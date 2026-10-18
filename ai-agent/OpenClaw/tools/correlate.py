"""Correlate bounded evidence for incident cases A-D. Reports observations, derived values,
hypotheses, contradictions and gaps separately; never a confirmed root cause."""
import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
import statistics
import sys

import akvorado_query
import graylog_query
import ixpmanager_query
import librenms_query

# Always part of the report: what this correlation cannot establish.
LIMITS = ["temporal_coincidence_is_not_causality", "empty_result_is_not_health",
          "snapshots_reflect_last_poll_not_collection_time", "names_mapped_by_operator_not_inferred"]
DOWN_STATES = {"idle", "connect", "active", "opensent", "openconfirm"}
DROP_RATIO = 0.1


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def call(module, argv):
    """Run a client through its own CLI entry point so its validation and error mapping apply."""
    out = io.StringIO()
    with redirect_stdout(out):
        try:
            module.main(argv)
        except SystemExit:  # argparse rejected the arguments
            return {"source": module.__name__.replace("_query", ""), "status": "error",
                    "error": "invalid_configuration_or_filter"}
    return json.loads(out.getvalue())


class Report:
    def __init__(self, case, query):
        self.case, self.query = case, query
        self.sources, self.findings, self.gaps, self.timeline, self.snapshots = [], [], [], [], []

    def add_source(self, label, result):
        entry = {"label": label, "source": result.get("source"), "operation": result.get("operation"),
                 "status": result.get("status"), "warnings": result.get("warnings", [])}
        if result.get("status") == "error":
            entry["error"] = result.get("error")
            self.gap("source_failed", label=label, error=result.get("error"))
        elif result.get("status") == "partial":
            self.gap("source_partial", label=label, warnings=result.get("warnings", []))
        self.sources.append(entry)
        for item in result.get("evidence", []):
            summary = {"label": label, "source": item.get("source"), "entity": item.get("entity"),
                       "observed_at": item.get("observed_at"), "collected_at": item.get("collected_at"),
                       "window": item.get("window"), "data": item.get("data"),
                       "raw_reference": item.get("raw_reference")}
            (self.timeline if item.get("observed_at") else self.snapshots).append(summary)
        return result.get("evidence", []) if result.get("status") != "error" else None

    def gap(self, code, **details):
        self.gaps.append({"code": code, **details})

    def finding(self, kind, code, evidence_refs, **details):
        # kind: observation | derived | hypothesis | contradiction
        self.findings.append({"kind": kind, "code": code, "evidence": evidence_refs, **details})

    def render(self):
        self.timeline.sort(key=lambda e: e["observed_at"])
        order = {"contradiction": 0, "observation": 1, "derived": 2, "hypothesis": 3}
        self.findings.sort(key=lambda f: order[f["kind"]])
        return {"schema_version": 1, "case": self.case, "generated_at": now(), "query": self.query,
                "sources": self.sources, "findings": self.findings, "gaps": self.gaps,
                "timeline": self.timeline, "snapshots": self.snapshots, "limits": LIMITS}


def ref(label, item):
    return {"label": label, "raw_reference": item.get("raw_reference"), "observed_at": item.get("observed_at"),
            "collected_at": item.get("collected_at")}


def latest(items, predicate):
    matching = [i for i in items if i.get("observed_at") and predicate(i)]
    return max(matching, key=lambda i: i["observed_at"]) if matching else None


def traffic(report, args, minutes):
    """Interface traffic in both directions; a drop is derived, never a cause."""
    if not args.exporter:
        report.gap("source_not_requested", label="akvorado", reason="no --exporter mapping given")
        return
    for direction in ("in", "out"):
        label = f"akvorado.timeseries.{direction}"
        argv = ["timeseries", "--exporter", args.exporter, "--minutes", str(minutes), "--limit", "1000"]
        if args.interface:
            argv += [f"--{direction}-interface", args.interface]
        items = report.add_source(label, call(akvorado_query, argv))
        if not items:
            continue
        series = [i["data"]["avg_bps"] for i in items]
        if len(series) >= 4:
            baseline = statistics.median(series[:-1])
            if baseline > 0 and series[-1] < baseline * DROP_RATIO:
                report.finding("derived", "traffic_drop", [ref(label, items[-1])], direction=direction,
                               last_bps=series[-1], baseline_median_bps=baseline, ratio_threshold=DROP_RATIO)
        else:
            report.gap("insufficient_traffic_buckets", label=label, buckets=len(series))


