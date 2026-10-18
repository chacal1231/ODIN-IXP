"""Read a bounded Graylog log sample; never execute operator-supplied shell or Lucene."""
import argparse
from datetime import datetime, timezone
import ipaddress
import json
import os
import re
import sys
import urllib.error

import read_api


class ContractError(ValueError):
    pass


EVENTS = {
    "all": None,
    "bgp": "arista_facility:BGP",
    "interface-down": "interface_state:down",
    "config": "arista_facility:SYS",
    "critical": "arista_severity:<4",
}
FIELDS = ("arista_event", "arista_facility", "arista_severity", "arista_mnemonic",
          "bgp_neighbor_ip", "bgp_vrf", "bgp_remote_asn", "bgp_state",
          "interface_name", "interface_state", "config_user", "message")


def utc(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None


def parameters(device, interface=None, neighbor=None, event="all", seconds=300, limit=20):
    allowed = {s.strip() for s in os.environ.get("GRAYLOG_ALLOWED_SOURCES", "").split(",") if s.strip()}
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", device) or device not in allowed:
        raise ValueError("Device not authorized")
    if type(seconds) is not int or not 1 <= seconds <= 86400:
        raise ValueError("Invalid range")
    if type(limit) is not int or not 1 <= limit <= 100 or event not in EVENTS:
        raise ValueError("Invalid limit or event")
    clauses = [f'source:"{device}"']
    if interface is not None:
        if not re.fullmatch(r"[A-Za-z0-9_./:-]{1,128}", interface):
            raise ValueError("Invalid interface")
        clauses.append(f'interface_name:"{interface}"')
    if neighbor is not None:
        clauses.append(f'bgp_neighbor_ip:"{ipaddress.ip_address(neighbor)}"')
    if EVENTS[event]:
        clauses.append(EVENTS[event])
    return {"query": " AND ".join(clauses), "range": seconds, "limit": limit,
            "sort": "timestamp:desc"}


def normalize(payload, device, limit, collected_at):
    if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
        raise ContractError("Expected legacy messages array")
    rows = payload["messages"]
    if len(rows) > limit:
        raise ContractError("Server exceeded limit")
    total = payload.get("total_results")
    if total is not None and (type(total) is not int or total < len(rows)):
        raise ContractError("Invalid total")
    warnings = []
    evidence = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("message"), dict):
            raise ContractError("Invalid message")
        message = row["message"]
        if message.get("source") != device:
            raise ContractError("Unexpected source; do not expose cross-scope records")
        observed = utc(message.get("timestamp"))
        if observed is None:
            warnings.append("missing_or_invalid_observed_at")
        index, record = row.get("index"), message.get("_id")
        reference = {"index": index, "id": record} if all(isinstance(v, str) and v for v in (index, record)) else None
        if reference is None:
            warnings.append("missing_raw_reference")
        evidence.append({"source": "graylog", "entity": {"device": device, "interface": message.get("interface_name")},
                         "observed_at": observed, "collected_at": collected_at,
                         "data": {k: message[k] for k in FIELDS if k in message}, "raw_reference": reference})
    if total is None:
        warnings.append("unknown_total_results")
    elif total > len(rows):
        warnings.append("sample_truncated")
    status = "partial" if warnings else ("ok" if rows else "empty")
    return {"schema_version": 1, "source": "graylog", "status": status,
            "collected_at": collected_at, "evidence": evidence,
            "coverage": {"returned": len(rows), "total_results": total, "limit": limit,
                         "sample_only": True}, "warnings": sorted(set(warnings))}


def query(device, interface=None, neighbor=None, event="all", seconds=300, limit=20):
    params = parameters(device, interface, neighbor, event, seconds, limit)
    payload = read_api.request("graylog", "search/universal/relative", params)
    collected = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result = normalize(payload, device, limit, collected)
    result["query"] = {"device": device, "interface": interface, "neighbor": neighbor,
                       "event": event, "range_seconds": seconds}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--interface")
    parser.add_argument("--neighbor")
    parser.add_argument("--event", choices=EVENTS, default="all")
    parser.add_argument("--seconds", type=int, default=300)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    try:
        result = query(args.device, args.interface, args.neighbor, args.event, args.seconds, args.limit)
    except urllib.error.HTTPError as exc:
        code = "authentication" if exc.code in (401, 403) else "rate_limited" if exc.code == 429 else "http_error"
        result = {"source": "graylog", "status": "error", "error": code, "http_status": exc.code}
        exc.close()
    except (TimeoutError, urllib.error.URLError):
        result = {"source": "graylog", "status": "error", "error": "connection_or_timeout"}
    except (ContractError, read_api.ResponseError, json.JSONDecodeError):
        result = {"source": "graylog", "status": "error", "error": "invalid_response"}
    except ValueError:
        result = {"source": "graylog", "status": "error", "error": "invalid_configuration_or_filter"}
    except Exception:
        result = {"source": "graylog", "status": "error", "error": "query_failed"}
    # One JSON result for automation. Never include exception text, URLs, headers or remote error bodies.
    try:
        output = json.dumps(result, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError):
        result = {"source": "graylog", "status": "error", "error": "invalid_response"}
        output = json.dumps(result)
    print(output)
    return 1 if result["status"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
