"""The page's validator (site/assets/check.js, site/check.html): under Node, it agrees with tools/check_schemas.py
(the Python jsonschema) on every example of examples/v1/ and every refused one (examples/v1/invalid/), and its
page names every schema.

    python3 -m unittest discover -s tests
"""
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class Validator(unittest.TestCase):
    def test_it_agrees_with_jsonschema(self):
        run = subprocess.run(["node", str(ROOT / "tests" / "check_runner.js")], capture_output=True, encoding="utf-8", timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        out = json.loads(run.stdout)
        self.assertGreater(out["checked"], 100)
        self.assertEqual(out["valid"], [], "an example the page refuses")
        self.assertEqual(out["invalid"], [], "a refused example the page accepts")
        self.assertEqual(out["reader"], [], "a text on which the page's reader of JSON errors disagrees with JSON.parse")


class Page(unittest.TestCase):
    def test_the_page_offers_every_schema(self):
        import build_site
        names = build_site.schema_names()
        self.assertEqual(names, sorted(p.stem for p in (ROOT / "schemas" / "v1").glob("*.json")))
        self.assertIn("handshake", names)


if __name__ == "__main__":
    unittest.main()
