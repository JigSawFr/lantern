"""What draft 0.9 adds, on the reference server and the suite: `requires`,
`includes` and variants of an app (SPEC.md § 6.1), the listing's `format`
filter (§ 6.2), and what is missing for a device that says the formats it
reads and the tokens it provides (§ 6.3).

    python3 -m unittest discover -s tests

Each test names the requirements it checks (SPEC.md § 3.5).
"""
import json
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "conformance"))

import lantern_client as client
from test_conformance import Running, run_suite

from server import lantern_server as ls

API = "/api/lantern"
SWITCH = {"Lantern-Platform": "switch"}
MOSS_BASE, MOSS_UPDATE = "0100EFEF00020000", "0100EFEF00020800"


def vector(name):
    return json.loads((ROOT / "vectors" / f"{name}.json").read_text(encoding="utf-8"))


def library_missing(apps, installed, want, formats=None, satisfies=None):
    """Library.missing() over `apps`, without a folder."""
    lib = types.SimpleNamespace(lock=threading.RLock(), apps={a["id"]: {"doc": a} for a in apps})
    found = ls.Library.missing(lib, "switch", installed, set(want), None if formats is None else set(formats),
                               None if satisfies is None else set(satisfies))
    return sorted(e["doc"]["id"] for e in found)


class Vectors(unittest.TestCase):
    """vectors/app-requires.json against both references."""

    def test_install(self):
        """L-6.1-3, L-6.1-4, L-6.1-5: a client installs only what it knows, meets, and does not already have."""
        for c in vector("app-requires")["install"]:
            decision, why = client.install_decision(c["app"], c["formats"], c["satisfies"], c["installed"])
            self.assertEqual((decision, len(why)), (c["decision"], c["reasons"]), c["name"])

    def test_variants(self):
        """Annex B.15: the fewest requires, then the smallest size."""
        v = vector("app-requires")["variants"]
        self.assertEqual(client.prefer_variant(v["apps"])["id"], v["preferred"])
        self.assertEqual(client.prefer_variant(list(reversed(v["apps"])))["id"], v["preferred"])

    def test_missing(self):
        """L-6.3-1, L-6.3-3, L-6.3-4: what a server leaves out, and counts as installed."""
        v = vector("app-requires")
        for c in v["missing"]:
            got = library_missing(v["library"], c["installed"], c["want"], c.get("formats"), c.get("satisfies"))
            self.assertEqual(got, c["missing"], c["name"])


