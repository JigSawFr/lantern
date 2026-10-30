"""What draft 0.5 adds, on the reference server, its peer and the suite:
events (a stream and long polling), grants, mirrors and peers, sync,
end-to-end encrypted backups, static libraries, deleting an account, DNS-SD,
the error texts in fifteen languages, and their test vectors.

    python3 -m unittest discover -s tests

Each test names the requirements it checks (SPEC.md § 3.5).
"""
import base64
import hashlib
import http.client
import http.server
import io
import json
import queue
import re
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "conformance"))

import lantern_client as client
import lantern_e2e as e2e
import library
from test_conformance import EVERY_SCOPE, USERS, Running, run_suite

from server import lantern_server as ls
from server import mdns, peer, static, texts

VECTORS = ROOT / "vectors"
ADMIN = "mila"


def vector(name):
    return json.loads((VECTORS / f"{name}.json").read_text(encoding="utf-8"))


def ms(offset=0.0):
    t = datetime.now(timezone.utc) + timedelta(seconds=offset)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


class Stream:
    """An event stream (SPEC.md § 18.1) of a test: its status, headers and blocks, read in a thread."""

    def __init__(self, srv, path="/api/lantern/v1/events", token=None, seed=None, headers=None):
        self.conn = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=30)
        hdrs = {"Accept": "text/event-stream", **(headers or {})}
        if token:
            hdrs["Authorization"] = "Bearer " + token
            hdrs.update(client.sign(seed, "GET", srv.url.rstrip("/") + path, hdrs["Authorization"]))
        self.conn.request("GET", path, headers=hdrs)
        self.sock = self.conn.sock
        self.r = self.conn.getresponse()
        self.status, self.headers = self.r.status, self.r.headers
        self.lines = queue.Queue()
        if self.status == 200:
            threading.Thread(target=self.read, daemon=True).start()
        else:
            self.body = self.r.read()

    def read(self):
        while True:
            try:
                line = self.r.fp.readline()
            except (OSError, ValueError, AttributeError):
                line = b""
            self.lines.put(line)
            if not line:
                return

    def blocks(self, seconds, until=None):
        out, block, deadline = [], {}, time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if not line:
                out.append({"end": True})
                break
            text = line.decode().rstrip("\r\n")
            if not text:
                if block:
                    out.append(block)
                    block = {}
                    if until and until(out):
                        break
            elif text.startswith(":"):
                out.append({"comment": text[1:].strip()})
            else:
                k, _, v = text.partition(":")
                block[k] = v.removeprefix(" ")
        return out

    def close(self):
        for fn in (lambda: self.sock.shutdown(socket.SHUT_RDWR), self.sock.close, self.conn.close):
            try:
                fn()
            except OSError:
                pass


def events(blocks, kind=None):
    return [(b["id"], b["event"], json.loads(b["data"])) for b in blocks if "event" in b
            and (kind is None or b["event"] == kind)]


class Live(unittest.TestCase):
    users = USERS

    def setUp(self):
        self.srv = Running(self.users)
        self.addCleanup(self.srv.close)

    def admin(self):
        if not hasattr(self, "_admin"):
            self._admin = self.srv.pair_keyed(ADMIN, EVERY_SCOPE)
        return self._admin[:2]

    def call(self, path, method="GET", data=None, who=None, headers=None):
        token, seed = who or self.admin()
        status, hdrs, body = self.srv.signed(path, token, seed, method, data, headers)
        doc = json.loads(body) if body and hdrs.get("Content-Type", "").endswith("json") else body
        return status, hdrs, doc

    def stream(self, who=None, **kw):
        token, seed = who or self.admin()
        s = Stream(self.srv, token=token, seed=seed, **kw)
        self.addCleanup(s.close)
        return s


