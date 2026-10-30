"""The site's demo library (site/demo/README.md, tools/make_demo.py): a static
library the conformance suite passes at Lantern Static, the same from the same
source, and its trapped variant, which the suite refuses scenario by scenario;
and the drafts' comparison of tools/build_site.py."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_site  # noqa: E402
import make_demo  # noqa: E402


def tree(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(folder.rglob("*")) if p.is_file()}


class Demo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "demo"
        cls.summary = make_demo.build(cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_suite(self):
        """The demo reaches Lantern Static; each trapped scenario fails the checks it names, and no level."""
        self.assertEqual(make_demo.check(self.out), [])

    def test_content(self):
        """Several platforms, titles with their icons, signed homebrew, cheat sets; placeholders only."""
        hello = json.loads((self.out / "lantern.json").read_text())
        self.assertEqual(hello["platforms"], ["3ds", "android", "linux", "switch", "vita"])
        self.assertEqual(hello["static"]["generated"], json.loads(make_demo.SOURCE.read_text())["generated"])
        title = json.loads((self.out / "v1/titles/switch/0100ABCD00010000.json").read_text())
        icon = self.out / title["icon"]["url"]
        self.assertEqual(icon.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(hashlib.sha256(icon.read_bytes()).hexdigest(), title["icon"]["sha256"])
        page = json.loads((self.out / "v1/homebrew/switch/pages/1.json").read_text())
        self.assertTrue(any("signature" in e for e in page["items"]))
        apps = json.loads((self.out / "v1/apps/switch/pages/1.json").read_text())["items"]
        self.assertIn(b"placeholder", (self.out / apps[0]["file"]).read_bytes())
        self.assertTrue((self.out / "v1/cheats/switch/0100ABCD00010000.json").exists())

    def test_same_source_same_files(self):
        """Nothing of the build's time or of chance: the same source gives the same bytes."""
        with tempfile.TemporaryDirectory() as tmp:
            again = Path(tmp) / "demo"
            make_demo.build(again)
            first, second = tree(self.out), tree(again)
            self.assertEqual(first, second)

    def test_scenarios(self):
        """scenarios.json (schema 1) lists every scenario with its root, what a client does and the checks."""
        doc = json.loads((self.out / "trapped/scenarios.json").read_text())
        self.assertEqual(doc["schema"], 1)
        names = [s["name"] for s in doc["scenarios"]]
        self.assertEqual(names, [s[0] for s in make_demo.SCENARIOS])
        for s in doc["scenarios"]:
            self.assertTrue((self.out / "trapped" / s["root"] / "lantern.json").exists(), s["name"])
            self.assertTrue(s["expect"] and s["suite"])
        big = self.out / "trapped/oversized-document/v1/apps/switch/pages/1.json"
        self.assertGreater(big.stat().st_size, 32 << 20)


class Source(unittest.TestCase):
    """demo.json's reader: absent, of a newer schema, with a field it does not know."""

    def write(self, doc):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "demo.json"
        if doc is not None:
            path.write_text(json.dumps(doc))
        return path

    def test_absent(self):
        self.assertIsNone(make_demo.read_source(self.write(None)))

    def test_newer(self):
        source = json.loads(make_demo.SOURCE.read_text())
        path = self.write({**source, "schema": 2})
        self.assertIsNone(make_demo.read_source(path))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(make_demo.build(Path(tmp) / "demo", path))       # no demo, no error
            self.assertFalse((Path(tmp) / "demo").exists())

    def test_unknown_field(self):
        source = json.loads(make_demo.SOURCE.read_text())
        doc = make_demo.read_source(self.write({**source, "x-later": {"a": 1}}))
        self.assertEqual(doc["name"], source["name"])


class Drafts(unittest.TestCase):
    """build_site.compared(): the sections a draft added, changed, renamed, removed and renumbered."""

    def test_compared(self):
        before = "# T\n\n## 1. Intro\n\nHello there.\n\n## 2. Old part\n\nGone soon.\n\n## 3. Kept\n\nSee § 1.\n" \
                 "\n### 3.1 Detail\n\nThe same words, many of them, kept as they are here.\n"
        after = "# T\n\n## 1. Intro\n\nHello there, and more.\n\n## 2. Kept\n\nSee § 3.\n\n### 2.1 Details\n\n" \
                "The same words, many of them, kept as they are here.\n\n## 3. New part\n\nNew.\n"
        d = build_site.compared(build_site.outline(before), build_site.outline(after))
        self.assertEqual([o["title"] for o in d["added"]], ["3. New part"])
        self.assertEqual([o["title"] for o in d["removed"]], ["2. Old part"])
        self.assertEqual([(b["title"], o["title"]) for b, o in d["changed"]], [("1. Intro", "1. Intro")])
        self.assertEqual([(b["title"], o["title"]) for b, o in d["renamed"]], [("3.1 Detail", "2.1 Details")])
        self.assertEqual([(b["number"], o["number"]) for b, o in d["renumbered"]], [("3", "2")])


if __name__ == "__main__":
    unittest.main()