class Reference(unittest.TestCase):
    """The reference server over tests/library.py's Moss and Ember: a base, two updates (one with another
    format and a token), and a base stored with the firmware's compression layer that includes the update."""

    @classmethod
    def setUpClass(cls):
        cls.srv = Running()
        cls.apps = {}
        status, doc = cls.srv.get_json(f"{API}/v1/apps?page_size=100")
        assert status == 200, doc
        for a in doc["items"]:
            cls.apps.setdefault((a["app_id"], a["version_code"], a["format"]), a)

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def listing(self, query):
        status, _, body = self.srv.get(f"{API}/v1/apps?{query}", headers=SWITCH)
        self.assertEqual(status, 200, body)
        return json.loads(body)["items"]

    def missing(self, installed, want=("update",), **extra):
        body = {"schema": 1, "installed": installed, "want": list(want), **extra}
        status, _, raw = self.srv.request(f"{API}/v1/apps/missing", headers=SWITCH, data=body)
        self.assertEqual(status, 200, raw)
        return sorted((a["app_id"], a["version_code"], a["format"]) for a in json.loads(raw)["items"])

    def test_the_tag_and_the_entry_give_requires_and_includes(self):
        """L-6.1-4, L-6.1-5, Annex A.1: [LZ4] on an nsp is fs-compression and sigpatch; library.json gives the rest."""
        packed = self.apps[(MOSS_BASE, 65536, "nsp")]
        self.assertEqual(packed["requires"], ["fs-compression", "sigpatch"])
        self.assertEqual(packed["includes"], [{"app_id": MOSS_UPDATE, "version_code": 131072}])
        alt = self.apps[(MOSS_UPDATE, 131072, "nsz")]
        self.assertEqual(alt["requires"], ["ncz-lz4"])
        self.assertNotIn("includes", alt)
        for key, app in self.apps.items():
            if key not in ((MOSS_BASE, 65536, "nsp"), (MOSS_UPDATE, 131072, "nsz")):
                self.assertNotIn("requires", app, key)
                self.assertNotIn("includes", app, key)

    def test_variants_are_separate_apps(self):
        """§ 6.1: the same app_id and version_code in two formats or with other requires: own id, size, sha256, file."""
        same = [a for a in self.listing("title_id=" + MOSS_BASE)
                if (a["app_id"], a["version_code"]) == (MOSS_UPDATE, 131072)]
        self.assertEqual(sorted(a["format"] for a in same), ["nsp", "nsz"])
        for field in ("id", "sha256", "file"):
            self.assertEqual(len({a[field] for a in same}), 2, field)
        paper = [a for a in self.listing("title_id=0100A1B200030000")]
        self.assertEqual(sorted(a["format"] for a in paper), ["nsp", "xcz"])

    def test_format_filter(self):
        """L-6.2-7: format filters; a format no app has gives an empty list, not an error."""
        for fmt in ("nsp", "nsz", "xci", "xcz", "apk"):
            got = self.listing(f"format={fmt}&platform=" + ("android" if fmt == "apk" else "switch"))
            self.assertTrue(got, fmt)
            self.assertEqual({a["format"] for a in got}, {fmt})
        every = self.listing("page_size=100")
        self.assertEqual(len(self.listing("format=nsz&page_size=100")), len([a for a in every if a["format"] == "nsz"]))
        for value in ("nope", "NSP", "x-nothing", "a%2Cb"):
            self.assertEqual(self.listing(f"format={value}"), [], value)

    def test_format_filter_pages(self):
        """L-6.2-3, L-6.2-7: a page of a filtered listing leads to the rest of it, and only to it."""
        seen, query = [], "format=nsp&platform=switch&page_size=2"
        status, doc = self.srv.get_json(f"{API}/v1/apps?{query}")
        while True:
            self.assertEqual(status, 200, doc)
            seen += doc["items"]
            if not doc["next"]:
                break
            status, doc = self.srv.get_json(f"{API}/v1/apps?{query}&cursor={doc['next']}")
        self.assertEqual({a["format"] for a in seen}, {"nsp"})
        self.assertEqual(len(seen), len({a["id"] for a in seen}))
        self.assertEqual(len(seen), len(self.listing("format=nsp&platform=switch&page_size=100")))
        status, doc = self.srv.get_json(f"{API}/v1/apps?{query}")
        status, _, _ = self.srv.get(f"{API}/v1/apps?platform=switch&page_size=2&cursor={doc['next']}")
        self.assertIn(status, (400, 410), "a cursor of another filter")

    def test_missing_without_the_new_fields_gives_every_variant(self):
        """L-6.3-3: no formats and no satisfies, no filter."""
        base = [{"app_id": MOSS_BASE, "version_code": 0}]
        self.assertEqual(self.missing(base), [(MOSS_UPDATE, 131072, "nsp"), (MOSS_UPDATE, 131072, "nsz")])

    def test_missing_formats_and_satisfies(self):
        """L-6.3-1, L-6.3-3: formats and satisfies leave out what the device cannot install."""
        base = [{"app_id": MOSS_BASE, "version_code": 0}]
        nsp, nsz = (MOSS_UPDATE, 131072, "nsp"), (MOSS_UPDATE, 131072, "nsz")
        self.assertEqual(self.missing(base, formats=["nsp"]), [nsp])
        self.assertEqual(self.missing(base, formats=["nsz", "nsp"]), [nsp, nsz])
        self.assertEqual(self.missing(base, formats=["xci"]), [])
        self.assertEqual(self.missing(base, formats=[]), [])
        self.assertEqual(self.missing(base, satisfies=[]), [nsp], "an app with no requires always passes")
        self.assertEqual(self.missing(base, satisfies=["ncz-lz4"]), [nsp, nsz])
        self.assertEqual(self.missing(base, satisfies=["sigpatch"]), [nsp])
        self.assertEqual(self.missing(base, formats=["nsz"], satisfies=[]), [])
        self.assertEqual(self.missing(base, formats=["nsz"], satisfies=["ncz-lz4", "unknown-token"]), [nsz])
        bases = self.missing([], ("base",), satisfies=[])
        self.assertNotIn((MOSS_BASE, 65536, "nsp"), bases, "the base that needs fs-compression")
        self.assertIn((MOSS_BASE, 0, "xci"), bases)
        self.assertIn((MOSS_BASE, 65536, "nsp"), self.missing([], ("base",), satisfies=["fs-compression", "sigpatch"]))
        self.assertNotIn((MOSS_BASE, 65536, "nsp"), self.missing([], ("base",), satisfies=["fs-compression"]))

    def test_missing_counts_what_an_installed_app_includes(self):
        """L-6.3-4: an installed app that equals one of ours also installs its includes."""
        nsp, nsz = (MOSS_UPDATE, 131072, "nsp"), (MOSS_UPDATE, 131072, "nsz")
        self.assertEqual(self.missing([{"app_id": MOSS_BASE, "version_code": 0}]), [nsp, nsz])
        self.assertEqual(self.missing([{"app_id": MOSS_BASE, "version_code": 65536}]), [],
                         "the packed base has the update inside")
        self.assertEqual(self.missing([{"app_id": MOSS_BASE, "version_code": 65536}], ("update", "dlc")), [])
        self.assertEqual(self.missing([{"app_id": MOSS_BASE, "version_code": 1}]), [nsp, nsz],
                         "a version no app of ours has includes nothing")

    def test_missing_refuses_malformed_arrays(self):
        """L-6.3-2: formats or satisfies that are not an array of at most 16 words give 400."""
        too_long = [f"w{n}" for n in range(17)]
        for key, value in (("formats", "nsp"), ("formats", [1]), ("formats", ["NSP"]), ("formats", ["a" * 17]),
                           ("formats", too_long), ("formats", None), ("formats", {"nsp": 1}),
                           ("satisfies", "sigpatch"), ("satisfies", ["Sig_Patch"]), ("satisfies", ["-x"]),
                           ("satisfies", ["a" * 33]), ("satisfies", too_long), ("satisfies", [["x"]])):
            body = {"schema": 1, "installed": [], "want": ["base"], key: value}
            status, _, raw = self.srv.request(f"{API}/v1/apps/missing", headers=SWITCH, data=body)
            self.assertEqual(status, 400, (key, value, raw))
            self.assertEqual(json.loads(raw)["code"], "bad_request")
        body = {"schema": 1, "installed": [], "want": ["base"], "formats": [f"w{n}" for n in range(16)],
                "satisfies": [f"t{n}" for n in range(16)]}
        self.assertEqual(self.srv.request(f"{API}/v1/apps/missing", headers=SWITCH, data=body)[0], 200)


