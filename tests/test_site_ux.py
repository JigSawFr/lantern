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


if __name__ == "__main__":
    unittest.main()
