"""Bounded GET client. Credentials come from environment, never command arguments."""
import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(source, path, params):
    prefix = source.upper()
    base = os.environ.get(prefix + "_URL", "").rstrip("/")
    token = os.environ.get(prefix + "_TOKEN", "")
    parsed = urllib.parse.urlsplit(base)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Configure una URL HTTPS sin credenciales, query ni fragmento")
    if not token or re.search(r"[\s\x00-\x1f\x7f]", token):
        raise ValueError("Token ausente o inválido")
    # Paths are relative to the configured API root; query values are encoded separately.
    if not re.fullmatch(r"[A-Za-z0-9_.:/-]+", path) or ".." in path or path.startswith("/"):
        raise ValueError("Ruta inválida")
    if source == "graylog" and path != "search/universal/relative":
        raise ValueError("Ruta Graylog no permitida")
    if source == "librenms" and path.split("/")[0] not in {
        "devices", "ports", "bgp", "routing", "alerts", "logs"
    }:
        raise ValueError("Ruta LibreNMS no permitida")
    headers = {"Accept": "application/json", "X-Requested-By": "ODIN"}
    if source == "graylog":
        encoded = base64.b64encode((token + ":token").encode()).decode()
        headers["Authorization"] = "Basic " + encoded
    else:
        headers["X-Auth-Token"] = token
    url = base + "/" + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers, method="GET")
    # Ignore ambient proxies; do not forward credentials to redirect destinations.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(req, timeout=20) as response:
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ValueError("Respuesta excede el límite; acote la consulta")
    return json.loads(body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", choices=["graylog", "librenms"])
    parser.add_argument("path")
    parser.add_argument("--param", action="append", default=[])
    args = parser.parse_args()
    try:
        params = {}
        for item in args.param:
            key, separator, value = item.partition("=")
            if not separator or not re.fullmatch(r"[A-Za-z0-9_]+", key) or len(value) > 4096:
                raise ValueError("Parámetro inválido")
            params[key] = value
        if args.source == "graylog":
            if not 1 <= int(params.get("range", "300")) <= 86400:
                raise ValueError("range debe estar entre 1 y 86400 segundos")
            if not 1 <= int(params.get("limit", "20")) <= 100:
                raise ValueError("limit debe estar entre 1 y 100")
            params.setdefault("range", "300")
            params.setdefault("limit", "20")
        result = request(args.source, args.path, params)
        print(json.dumps(result, ensure_ascii=False))
    except urllib.error.HTTPError as exc:
        print(json.dumps({"status": "error", "http_status": exc.code}), file=sys.stderr)
        exc.close()
        return 1
    except Exception:
        # Do not emit remote bodies, request headers, token values or exception URLs.
        print('{"status":"error","message":"Consulta fallida; revise configuración, conectividad y límites"}', file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
