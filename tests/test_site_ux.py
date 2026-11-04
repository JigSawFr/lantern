"""Small things of the site's pages that a catalog or a refactor could break (tools/build_site.py).

    python3 -m unittest discover -s tests
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_site  # noqa: E402


class Pages(unittest.TestCase):
    def test_the_hero_facts_are_three_whole_items_in_every_language(self):
        """Each fact is a list item with a dot of its own (no line starts with a bare separator): the catalog's
        `hero_sub` is split on " · ", and no part may itself hold one."""
        for p in sorted((ROOT / "site" / "i18n").glob("*.json")):
            parts = json.loads(p.read_text(encoding="utf-8"))["hero_sub"].split(" · ")
            self.assertEqual(len(parts), 3, p.stem)
            self.assertTrue(all(part.strip() and "·" not in part for part in parts), p.stem)

    def test_the_drafts_chip_names_the_current_draft_and_does_not_repeat_it(self):
        catalog = json.loads((ROOT / "site" / "i18n" / "en-US.json").read_text(encoding="utf-8"))
        nav = build_site.drafts_nav(catalog, "../", "en-US", "current")
        self.assertIn(f"Current · {build_site.DRAFT}</a>", nav)
        self.assertNotIn(f">{build_site.DRAFT}</a>", nav, "the latest draft is the current text")
        self.assertIn(">0.7</a>", nav)
        # on the latest draft's own page its chip is there, and is the page shown
        own = build_site.drafts_nav(catalog, "../../", "en-US", build_site.DRAFT)
        self.assertIn(f'aria-current="page">{build_site.DRAFT}</a>', own)

    def test_the_entry_texts_exist_in_every_language(self):
        for p in sorted((ROOT / "site" / "i18n").glob("*.json")):
            catalog = json.loads(p.read_text(encoding="utf-8"))
            for key in ("hero_impl", "impl_guide", "spec_start", "home_rail"):
                self.assertTrue(str(catalog.get(key, "")).strip(), f"{p.stem}: {key}")

    def test_the_code_copy_texts_exist_in_every_language(self):
        """site/assets/code.js reads these three from the script tag the build writes for the spec and the start page."""
        for p in sorted((ROOT / "site" / "i18n").glob("*.json")):
            catalog = json.loads(p.read_text(encoding="utf-8"))
            for key in ("ui_copy", "ui_copied", "ui_copy_failed", "spec_copy", "spec_copied", "spec_copy_failed"):
                self.assertTrue(str(catalog.get(key, "")).strip(), f"{p.stem}: {key}")
        self.assertTrue((ROOT / "site" / "assets" / "code.js").is_file())


class ChangesPage(unittest.TestCase):
    """spec/changes/: a card for each draft, and what changed since each older one."""


    def test_versions_sort_as_numbers(self):
        self.assertLess(build_site.version_key("0.9"), build_site.version_key("0.10"))
        self.assertEqual(build_site.version_key("1.2"), (1, 2))

    def test_the_summary_is_the_sentence_the_entry_opens_with(self):
        date, said = build_site.draft_summary(["- 0.8 (2026-11-01): a guide; nothing else.", "  more."])
        self.assertEqual(date, "2026-11-01")
        self.assertTrue(said.startswith("a guide"))
        self.assertEqual(build_site.draft_summary(None), (None, None))
        self.assertEqual(build_site.draft_summary(["no head"]), (None, None))

    def test_the_built_page_has_a_card_a_panel_and_the_feed(self):
        out = ROOT / "build" / "spec" / "changes" / "index.html"
        if not out.is_file():
            self.skipTest("site not built")
        page = out.read_text(encoding="utf-8")
        notes = build_site.changes_notes((ROOT / "SPEC.md").read_text(encoding="utf-8"))
        for v in notes:
            self.assertIn(f'id="d-{v}"', page, v)
            if v != build_site.DRAFT:
                self.assertIn(f'id="since-{v}"', page, v)
                self.assertIn(f'href="#since-{v}"', page, v)
        self.assertNotIn(f'id="since-{build_site.DRAFT}"', page)
        self.assertIn('href="../../feed.xml"', page)
        self.assertNotIn("style=", page, "the CSP forbids style attributes")


class References(unittest.TestCase):
    def test_every_rfc_the_text_names_is_in_annex_e_and_each_one_listed_is_named(self):
        import re
        spec = (ROOT / "SPEC.md").read_text(encoding="utf-8")
        start, end = spec.index("\n## Annex E"), spec.index("\n## Changes")
        named = set(re.findall(r"RFC (\d+)", spec[:start] + spec[end:]))
        listed = set(re.findall(r"RFC (\d+)", spec[start:end]))
        self.assertEqual(named - listed, set(), "named in the text, missing from Annex E")
        self.assertEqual(listed - named, set(), "listed in Annex E, named nowhere")


if __name__ == "__main__":
    unittest.main()
