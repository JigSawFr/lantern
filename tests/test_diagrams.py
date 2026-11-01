"""tools/diagrams.py, the specification's figures (site/README.md): each one is placed under a heading
that exists, speaks in every language, and refers to sections that exist.

    python3 -m unittest discover -s tests
"""
import json
import re
import sys
import unittest
import xml.etree.ElementTree as ET
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


SVG = "{http://www.w3.org/2000/svg}"


def boxes(svg_text):
    """The figure's texts, each with its extent as the drawing's own estimate gives it, and the rectangle
    drawn just before it (a node, a note, an actor): [(text, x0, x1, y_first_baseline, rect or None)]."""
    root = ET.fromstring(svg_text)
    width = float(root.get("viewBox").split()[2])
    found, last = [], None
    for el in root.iter():
        if el.tag == SVG + "rect":
            last = (float(el.get("x", 0)), float(el.get("y", 0)), float(el.get("width")), float(el.get("height")))
        elif el.tag == SVG + "text":
            lines = ["".join(t.itertext()) for t in el.findall(SVG + "tspan")]
            x = float(el.get("x"))
            mono = "mono" in el.get("class", "")
            w = diagrams.tw("\n".join(lines), mono)
            anchor = el.get("text-anchor")
            x0 = x - w / 2 if anchor == "middle" else x - w if anchor == "end" else x
            found.append((" ".join(lines), x0, x0 + w, float(el.get("y")), last if "nodetext" in el.get("class", "") or "notetext" in el.get("class", "") else None))
    return width, found


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
        self.assertIn('data-kind="view"', with_file)   # the drawing, or the list of its steps
        self.assertNotIn("dg-tools", diagrams.render("connect", CATALOGS["en-US"]))

    def test_a_sequence_can_be_stepped_through_and_a_graph_cannot(self):
        catalog = CATALOGS["en-US"]
        sequence = diagrams.render("connect", catalog, None, None, stepper=True)
        self.assertIn("dg-stepper", sequence)
        self.assertEqual(sequence.count('class="dg-step"'), len(diagrams.DIAGRAMS["connect"]["steps"]))
        # each step has its line in the list for screen readers, which the stepper says aloud
        self.assertEqual(sequence.count("<li>"), len(diagrams.DIAGRAMS["connect"]["steps"]))
        self.assertNotIn("dg-stepper", diagrams.render("sync", catalog, None, None, stepper=True))
        self.assertNotIn("dg-stepper", diagrams.render("connect", catalog))

    def test_every_text_fits_its_figure_and_its_box_in_every_language(self):
        """The estimate the layout is made with (wide characters of the East Asian scripts, the Cyrillic
        alphabet) leaves no text outside the figure or outside the box it is written in."""
        for code, catalog in CATALOGS.items():
            for name in diagrams.DIAGRAMS:
                svg, _ = diagrams.draw(name, catalog)
                width, texts = boxes(svg)
                for text, x0, x1, _, rect in texts:
                    self.assertGreaterEqual(x0, -1, f"{code} {name}: {text!r} leaves the figure on the left")
                    self.assertLessEqual(x1, width + 1, f"{code} {name}: {text!r} leaves the figure on the right")
                    if rect:
                        rx, _, rw, _ = rect
                        self.assertGreaterEqual(x0, rx - 1, f"{code} {name}: {text!r} leaves its box on the left")
                        self.assertLessEqual(x1, rx + rw + 1, f"{code} {name}: {text!r} leaves its box on the right")

    def test_the_routes_of_the_figures_are_those_of_openapi(self):
        """A route a figure draws (GET /v1/saves/{title_id}…) is a path of openapi.yaml: a renamed route cannot
        stay drawn."""
        paths = {re.sub(r"\{[^}]*\}", "{}", p) for p in re.findall(r"^  (/[^ :]*):", (ROOT / "openapi.yaml").read_text(encoding="utf-8"), re.M)}
        drawn = set()
        for spec in diagrams.DIAGRAMS.values():
            texts = [step[1] if step[0] == "sep" else step[3] for step in spec.get("steps", [])]
            texts += [node[2] for node in spec.get("nodes", {}).values()] + [edge[2] for edge in spec.get("edges", [])]
            for text in texts:
                for m in re.finditer(r"(?:GET|POST|PATCH|DELETE|HEAD|PUT)\s+((?:/[\w.{}\-]*)+)", text):
                    drawn.add(re.sub(r"\{[^}]*\}", "{}", m.group(1)))
        self.assertTrue(drawn, "no route found in the figures")
        self.assertEqual(sorted(drawn - paths), [], "a route of a figure is not in openapi.yaml")

    def test_a_figure_is_a_list_of_its_steps_for_a_screen_reader(self):
        html = diagrams.render("connect", CATALOGS["en-US"])
        self.assertIn("<li>Device → Server: GET /.well-known/lantern</li>", html)


if __name__ == "__main__":
    unittest.main()