def graylog(report, args, label, extra):
    if not args.graylog_source:
        report.gap("source_not_requested", label="graylog", reason="no --graylog-source mapping given")
        return None
    argv = ["--device", args.graylog_source, "--seconds", str(args.minutes * 60), "--limit", "100"] + extra
    return report.add_source(label, call(graylog_query, argv))


def members(report, args, sessions, label):
    """Identify BGP peers as IXP members by exact peering-LAN address in IXP Manager."""
    if not args.ixp_manager:
        report.gap("source_not_requested", label="ixpmanager", reason="no --ixp-manager given")
        return
    peers = sorted({s["entity"].get("peer") for s in sessions if s["entity"].get("peer")})[:ixpmanager_query.MAX_ADDRESSES]
    if not peers:
        return
    argv = ["ips", "--limit", "500"] + [a for p in peers for a in ("--address", p)]
    result = call(ixpmanager_query, argv)
    found = report.add_source("ixpmanager.ips", result) or []
    by_address = {}
    for item in found:
        by_address.setdefault(item["data"]["address"], []).append(item)
    for s in sessions:
        peer = s["entity"].get("peer")
        for item in by_address.get(peer, []):
            report.finding("derived", "peer_is_ixp_member", [ref(label, s), ref("ixpmanager.ips", item)],
                           peer=peer, asn=item["data"]["asn"], member=item["data"]["member"],
                           routeserver=item["data"]["routeserver"], connection_state=item["data"]["connection_state"])
            remote = s["entity"].get("remote_asn")
            if remote is not None and str(remote) != str(item["data"]["asn"]):
                report.finding("contradiction", "peer_asn_differs_from_ixp_manager",
                               [ref(label, s), ref("ixpmanager.ips", item)], peer=peer,
                               librenms_remote_asn=remote, ixp_manager_asn=item["data"]["asn"])
    if result.get("not_found"):
        report.gap("peers_not_in_ixp_manager", addresses=result["not_found"])


def librenms(report, label, argv):
    return report.add_source(label, call(librenms_query, argv))


def port_state(report, args, label):
    items = librenms(report, label, ["ports", "--device", args.device, "--interface", args.interface])
    if items is None:
        return None
    if not items:
        report.gap("interface_not_found", label=label, interface=args.interface)
        return None
    port = items[0]
    oper, admin = port["data"].get("ifOperStatus"), port["data"].get("ifAdminStatus")
    if admin == "up" and oper != "up":
        report.finding("observation", "interface_oper_down_admin_up", [ref(label, port)], oper=oper)
    elif admin != "up":
        report.finding("observation", "interface_admin_down", [ref(label, port)], admin=admin)
    else:
        report.finding("observation", "interface_oper_up", [ref(label, port)])
    return port


def case_port_down(report, args):
    port = port_state(report, args, "librenms.ports")
    events = graylog(report, args, "graylog.interface", ["--interface", args.interface]) or []
    last = latest(events, lambda e: e["data"].get("interface_state") in ("up", "down"))
    if last:
        report.finding("observation", f"log_interface_{last['data']['interface_state']}",
                       [ref("graylog.interface", last)])
        if port and port["data"].get("ifOperStatus") == "up" and last["data"]["interface_state"] == "down":
            report.finding("contradiction", "librenms_up_but_latest_log_down",
                           [ref("librenms.ports", port), ref("graylog.interface", last)],
                           note="LibreNMS reflects its last poll; check poll time and later logs")
    sessions = librenms(report, "librenms.bgp", ["bgp", "--device", args.device]) or []
    down = [s for s in sessions if str(s["data"].get("bgpPeerState", "")).lower() in DOWN_STATES]
    if down and port and port["data"].get("ifOperStatus") != "up":
        report.finding("hypothesis", "bgp_sessions_down_on_same_device",
                       [ref("librenms.bgp", s) for s in down], peers=[s["entity"].get("peer") for s in down],
                       confidence="low", note="no interface-to-peer mapping verified")
        members(report, args, down, "librenms.bgp")
    traffic(report, args, args.minutes)


