"""What draft 0.6 settles and adds, on the reference server and the suite:
the values and routes of the core (SPEC.md § 2.3, § 2.4), the edge cases of
§ 4.3, § 6.3, § 6.6 and § 14, requests declined and done (§ 11), mirrors
read by the suite (§ 19.2), heartbeats for tests, compression below Python
3.14, and the files of a release (§ 3.6).

    python3 -m unittest discover -s tests

Each test names the requirements it checks (SPEC.md § 3.5).
"""
import functools
import hashlib
import http.client
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import unittest
import unittest.mock
import urllib.parse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "conformance"))

import lantern_client as client
import library
from test_conformance import EVERY_SCOPE, USERS, Running, run_suite
from test_v05 import ADMIN, Live, events

from server import lantern_server as ls

# Sam may ask for games, not administer: whose requests an admin decides.
SAM = {"name": "sam", "password": ls.hash_password("tide-lamp", 1000), "scopes": ["library", "requests"],
       "state": "active"}
SAM_DEVICE = {"schema": 1, "device": "Sam's Switch", "scopes": ["library", "requests"]}
TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$")


def strings(doc):
    if isinstance(doc, dict):
        for k, v in doc.items():
            yield from ((k, v),) if isinstance(v, str) else strings(v)
    elif isinstance(doc, list):
        for v in doc:
            yield from strings(v)


class Values(Live):
    """SPEC.md § 2.3."""

    def missing(self, body, content_type="application/json"):
        return self.call("/api/lantern/v1/apps/missing?platform=switch", "POST", body,
                         headers={"Content-Type": content_type})[0]

    def test_i_json(self):
        """L-2.3-1: a member twice, an integer beyond 2^53 - 1, an unpaired surrogate, a byte order mark: 400."""
        good = b'{"schema": 1, "installed": [], "want": ["base"]}'
        self.assertEqual(self.missing(good), 200)
        for bad in (good[:-1] + b', "want": ["dlc"]}', good[:-1] + b', "x": 9007199254740992}',
                    good[:-1] + b', "x": "\\udc00"}', b"\xef\xbb\xbf" + good):
            self.assertEqual(self.missing(bad), 400, bad)
        self.assertEqual(self.missing(good, "text/plain"), 400)                  # L-2.4-7

    def test_times_and_text(self):
        """L-2.3-2, L-2.3-5: every time of the server's documents in UTC with Z; text in NFC."""
        docs = [self.call(path)[2] for path in ("/api/lantern/v1/", "/api/lantern/v1/apps?page_size=500",
                                                "/api/lantern/v1/homebrew?page_size=500", "/api/lantern/v1/cheats")]
        times = [v for d in docs for k, v in strings(d) if k in ("created", "updated", "added", "expires")]
        self.assertTrue(times)
        self.assertEqual([t for t in times if not TIME.match(t)], [])
        self.assertTrue(all(unicodedata.is_normalized("NFC", v) for d in docs for _, v in strings(d)))

    def test_caseless_search(self):
        """L-2.3-6, L-6.2-1: q by Unicode's canonical caseless match: case, NFD and ß; accents still count."""
        meta = json.loads((self.srv.root / "library.json").read_text())
        for name, tid in (("Étoile du Nord", "0100E7E700080000"), ("Straße der Lichter", "0100E8E800090000")):
            (self.srv.root / f"{name} [{tid}][v0].nsp").write_bytes(b"\0" * 32)
            meta["apps"].append({"file": f"{name} [{tid}][v0].nsp", "name": name})
        (self.srv.root / "library.json").write_text(json.dumps(meta))

        def found(q):
            doc = self.call("/api/lantern/v1/apps?page_size=500&q=" + urllib.parse.quote(q))[2]
            return {a["name"] for a in doc["items"]}
        self.assertEqual(found("ÉTOILE"), {"Étoile du Nord"})
        self.assertEqual(found(unicodedata.normalize("NFD", "étoile")), {"Étoile du Nord"})
        self.assertEqual(found("etoile"), set())                                # an accent is not case
        self.assertEqual(found("STRASSE"), {"Straße der Lichter"})
        self.assertEqual(self.call("/api/lantern/v1/apps?q=" + "x" * 257)[0], 400)    # L-6.2-6
        names = [a["name"] for a in self.call("/api/lantern/v1/apps?page_size=500&platform=switch")[2]["items"]]
        self.assertEqual(names, sorted(names, key=ls.fold))                    # L-6.2-2: by the same match

    def test_empty_page(self):
        """L-2.3-7: nothing is an empty page."""
        status, _, doc = self.call("/api/lantern/v1/apps?title_id=0100FFFF00090000")
        self.assertEqual((status, doc["items"], doc["next"], doc["total"]), (200, [], None, 0))