class Vectors(unittest.TestCase):
    """The 0.5 vectors against the reference, both ways (SPEC.md § 17)."""

    def test_encrypted_saves(self):
        """L-9.4-1, L-9.4-7: backups decrypt to their archive; the refused ones never; phrases checked."""
        v = vector("encrypted-saves")
        for k in v["keys"]:
            key = bytes.fromhex(k["save_key"])
            self.assertEqual((e2e.key_id(key), e2e.phrase(key), e2e.qr_text(key)), (k["key_id"], k["phrase"], k["qr"]))
            self.assertEqual(e2e.key_from_qr(k["qr"]), key)
        for b in v["backups"]:
            key, fk, wn = (bytes.fromhex(b[x]) for x in ("save_key", "file_key", "wrap_nonce"))
            archive = bytes.fromhex(b["archive"]) if isinstance(b["archive"], str) else \
                bytes(i % 251 for i in range(b["archive"]["size"]))
            data = e2e.encrypt(key, archive, fk, wn)
            self.assertEqual((hashlib.sha256(data).hexdigest(), len(data), data[:88].hex()),
                             (b["sha256"], b["size"], b["header"]))
            self.assertEqual(e2e.decrypt(key, data), archive)
        for r in v["refused"]:
            self.assertFalse(r["opens"])
        for p in v["phrases"]:
            if p["accepted"]:
                self.assertEqual(e2e.key_from_phrase(p["phrase"]).hex(), v["keys"][0]["save_key"])
            else:
                with self.assertRaises(e2e.Refused):
                    e2e.key_from_phrase(p["phrase"])
        for case in v["primitives"]["xchacha20poly1305"]:
            sealed = e2e.xchacha20poly1305_seal(bytes.fromhex(case["key"]), bytes.fromhex(case["nonce"]),
                                                bytes.fromhex(case["plaintext"]), bytes.fromhex(case["aad"]))
            self.assertEqual(sealed.hex(), case["sealed"])

    def test_grants(self):
        """L-19.4-1: what a peer decides of each grant, the server's reader and the client's alike."""
        for case in vector("grants")["cases"]:
            keys = {u: base64.b64decode(k) for u, k in case["servers"].items()}
            for read in (ls.read_grant, client.read_grant):
                doc = read(case["grant"], keys, case["peer_time"])
                self.assertEqual(doc is not None and doc["sha256"] == case["path_sha256"], case["serves"], case["name"])

    def test_sync_merge(self):
        """L-20.4-1, L-20.4-2: the merge rule, the server's and the client's alike."""
        v = vector("sync-merge")
        now = datetime.fromisoformat(v["server_time"].replace("Z", "+00:00"))
        for case in v["cases"]:
            for mod in (ls, client):
                sent = dict(case["sent"], updated=mod.sync_time(case["sent"]["updated"], now, v["skew"]))
                self.assertEqual(mod.sync_wins(sent, case["have"]), case["replaced"], case["name"])
            self.assertEqual(case["kept"]["updated"],
                             (sent if case["replaced"] else case["have"])["updated"], case["name"])

    def test_static_layout(self):
        """L-21.1-2: the layout's files, and the paths a document may point at."""
        v = vector("static-layout")
        self.assertIn({"name": "The handshake", "route": "GET /.well-known/lantern", "file": "lantern.json"}, v["routes"])
        for p in v["paths"]:
            self.assertEqual(static.relative_ok(p["path"]), p["accepted"], p["path"])


