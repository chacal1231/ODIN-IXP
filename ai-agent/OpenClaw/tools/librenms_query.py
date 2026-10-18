"""Read bounded LibreNMS state through enumerated operations; never free API paths or parameters."""
import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
import re
import sys
import urllib.error

import read_api


class ContractError(ValueError):
    pass


HOST = re.compile(r"[A-Za-z0-9_.:-]{1,253}")
NAME = re.compile(r"[A-Za-z0-9_. /:-]{1,128}")
INTERFACE = re.compile(r"[A-Za-z0-9_./:-]{1,128}")
PORT_COLUMNS = ("port_id", "device_id", "ifName", "ifAlias", "ifOperStatus", "ifAdminStatus", "ifSpeed",
                "ifInOctets_rate", "ifOutOctets_rate", "ifInErrors_rate", "ifOutErrors_rate")
DEVICE_FIELDS = ("device_id", "hostname", "display", "sysName", "status", "status_reason", "uptime",
                 "hardware", "version", "os", "last_polled")
BGP_FIELDS = ("device_id", "bgpPeerIdentifier", "bgpPeerRemoteAddr", "bgpPeerRemoteAs", "bgpPeerState",
              "bgpPeerAdminStatus", "bgpPeerDescr", "bgpPeerFsmEstablishedTime", "bgpLocalAddr")
SENSOR_CLASSES = {"temperature": "°C", "dbm": "dBm", "voltage": "V", "current": "A", "power": "W",
                  "fanspeed": "rpm", "humidity": "%", "state": None}
UNITS = {"ifSpeed": "bit/s", "ifInOctets_rate": "bytes/s", "ifOutOctets_rate": "bytes/s",
         "ifInErrors_rate": "errors/s", "ifOutErrors_rate": "errors/s", "uptime": "s",
         "bgpPeerFsmEstablishedTime": "s"}
ALERT_STATES = {"ok": 0, "active": 1, "acknowledged": 2}
BGP_STATES = ("idle", "connect", "active", "opensent", "openconfirm", "established")


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def allowed_devices():
    raw = os.environ.get("LIBRENMS_ALLOWED_DEVICES", "")
    values = {v.strip() for v in raw.split(",") if v.strip()}
    if not values:
        raise ValueError("LIBRENMS_ALLOWED_DEVICES no configurado")
    return None if values == {"*"} else values


def source_time(value):
    """LibreNMS prints local server time; convert only when its zone is configured."""
    zone = os.environ.get("LIBRENMS_TIMEZONE")
    if not isinstance(value, str) or not zone:
        return None
    offset = re.fullmatch(r"([+-])(\d{2}):(\d{2})", zone)
    if offset:
        # Fixed offset (e.g. -05:00): valid for zones without DST and needs no tzdata.
        sign = 1 if offset.group(1) == "+" else -1
        tz = timezone(sign * timedelta(hours=int(offset.group(2)), minutes=int(offset.group(3))))
    else:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            tz = ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("LIBRENMS_TIMEZONE inválida") from None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def host(value):
    if not isinstance(value, str) or not HOST.fullmatch(value) or ".." in value:
        raise ValueError("Hostname inválido")
    return value


def fetch(path, params, key):
    payload = read_api.request("librenms", path, params)
    if not isinstance(payload, dict) or payload.get("status") not in (None, "ok"):
        raise ContractError("LibreNMS status no ok")
    rows = payload.get(key)
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ContractError(f"Se esperaba lista '{key}'")
    return rows


class Scope:
    """Maps LibreNMS device_id to hostname and enforces LIBRENMS_ALLOWED_DEVICES."""

    def __init__(self):
        self.allowed = allowed_devices()
        self._devices = None

    def devices(self):
        if self._devices is None:
            self._devices = {d.get("device_id"): d for d in fetch("devices", {}, "devices")}
        return self._devices

    def check(self, hostname):
        if self.allowed is not None and hostname not in self.allowed:
            raise ValueError("Device not authorized")
        return hostname

    def device_id(self, hostname):
        matches = [i for i, d in self.devices().items() if d.get("hostname") == hostname]
        if len(matches) != 1:
            raise ContractError("Hostname no encontrado o ambiguo en LibreNMS")
        return matches[0]

    def hostname_of(self, device_id):
        device = self.devices().get(device_id)
        return device.get("hostname") if device else None

    def permits(self, device_id):
        hostname = self.hostname_of(device_id)
        return hostname is not None and (self.allowed is None or hostname in self.allowed)


