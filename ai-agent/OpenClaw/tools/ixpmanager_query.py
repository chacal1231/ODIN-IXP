"""IXP Manager inventory (members, ASNs, switches, peering LAN IPs) from the IX-F member export 1.0."""
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


NAME = re.compile(r"[\w .,&'()/-]{1,128}")
SWITCH = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
MAX_ADDRESSES = 50
# Contact data and MAC addresses are deliberately never copied into results.
MEMBER_FIELDS = ("asnum", "name", "member_type", "peering_policy", "member_since", "url")
ADDRESS_FIELDS = ("address", "as_macro", "max_prefix", "routeserver")


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def allowed_ixps():
    values = {v.strip() for v in os.environ.get("IXPMANAGER_ALLOWED_IXPS", "").split(",") if v.strip()}
    if not values:
        raise ValueError("IXPMANAGER_ALLOWED_IXPS no configurado")
    if values == {"*"}:
        return None
    if not all(v.isdigit() for v in values):
        raise ValueError("IXPMANAGER_ALLOWED_IXPS debe listar ixp_id numéricos")
    return {int(v) for v in values}


class Export:
    """Validated view of the IX-F export restricted to the authorized IXPs."""

    def __init__(self, payload, allowed):
        if not isinstance(payload, dict) or not isinstance(payload.get("member_list"), list) \
                or not isinstance(payload.get("ixp_list"), list):
            raise ContractError("Se esperaba exportación IX-F con ixp_list y member_list")
        if str(payload.get("version", "")).split(".")[0] != "1":
            raise ContractError("Versión IX-F no soportada")
        self.observed_at = utc(payload.get("timestamp"))
        self.allowed = allowed
        self.ixps, self.switches, self.vlans = {}, {}, {}
        for ixp in payload["ixp_list"]:
            if not isinstance(ixp, dict) or type(ixp.get("ixp_id")) is not int:
                raise ContractError("ixp_list inválida")
            if allowed is not None and ixp["ixp_id"] not in allowed:
                continue
            self.ixps[ixp["ixp_id"]] = {"ixp_id": ixp["ixp_id"], "shortname": ixp.get("shortname"),
                                        "name": ixp.get("name"), "country": ixp.get("country")}
            for sw in ixp.get("switch") or []:
                if isinstance(sw, dict) and type(sw.get("id")) is int:
                    self.switches[sw["id"]] = {k: sw.get(k) for k in ("id", "name", "colo", "city", "manufacturer",
                                                                        "model", "software")} | {"ixp_id": ixp["ixp_id"]}
            for vlan in ixp.get("vlan") or []:
                if isinstance(vlan, dict) and type(vlan.get("id")) is int:
                    self.vlans[(ixp["ixp_id"], vlan["id"])] = vlan.get("name")
        self.members = []
        for m in payload["member_list"]:
            if not isinstance(m, dict) or type(m.get("asnum")) is not int or not isinstance(m.get("connection_list"), list):
                raise ContractError("member_list inválida")
            connections = [self.connection(c) for c in m["connection_list"]
                           if isinstance(c, dict) and c.get("ixp_id") in self.ixps]
            if connections:
                self.members.append({**{k: m.get(k) for k in MEMBER_FIELDS}, "connections": connections})

    def connection(self, c):
        interfaces = []
        for i in c.get("if_list") or []:
            if not isinstance(i, dict):
                raise ContractError("if_list inválida")
            switch = self.switches.get(i.get("switch_id"), {})
            speed = i.get("if_speed")
            interfaces.append({"switch_id": i.get("switch_id"), "switch": switch.get("name"),
                               "speed_mbps": speed if type(speed) is int and speed >= 0 else None,
                               "if_type": i.get("if_type")})
        vlans = []
        for v in c.get("vlan_list") or []:
            if not isinstance(v, dict):
                raise ContractError("vlan_list inválida")
            entry = {"vlan_id": v.get("vlan_id"), "vlan": self.vlans.get((c["ixp_id"], v.get("vlan_id")))}
            for family in ("ipv4", "ipv6"):
                if isinstance(v.get(family), dict):
                    entry[family] = {k: v[family].get(k) for k in ADDRESS_FIELDS if k in v[family]}
            vlans.append(entry)
        return {"ixp_id": c["ixp_id"], "state": c.get("state"), "connected_since": c.get("connected_since"),
                "interfaces": interfaces, "vlans": vlans}