class Routes(Live):
    """SPEC.md § 2.4."""

    def test_paths(self):
        """L-2.4-1: a trailing / is another path; <base>/v1 is the handshake; no redirect."""
        self.assertEqual(self.call("/api/lantern/v1/apps/")[0], 404)
        status, _, doc = self.call("/api/lantern/v1")
        self.assertEqual((status, doc["uid"]), (200, self.srv.lib.uid))

    def test_queries(self):
        """L-2.4-3, L-2.4-4, L-2.4-5: twice 400; empty absent; unknown ignored."""
        self.assertEqual(self.call("/api/lantern/v1/apps?type=base&type=dlc")[0], 400)
        plain = self.call("/api/lantern/v1/apps?page_size=500")[2]
        for query in ("platform=&type=&q=&sort=&cursor=&title_id=", "x-lantern-test=1"):
            status, _, doc = self.call(f"/api/lantern/v1/apps?page_size=500&{query}")
            self.assertEqual((status, doc["items"]), (200, plain["items"]), query)
        self.assertEqual(self.call("/api/lantern/v1/changes?since=")[0], 200)  # absent: the current token

    def test_head(self):
        """L-2.4-6: HEAD as GET on every GET route, without a body; the poll and the stream 405."""
        apps = self.call("/api/lantern/v1/apps?page_size=500")[2]["items"]
        for path in ("/.well-known/lantern", "/api/lantern/v1/", "/api/lantern/v1/apps", "/api/lantern/v1/changes",
                     "/api/lantern/v1/titles?ids=0100ABCD00010000", "/api/lantern/v1/titles/0100ABCD00010000?platform=switch",
                     "/api/lantern/v1/homebrew", f"/api/lantern/v1/homebrew/{library.PAPERLAMP}",
                     "/api/lantern/v1/cheats", "/api/lantern/v1/requests", "/api/lantern/v1/saves",
                     "/api/lantern/v1/sync", "/api/lantern/v1/sync/wishes", "/api/lantern/v1/admin/users",
                     "/api/lantern/v1/admin/devices", "/api/lantern/v1/admin/pairings",
                     "/api/lantern/v1/admin/invitations", "/api/lantern/v1/admin/requests", apps[0]["file"],
                     "/api/lantern/v1/nowhere"):
            get, head = self.call(path), self.call(path, "HEAD")
            self.assertEqual((head[0], head[2]), (get[0], b""), path)
            self.assertEqual(head[1].get("ETag"), get[1].get("ETag"), path)
        self.assertEqual(self.call("/api/lantern/v1/events", "HEAD")[0], 405)
        code = self.srv.start_pairing()
        self.assertEqual(self.srv.request(code["poll"], method="HEAD")[0], 405)


