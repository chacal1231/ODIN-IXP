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


class ResponseError(ValueError):
    """The remote answered, but the body is unusable (too large or not decodable)."""


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
    if source == "akvorado":
        # ClickHouse HTTP interface: queries go in params, only to the root path.
        if path != "":
            raise ValueError("Ruta ClickHouse no permitida")
    elif not re.fullmatch(r"[A-Za-z0-9_.:/-]+", path) or ".." in path or path.startswith("/"):
        raise ValueError("Ruta inválida")
    if source == "ixpmanager" and path != "member-export/ixf/1.0":
        raise ValueError("Ruta IXP Manager no permitida")
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
    elif source == "akvorado":
        user = os.environ.get("AKVORADO_USER", "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", user):
            raise ValueError("AKVORADO_USER ausente o inválido")
        headers["X-ClickHouse-User"], headers["X-ClickHouse-Key"] = user, token
    elif source == "ixpmanager":
        headers["X-IXP-Manager-API-Key"] = token
    else:
        headers["X-Auth-Token"] = token
    url = base + "/" + path + "?" + urllib.parse.urlencode(params)
    # GET makes ClickHouse treat the request as readonly; the account must also be SELECT-only.
    req = urllib.request.Request(url, headers=headers, method="GET")
    # Ignore ambient proxies; do not forward credentials to redirect destinations.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    # The IX-F export lists every member in one document; other sources answer bounded queries.
    max_bytes = 10_000_000 if source == "ixpmanager" else 2_000_000
    with opener.open(req, timeout=20) as response:
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ResponseError("Respuesta excede el límite; acote la consulta")
    try:
        return json.loads(body)
    except UnicodeDecodeError:
        raise ResponseError("Respuesta no decodificable") from None


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
