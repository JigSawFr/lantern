"""What draft 0.7 adds, on the reference server and the suite: differential
updates (SPEC.md § 22), browsers (§ 2.5, Annex A.7), canonical JSON
(§ 2.3), a pairing's poll after a slow_down (§ 5.2), an upload's chunk size
(§ 9.3), images on the server's origin (§ 7.1), and how a client finds a
static library (§ 21.3).

    python3 -m unittest discover -s tests

Each test names the requirements it checks (SPEC.md § 3.5).
"""
import hashlib
import io
import json
import sys
import tempfile
import unittest
import unittest.mock
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "conformance"))

import lantern_client as client
import library
from test_conformance import USERS, Running, run_suite
from test_v05 import Live

from server import cdc, static
from server import lantern_server as ls

ORIGIN = "https://app.example.org"


def vector(name):
    return json.loads((ROOT / "vectors" / f"{name}.json").read_text(encoding="utf-8"))


def stream(seed, size):
    out, i = bytearray(), 0
    while len(out) < size:
        out += hashlib.sha256(seed.encode() + i.to_bytes(8, "big")).digest()
        i += 1
    return bytes(out[:size])


class Vectors(unittest.TestCase):
    """The 0.7 vectors against both references, the server's and the client's."""

    def test_chunks(self):
        """L-22.1-1, L-22.3-1: lantern-cdc-1's cuts and indexes; the indexes a client refuses."""
        v = vector("chunks")
        gear = b"".join(g.to_bytes(8, "big") for g in cdc.GEAR)
        self.assertEqual(hashlib.sha256(gear).hexdigest(), v["gear"]["sha256"])
        self.assertEqual(cdc.GEAR, client.GEAR)
        base = stream("lantern-cdc-1 vector", 1000000)
        made = {"": b"", "lantern-cdc-1 vector": None}
        for case in v["cases"]:
            f = case["file"]
            if "zeros" in f:
                data = bytes(f["zeros"])
            elif "edit" in f:
                data = base[:300000] + stream("an insertion", 777) + base[300000:700000] + base[710000:]
            else:
                data = stream(f["seed"], f["size"]) if made.get(f["seed"]) is None else made[f["seed"]]
            size = case["chunker"]["size"]
            self.assertEqual([o for o, _ in cdc.cut(data, size)], case["cuts"], case["name"])
            for raw in (cdc.index(data, size)[1], client.chunk_index(data, size)[1]):
                self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (case["index_size"], case["index_sha256"]))
        for r in v["refused"]:
            with self.assertRaises(client.Unusable, msg=r["name"]):
                client.read_chunk_index(r["index"].encode(), r["chunks"], r["file_sha256"], r["file_size"])

    def test_update(self):
        """L-22.3-2: the newer version put together from the older, reading only the vector's ranges."""
        v = vector("chunks")
        base = stream("lantern-cdc-1 vector", 1000000)
        new = base[:300000] + stream("an insertion", 777) + base[300000:700000] + base[710000:]
        index, _ = client.chunk_index(new, 65536)
        asked = []

        def read(a, b):
            asked.append(f"bytes={a}-{b}")
            return new[a:b + 1]
        self.assertEqual(client.assemble(index, [base], read, hashlib.sha256(new).hexdigest(), len(new)), new)
        self.assertEqual(asked, v["update"]["ranges"])
        with self.assertRaises(client.Refused):      # a source that lies: the chunk is caught, nothing kept
            client.assemble(index, [base], lambda a, b: bytes(b - a + 1), hashlib.sha256(new).hexdigest(), len(new))

    def test_canonical_json(self):
        """L-20.4-1: canonical JSON (RFC 8785), numbers as ECMAScript writes them, both references alike."""
        for case in vector("canonical-json")["cases"]:
            value = json.loads(case["json"])
            self.assertEqual(cdc.canonical(value).decode(), case["canonical"], case["name"])
            self.assertEqual(client.canonical(value).decode(), case["canonical"], case["name"])

    def test_sync_numbers(self):
        """L-20.4-1: the merge rule over values with numbers: 1.0 and 1 the same, the server's kept."""
        for case in vector("sync-merge")["cases"]:
            if not case["have"] or "value" not in case["have"] or "value" not in case["sent"]:
                continue
            for wins in (ls.sync_wins, client.sync_wins):
                sent = dict(case["sent"], updated=case["kept"]["updated"] if case["replaced"] else case["sent"]["updated"])
                if "ahead" in case["name"] or "milliseconds" in case["name"]:
                    continue
                self.assertEqual(wins(sent, case["have"]), case["replaced"], case["name"])