def load():
    allowed = allowed_ixps()
    payload = read_api.request("ixpmanager", "member-export/ixf/1.0", {})
    return Export(payload, allowed)


def evidence(export, entity, data, units=None):
    return {"source": "ixpmanager", "entity": entity, "observed_at": export.observed_at,
            "collected_at": now(), "data": data, "units": units or {}, "raw_reference": None}


SPEED_UNITS = {"total_speed_mbps": "Mbit/s", "speed_mbps": "Mbit/s"}


def member_summary(m):
    speeds = [i["speed_mbps"] for c in m["connections"] for i in c["interfaces"]]
    return {"asnum": m["asnum"], "name": m["name"], "member_type": m["member_type"],
            "connections": len(m["connections"]), "ports": len(speeds),
            "total_speed_mbps": sum(speeds) if speeds and None not in speeds else None,
            "states": sorted({str(c["state"]) for c in m["connections"]})}


def result(operation, query, export, items, limit, warnings=()):
    warnings = set(warnings)
    if len(items) > limit:
        warnings.add("sample_truncated")
    if export.observed_at is None:
        warnings.add("missing_or_invalid_observed_at")
    status = "partial" if warnings else ("ok" if items else "empty")
    # Physical port names are not part of IX-F: mapping to LibreNMS interfaces needs another source.
    info = {"port_names_not_in_ixf_export", "contacts_and_macs_omitted"}
    return {"schema_version": 1, "source": "ixpmanager", "operation": operation, "status": status,
            "collected_at": now(), "query": query, "evidence": items[:limit],
            "coverage": {"returned": min(len(items), limit), "available": len(items), "limit": limit},
            "warnings": sorted(warnings | info)}


def op_members(export, args):
    items = []
    for m in export.members:
        if args.name is not None and args.name.casefold() not in str(m["name"] or "").casefold():
            continue
        items.append(evidence(export, {"asn": m["asnum"], "member": m["name"]}, member_summary(m), SPEED_UNITS))
    items.sort(key=lambda e: e["entity"]["asn"])
    return result("members", {"name": args.name}, export, items, args.limit)


def op_member(export, args):
    items = [evidence(export, {"asn": m["asnum"], "member": m["name"]}, m,
                      {"connections[].interfaces[].speed_mbps": "Mbit/s"})
             for m in export.members if m["asnum"] == args.asn]
    return result("member", {"asn": args.asn}, export, items, args.limit)


def op_ips(export, args):
    wanted = {}
    for raw in args.address:
        wanted[str(ipaddress.ip_address(raw))] = raw
    index = {}
    for m in export.members:
        for c in m["connections"]:
            for v in c["vlans"]:
                for family in ("ipv4", "ipv6"):
                    address = (v.get(family) or {}).get("address")
                    try:
                        key = str(ipaddress.ip_address(address))
                    except ValueError:
                        continue
                    index.setdefault(key, []).append((m, c, v, family))
    items, missing = [], []
    for key in wanted:
        matches = index.get(key, [])
        if not matches:
            missing.append(key)
        for m, c, v, family in matches:
            items.append(evidence(export, {"address": key, "asn": m["asnum"], "member": m["name"]},
                                  {"address": key, "asn": m["asnum"], "member": m["name"], "ixp_id": c["ixp_id"],
                                   "vlan_id": v["vlan_id"], "vlan": v["vlan"], "family": family,
                                   "routeserver": v[family].get("routeserver"), "connection_state": c["state"]}))
    warnings = ["address_assigned_to_multiple_members"] if len(items) > len(wanted) - len(missing) else []
    out = result("ips", {"addresses": sorted(wanted)}, export, items, args.limit, warnings)
    out["not_found"] = missing
    return out