class EdgeCases(Live):
    """SPEC.md § 4.3, § 6.3, § 6.6, § 14, § 19.2."""

    def test_ambiguous(self):
        """L-4.3-8: a homebrew id of two platforms gives 400 without a platform."""
        self.assertEqual(self.call(f"/api/lantern/v1/homebrew/{library.FROSTLINE}")[0], 400)
        self.assertEqual(self.call(f"/api/lantern/v1/homebrew/{library.FROSTLINE}?platform=3ds")[0], 200)

    def test_missing_want(self):
        """L-6.3-2: want empty or of another type gives 400; an unknown installed app is ignored."""
        path = "/api/lantern/v1/apps/missing?platform=switch&page_size=500"
        for want in ([], ["patch"]):
            self.assertEqual(self.call(path, "POST", {"schema": 1, "installed": [], "want": want})[0], 400)
        plain = self.call(path, "POST", {"schema": 1, "installed": [], "want": ["base"]})[2]["items"]
        other = self.call(path, "POST", {"schema": 1, "installed": [{"app_id": "0100FFFF00090000", "version_code": 3}],
                                         "want": ["base"]})[2]["items"]
        self.assertEqual(other, plain)
        twice = self.call(path, "POST", {"schema": 1, "want": ["update"], "installed": [
            {"app_id": "0100ABCD00010000", "version_code": 0}, {"app_id": "0100ABCD00010000", "version_code": 196608}]})
        self.assertEqual(twice[2]["items"], [])                                  # the highest version counts

    def test_ranges(self):
        """L-6.6-6, L-6.6-7: If-Range keeps or drops the range; two ranges give the whole file, never multipart."""
        app = next(a for a in self.call("/api/lantern/v1/apps?page_size=500")[2]["items"] if a["size"] > 10)
        whole = self.call(app["file"])
        tag = whole[1]["ETag"]
        r = self.call(app["file"], headers={"Range": "bytes=1-", "If-Range": tag})
        self.assertEqual((r[0], r[2]), (206, whole[2][1:]))
        r = self.call(app["file"], headers={"Range": "bytes=1-", "If-Range": '"other"'})
        self.assertEqual((r[0], r[2]), (200, whole[2]))
        r = self.call(app["file"], headers={"Range": "bytes=0-0,2-3"})
        self.assertEqual((r[0], r[2], r[1]["Content-Type"]), (200, whole[2], "application/octet-stream"))
        empty = next(a for a in self.call("/api/lantern/v1/apps?page_size=500")[2]["items"] if a["size"] == 0)
        self.assertEqual(empty["sha256"], hashlib.sha256(b"").hexdigest())     # § 2.3: an empty file
        self.assertEqual(self.call(empty["file"], headers={"Range": "bytes=0-"})[0], 416)

    def test_not_modified(self):
        """L-14-3, L-14-4: weak or *, 304 with the 200's ETag, Vary and Cache-Control; a tag per page."""
        path = "/api/lantern/v1/apps?page_size=1"
        status, headers, doc = self.call(path)
        self.assertEqual(status, 200)
        for given in ("W/" + headers["ETag"], "*", '"x", ' + headers["ETag"]):
            again = self.call(path, headers={"If-None-Match": given})
            self.assertEqual((again[0], again[2]), (304, b""), given)
            for name in ("ETag", "Vary", "Cache-Control"):
                self.assertEqual(again[1][name], headers[name], name)
        nxt = self.call(path + "&cursor=" + doc["next"])
        self.assertNotEqual(nxt[1]["ETag"], headers["ETag"])

    def test_cheats_without_a_build(self):
        """Annex A.2: a 3DS cheat set has no build_id, read from cheats/3ds/<title id>/ and written without one."""
        folder = self.srv.root / "cheats" / "3ds" / "0004000000ABCD00"
        folder.mkdir(parents=True)
        (folder / "Community_list.txt").write_text("[Lamp oil]\n12345678 00000001\n")
        (folder / "0123").mkdir()
        (folder / "0123" / "Wrong.txt").write_text("[x]\n")                     # a build: not of the 3DS's layout
        sets = self.call("/api/lantern/v1/cheats?platform=3ds")[2]["cheats"]
        self.assertEqual([(c["source"], "build_id" in c) for c in sets], [("Community list", False)])
        body = {"schema": 1, "platform": "3ds", "title_id": "0004000000ABCD01", "source": "Noor",
                "text": "[Lamp]\n12345678 00000001\n"}
        status, _, doc = self.call("/api/lantern/v1/cheats", "POST", body)
        self.assertEqual((status, "build_id" in doc), (201, False))
        self.assertEqual(self.call("/api/lantern/v1/cheats", "POST", {**body, "build_id": "01", "source": "Lea"})[0], 400)

    def test_mirrors_on_loopback(self):
        """§ 19.2: plain HTTP for a mirror on a private network or on loopback, for testing; not elsewhere."""
        for url, ok in (("http://127.0.0.1:8070/a.nsp", True), ("http://[::1]/a", True),
                        ("http://192.168.1.20/a", True), ("http://203.0.113.9/a", False)):
            self.assertEqual((ls.mirror_url_ok(url), client.mirror_ok(url)), (ok, ok), url)