class Events(Live):
    """SPEC.md § 18 on a live server."""

    def test_stream_and_resume(self):
        """L-18.1-1, L-18.1-2, L-18.1-3, L-18.1-7: retry, ready, an event, again after Last-Event-ID."""
        s = self.stream(headers={"Accept-Encoding": "gzip"})
        self.assertEqual((s.status, s.headers["Content-Type"].split(";")[0]), (200, "text/event-stream"))
        self.assertIsNone(s.headers.get("Content-Encoding"))
        first = s.blocks(3, until=lambda b: any(x.get("event") == "ready" for x in b))
        self.assertTrue(first[0]["retry"].isdigit())
        ready = next(b for b in first if b.get("event") == "ready")
        status, _, req = self.call("/api/lantern/v1/requests", "POST", {"schema": 1, "platform": "switch",
                                                                        "title_id": "0100FFFF00090000"})
        self.assertEqual(status, 201)
        got = events(s.blocks(5, until=lambda b: events(b, "request")), "request")
        self.assertEqual(got[0][2], {"schema": 1, "id": req["id"], "platform": "switch",      # L-11-6: to an admin,
                                     "title_id": "0100FFFF00090000", "status": "open", "user": ADMIN})  # with its user
        status, _, doc = self.call(f"/api/lantern/v1/changes?since={got[0][0]}")
        self.assertEqual((status, doc["added"]), (200, []))
        again = self.stream(headers={"Last-Event-ID": ready["id"]})
        blocks = again.blocks(3, until=lambda b: events(b, "request"))
        self.assertEqual(events(blocks, "ready")[0][0], ready["id"])
        self.assertEqual(events(blocks, "request")[0][0], got[0][0])
        bad = self.stream(headers={"Last-Event-ID": "s_00000000_1"})
        self.assertEqual(bad.status, 410)                                       # L-18.1-4: another epoch
        bad = self.stream(headers={"Last-Event-ID": "nonsense"})
        self.assertEqual(bad.status, 400)

    def test_who_sees_what(self):
        """L-18.2-1: a request of another account, a pairing to a token without admin, a library change hidden
        by a cap: no event."""
        lea = self.srv.pair_keyed("lea", {"schema": 1, "device": "Lea's Switch", "scopes": ["library", "requests"]})[:2]
        capped = self.srv.pair_keyed("lea", rating_cap={"age": 7})[:2]
        s_lea, s_cap, s_admin = self.stream(who=lea), self.stream(who=capped), self.stream()
        for s in (s_lea, s_cap, s_admin):
            s.blocks(3, until=lambda b: events(b, "ready"))
        self.call("/api/lantern/v1/requests", "POST", {"schema": 1, "platform": "switch", "title_id": "0100FFFF00090000"})
        self.srv.start_pairing({"schema": 1, "device": "Noor's Switch", "scopes": ["library"]})
        hidden = self.srv.root / "Ember Tide [0100E1E100060000][v0].nsp"
        hidden.write_bytes(b"\0" * 64)
        meta = json.loads((self.srv.root / "library.json").read_text())
        meta["apps"].append({"file": hidden.name, "ratings": [{"system": "PEGI", "rating": "18"}]})
        (self.srv.root / "library.json").write_text(json.dumps(meta))
        self.srv.lib.scan()
        admin_events = events(s_admin.blocks(3, until=lambda b: len(events(b)) >= 4))
        self.assertEqual({e for _, e, _ in admin_events} - {"ready"}, {"request", "pairing", "library"})
        lib = next(d for _, e, d in admin_events if e == "library")
        self.assertEqual(lib, {"schema": 1, "families": ["apps", "titles"], "platforms": ["switch"]})
        self.assertEqual({e for _, e, _ in events(s_lea.blocks(2))}, {"library"})   # not the admin's request
        self.assertEqual(events(s_cap.blocks(1)), [])                               # PEGI 18 above the cap
        self.assertEqual(self.call("/api/lantern/v1/changes?since=s_x&wait=1", who=lea)[0], 400)

    def test_long_poll(self):
        """L-18.3-1, L-18.3-2, L-18.3-3: answers when an event comes, or by wait; 400 without since."""
        status, _, now = self.call("/api/lantern/v1/changes")
        t0 = time.monotonic()
        status, _, doc = self.call(f"/api/lantern/v1/changes?since={now['since']}&wait=1")
        self.assertEqual((status, doc["events"], doc["since"]), (200, [], now["since"]))
        self.assertGreaterEqual(time.monotonic() - t0, 0.9)
        threading.Timer(0.5, lambda: self.call("/api/lantern/v1/requests", "POST", {
            "schema": 1, "platform": "switch", "title_id": "0100FFFF00090000"})).start()
        t0 = time.monotonic()
        status, _, doc = self.call(f"/api/lantern/v1/changes?since={now['since']}&wait=30")
        self.assertLess(time.monotonic() - t0, 10)
        self.assertEqual([e["event"] for e in doc["events"]], ["request"])
        self.assertEqual(doc["since"], doc["events"][-1]["id"])
        for query in ("wait=5", f"since={now['since']}&wait=-1", f"since={now['since']}&wait=soon"):
            self.assertEqual(self.call(f"/api/lantern/v1/changes?{query}")[0], 400)

    def test_limits_revocation_and_shutdown(self):
        """L-18.4-1, L-18.4-2, L-18.1-8, L-18.2-2: two streams a token, then 429; a frozen account's stream
        ends; shutdown on every stream when the server stops."""
        hello = self.call("/api/lantern/v1/")[2]
        self.assertEqual((hello["limits"]["heartbeat"], hello["limits"]["event_streams"], hello["limits"]["wait"]),
                         (5, 2, 60))
        a, b = self.stream(), self.stream()
        c = self.stream()
        self.assertEqual((c.status, json.loads(c.body)["code"]), (429, "slow_down"))
        self.assertLessEqual(int(c.headers["Retry-After"]), 5)
        a.close()
        time.sleep(1.5)
        d = self.stream()
        self.assertEqual(d.status, 200)
        lea = self.srv.pair_keyed("lea")[:2]
        s = self.stream(who=lea)
        s.blocks(2, until=lambda x: events(x, "ready"))
        self.call("/api/lantern/v1/admin/users/lea", "PATCH", {"schema": 1, "state": "frozen"})
        self.assertIn({"end": True}, s.blocks(8, until=lambda x: {"end": True} in x))
        b.blocks(2, until=lambda x: events(x, "ready"))
        threading.Thread(target=self.srv.server.shutdown, daemon=True).start()
        got = events(b.blocks(5, until=lambda x: events(x, "shutdown")), "shutdown")
        self.assertEqual(got[0][2]["schema"], 1)
        self.srv.server.stopping.clear()

    def test_saves_and_sync_events(self):
        """L-18.2-1: a backup kept and a sync collection changed, to the account's streams."""
        s = self.stream()
        s.blocks(3, until=lambda b: events(b, "ready"))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("save.dat", b"Frostline")
        data = out.getvalue()
        digest = base64.b64encode(hashlib.sha256(data).digest()).decode()
        status, _, entry = self.call("/api/lantern/v1/saves/0100ABCD00010000?platform=switch", "POST", data,
                                     headers={"Content-Type": "application/zip", "Content-Digest": f"sha-256=:{digest}:"})
        self.assertEqual(status, 201)
        gen = self.call("/api/lantern/v1/sync")[2]["generation"]
        self.call("/api/lantern/v1/sync/wishes", "PATCH", {"schema": 1, "generation": gen, "items": [
            {"key": "switch/0100ABCD00010000", "value": {"platform": "switch", "title_id": "0100ABCD00010000"},
             "updated": ms()}]})
        got = {e: d for _, e, d in events(s.blocks(4, until=lambda b: len(events(b)) >= 3))}
        self.assertEqual(got["save"]["save_id"], entry["save_id"])
        self.assertEqual(got["sync"], {"schema": 1, "collection": "wishes", "rev": 1})


