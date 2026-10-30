"""The conformance suite's checks of what draft 0.5 adds (SPEC.md § 9.4, § 18
to § 20, § 5.7's deletion, § 4.1's DNS-SD, the rate limits of § 5.2 and
§ 5.5): a mixin of run.py's Suite, which gives it http, hello, validate(),
expect_problem() and the rest. The static libraries' checks (§ 21) are
static_check.py's.
"""
import base64
import hashlib
import http.client
import io
import json
import queue
import secrets
import select
import socket
import struct
import threading
import time
import zipfile
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

import lantern_client as client
import lantern_e2e as e2e

# run.py's own (bind() sets them): its exceptions, which its check() reads, its Response and Client, and its
# helpers.
Fail = Skip = Blind = Warn = Response = Client = check_repr_digest = problem_detail = None


def expect(cond, msg):
    if not cond:
        raise Fail(msg)


def bind(**names):
    """Takes run.py's classes and helpers, whatever the name it was loaded under."""
    globals().update(names)


def now_ms(offset=0.0):
    t = datetime.now(timezone.utc) + timedelta(seconds=offset)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


class Stream:
    """An open event stream (SPEC.md § 18.1), read a block at a time: a thread reads its lines as they come."""

    def __init__(self, conn, response, label, sock):
        self.conn, self.r, self.label, self.sock = conn, response, label, sock
        self.closed = False
        self.lines = queue.Queue()
        sock.settimeout(None)
        threading.Thread(target=self.reader, daemon=True).start()

    def reader(self):
        while True:
            try:
                line = self.r.fp.readline(65537)
            except (OSError, ValueError, AttributeError):
                line = b""
            self.lines.put((time.monotonic(), line))
            if not line:
                return

    def blocks(self, seconds, stop=None):
        """The blocks read within `seconds` (or until stop(blocks) is true): each a dict of its fields (retry,
        id, event, data) or {"comment": text}; the stream's end is {"end": True}."""
        out, block = [], {}
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not self.closed:
            try:
                at, line = self.lines.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if not line:
                self.closed = True
                out.append({"end": True, "at": at})
                break
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            if text == "":
                if block:
                    block["at"] = at
                    out.append(block)
                    block = {}
                    if stop and stop(out):
                        break
                continue
            if text.startswith(":"):
                out.append({"comment": text[1:].strip(), "at": at})
                if stop and stop(out):
                    break
                continue
            field, _, value = text.partition(":")
            block[field] = value.removeprefix(" ")
        return out

    def close(self):
        self.closed = True
        for closing in (lambda: self.sock.shutdown(socket.SHUT_RDWR), self.sock.close, self.conn.close):
            try:
                closing()
            except OSError:
                pass


def events_of(blocks):
    return [b for b in blocks if "event" in b or "data" in b]


