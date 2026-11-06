"""The SDK page (site/sdk.html, tools/build_site.py's sdk_*): sdk.json is read by the `schema` rule (a newer one is
absent, an unknown field is skipped), the tables say what the file says, and every catalog has the page's texts."""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import build_site  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "sdk.json"
SECTIONS = {"6.3": "63-missing", "4.2": "42-handshake"}


def catalog(code="en-US"):
    return json.loads((ROOT / "site" / "i18n" / f"{code}.json").read_text(encoding="utf-8"))


def read(path):
    with mock.patch.dict(os.environ, {"SDK_JSON": str(path)}):
        return build_site.sdk_data()


class Reader(unittest.TestCase):
    def test_a_file_is_read(self):
        data = read(FIXTURE)
        self.assertEqual(data["schema"], 1)
        self.assertIn("languages", data)

    def test_a_newer_schema_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sdk.json"
            path.write_text(json.dumps({"schema": 2, "sdk": {}}), encoding="utf-8")
            self.assertIsNone(read(path))

    def test_what_is_not_json_or_not_there_is_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sdk.json"
            path.write_text("not json", encoding="utf-8")
            self.assertIsNone(read(path))
            self.assertIsNone(read(Path(tmp) / "missing.json"))
            path.write_text("[1, 2]", encoding="utf-8")
            self.assertIsNone(read(path))

    def test_offline_without_a_file_is_absent(self):
        with mock.patch.dict(os.environ, {"SITE_OFFLINE": "1"}, clear=False):
            os.environ.pop("SDK_JSON", None)
            self.assertIsNone(build_site.sdk_data())

    def test_a_page_without_data_says_so(self):
        with mock.patch.dict(os.environ, {"SDK_JSON": "/nonexistent/sdk.json"}):
            values = build_site.sdk_values(catalog(), "../", "", SECTIONS)
        self.assertEqual(values["sdk_cards"], "")
        self.assertIn(catalog()["sdk_nodata"], values["sdk_nodata"])


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with mock.patch.dict(os.environ, {"SDK_JSON": str(FIXTURE)}):
            cls.values = build_site.sdk_values(catalog(), "../", "", SECTIONS)

    def test_every_language_has_a_card_and_a_planned_one_no_readme(self):
        cards = self.values["sdk_cards"]
        for name in ("C++23", "Python", "TypeScript", "Go", "Rust"):
            self.assertIn(f"<h3>{name}</h3>", cards)
        self.assertEqual(cards.count("Its README"), 5)  # all but Rust, which has no folder

    def test_nothing_is_installed_before_a_release(self):
        self.assertNotIn("pip install", self.values["sdk_cards"])

    def test_the_parity_table_has_a_row_per_family_and_a_mark_for_each_cell(self):
        table = self.values["sdk_parity"]
        self.assertEqual(table.count('<th scope="row">'), 4)  # three families and the totals
        self.assertIn("<tfoot>", table)
        self.assertIn('class="reached"', table)
        self.assertIn('class="half"', table)  # C++ serves part of it

    def test_the_calls_link_to_the_sources_and_the_specification(self):
        calls = self.values["sdk_calls"]
        self.assertIn("lantern-sdk/blob/main/python/src/", calls)
        self.assertIn('href="../spec/#42-handshake"', calls)
        self.assertIn("<code>iterApps</code>", calls)

    def test_a_section_the_specification_lacks_is_not_a_link(self):
        with mock.patch.dict(os.environ, {"SDK_JSON": str(FIXTURE)}):
            calls = build_site.sdk_values(catalog(), "../", "", {})["sdk_calls"]
        self.assertNotIn("spec/#", calls)
        self.assertIn("§&nbsp;4.2", calls)

    def test_examples_show_their_source_escaped(self):
        examples = self.values["sdk_examples"]
        self.assertIn('class="tabs"', examples)
        self.assertIn('type="radio"', examples)
        self.assertNotIn("<script", examples)

    def test_versions(self):
        self.assertIn("0.11", self.values["sdk_versions"])
        self.assertIn(catalog()["sdk_none_yet"], self.values["sdk_versions"])


class Texts(unittest.TestCase):
    def test_every_catalog_has_every_text_the_page_uses(self):
        used = set(re.findall(r"\{\{(sdk_[a-z_]+)\}\}", (ROOT / "site" / "sdk.html").read_text(encoding="utf-8")))
        used |= {f"sdk_g_{g}" for g in build_site.SDK_CALLS}
        used |= {"nav_sdk", "title_sdk", "description_sdk", "sdk_eyebrow", "sdk_title", "sdk_lede", "sdk_nodata"}
        used -= {"sdk_head", "sdk_cards", "sdk_parity", "sdk_levels", "sdk_calls", "sdk_examples", "sdk_versions", "sdk_trust", "sdk_nav"}
        used |= {f"sdk_task_{t}" for t, _ in build_site.SDK_TASKS} | {"sdk_total", "sdk_calls_later", "sdk_nav_aria"} | {f"sdk_nav_{k}" for k in build_site.SDK_SECTIONS}
        used |= {f"sdk_trust_{k}{s}" for k in ("suite", "hostile", "vectors") for s in ("", "_t")} | {"sdk_trust_release_t", "sdk_trust_release_x"}
        for p in sorted((ROOT / "site" / "i18n").glob("*.json")):
            texts = json.loads(p.read_text(encoding="utf-8"))
            for key in sorted(used):
                self.assertTrue(texts.get(key), f"{p.stem}: {key}")
            self.assertIn("{v}", texts["sdk_released"], p.stem)
            self.assertNotIn("`", "".join(texts[k] for k in used if k in texts), p.stem)


if __name__ == "__main__":
    unittest.main()


class Navigation(unittest.TestCase):
    def setUp(self):
        with mock.patch.dict(os.environ, {"SDK_JSON": str(FIXTURE)}):
            self.values = build_site.sdk_values(catalog(), "../", "", {})

    def test_the_sub_navigation_leads_to_each_section(self):
        nav = self.values["sdk_nav"]
        for section in build_site.SDK_SECTIONS:
            self.assertIn(f'href="#{section}"', nav)
            self.assertIn(f'<section id="{section}">', (ROOT / "site" / "sdk.html").read_text(encoding="utf-8"))

    def test_each_level_a_server_reaches_is_a_chip_leading_to_the_badges(self):
        levels = self.values["sdk_levels"]
        self.assertIn('<a href="../badge/">Core</a>', levels)
        self.assertIn('<a href="../badge/">+titles</a>', levels)

    def test_the_tables_and_cards_name_their_language_for_the_script(self):
        self.assertIn('data-lang="python"', self.values["sdk_parity"])
        self.assertIn('data-lang="python"', self.values["sdk_calls"])
        self.assertIn('data-lang="python"', self.values["sdk_cards"])
        self.assertIn('type="radio" name="ex-read" id="ex-read-0" data-lang=', self.values["sdk_examples"])

    def test_the_versions_are_a_table(self):
        self.assertIn("<table>", self.values["sdk_versions"])