class Peers(Live):
    """SPEC.md § 19: grants, mirrors, a peer."""

    def test_grants(self):
        """L-19.3-1, L-19.3-2, L-19.3-3: a grant per visible file, verifying by peers.key; 404 for a hidden one."""
        hello = self.call("/api/lantern/v1/")[2]
        key = base64.b64decode(hello["peers"]["key"])
        self.assertEqual(self.srv.get_json("/api/lantern/v1/")[1]["peers"], hello["peers"])     # every caller
        apps = self.call("/api/lantern/v1/apps?page_size=500")[2]["items"]
        moss = next(a for a in apps if a["title_id"] == "0100EFEF00020000")
        status, _, g = self.call(f"/api/lantern/v1/grants/sha256/{moss['sha256']}")
        self.assertEqual((status, g["sha256"], g["size"]), (200, moss["sha256"], moss["size"]))
        doc = ls.read_grant(g["grant"], {hello["uid"]: key})
        self.assertLessEqual(doc["exp"], time.time() + hello["peers"]["grant_lifetime"] + 1)
        self.assertIsNone(ls.read_grant(g["grant"], {hello["uid"]: key}, now=doc["exp"] + 1))
        capped = self.srv.pair_keyed("lea", rating_cap={"age": 12})[:2]
        self.assertEqual(self.call(f"/api/lantern/v1/grants/sha256/{moss['sha256']}", who=capped)[0], 404)
        self.assertEqual(self.call("/api/lantern/v1/grants/sha256/" + "0" * 64)[0], 404)
        update = next(a for a in apps if a["app_id"] == "0100EFEF00020800")
        self.assertEqual(len(update["mirrors"]), 2)                               # L-19.2-2: library.json's

    def test_peer(self):
        """L-19.4-1, L-19.4-2, L-19.4-4, L-19.4-5, L-19.5-1: a reference peer serves what a grant names, to it
        alone; nothing that is not a library's file; answers discovery that asks for peers."""
        token, seed = self.admin()
        uid, key, wanted = peer.server_files(self.srv.url, token, seed)
        (self.srv.root / ".lantern-saves").mkdir(exist_ok=True)
        stray = self.srv.root / "stray-save.zip"
        stray.write_bytes(b"PK\5\6" + bytes(18))
        held = peer.held_files(self.srv.root, wanted)
        self.assertNotIn(hashlib.sha256(stray.read_bytes()).hexdigest(), held)        # not a library's file
        p = peer.Peer(("127.0.0.1", 0), held, {uid: key}, slots=1, name="Lea's Switch")
        threading.Thread(target=p.serve_forever, args=(0.05,), daemon=True).start()
        self.addCleanup(p.server_close)
        self.addCleanup(p.shutdown)
        sha = next(iter(held))
        grant = self.call(f"/api/lantern/v1/grants/sha256/{sha}")[2]["grant"]
        conn = http.client.HTTPConnection("127.0.0.1", p.server_address[1], timeout=10)

        def get(path, headers=None, method="GET"):
            conn.request(method, path, headers=headers or {})
            r = conn.getresponse()
            return r.status, r.headers, r.read()
        status, h, body = get(f"/lantern/v1/blobs/sha256/{sha}")
        self.assertEqual((status, json.loads(body)["code"], h.get("WWW-Authenticate")), (403, "forbidden", None))
        status, h, body = get(f"/lantern/v1/blobs/sha256/{sha}", {"Lantern-Grant": grant})
        self.assertEqual((status, hashlib.sha256(body).hexdigest()), (200, sha))
        self.assertEqual(h["Repr-Digest"], f"sha-256=:{base64.b64encode(bytes.fromhex(sha)).decode()}:")
        status, _, body = get(f"/lantern/v1/blobs/sha256/{sha}", {"Lantern-Grant": grant, "Range": "bytes=0-0"})
        self.assertEqual((status, len(body)), (206, 1))
        other = ls.make_grant(bytes(32), uid, sha, held[sha]["size"], int(time.time()) + 60)
        self.assertEqual(get(f"/lantern/v1/blobs/sha256/{sha}", {"Lantern-Grant": other})[0], 403)
        p.active = 1                                                            # its one slot taken
        self.assertEqual(get(f"/lantern/v1/blobs/sha256/{sha}", {"Lantern-Grant": grant})[0], 429)
        p.active = 0
        statuses = [get(f"/lantern/v1/blobs/sha256/{sha}", method="HEAD")[0] for _ in range(15)]
        self.assertIn(429, statuses)
        limiter = ls.Limiter(5, 1.0)
        self.assertIsNone(p.reply(b'{"schema":1,"lantern":"discover"}', "127.0.0.1", limiter))
        reply = json.loads(p.reply(b'{"schema":1,"lantern":"discover","peers":true}', "127.0.0.1", limiter))
        self.assertEqual((reply["lantern"], reply["servers"], reply["slots"]), ("peer", [uid], 1))
        self.assertIsNone(p.reply(b'{"schema":1,"lantern":"discover","peers":true}', "203.0.113.9", limiter))
        self.assertFalse(peer.local("203.0.113.9"))
        self.assertTrue(peer.local("192.168.1.20") and peer.local("fe80::1") and peer.local("127.0.0.1"))
        with self.assertRaises(ValueError):
            peer.Peer(("203.0.113.9", 0), {}, {})                               # plain HTTP off a private network
        server_reply = ls.discovery_reply(self.srv.server, self.srv.port, b'{"schema":1,"lantern":"discover",'
                                          b'"peers":true}', "127.0.0.1", ls.Limiter(5, 1.0))
        self.assertEqual(json.loads(server_reply)["lantern"], "server")         # a server answers as ever

    def test_suite_with_a_peer(self):
        """The suite's --peer checks pass against the reference peer."""
        srv = Running(discovery=True, large=True)        # a game large enough to hold the peer's slots
        self.addCleanup(srv.close)
        uid, key, wanted = peer.server_files(srv.url)
        p = peer.Peer(("127.0.0.1", 0), peer.held_files(srv.root, wanted), {uid: key})
        threading.Thread(target=p.serve_forever, args=(0.05,), daemon=True).start()
        self.addCleanup(p.server_close)
        self.addCleanup(p.shutdown)
        udp = p.discovery(0)
        self.addCleanup(udp.close)
        code, report = run_suite(srv.url, "--peer", f"http://127.0.0.1:{p.server_address[1]}/lantern", "--discover",
                                 "127.0.0.1", "--discover-port", str(srv.udp.getsockname()[1]),
                                 "--peer-discover-port", str(udp.getsockname()[1]))
        self.assertEqual(code, 0, report)
        for cid in ("peer.refused", "peer.serves", "peer.discovery", "peer.slots", "peer.rate", "peers.mirrors",
                    "discovery.reply", "discovery.rate"):
            self.assertRegex(report, rf"PASS  § \S+\s+{re.escape(cid)} ")