def evidence(entity, data, observed=None, raw_reference=None, units=None):
    return {"source": "librenms", "entity": entity, "observed_at": observed, "collected_at": None,
            "data": data, "units": units or {k: UNITS[k] for k in data if k in UNITS},
            "raw_reference": raw_reference}


def result(operation, query, items, limit, warnings=(), filtered=0, timed=False, info=()):
    """`warnings` affect coverage (status partial); `info` qualifies the data without doing so."""
    warnings = set(warnings)
    if len(items) > limit:
        warnings.add("sample_truncated")
    if filtered:
        warnings.add("out_of_scope_filtered")
    collected = now()
    shown = items[:limit]
    for item in shown:
        item["collected_at"] = collected
        if timed and item["observed_at"] is None:
            warnings.add("missing_or_unconverted_observed_at")
    if not timed:
        # State snapshots: LibreNMS gives no per-value observation time. Not a coverage problem.
        warnings.add("snapshot_without_observed_at")
    coverage_warnings = warnings - {"snapshot_without_observed_at", "out_of_scope_filtered"}
    status = "partial" if coverage_warnings else ("ok" if shown else "empty")
    warnings |= set(info)
    return {"schema_version": 1, "source": "librenms", "operation": operation, "status": status,
            "collected_at": collected, "query": query, "evidence": shown,
            "coverage": {"returned": len(shown), "available": len(items), "limit": limit,
                         "out_of_scope_filtered": filtered, "sample_only": len(items) > limit},
            "warnings": sorted(warnings)}


def device_entity(d):
    return {"device": d.get("hostname"), "display": d.get("display"), "device_id": d.get("device_id")}


def op_resolve(scope, args):
    name = args.name
    if not NAME.fullmatch(name):
        raise ValueError("Nombre inválido")
    wanted = name.casefold()
    items, filtered = [], 0
    for d in scope.devices().values():
        names = {str(d.get(k, "")).casefold() for k in ("hostname", "display", "sysName")}
        if wanted in names:
            if scope.permits(d.get("device_id")):
                items.append(evidence(device_entity(d), {k: d[k] for k in DEVICE_FIELDS if k in d},
                                      raw_reference={"device_id": d.get("device_id")}))
            else:
                filtered += 1
    warnings = ["ambiguous_name"] if len(items) > 1 else []
    return result("resolve", {"name": name}, items, args.limit, warnings, filtered)


def op_devices(scope, args):
    items, filtered = [], 0
    for d in scope.devices().values():
        if args.state != "all" and (d.get("status") in (1, True, "1")) != (args.state == "up"):
            continue
        if not scope.permits(d.get("device_id")):
            filtered += 1
            continue
        items.append(evidence(device_entity(d), {k: d[k] for k in DEVICE_FIELDS if k in d},
                              raw_reference={"device_id": d.get("device_id")}))
    return result("devices", {"state": args.state}, items, args.limit, (), filtered)


def op_ports(scope, args):
    hostname = scope.check(host(args.device))
    device_id = scope.device_id(hostname)
    if args.interface is not None and not INTERFACE.fullmatch(args.interface):
        raise ValueError("Interfaz inválida")
    rows = fetch(f"devices/{hostname}/ports", {"columns": ",".join(PORT_COLUMNS)}, "ports")
    items = []
    for p in rows:
        if p.get("device_id") not in (None, device_id):
            raise ContractError("Puerto de otro equipo; no exponer registros fuera de ámbito")
        if args.interface is not None and p.get("ifName") != args.interface:
            continue
        if args.down and not (p.get("ifAdminStatus") == "up" and p.get("ifOperStatus") != "up"):
            continue
        items.append(evidence({"device": hostname, "interface": p.get("ifName")},
                              {k: p[k] for k in PORT_COLUMNS if k in p},
                              raw_reference={"port_id": p.get("port_id")}))
    query = {"device": hostname, "interface": args.interface, "down": args.down}
    return result("ports", query, items, args.limit)


