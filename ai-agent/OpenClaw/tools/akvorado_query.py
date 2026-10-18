"""Bounded Akvorado/ClickHouse traffic queries from closed SQL templates; never operator SQL."""
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


EXPORTER = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
INTERFACE = re.compile(r"[A-Za-z0-9_./:-]{1,128}")
# Operator-facing dimension -> ClickHouse column. Only these identifiers ever reach the SQL text.
DIMENSIONS = {
    "exporter": "ExporterName", "src-as": "SrcAS", "dst-as": "DstAS",
    "in-interface": "InIfName", "out-interface": "OutIfName",
    "in-provider": "InIfProvider", "out-provider": "OutIfProvider",
    "in-connectivity": "InIfConnectivity", "out-connectivity": "OutIfConnectivity",
    "in-boundary": "InIfBoundary", "out-boundary": "OutIfBoundary",
    "dst-country": "DstCountry", "proto": "Proto", "etype": "EType",
}
IP_DIMENSIONS = {"dst-as": "DstAS", "src-as": "SrcAS", "dst-port": "DstPort", "src-port": "SrcPort",
                 "proto": "Proto", "exporter": "ExporterName"}
MAX_MINUTES = 90 * 24 * 60
MAX_IP_MINUTES = 60
VOLUME = "sum(Bytes * SamplingRate) AS bytes, sum(Packets * SamplingRate) AS packets"
# Epoch seconds: independent of the ClickHouse server time zone.
TIME_FILTER = "TimeReceived >= toDateTime({start:UInt32}) AND TimeReceived < toDateTime({end:UInt32})"


def now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


def allowed_exporters():
    values = {v.strip() for v in os.environ.get("AKVORADO_ALLOWED_EXPORTERS", "").split(",") if v.strip()}
    if not values:
        raise ValueError("AKVORADO_ALLOWED_EXPORTERS no configurado")
    return None if values == {"*"} else values


def exporter(value, allowed, required):
    if value is None:
        if required or allowed is not None:
            # Without a global grant, every traffic query must be scoped to one authorized exporter.
            raise ValueError("--exporter requerido")
        return None
    if not EXPORTER.fullmatch(value) or (allowed is not None and value not in allowed):
        raise ValueError("Exporter not authorized")
    return value


def table_for(minutes):
    # Resolution tables as documented in the Akvorado Skill; retention not yet verified.
    if minutes <= 60:
        return "flows_1m0s", 60
    if minutes <= 1440:
        return "flows_5m0s", 300
    return "flows_1h0m0s", 3600


def window(minutes):
    if type(minutes) is not int or not 1 <= minutes <= MAX_MINUTES:
        raise ValueError("--minutes fuera de rango")
    end = now()
    return end - timedelta(minutes=minutes), end


def run_sql(sql, params, limit):
    """Execute a template with ClickHouse query parameters; detect truncation via limit + 1."""
    query = {"query": sql + " FORMAT JSON", "param_limit": str(limit + 1)}
    query.update({f"param_{k}": str(v) for k, v in params.items()})
    payload = read_api.request("akvorado", "", query)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ContractError("Se esperaba JSON de ClickHouse con 'data'")
    rows = payload["data"]
    if not all(isinstance(r, dict) for r in rows):
        raise ContractError("Filas inválidas")
    return rows[:limit], len(rows) > limit


def count(value):
    # ClickHouse quotes 64-bit integers in JSON by default.
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ContractError("Contador inválido")


def result(operation, query, items, truncated, warnings=(), info=()):
    warnings = set(warnings) | ({"sample_truncated"} if truncated else set())
    status = "partial" if warnings else ("ok" if items else "empty")
    return {"schema_version": 1, "source": "akvorado", "operation": operation, "status": status,
            "collected_at": iso(now()), "query": query, "evidence": items,
            "coverage": {"returned": len(items), "truncated": truncated},
            "warnings": sorted(warnings | set(info))}


def evidence(entity, data, units, start=None, end=None):
    return {"source": "akvorado", "entity": entity, "observed_at": None,
            "window": {"from": iso(start), "to": iso(end)} if start else None,
            "collected_at": iso(now()), "data": data, "units": units, "raw_reference": None}


def volume(row, seconds):
    bytes_, packets = count(row.get("bytes")), count(row.get("packets"))
    return {"bytes": bytes_, "packets": packets, "avg_bps": round(bytes_ * 8 / seconds, 1)}


VOLUME_UNITS = {"bytes": "bytes", "packets": "packets", "avg_bps": "bit/s"}
# Aggregated buckets are aligned to the table resolution and the newest one may still be filling.
TRAFFIC_INFO = ("window_edges_approximate", "schema_unverified", "ingestion_lag_unknown")