class Deltas(unittest.TestCase):
    """SPEC.md § 22 on the reference server."""

    def setUp(self):
        self.srv = Running()
        self.addCleanup(self.srv.close)

    def test_indexes_and_route(self):
        """L-22.1-1, L-22.1-2: the two versions of an update carry chunks; their indexes by url and by SHA-256."""
        apps = json.loads(self.srv.get("/api/lantern/v1/apps?page_size=500")[2])["items"]
        chunked = [a for a in apps if a.get("chunks")]
        self.assertEqual(sorted(a["version_code"] for a in chunked), [65536, 196608])
        for a in chunked:
            status, headers, raw = self.srv.get(a["chunks"]["url"])
            self.assertEqual((status, hashlib.sha256(raw).hexdigest()), (200, a["chunks"]["sha256"]))
            index = client.read_chunk_index(raw, a["chunks"], a["sha256"], a["size"])
            self.assertEqual(client.canonical(index), raw)
        self.assertEqual(self.srv.get("/api/lantern/v1/chunks/sha256/" + "0" * 64)[0], 404)
        small = next(a for a in apps if not a.get("chunks"))
        self.assertEqual(self.srv.get("/api/lantern/v1/chunks/sha256/" + small["sha256"])[0], 404)
        old, new = sorted(chunked, key=lambda a: a["version_code"])
        seed = self.srv.get(old["file"])[2]
        index = json.loads(self.srv.get(new["chunks"]["url"])[2])
        plan = client.delta_plan(index, [seed])
        read = sum(n for _, n, _, src in plan if src is None)
        self.assertLess(read, new["size"] // 2)              # most of it comes from the older version

    def test_homebrew_package_and_static_export(self):
        """L-22.1-1, L-21.1-1: a homebrew zip cut into chunks; the export holds the indexes and the images."""
        folder = self.srv.root / "homebrew" / "chunky"
        folder.mkdir(parents=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            z.writestr("switch/org.example.chunky/chunky.nro", library.nro("Chunky", "Ines", "1.0.0", stream("c", 200000)))
        (folder / "chunky.zip").write_bytes(buf.getvalue())
        (folder / "homebrew.json").write_text(json.dumps({"schema": 1, "id": "org.example.chunky", "build": 100}))
        self.srv.lib.scan()
        entry = json.loads(self.srv.get("/api/lantern/v1/homebrew/org.example.chunky?platform=switch")[2])
        self.assertIn("chunks", entry["package"])
        with tempfile.TemporaryDirectory() as out:
            done = static.export(ls, self.srv.lib, out, 4)
            self.assertGreaterEqual(done["indexes"], 3)
            code, report = run_suite("--static", out)
            self.assertEqual(code, 0, report)
            self.assertRegex(report, r"PASS  § 22.1  static.chunks .*\n +[0-9]+ index\(es\), [1-9]")
            hello = json.loads((Path(out) / "lantern.json").read_text())
            self.assertEqual(hello["features"]["deltas"], 1)
            title = json.loads((Path(out) / "v1/titles/switch/0100ABCD00010000.json").read_text())
            self.assertTrue(title["icon"]["url"].startswith("v1/blobs/sha256/"))

    def test_off(self):
        """L-4.2-7: --deltas-max 0: no chunks, the family at 0, its route 404."""
        self.srv.lib.deltas = (ls.DELTAS_MIN, 0)
        self.srv.lib.indexes = {}
        self.srv.lib.scan()
        hello = json.loads(self.srv.get("/api/lantern/v1/")[2])
        self.assertEqual(hello["features"]["deltas"], 0)
        apps = json.loads(self.srv.get("/api/lantern/v1/apps?page_size=500")[2])["items"]
        self.assertFalse([a for a in apps if a.get("chunks")])


class Browsers(unittest.TestCase):
    """SPEC.md § 2.5 and Annex A.7 on the reference server."""

    def setUp(self):
        self.srv = Running(cors=(ORIGIN,))
        self.addCleanup(self.srv.close)

    def test_preflight_and_answers(self):
        """L-2.5-2, L-2.5-3, L-2.5-5: a preflight answered without a token; every answer to the origin carries
        its headers, errors included; another origin none; no credential ever."""
        status, h, _ = self.srv.request("/api/lantern/v1/sync/wishes", method="OPTIONS", headers={
            "Origin": ORIGIN, "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization, if-match, signature-input, x-other"})
        self.assertEqual((status, h["Access-Control-Allow-Origin"]), (204, ORIGIN))
        self.assertEqual(h["Access-Control-Allow-Headers"], "Authorization, If-Match, Signature-Input")
        self.assertIn("PATCH", h["Access-Control-Allow-Methods"])
        self.assertGreaterEqual(int(h["Access-Control-Max-Age"]), 600)
        status, h, _ = self.srv.get("/api/lantern/v1/no-such-route", headers={"Origin": ORIGIN})
        self.assertEqual((status, h["Access-Control-Allow-Origin"]), (404, ORIGIN))
        self.assertIn("WWW-Authenticate", h["Access-Control-Expose-Headers"])
        self.assertIn("Origin", h["Vary"])
        status, h, _ = self.srv.get("/api/lantern/v1/apps", headers={"Origin": "https://other.example.org"})
        self.assertEqual((status, h.get("Access-Control-Allow-Origin")), (200, None))
        status, h, _ = self.srv.request("/api/lantern/v1/apps", method="OPTIONS", headers={
            "Origin": "https://other.example.org", "Access-Control-Request-Method": "GET"})
        self.assertEqual(status, 405)
        self.assertIsNone(h.get("Access-Control-Allow-Credentials"))
        status, h, _ = self.srv.get("/pair", headers={"Origin": ORIGIN})      # the server's own page: not a route
        self.assertIsNone(h.get("Access-Control-Allow-Origin"))

    def test_suite_with_an_origin(self):
        """L-2.5-2, L-2.5-3, L-A.7-1: the suite's --origin checks pass on the reference, and fail on a server
        that leaves its errors without Access-Control-Allow-Origin."""
        code, report = run_suite(self.srv.url, "--origin", ORIGIN)
        self.assertEqual(code, 0, report)
        for cid in ("cors.preflight", "cors.responses", "cors.other-origin", "cors.credentials", "platforms.web",
                    "deltas.update", "titles.images"):
            self.assertRegex(report, rf"PASS  § [0-9.A]+ +{cid.replace('.', '[.]')} ")

        class Bare(ls.Handler):
            def send_head(self, status, length, headers, encodings=True):
                if status >= 400:
                    self.cors = None
                super().send_head(status, length, headers, encodings)
        srv = Running(handler=Bare, cors=(ORIGIN,))
        self.addCleanup(srv.close)
        code, report = run_suite(srv.url, "--origin", ORIGIN)
        self.assertEqual(code, 1)
        self.assertRegex(report, r"FAIL  § 2.5   cors.responses ")

    def test_nothing_of_the_web(self):
        """L-A.7-1: an app of platform web in library.json is not served, nor web listed."""
        meta = json.loads((self.srv.root / "library.json").read_text())
        (self.srv.root / "web.zip").write_bytes(b"x" * 10)
        meta["apps"].append({"file": "web.zip", "platform": "web", "title_id": "org.example.web", "name": "Web"})
        (self.srv.root / "library.json").write_text(json.dumps(meta))
        self.srv.lib.scan()
        hello = json.loads(self.srv.get("/api/lantern/v1/")[2])
        self.assertNotIn("web", hello["platforms"])
        self.assertEqual(json.loads(self.srv.get("/api/lantern/v1/apps?platform=web")[2])["items"], [])


class Images(unittest.TestCase):
    """L-7.1-2: the suite finds the images of the server's origin whichever app the server lists first."""

    def test_first_app_without_images(self):
        """The android app, whose title has no image, listed first: the switch title's icon is still checked."""
        srv = Running()
        self.addCleanup(srv.close)
        meta = json.loads((srv.root / "library.json").read_text())
        for entry in meta["apps"]:
            if entry.get("platform") == "android":
                entry["name"] = "Aurora Tales"     # before "Frostline Tales" by name, whatever the ids
        (srv.root / "library.json").write_text(json.dumps(meta))
        srv.lib.scan()
        first = json.loads(srv.get("/api/lantern/v1/apps")[2])["items"][0]
        self.assertEqual(first["platform"], "android")
        code, report = run_suite(srv.url)
        self.assertEqual(code, 0, report)
        self.assertRegex(report, r"PASS  § 7.1\s+titles[.]images ")


class Pairing(unittest.TestCase):
    """L-5.2-15: a client polling faster than interval is not shut out."""

    def test_fast_poller_gets_its_token(self):
        clock = [1000.0]
        real = ls.time.monotonic
        ls.time.monotonic = lambda: clock[0]
        self.addCleanup(setattr, ls.time, "monotonic", real)
        accounts = ls.Accounts(None)
        pairing = ls.Pairing(unittest.mock.Mock(issue=lambda *a, **k: "et_x"), accounts, interval=5)
        pairing.grant = lambda entry, user, scopes=None: ["library"]
        entry = pairing.start("Lea's Switch", ["library"])
        self.assertIsNone(pairing.poll(entry["pid"]))
        refused = 0
        for step in range(40):              # every 3 seconds, faster than the interval of 5
            clock[0] += 3
            if step == 5:
                pairing.approve(entry, "lea")
            try:
                doc = pairing.poll(entry["pid"])
            except ls.Problem as p:
                self.assertEqual(p.status, 429)
                self.assertLessEqual(int(p.headers["Retry-After"]), 5)
                refused += 1
                continue
            if doc is not None:
                self.assertEqual(doc["token"], "et_x")
                break
        else:
            self.fail("the token never came")
        self.assertGreater(refused, 0)


class StaticLibraries(unittest.TestCase):
    """L-21.3-3: where a client finds the library an address names."""

    def test_find_library(self):
        server = json.dumps({"schema": 1, "base": "/api/lantern"}).encode()
        lib = json.dumps({"schema": 1, "base": ".", "static": {"generated": "2026-10-30T18:00:00Z",
                                                                 "page_size": 100}}).encode()
        newer = json.dumps({"schema": 2, "base": "/api/lantern"}).encode()

        def reader(files):
            return lambda url: files.get(url)
        root = "https://lea.example.org/library/"
        well_known = "https://lea.example.org/.well-known/lantern"
        self.assertEqual(client.find_library(root, reader({well_known: server, root + "lantern.json": lib}))[0],
                         "server")
        self.assertEqual(client.find_library(root, reader({root + "lantern.json": lib})), ("static", json.loads(lib), root))
        self.assertEqual(client.find_library(root, reader({well_known: newer, root + "lantern.json": lib}))[0], "static")
        self.assertIsNone(client.find_library("https://lea.example.org/", reader({well_known: lib})))
        self.assertEqual(client.find_library("/media/usb/library", reader({"/media/usb/library/lantern.json": lib}))[0],
                         "static")
        self.assertIsNone(client.find_library(root, reader({root + "lantern.json": b"not json"})))


class Compression(unittest.TestCase):
    """L-2.1-1: the suite reads the bodies it asks for: zstd only when its Python decodes it, never br."""

    def test_readable(self):
        from test_conformance import conformance
        self.assertEqual("zstd" in conformance.READABLE, conformance.zstd is not None)
        self.assertNotIn("br", conformance.READABLE)


class Uploads(Live):
    """L-9.3-3: HEAD on an upload gives its chunk size, for a client that kept only its address."""
    users = USERS

    def test_head_gives_the_chunk_size(self):
        data = b"\0" * 5000
        status, _, doc = self.call("/api/lantern/v1/saves/0100FFFF00090000/uploads?platform=switch", "POST",
                                   {"schema": 1, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        self.assertEqual(status, 201, doc)
        status, headers, _ = self.call(doc["upload"], "HEAD")
        self.assertEqual((status, headers["Lantern-Chunk-Size"]), (204, str(doc["chunk_size"])))


if __name__ == "__main__":
    unittest.main()