class Requests(Live):
    """SPEC.md § 11: open, then done or declined, final; an admin decides."""
    users = {**USERS, "users": [*USERS["users"], SAM]}    # noqa: RUF012 - read, never changed

    def test_lifecycle(self):
        """L-11-3, L-11-4, L-11-5, L-11-6."""
        sam = self.srv.pair_keyed("sam", SAM_DEVICE)[:2]
        s_sam, s_admin = self.stream(who=sam), self.stream()
        for s in (s_sam, s_admin):
            s.blocks(3, until=lambda b: events(b, "ready"))
        body = {"schema": 1, "platform": "switch", "title_id": "0100FFFF00090000"}
        status, _, req = self.call("/api/lantern/v1/requests", "POST", body, who=sam)
        self.assertEqual((status, req["status"], req["updated"]), (201, "open", req["created"]))
        status, _, listed = self.call("/api/lantern/v1/admin/requests?status=open")
        self.assertEqual(status, 200)
        mine = next(r for r in listed["items"] if r["id"] == req["id"])
        self.assertEqual((mine["user"], mine["status"]), ("sam", "open"))
        self.assertEqual(self.call("/api/lantern/v1/admin/requests", who=sam)[0], 403)      # L-5.7-1
        path = f"/api/lantern/v1/admin/requests/{req['id']}"
        self.assertEqual(self.call(path, "POST", {"schema": 1, "decision": "maybe"})[0], 400)
        self.assertEqual(self.call(path, "POST", {"schema": 1, "decision": "done", "reason": "Added."})[0], 400)
        reason = "This shelf keeps only the games of the household."
        status, _, doc = self.call(path, "POST", {"schema": 1, "decision": "decline", "reason": reason})
        self.assertEqual((status, doc["status"], doc["reason"], doc["user"]), (200, "declined", reason, "sam"))
        own = self.call("/api/lantern/v1/requests", who=sam)[2]["requests"]
        self.assertEqual((own[0]["status"], own[0]["reason"]), ("declined", reason))      # L-11-5
        self.assertNotIn("user", own[0])
        for decision in ("decline", "done"):                                     # L-11-3: final
            self.assertEqual(self.call(path, "POST", {"schema": 1, "decision": decision})[0], 409)
        self.assertEqual(self.call("/api/lantern/v1/admin/requests/r_nowhere", "POST",
                                   {"schema": 1, "decision": "done"})[0], 404)
        status, _, again = self.call("/api/lantern/v1/requests", "POST", body, who=sam)
        self.assertEqual(status, 201)
        self.assertNotEqual(again["id"], req["id"])
        status, _, done = self.call(f"/api/lantern/v1/admin/requests/{again['id']}", "POST",
                                    {"schema": 1, "decision": "done"})
        self.assertEqual((status, done["status"], "reason" in done), (200, "done", False))
        want = [(req["id"], "open"), (req["id"], "declined"), (again["id"], "open"), (again["id"], "done")]

        def got(s, user):
            seen = events(s.blocks(5, until=lambda b: len(events(b, "request")) >= 4), "request")
            self.assertEqual([(d["id"], d["status"]) for _, _, d in seen], want)
            self.assertEqual({d.get("user") for _, _, d in seen}, {user})
        got(s_sam, None)                                                          # L-11-6: to the account,
        got(s_admin, "sam")                                                       # to the admin, with its user
        self.assertEqual(self.call("/api/lantern/v1/admin/requests?status=declined")[2]["items"][0]["id"], req["id"])
        self.assertEqual(self.call("/api/lantern/v1/admin/requests?status=lost")[0], 400)
        self.assertEqual(self.call("/api/lantern/v1/admin/requests?user=lea")[2]["items"], [])

    def test_arrival(self):
        """L-11-3: an open request is done when its title arrives, and its updated changes."""
        status, _, req = self.call("/api/lantern/v1/requests", "POST", {"schema": 1, "platform": "switch",
                                                                       "title_id": "0100E6E600070000"})
        self.assertEqual(status, 201)
        time.sleep(1.1)
        (self.srv.root / "Ember Tide [0100E6E600070000][v0].nsp").write_bytes(b"\0" * 16)
        self.srv.lib.scan()
        doc = next(r for r in self.call("/api/lantern/v1/requests")[2]["requests"] if r["id"] == req["id"])
        self.assertEqual(doc["status"], "done")
        self.assertGreater(doc["updated"], doc["created"])
        self.assertEqual(self.call(f"/api/lantern/v1/admin/requests/{req['id']}", "POST",
                                   {"schema": 1, "decision": "decline"})[0], 409)


