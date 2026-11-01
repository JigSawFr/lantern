"""tools/diagrams.py, the specification's figures (site/README.md): each one is placed under a heading
that exists, speaks in every language, and refers to sections that exist.

    python3 -m unittest discover -s tests
"""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import diagrams  # noqa: E402

CATALOGS = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "site" / "i18n").glob("*.json"))}
HEADINGS = {m.group(1) for m in re.finditer(r"^#{2,3} (\d+(?:\.\d+)?)\.? ", (ROOT / "SPEC.md").read_text(encoding="utf-8"), re.M)}


def references(spec):
    """The section numbers a figure's boxes point at (§ n)."""
    if spec["kind"] != diagrams.COLUMNS:
        return set()
    return {ref for _, items in spec["cols"] for _, ref in items}


class DiagramsTest(unittest.TestCase):
    def test_every_figure_has_its_place_but_the_home_page_one(self):
        self.assertEqual(set(diagrams.WHERE), set(diagrams.DIAGRAMS) - {"overview"})
        for name, number in diagrams.WHERE.items():
            self.assertIn(number, HEADINGS, f"{name}: SPEC.md has no section {number}")

    def test_references_lead_to_sections(self):
        for name, spec in diagrams.DIAGRAMS.items():
            for ref in references(spec):
                self.assertIn(ref, HEADINGS, f"{name}: § {ref} is not a section of SPEC.md")

    def test_every_language_has_every_key(self):
        for code, catalog in CATALOGS.items():
            self.assertEqual(sorted(diagrams.keys() - set(catalog)), [], code)
            # a catalog keeps no text a figure no longer uses
            self.assertEqual(sorted(k for k in catalog if k.startswith("dg_") and k not in diagrams.keys()), [], code)

    def test_each_figure_draws_in_each_language(self):
        sections = {n: f"s{n}" for n in HEADINGS}
        for code, catalog in CATALOGS.items():
            for name in diagrams.DIAGRAMS:
                html = diagrams.render(name, catalog, sections)
                self.assertTrue(html.startswith("<figure"), (code, name))
                self.assertIn("<svg", html)
                self.assertNotIn("style=", html, "the CSP forbids inline style")
                self.assertIn('class="sr"', html, "a list for screen readers")
                self.assertNotRegex(re.sub(r"<[^>]+>", "", html), r"@[a-z_]+", f"{code} {name}: a key left unreplaced")

    def test_the_figures_of_the_repository_are_up_to_date(self):
        self.assertEqual(diagrams.export(ROOT / "figures", check=True), [], "python3 tools/diagrams.py write")

    def test_a_standalone_figure_is_a_file_of_its_own(self):
        for name in diagrams.DIAGRAMS:
            text = diagrams.standalone(name, CATALOGS["fr"])
            self.assertTrue(text.startswith("<?xml"), name)
            self.assertIn("<style>", text)
            self.assertIn("<title>", text)
            self.assertNotIn("<a ", text, "a file of its own has no link to a page of the site")
            self.assertNotIn("var(", text, "no variable of the site's css")

    def test_a_figure_offers_its_downloads_where_it_is_given_a_file(self):
        with_file = diagrams.render("connect", CATALOGS["en-US"], None, "figures/connect.en.svg")
        self.assertIn('data-src="figures/connect.en.svg"', with_file)
        self.assertNotIn("dg-tools", diagrams.render("connect", CATALOGS["en-US"]))

    def test_a_figure_is_a_list_of_its_steps_for_a_screen_reader(self):
        html = diagrams.render("connect", CATALOGS["en-US"])
        self.assertIn("<li>Device → Server: GET /.well-known/lantern</li>", html)


if __name__ == "__main__":
    unittest.main()