class Sync(Live):
    """SPEC.md § 20."""

    def wish(self, tid="0100ABCD00010000", updated=None, deleted=False, note=None):
        item = {"key": f"switch/{tid}", "updated": updated or ms()}
        if deleted:
            item["deleted"] = True
        else:
            item["value"] = {"platform": "switch", "title_id": tid, **({"note": note} if note else {})}
        return item

    def write(self, items, collection="wishes", generation=None, who=None, headers=None):
        gen = generation or self.call("/api/lantern/v1/sync", who=who)[2]["generation"]
        return self.call(f"/api/lantern/v1/sync/{collection}", "PATCH", {"schema": 1, "generation": gen,
                                                                         "items": items}, who=who, headers=headers)

    def test_merge(self):
        """L-20.4-1, L-20.4-2, L-20.3-1: two devices; the later wins, a deletion wins a tie, the future is now."""
        other = self.srv.pair_keyed(ADMIN, EVERY_SCOPE)[:2]
        t = ms(-60)
        self.assertEqual(self.write([self.wish(updated=t)])[0], 200)
        _, _, doc = self.write([self.wish(updated=ms(-120), note="older")], who=other)
        self.assertEqual(doc["items"][0].get("value", {}).get("note"), None)
        _, _, doc = self.write([self.wish(updated=t, deleted=True)], who=other)
        self.assertTrue(doc["items"][0]["deleted"])
        _, _, doc = self.write([self.wish("0100EFEF00020000", updated="2100-01-01T00:00:00Z")])
        self.assertLess(doc["items"][0]["updated"], ms(10))
        doc = self.call("/api/lantern/v1/sync/wishes")[2]
        self.assertEqual([i["key"] for i in doc["items"]], ["switch/0100EFEF00020000"])     # no deletion
        since = self.call("/api/lantern/v1/sync/wishes?since=0")[2]
        self.assertEqual(len(since["items"]), 2)
        self.assertEqual(self.call(f"/api/lantern/v1/sync/wishes?since={doc['rev'] + 5}")[0], 400)

    def test_conditions(self):
        """L-20.4-3, L-20.4-4, L-20.4-5, L-20.4-6: If-Match, generation, another device's item, malformed."""
        overview = self.call("/api/lantern/v1/sync")[2]
        gen = overview["generation"]
        status, _, body = self.write([self.wish()], headers={"If-Match": f'"{gen}-5"'})
        self.assertEqual((status, body["code"]), (412, "precondition_failed"))
        self.assertEqual(self.write([self.wish()], headers={"If-Match": f'"{gen}-0"'})[0], 200)
        self.assertEqual(self.write([self.wish()], generation="g_old")[0], 409)
        mine = {"key": overview["device"], "value": {"device": "Mila's Switch", "platform": "switch",
                                                     "apps": [{"app_id": "0100ABCD00010000", "version_code": 0}]},
                "updated": ms()}
        self.assertEqual(self.write([mine], "installed")[0], 200)
        self.assertEqual(self.write([{**mine, "key": "d_0000000000000000"}], "installed")[0], 403)
        for bad in ({"key": "Frostline", "value": {}, "updated": ms()}, self.wish(updated="yesterday"),
                    {**self.wish(), "deleted": True}, {"key": "switch/0100ABCD00010800",
                                                       "value": {"platform": "switch", "title_id": "0100ABCD00010800"},
                                                       "updated": ms()}):
            self.assertEqual(self.write([bad])[0], 400, bad)
        self.assertEqual(self.write([self.wish(), self.wish()])[0], 400)          # a key twice
        self.assertEqual(self.call("/api/lantern/v1/sync/nothing")[0], 404)

    def test_erase_and_retention(self):
        """L-20.5-1, L-20.5-2: erased at once, a new generation; deletions kept 30 days, then a since gives 410."""
        self.write([self.wish(), self.wish("0100EFEF00020000")])
        self.write([self.wish(deleted=True)])
        gen = self.call("/api/lantern/v1/sync")[2]["generation"]
        sync = self.srv.server.sync
        col = sync.doc["accounts"][ADMIN]["collections"]["wishes"]
        col["items"]["switch/0100ABCD00010000"]["kept"] = "2026-01-01T00:00:00Z"   # a deletion of long ago
        self.assertEqual(self.call("/api/lantern/v1/sync/wishes?since=0")[0], 410)
        self.assertEqual(self.call("/api/lantern/v1/sync/wishes", "DELETE")[0], 204)
        doc = self.call("/api/lantern/v1/sync")[2]
        self.assertNotEqual(doc["generation"], gen)
        self.assertEqual(doc["collections"]["wishes"], {"rev": 0, "items": 0})
        self.assertEqual(self.call("/api/lantern/v1/sync", "DELETE")[0], 204)
        lea = self.srv.pair_keyed("lea")[:2]
        self.assertEqual(self.call("/api/lantern/v1/sync", who=lea)[0], 403)      # no scope sync.read

    def test_file(self):
        """A sync file of a newer schema: the family unavailable, never written over; unknown keys kept."""
        path = self.srv.root / ".lantern-sync.json"
        self.write([self.wish()])
        doc = json.loads(path.read_text())
        doc["x-example"] = "kept"
        path.write_text(json.dumps(doc))
        again = ls.Sync(path)
        again.write()
        self.assertEqual(json.loads(path.read_text())["x-example"], "kept")
        path.write_text(json.dumps({"schema": 2, "accounts": {}}))
        newer = ls.Sync(path)
        self.assertFalse(newer.available)
        newer.write()
        self.assertEqual(json.loads(path.read_text())["schema"], 2)
        path.unlink()
        self.assertTrue(ls.Sync(path).available)                                  # absent: empty, and written


