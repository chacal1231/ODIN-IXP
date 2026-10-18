#!/usr/bin/env python3
"""pmbmpd msglog (JSON lines) -> ClickHouse, at-least-once.

A batch is acknowledged by ClickHouse before its file offset is checkpointed, so a
failed insert is retried instead of discarded, and a restart resumes from the last
acknowledged line. Standard library only.
"""
import base64
import glob
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

EVENT_TYPES = {"update", "withdraw", "peer_up", "peer_down"}
COLUMNS = ("timestamp", "log_type", "afi", "safi", "ip_prefix", "bgp_nexthop", "as_path", "comms",
           "lcomms", "origin", "local_pref", "med", "peer_ip", "bmp_router", "bmp_msg_type")
# Upper bounds of the UInt8/UInt32 columns in bmp_events.
INTEGERS = {"afi": 2**8, "safi": 2**8, "local_pref": 2**32, "med": 2**32}
READ_CHUNK = 1 << 20
# Client errors that retrying cannot fix: the batch goes to the dead-letter file instead.
RETRYABLE_HTTP = {401, 403, 408, 429}


class InvalidRecord(ValueError):
    pass


def log(event, **fields):
    # One JSON line per event on stderr; never log credentials or BMP payloads.
    print(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event, **fields}),
          file=sys.stderr, flush=True)


def to_row(record):
    """Map a pmbmpd record to a bmp_events row; None if its log_type is not ingested."""
    if not isinstance(record, dict):
        raise InvalidRecord("not an object")
    if record.get("log_type") not in EVENT_TYPES:
        return None
    if not isinstance(record.get("timestamp"), str) or not record["timestamp"]:
        raise InvalidRecord("missing timestamp")
    row = {}
    for column in COLUMNS:
        value = record.get(column)
        if column in INTEGERS:
            # Same default as the previous ingester: absent or out-of-range numbers are stored as 0.
            row[column] = value if type(value) is int and 0 <= value < INTEGERS[column] else 0
        else:
            row[column] = "" if value is None else str(value)
    return row


class ClickHouse:
    def __init__(self, url, table, user, password, timeout):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("CLICKHOUSE_URL inválida: usar http(s)://host:puerto/ sin credenciales")
        if parsed.scheme == "http" and os.environ.get("CLICKHOUSE_ALLOW_HTTP") != "1":
            raise ValueError("CLICKHOUSE_URL usa HTTP; usar HTTPS o fijar CLICKHOUSE_ALLOW_HTTP=1 en red privada")
        if not table.replace("_", "").isalnum():
            raise ValueError("CLICKHOUSE_TABLE inválida")
        self.base, self.table, self.timeout = url.rstrip("/") + "/", table, timeout
        self.headers = {"Content-Type": "application/x-ndjson"}
        if user:
            self.headers["Authorization"] = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def insert(self, rows, token):
        params = urllib.parse.urlencode({
            "query": f"INSERT INTO {self.table} ({','.join(COLUMNS)}) FORMAT JSONEachRow",
            "date_time_input_format": "best_effort",
            # Effective only if the table sets non_replicated_deduplication_window; harmless otherwise.
            "insert_deduplication_token": token,
        })
        body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode()
        req = urllib.request.Request(self.base + "?" + params, data=body, headers=self.headers, method="POST")
        with self.opener.open(req, timeout=self.timeout) as response:
            response.read(65536)