class Heartbeats(unittest.TestCase):
    """--heartbeat and --test-heartbeat (SPEC.md § 18.4)."""

    def test_beat_below_the_limit(self):
        srv = Running(USERS)
        self.addCleanup(srv.close)
        self.assertEqual((srv.server.heartbeat, srv.server.beat), (5, 0.25))
        hello = json.loads(srv.get("/api/lantern/v1/")[2])
        self.assertEqual(hello["limits"]["heartbeat"], 5)                       # what a client reads stays valid

    def test_bounds(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for args in (["--heartbeat", "4"], ["--heartbeat", "61"], ["--test-heartbeat", "20"], ["--test-heartbeat", "0"]):
            with self.assertRaises(SystemExit), unittest.mock.patch("sys.stderr"):
                ls.main(["--library", tmp.name, *args])


class Compression(unittest.TestCase):
    """JSON compressed (SPEC.md § 2.1): gzip only below Python 3.14, zstd from 3.14, never br."""

    def setUp(self):
        self.srv = Running()
        self.addCleanup(self.srv.close)

    def coding(self):
        return self.srv.get("/api/lantern/v1/apps", headers={"Accept-Encoding": "zstd, br, gzip"})[1].get(
            "Content-Encoding")

    def test_gzip_without_zstd(self):
        with unittest.mock.patch.object(ls, "zstd", None):
            self.assertEqual(self.coding(), "gzip")
            _, headers, body = self.srv.get("/api/lantern/v1/apps", headers={"Accept-Encoding": "br"})
            self.assertIsNone(headers.get("Content-Encoding"))                  # never br
            self.assertEqual(json.loads(body)["schema"], 1)

    @unittest.skipIf(ls.zstd is None, "zstd needs Python 3.14")
    def test_zstd_from_3_14(self):
        self.assertEqual(self.coding(), "zstd")


class Mirrors(unittest.TestCase):
    """The suite's --fetch-mirrors (SPEC.md § 19.2, L-19.2-2): a mirror read whole, without a credential."""

    def serve(self, folder):
        handler = functools.partial(Quiet, directory=str(folder))
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        return f"http://127.0.0.1:{httpd.server_address[1]}/"

    def run_with_mirror(self, lie=False):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder, served = Path(tmp.name) / "library", Path(tmp.name) / "mirror"
        url = self.serve(served)
        srv = Running(folder=folder, mirror=url)
        self.addCleanup(srv.close)
        shutil.copytree(folder, served)
        if lie:
            (served / library.MIRRORED).write_bytes(os.urandom((served / library.MIRRORED).stat().st_size))
        Quiet.seen = []
        return run_suite(srv.url, "--fetch-mirrors")

    def test_suite_reads_a_mirror(self):
        code, report = self.run_with_mirror()
        self.assertEqual(code, 0, report)
        self.assertRegex(report, r"PASS  § 19.2\s+peers.mirrors-fetch ")
        self.assertTrue(Quiet.seen)
        self.assertFalse([h for h in Quiet.seen if {"authorization", "signature", "cookie"} & set(h)])

    def test_suite_catches_a_lying_mirror(self):
        code, report = self.run_with_mirror(lie=True)
        self.assertEqual(code, 1, report)
        self.assertRegex(report, r"FAIL  § 19.2\s+peers.mirrors-fetch ")


class Quiet(http.server.SimpleHTTPRequestHandler):
    seen = []       # noqa: RUF012 - the headers of each request, lower-case names

    def log_message(self, *args):
        pass

    def do_GET(self):
        Quiet.seen.append({k.lower() for k in self.headers})
        super().do_GET()


class SuiteCatchesFaults(unittest.TestCase):
    """The suite fails a server that breaks one of 0.6's MUSTs."""

    def fails(self, handler, cid, users=None, token=False):
        srv = Running(users, handler=handler)
        self.addCleanup(srv.close)
        args = []
        if token:
            tok, _, key = srv.pair_keyed(ADMIN, EVERY_SCOPE)
            args = ["--token", tok, "--key", key]
        code, report = run_suite(srv.url, *args)
        self.assertEqual(code, 1, report)
        self.assertRegex(report, rf"FAIL  § \S+\s+{re.escape(cid)} ", report)

    def test_parameter_twice_taken(self):
        class Last(ls.Handler):
            def handle_any(self, method):
                path, _, query = self.path.partition("?")
                pairs = [p for p in query.split("&") if p]
                kept = {p.split("=", 1)[0]: p for p in pairs}           # the last of each, as 0.5 did
                self.path = path + ("?" + "&".join(kept.values()) if kept else "")
                super().handle_any(method)
        self.fails(Last, "routes.query-twice")

    def test_if_range_ignored(self):
        class Blind(ls.Handler):
            def handle_any(self, method):
                if "If-Range" in self.headers:
                    del self.headers["If-Range"]
                super().handle_any(method)
        self.fails(Blind, "files.if-range")

    def test_redirected(self):
        class Slash(ls.Handler):
            def handle_any(self, method):
                if self.path.endswith("/v1/apps/"):
                    self.send_response(301)
                    self.send_header("Location", self.path.rstrip("/"))
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                super().handle_any(method)
        self.fails(Slash, "routes.paths")

    def test_image_without_a_long_lifetime(self):
        """L-7.1-2 (a SHOULD): an image on the server's origin that its cache keeps no time gives a WARN."""
        class Iconic(ls.Handler):
            def send_doc(self, status, doc, headers=None, problem=False):
                if isinstance(doc, dict) and "titles" in doc and "unknown" in doc:
                    icon = {"url": f"{ls.BASE}/v1/files/{next(iter(self.server.library.files))}"}
                    doc = {**doc, "titles": [{**t, "icon": icon} for t in doc["titles"]]}
                super().send_doc(status, doc, headers, problem)
        srv = Running(handler=Iconic)
        self.addCleanup(srv.close)
        code, report = run_suite(srv.url)
        self.assertEqual(code, 0, report)
        self.assertRegex(report, r"WARN  § 7.1\s+titles.images ")

    def test_declined_reopened(self):
        class Lenient(ls.Handler):
            def admin_request(self, query, rid):
                for r in self.server.library.requests():
                    if r.get("id") == rid:
                        r["status"] = "open"            # whatever it was
                super().admin_request(query, rid)
        self.fails(Lenient, "admin.requests", USERS, token=True)


class Releases(unittest.TestCase):
    """tools/release.py (SPEC.md § 3.6): the files, their sums, the same bytes twice; the tag checked."""

    def release(self, out, *args):
        env = {**os.environ, "SOURCE_DATE_EPOCH": "1793345400"}
        return subprocess.run([sys.executable, str(ROOT / "tools" / "release.py"), "--out", str(out), *args],
                              capture_output=True, text=True, env=env, check=False)

    def test_files(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        v = re.search(r"^Draft (\d+\.\d+),", (ROOT / "SPEC.md").read_text(encoding="utf-8"), re.MULTILINE).group(1)
        a, b = Path(tmp.name) / "a", Path(tmp.name) / "b"
        run = self.release(a, "--tag", f"spec-v{v}", "--notes", str(Path(tmp.name) / "notes.md"))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.release(b)
        names = sorted(p.name for p in a.iterdir())
        self.assertEqual(names, sorted(["SHA256SUMS", "SPEC.md", "openapi.yaml", f"lantern-{v}.zip",
                                        f"lantern-schemas-{v}.zip", f"lantern-examples-{v}.zip",
                                        f"lantern-vectors-{v}.zip", f"lantern-conformance-{v}.zip"]))
        for name in names:
            self.assertEqual((a / name).read_bytes(), (b / name).read_bytes(), name)     # reproducible
        sums = dict(reversed(line.split("  ")) for line in (a / "SHA256SUMS").read_text().splitlines())
        self.assertEqual(sorted(sums), [n for n in names if n != "SHA256SUMS"])
        for name, digest in sums.items():
            self.assertEqual(hashlib.sha256((a / name).read_bytes()).hexdigest(), digest)
        with zipfile.ZipFile(a / f"lantern-{v}.zip") as z:
            members = set(z.namelist())
        self.assertTrue({"SPEC.md", "openapi.yaml", "schemas/v1/common.json", "conformance/run.py",
                         "vectors/grants.json", "examples/v1/apps.json", "LICENSES/CC-BY-4.0.txt"} <= members)
        self.assertFalse([m for m in members if "__pycache__" in m or m.startswith(("site/", "tests/"))])
        notes = (Path(tmp.name) / "notes.md").read_text()
        self.assertIn(f"gh attestation verify lantern-{v}.zip --repo JigSawFr/lantern", notes)
        self.assertIn(f"- {v} (", notes)                                        # its Changes
        wrong = self.release(Path(tmp.name) / "c", "--tag", "spec-v0.1")
        self.assertEqual(wrong.returncode, 1)
        self.assertFalse((Path(tmp.name) / "c").exists())

    def test_schema_ids(self):
        """SPEC.md § 3.2: each schema's $id is its stable address."""
        for path in sorted((ROOT / "schemas" / "v1").glob("*.json")):
            self.assertEqual(json.loads(path.read_text())["$id"],
                             f"https://lantern.boreale.dev/schemas/v1/{path.name}")


if __name__ == "__main__":
    unittest.main()
