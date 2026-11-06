"""The Bridge page (site/bridge.html, /bridge/): every text it uses is in every catalog, it says nothing is released,
and the footer and the sitemap lead to it."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_site  # noqa: E402

PAGE = (ROOT / "site" / "bridge.html").read_text(encoding="utf-8")


class Texts(unittest.TestCase):
    def test_every_catalog_has_every_text_the_page_uses(self):
        used = set(re.findall(r"\{\{(bridge_[a-z0-9_]+)\}\}", PAGE))
        used |= {"nav_bridge", "title_bridge", "description_bridge", "bridge_eyebrow", "bridge_title", "bridge_lede"}
        for p in sorted((ROOT / "site" / "i18n").glob("*.json")):
            texts = json.loads(p.read_text(encoding="utf-8"))
            for key in sorted(used):
                self.assertTrue(texts.get(key), f"{p.stem}: {key}")

    def test_the_page_says_nothing_is_released_and_names_no_draft(self):
        en = json.loads((ROOT / "site" / "i18n" / "en-US.json").read_text(encoding="utf-8"))
        self.assertIn("nothing released yet", en["bridge_status"])
        self.assertNotRegex(en["bridge_status"], r"\b0\.\d+\b")

    def test_the_page_is_known_and_linked_from_the_footer(self):
        self.assertEqual(build_site.PAGES["bridge/"], "bridge")
        self.assertIn('nav_bridge"], f"{home}bridge/"', (ROOT / "tools" / "build_site.py").read_text(encoding="utf-8"))

    def test_the_run_steps_use_a_reserved_loopback_address(self):
        self.assertIn("http://127.0.0.1:8080/.well-known/lantern", PAGE)
        self.assertNotRegex(PAGE, r"@[a-z0-9.-]+\.[a-z]{2,}")


if __name__ == "__main__":
    unittest.main()