class EncryptedSaves(Live):
    """SPEC.md § 9.4 on a live server."""

    def test_kept_as_sent(self):
        """L-9.4-4: an encrypted backup kept as sent, listed with its encryption; its header checked."""
        key = bytes(range(32))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("save.dat", b"Frostline " * 100)
        data = e2e.encrypt(key, out.getvalue(), bytes(32), bytes(24))
        encryption = {"scheme": e2e.SCHEME, "key_id": e2e.key_id(key)}
        status, _, up = self.call("/api/lantern/v1/saves/0100ABCD00010000/uploads?platform=switch", "POST", {
            "schema": 1, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "encryption": encryption})
        self.assertEqual(status, 201)
        status, _, entry = self.call(up["upload"], "PATCH", data, headers={
            "Upload-Offset": "0", "Content-Type": "application/offset+octet-stream"})
        self.assertEqual((status, entry["encryption"]), (201, encryption))
        status, _, back = self.call(f"/api/lantern/v1/saves/0100ABCD00010000/{entry['save_id']}?platform=switch")
        self.assertEqual(e2e.decrypt(key, back), out.getvalue())
        digest = base64.b64encode(hashlib.sha256(data).digest()).decode()
        headers = {"Content-Type": "application/octet-stream", "Content-Digest": f"sha-256=:{digest}:"}
        for header, expected in ((f"{e2e.SCHEME}; key_id={encryption['key_id']}", 201),
                                 (f"{e2e.SCHEME}; key_id=0000000000000000", 400),      # another key id
                                 ("age-v1; key_id=0a1b2c3d4e5f6071", 400), ("nonsense", 400)):
            status, _, _ = self.call("/api/lantern/v1/saves/0100ABCD00010000?platform=switch", "POST", data,
                                     headers={**headers, "Lantern-Save-Encryption": header})
            self.assertEqual(status, expected, header)
        status, _, _ = self.call("/api/lantern/v1/saves/0100ABCD00010000?platform=switch", "POST", data,
                                 headers=headers)
        self.assertEqual(status, 400)                                   # in clear, it must be a zip
        listed = self.call("/api/lantern/v1/saves?platform=switch")[2]["saves"]
        self.assertEqual(sum(1 for s in listed if s.get("encryption") == encryption), 2)


class DeletingAccounts(Live):
    """SPEC.md § 5.7's deletion."""

    def test_delete(self):
        """L-5.7-6, L-5.7-7, L-20.5-3: confirmed by the name; the account's tokens, invitations, backups,
        requests and sync data go; users.json's own and the caller's own give 409."""
        self.assertEqual(self.call("/api/lantern/v1/admin/users", "POST", {
            "schema": 1, "name": "sam", "scopes": ["library", "saves", "requests", "sync.read", "sync.write"]})[0], 201)
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        inv = self.call("/api/lantern/v1/admin/invitations", "POST", {
            "schema": 1, "user": "sam", "scopes": ["library", "saves", "requests", "sync.read", "sync.write"],
            "expires": expires, "devices": 3})[2]
        seed, public = client.ed25519_keypair()
        code = self.srv.start_pairing({"schema": 1, "device": "Sam's Switch", "invitation": inv["code"],
                                       "scopes": ["library", "saves", "requests", "sync.read", "sync.write"],
                                       "key": {"alg": "ed25519", "public_key": base64.b64encode(public).decode()}})
        sam = (json.loads(self.srv.signed(code["poll"], None, seed)[2])["token"], seed)
        self.call("/api/lantern/v1/requests", "POST", {"schema": 1, "platform": "switch",
                                                       "title_id": "0100FFFF00090000"}, who=sam)
        gen = self.call("/api/lantern/v1/sync", who=sam)[2]["generation"]
        self.call("/api/lantern/v1/sync/wishes", "PATCH", {"schema": 1, "generation": gen, "items": [
            {"key": "switch/0100ABCD00010000", "value": {"platform": "switch", "title_id": "0100ABCD00010000"},
             "updated": ms()}]}, who=sam)
        self.assertEqual(self.call("/api/lantern/v1/admin/users/sam", "DELETE")[0], 400)
        self.assertEqual(self.call("/api/lantern/v1/admin/users/sam?confirm=Sam", "DELETE")[0], 400)
        self.assertEqual(self.call(f"/api/lantern/v1/admin/users/{ADMIN}?confirm={ADMIN}", "DELETE")[0], 409)
        self.assertEqual(self.call("/api/lantern/v1/admin/users/lea?confirm=lea", "DELETE")[0], 409)   # users.json
        self.assertEqual(self.call("/api/lantern/v1/admin/users/sam?confirm=sam", "DELETE")[0], 204)
        self.assertEqual(self.call("/api/lantern/v1/", who=sam)[0], 401)
        self.assertEqual(self.call("/api/lantern/v1/admin/users/sam?confirm=sam", "DELETE")[0], 404)
        self.assertEqual(self.call("/api/lantern/v1/admin/users/sam", "PATCH", {"schema": 1, "state": "frozen"})[0], 404)
        self.assertNotIn("sam", self.srv.server.accounts.names())
        self.assertEqual(self.srv.server.invitations.listed(), [])
        self.assertFalse([r for r in self.srv.lib.requests() if r.get("user") == "sam"])
        self.assertNotIn("sam", self.srv.server.sync.doc["accounts"])
        status = self.srv.request("/api/lantern/v1/pairing", data={
            "schema": 1, "device": "x", "scopes": ["library"], "invitation": inv["code"]})[0]
        self.assertEqual(status, 410)
        self.assertEqual(self.call("/api/lantern/v1/admin/users", "POST", {"schema": 1, "name": "sam",
                                                                           "scopes": ["library"]})[0], 201)
        self.assertEqual(self.srv.server.accounts.get("sam")["scopes"], ["library"])     # inherits nothing