class Scanning(unittest.TestCase):
    """How the reference server reads a folder's names and library.json (server/lantern_server.py, identify())."""

    def scan(self, files, meta=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "shelf"
        for name in files:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_bytes(b"x" * 20)
        if meta is not None:
            (root / "library.json").write_text(json.dumps({"schema": 1, "apps": meta}), encoding="utf-8")
        lib = ls.Library(root, Path(tmp.name) / "state.json")
        return {a["doc"]["format"] + ":" + a["doc"]["id"]: a["doc"] for a in lib.apps.values()}

    def test_the_tag_is_for_an_nsp_in_any_case(self):
        docs = self.scan(["A [0100ABCD00010000][v0][lz4].nsp", "B [0100ABCD00030000][v0][LZ4].nsz",
                          "C [0100ABCD00050000][v0][Lz4].nsp", "D [0100ABCD00070000][v0] [LZ4 tag].nsp"])
        by_name = {d["name"]: d for d in docs.values()}
        self.assertEqual(by_name["A"]["requires"], ["fs-compression", "sigpatch"])
        self.assertNotIn("requires", by_name["B"], "an nsz is not stored with the firmware's layer")
        self.assertEqual(by_name["C"]["requires"], ["fs-compression", "sigpatch"])
        self.assertNotIn("requires", by_name["D"], "a tag is exactly [LZ4]")

    def test_an_entry_replaces_what_the_tag_says(self):
        file = "A [0100ABCD00010000][v0][LZ4].nsp"
        docs = self.scan([file], [{"file": file, "requires": ["sigpatch"]}])
        self.assertEqual(next(iter(docs.values()))["requires"], ["sigpatch"])
        docs = self.scan([file], [{"file": file, "requires": []}])
        self.assertNotIn("requires", next(iter(docs.values())))

    def test_malformed_requires_and_includes_are_dropped(self):
        """§ 6.1: at most 8 tokens, and at most 16 includes; a bad one is not served, the app is."""
        file = "A [0100ABCD00010000][v0].nsp"
        for entry in ({"requires": ["Sig"]}, {"requires": "sigpatch"}, {"requires": [f"t{n}" for n in range(9)]},
                      {"includes": [{"app_id": "0100ABCD00010800"}]}, {"includes": [{"app_id": "x y", "version_code": 1}]},
                      {"includes": [{"app_id": "0100ABCD00010800", "version_code": 1}] * 17}, {"includes": {}}):
            docs = self.scan([file], [{"file": file, **entry}])
            doc = next(iter(docs.values()))
            self.assertNotIn("requires", doc, entry)
            self.assertNotIn("includes", doc, entry)
        docs = self.scan([file], [{"file": file, "requires": ["a", "a", "b"], "includes": [
            {"app_id": "0100ABCD00010800", "version_code": 5, "x-more": 1}]}])
        doc = next(iter(docs.values()))
        self.assertEqual((doc["requires"], doc["includes"]), (["a", "b"], [{"app_id": "0100ABCD00010800", "version_code": 5}]))


class SuiteAgainstReference(unittest.TestCase):
    def test_the_new_checks_pass_and_see_something(self):
        """The suite's checks of 0.9 pass on the reference server's library, and none skips."""
        srv = Running()
        self.addCleanup(srv.close)
        code, report = run_suite(srv.url)
        self.assertEqual(code, 0, report)
        for cid in ("apps.format", "missing.formats", "missing.satisfies", "missing.arrays", "missing.includes"):
            self.assertRegex(report, rf"PASS  § \S+\s+{cid} ", report)
        self.assertIn("Levels reached (SPEC.md § 17, draft 0.11)", report)


if __name__ == "__main__":
    unittest.main()