def case_optics(report, args):
    argv = ["optics", "--device", args.device] + (["--interface", args.interface] if args.interface else [])
    items = librenms(report, "librenms.optics", argv) or []
    for item in items:
        state = item["data"].get("state")
        if state in ("below_low", "above_high", "warn_low", "warn_high"):
            report.finding("derived", f"optical_{state}", [ref("librenms.optics", item)],
                           sensor=item["data"].get("sensor_descr"), direction=item["data"].get("direction"),
                           current_dbm=item["data"].get("current_dbm"),
                           lower_margin_db=item["data"].get("lower_margin_db"),
                           upper_margin_db=item["data"].get("upper_margin_db"))
        elif state in ("limits_missing", "limits_incompatible", "no_reading"):
            report.gap(f"optical_{state}", sensor=item["data"].get("sensor_descr"))
    if args.interface:
        graylog(report, args, "graylog.interface", ["--interface", args.interface])


def case_degradation(report, args):
    port = port_state(report, args, "librenms.ports")
    if port and port["data"].get("ifOperStatus") != "up":
        report.gap("interface_not_up_use_port_down_case", interface=args.interface)
    elif port:
        errors = {k: librenms_query.number(port["data"].get(k)) for k in ("ifInErrors_rate", "ifOutErrors_rate")}
        if any(v and v > 0 for v in errors.values()):
            report.finding("observation", "errors_while_up", [ref("librenms.ports", port)], **errors)
    optics = librenms(report, "librenms.optics", ["optics", "--device", args.device, "--interface", args.interface]) or []
    for item in optics:
        if item["data"].get("state") not in ("within_limits", None):
            report.finding("derived", f"optical_{item['data']['state']}", [ref("librenms.optics", item)],
                           sensor=item["data"].get("sensor_descr"),
                           lower_margin_db=item["data"].get("lower_margin_db"),
                           upper_margin_db=item["data"].get("upper_margin_db"))
    graylog(report, args, "graylog.interface", ["--interface", args.interface])
    traffic(report, args, args.minutes)


def case_bgp(report, args):
    argv = ["bgp", "--device", args.device] + (["--remote-address", args.neighbor] if args.neighbor else [])
    sessions = librenms(report, "librenms.bgp", argv) or []
    for s in sessions:
        state = str(s["data"].get("bgpPeerState", "")).lower()
        report.finding("observation", "bgp_session_established" if state == "established" else "bgp_session_not_established",
                       [ref("librenms.bgp", s)], peer=s["entity"].get("peer"), state=state)
    events = graylog(report, args, "graylog.bgp", ["--event", "bgp"] + (["--neighbor", args.neighbor] if args.neighbor else [])) or []
    for s in sessions:
        peer = s["entity"].get("peer")
        last = latest(events, lambda e: e["data"].get("bgp_neighbor_ip") == peer and e["data"].get("bgp_state"))
        if last and str(last["data"]["bgp_state"]).lower() != str(s["data"].get("bgpPeerState", "")).lower():
            report.finding("contradiction", "bgp_state_differs_between_sources",
                           [ref("librenms.bgp", s), ref("graylog.bgp", last)], peer=peer,
                           librenms_state=s["data"].get("bgpPeerState"), last_log_state=last["data"]["bgp_state"],
                           note="compare log time with LibreNMS poll time before concluding")
    members(report, args, sessions, "librenms.bgp")
    # Route-level changes (updates/withdrawals) need PMACCT, which has no read client yet.
    report.gap("source_not_integrated", label="pmacct", reason="route updates and withdrawals not covered")


CASES = {"port-down": case_port_down, "optics": case_optics, "degradation": case_degradation, "bgp": case_bgp}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("case", choices=CASES)
    p.add_argument("--device", required=True, help="Hostname en LibreNMS")
    p.add_argument("--interface")
    p.add_argument("--neighbor")
    p.add_argument("--graylog-source", help="Nombre del mismo equipo en Graylog")
    p.add_argument("--exporter", help="Nombre del mismo equipo en Akvorado")
    p.add_argument("--ixp-manager", action="store_true", help="Identificar peers BGP como miembros en IXP Manager")
    p.add_argument("--minutes", type=int, default=60)
    args = p.parse_args(argv)
    if args.case in ("port-down", "degradation") and not args.interface:
        p.error("--interface requerido para este caso")
    if not 1 <= args.minutes <= 1440:
        p.error("--minutes: 1–1440")
    report = Report(args.case, {k: v for k, v in vars(args).items() if k != "case"})
    CASES[args.case](report, args)
    print(json.dumps(report.render(), ensure_ascii=False, allow_nan=False))
    return 1 if all(s["status"] == "error" for s in report.sources) else 0


if __name__ == "__main__":
    sys.exit(main())