class NewFamilies:
    """The checks of SPEC.md § 9.4, § 18, § 19, § 20 and § 5.7's deletion."""

    # Event streams (SPEC.md § 18).

    def open_stream(self, path=None, auth="token", headers=None, platform=None, token=None, seed=None, retry=6,
                    http=None):
        """A Stream, or the Response of an error (logged like any)."""
        http = http or self.http
        path = path or self.api("/v1/events")
        u = http.origin
        cls = http_client_class(u.scheme)
        kw = {"context": http.context} if u.scheme == "https" else {}
        conn = cls(u.hostname, u.port, timeout=http.timeout, **kw)
        hdrs = {"User-Agent": "LanternConformance/0.5", "Accept": "text/event-stream", "Accept-Language": "en",
                **(headers or {})}
        if platform:
            hdrs["Lantern-Platform"] = platform
        authorization = "Bearer " + token if token else http.authorization(auth)
        if authorization:
            hdrs["Authorization"] = authorization
        key = seed if seed is not None else (http.seed if auth == "token" and token is None and http.token else None)
        if key is not None:
            hdrs.update(http.signed(key, "GET", path, authorization, None))
        conn.request("GET", path, headers=hdrs)
        http.check_pin(conn)
        sock = conn.sock        # getresponse() lets go of it, the stream closing the connection
        r = conn.getresponse()
        label = "device" if token else "anonymous" if not authorization else auth
        if r.status != 200 or not (r.getheader("Content-Type") or "").startswith("text/event-stream"):
            data = r.read(1 << 20)
            conn.close()
            res = self.response("GET", path, label, r, data, platform)
            if res.status == 429 and retry:     # a stream closed a moment ago: the server frees its slot soon
                time.sleep(min(int(res.header("Retry-After") or 1), 1) / 2)
                return self.open_stream(path, auth, headers, platform, token, seed, retry=retry - 1, http=http)
            return res
        self.response("GET", path, label, r, b"", platform, raw=True)
        return Stream(conn, r, label, sock)

    def response(self, method, path, label, r, data, platform, raw=False):
        res = Response(method, path, label, r.status, r.headers, data, False, raw, platform)
        self.http.log.append(res)
        return res

    def events_limits(self):
        return (self.hello.get("limits") or {})

    def ready(self, stream):
        """The stream's first blocks: retry, then the event ready; (its id, the blocks read)."""
        blocks = stream.blocks(5, stop=lambda b: any(x.get("event") == "ready" for x in b))
        fields = [b for b in blocks if "comment" not in b]
        expect(fields and "retry" in fields[0] and fields[0]["retry"].isdigit(),
               f"the stream does not begin with a retry field: {fields[:1]}")
        ready = next((b for b in fields if b.get("event") == "ready"), None)
        expect(ready is not None and ready.get("id"), "no event ready with an id after retry")
        expect(fields.index(ready) <= 1, "ready is not the stream's first event")
        return ready["id"], blocks

    def c_feature_events(self, auth, level):
        if not level:
            r = self.http.request("GET", self.api("/v1/events"), auth=auth, headers={"Accept": "text/event-stream"})
            expect(r.status in (401, 403, 404), f"{r}: feature at 0, expected 401, 403 or 404")
            return f"{r.status}"
        s = self.open_stream(auth=auth)
        expect(isinstance(s, Stream), f"{s}: feature at {level}, expected a stream")
        try:
            self.ready(s)
        finally:
            s.close()

    def c_events_stream(self):
        limits = self.events_limits()
        expect(isinstance(limits.get("heartbeat"), int) and 5 <= limits["heartbeat"] <= 60,
               f"limits.heartbeat {limits.get('heartbeat')!r}: 5 to 60 seconds")
        expect(isinstance(limits.get("event_streams"), int) and limits["event_streams"] >= 1,
               f"limits.event_streams {limits.get('event_streams')!r}")
        expect(isinstance(limits.get("wait"), int) and 30 <= limits["wait"] <= 300,
               f"limits.wait {limits.get('wait')!r}: 30 to 300 seconds")
        s = self.open_stream(headers={"Accept-Encoding": "gzip, br, zstd"})
        expect(isinstance(s, Stream), f"{s}, expected 200 text/event-stream")
        try:
            expect(not s.r.getheader("Content-Encoding"), f"a stream with Content-Encoding {s.r.getheader('Content-Encoding')}")
            rid, blocks = self.ready(s)
        except BaseException:
            s.close()
            raise
        # Kept open for events.heartbeat, which reads what came while the other checks ran.
        self.beat = (s, next(b["at"] for b in blocks if b.get("event") == "ready"))
        self.ready_id = rid
        path = self.api(f"/v1/changes?since={quote(rid, safe='')}") + ("" if self.features(self.hello)["changes"]
                                                                        else "&wait=0")
        r = self.http.request("GET", path)
        expect(r.status == 200, f"{r}: the id of ready is not a token changes takes" + problem_detail(r))
        self.validate(r.json(), "changes", str(r))
        return f"ready {rid}; heartbeat {limits['heartbeat']} s, {limits['event_streams']} stream(s), wait {limits['wait']} s"

    def c_events_heartbeat(self):
        beat = self.events_limits().get("heartbeat", 60)
        if getattr(self, "beat", None) is None:
            raise Skip("no stream (events.stream)")
        s, start = self.beat
        self.beat = None
        try:
            blocks = s.blocks(max(0.1, start + beat + 3 - time.monotonic()), stop=lambda b: bool(b))
        finally:
            s.close()
        expect(blocks and "end" not in blocks[0] and blocks[0]["at"] - start <= beat + 2,
               f"nothing on the stream within {beat + 2} s of ready (limits.heartbeat {beat})")
        return f"a {'heartbeat' if 'comment' in blocks[0] else 'event'} {blocks[0]['at'] - start:.1f} s after ready"

    def own_event(self):
        """Makes an event of the suite's own (a request, or a wish), and a function that undoes it; (kind, its
        data's id or key, the platform, undo)."""
        scopes = self.scopes()
        if "requests" in scopes and self.features(self.hello)["requests"]:
            platform, tid = self.own_title(self.sample_platform())
            r = self.http.request("POST", self.api("/v1/requests"), body={"schema": 1, "platform": platform,
                                                                         "title_id": tid}, platform=platform)
            expect(r.status == 201, f"{r}, expected 201" + problem_detail(r))
            rid = r.json()["id"]
            return "request", rid, platform, lambda: self.http.request(
                "DELETE", self.api(f"/v1/requests/{quote(rid, safe='')}"), platform=platform)
        if "sync.write" in scopes and self.features(self.hello)["sync"]:
            gen = self.get_json(self.api("/v1/sync"), "sync")[1]["generation"]
            platform, tid = self.own_title(self.sample_platform())
            key = f"{platform}/{tid}"
            r = self.http.request("PATCH", self.api("/v1/sync/wishes"), body={"schema": 1, "generation": gen, "items": [
                {"key": key, "value": {"platform": platform, "title_id": tid}, "updated": now_ms()}]})
            expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
            return "sync", "wishes", None, lambda: self.http.request("PATCH", self.api("/v1/sync/wishes"), body={
                "schema": 1, "generation": gen, "items": [{"key": key, "deleted": True, "updated": now_ms(1)}]})
        raise Blind("needs the scope requests or sync.write, to make an event of its own")

    @staticmethod
    def is_mine(block, kind, ident):
        if block.get("event") != kind:
            return False
        try:
            data = json.loads(block.get("data", ""))
        except ValueError:
            return False
        return data.get("id") == ident if kind == "request" else data.get("collection") == ident

    def c_events_resume(self):
        s = self.open_stream()
        expect(isinstance(s, Stream), f"{s}, expected a stream")
        undo = None
        try:
            start, _ = self.ready(s)
            kind, ident, platform, undo = self.own_event()
            blocks = s.blocks(8, stop=lambda b: any(self.is_mine(x, kind, ident) for x in b))
        finally:
            s.close()
        try:
            mine = next((b for b in blocks if self.is_mine(b, kind, ident)), None)
            expect(mine is not None, f"no event {kind} on the stream within 8 s of making one")
            event = {"id": mine.get("id"), "event": mine["event"], "data": json.loads(mine["data"])}
            self.validate(event, "event", f"the event {kind}")
            again = self.open_stream(headers={"Last-Event-ID": start})
            expect(isinstance(again, Stream), f"{again}: resuming with Last-Event-ID, expected a stream")
            try:
                rid, first = self.ready(again)
                expect(rid == start, f"ready's id {rid}, not the token resumed from, {start}")
                first += again.blocks(5, stop=lambda b: any(self.is_mine(x, kind, ident) for x in b))
            finally:
                again.close()
            replayed = next((b for b in first if self.is_mine(b, kind, ident)), None)
            expect(replayed is not None and replayed.get("id") == mine["id"],
                   "resumed with Last-Event-ID, the stream does not give the event again, with its id")
            other = self.open_stream(path=self.api(f"/v1/events?since={quote(start, safe='')}&platform=x-lantern-conformance"),
                                     headers={"Last-Event-ID": "lantern-conformance"})
            expect(isinstance(other, Stream), f"{other}: ?since= wins over Last-Event-ID, expected a stream")
            try:
                self.ready(other)
                seen = other.blocks(2)
            finally:
                other.close()
            if platform:
                expect(not any(self.is_mine(b, kind, ident) for b in seen),
                       "a stream of another platform got the event of a request of this one")
            anon = self.features(self.hello_anon)["events"]
            if anon and self.args.token:
                a = self.open_stream(path=self.api(f"/v1/events?since={quote(start, safe='')}"), auth="none")
                if isinstance(a, Stream):
                    try:
                        self.ready(a)
                        expect(not any(self.is_mine(b, kind, ident) for b in a.blocks(2)),
                               "an anonymous stream got the event of an account")
                    finally:
                        a.close()
            r = self.http.request("GET", self.api(f"/v1/changes?since={quote(start, safe='')}&wait=5"))
            expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
            doc = r.json()
            self.validate(doc, "changes", str(r))
            expect(any(e["id"] == mine["id"] and e["event"] == kind for e in doc.get("events", [])),
                   f"{r}: the long poll does not list the event {mine['id']}")
        finally:
            if undo:
                undo()
        return f"{kind} {mine['id']}: on the stream, again after Last-Event-ID, in the long poll; not to another platform"

    def c_events_bad_token(self):
        r = self.open_stream(headers={"Last-Event-ID": "lantern-conformance-" + secrets.token_hex(4)}, retry=0)
        if isinstance(r, Stream):
            r.close()
            raise Fail("a Last-Event-ID the server never gave opened a stream: expected 400 or 410")
        self.expect_problem(r, [400, 410], {"bad_request", "gone"})

    def c_events_long_poll(self):
        for query in ("wait=5", "since=x&wait=soon"):
            r = self.http.request("GET", self.api(f"/v1/changes?{query}"))
            self.expect_problem(r, [400], {"bad_request"})
        start = getattr(self, "ready_id", None)
        if start is None:
            raise Skip("no token from a stream (events.stream)")
        t0 = time.monotonic()
        r = self.http.request("GET", self.api(f"/v1/changes?since={quote(start, safe='')}&wait=2"))
        took = time.monotonic() - t0
        expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
        self.validate(r.json(), "changes", str(r))
        expect(isinstance(r.json().get("events"), list), f"{r}: no events list with wait")
        expect(took < 2 + 10, f"{r}: answered after {took:.1f} s for a wait of 2")
        return f"{len(r.json()['events'])} event(s) after {took:.1f} s; without since or of another form, 400"

    def c_events_limit(self):
        n = self.events_limits().get("event_streams", 1)
        if n > 8:
            raise Skip(f"limits.event_streams {n}: too many streams to hold")
        held = []
        try:
            for _ in range(n):
                s = self.open_stream()
                expect(isinstance(s, Stream), f"{s}: stream {len(held) + 1} of {n}, expected a stream")
                held.append(s)
            extra = self.open_stream(retry=0)
            if isinstance(extra, Stream):
                held.append(extra)
                raise Fail(f"stream {n + 1} opened, above limits.event_streams {n}: expected 429")
            self.expect_problem(extra, [429], {"slow_down"})
            after = extra.header("Retry-After") or ""
            beat = self.events_limits().get("heartbeat", 60)
            expect(after.isdigit() and int(after) <= beat, f"{extra}: Retry-After {after or 'none'}, at most {beat}")
        finally:
            for s in held:
                s.close()
        time.sleep(1.5)        # the server sees the streams closed
        return f"{n} stream(s), then 429 with Retry-After {after}"

    def c_events_revoked(self):
        if "admin" not in self.scopes() or not self.features(self.hello)["admin"]:
            raise Skip("needs the scope admin, to revoke a device of the suite's own")
        seed, _, r = self.keyed_pairing(["library"])
        expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
        found = self.waiting(r.json()["code"])
        d = self.http.request("POST", self.api(f"/v1/admin/pairings/{quote(found['id'], safe='')}"),
                              body={"schema": 1, "decision": "approve", "scopes": ["library"]})
        expect(d.status == 204, f"{d}, expected 204" + problem_detail(d))
        token = self.collect(r.json()["poll"], seed)["token"]
        devices = self.admin_walk(self.api("/v1/admin/devices"), "admin-devices")
        mine = next((x for x in devices if x.get("key") == client.key_fingerprint(
            base64.b64encode(client.ed25519_public(seed)).decode())), None)
        expect(mine is not None, "the device paired is not listed")
        s = self.open_stream(token=token, seed=seed)
        expect(isinstance(s, Stream), f"{s}: the device's stream, expected a stream")
        try:
            self.ready(s)
            gone = self.http.request("DELETE", self.api(f"/v1/admin/devices/{quote(mine['id'], safe='')}"))
            expect(gone.status == 204, f"{gone}, expected 204")
            beat = self.events_limits().get("heartbeat", 60)
            t0 = time.monotonic()
            s.blocks(beat + 5, stop=lambda b: any("end" in x for x in b))
            expect(s.closed, f"the stream of a revoked device still open {beat + 5} s later")
        finally:
            s.close()
        return f"ended {time.monotonic() - t0:.1f} s after the device was revoked"

    # Mirrors and grants (SPEC.md § 19).

    def grant_key(self):
        peers = self.hello.get("peers") or {}
        try:
            key = base64.b64decode(peers.get("key", ""), validate=True)
        except ValueError:
            key = b""
        return key

    def c_peers_handshake(self):
        peers, anon = self.hello.get("peers"), (self.hello_anon or {}).get("peers")
        expect(isinstance(peers, dict) and len(self.grant_key()) == 32, f"peers {peers!r}: no grant key of 32 bytes")
        expect(isinstance(peers.get("grant_lifetime"), int) and 1 <= peers["grant_lifetime"] <= 900,
               f"peers.grant_lifetime {peers.get('grant_lifetime')!r}: 900 seconds at most")
        if anon is not None:
            expect(anon.get("key") == peers["key"], "peers.key differs without a token")
        return f"key {client.key_fingerprint(peers['key'])}, grants of {peers['grant_lifetime']} s"

    def files_of_library(self):
        """[(sha256, size, where)] of the apps and homebrew packages read so far."""
        out = [(a["sha256"], a["size"], f"app {a['id']}") for a in (self.apps or ([self.sample] if self.sample else []))]
        for e in self.homebrew or []:
            for p in [e["package"], *e.get("packages", [])]:
                out.append((p["sha256"], p["size"], f"homebrew {e['platform']}/{e['id']}"))
        return out

    def grant_for(self, sha256, platform=None):
        return self.http.request("GET", self.api(f"/v1/grants/sha256/{sha256}"), platform=platform)

    def c_peers_grant(self):
        files = self.files_of_library()
        if not files:
            raise Skip("no file in the library")
        key, lifetime = self.grant_key(), (self.hello.get("peers") or {}).get("grant_lifetime", 900)
        checked = 0
        for sha, size, where in files[:3]:
            r = self.grant_for(sha)
            expect(r.status == 200, f"{r}: a grant for the file of {where}, expected 200" + problem_detail(r))
            doc = r.json()
            self.validate(doc, "grant", str(r))
            expect(doc["sha256"] == sha and doc["size"] == size, f"{r}: the grant names another file")
            now = time.time() + self.http.offset
            payload = client.read_grant(doc["grant"], {self.hello["uid"]: key}, now - 60)
            expect(payload is not None, f"{r}: the grant does not verify by peers.key, for this server's uid")
            expect(payload["sha256"] == sha and payload["size"] == size, f"{r}: the grant's payload names another file")
            expect(payload["exp"] <= now + lifetime + 60, f"{r}: exp {payload['exp']} is beyond grant_lifetime")
            checked += 1
            self.granted = getattr(self, "granted", []) + [(sha, size, doc["grant"])]
        r = self.grant_for("0" * 64)
        self.expect_problem(r, [404], {"not_found"})
        return f"{checked} grant(s) verified; an unknown file 404"

    def c_peers_mirrors(self):
        files = list(self.apps or []) + [p for e in (self.homebrew or []) for p in [e["package"], *e.get("packages", [])]]
        mirrors = [m for f in files for m in f.get("mirrors", [])]
        token = self.args.token or "\0"
        bad = [m.get("url") for m in mirrors if not client.mirror_ok(m.get("url")) or token in str(m.get("url"))]
        expect(not bad, "mirrors not of § 19.2's form, or holding the token: " + ", ".join(map(str, bad[:3])))
        if not mirrors:
            raise Skip("no mirror in the library read")
        return f"{len(mirrors)} mirror(s)"

    # A peer (SPEC.md § 19.4), with --peer.

    def peer_client(self):
        if not self.args.peer:
            raise Skip("no --peer address given")
        if getattr(self, "_peer", None) is None:
            u = urlsplit(self.args.peer)
            ctx = None
            if u.scheme == "https":
                import ssl
                ctx = ssl.create_default_context()
                ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE   # nobody pins a peer (§ 19.4)
            self._peer = Client(u, None, ctx, self.args.timeout)
            self._peer.log = self.http.log
        return self._peer

    def peer_path(self, sha):
        base = urlsplit(self.args.peer).path.rstrip("/")
        return f"{base}/v1/blobs/sha256/{sha}"

    def c_peer_refused(self):
        peer = self.peer_client()
        grants = getattr(self, "granted", [])
        if not grants:
            raise Skip("no grant (peers.grant)")
        sha, _, grant = grants[0]
        r = peer.request("GET", self.peer_path(sha), auth="none", raw=True)
        self.expect_problem(r, [403], {"forbidden"})
        expect(not r.header("WWW-Authenticate"), f"{r}: a peer asks for no token, yet WWW-Authenticate")
        payload, sig = grant.split(".")
        forged = client.b64url(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).replace(b'"size":', b'"size":1')) + "." + sig
        r = peer.request("GET", self.peer_path(sha), auth="none", raw=True, headers={"Lantern-Grant": forged})
        self.expect_problem(r, [403], {"forbidden"})
        other = "f" * 64 if sha != "f" * 64 else "e" * 64
        r = peer.request("GET", self.peer_path(other), auth="none", raw=True, headers={"Lantern-Grant": grant})
        self.expect_problem(r, [403], {"forbidden"})
        return "without a grant, with one changed, with one of another file: 403"

    def c_peer_serves(self):
        peer = self.peer_client()
        served = 0
        for sha, size, grant in getattr(self, "granted", []):
            if size > self.args.max_download:
                continue
            r = peer.request("GET", self.peer_path(sha), auth="none", raw=True, limit=size,
                             headers={"Lantern-Grant": grant})
            if r.status == 404:
                continue
            expect(r.status == 200, f"{r}, expected 200 or 404" + problem_detail(r))
            expect(len(r.body) == size and hashlib.sha256(r.body).hexdigest() == sha,
                   f"{r}: not the bytes of the file the grant names")
            check_repr_digest(r, sha)
            if size >= 2:
                part = peer.request("GET", self.peer_path(sha), auth="none", raw=True, limit=size,
                                    headers={"Lantern-Grant": grant, "Range": "bytes=1-"})
                expect(part.status == 206 and part.body == r.body[1:], f"{part}: bytes=1- is not the rest of the file")
            served += 1
        if not served:
            raise Skip("the peer holds none of the files granted")
        return f"{served} file(s), checked"

    def c_peer_rate(self):
        peer = self.peer_client()
        sha = (getattr(self, "granted", None) or [("0" * 64, 0, "")])[0][0]
        for i in range(60):
            r = peer.request("HEAD", self.peer_path(sha), auth="none", raw=True)
            if r.status == 429:
                expect((r.header("Retry-After") or "").isdigit(), f"{r}: no Retry-After")
                return f"429 after {i + 1} requests"
        raise Fail("60 requests at once from one address, and no 429")

    def c_peer_discovery(self):
        self.peer_client()
        if not self.args.discover:
            raise Skip("no --discover address given")
        port = self.args.peer_discover_port or self.args.discover_port
        replies = self.datagrams({"schema": 1, "lantern": "discover", "peers": True}, port)
        peers = [(d, a) for d, a in replies if d.get("lantern") == "peer"]
        expect(peers, f"no peer answered a datagram that asks for peers ({len(replies)} reply(ies))")
        for doc, _ in peers:
            self.validate(doc, "discovery-peer", "a peer's reply")
        want = urlsplit(self.args.peer).port
        mine = [d for d, _ in peers if d["port"] == want]
        expect(mine, f"no peer's reply gives the port {want} of --peer")
        expect(self.hello["uid"] in mine[0]["servers"], "the peer's servers do not hold this server's uid")
        quiet = [d for d, _ in self.datagrams({"schema": 1, "lantern": "discover"}, port) if d.get("lantern") == "peer"]
        expect(not quiet, "a peer answered a datagram that does not ask for peers")
        return f"{mine[0]['name']}: slots {mine[0]['slots']}, tls {mine[0]['tls']}"

    def datagrams(self, doc, port, seconds=1.5):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        out = []
        try:
            sock.sendto(json.dumps(doc).encode(), (self.args.discover, port))
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                ready, _, _ = select.select([sock], [], [], max(0.0, deadline - time.monotonic()))
                if not ready:
                    break
                data, peer = sock.recvfrom(65536)
                try:
                    out.append((json.loads(data.decode("utf-8")), peer[0]))
                except (UnicodeDecodeError, ValueError):
                    pass
        finally:
            sock.close()
        return out

    # Sync (SPEC.md § 20).

    def sync_write(self, items, collection="wishes", generation=None, headers=None, http_token=None, seed=None):
        gen = generation or self.get_json(self.api("/v1/sync"), "sync")[1]["generation"]
        return self.http.request("PATCH", self.api(f"/v1/sync/{collection}"), body={
            "schema": 1, "generation": gen, "items": items}, headers=headers, token=http_token, seed=seed)

    def c_sync_overview(self):
        _, doc = self.get_json(self.api("/v1/sync"), "sync")
        if self.args.token:
            expect(doc.get("device"), "no device id for a caller with a token")
        self.sync_doc = doc
        return f"generation {doc['generation']}: " + ", ".join(f"{k} {v['items']}" for k, v in doc["collections"].items())

    def c_sync_write(self):
        if "sync.write" not in self.scopes():
            raise Blind("the token lacks the scope sync.write")
        _, before = self.get_json(self.api("/v1/sync"), "sync")
        gen = before["generation"]
        platform, tid = self.own_title(self.sample_platform())
        key = f"{platform}/{tid}"
        value = {"platform": platform, "title_id": tid, "note": "Lantern conformance"}
        t0 = now_ms(-60)
        r = self.sync_write([{"key": key, "value": value, "updated": t0}], generation=gen)
        expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
        self.validate(r.json(), "sync-collection", str(r))
        kept = r.json()["items"][0]
        expect(kept.get("value") == value and kept["updated"].startswith(t0[:19]), f"{r}: the item sent is not kept")
        rev = kept["rev"]
        r = self.sync_write([{"key": key, "value": {**value, "note": "older"}, "updated": now_ms(-120)}], generation=gen)
        expect(r.status == 200 and r.json()["items"][0].get("value") == value,
               f"{r}: an item of an earlier updated replaced the one kept")
        r = self.sync_write([{"key": key, "deleted": True, "updated": kept["updated"]}], generation=gen)
        expect(r.status == 200 and r.json()["items"][0].get("deleted") is True,
               f"{r}: on the same updated, the deletion did not win")
        r, doc = self.get_json(self.api(f"/v1/sync/wishes?since={rev - 1}"), "sync-collection")
        expect(any(i["key"] == key and i.get("deleted") for i in doc["items"]),
               f"{r}: the deletion is not among the items since {rev - 1}")
        return f"{key}: kept, not replaced by an older, deleted on the same time; listed since {rev - 1}"

    def c_sync_future(self):
        if "sync.write" not in self.scopes():
            raise Blind("the token lacks the scope sync.write")
        platform, tid = self.own_title(self.sample_platform())
        key = f"{platform}/{tid}"
        r = self.sync_write([{"key": key, "value": {"platform": platform, "title_id": tid},
                              "updated": "2100-01-01T00:00:00.000Z"}])
        expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
        kept = r.json()["items"][0]["updated"]
        skew = (self.hello.get("auth") or {}).get("skew", 300)
        expect(kept < now_ms(self.http.offset + skew + 60), f"{r}: an updated of 2100 was kept as {kept}")
        later = datetime.fromisoformat(kept.replace("Z", "+00:00")) + timedelta(milliseconds=1)
        self.sync_write([{"key": key, "deleted": True,
                          "updated": later.strftime("%Y-%m-%dT%H:%M:%S.") + f"{later.microsecond // 1000:03d}Z"}])
        return f"2100 kept as {kept}"

    def c_sync_if_match(self):
        if "sync.write" not in self.scopes():
            raise Blind("the token lacks the scope sync.write")
        gen = self.get_json(self.api("/v1/sync"), "sync")[1]["generation"]
        platform, tid = self.own_title(self.sample_platform())
        r = self.sync_write([{"key": f"{platform}/{tid}", "deleted": True, "updated": now_ms()}], generation=gen,
                            headers={"If-Match": f'"{gen}-999999999"'})
        self.expect_problem(r, [412], {"precondition_failed"})

    def c_sync_generation(self):
        if "sync.write" not in self.scopes():
            raise Blind("the token lacks the scope sync.write")
        platform, tid = self.own_title(self.sample_platform())
        r = self.sync_write([{"key": f"{platform}/{tid}", "deleted": True, "updated": now_ms()}],
                            generation="g_lantern-conformance")
        self.expect_problem(r, [409], {"conflict"})

    def c_sync_installed(self):
        if "sync.write" not in self.scopes():
            raise Blind("the token lacks the scope sync.write")
        r = self.sync_write([{"key": "d_0000000000000000", "value": {"device": "Lantern conformance",
                                                                     "platform": "switch"}, "updated": now_ms()}],
                            collection="installed")
        self.expect_problem(r, [403], {"forbidden"})

    def c_sync_malformed(self):
        if "sync.write" not in self.scopes():
            raise Blind("the token lacks the scope sync.write")
        for item in ({"key": "Frostline Tales", "value": {}, "updated": now_ms()},
                     {"key": "switch/0100ABCD00010000", "deleted": True, "updated": "yesterday"}):
            self.expect_problem(self.sync_write([item]), [400], {"bad_request"})

    def c_sync_limits(self):
        n = self.events_limits().get("sync_items")
        if not (isinstance(n, int) and n >= 1):
            raise Warn("no limits.sync_items")
        return f"{n} items a collection"

    # End-to-end encrypted backups (SPEC.md § 9.4).

    def encrypted(self, size=3000):
        """(the encrypted backup of a small zip, its archive, the save key), the key made here."""
        key = secrets.token_bytes(32)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
            z.writestr("lantern-conformance/save.dat", secrets.token_bytes(size))
        archive = out.getvalue()
        return e2e.encrypt(key, archive, secrets.token_bytes(32), secrets.token_bytes(24)), archive, key

    def c_e2e_upload(self):
        data, archive, key = self.encrypted()
        encryption = {"scheme": e2e.SCHEME, "key_id": e2e.key_id(key)}
        platform, tid = self.save_title()
        body = {"schema": 1, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "kind": "account",
                "encryption": encryption}
        r = self.http.request("POST", self.api(f"/v1/saves/{quote(tid, safe='')}/uploads"), body=body, platform=platform)
        expect(r.status == 201, f"{r}, expected 201" + problem_detail(r))
        upload = r.json()["upload"]
        self.uploads.append(upload)
        r = self.patch(upload, 0, data)
        expect(r.status == 201, f"{r}: the whole encrypted backup in one chunk, expected 201" + problem_detail(r))
        self.uploads.remove(upload)
        self.keep(r)
        entry = r.json()
        self.validate(entry, "save", str(r))
        expect(entry.get("encryption") == encryption, f"{r}: encryption {entry.get('encryption')}, sent {encryption}")
        path = self.api(f"/v1/saves/{quote(tid, safe='')}/{quote(entry['save_id'], safe='')}")
        back = self.http.request("GET", path, platform=platform, raw=True, limit=len(data))
        expect(back.status == 200 and back.body == data, f"{back}: not the bytes sent")
        expect(e2e.decrypt(key, back.body) == archive, "the bytes read back do not decrypt to the archive")
        digest = base64.b64encode(hashlib.sha256(data).digest()).decode()
        r = self.http.request("POST", self.api(f"/v1/saves/{quote(tid, safe='')}"), body=data, platform=platform,
                              headers={"Content-Type": "application/octet-stream", "Content-Digest": f"sha-256=:{digest}:",
                                       "Lantern-Save-Encryption": f"{e2e.SCHEME}; key_id={encryption['key_id']}"})
        expect(r.status == 201, f"{r}: in one request, expected 201" + problem_detail(r))
        self.keep(r)
        expect(r.json().get("encryption") == encryption, f"{r}: encryption {r.json().get('encryption')}")
        _, listed = self.get_json(self.api(f"/v1/saves?title_id={quote(tid, safe='')}"), "saves", platform=platform)
        expect(sum(1 for s in listed["saves"] if s.get("encryption") == encryption) == 2,
               "the encrypted backups are not listed with their encryption")
        return f"key {encryption['key_id']}: uploaded, sent in one request, listed, read back, decrypted"

    def c_e2e_not_offered(self):
        if self.features(self.hello)["encrypted_saves"]:
            raise Skip("the server offers encrypted_saves")
        data, _, key = self.encrypted(10)
        platform, tid = self.save_title()
        digest = base64.b64encode(hashlib.sha256(data).digest()).decode()
        r = self.http.request("POST", self.api(f"/v1/saves/{quote(tid, safe='')}"), body=data, platform=platform,
                              headers={"Content-Type": "application/octet-stream", "Content-Digest": f"sha-256=:{digest}:",
                                       "Lantern-Save-Encryption": f"{e2e.SCHEME}; key_id={e2e.key_id(key)}"})
        self.keep(r)
        self.expect_problem(r, [400], {"bad_request"})

    # Deleting an account (SPEC.md § 5.7), with --admin-writes.

    def c_admin_users_delete(self):
        if not self.args.admin_writes:
            raise Skip("it makes and deletes an account: run with --admin-writes")
        name = getattr(self, "made_account", None)
        if name is None:
            raise Skip("no account of the suite's own (admin.users-write)")
        path = self.api(f"/v1/admin/users/{quote(name, safe='')}")
        self.expect_problem(self.http.request("DELETE", path), [400], {"bad_request"})
        self.expect_problem(self.http.request("DELETE", path + "?confirm=" + quote(name + "x", safe="")), [400],
                            {"bad_request"})
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        r = self.http.request("POST", self.api("/v1/admin/invitations"), body={
            "schema": 1, "user": name, "scopes": ["library", "admin", "sync.read", "sync.write"], "expires": expires,
            "devices": 2, "note": "Lantern conformance"})
        expect(r.status == 201, f"{r}, expected 201" + problem_detail(r))
        inv = r.json()
        seed, _, p = self.keyed_pairing(["library", "admin", "sync.read", "sync.write"], inv["code"])
        expect(p.status == 200, f"{p}: redeeming, expected 200" + problem_detail(p))
        token = self.collect(p.json()["poll"], seed)["token"]
        hello = self.http.request("GET", self.api("/v1/"), token=token, seed=seed)
        expect(hello.status == 200 and hello.json()["account"]["name"] == name, f"{hello}: not the account {name}")
        # The account's own device, an admin, deletes its own account: 409 (the suite never tries it with its own).
        own = self.http.request("DELETE", path + "?confirm=" + quote(name, safe=""), token=token, seed=seed)
        self.expect_problem(own, [409], {"conflict"})
        erased = ""
        if hello.json()["features"].get("sync"):
            r = self.http.request("GET", self.api("/v1/sync"), token=token, seed=seed)
            gen = r.json()["generation"]
            platform, tid = self.own_title(self.sample_platform())
            w = self.sync_write([{"key": f"{platform}/{tid}", "value": {"platform": platform, "title_id": tid},
                                  "updated": now_ms()}], generation=gen, http_token=token, seed=seed)
            expect(w.status == 200, f"{w}, expected 200" + problem_detail(w))
            d = self.http.request("DELETE", self.api("/v1/sync"), token=token, seed=seed)
            expect(d.status == 204, f"{d}, expected 204" + problem_detail(d))
            r = self.http.request("GET", self.api("/v1/sync"), token=token, seed=seed)
            expect(r.json()["generation"] != gen and all(c["items"] == 0 for c in r.json()["collections"].values()),
                   f"{r}: after DELETE, the same generation, or items left")
            w = self.sync_write([{"key": f"{platform}/{tid}", "deleted": True, "updated": now_ms(1)}], generation=gen,
                                http_token=token, seed=seed)
            self.expect_problem(w, [409], {"conflict"})
            erased = "; its sync data erased (a new generation, 409 for the old one)"
        r = self.http.request("DELETE", path + "?confirm=" + quote(name, safe=""))
        expect(r.status == 204, f"{r}, expected 204" + problem_detail(r))
        after = self.http.request("GET", self.api("/v1/"), token=token, seed=seed)
        self.expect_problem(after, [401], {"unauthorized"})
        _, _, again = self.keyed_pairing(["library"], inv["code"])
        self.expect_problem(again, [410], {"gone"})
        self.expect_problem(self.http.request("DELETE", path + "?confirm=" + quote(name, safe="")), [404], {"not_found"})
        listed = {u["name"] for u in self.admin_walk(self.api("/v1/admin/users"), "admin-users")}
        expect(name not in listed, f"{name} is still listed")
        self.made_account = None
        return f"{name}: 400 without confirm, 409 for one's own; deleted: its token 401, its invitation 410{erased}"

    # Rate limits of pairing (SPEC.md § 5.2, § 5.5), last: they leave the address limited for a while.

    def c_invitation_rate(self):
        _, public = client.ed25519_keypair()
        key = {"alg": "ed25519", "public_key": base64.b64encode(public).decode()}
        for i in range(self.args.rate_probe):
            code = "-".join("".join(secrets.choice("23456789ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(4)) for _ in range(4))
            r = self.http.request("POST", self.api("/v1/pairing"), auth="none", body={
                "schema": 1, "device": "Lantern conformance", "scopes": ["library"], "key": key, "invitation": code})
            if r.status == 429:
                self.expect_problem(r, [429], {"slow_down"})
                expect((r.header("Retry-After") or "").isdigit(), f"{r}: no Retry-After")
                return f"429 after {i + 1} wrong invitation codes"
            self.expect_problem(r, [410, 400], {"gone", "key_required", "bad_request"})
        raise Fail(f"{self.args.rate_probe} wrong invitation codes from one address, and no 429 (--rate-probe)")

    def c_pairing_rate(self):
        _, public = client.ed25519_keypair()
        body = {"schema": 1, "device": "Lantern conformance", "scopes": ["library"],
                "key": {"alg": "ed25519", "public_key": base64.b64encode(public).decode()}}
        for i in range(self.args.rate_probe):
            r = self.http.request("POST", self.api("/v1/pairing"), auth="none", body=body)
            if r.status == 429:
                self.expect_problem(r, [429], {"slow_down"})
                expect((r.header("Retry-After") or "").isdigit(), f"{r}: no Retry-After")
                return f"429 after {i + 1} pairing requests"
            expect(r.status == 200, f"{r}, expected 200 or 429" + problem_detail(r))
        raise Fail(f"{self.args.rate_probe} pairing requests from one address, and no 429 (--rate-probe)")

    # DNS-SD (SPEC.md § 4.1), with --dns-sd.

    def c_dns_sd(self):
        if not self.args.dns_sd:
            raise Skip("no --dns-sd address given")
        host, _, port = self.args.dns_sd.partition(":")
        query = struct.pack("!HHHHHH", 0x4C54, 0, 1, 0, 0, 0) + dns_name("_lantern._tcp.local") + struct.pack("!HH", 12, 1)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3)
        try:
            sock.sendto(query, (host, int(port or 5353)))
            data, _ = sock.recvfrom(9000)
        except TimeoutError:
            raise Warn(f"no DNS-SD answer from {self.args.dns_sd} in 3 s") from None
        finally:
            sock.close()
        try:
            records = dns_records(data)
        except (ValueError, IndexError, struct.error) as e:
            raise Fail(f"the answer is not a DNS message: {e}") from None
        txt = {r["name"]: r["txt"] for r in records if r["type"] == 16}
        srv = {r["name"]: r["port"] for r in records if r["type"] == 33}
        ptr = [r["target"] for r in records if r["type"] == 12 and r["name"] == "_lantern._tcp.local"]
        mine = [n for n in ptr if txt.get(n, {}).get("uid") == self.hello["uid"]]
        if not mine:
            raise Warn(f"no _lantern._tcp instance with uid={self.hello['uid']} ({len(ptr)} instance(s))")
        name = mine[0]
        expect(txt[name].get("path") == self.base, f"TXT path {txt[name].get('path')}, the handshake's base is {self.base}")
        expect("1" in txt[name].get("v", "").split(","), f"TXT v {txt[name].get('v')}")
        want = self.origin.port or (443 if self.origin.scheme == "https" else 80)
        expect(srv.get(name) == want, f"SRV port {srv.get(name)}, the server answers on {want}")
        return f"{name}: port {srv[name]}, TXT {txt[name]}"


def http_client_class(scheme):
    return http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection


def dns_name(name):
    return b"".join(bytes([len(p.encode())]) + p.encode() for p in name.split(".")) + b"\0"


def dns_read_name(data, pos, hops=0):
    parts = []
    while True:
        n = data[pos]
        if n == 0:
            return ".".join(parts), pos + 1
        if n & 0xC0 == 0xC0:
            if hops > 16:
                raise ValueError("pointer loop")
            name, _ = dns_read_name(data, ((n & 0x3F) << 8) | data[pos + 1], hops + 1)
            return ".".join(parts + ([name] if name else [])), pos + 2
        parts.append(data[pos + 1:pos + 1 + n].decode("utf-8", "replace").replace(".", "\\."))
        pos += 1 + n


def dns_records(data):
    """The answers and additional records of a DNS message: [{name, type, …}] (PTR target, SRV port, TXT keys)."""
    _, _, qd, an, ns, ar = struct.unpack("!HHHHHH", data[:12])
    pos = 12
    for _ in range(qd):
        _, pos = dns_read_name(data, pos)
        pos += 4
    out = []
    for _ in range(an + ns + ar):
        name, pos = dns_read_name(data, pos)
        rtype, _, _, length = struct.unpack("!HHIH", data[pos:pos + 10])
        pos += 10
        rdata = data[pos:pos + length]
        rec = {"name": name.lower(), "type": rtype}
        if rtype == 12:
            rec["target"] = dns_read_name(data, pos)[0].lower()
        elif rtype == 33:
            rec["port"] = struct.unpack("!H", rdata[4:6])[0]
        elif rtype == 16:
            txt, i = {}, 0
            while i < len(rdata):
                n = rdata[i]
                k, _, v = rdata[i + 1:i + 1 + n].decode("utf-8", "replace").partition("=")
                txt[k] = v
                i += 1 + n
            rec["txt"] = txt
        out.append(rec)
        pos += length
    return out