def op_exporters(args, allowed):
    rows, truncated = run_sql("SELECT DISTINCT ExporterName FROM exporters ORDER BY ExporterName "
                              "LIMIT {limit:UInt32}", {}, args.limit)
    items = [evidence({"exporter": r.get("ExporterName")}, {"exporter": r.get("ExporterName")}, {})
             for r in rows if allowed is None or r.get("ExporterName") in allowed]
    filtered = len(rows) - len(items)
    return result("exporters", {}, items, truncated, info=("out_of_scope_filtered",) if filtered else ())


def op_interfaces(args, allowed):
    name = exporter(args.exporter, allowed, required=True)
    sql = ("SELECT DISTINCT IfName, IfDescription, IfConnectivity, IfProvider, IfBoundary, IfSpeed "
           "FROM exporters WHERE ExporterName = {exporter:String} AND IfName != '' "
           "ORDER BY IfName LIMIT {limit:UInt32}")
    rows, truncated = run_sql(sql, {"exporter": name}, args.limit)
    items = [evidence({"exporter": name, "interface": r.get("IfName")}, r, {"IfSpeed": "unverified"})
             for r in rows]
    return result("interfaces", {"exporter": name}, items, truncated, info=("schema_unverified",))


def filters(args, allowed, clauses, params):
    name = exporter(args.exporter, allowed, required=False)
    if name is not None:
        clauses.append("ExporterName = {exporter:String}")
        params["exporter"] = name
    for flag, column in (("in_interface", "InIfName"), ("out_interface", "OutIfName")):
        value = getattr(args, flag, None)
        if value is not None:
            if name is None or not INTERFACE.fullmatch(value):
                raise ValueError("Interfaz inválida o sin --exporter")
            clauses.append(f"{column} = {{{flag}:String}}")
            params[flag] = value
    for flag, column in (("src_asn", "SrcAS"), ("dst_asn", "DstAS")):
        value = getattr(args, flag, None)
        if value is not None:
            if not 0 <= value <= 4294967295:
                raise ValueError("ASN inválido")
            clauses.append(f"{column} = {{{flag}:UInt32}}")
            params[flag] = value
    if getattr(args, "external", False):
        clauses.append("InIfBoundary = 'external'")
    return name


def op_top(args, allowed):
    start, end = window(args.minutes)
    table, _ = table_for(args.minutes)
    clauses, params = [TIME_FILTER], {}
    params.update(start=int(start.timestamp()), end=int(end.timestamp()))
    name = filters(args, allowed, clauses, params)
    column = DIMENSIONS[args.by]
    sql = (f"SELECT {column} AS key, {VOLUME} FROM {table} WHERE {' AND '.join(clauses)} "
           "GROUP BY key ORDER BY bytes DESC LIMIT {limit:UInt32}")
    rows, truncated = run_sql(sql, params, args.limit)
    seconds = args.minutes * 60
    items = [evidence({"exporter": name, args.by: r.get("key")}, {args.by: r.get("key"), **volume(r, seconds)},
                      VOLUME_UNITS, start, end) for r in rows]
    query = {"by": args.by, "minutes": args.minutes, "table": table, "exporter": name,
             "in_interface": args.in_interface, "out_interface": args.out_interface,
             "src_asn": args.src_asn, "dst_asn": args.dst_asn, "external": args.external}
    return result("top", query, items, truncated, info=TRAFFIC_INFO)


def op_timeseries(args, allowed):
    start, end = window(args.minutes)
    table, resolution = table_for(args.minutes)
    step = max(args.step, resolution)
    if step % resolution or (args.minutes * 60) // step > 1000:
        raise ValueError("--step debe ser múltiplo de la resolución y dar como mucho 1000 puntos")
    clauses, params = [TIME_FILTER], {"step": step}
    params.update(start=int(start.timestamp()), end=int(end.timestamp()))
    name = filters(args, allowed, clauses, params)
    sql = ("SELECT toUnixTimestamp(toStartOfInterval(TimeReceived, toIntervalSecond({step:UInt32}))) AS t, "
           f"{VOLUME} FROM {table} WHERE {' AND '.join(clauses)} GROUP BY t ORDER BY t LIMIT {{limit:UInt32}}")
    rows, truncated = run_sql(sql, params, args.limit)
    items = []
    for r in rows:
        bucket = datetime.fromtimestamp(count(r.get("t")), timezone.utc)
        items.append(evidence({"exporter": name, "interface": args.in_interface or args.out_interface},
                              volume(r, step), VOLUME_UNITS, bucket, bucket + timedelta(seconds=step)))
    query = {"minutes": args.minutes, "step_seconds": step, "table": table, "exporter": name,
             "in_interface": args.in_interface, "out_interface": args.out_interface}
    # Buckets without flows are absent from the answer, not zero.
    return result("timeseries", query, items, truncated,
                  info=TRAFFIC_INFO + ("missing_buckets_mean_no_flows_recorded",))


