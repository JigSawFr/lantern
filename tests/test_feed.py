"""The Atom feed of the drafts (tools/build_site.py, atom_feed()): well formed, one entry per draft the text's
"Changes" tells of, newest first, each with its own id, its date and a page of the site.

    python3 -m unittest discover -s tests
"""
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_site  # noqa: E402

ATOM = "{http://www.w3.org/2005/Atom}"


class Feed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        notes = build_site.changes_notes((ROOT / "SPEC.md").read_text(encoding="utf-8"))
        cls.notes = notes
        cls.root = ET.fromstring(build_site.atom_feed(notes))

    def test_one_entry_per_draft_newest_first(self):
        titles = [e.find(ATOM + "title").text for e in self.root.findall(ATOM + "entry")]
        drafts = [v for v, _, _ in build_site.DRAFTS if v in self.notes]
        self.assertEqual(titles, [f"Draft {v}" for v in reversed(drafts)])
        self.assertEqual(titles[0], f"Draft {build_site.DRAFT}")

    def test_each_entry_has_what_a_reader_needs(self):
        ids = set()
        for e in self.root.findall(ATOM + "entry"):
            i = e.find(ATOM + "id").text
            self.assertNotIn(i, ids)
            ids.add(i)
            self.assertRegex(e.find(ATOM + "updated").text, r"^\d{4}-\d{2}-\d{2}T00:00:00Z$")
            href = e.find(ATOM + "link").get("href")
            self.assertRegex(href, r"^https://[^/]+/spec/\d+\.\d+/$")
            self.assertTrue(e.find(ATOM + "summary").text.strip())

    def test_the_feed_says_who_and_when(self):
        for tag in ("id", "title", "updated"):
            self.assertIsNotNone(self.root.find(ATOM + tag), tag)
        self.assertIsNotNone(self.root.find(ATOM + "author/" + ATOM + "name"))
        dates = [e.find(ATOM + "updated").text for e in self.root.findall(ATOM + "entry")]
        self.assertEqual(self.root.find(ATOM + "updated").text, max(dates))
        self.assertTrue(re.match(r"^tag:", self.root.find(ATOM + "id").text))


if __name__ == "__main__":
    unittest.main()