def op_bgp(scope, args):
    params = {}
    if args.device is not None:
        params["hostname"] = scope.check(host(args.device))
    if args.state is not None:
        params["bgp_state"] = args.state
    if args.remote_asn is not None:
        if not 1 <= args.remote_asn <= 4294967295:
            raise ValueError("ASN inválido")
        params["remote_asn"] = str(args.remote_asn)
    if args.remote_address is not None:
        params["remote_address"] = str(ipaddress.ip_address(args.remote_address))
    items, filtered = [], 0
    for s in fetch("bgp", params, "bgp_sessions"):
        if not scope.permits(s.get("device_id")):
            filtered += 1
            continue
        hostname = scope.hostname_of(s.get("device_id"))
        if args.device is not None and hostname != params["hostname"]:
            raise ContractError("Sesión de otro equipo; no exponer registros fuera de ámbito")
        # Server-side filters are re-checked so an ignored parameter cannot widen the answer.
        if args.state is not None and str(s.get("bgpPeerState", "")).lower() != args.state:
            continue
        if args.remote_asn is not None and str(s.get("bgpPeerRemoteAs")) != params["remote_asn"]:
            continue
        if args.remote_address is not None and s.get("bgpPeerRemoteAddr") != params["remote_address"]:
            continue
        items.append(evidence({"device": hostname, "peer": s.get("bgpPeerRemoteAddr"),
                               "remote_asn": s.get("bgpPeerRemoteAs")},
                              {k: s[k] for k in BGP_FIELDS if k in s},
                              raw_reference={"bgpPeer_id": s.get("bgpPeer_id")}))
    query = {"device": args.device, "state": args.state, "remote_asn": args.remote_asn,
             "remote_address": params.get("remote_address")}
    return result("bgp", query, items, args.limit, (), filtered)


def op_alerts(scope, args):
    params = {"state": str(ALERT_STATES[args.state])}
    if args.severity is not None:
        params["severity"] = args.severity
    items, filtered, warnings = [], 0, set()
    for a in fetch("alerts", params, "alerts"):
        if not scope.permits(a.get("device_id")):
            filtered += 1
            continue
        if str(a.get("state")) != params["state"] or (args.severity and a.get("severity") != args.severity):
            continue
        fields = ("id", "device_id", "rule_id", "state", "severity", "timestamp", "name", "rule")
        items.append(evidence({"device": scope.hostname_of(a.get("device_id"))},
                              {k: a[k] for k in fields if k in a},
                              observed=source_time(a.get("timestamp")), raw_reference={"alert_id": a.get("id")}))
    return result("alerts", {"state": args.state, "severity": args.severity}, items, args.limit,
                  warnings, filtered, timed=True)


def op_sensors(scope, args):
    hostname = scope.check(host(args.device))
    path = f"devices/{hostname}/health/device_{args.sensor_class}"
    if args.sensor_id is not None:
        if args.sensor_id < 1:
            raise ValueError("sensor_id inválido")
        path += f"/{args.sensor_id}"
    unit = SENSOR_CLASSES[args.sensor_class]
    items = []
    fields = ("sensor_id", "sensor_class", "sensor_descr", "sensor_current", "sensor_limit",
              "sensor_limit_warn", "sensor_limit_low", "sensor_limit_low_warn", "sensor_type", "desc")
    for g in fetch(path, {}, "graphs"):
        data = {k: g[k] for k in fields if k in g}
        units = {k: unit for k in data if unit and (k == "sensor_current" or k.startswith("sensor_limit"))}
        items.append(evidence({"device": hostname, "sensor": g.get("sensor_descr") or g.get("desc")}, data,
                              raw_reference={"sensor_id": g.get("sensor_id")}, units=units))
    # LibreNMS may fill limits itself; they are not proof of vendor DOM thresholds.
    info = ["limits_origin_unverified"] if args.sensor_class == "dbm" else []
    query = {"device": hostname, "class": args.sensor_class, "sensor_id": args.sensor_id}
    return result("sensors", query, items, args.limit, info=info)


