"""The SDK page (site/sdk.html, tools/build_site.py's sdk_*): sdk.json is read by the `schema` rule (a newer one is
absent, an unknown field is skipped), the tables say what the file says, and every catalog has the page's texts."""
import html
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
        table = self.values["sdk_parity"].split('class="parity-list"')[0]
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
        used -= {"sdk_head", "sdk_cards", "sdk_parity", "sdk_levels", "sdk_calls", "sdk_examples", "sdk_versions", "sdk_trust", "sdk_nav", "sdk_use", "sdk_origin"}
        used |= {f"sdk_task_{t}" for t, _ in build_site.SDK_TASKS} | {"sdk_total", "sdk_calls_later", "sdk_nav_aria"} | {f"sdk_nav_{k}" for k in build_site.SDK_SECTIONS}
        used |= {f"sdk_trust_{k}{s}" for k in ("suite", "hostile", "vectors") for s in ("", "_t")} | {"sdk_trust_release_t", "sdk_trust_release_x"}
        used |= {"sdk_use_title", "sdk_i_code", "sdk_origin"} | {f"sdk_use_{k}" for k, _ in build_site.SDK_USES} | {"sdk_show_all", "sdk_show_less"}
        for p in sorted((ROOT / "site" / "i18n").glob("*.json")):
            texts = json.loads(p.read_text(encoding="utf-8"))
            for key in sorted(used):
                self.assertTrue(texts.get(key), f"{p.stem}: {key}")
            self.assertIn("{v}", texts["sdk_released"], p.stem)
            self.assertNotIn("`", "".join(texts[k] for k in used if k in texts), p.stem)


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


class Choosing(unittest.TestCase):
    def setUp(self):
        with mock.patch.dict(os.environ, {"SDK_JSON": str(FIXTURE)}):
            self.values = build_site.sdk_values(catalog(), "../", "", {})

    def test_each_situation_leads_to_the_card_of_its_language(self):
        use = self.values["sdk_use"]
        for _, lang in build_site.SDK_USES:
            self.assertIn(f'href="#sdk-{lang}"', use)
            self.assertIn(f'id="sdk-{lang}"', self.values["sdk_cards"])

    def test_the_picker_is_hidden_until_the_script_shows_it(self):
        self.assertIn('class="picker" hidden', self.values["sdk_use"])
        self.assertIn('data-pick="python"', self.values["sdk_use"])

    def test_a_card_says_how_far_the_language_goes_and_leads_to_its_readme(self):
        cards = self.values["sdk_cards"]
        self.assertIn('class="parity"', cards)
        self.assertIn('class="card linked"', cards)

    def test_the_data_say_where_they_come_from(self):
        self.assertIn(f"commit/{build_site.SDK_COMMIT}", self.values["sdk_origin"])

    def test_tabs_and_tables_are_named_for_a_screen_reader(self):
        self.assertIn('role="radiogroup" aria-labelledby="ex-read-title"', self.values["sdk_examples"])
        self.assertIn('<h3 id="ex-read-title">', self.values["sdk_examples"])
        for key in ("sdk_parity", "sdk_calls", "sdk_versions"):
            self.assertIn('<caption class="sr">', self.values[key])


class Code(unittest.TestCase):
    def test_colouring_changes_nothing_in_the_text(self):
        data = read(FIXTURE)
        for example in data["examples"]:
            lang = example["language"]
            coloured = build_site.sdk_highlight(example["source"], lang)
            plain = html.unescape(re.sub(r"<[^>]+>", "", coloured))
            self.assertEqual(plain, example["source"], example["path"])

    def test_comments_strings_numbers_and_keywords_are_marked(self):
        out = build_site.sdk_highlight('auto x = "a"; // c\nint n = 42;', "cpp")
        for kind in ("c", "s", "n", "k"):
            self.assertIn(f'class="tk-{kind}"', out)

    def test_a_hash_is_a_comment_in_python_only(self):
        self.assertIn('tk-c', build_site.sdk_highlight("x = 1  # c", "python"))
        self.assertNotIn('tk-c', build_site.sdk_highlight("#include <a>", "cpp"))

    def test_a_long_example_is_cut_with_a_toggle_and_a_short_one_is_not(self):
        cat = catalog()
        short = build_site.sdk_code(cat, "ex", "python", "x = 1\n" * 3)
        long = build_site.sdk_code(cat, "ex", "python", "x = 1\n" * (build_site.SDK_FOLD + 5))
        self.assertNotIn("fold", short)
        self.assertIn('type="checkbox" id="ex-fold"', long)
        self.assertIn("<pre", long)  # the whole source is there without styles or script

    def test_the_parity_by_language_is_there_for_a_narrow_screen(self):
        with mock.patch.dict(os.environ, {"SDK_JSON": str(FIXTURE)}):
            parity = build_site.sdk_values(catalog(), "../", "", {})["sdk_parity"]
        self.assertIn('class="parity-list"', parity)
        self.assertIn('<details data-lang="python">', parity)


if __name__ == "__main__":
    unittest.main()