class State:
    """Durable checkpoints {path: {dev, ino, offset}} plus the dead-letter file."""

    def __init__(self, directory):
        os.makedirs(directory, exist_ok=True)
        self.path = os.path.join(directory, "checkpoint.json")
        self.dead_letter = os.path.join(directory, "dead-letter.jsonl")
        try:
            with open(self.path, encoding="utf-8") as fh:
                self.checkpoints = json.load(fh)
        except FileNotFoundError:
            self.checkpoints = {}

    def save(self, key, dev, ino, offset):
        self.checkpoints[key] = {"dev": dev, "ino": ino, "offset": offset}
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.checkpoints, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)

    def reject(self, rows, source, http_status):
        with open(self.dead_letter, "a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps({"source": source, "http_status": http_status, "row": row}) + "\n")
            fh.flush()
            os.fsync(fh.fileno())


class Tailer:
    """Complete lines of one msglog file; survives restarts, truncation and rename rotation.

    Rotation recovery relies on an uncompressed '<file>.1' (logrotate delaycompress) holding
    the previous content. Without it the unread tail is reported as a gap, never silently skipped.
    """

    def __init__(self, path, state, start_at_end=False):
        self.path, self.state = path, state
        self.fh = self.dev = self.ino = None
        self.offset = 0          # acknowledged by ClickHouse
        self.read_offset = 0     # parsed into pending
        self.backlog = None      # (rotated_path, offset) still to read before the live file
        self.pending, self.first_pending_at = [], None
        self.invalid = 0
        saved = self.state.checkpoints.get(path)
        self._open(saved)
        if saved is None and start_at_end and self.fh is not None:
            # Migration from the previous ingester: skip content it already inserted.
            self.offset = self.read_offset = os.fstat(self.fh.fileno()).st_size
            self.state.save(self.path, self.dev, self.ino, self.offset)
            log("started_at_end", file=self.path, offset=self.offset)

    def _open(self, saved):
        try:
            fh = open(self.path, "rb")
        except FileNotFoundError:
            return
        st = os.fstat(fh.fileno())
        offset = 0
        if saved and (saved["dev"], saved["ino"]) == (st.st_dev, st.st_ino):
            offset = saved["offset"]
            if offset > st.st_size:  # copytruncate happened while stopped
                self._recover_rotated(offset)
                offset = 0
        elif saved:  # renamed while stopped: the old inode should now be '<file>.1'
            self._recover_rotated(saved["offset"], expect_ino=saved["ino"])
        self.fh, self.dev, self.ino = fh, st.st_dev, st.st_ino
        self.offset = self.read_offset = offset

    def _recover_rotated(self, offset, expect_ino=None):
        rotated = self.path + ".1"
        try:
            st = os.stat(rotated)
        except FileNotFoundError:
            st = None
        if st is None or st.st_size < offset or (expect_ino is not None and st.st_ino != expect_ino):
            log("rotation_gap", file=self.path, unread_from=offset)
        else:
            self.backlog = (rotated, offset)

    def read(self, batch_size):
        """Parse up to batch_size rows into pending; True if more data may be immediately available."""
        if self.backlog:
            return self._read_backlog(batch_size)
        if self.fh is None:
            self._open(self.state.checkpoints.get(self.path))
            if self.fh is None:
                return False
        if not self.pending:
            self._check_rotation()
            if self.backlog:
                return self._read_backlog(batch_size)
        self.fh.seek(self.read_offset)
        while len(self.pending) < batch_size:
            chunk = self.fh.read(READ_CHUNK)
            end = chunk.rfind(b"\n")
            if end < 0:
                return False  # a partial last line stays unread until it is complete
            for line in chunk[:end + 1].splitlines():
                self._parse(line)
            self.read_offset += end + 1
            self.fh.seek(self.read_offset)
        return True

    def _read_backlog(self, batch_size):
        rotated, offset = self.backlog
        with open(rotated, "rb") as fh:
            fh.seek(offset)
            while len(self.pending) < batch_size:
                line = fh.readline()
                if not line.endswith(b"\n"):
                    log("rotation_backlog_drained", file=rotated)
                    self.backlog = None
                    return True
                self._parse(line)
                offset += len(line)
        self.backlog = (rotated, offset)
        return True

    def _check_rotation(self):
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return
        if (st.st_dev, st.st_ino) != (self.dev, self.ino):
            # Renamed: keep reading the old inode until it has no more complete lines.
            self.fh.seek(self.read_offset)
            if b"\n" not in self.fh.read(READ_CHUNK):
                log("file_rotated", file=self.path)
                self.fh.close()
                self._open(None)
        elif st.st_size < self.read_offset:
            log("file_truncated", file=self.path, previous_offset=self.read_offset)
            self._recover_rotated(self.read_offset)
            self.offset = self.read_offset = 0

    def _parse(self, line):
        line = line.strip()
        if not line:
            return
        try:
            row = to_row(json.loads(line))
        except (ValueError, UnicodeDecodeError):  # includes InvalidRecord and JSONDecodeError
            self.invalid += 1
            log("invalid_line", file=self.path)
            return
        if row is not None:
            if not self.pending:
                self.first_pending_at = time.monotonic()
            self.pending.append(row)

    def due(self, batch_size, flush_seconds, stopping):
        return bool(self.pending) and (stopping or len(self.pending) >= batch_size or
                                       time.monotonic() - self.first_pending_at >= flush_seconds)

    def token(self):
        return f"{self.path}:{self.ino}:{self.backlog or ''}:{self.offset}:{self.read_offset}"

    def acknowledge(self):
        self.pending, self.first_pending_at = [], None
        if self.backlog is None and self.fh is not None:
            self.offset = self.read_offset
            self.state.save(self.path, self.dev, self.ino, self.offset)

    def lag_bytes(self):
        try:
            return max(os.stat(self.path).st_size - self.offset, 0)
        except FileNotFoundError:
            return 0


def flush(tailer, sink, state, stop, counters):
    """Insert pending rows; returns False only when stopping with rows still unacknowledged."""
    backoff = 1
    while True:
        try:
            sink.insert(tailer.pending, tailer.token())
            counters["inserted"] += len(tailer.pending)
            break
        except urllib.error.HTTPError as exc:
            exc.close()
            if 400 <= exc.code < 500 and exc.code not in RETRYABLE_HTTP:
                state.reject(tailer.pending, tailer.path, exc.code)
                counters["rejected"] += len(tailer.pending)
                log("batch_rejected", file=tailer.path, rows=len(tailer.pending), http_status=exc.code)
                break
            status = exc.code
        except OSError:  # URLError, timeouts, connection resets
            status = None
        counters["retries"] += 1
        log("insert_failed", file=tailer.path, rows=len(tailer.pending), http_status=status, retry_in=backoff)
        if stop["requested"] and time.monotonic() > stop["deadline"]:
            log("stopped_with_pending", file=tailer.path, rows=len(tailer.pending))
            return False
        time.sleep(backoff)
        backoff = min(backoff * 2, 60)
    tailer.acknowledge()
    return True


def run(config, stop):
    sink = ClickHouse(config["url"], config["table"], config["user"], config["password"], config["timeout"])
    state = State(config["state_dir"])
    tailers = {}
    counters = {"inserted": 0, "rejected": 0, "retries": 0}
    last_stats = time.monotonic()
    log("started", pattern=config["pattern"], batch_size=config["batch_size"], flush_seconds=config["flush_seconds"])
    while True:
        for path in glob.glob(config["pattern"]):
            if path not in tailers:
                tailers[path] = Tailer(path, state, config["start_at_end"])
        busy = False
        for tailer in tailers.values():
            if not stop["requested"]:
                busy |= tailer.read(config["batch_size"])
            if tailer.due(config["batch_size"], config["flush_seconds"], stop["requested"]):
                if not flush(tailer, sink, state, stop, counters):
                    return 1
        if time.monotonic() - last_stats >= 60:
            log("stats", **counters, invalid=sum(t.invalid for t in tailers.values()),
                lag_bytes={p: t.lag_bytes() for p, t in tailers.items()})
            last_stats = time.monotonic()
        if stop["requested"]:
            log("stopped", **counters)
            return 0
        if not busy:
            time.sleep(config["poll_seconds"])


def main():
    config = {
        "url": os.environ.get("CLICKHOUSE_URL", ""),
        "table": os.environ.get("CLICKHOUSE_TABLE", "bmp_events"),
        "user": os.environ.get("CLICKHOUSE_USER", ""),
        "password": os.environ.get("CLICKHOUSE_PASSWORD", ""),
        "timeout": float(os.environ.get("CLICKHOUSE_TIMEOUT", "10")),
        "pattern": os.environ.get("BMP_FILES", "/data/bmp-logs/bmp-events-*.json"),
        "state_dir": os.environ.get("BMP_STATE_DIR", "/var/lib/bmp-ingester"),
        "batch_size": int(os.environ.get("BMP_BATCH_SIZE", "500")),
        "flush_seconds": float(os.environ.get("BMP_FLUSH_SECONDS", "5")),
        "poll_seconds": float(os.environ.get("BMP_POLL_SECONDS", "0.5")),
        # Only applies to files without a checkpoint: "end" skips existing content, "start" reads it.
        "start_at_end": os.environ.get("BMP_INITIAL_POSITION", "start") == "end",
    }
    stop = {"requested": False, "deadline": 0.0}

    def request_stop(signum, frame):
        stop["requested"], stop["deadline"] = True, time.monotonic() + 20

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        return run(config, stop)
    except ValueError as exc:
        log("configuration_error", detail=str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