def op_ip(args, allowed):
    if not 1 <= args.minutes <= MAX_IP_MINUTES:
        raise ValueError("--minutes para consultas por IP: 1–60")
    address = ipaddress.ip_address(args.address)
    mapped = f"::ffff:{address}" if address.version == 4 else str(address)
    start, end = window(args.minutes)
    column = "SrcAddr" if args.role == "source" else "DstAddr"
    clauses = [f"{column} = toIPv6({{address:String}})", TIME_FILTER]
    params = {"address": mapped, "start": int(start.timestamp()), "end": int(end.timestamp())}
    name = filters(args, allowed, clauses, params)
    by = IP_DIMENSIONS[args.by]
    sql = (f"SELECT {by} AS key, {VOLUME} FROM flows WHERE {' AND '.join(clauses)} "
           "GROUP BY key ORDER BY bytes DESC LIMIT {limit:UInt32}")
    rows, truncated = run_sql(sql, params, args.limit)
    items = [evidence({"exporter": name, "address": str(address), "role": args.role, args.by: r.get("key")},
                      {args.by: r.get("key"), **volume(r, args.minutes * 60)}, VOLUME_UNITS, start, end)
             for r in rows]
    query = {"address": str(address), "role": args.role, "by": args.by, "minutes": args.minutes, "exporter": name}
    return result("ip", query, items, truncated, info=TRAFFIC_INFO)


OPERATIONS = {"exporters": op_exporters, "interfaces": op_interfaces, "top": op_top,
              "timeseries": op_timeseries, "ip": op_ip}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="operation", required=True)

    def add(name, help_text, traffic=False):
        s = sub.add_parser(name, help=help_text)
        s.add_argument("--limit", type=int, default=20)
        if traffic:
            s.add_argument("--exporter")
            s.add_argument("--in-interface")
            s.add_argument("--out-interface")
            s.add_argument("--src-asn", type=int)
            s.add_argument("--dst-asn", type=int)
            s.add_argument("--external", action="store_true", help="Solo entrada por interfaces externas")
            s.add_argument("--minutes", type=int, default=60)
        return s

    add("exporters", "Exportadores (PEs) autorizados")
    add("interfaces", "Interfaces de un exportador").add_argument("--exporter", required=True)
    add("top", "Top por dimensión", traffic=True).add_argument("--by", choices=DIMENSIONS, required=True)
    add("timeseries", "Serie temporal", traffic=True).add_argument("--step", type=int, default=300)
    s = add("ip", "Tráfico de una IP (tabla flows, máx. 60 min)", traffic=True)
    s.add_argument("--address", required=True)
    s.add_argument("--role", choices=("source", "destination"), required=True)
    s.add_argument("--by", choices=IP_DIMENSIONS, required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if not 1 <= args.limit <= 1000:
            raise ValueError("limit debe estar entre 1 y 1000")
        out = OPERATIONS[args.operation](args, allowed_exporters())
    except urllib.error.HTTPError as exc:
        code = "authentication" if exc.code in (401, 403) else "rate_limited" if exc.code == 429 else \
            "query_rejected" if exc.code in (400, 404) else "http_error"
        out = {"source": "akvorado", "status": "error", "error": code, "http_status": exc.code}
        exc.close()
    except (TimeoutError, urllib.error.URLError):
        out = {"source": "akvorado", "status": "error", "error": "connection_or_timeout"}
    except (ContractError, read_api.ResponseError, json.JSONDecodeError):
        out = {"source": "akvorado", "status": "error", "error": "invalid_response"}
    except ValueError:
        out = {"source": "akvorado", "status": "error", "error": "invalid_configuration_or_filter"}
    except Exception:
        out = {"source": "akvorado", "status": "error", "error": "query_failed"}
    # One JSON result for automation. Never include exception text, URLs, headers, SQL or remote bodies.
    try:
        text = json.dumps(out, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError):
        out = {"source": "akvorado", "status": "error", "error": "invalid_response"}
        text = json.dumps(out)
    print(text)
    return 1 if out["status"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