MAX_OPTIC_SENSORS = 64
RX = re.compile(r"\b(rx|receive[rd]?|input)\b", re.I)
TX = re.compile(r"\b(tx|transmit(ter)?|output)\b", re.I)


def number(value):
    """Finite float from int/float/numeric string; None otherwise (never 0 by default)."""
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and parsed not in (float("inf"), float("-inf")) else None


def optical_margins(current, low, high, low_warn=None, high_warn=None):
    """Margins in dB from a dBm reading and dBm limits. Missing limits stay missing."""
    out = {"lower_margin_db": None, "upper_margin_db": None, "state": None, "notes": []}
    if current is None:
        out["state"] = "no_reading"
        return out
    if low is not None and high is not None and low >= high:
        out["state"] = "limits_incompatible"
        return out
    if low is not None:
        out["lower_margin_db"] = round(current - low, 2)
    if high is not None:
        out["upper_margin_db"] = round(high - current, 2)
    if low is None and high is None:
        out["state"] = "limits_missing"
    elif low is not None and current < low:
        out["state"] = "below_low"
    elif high is not None and current > high:
        out["state"] = "above_high"
    elif low_warn is not None and current < low_warn:
        out["state"] = "warn_low"
    elif high_warn is not None and current > high_warn:
        out["state"] = "warn_high"
    else:
        out["state"] = "within_limits"
    if low is None and high is not None:
        out["notes"].append("lower_limit_missing")
    if high is None and low is not None:
        out["notes"].append("upper_limit_missing")
    return out


def op_optics(scope, args):
    hostname = scope.check(host(args.device))
    if args.interface is not None and not INTERFACE.fullmatch(args.interface):
        raise ValueError("Interfaz inválida")
    base = f"devices/{hostname}/health/device_dbm"
    sensors = fetch(base, {}, "graphs")
    warnings, info = set(), {"limits_origin_unverified"}
    if args.interface is not None:
        pattern = re.compile(rf"(?<![A-Za-z0-9/]){re.escape(args.interface)}(?![0-9/])", re.I)
        sensors = [s for s in sensors if pattern.search(str(s.get("sensor_descr") or s.get("desc") or ""))]
    if len(sensors) > MAX_OPTIC_SENSORS:
        sensors = sensors[:MAX_OPTIC_SENSORS]
        warnings.add("sensor_list_truncated")
    items = []
    for s in sensors:
        if "sensor_current" not in s:
            # The type listing may carry only ids and descriptions; read each sensor explicitly.
            sensor_id = s.get("sensor_id")
            if type(sensor_id) is not int or sensor_id < 1:
                warnings.add("sensor_without_id")
                continue
            detail = fetch(f"{base}/{sensor_id}", {}, "graphs")
            if len(detail) != 1:
                raise ContractError("Se esperaba un sensor")
            s = {**s, **detail[0]}
        descr = str(s.get("sensor_descr") or s.get("desc") or "")
        values = {k: number(s.get(k)) for k in ("sensor_current", "sensor_limit_low", "sensor_limit",
                                               "sensor_limit_low_warn", "sensor_limit_warn")}
        margins = optical_margins(values["sensor_current"], values["sensor_limit_low"], values["sensor_limit"],
                                  values["sensor_limit_low_warn"], values["sensor_limit_warn"])
        direction = "rx" if RX.search(descr) else "tx" if TX.search(descr) else "unknown"
        data = {"sensor_descr": descr, "direction": direction, "current_dbm": values["sensor_current"],
                "limit_low_dbm": values["sensor_limit_low"], "limit_high_dbm": values["sensor_limit"],
                "warn_low_dbm": values["sensor_limit_low_warn"], "warn_high_dbm": values["sensor_limit_warn"],
                **margins}
        units = {k: "dBm" for k in data if k.endswith("_dbm")} | {k: "dB" for k in data if k.endswith("_db")}
        items.append(evidence({"device": hostname, "sensor": descr, "direction": direction}, data,
                              raw_reference={"sensor_id": s.get("sensor_id")}, units=units))
    rank = {"below_low": 0, "above_high": 0, "warn_low": 1, "warn_high": 1, "within_limits": 2,
            "limits_missing": 3, "limits_incompatible": 3, "no_reading": 3}

    def risk(item):
        d = item["data"]
        margins = [m for m in (d["lower_margin_db"], d["upper_margin_db"]) if m is not None]
        return (rank[d["state"]], min(margins) if margins else float("inf"))

    items.sort(key=risk)
    if any(i["data"]["state"] in ("limits_missing", "limits_incompatible", "no_reading") for i in items):
        info.add("sensors_without_usable_limits")
    if any(i["data"]["direction"] == "unknown" for i in items):
        info.add("direction_unresolved")
    query = {"device": hostname, "interface": args.interface}
    return result("optics", query, items, args.limit, warnings, info=info)


