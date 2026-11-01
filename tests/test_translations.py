"""The translations page (tools/build_site.py, translation_rows() and translations_table()): one row per language
of the site, English the original, the specification translated where site/translations/ has it and says whether
it is current, and every text of the page in every catalog.

    python3 -m unittest discover -s tests
"""
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "library" / "boreale-site"))
import boreale_site as boreale  # noqa: E402
import build_site  # noqa: E402


class Translations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        t = build_site.read_translation("SPEC.fr.md")
        cls.rows = build_site.translation_rows({"SPEC.fr.md": (t, None)}, (ROOT / "SPEC.md").read_text(encoding="utf-8"))

    def test_one_row_per_language_of_the_site(self):
        self.assertEqual([r[0] for r in self.rows], [c for c, _, _, _ in boreale.LANGUAGES])

    def test_english_is_the_original_and_french_follows_the_text(self):
        by = {r[0]: r for r in self.rows}
        self.assertEqual(by["en-US"][3], "original")
        self.assertIn(by["fr"][3], ("current", "behind"))
        self.assertEqual(by["fr"][3:], by["fr-CA"][3:], "both French catalogs show the same translation")
        self.assertEqual(by["de"][3], "none")

    def test_the_translation_is_current_when_the_header_says_so(self):
        """site/translations/SPEC.fr.md names SPEC.md's SHA-256 at the commit it translates: the page calls it
        current when that is this SPEC.md's (check_site.py warns of the same lag)."""
        by = {r[0]: r for r in self.rows}
        text = (ROOT / "site" / "translations" / "SPEC.fr.md").read_text(encoding="utf-8")
        same = hashlib.sha256((ROOT / "SPEC.md").read_bytes()).hexdigest() in text
        self.assertEqual(by["fr"][3] == "current", same)

    def test_every_catalog_has_the_page_texts(self):
        for p in sorted((ROOT / "site" / "i18n").glob("*.json")):
            catalog = json.loads(p.read_text(encoding="utf-8"))
            for key in ("tr_title", "tr_lede", "tr_note", "tr_col_lang", "tr_col_site", "tr_col_spec", "tr_original", "tr_site",
                        "tr_spec_current", "tr_spec_behind", "tr_spec_none", "tr_help", "footer_translations"):
                self.assertTrue(catalog.get(key), f"{p.stem}: {key}")
            self.assertIn("{v}", catalog["tr_spec_current"], p.stem)
            self.assertIn("{v}", catalog["tr_spec_behind"], p.stem)


if __name__ == "__main__":
    unittest.main()