class StaticLibraries(unittest.TestCase):
    """SPEC.md § 21: the reference's export, and the suite's --static."""

    def export(self, page_size=3):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = library.make(Path(tmp.name) / "library")
        lib = ls.Library(root, Path(tmp.name) / "state.json")
        out = Path(tmp.name) / "static"
        static.export(ls, lib, out, page_size)
        return lib, out

    def test_export_and_suite(self):
        """L-21.1-1, L-21.1-2, L-21.2-1: the tree passes the suite, as a folder and over HTTP."""
        _, out = self.export()
        hello = json.loads((out / "lantern.json").read_text())
        self.assertEqual((hello["base"], hello["static"]["page_size"], hello["features"]["pairing"]), (".", 3, 0))
        code, report = run_suite("--static", str(out))
        self.assertEqual(code, 0, report)
        self.assertIn("Levels reached (SPEC.md § 17, draft 0.7): Lantern Static\n", report)
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(out)))
        threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        code, report = run_suite("--static", f"http://127.0.0.1:{httpd.server_address[1]}/")
        self.assertEqual(code, 0, report)
        self.assertRegex(report, r"PASS  § 21.1\s+static.files ")

    def test_layout(self):
        """Pages of fixed cursors, every platform's first page, files by their SHA-256, an earlier tree replaced."""
        lib, out = self.export(page_size=4)
        first = json.loads((out / "v1/apps/switch/pages/1.json").read_text())
        self.assertEqual((len(first["items"]), first["next"], first["total"]), (4, "2", library.SWITCH))
        for p in json.loads((out / "lantern.json").read_text())["platforms"]:
            for family in ("apps", "titles", "homebrew"):
                self.assertTrue((out / f"v1/{family}/{p}/pages/1.json").exists(), (family, p))
        for app in first["items"]:
            self.assertEqual(app["file"], f"v1/blobs/sha256/{app['sha256']}")
            self.assertEqual(hashlib.sha256((out / app["file"]).read_bytes()).hexdigest(), app["sha256"])
        stale = out / "v1/apps/switch/pages/9.json"
        stale.write_text("{}")
        again = out.parent / "again"
        static.export(ls, lib, out, 4)
        self.assertFalse(stale.exists())
        static.export(ls, lib, again, 4)
        self.assertEqual((out / "v1/apps/switch/pages/2.json").read_text(),
                         (again / "v1/apps/switch/pages/2.json").read_text())         # the same pages
        self.assertEqual(lib.homebrew[("switch", library.FROSTLINE)]["doc"]["package"]["file"][:18],
                         "/api/lantern/v1/fi")                                         # the library's own untouched

    def test_suite_catches_a_broken_tree(self):
        """L-21.1-1: a page chain broken, a file of another size: FAIL."""
        _, out = self.export()
        page = json.loads((out / "v1/apps/switch/pages/1.json").read_text())
        page["next"] = "7"
        (out / "v1/apps/switch/pages/1.json").write_text(json.dumps(page))
        code, report = run_suite("--static", str(out))
        self.assertEqual(code, 1)
        self.assertRegex(report, r"FAIL  § 21.1\s+static.pages.apps ")