def op_eventlog(scope, args):
    hostname = scope.check(host(args.device))
    rows = fetch(f"logs/eventlog/{hostname}", {"limit": str(args.limit + 1)}, "logs")
    items = []
    fields = ("event_id", "datetime", "type", "message", "severity", "reference")
    for e in rows:
        items.append(evidence({"device": hostname}, {k: e[k] for k in fields if k in e},
                              observed=source_time(e.get("datetime")), raw_reference={"event_id": e.get("event_id")}))
    return result("eventlog", {"device": hostname}, items, args.limit, (), 0, timed=True)


OPERATIONS = {"resolve": op_resolve, "devices": op_devices, "ports": op_ports, "bgp": op_bgp,
              "alerts": op_alerts, "sensors": op_sensors, "optics": op_optics, "eventlog": op_eventlog}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="operation", required=True)

    def add(name, help_text):
        s = sub.add_parser(name, help=help_text)
        s.add_argument("--limit", type=int, default=50)
        return s

    add("resolve", "Nombre amigable/sysName/hostname -> hostname").add_argument("--name", required=True)
    add("devices", "Equipos autorizados").add_argument("--state", choices=("all", "up", "down"), default="all")
    s = add("ports", "Interfaces de un equipo")
    s.add_argument("--device", required=True)
    s.add_argument("--interface")
    s.add_argument("--down", action="store_true", help="Solo admin up y oper no up")
    s = add("bgp", "Sesiones BGP")
    s.add_argument("--device")
    s.add_argument("--state", choices=BGP_STATES)
    s.add_argument("--remote-asn", type=int)
    s.add_argument("--remote-address")
    s = add("alerts", "Alertas")
    s.add_argument("--state", choices=ALERT_STATES, default="active")
    s.add_argument("--severity", choices=("ok", "warning", "critical"))
    s = add("sensors", "Sensores de un equipo")
    s.add_argument("--device", required=True)
    s.add_argument("--class", dest="sensor_class", choices=SENSOR_CLASSES, required=True)
    s.add_argument("--sensor-id", type=int)
    s = add("optics", "Potencia óptica con márgenes en dB, ordenada por riesgo")
    s.add_argument("--device", required=True)
    s.add_argument("--interface")
    s = add("eventlog", "Eventlog de un equipo")
    s.add_argument("--device", required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if not 1 <= args.limit <= 500:
            raise ValueError("limit debe estar entre 1 y 500")
        out = OPERATIONS[args.operation](Scope(), args)
    except urllib.error.HTTPError as exc:
        code = "authentication" if exc.code in (401, 403) else "rate_limited" if exc.code == 429 else \
            "not_found" if exc.code == 404 else "http_error"
        out = {"source": "librenms", "status": "error", "error": code, "http_status": exc.code}
        exc.close()
    except (TimeoutError, urllib.error.URLError):
        out = {"source": "librenms", "status": "error", "error": "connection_or_timeout"}
    except (ContractError, read_api.ResponseError, json.JSONDecodeError):
        out = {"source": "librenms", "status": "error", "error": "invalid_response"}
    except ValueError:
        out = {"source": "librenms", "status": "error", "error": "invalid_configuration_or_filter"}
    except Exception:
        out = {"source": "librenms", "status": "error", "error": "query_failed"}
    # One JSON result for automation. Never include exception text, URLs, headers or remote bodies.
    try:
        text = json.dumps(out, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError):
        out = {"source": "librenms", "status": "error", "error": "invalid_response"}
        text = json.dumps(out)
    print(text)
    return 1 if out["status"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