def op_switches(export, args):
    counts = {}
    for m in export.members:
        for c in m["connections"]:
            for i in c["interfaces"]:
                counts.setdefault(i["switch_id"], set()).add(m["asnum"])
    items = [evidence(export, {"switch": s["name"], "switch_id": s["id"]},
                      {**s, "members": len(counts.get(s["id"], ()))}) for s in export.switches.values()]
    return result("switches", {}, export, items, args.limit)


def op_switch(export, args):
    if not SWITCH.fullmatch(args.name):
        raise ValueError("Switch inválido")
    ids = {i for i, s in export.switches.items() if s["name"] == args.name}
    if not ids:
        return result("switch", {"name": args.name}, export, [], args.limit, ["switch_not_found"])
    items = []
    for m in export.members:
        ports = [i for c in m["connections"] for i in c["interfaces"] if i["switch_id"] in ids]
        if ports:
            states = sorted({str(c["state"]) for c in m["connections"]
                             if any(i["switch_id"] in ids for i in c["interfaces"])})
            items.append(evidence(export, {"asn": m["asnum"], "member": m["name"], "switch": args.name},
                                  {"asnum": m["asnum"], "name": m["name"], "ports": len(ports),
                                   "speed_mbps": sum(p["speed_mbps"] or 0 for p in ports), "states": states},
                                  SPEED_UNITS))
    items.sort(key=lambda e: -e["data"]["speed_mbps"])
    return result("switch", {"name": args.name}, export, items, args.limit)


OPERATIONS = {"members": op_members, "member": op_member, "ips": op_ips, "switches": op_switches,
              "switch": op_switch}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="operation", required=True)

    def add(name, help_text):
        s = sub.add_parser(name, help=help_text)
        s.add_argument("--limit", type=int, default=50)
        return s

    add("members", "Miembros (filtro por nombre opcional)").add_argument("--name")
    add("member", "Detalle de un miembro por ASN").add_argument("--asn", type=int, required=True)
    add("ips", "Miembro dueño de IPs del peering LAN").add_argument("--address", action="append", required=True)
    add("switches", "Switches del IXP")
    add("switch", "Miembros conectados a un switch").add_argument("--name", required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if not 1 <= args.limit <= 500:
            raise ValueError("limit debe estar entre 1 y 500")
        if getattr(args, "name", None) is not None and args.operation == "members" and not NAME.fullmatch(args.name):
            raise ValueError("Nombre inválido")
        if getattr(args, "asn", None) is not None and not 1 <= args.asn <= 4294967295:
            raise ValueError("ASN inválido")
        if getattr(args, "address", None) is not None and len(args.address) > MAX_ADDRESSES:
            raise ValueError("Demasiadas direcciones")
        out = OPERATIONS[args.operation](load(), args)
    except urllib.error.HTTPError as exc:
        code = "authentication" if exc.code in (401, 403) else "rate_limited" if exc.code == 429 else "http_error"
        out = {"source": "ixpmanager", "status": "error", "error": code, "http_status": exc.code}
        exc.close()
    except (TimeoutError, urllib.error.URLError):
        out = {"source": "ixpmanager", "status": "error", "error": "connection_or_timeout"}
    except (ContractError, read_api.ResponseError, json.JSONDecodeError):
        out = {"source": "ixpmanager", "status": "error", "error": "invalid_response"}
    except ValueError:
        out = {"source": "ixpmanager", "status": "error", "error": "invalid_configuration_or_filter"}
    except Exception:
        out = {"source": "ixpmanager", "status": "error", "error": "query_failed"}
    # One JSON result for automation. Never include exception text, URLs, headers or remote bodies.
    try:
        text = json.dumps(out, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError):
        out = {"source": "ixpmanager", "status": "error", "error": "invalid_response"}
        text = json.dumps(out)
    print(text)
    return 1 if out["status"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