class DnsSd(unittest.TestCase):
    """SPEC.md § 4.1: the reference server's DNS-SD, with the standard library alone."""

    def query(self, port, name, qtype=12):
        q = struct.pack("!HHHHHH", 7, 0, 1, 0, 0, 0) + b"".join(
            bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\0" + struct.pack("!HH", qtype, 1)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(3)
        try:
            s.sendto(q, ("127.0.0.1", port))
            return s.recvfrom(9000)[0]
        finally:
            s.close()

    def test_answers(self):
        """L-4.1-4: PTR, SRV, TXT and A of _lantern._tcp, unicast to a one-shot query; the suite reads them."""
        srv = Running()
        self.addCleanup(srv.close)
        r = ls.advertise(srv.server, srv.port, 0, "127.0.0.1")
        self.addCleanup(r.close)
        port = r.sock.getsockname()[1]
        import checks_v05
        records = checks_v05.dns_records(self.query(port, "_lantern._tcp.local"))
        kinds = {x["type"] for x in records}
        self.assertEqual(kinds, {12, 33, 16, 1})
        txt = next(x["txt"] for x in records if x["type"] == 16)
        self.assertEqual(txt, {"uid": srv.lib.uid, "path": "/api/lantern", "v": "1"})
        self.assertEqual(next(x["port"] for x in records if x["type"] == 33), srv.port)
        self.assertIsNone(r.reply(b"\x00" * 5, ("127.0.0.1", 9)))                     # not a query: silent
        self.assertIsNone(r.reply(self.query_bytes("_other._tcp.local"), ("127.0.0.1", 9)))
        report = run_suite(srv.url, "--dns-sd", f"127.0.0.1:{port}")[1]
        self.assertRegex(report, r"PASS  § 4.1\s+discovery.dns-sd ")

    @staticmethod
    def query_bytes(name):
        return struct.pack("!HHHHHH", 7, 0, 1, 0, 0, 0) + mdns.encode_name(name) + struct.pack("!HH", 12, 1)


class Texts(unittest.TestCase):
    """SPEC.md § 2.2: the server's error texts in the fifteen languages of the site."""

    def test_every_language(self):
        site = sorted(p.stem for p in (ROOT / "site" / "i18n").glob("*.json"))
        self.assertEqual(sorted(texts.LANGUAGES), site)
        codes = set(texts.FR)
        for lang in texts.LANGUAGES[1:]:
            self.assertEqual(set(texts.ERRORS[lang]), codes, lang)
            for code, (title, detail) in texts.ERRORS[lang].items():
                self.assertTrue(title and detail and "\n" not in title, (lang, code))
        for tags, want in ((["fr-CA"], "fr-CA"), (["fr-BE"], "fr"), (["es-MX"], "es-419"), (["es-ES"], "es"),
                           (["pt-BR"], "pt-BR"), (["pt"], "pt"), (["zh-TW"], "zh-Hant"), (["zh-Hant-HK"], "zh-Hant"),
                           (["zh-CN"], "zh-Hans"), (["zh"], "zh-Hans"), (["sv", "de-AT"], "de"), (["sv"], "en"),
                           (["ja-JP"], "ja"), ([], "en")):
            self.assertEqual(texts.best(tags), want, tags)

    def test_on_the_wire(self):
        """L-2.2-1, L-2.2-2: an error in Japanese, Brazilian Portuguese and Traditional Chinese, its language said."""
        srv = Running(USERS)
        self.addCleanup(srv.close)
        for header, lang, title in (("ja", "ja", "認証されていません"), ("pt-BR,pt;q=0.8", "pt-BR", "Não autorizado"),
                                    ("zh-TW", "zh-Hant", "未授權")):
            status, headers, body = srv.get("/api/lantern/v1/apps", headers={"Accept-Language": header})
            doc = json.loads(body)
            self.assertEqual((status, doc["language"], doc["title"], headers["Content-Language"]),
                             (401, lang, title, lang))


class SuiteCatchesFaults(unittest.TestCase):
    """The suite fails a server that breaks one of 0.5's MUSTs."""

    def fails(self, handler, cid, users=USERS, scopes=EVERY_SCOPE, extra=()):
        srv = Running(users, handler=handler)
        self.addCleanup(srv.close)
        token, _, key = srv.pair_keyed(ADMIN, scopes)
        code, report = run_suite(srv.url, "--token", token, "--key", key, *extra)
        self.assertEqual(code, 1, report)
        self.assertRegex(report, rf"FAIL  § \S+\s+{re.escape(cid)} ", report)

    def test_events_without_ready(self):
        class NoReady(ls.Handler):
            def write_event(self, eid, event, data):
                if event != "ready":
                    super().write_event(eid, event, data)
        self.fails(NoReady, "events.stream")

    def test_sync_last_arrival_wins(self):
        class Arrival(ls.Handler):
            def sync_item(self, name, item):
                out = super().sync_item(name, item)
                out["updated"] = ms()          # the time it arrives, whatever the device said
                return out
        self.fails(Arrival, "sync.write")

    def test_grant_of_another_key(self):
        class OtherKey(ls.Handler):
            def grant(self, query, hexdigest):
                self.server.library.grant_seed = bytes(32)
                return super().grant(query, hexdigest)
        self.fails(OtherKey, "peers.grant")

    def test_deleting_without_confirmation(self):
        class Eager(ls.Handler):
            def admin_user(self, query, name):
                if self.method == "DELETE" and "confirm" not in query:
                    query = {**query, "confirm": name}
                return super().admin_user(query, name)
        self.fails(Eager, "admin.users-delete", extra=("--admin-writes",))

    def test_pairing_without_limit(self):
        class Unlimited(ls.Handler):
            def pair_start(self, query):
                self.server.pair_limiter = ls.Limiter(10 ** 6, 1.0)
                self.server.attempts = ls.Limiter(10 ** 6, 1.0)
                return super().pair_start(query)
        self.fails(Unlimited, "pairing.rate-limit", extra=("--rate-probe", "40"))


if __name__ == "__main__":
    unittest.main()
