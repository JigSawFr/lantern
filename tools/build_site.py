#!/usr/bin/env python3
"""Builds Lantern's website into <out-dir> (site/README.md).

    python3 tools/build_site.py <out-dir>

site/template.html is the page around site/home.html (the protocol) and
the specification (spec/: SPEC.md, rendered at each build by markdown());
each {{key}} is the key's text in the language's catalog,
site/i18n/<language>.json. The fifteen languages of Boréale's sites
(LANGUAGES): English at the root, each other one in its folder (fr/, fr-ca/,
de/ ... zh-hant/). The specification is in English in every language: only
the page around it is translated; each requirement's id in it ([L-5.2-3]) is
an anchor. errors/ lists the error types of SPEC.md's section "Errors"
(ERRORS_HEADING), each at the address its `type` gives (errors/<name>/), in
English. So are the pages of conformance (SPEC.md § 17), in English, read
from the text and the suite: conformance/ (the levels), requirements/
(traceability: each requirement and the suite's checks that cover it, from
tools/requirements.py and conformance/run.py), implementations/ (the
registry, site/registry.json) and badge/ (the "Lantern compatible" badges,
written into assets/badges/ by badge_svg()); releases/ says how a version of
the text is released and how to verify its files (SPEC.md § 3.6), in
English too. schemas/v1/<name>.json are the schemas, each at its $id
(copy_schemas()), as they are. spec/<draft>/ are the drafts as
they were published (DRAFTS, read from git), spec/changes/ what each one
changed; the French spec/ pages show the informative translation of
site/translations/ (TRANSLATIONS); demo/ is the demo library and its trapped
variant (tools/make_demo.py), with its page in every language.

SITE_URL is the site's address (https://lantern.boreale.dev/ by default);
the links inside the site are relative, so it works at another one too.
SITE_OFFLINE=1 builds without reading boreale.dev's versions.json. What
Boréale's sites share (the languages, the header's two menus, the links out
and their UTM tags, the audience, the fonts and marks) is boreale-site's, the
submodule library/boreale-site. Python's standard library only.
"""
import difflib
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "conformance"))
sys.path.insert(0, str(ROOT / "library" / "boreale-site"))
import make_demo  # noqa: E402  (tools/make_demo.py)
import diagrams  # noqa: E402  (tools/diagrams.py: the specification's figures)
import qr  # noqa: E402  (tools/qr.py: the demo's QR code)
import requirements as spec_requirements  # noqa: E402  (tools/requirements.py)
import boreale_site as boreale  # noqa: E402  (library/boreale-site)
from boreale_site import CODES, LANGUAGES, OG_LOCALES, fill, folder  # noqa: E402

SITE = ROOT / "site"
SPEC = ROOT / "SPEC.md"
REPO = "https://github.com/JigSawFr/lantern"
# This site in boreale-site's sites.json: its address (SITE_URL), its
# utm_source on the links to Boréale's other sites, its place in the menu of
# Boréale's sites. The audience is counted by Umami Cloud, only from its own
# host (site/README.md).
LANTERN = boreale.Site("lantern", os.environ.get("SITE_URL"))
SITE_URL = LANTERN.url
# English, at the root: the reference catalog (site/i18n/en-US.json).
ENGLISH = CODES[0]
# The pages in every language, by their path under each language's folder.
# The file of the demo library the quick start downloads and hashes (its app's `sha256`, vita's first):
# check_site.py's tests and the page's commands read it from here.
DEMO_FILE = "fa75492f7b78cad7ca4044e8fb548ac67bfd7fbf05242ceecb29ebe492218a0d"
PAGES = {"": "home", "spec/": "spec", "start/": "start", "check/": "check", "examples/": "examples", "translations/": "translations", "demo/": "demo", "sdk/": "sdk"}
# The drafts of SPEC.md, each at spec/<draft>/: SPEC.md at the commit that
# finished it, read from git at each build (git show <commit>:SPEC.md), so
# that a published draft never changes; the site's workflow checks out the
# whole history for it (fetch-depth: 0). (draft, commit, pull request.)
# Draft 0.1 is its text once the conformance suite had settled it (#3, #4,
# #6, its "Changes"); it was first published in #1.
# The last draft may be (draft, None, None) while it is not merged yet: its
# page is then the working tree's SPEC.md (which must say "Draft <draft>,"),
# without a commit or a pull request, and its links lead to main. Once draft
# 0.7 is merged, a pull request replaces its None, None with the commit on
# main that finished it and its pull request's number, as for 0.1 to 0.6
# (and points site/translations/SPEC.fr.md's header at that commit);
# check_site.py then pins the page to that commit like the others.
DRAFTS = [
    ("0.1", "fda0f52aebef05bc3dbb9e8e2917c7e32eb15094", 6),
    ("0.2", "a4c1609a67c990e6fe7cb443f59c11f89c604137", 7),
    ("0.3", "836e13115663bc671d0727b221eaf2b42d3dfe83", 9),
    ("0.4", "442cc07ac7f86a37b5145e2940a0962bd6b8fe2a", 10),
    ("0.5", "ca10e3146a6300cc99814e2290de5da97c735965", 11),
    ("0.6", "9871962a35d336b3fb0906cd4e049858817962cb", 13),
    ("0.7", "8f34dd69ef50b4952b6231a56276bb1236b2051b", 15),
    ("0.8", "5ac42b8c73d60d44df6d2557fccb0c92abd00324", 30),
    ("0.9", "71c23bc936adb718b32033a9d71d4916e64737e9", 42),
    ("0.10", "0801aa70476c9da22ce7440cf61ba110bfb50741", 45),
    ("0.11", "84f935ad4deaaf89bed166619d2794849f001294", 48),
]
# The specification's informative translations (site/translations/), by
# the catalogs whose spec/ page shows them; each says the English commit it
# translates (read_translation()).
TRANSLATIONS = {"fr": "SPEC.fr.md", "fr-CA": "SPEC.fr.md"}

REQ = re.compile(r"\[(L-(?:\d+(?:\.\d+)?|[A-Z](?:\.\d+)?)-\d+)\]")
DRAFT = "0.11"   # the draft the badges name (SPEC.md § 17)
LEVELS = [("core", "Core"), ("titles", "+titles"), ("homebrew", "+homebrew"), ("saves", "+saves"),
          ("cheats", "+cheats"), ("requests", "+requests"), ("admin", "+admin"), ("events", "+events"),
          ("peers", "+peers"), ("sync", "+sync"), ("encrypted_saves", "+encrypted_saves"), ("deltas", "+deltas"),
          ("static", "Static")]
# SPEC.md's section of errors, whatever its number: "## 12. Errors".
ERRORS_HEADING = re.compile(r"## (\d+)\. Errors$")


# ---- SPEC.md, rendered: the subset it is written in (headings, paragraphs,
# lists with their continuation lines and code, fenced code, tables, `code`,
# **strong**, [links](url)); each heading an anchor as GitHub makes it, each
# "§ 4.2" a link to its section, and each "Annex A" or "Annex A.1" to the
# annex or its part.

def slug(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text).lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def plain(text: str) -> str:
    return re.sub(r"[`*]", "", text)


# A heading's number: "4.2", an annex's letter ("Annex A —", "Annexe A —" in
# French) or part ("A.1"); and an anchor of its own, "{#changes}" at its end,
# which a translation gives an unnumbered heading to keep the English one's.
HEADING = re.compile(r"((\d+(?:\.\d+)?)\.? .*?|Annexe? ([A-Z]) .*?|([A-Z]\.\d+) .*?|.*?)(?: \{#([a-z0-9-]+)\})?$")
# The text's status line ("Draft 0.7, 2026-10-30. Status: ...", "Brouillon 0.7, ...") and its licence.
STATUS = re.compile(r"(?:Draft|Brouillon) (\S+?), (\d{4}-\d{2}-\d{2})\.")
LICENCE = re.compile(r"\[(CC BY [\d.]+)\]\(([^)\s]+)\)")
# A route in a code span of the text ("GET <base>/v1/apps", "/.well-known/lantern"): what the search finds by it.
ROUTE = re.compile(r"(?:(?:GET|PUT|POST|PATCH|DELETE|HEAD|OPTIONS) )?(?:<base>)?/[\w{}<>\-./:*~?=&]*")
ANNEX = re.compile(r"\b(?:Annex|[Aa]nnexe) ([A-Z](?:\.\d+)?)\b")


def heading(text: str) -> tuple:
    """(the heading as shown, its number or letter or None, its own anchor or None)."""
    m = HEADING.match(text)
    return m.group(1), m.group(2) or m.group(3) or m.group(4), m.group(5)


def heading_id(text: str, sections: dict) -> str:
    shown, number, own = heading(text)
    return own or (sections.get(number) if number else None) or slug(shown)


def inline(text: str, sections: dict, refs: bool = True, ref: str = "main") -> str:
    codes = []

    def keep(m):
        codes.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"
    text = re.sub(r"`([^`]+)`", keep, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    if refs:   # a requirement's id: an anchor, which the traceability page links to (SPEC.md § 3.5)
        text = REQ.sub(lambda m: f'<a class="req" id="{m.group(1)}" href="#{m.group(1)}">{m.group(1)}</a>', text)

    def link(m):
        label, href = m.group(1), m.group(2)
        if not urlparse(href).scheme and not href.startswith("#"):
            href = f"{REPO}/{'tree' if href.endswith('/') else 'blob'}/{ref}/{href}"
        return f'<a href="{html.escape(href)}">{label}</a>'
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, text)

    def section(m):
        number = m.group(1)
        anchor = sections.get(number)
        return f'<a href="#{anchor}">§&nbsp;{number}</a>' if anchor else m.group(0)
    if refs:  # not in a heading, itself a link
        text = re.sub(r"§ (\d+(?:\.\d+)?)", section, text)

    def annex(m):
        anchor = sections.get(m.group(1))
        return f'<a href="#{anchor}">{m.group(0).replace(" ", "&nbsp;")}</a>' if anchor else m.group(0)
    if refs:
        text = ANNEX.sub(annex, text)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


def table(rows: list, sections: dict, label: str, ref: str = "main") -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], cells[2:]
    out = [f'<div class="table" tabindex="0" role="region" aria-label="{html.escape(label)}"><table>',
           "<thead><tr>" + "".join(f'<th scope="col">{inline(c, sections, ref=ref)}</th>' for c in head)
           + "</tr></thead>", "<tbody>"]
    out += ["<tr>" + "".join(f"<td>{inline(c, sections, ref=ref)}</td>" for c in r) + "</tr>" for r in body]
    return "\n".join(out + ["</tbody></table></div>"])


def blocks(lines: list, sections: dict, tight: bool = False, ref: str = "main") -> str:
    """Markdown `lines` (their indentation already taken off) as HTML; its relative links to the repository
    at `ref`."""
    out, i, title = [], 0, ""
    para = []

    def flush():
        if para:
            text = inline(" ".join(s.strip() for s in para), sections, ref=ref)
            out.append(text if tight and not out else f"<p>{text}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
        elif line.startswith("```"):
            flush()
            lang = line[3:].strip()
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            code = html.escape("\n".join(lines[i + 1:j]))
            cls = f' class="language-{lang}"' if lang else ""
            out.append(f'<pre tabindex="0"><code{cls}>{code}</code></pre>')
            i = j + 1
        elif m := re.match(r"(#{2,4}) (.*)", line):
            flush()
            level, text = len(m.group(1)), m.group(2)
            anchor, text = heading_id(text, sections), heading(text)[0]
            title = plain(text)
            out.append(f'<h{level} id="{anchor}"><a class="anchor" href="#{anchor}">'
                       f'{inline(text, sections, refs=False, ref=ref)}</a></h{level}>')
            if level in (2, 3):
                out.append(f"<!--meta:{anchor}-->")
            for figure, number in diagrams.WHERE.items():
                if heading(m.group(2))[1] == number:
                    out.append(f"<!--diagram:{figure}-->")
            i += 1
        elif line.startswith("|"):
            flush()
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            out.append(table(lines[i:j], sections, title, ref))
            i = j
        elif re.match(r"(- |\d+\. )", line):
            flush()
            ordered = not line.startswith("- ")
            items = []
            while i < len(lines) and (m := re.match(r"(- |\d+\. )", lines[i])):
                indent = len(m.group(1))
                item = [lines[i][indent:]]
                i += 1
                while i < len(lines) and (lines[i].startswith(" " * indent) or (
                        not lines[i].strip() and i + 1 < len(lines) and lines[i + 1].startswith(" " * indent))):
                    item.append(lines[i][indent:])
                    i += 1
                items.append(item)
                while i < len(lines) and not lines[i].strip() and i + 1 < len(lines) \
                        and re.match(r"(- |\d+\. )", lines[i + 1]) and ordered == (not lines[i + 1].startswith("- ")):
                    i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{blocks(item, sections, tight=True, ref=ref)}</li>" for item in items)
                       + f"</{tag}>")
        else:
            para.append(line)
            i += 1
    flush()
    return "\n".join(out)


def read_spec(text: str | None = None, ref: str = "main", anchors: dict | None = None,
              errors_needed: bool = True) -> dict:
    """SPEC.md (or `text`, an earlier draft or a translation of it, whose
    relative links lead to the repository at `ref`): its title, its first
    lines (status, licence), its body, its table of contents, and its section
    of errors' table (ERRORS_HEADING). Numbered headings ("## 4.", "### 4.2")
    and the annexes' ("## Annex A —", "### A.1") are the targets of "§ 4.2",
    "Annex A" and "Annex A.1". A translation's numbered headings take the
    English ones' anchors (`anchors`, the English text's `sections`), so that
    #42-handshake leads to the same section in every language."""
    lines = (SPEC.read_text(encoding="utf-8") if text is None else text).split("\n")
    title = lines[0].lstrip("# ").strip()
    rest = lines[1:]
    first = next(i for i, line in enumerate(rest) if line.startswith("## "))
    sections, toc = {}, []
    for line in rest:
        if m := re.match(r"(#{2,3}) (.*)", line):
            shown, number, own = heading(m.group(2))
            anchor = own or (anchors or {}).get(number) or slug(shown)
            if number:
                sections[number] = anchor
            if len(m.group(1)) == 2:
                toc.append((anchor, plain(shown), []))
            elif toc:
                toc[-1][2].append((anchor, plain(shown)))
    errors = []
    in_errors = False
    errors_number = ""
    for line in rest:
        if line.startswith("## "):
            m = ERRORS_HEADING.match(line)
            in_errors = bool(m)
            errors_number = m.group(1) if m else errors_number
        elif in_errors and re.match(r"\| \d{3} ", line):
            status, codes, when = [c.strip() for c in line.strip().strip("|").split("|")]
            names = re.findall(r"`([a-z_]+)`", codes)
            # "A scope missing; a frozen account": one case per code, when there are as many.
            whens = [w.strip() for w in when.split(";")]
            if len(whens) != len(names):
                whens = [when] * len(names)
            for code, case in zip(names, whens):
                case = case[:1].upper() + case[1:]
                errors.append({"status": int(status), "code": code, "name": code.replace("_", "-"), "when": case})
    if not errors and errors_needed:
        sys.exit("build_site: SPEC.md has no section of errors (## <n>. Errors) with its table")
    # The body, a part per top-level section (its heading to the next one's), so that the page can end each
    # with a link to its neighbours; the fenced code of a part may hold a line that looks like a heading.
    body_lines = rest[first:]
    starts, fenced = [], False
    for n, line in enumerate(body_lines):
        fenced = fenced != line.startswith("```")
        if line.startswith("## ") and not fenced:
            starts.append(n)
    if len(starts) != len(toc):
        sys.exit(f"build_site: {len(starts)} top-level headings in the text, {len(toc)} in its contents")
    parts = [(anchor, text, blocks(body_lines[a:b], sections, ref=ref)) for (anchor, text, _), a, b
             in zip(toc, starts, starts[1:] + [len(body_lines)])]
    status = None
    head = "\n".join(rest[:first])
    if m := STATUS.search(head):
        licence = LICENCE.search(head)
        href = licence.group(2) if licence else ""
        if href and not urlparse(href).scheme:
            href = f"{REPO}/blob/{ref}/{href}"
        status = {"draft": m.group(1), "date": m.group(2), "licence": licence.group(1) if licence else "",
                  "licence_href": href}
    return {"title": title, "intro": blocks(rest[:first], sections, ref=ref),
            "body": "\n".join(html_ for _, _, html_ in parts), "parts": parts, "toc": toc, "sections": sections,
            "errors": errors, "errors_section": errors_number, "text": "\n".join(lines), "status": status}


def toc_html(spec: dict, label: str, lang: str = "en") -> str:
    """The contents: a <details> (open without script; site/assets/spec.js folds it on a phone, and keeps it
    open beside the text), its summary the current section once script runs. The titles are the text's own."""
    items = []
    for anchor, text, subs in spec["toc"]:
        inner = ("<ol>" + "".join(f'<li><a href="#{a}">{html.escape(t)}</a></li>' for a, t in subs) + "</ol>") if subs else ""
        items.append(f'<li><a href="#{anchor}">{html.escape(text)}</a>{inner}</li>')
    return (f'<nav class="toc" aria-label="{label}"><details class="toc-box" open>'
            f'<summary><span class="toc-title">{label}</span><span class="toc-now" lang="{lang}"></span></summary>'
            f'<div class="toc-list"><ol lang="{lang}">' + "".join(items) + "</ol></div></details></nav>")


def search_form(catalog: dict, root: str) -> str:
    """The search field above the contents, hidden until site/assets/spec.js runs; its index is
    spec/search.json (search_index())."""
    texts = " ".join(f'data-{k.replace("_", "-")}="{html.escape(catalog["spec_" + k], quote=True)}"'
                     for k in ("search_none", "search_count", "search_error", "kind_section", "kind_req",
                               "kind_route", "kind_error"))
    return (f'<form class="spec-search" role="search" hidden data-index="{root}spec/search.json" {texts}>\n'
            f'<label for="spec-q">{catalog["spec_search"]}</label>\n'
            f'<input id="spec-q" type="search" name="q" autocomplete="off" spellcheck="false" enterkeyhint="search" '
            f'aria-keyshortcuts="/" aria-describedby="spec-q-keys" placeholder="{html.escape(catalog["spec_search_hint"], quote=True)}">\n'
            f'<p id="spec-q-keys" class="spec-keys">{catalog["spec_search_keys"]}</p>\n'
            f'<p class="sr" role="status" aria-live="polite" id="spec-q-status"></p>\n'
            f'<ul class="spec-results" id="spec-results" lang="en" hidden></ul>\n</form>')


def status_chips(spec: dict, catalog: dict) -> str:
    """The text's draft, date and licence as a row of chips, read from its status line (read_spec())."""
    status = spec.get("status")
    if not status:
        return ""
    items = [f'<li>{catalog["spec_chip_draft"]} {html.escape(status["draft"])}</li>',
             f'<li><time datetime="{status["date"]}">{status["date"]}</time></li>']
    if status["licence"]:
        link = (f'<a href="{html.escape(status["licence_href"])}">{html.escape(status["licence"])}</a>'
                if status["licence_href"] else html.escape(status["licence"]))
        items.append(f'<li>{catalog["spec_chip_licence"]} {link}</li>')
    return f'<ul class="chips" aria-label="{catalog["spec_status"]}">{"".join(items)}</ul>'


def annex_cards(spec: dict, catalog: dict, lang: str) -> str:
    """A card for each of the annexes the page's text has (A: platforms, B: client authors, C: the road to
    1.0, D: reading guide), under the page's header; their titles are the text's, their words the catalog's."""
    cards = []
    for anchor, text, _ in spec["toc"]:
        m = re.match(r"Annexe? ([A-D]) — (.*)", text)
        if m and f"spec_annex_{m.group(1).lower()}" in catalog:
            cards.append(f'<li><a href="#{anchor}"><span class="annex-k" lang="{lang}">{html.escape(text.split(" — ")[0])}</span>'
                         f'<strong lang="{lang}">{html.escape(m.group(2))}</strong>'
                         f'<span class="annex-d">{catalog["spec_annex_" + m.group(1).lower()]}</span></a></li>')
    return f'<nav class="annex-cards" aria-label="{catalog["spec_annexes"]}"><ul>{"".join(cards)}</ul></nav>\n' if cards else ""


def section_nav(parts: list, i: int, catalog: dict, ui: str) -> str:
    """The end of a top-level section: the sections around it and the way back to the top."""
    def link(j, rel, key):
        return (f'<a rel="{rel}" href="#{parts[j][0]}"><span class="sec-dir" lang="{ui}">{catalog[key]}</span> '
                f'<span class="sec-name">{html.escape(parts[j][1])}</span></a>') if 0 <= j < len(parts) else ""
    return (f'<div class="sec-nav">{link(i - 1, "prev", "spec_prev")}{link(i + 1, "next", "spec_next")}'
            f'<a class="sec-top" href="#top" lang="{ui}">{catalog["spec_top"]}</a></div>')


# ---- The page around them.

def indexing(language: str, path: str, alternate: bool, noindex: bool = False) -> str:
    """The canonical address and, for a page in every language, the others'; a page kept out of search
    engines (an earlier draft, the trapped libraries) says so."""
    if not alternate:
        lines = [f'<link rel="canonical" href="{LANTERN.address(language, path)}">']
    else:
        lines = LANTERN.indexing(language, path).split("\n")
    if noindex:
        lines.insert(0, '<meta name="robots" content="noindex">')
    return "\n".join(lines)


def hero(page: str, catalog: dict, root: str, language: str, spec: dict, extra: dict) -> str:
    if page == "home":   # site/hero.html, filled with the page's values (page_html())
        return (SITE / "hero.html").read_text(encoding="utf-8")
    if page == "translations" and "h1" not in extra:
        return (f'<div class="wrap hero small">\n    <span class="eyebrow">{catalog["tr_eyebrow"]}</span>\n'
                f'    <h1>{catalog["tr_title"]}</h1>\n    <p class="lede">{catalog["tr_lede"]}</p>\n  </div>')
    if page == "examples" and "h1" not in extra:
        return (f'<div class="wrap hero small">\n    <span class="eyebrow">{catalog["examples_eyebrow"]}</span>\n'
                f'    <h1>{catalog["examples_title"]}</h1>\n    <p class="lede">{catalog["examples_lede"]}</p>\n  </div>')
    if page == "check" and "h1" not in extra:
        return (f'<div class="wrap hero small">\n    <span class="eyebrow">{catalog["check_eyebrow"]}</span>\n'
                f'    <h1>{catalog["check_title"]}</h1>\n    <p class="lede">{catalog["check_lede"]}</p>\n  </div>')
    if page == "start" and "h1" not in extra:
        return (f'<div class="wrap hero small">\n    <span class="eyebrow">{catalog["start_eyebrow"]}</span>\n'
                f'    <h1>{catalog["start_title"]}</h1>\n    <p class="lede">{catalog["start_lede"]}</p>\n  </div>')
    if page == "sdk" and "h1" not in extra:
        return (f'<div class="wrap hero small">\n    <span class="eyebrow">{catalog["sdk_eyebrow"]}</span>\n'
                f'    <h1>{catalog["sdk_title"]}</h1>\n    <p class="lede">{catalog["sdk_lede"]}</p>\n  </div>')
    if page == "demo" and "h1" not in extra:
        return (f'<div class="wrap hero small">\n    <span class="eyebrow">{catalog["demo_eyebrow"]}</span>\n'
                f'    <h1>{catalog["demo_title"]}</h1>\n    <p class="lede">{catalog["demo_lede"]}</p>\n  </div>')
    if page == "spec" and "h1" not in extra:
        translated = extra.get("translation")
        if translated:
            note = (f'\n    <p class="banner" role="note" lang="{translated["lang"]}">{html.escape(translated["banner"])} '
                    f'<a href="{root}spec/" lang="en" hreflang="en">{html.escape(translated["english"])}</a></p>')
        elif language != ENGLISH:
            note = f'\n    <p class="note-en">{catalog["spec_english"]}</p>'
        else:
            note = ""
        start = spec["sections"].get("D")
        where = ""
        if start:
            jump = "" if translated else f' <a class="spec-jump" href="#spec-q" hidden>{catalog["spec_search"]}</a>'
            where = f'\n    <p class="spec-start"><a href="#{start}">{catalog["spec_start"]}</a>{jump}</p>'
        return (f'<div class="wrap hero small">\n    <span class="eyebrow">{catalog["spec_eyebrow"]}</span>\n'
                f'    <h1>{catalog["spec_title"]}</h1>\n    <p class="lede">{catalog["spec_lede"]}</p>{note}{where}\n'
                f'    {status_chips(spec, catalog)}\n'
                f'    {drafts_nav(catalog, root, language, "current", translated is None)}\n  </div>')
    more = f'\n    {extra["after"]}' if extra.get("after") else ""
    return (f'<div class="wrap hero small">\n    <span class="eyebrow">{extra["eyebrow"]}</span>\n'
            f'    <h1>{extra["h1"]}</h1>\n    <p class="lede">{extra["lede"]}</p>{more}\n  </div>')


def drafts_nav(catalog: dict, root: str, language: str, here: str, translations: bool = True) -> str:
    """The specification's drafts: the current text, each draft as it was published, what changed; and
    its translations. `here` is the one shown ("current", a draft, or "changes")."""
    def item(key, href, label):
        current = ' aria-current="page"' if key == here else ""
        return f'<li><a href="{href}"{current}>{label}</a></li>'
    # "Current" names the draft it is (the latest draft's own page is the same text, so it has no chip of its own
    # unless it is the page shown).
    items = [item("current", f"{root}{folder(language)}spec/", f'{catalog["spec_current"]} · {DRAFT}')]
    items += [item(v, f"{root}spec/{v}/", v) for v, _, _ in reversed(DRAFTS) if v != DRAFT or here == v]
    items.append(item("changes", f"{root}spec/changes/", catalog["spec_changes"]))
    links, seen = [], set()
    for c, _, name, hl in LANGUAGES:
        if translations and c in TRANSLATIONS and TRANSLATIONS[c] not in seen:
            seen.add(TRANSLATIONS[c])
            links.append(f'<a href="{root}{folder(c)}spec/" lang="{hl}" hreflang="{hl}">{html.escape(name)}</a>')
    links = f'<p class="translations">{catalog["spec_translations"]} {" · ".join(links)}</p>' if links else ""
    return (f'<nav class="drafts" aria-label="{catalog["spec_drafts"]}"><span class="drafts-label">'
            f'{catalog["spec_drafts"]}</span><ul>{"".join(items)}</ul></nav>{links}')


def put_diagrams(text: str, catalog: dict, sections: dict, drawn: bool, ui: str, meta: dict | None = None) -> str:
    """The figures at their headings (diagrams.WHERE), and under each heading its line of aids (`meta`: the
    draft each section first appeared in, and the English titles an issue about it quotes) in `text`; an
    earlier draft, whose sections are not these, gets none."""
    def aids(m):
        anchor = m.group(1)
        if not drawn or not meta or anchor not in meta["titles"]:
            return ""
        number, title = meta["titles"][anchor]
        what = f"{number} {title}".strip()
        ask = (f'<a class="ask" rel="noreferrer" href="{REPO}/issues/new?title='
               f'{urllib.parse.quote("question: " + what)}&body='
               f'{urllib.parse.quote("About " + what + " of SPEC.md, draft " + DRAFT + ".")}" '
               f'title="{html.escape(catalog["spec_ask_title"], quote=True)}">{html.escape(catalog["spec_ask"])}</a>')
        since = meta["since"].get(anchor)
        chip = (f'<span class="since">{html.escape(catalog["spec_since"].replace("{v}", since))}</span>'
                if since and since != DRAFTS[0][0] else "")
        return f'<p class="sec-meta">{chip}{ask}</p>'
    text = re.sub(r"<!--meta:([^>]*?)-->", aids, text)
    return re.sub(r"<!--diagram:(\w+)-->",
                  lambda m: diagrams.render(m.group(1), catalog, sections, f"figures/{m.group(1)}.{ui}.svg", stepper=True) if drawn else "", text)


def spec_body(spec: dict, catalog: dict, lang: str = "en", source: str = f"{REPO}/blob/main/SPEC.md",
              label: str | None = None, ui: str = "en", root: str = "", search: bool = False,
              cards: bool = False, drawn: bool = False, meta: dict | None = None) -> str:
    """The specification's text with its contents beside it. `lang` is the text's, `ui` the page's language;
    `search` puts the search field above the contents (the current English text, whose index search_index()
    writes), `cards` the annexes' under the header (the current text's)."""
    texts = " ".join(f'data-{k.replace("_", "-")}="{html.escape(catalog["spec_" + k], quote=True)}"'
                     for k in ("copy", "copied", "copy_failed"))
    # The print button is hidden until site/assets/spec.js runs: the browser's own print gives the PDF.
    printing = f'<button type="button" class="spec-print" hidden>{html.escape(catalog["spec_print"])}</button>'
    side = (search_form(catalog, root) if search else "") + toc_html(spec, catalog["spec_toc"], lang) + printing
    text = "\n".join(html_ + "\n" + section_nav(spec["parts"], i, catalog, ui) for i, (_, _, html_) in enumerate(spec["parts"]))
    text = put_diagrams(text, catalog, spec["sections"], drawn, ui, meta)
    return (f'{annex_cards(spec, catalog, lang) if cards else ""}'
            f'<div class="spec-layout" data-ui="{ui}" {texts}>\n<div class="spec-side">\n{side}\n</div>\n'
            f'<article class="prose" lang="{lang}">\n<h2 class="spec-name sr">{html.escape(spec["title"])}</h2>\n'
            f'{spec["intro"]}\n{text}\n'
            f'<p class="source"><a href="{source}">{label or catalog["spec_source"]}</a></p>\n'
            f'</article>\n<p class="sr" role="status" aria-live="polite" id="spec-live"></p>\n</div>')


def search_index(spec: dict) -> dict:
    """The current specification's search index (spec/search.json, schema 1, read by site/assets/spec.js): its
    sections (number, title, the top-level section they are in), each requirement id with the sentence it ends
    and the section it is in, and the routes (code spans such as `GET <base>/v1/apps`) and error codes with the
    sections they appear in (at most three). English only, like the text. Built here, so that the page needs
    no service."""
    lines = spec["text"].split("\n")
    sections, requirements, terms = [], [], {}
    top, here, fenced = "", "", False
    para: list = []

    def add_term(term: str, kind: str, anchor: str) -> None:
        found = terms.setdefault((term, kind), [])
        if anchor and anchor not in found and len(found) < 3:
            found.append(anchor)

    def requirements_of(text: str) -> None:
        # An id in a code span is an example, not an anchor (inline()): masked, but its words are kept.
        text = re.sub(r"\s+", " ", text)
        masked = re.sub(r"`[^`]*`", lambda m: "_" * len(m.group(0)), text)
        for m in REQ.finditer(masked):
            sentence = text[:m.start()].rstrip()
            sentence = sentence[:-1] if sentence.endswith(".") else sentence
            cut = max(sentence.rfind(". "), sentence.rfind("] "))
            sentence = REQ.sub("", plain(sentence[cut + 2:] if cut >= 0 else sentence)).strip(" -;")
            if here:
                requirements.append({"id": m.group(1), "s": here, "t": sentence[-220:].strip()})

    def flush() -> None:
        if para:
            requirements_of(" ".join(para))
            para.clear()

    for line in lines[1:]:
        if line.startswith("```"):
            flush()
            fenced = not fenced
            continue
        if fenced:
            continue
        if m := re.match(r"(#{2,4}) (.*)", line):
            flush()
            shown, number, own = heading(m.group(2))
            here = own or spec["sections"].get(number) or slug(shown)
            if len(m.group(1)) == 2:
                top = plain(shown)
            sections.append({"id": here, "n": number or "", "t": plain(shown), "p": top if len(m.group(1)) > 2 else ""})
            continue
        if not line.strip() or re.match(r"(- |\d+\. )", line.lstrip()) or line.startswith("|"):
            flush()
        para.append(line.strip()) if line.strip() else None
        for span in re.findall(r"`([^`]+)`", line):
            if ROUTE.fullmatch(span) and len(span) > 1:
                add_term(span, "route", here)
    flush()
    errors_at = next((x["id"] for x in sections if ERRORS_HEADING.match("## " + x["t"])), "")
    for error in spec["errors"]:
        add_term(error["code"], "error", errors_at)
    return {"schema": 1, "draft": (spec.get("status") or {}).get("draft", ""), "sections": sections,
            "requirements": requirements,
            "terms": [{"t": t, "k": k, "s": a} for (t, k), a in terms.items() if a]}


def problem(error: dict) -> str:
    title = error["code"].replace("_", " ").capitalize()
    return html.escape(json.dumps({"schema": 1, "type": f"{SITE_URL}errors/{error['name']}", "title": title,
                                   "status": error["status"], "code": error["code"]}, indent=1))


def errors_body(spec: dict, root: str) -> str:
    rows = "\n".join(
        f'<tr id="{e["name"]}"><td><a href="{e["name"]}/"><code>{e["name"]}</code></a></td><td class="num">{e["status"]}</td>'
        f'<td><code>{e["code"]}</code></td><td>{inline(e["when"], {}) or "—"}</td></tr>' for e in spec["errors"])
    number = spec["errors_section"]
    anchor = spec["sections"].get(number, "")
    return (f'<section class="prose" lang="en">\n<p>Every error a Lantern server returns is '
            f'<code>application/problem+json</code> (RFC 9457) with a real status code. Its <code>type</code> is one of '
            f'these addresses, <code>{SITE_URL}errors/&lt;name&gt;</code>; its <code>code</code> is the same name in '
            f'snake case. <a href="{root}spec/#{anchor}">The specification, §&nbsp;{number}</a>.</p>\n'
            f'<div class="table" tabindex="0" role="region" aria-label="Error types"><table>\n'
            f'<thead><tr><th scope="col">Type</th><th scope="col" class="num">Status</th><th scope="col">code</th>'
            f'<th scope="col">When</th></tr></thead>\n<tbody>\n{rows}\n</tbody></table></div>\n'
            f'<p><code>detail</code> is for people: a client shows it, bounded and without control '
            f'characters.</p>\n</section>')


def error_body(spec: dict, error: dict, root: str) -> str:
    number = spec["errors_section"]
    anchor = spec["sections"].get(number, "")
    when = inline(error["when"], {}) or "—"
    return (f'<section class="prose" lang="en">\n<dl class="facts">\n'
            f'<div><dt>Status</dt><dd>{error["status"]}</dd></div>\n'
            f'<div><dt>code</dt><dd><code>{error["code"]}</code></dd></div>\n'
            f'<div><dt>type</dt><dd><code>{SITE_URL}errors/{error["name"]}</code></dd></div>\n'
            f'<div><dt>When</dt><dd>{when}</dd></div>\n</dl>\n'
            f'<p>As a server sends it (<code>application/problem+json</code>, RFC 9457), with a <code>detail</code> '
            f'for people when it has one:</p>\n<pre tabindex="0"><code class="language-json">{problem(error)}</code></pre>\n'
            f'<p><a href="{root}errors/#{error["name"]}">Every error type</a> · '
            f'<a href="{root}spec/#{anchor}">The specification, §&nbsp;{number}</a></p>\n</section>')


# ---- Conformance (SPEC.md § 17): the levels, the requirements and the checks
# that cover them, the registry of implementations, and the badges.

def suite_module():
    """conformance/run.py, for its REQS, CLIENT_RULES and UNSEEN (it runs nothing on import)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("lantern_conformance", ROOT / "conformance" / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def levels_table(spec: dict, root: str) -> str:
    """§ 17's table of levels, as SPEC.md gives it, its § links leading to the specification."""
    lines = SPEC.read_text(encoding="utf-8").split("\n")
    start = next(i for i, line in enumerate(lines) if line.startswith("| Level | What |"))
    rows = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        rows.append(line)
    shown = table(rows, spec["sections"], "Conformance levels").replace('href="#', f'href="{root}spec/#')
    # Each level with its badge (assets/badges/), in a last column: what a level looks like once it is reached.
    head, body = shown.split("</tr></thead>")
    cells = body.split("</tr>")
    if len(cells) - 1 != len(LEVELS):   # the rows, then the closing tags
        sys.exit(f"build_site: SPEC.md § 17's table has {len(cells) - 1} levels, LEVELS {len(LEVELS)}")
    cells = [c + (f'<td class="badge"><a href="{root}badge/"><img src="{root}assets/badges/{badge_file(k)}" '
                  f'alt="Lantern compatible {DRAFT} · {label}" height="28"></a></td>')
             for c, (k, label) in zip(cells, LEVELS)] + [cells[-1]]
    return head + '<th scope="col">Badge</th></tr></thead>' + "</tr>".join(cells)


def to_spec(text: str, root: str) -> str:
    return text.replace('href="#', f'href="{root}spec/#')


def badge_svg(level: str, label: str) -> str:
    """The "Lantern compatible" badge of a level, after Boréale's brand (branding/README.md): a frame in the
    aurora's colours around the night, the lantern in snow, the name in snow and the level in the aurora."""
    name, tag = "Lantern compatible", f"{DRAFT} · {label}"
    left = 30 + round(len(name) * 6.3) + 8
    right = round(len(tag) * 6.8) + 18
    width = left + right
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="28" viewBox="0 0 {width} 28" role="img" aria-label="{name} {tag}">
  <title>{name} {tag}</title>
  <defs><linearGradient id="aurora" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#00FFCC"/><stop offset="0.6" stop-color="#33BBFF"/><stop offset="1" stop-color="#8A5CFF"/></linearGradient></defs>
  <rect x="1" y="1" width="{width - 2}" height="26" rx="7" fill="#0E1A33" stroke="url(#aurora)" stroke-width="2"/>
  <line x1="{left}" y1="6" x2="{left}" y2="22" stroke="#22324F" stroke-width="1"/>
  <g transform="translate(9 4.5) scale(0.15) translate(-92 -62)">
    <path d="M114 78 A 14 14 0 0 1 142 78" fill="none" stroke="#E8EEF7" stroke-width="10" stroke-linecap="round"/>
    <path d="M106 84 L 150 84 L 162 98 L 94 98 Z" fill="#E8EEF7" stroke="#E8EEF7" stroke-width="6" stroke-linejoin="round"/>
    <rect x="102" y="106" width="52" height="64" rx="8" fill="none" stroke="#E8EEF7" stroke-width="12"/>
    <path d="M128 118 C 137 128, 140 136, 140 144 A 12 12 0 0 1 116 144 C 116 136, 119 128, 128 118 Z" fill="#E8EEF7"/>
    <rect x="92" y="178" width="72" height="12" rx="6" fill="#E8EEF7"/>
  </g>
  <text x="30" y="18.5" fill="#E8EEF7" font-family="Sora, 'Avenir Next', 'Segoe UI', system-ui, sans-serif" font-size="11.5" font-weight="600" letter-spacing="-0.1">{name}</text>
  <text x="{left + 9}" y="18.5" fill="#00FFCC" font-family="'JetBrains Mono', ui-monospace, Menlo, monospace" font-size="11.5" font-weight="500">{html.escape(tag)}</text>
</svg>
"""


def badge_file(level: str) -> str:
    return f"lantern-{DRAFT}-{level}.svg"


def conformance_body(spec: dict, root: str) -> str:
    return f"""<section class="prose" lang="en">
<p>A Lantern implementation is conformant at a level when the conformance suite, run against it, passes every
check of that level (<a href="{root}spec/#17-conformance">the specification, §&nbsp;17</a>). Every level of a
server needs <code>Lantern Core</code>; <code>Lantern Static</code> stands alone, for a static library
(<a href="{root}spec/#21-static-libraries">§&nbsp;21</a>), which the suite checks with <code>--static</code>.</p>
{levels_table(spec, root)}
<h2 id="run">Run the suite</h2>
<p>With a token that holds every scope the levels need, and its device key, and anonymously on a public server.
At the end it prints the levels reached, and why it did not reach the others.</p>
<pre tabindex="0"><code>pip install -r tools/requirements.txt
python3 conformance/run.py https://shelf.example.org/ --token et_… --key device.key
…
Levels reached (SPEC.md § 17, draft {DRAFT}): Lantern Core +titles +homebrew +events
python3 conformance/run.py --static https://lea.example.org/library/
…
Levels reached (SPEC.md § 17, draft {DRAFT}): Lantern Static</code></pre>
<p>A level is reached when its family is offered to the caller, none of its checks fails, and none was left out for
want of a token, a key or a scope. Each check names the requirements it covers: the
<a href="{root}requirements/">traceability page</a> lists them all, and those only a client can keep.</p>
<h2 id="name">The name and the badge</h2>
<p>Only an implementation that passes the suite at a level may call itself “Lantern compatible” and show
<a href="{root}badge/">the badge</a>, with that level and the version of the text it passed:
“Lantern compatible {DRAFT} · Core +titles”.</p>
<h2 id="registry">The registry</h2>
<p><a href="{root}implementations/">The implementations that pass</a>, the reference server first; yours joins
them by a pull request with the suite's report.</p>
<h2 id="vectors">Test vectors</h2>
<p>For client and server libraries, the bytes the text spells out, case by case, with what a reader decides:
signed requests, homebrew signatures, Ed25519 signatures a verifier refuses, SPKI fingerprints, paths,
<code>version_code</code> per profile, requirements, rating caps, encrypted backups and recovery phrases, grants,
sync's merge rule and the static layout, in
<a href="{REPO}/tree/main/vectors">vectors/</a>.</p>
</section>"""


def requirements_body(spec: dict, root: str) -> str:
    found, problems = spec_requirements.requirements()
    if problems:
        sys.exit("build_site: SPEC.md's requirement ids: " + "; ".join(problems[:3]))
    suite = suite_module()
    checks = {}
    for cid, ids in suite.REQS.items():
        shown = cid + ".*" if cid in ("features", "apps.pages", "schema.refused", "static.pages") else cid
        for rid in ids:
            checks.setdefault(rid, []).append(shown)
    client = {rid: rule for _, ids, rule in suite.CLIENT_RULES for rid in ids}
    counts = {"suite": 0, "client": 0, "unseen": 0}
    per_section = {}
    groups, current = [], None
    for r in found:
        if r["heading"] != current:
            current = r["heading"]
            groups.append((current, r["section"], []))
        if r["id"] in checks:
            kind, seen = "suite", "Checked by " + ", ".join(f"<code>{c}</code>" for c in checks[r["id"]])
        elif r["id"] in client:
            kind, seen = "client", "A client's rule: the suite cannot see it"
        else:
            kind, seen = "unseen", "Inside the server: the suite cannot see it (" + html.escape(suite.UNSEEN.get(r["id"], "")) + ")"
        counts[kind] += 1
        per_section.setdefault(r["section"], [r["heading"], 0, 0, 0, 0])
        per_section[r["section"]][1] += 1
        per_section[r["section"]][{"suite": 2, "client": 3, "unseen": 4}[kind]] += 1
        groups[-1][2].append(
            f'<li id="{r["id"]}"><p class="req-head"><a class="req" href="{root}spec/#{r["id"]}">{r["id"]}</a>'
            f'<span class="state">{r["level"]}</span><span class="seen {kind}">{seen}</span></p>'
            f'<p>{to_spec(inline(r["text"], spec["sections"]), root)}</p></li>')
    body = "\n".join(
        f'<h2 id="s-{html.escape(section)}">{inline(heading, spec["sections"], refs=False)}</h2>\n<ul class="reqs">\n'
        + "\n".join(items) + "\n</ul>" for heading, section, items in groups)
    total = len(found)
    rows = "".join(
        f'<tr><th scope="row"><a href="#s-{html.escape(section)}">{inline(heading, spec["sections"], refs=False)}</a></th>'
        f'<td>{n}</td><td>{a}</td><td>{b}</td><td>{c}</td></tr>' for section, (heading, n, a, b, c) in per_section.items())
    by_section = ('<h2 id="by-section">By section</h2>\n<div class="table"><table><thead><tr><th scope="col">Section</th>'
                  '<th scope="col">Requirements</th><th scope="col">Checked by the suite</th><th scope="col">A client keeps</th>'
                  f'<th scope="col">Inside a server</th></tr></thead><tbody>{rows}</tbody></table></div>')
    return (f'<section class="prose wide" lang="en">\n<p>Every MUST and SHOULD of the specification has an id '
            f'(<a href="{root}spec/#35-changes-and-proposals">§&nbsp;3.5</a>). Here is each one, and what sees it: the '
            f'checks of the <a href="{REPO}/blob/main/conformance/run.py">conformance suite</a> that cover it, or why the '
            f'suite cannot see it, a client\'s rule or one inside a server.</p>\n'
            f'<dl class="facts"><div><dt>In all</dt><dd>{total} requirements</dd></div>'
            f'<div><dt>Suite</dt><dd>{counts["suite"]} checked by the suite</dd></div>'
            f'<div><dt>Clients</dt><dd>{counts["client"]} a client keeps</dd></div>'
            f'<div><dt>Inside</dt><dd>{counts["unseen"]} inside a server</dd></div></dl>\n{by_section}\n{body}\n</section>')


def releases_body(root: str) -> str:
    """releases/: how a version of the text is released and how to check its files (SPEC.md § 3.6)."""
    v = DRAFT
    return f"""<section class="prose" lang="en">
<p>Each version of the text is released on the repository by a tag <code>spec-v&lt;version&gt;</code>
(<code>spec-v{v}</code>), from draft 0.6 on (<a href="{root}spec/#36-releases">the specification, §&nbsp;3.6</a>).
The maintainer makes the tag; the repository's release workflow builds the files from it, attests them and
publishes them, a prerelease while the text is a draft. <a href="{REPO}/releases">The releases, on GitHub</a>.</p>
<h2 id="files">What a release holds</h2>
<ul>
<li><code>SPEC.md</code> and <code>openapi.yaml</code>, as they are at the tag;</li>
<li><code>lantern-schemas-{v}.zip</code>, <code>lantern-examples-{v}.zip</code>, <code>lantern-vectors-{v}.zip</code>
and <code>lantern-conformance-{v}.zip</code>: the schemas, their examples, the test vectors and the conformance
suite;</li>
<li><code>lantern-{v}.zip</code>: all of them in one, with the licences;</li>
<li><code>SHA256SUMS</code>: the SHA-256 of each file.</li>
</ul>
<p>The zips are reproducible: the same tagged tree gives the same bytes. Each file carries a build provenance
attestation (SLSA, signed through Sigstore): GitHub's word that it was built from that tag by this repository's
release workflow, and not changed since.</p>
<h2 id="verify">Verify a release</h2>
<p>With the <a href="https://cli.github.com/">GitHub CLI</a>, download the release, check the attestation of each
file you use, then their sums:</p>
<pre tabindex="0"><code>gh release download spec-v{v} --repo JigSawFr/lantern
gh attestation verify lantern-{v}.zip --repo JigSawFr/lantern
sha256sum --check --ignore-missing SHA256SUMS</code></pre>
<p><code>gh attestation verify</code> fails when the file was not built by a workflow of
<code>JigSawFr/lantern</code>, or was changed after. To also require the release workflow itself:</p>
<pre tabindex="0"><code>gh attestation verify lantern-{v}.zip --repo JigSawFr/lantern \\
  --signer-workflow JigSawFr/lantern/.github/workflows/release.yml</code></pre>
<p>An implementation names the version it follows, and the conformance suite of that release checks it
(<a href="{root}conformance/">conformance levels</a>).</p>
<h2 id="schemas">The schemas at their address</h2>
<p>Each schema's <code>$id</code> is its stable address, where this site serves it as it is in the repository:
<a href="{root}schemas/v1/apps.json"><code>{SITE_URL}schemas/v1/apps.json</code></a>,
<a href="{root}schemas/v1/common.json"><code>{SITE_URL}schemas/v1/common.json</code></a>… The address of a schema of
<code>/v1/</code> never changes, and each release carries the same files
(<a href="{root}spec/#32-document-schema">§&nbsp;3.2</a>).</p>
</section>"""


def registry() -> list:
    """site/registry.json's implementations; another schema is none (workbench's rule), never an error."""
    data = json.loads((SITE / "registry.json").read_text(encoding="utf-8"))
    if type(data.get("schema")) is not int or data["schema"] != 1:
        return []
    return [i for i in data.get("implementations", []) if isinstance(i, dict) and isinstance(i.get("name"), str)]


def registry_body(root: str) -> str:
    names = dict(LEVELS)
    rows = "\n".join(
        f'<tr><td><a href="{html.escape(i["url"])}">{html.escape(i["name"])}</a></td><td>{html.escape(i.get("kind", ""))}</td>'
        f'<td>{" ".join(f"<span class=state>{html.escape(names.get(x, x))}</span>" for x in i.get("levels", []))}</td>'
        f'<td class="num">{html.escape(i.get("draft", ""))}</td><td>{html.escape(i.get("licence", ""))}</td>'
        f'<td class="num">{html.escape(i.get("checked", ""))}</td></tr>' for i in registry())
    # Level by level (the levels in rows, so that more implementations are more columns): its name, and for each
    # implementation a tick where the suite passed it, a dash where it has not been shown to.
    heads = "".join(f'<th scope="col">{html.escape(i["name"])}</th>' for i in registry())
    mrows = "\n".join(
        f'<tr><th scope="row"><code>{label}</code></th>'
        + "".join('<td class="reached"><span aria-hidden="true">✓</span><span class="sr">Reached</span></td>' if k in i.get("levels", [])
                  else '<td class="none"><span aria-hidden="true">–</span><span class="sr">Not shown</span></td>' for i in registry())
        + "</tr>" for k, label in LEVELS)
    matrix = (f'<div class="table matrix" tabindex="0" role="region" aria-label="Levels reached, by implementation"><table>'
              f'<thead><tr><th scope="col">Level</th>{heads}</tr></thead>\n<tbody>\n{mrows}\n</tbody></table></div>')
    return f"""<section class="prose wide" lang="en">
<p>The implementations that pass the conformance suite, with the levels they reach and the draft they passed
(<a href="{root}conformance/">conformance levels</a>). The reference server comes first: it is the text's own, and
it passes every level.</p>
<div class="table" tabindex="0" role="region" aria-label="Implementations"><table>
<thead><tr><th scope="col">Implementation</th><th scope="col">Kind</th><th scope="col">Levels</th>
<th scope="col" class="num">Draft</th><th scope="col">Licence</th><th scope="col" class="num">Checked</th></tr></thead>
<tbody>
{rows}
</tbody></table></div>
<h2 id="matrix">Levels reached</h2>
<p>The same, level by level (the badges are on <a href="{root}conformance/">the levels' page</a>): a tick where the suite passes a level at the draft the row names, a dash where it has not been
shown to.</p>
{matrix}
<h2 id="add">Add yours</h2>
<ol>
<li>Run the suite against your server, at this draft, with a token that holds every scope and its device key
(and anonymously, for a public server): <code>python3 conformance/run.py https://… --token … --key …</code>.</li>
<li>Add an entry to <a href="{REPO}/blob/main/site/registry.json">site/registry.json</a>: its <code>name</code>,
<code>kind</code> (server, client, library), <code>url</code>, <code>licence</code>, <code>language</code>, the
<code>draft</code> it passed, the <code>levels</code> the suite printed, and the day it was <code>checked</code>.</li>
<li>Open a pull request with the suite's report in its description. Its levels are those the report shows; a
client library is listed with the levels of the vectors and checks it passes.</li>
</ol>
<p>An entry stays while it passes: with a new draft, run the suite again and update its <code>draft</code>.</p>
</section>"""


def badge_body(root: str) -> str:
    imgs = "\n".join(f'<li><img src="{root}assets/badges/{badge_file(k)}" alt="Lantern compatible {DRAFT} · {label}" '
                     f'height="28"><code>{badge_file(k)}</code></li>' for k, label in LEVELS)
    url = f"{SITE_URL}assets/badges/{badge_file('core')}"
    link = f"{SITE_URL}implementations/?utm_source=github&amp;utm_medium=readme&amp;utm_campaign=badge"
    return f"""<section class="prose wide" lang="en">
<p>An implementation that passes the conformance suite at a level may show its badge: the <code>Core</code> one,
and one for each further level it reaches, with the draft it passed. Only then (<a href="{root}conformance/#name">the
name and the badge</a>).</p>
<ul class="badges">
{imgs}
</ul>
<h2 id="use">In a README</h2>
<pre tabindex="0"><code>[![Lantern compatible {DRAFT} · Core]({url})]({link.replace("&amp;", "&")})</code></pre>
<pre tabindex="0"><code>{html.escape(f'<a href="{link.replace("&amp;", "&")}"><img src="{url}" alt="Lantern compatible {DRAFT} · Core" height="28"></a>')}</code></pre>
<p>A badge says the draft it was checked against, and keeps saying it: with a new draft, run the suite again
before you show the new one. The badges follow Boréale's brand: the frame in the aurora's colours around the
night, the lantern in snow.</p>
</section>"""


# ---- The drafts, the translations and the demo.

def spec_at(commit: str) -> str:
    """SPEC.md as it was at `commit`, from git."""
    try:
        return subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:SPEC.md"], check=True, capture_output=True,
                              encoding="utf-8").stdout
    except (OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"build_site: SPEC.md of {commit[:7]} is not in git ({str(error).strip()}): the drafts need the "
                 "repository's history (git fetch --unshallow)")


# What the specification's page puts under each heading (section_aids(), filled by main()).
AIDS: dict = {}


def section_aids(current: str) -> dict:
    """For each section (## and ###) of the current text, by its anchor: the draft it first appeared in (walking
    the drafts of DRAFTS in order and following renamed sections: compared()), and its number and English title,
    which the issue about it quotes."""
    first, previous = {}, None
    for v, commit, _ in DRAFTS:
        text = current if commit is None else spec_at(commit)
        now = outline(text)
        if previous is None:
            first = {o["key"]: v for o in now}
        else:
            diff = compared(previous, now)
            kept = {o["key"]: first[o["key"]] for o in now if o["key"] in first}
            for old_o, new_o in diff["renamed"]:
                kept[new_o["key"]] = first.get(old_o["key"], v)
            for o in diff["added"]:
                kept[o["key"]] = v
            first = {k: kept.get(k, v) for k in (o["key"] for o in now)}
        previous = now
    final = outline(current)
    since = {o["anchor"]: first.get(o["key"]) for o in final}
    titles = {}
    for o in final:
        number = o["number"] or ""
        label = f"§ {number}" if number and number[0].isdigit() else (f"Annex {number}" if number else "")
        titles[o["anchor"]] = (label, re.sub(r"^(?:\d+(?:\.\d+)?\.?|Annex [A-Z] —|[A-Z]\.\d+) ", "", o["title"]).strip())
    return {"since": since, "titles": titles}


def read_translation(name: str) -> dict:
    """A translation of SPEC.md (site/translations/<name>): its header, a comment of `key: value` lines
    (language, commit, sha256: the English text it translates; banner, english, source), then its text."""
    text = (SITE / "translations" / name).read_text(encoding="utf-8")
    m = re.match(r"<!--\n(.*?)\n-->\n+", text, re.DOTALL)
    if not m:
        sys.exit(f"build_site: site/translations/{name} has no header")
    fields = dict(re.findall(r"^([a-z0-9-]+): (.+)$", m.group(1), re.MULTILINE))
    lacking = [k for k in ("language", "commit", "sha256", "banner", "english", "source") if k not in fields]
    if lacking:
        sys.exit(f"build_site: site/translations/{name}'s header lacks {', '.join(lacking)}")
    return {**fields, "name": name, "text": text[m.end():]}


FRENCH_BEFORE = re.compile(r" ([:;?!»])")
FRENCH_AFTER = re.compile(r"« ")


def french_spaces(text: str) -> str:
    """French typography in a rendered translation: the space before « : », « ; », « ? », « ! » and « »
    », and after « «, made non-breaking (a narrow one before ; ? !), so that a sign never wraps alone onto a
    line of its own. Only in the text: never inside a tag, <code> or <pre>, where a space is the code's."""
    out, depth = [], 0
    for part in re.split(r"(<[^>]+>)", text):
        if part.startswith("<"):
            m = re.match(r"<(/?)(code|pre)\b", part)
            if m:
                depth += -1 if m.group(1) else 1
            out.append(part)
        elif depth:
            out.append(part)
        else:
            part = FRENCH_BEFORE.sub(lambda m: ("\u202f" if m.group(1) in ";?!" else "\u00a0") + m.group(1), part)
            out.append(FRENCH_AFTER.sub("«\u00a0", part))
    return "".join(out)


def footer_translation(language: str, root: str) -> tuple:
    """The footer's link to the specification in the other language, as (text, href, attributes): French, or English from French."""
    if language in TRANSLATIONS:
        return "Specification in English", f"{root}spec/", {"lang": "en", "hreflang": "en"}
    code = next(iter(TRANSLATIONS))
    return "Spécification en français", f"{root}{folder(code)}spec/", {"lang": code, "hreflang": code}


def page_header(language: str, catalog: dict, root: str, path: str, page: str, versions: dict) -> str:
    """The page's header (boreale-site's chrome): the site's links, "Try it" as the call to action, GitHub."""
    home = root + folder(language)
    current = {"spec": "nav_spec", "demo": "nav_try", "sdk": "nav_sdk"}.get(page)
    if path == "conformance/":
        current = "footer_conformance"
    return LANTERN.header(language, catalog, root, path, links=[
        ("nav_how", f"{home}#how"), ("nav_spec", f"{home}spec/"), ("nav_sdk", f"{home}sdk/"),
        ("footer_conformance", f"{root}conformance/"),
    ], cta=("nav_try", f"{home}demo/"), github=REPO, current=current, label=catalog["nav_label"], latest=versions)


def page_footer(language: str, catalog: dict, root: str) -> str:
    """The page's footer: the protocol's pages, the rest of the project, the licences' line and the trademarks."""
    home = root + folder(language)
    translation = footer_translation(language, root)
    return LANTERN.footer(language, catalog, root, columns=[
        (catalog["nav_project"], [(catalog["nav_spec"], f"{home}spec/"), (catalog["footer_conformance"], f"{root}conformance/"),
                                  (catalog["footer_errors"], f"{root}errors/"), (catalog["footer_drafts"], f"{root}spec/changes/"),
                                  translation]),
        (catalog["footer_label"], [(catalog["footer_start"], f"{home}start/"), (catalog["footer_check"], f"{home}check/"), (catalog["footer_examples"], f"{home}examples/"), (catalog["nav_sdk"], f"{home}sdk/"), (catalog["footer_translations"], f"{home}translations/"), (catalog["footer_demo"], f"{home}demo/"), (catalog["footer_releases"], f"{root}releases/"),
                                   ("GitHub", REPO), (catalog["footer_issues"], f"{REPO}/issues")]),
    ], about=[catalog["footer_license"]], fine=catalog["footer_trademarks"])


def outline(text: str) -> list:
    """The ## and ### sections of a SPEC.md: each one's key (its title without its number, under its
    section's for a ###), number, title, anchor, level, and words (its own text, before its first part)."""
    out, parent = [], None
    for line in text.split("\n"):
        if m := re.match(r"(#{2,3}) (.*)", line):
            shown, number, own = heading(m.group(2))
            title = re.sub(r"^(?:\d+(?:\.\d+)?\.?|Annex [A-Z] —|[A-Z]\.\d+) ", "", plain(shown)).strip().lower()
            level = len(m.group(1))
            parent = title if level == 2 else parent
            out.append({"key": (None if level == 2 else parent, title), "number": number, "title": plain(shown),
                        "anchor": own or slug(shown), "level": level, "words": []})
        elif out:
            out[-1]["words"] += line.split()
    return [o for o in out if o["key"] != (None, "changes")]


def compared(before: list, after: list) -> dict:
    """The sections `after` added, removed, renamed, changed and renumbered against `before`. A section is
    changed when its words are, "§ n" references aside (a renumbering alone is not a change)."""
    def norm(words):
        return re.sub(r"§ \d+(?:\.\d+)?", "§", " ".join(words)).split()
    old = {o["key"]: o for o in before}
    new = {o["key"]: o for o in after}
    added = [o for o in after if o["key"] not in old]
    removed = [o for o in before if o["key"] not in new]
    renamed = []
    for a in list(added):
        scored = [(difflib.SequenceMatcher(None, norm(r["words"]), norm(a["words"]), autojunk=False).ratio(), i)
                  for i, r in enumerate(removed) if r["level"] == a["level"]]
        if scored and max(scored)[0] >= 0.5:
            r = removed.pop(max(scored)[1])
            added.remove(a)
            renamed.append((r, a))
    changed, renumbered = [], []
    for o in after:
        if o["key"] in old:
            b = old[o["key"]]
            if norm(b["words"]) != norm(o["words"]):
                changed.append((b, o))
            elif b["number"] != o["number"]:
                renumbered.append((b, o))
    return {"added": added, "removed": removed, "renamed": renamed, "changed": changed, "renumbered": renumbered}


def delta(b: dict, o: dict) -> str:
    plus, minus = delta_counts(b, o)
    return f'<span class="delta"><span class="plus">+{plus}</span> <span class="minus">−{minus}</span> words</span>'


def changes_notes(text: str) -> dict:
    """SPEC.md's section "Changes", by draft: {draft: [its lines]}."""
    lines = text.split("\n")
    start = next((i for i, line in enumerate(lines) if line == "## Changes"), None)
    notes, current = {}, None
    for line in lines[start + 1:] if start is not None else []:
        if line.startswith("## "):
            break
        if m := re.match(r"- (\d+\.\d+) \(", line):
            current = m.group(1)
        if current:
            notes.setdefault(current, []).append(line)
    return notes


def atom_feed(notes: dict) -> str:
    """feed.xml, an Atom feed (RFC 4287) of the drafts, newest first: for each, the sentence its "Changes" entry
    opens with, its date, and a link to its page (spec/<draft>/). A new draft is what an author of a client or
    a server wants to hear of."""
    entries = []
    for v, _, _ in reversed(DRAFTS):
        lines = notes.get(v)
        if not lines:
            continue
        date, text = draft_summary(lines)
        if not date:
            continue
        entries.append(
            f"  <entry>\n    <id>tag:{urlparse(SITE_URL).hostname},{date}:spec-{v}</id>\n"
            f"    <title>Draft {v}</title>\n    <updated>{date}T00:00:00Z</updated>\n"
            f'    <link rel="alternate" type="text/html" href="{html.escape(SITE_URL)}spec/{v}/"/>\n'
            f"    <summary>{html.escape(text)}</summary>\n  </entry>\n")
    updated = max((re.search(r"<updated>([^<]+)</updated>", e).group(1) for e in entries), default="2026-10-30T00:00:00Z")
    return ('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="en">\n'
            f"  <id>tag:{urlparse(SITE_URL).hostname},2026:drafts</id>\n  <title>Lantern: the drafts of the specification</title>\n"
            f"  <subtitle>A new draft of the Lantern protocol, and what it changes.</subtitle>\n  <updated>{updated}</updated>\n"
            f'  <link rel="self" type="application/atom+xml" href="{html.escape(SITE_URL)}feed.xml"/>\n'
            f'  <link rel="alternate" type="text/html" href="{html.escape(SITE_URL)}spec/"/>\n'
            f"  <author><name>Lantern</name></author>\n" + "".join(entries) + "</feed>\n")


def version_key(v: str) -> tuple:
    return tuple(int(n) for n in v.split("."))


def draft_summary(lines: list | None) -> tuple:
    """(date, the sentence) a "Changes" entry opens with, or (None, None): what the Atom feed and the cards of
    spec/changes/ both say first."""
    head = re.match(r"- \d+\.\d+ \((\d{4}-\d{2}-\d{2})\):\s*(.*)", (lines or [""])[0])
    if not head:
        return None, None
    summary = [head.group(2)]
    for line in lines[1:]:
        if not line.strip() or re.match(r"\s*- ", line):
            break
        summary.append(line.strip())
    return head.group(1), re.sub(r"\*\*|`", "", " ".join(summary).strip())


def delta_counts(b: dict, o: dict) -> tuple:
    plus = minus = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, b["words"], o["words"], autojunk=False).get_opcodes():
        if op in ("replace", "delete"):
            minus += i2 - i1
        if op in ("replace", "insert"):
            plus += j2 - j1
    return plus, minus


def diff_groups(d: dict, link, at: str, was_at: str) -> list:
    """The sections of a comparison (compared()) as (kind, label, [html]): `link(o, draft)` makes a section's
    link; `at` is the draft the new sections are read in, `was_at` the one the old ones are."""
    return [("added", "Added", [link(o, at) for o in d["added"]]),
            ("changed", "Changed", [f"{link(o, at)} {delta(b, o)}" + (f' <span class="was">was §&nbsp;{b["number"]}</span>'
                                    if b["number"] != o["number"] and b["number"] else "") for b, o in d["changed"]]),
            ("renamed", "Renamed or moved", [f'{link(o, at)} <span class="was">was {link(b, was_at)}</span> {delta(b, o)}'
                                             for b, o in d["renamed"]]),
            ("removed", "Removed", [link(o, was_at) for o in d["removed"]]),
            ("renumbered", "Renumbered only", [f'{link(o, at)} <span class="was">was §&nbsp;{b["number"]}</span>'
                                               for b, o in d["renumbered"]])]


def chip_lists(groups: list) -> str:
    return "".join(f'<h4>{label} ({len(items)})</h4><ul class="sections-diff kind-{kind}">'
                   + "".join(f"<li>{i}</li>" for i in items) + "</ul>" for kind, label, items in groups if items)


def changes_body(drafts: list) -> str:
    """spec/changes/: a card for each draft, newest first, on a timeline: the sentence its "Changes" opens with, the
    sections it added, changed, renamed and removed as counts and as lists, the text's own account; and, for an
    author who implements an older draft, what has changed since it (the panels of "Since your draft")."""
    notes = changes_notes(SPEC.read_text(encoding="utf-8"))
    latest_v, _, _, latest = drafts[-1]

    def link(o, at):
        number = f"§&nbsp;{o['number']} " if o["number"] and o["number"][0].isdigit() else ""
        return f'<a href="../{at}/#{o["anchor"]}">{number}{html.escape(re.sub(r"^[0-9.]+ ", "", o["title"]))}</a>'

    cards, previous = [], None
    for v, commit, pr, spec in drafts:
        here = outline(spec["text"])
        said = notes.get(v)
        date, summary = draft_summary(said)
        said_html = (blocks(said, spec["sections"], ref=commit or "main").replace('href="#', f'href="../{v}/#')
                     if said else "<p>The text says nothing of its changes.</p>")
        words = len(spec["text"].split())
        stats, groups = [], []
        if previous is None:
            stats.append(f'<span class="chip">{len(here)} sections</span>')
            sections = f"<p>The first draft: {len(here)} sections and parts, {words:,} words.</p>"
            heading_ = "Its sections"
        else:
            pv, before = previous
            d = compared(outline(before["text"]), here)
            groups = diff_groups(d, link, v, pv)
            for kind, label, items in groups:
                if items:
                    stats.append(f'<span class="chip kind-{kind}">{len(items)} {label.lower().split(" ")[0]}</span>')
            plus = sum(delta_counts(b, o)[0] for b, o in d["changed"] + d["renamed"]) + sum(len(o["words"]) for o in d["added"])
            minus = sum(delta_counts(b, o)[1] for b, o in d["changed"] + d["renamed"]) + sum(len(o["words"]) for o in d["removed"])
            stats.append(f'<span class="chip words"><span class="plus">+{plus:,}</span> <span class="minus">−{minus:,}</span> words</span>')
            sections = chip_lists(groups) if any(i for _, _, i in groups) else "<p>No section changed, read from the two texts.</p>"
            heading_ = f"Its sections, against draft {pv}"
        newest = v == latest_v
        links = (f'<a href="../{v}/">Read draft {v}</a> · {pull(pr, "lantern#")}'
                 + (f' · <code>{commit[:7]}</code>' if commit else ""))
        cards.append(
            f'<li class="draft" id="d-{v}">\n<header><h2><span class="v">Draft {v}</span>'
            + (f' <time datetime="{date}">{date}</time>' if date else "") + "</h2>"
            + ('<span class="now">current</span>' if newest else "") + "</header>\n"
            + (f'<p class="summary">{html.escape(summary)}</p>\n' if summary else "")
            + f'<p class="stats">{" ".join(stats)} <span class="chip words">{words:,} words</span></p>\n'
            + f'<p class="meta">{links}</p>\n'
            + f'<details class="fold" id="d-{v}-said"{" open" if newest else ""}><summary>What the text says</summary>{said_html}</details>\n'
            + f'<details class="fold" id="d-{v}-sections"{" open" if newest else ""}><summary>{heading_}</summary>{sections}</details>\n</li>')
        previous = (v, spec)

    # "Since your draft": for each older draft, what the current text has added, changed, renamed or removed
    # against it, read from the two texts; a panel shows when its link is followed (:target), without script.
    olders = [x for x in drafts if x[0] != latest_v]
    panels = []
    for v, _, _, spec in olders:
        d = compared(outline(spec["text"]), outline(latest["text"]))
        groups = diff_groups(d, link, latest_v, v)
        counts = ", ".join(f"{len(i)} {label.lower()}" for _, label, i in groups if i) or "nothing"
        between = ", ".join(f'<a href="#d-{x[0]}">{x[0]}</a>' for x in drafts if version_key(x[0]) > version_key(v))
        panels.append(f'<section class="since" id="since-{v}" aria-label="Since draft {v}">'
                      f'<h3>Since draft {v}: {counts}</h3>'
                      f'<p class="meta">Drafts since: {between}. Read from draft {v} and draft {latest_v} side by side.</p>'
                      + chip_lists(groups) + "</section>")
    picker = "".join(f'<a href="#since-{v}">{v}</a>' for v, _, _, _ in reversed(olders))
    rows = "".join(f'<tr><td><a href="#d-{v}">Draft {v}</a></td><td>{pull(pr)}</td>'
                   f'<td class="num">{len(outline(spec["text"]))}</td><td class="num">{len(spec["text"].split()):,}</td></tr>'
                   for v, commit, pr, spec in reversed(drafts))
    return ('<section class="prose wide changes" lang="en">\n<p>Every draft of the specification as it was published, '
            'newest first, and what it changed: the sentence its section “Changes” opens with, the sections it added, '
            'changed, renamed and removed against the draft before it, read from the two texts '
            '(a renumbering alone is not a change), and what the text itself says. Each draft keeps its page; '
            '<a href="../">the specification</a> is the current text. <a href="../../feed.xml">Follow the drafts by Atom</a>.</p>\n'
            '<nav class="since-pick" aria-label="Since your draft"><span class="label">I implement draft</span>'
            f'<span class="picks">{picker}</span></nav>\n'
            '<p class="note since-help">Pick the draft you implement: what the current text has changed since it.</p>\n'
            + "\n".join(panels) + '\n<ol class="timeline">\n' + "\n".join(reversed(cards)) + "\n</ol>\n"
            '<details class="fold sizes"><summary>The size of each draft</summary>'
            '<div class="table" tabindex="0" role="region" aria-label="Drafts"><table>\n'
            '<thead><tr><th scope="col">Draft</th><th scope="col">Pull request</th><th scope="col" class="num">'
            'Sections</th><th scope="col" class="num">Words</th></tr></thead>\n<tbody>\n' + rows
            + "\n</tbody></table></div></details>\n</section>")


def pull(pr: int | None, prefix: str = "#") -> str:
    """A draft's pull request, linked; "not merged yet" for the draft in progress (DRAFTS)."""
    return f'<a href="{REPO}/pull/{pr}">{prefix}{pr}</a>' if pr else "not merged yet"


def draft_banner(v: str, pr: int | None) -> str:
    if v != DRAFT:
        later = DRAFTS[[d for d, _, _ in DRAFTS].index(v) + 1][0]
        return (f'<p class="banner" role="note"><strong>Draft {v}, superseded;</strong> the current draft is '
                f'<a href="../">{DRAFT}</a>. <a href="../changes/#d-{later}">What changed since</a>.</p>')
    if pr is None:
        return (f'<p class="banner" role="note"><strong>Draft {v}, the current draft,</strong> not merged yet: '
                f'this page is SPEC.md as it is now. <a href="../">The current text</a> is the same.</p>')
    return (f'<p class="banner" role="note"><strong>Draft {v} as it was published</strong> (lantern#{pr}). '
            f'<a href="../">The current text</a> is this draft, with the fixes made since, if any.</p>')


def trapped_body() -> str:
    rows = "\n".join(
        f'<tr id="{name}"><td><a href="{name}/lantern.json"><code>{name}</code></a></td><td>{inline(what, {})}</td>'
        f'<td>{inline(expect, {})}</td><td>{", ".join(f"<code>{c}</code>" for c in checks)}</td></tr>'
        for name, what, expect, checks, _ in make_demo.SCENARIOS)
    return f"""<section class="prose wide" lang="en">
<p class="banner" role="note"><strong>Broken on purpose.</strong> Each folder below is a static library with one
fault, for testing what a client does with a library that lies. Install nothing from them, and never point a device
you care about at them.</p>
<p>Each one is the <a href="../">demo library</a>'s first Switch game, its cheat sets and a homebrew, with one thing
broken. Point the client under test at a folder (<code>{SITE_URL}demo/trapped/bad-digest/</code>), and check that it
does what the third column says. <a href="scenarios.json">scenarios.json</a> lists them for a test harness
(<code>schema</code> 1: each one's <code>root</code>, <code>what</code>, <code>expect</code> and the suite's checks
that refuse it). They mirror the malicious test server of lantern-sdk's Python library where a static file can
express the fault; a fault of TLS, of pairing or of a server's answers has no static form.</p>
<div class="table" tabindex="0" role="region" aria-label="Scenarios"><table>
<thead><tr><th scope="col">Scenario</th><th scope="col">What is broken</th><th scope="col">What a client does</th>
<th scope="col">The suite's checks that refuse it</th></tr></thead>
<tbody>
{rows}
</tbody></table></div>
<p>The conformance suite checks each one at every build of this site, and must refuse it by the checks named:
<code>python3 tools/make_demo.py check build/demo</code>.</p>
</section>"""


def crumbs_html(catalog: dict, root: str, language: str, items: list) -> str:
    """The breadcrumb of a page below the home page: `items` are (label, address) pairs, the address under the
    language's folder, the last one the page itself (aria-current). Empty for the home page."""
    if not items:
        return ""
    home = root + folder(language)
    trail = [(catalog["nav_project"], home)] + [(label, root + folder(language) + href if href else None) for label, href in items]
    parts = []
    for label, href in trail:
        inner = f'<a href="{href}">{html.escape(label)}</a>' if href else f'<span aria-current="page">{html.escape(label)}</span>'
        parts.append(f"<li>{inner}</li>")
    return (f'<nav class="wrap crumbs" aria-label="{html.escape(catalog["crumbs_label"], quote=True)}"><ol>'
            + "".join(parts) + "</ol></nav>")


def demo_stats() -> dict:
    """What the demo library holds, counted from its source (site/demo/demo.json) at each build."""
    data = json.loads(make_demo.SOURCE.read_text(encoding="utf-8"))
    names = {"switch": "Nintendo Switch", "3ds": "New 3DS", "vita": "PS Vita", "android": "Android", "linux": "Linux"}

    def platforms(codes):
        return ", ".join(names.get(c, c) for c in dict.fromkeys(codes))
    apps, homebrew, cheats = data["apps"], data["homebrew"], data["cheats"]
    return {
        "games": {"count": len(apps), "platforms": platforms(a["file"].split("/")[0] for a in apps)},
        "homebrew": {"count": len(homebrew), "platforms": platforms(h["platform"] for h in homebrew),
                     "signed": sum(1 for h in homebrew if h.get("signed_by"))},
        "cheats": {"count": len(cheats), "platforms": platforms(c["platform"] for c in cheats),
                   "codes": sum(len(re.findall(r"^\[", c["text"], re.M)) for c in cheats)},
    }


# ---- The SDK's page: sdk.json, what lantern-sdk says about itself (its tools/site_data.py), read at each build.

SDK_REPO = "https://github.com/JigSawFr/lantern-sdk"
#: The commit of lantern-sdk whose sdk.json the page shows; raised by a pull request (a Dependabot-like bump by hand).
SDK_COMMIT = "9fc3b4f817e7186eb5f6a33979e4dbebdbf6c0b7"
SDK_SCHEMA = 1
SDK_CALLS = ("handshake", "apps", "missing", "download", "pair", "await_pairing", "upload_save", "events", "serve",
             "static_write", "static_read")
SDK_LANGS = ("cpp", "c", "python", "typescript", "go", "rust")
SDK_NAMES = {"cpp": "C++", "c": "C", "python": "Python", "typescript": "TypeScript", "go": "Go", "rust": "Rust"}


def sdk_data() -> dict | None:
    """sdk.json of lantern-sdk at SDK_COMMIT (or the file SDK_JSON names, for a local build); None when it cannot be
    read (SITE_OFFLINE, no network) or states a newer `schema`, and the page then says its data is not there."""
    local = os.environ.get("SDK_JSON")
    try:
        if local:
            raw = Path(local).read_text(encoding="utf-8")
        elif os.environ.get("SITE_OFFLINE") or SDK_COMMIT is None:
            return None
        else:
            import urllib.request
            url = f"https://raw.githubusercontent.com/JigSawFr/lantern-sdk/{SDK_COMMIT}/sdk.json"
            with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 (a fixed https address)
                raw = response.read().decode("utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("schema"), int) or data["schema"] > SDK_SCHEMA:
        return None  # a newer schema is read as absent (the rule of versioned formats)
    return data


def sdk_values(catalog: dict, root: str, home: str, sections: dict) -> dict:
    """The SDK page's blocks, from sdk.json; empty ones and a note when the data is not there."""
    data = sdk_data()
    keys = ("sdk_head", "sdk_cards", "sdk_parity", "sdk_levels", "sdk_calls", "sdk_examples", "sdk_versions", "sdk_use", "sdk_origin")
    trust = sdk_trust(catalog, root)
    nav = sdk_nav(catalog)
    if data is None:
        return {**{k: "" for k in keys}, "sdk_legend": sdk_legend(catalog), "sdk_trust": trust, "sdk_nav": nav,
                "sdk_nodata": f'<p class="note">{catalog["sdk_nodata"]}</p>'}
    return {"sdk_nodata": "", "sdk_legend": sdk_legend(catalog), "sdk_trust": trust, "sdk_nav": nav, "sdk_head": sdk_head(catalog, data), "sdk_use": sdk_use(catalog, data), "sdk_origin": sdk_origin(catalog),
            "sdk_cards": sdk_cards(catalog, data),
            "sdk_parity": sdk_parity(catalog, data), "sdk_levels": sdk_levels(catalog, data, root),
            "sdk_calls": sdk_calls(catalog, data, root, home, sections), "sdk_examples": sdk_examples(catalog, data),
            "sdk_versions": sdk_versions(catalog, data)}


def sdk_legend(catalog: dict) -> str:
    return catalog["sdk_legend"].replace("◐", HALF)


SDK_SECTIONS = ("pick", "parity", "calls", "examples", "trust", "versions")


def sdk_nav(catalog: dict) -> str:
    links = "".join(f'<li><a href="#{k}">{catalog["sdk_nav_" + k]}</a></li>' for k in SDK_SECTIONS)
    return f'<nav class="subnav" aria-label="{html.escape(catalog["sdk_nav_aria"], quote=True)}"><ul>{links}</ul></nav>'


def sdk_trust(catalog: dict, root: str) -> str:
    tiles = (("suite", f'{root}conformance/'), ("hostile", None), ("vectors", None), ("release", None))
    out = []
    for key, link in tiles:
        text = catalog["sdk_trust_" + key + ("_x" if key == "release" else "")]
        title = catalog["sdk_trust_" + key + "_t"]
        head = f'<a href="{html.escape(link, quote=True)}">{title}</a>' if link else title
        out.append(f'<li class="card"><h3>{head}</h3><p>{text}</p></li>')
    return '<ul class="cards cards-small trust">' + "".join(out) + "</ul>"


def sdk_head(catalog: dict, data: dict) -> str:
    sdk = data.get("sdk", {})
    release = sdk.get("release")
    state = catalog["sdk_released"].replace("{v}", str(release)) if release else catalog["sdk_unreleased"]
    chips = [("sdk_k_version", sdk.get("version", "")), ("sdk_k_draft", sdk.get("spec_draft", "")),
             ("sdk_k_capi", sdk.get("c_api_version", ""))]
    items = "".join(f'<li>{catalog[k]} <strong>{html.escape(str(v))}</strong></li>' for k, v in chips if v != "")
    return (f'<ul class="chips">{items}</ul>\n    <p class="note">{state} '
            f'<a href="{html.escape(sdk.get("releases", SDK_REPO), quote=True)}">{catalog["sdk_releases"]}</a> · '
            f'<a href="{SDK_REPO}">GitHub</a></p>')


#: Who each library is for: (the text's key, the language), the reader's own situation first.
SDK_USES = (("console", "cpp"), ("mobile", "c"), ("python", "python"), ("web", "typescript"))


def sdk_use(catalog: dict, data: dict) -> str:
    """"Which one is for me": a line a situation, leading to the card of the language; and the picker that, with
    script, sets the language the page follows (the buttons are hidden until sdk.js shows them)."""
    ids = {lang.get("id") for lang in data.get("languages", [])}
    items = "".join(f'<li>{catalog["sdk_use_" + key]} <a href="#sdk-{lang}">{SDK_NAMES[lang]}</a></li>'
                    for key, lang in SDK_USES if lang in ids)
    buttons = "".join(f'<button type="button" data-pick="{lang}" aria-pressed="false">{SDK_NAMES[lang]}</button>'
                      for lang in SDK_LANGS if lang in ids)
    label = html.escape(catalog["sdk_i_code"], quote=True)
    return (f'<div class="picker" hidden role="group" aria-label="{label}"><span>{catalog["sdk_i_code"]}</span>{buttons}</div>\n'
            f'    <h3>{catalog["sdk_use_title"]}</h3>\n    <ul class="uses">{items}</ul>')


def sdk_origin(catalog: dict) -> str:
    short = SDK_COMMIT[:7]
    return f'<p class="note origin">{catalog["sdk_origin"].replace("{c}", f"<a href={chr(34)}{SDK_REPO}/commit/{SDK_COMMIT}{chr(34)}><code>{short}</code></a>")}</p>'


def sdk_counts(data: dict, lang: str) -> tuple[int, int, int] | None:
    families = data.get("families", [])
    if not any(lang in row.get("support", {}) for row in families):
        return None
    got = [sum(1 for row in families if row.get("support", {}).get(lang, {}).get(side) == "yes") for side in ("client", "server")]
    return got[0], got[1], len(families)


def sdk_cards(catalog: dict, data: dict) -> str:
    cards = []
    for lang in data.get("languages", []):
        name = html.escape(str(lang.get("name", "")))
        status = lang.get("status", "")
        facts = [("sdk_k_requires", lang.get("requires")), ("sdk_k_package", lang.get("package")),
                 ("sdk_k_adapters", ", ".join(lang.get("adapters", [])))]
        rows = "".join(f"<div><dt>{catalog[k]}</dt><dd>{html.escape(str(v))}</dd></div>" for k, v in facts if v)
        rows = rows.replace(f"<dd>{html.escape(str(lang.get('package') or ''))}</dd>", f"<dd><code>{html.escape(str(lang.get('package') or '')).replace('/', '/<wbr>')}</code></dd>") if lang.get("package") else rows
        install = lang.get("install")
        code = (f'<pre tabindex="0"><code>{html.escape(install)}</code></pre>' if install and (data.get("sdk") or {}).get("release") else "")
        readme = lang.get("readme")
        link = (f'<p class="more"><a href="{SDK_REPO}/blob/main/{html.escape(readme, quote=True)}">{catalog["sdk_readme"]}</a></p>'
                if readme else "")
        counts = sdk_counts(data, str(lang.get("id", "")))
        parity = (f'<p class="parity"><span>{catalog["sdk_client"]} <strong>{counts[0]}/{counts[2]}</strong></span> '
                  f'<span>{catalog["sdk_server"]} <strong>{counts[1]}/{counts[2]}</strong></span></p>' if counts else "")
        state = catalog["sdk_status_" + status] if "sdk_status_" + status in catalog else ""
        cards.append(f'<li class="card{" linked" if readme else ""}" id="sdk-{html.escape(str(lang.get("id", "")), quote=True)}" data-lang="{html.escape(str(lang.get("id", "")), quote=True)}"><h3>{name}</h3><p class="kind"><span class="pill pill-{html.escape(str(status), quote=True)}">{state}</span>'
                     f' {catalog["sdk_role_" + lang.get("role", "both")]}</p>{parity}<dl class="facts">{rows}</dl>{code}{link}</li>')
    return '<ul class="cards cards-small">' + "".join(cards) + "</ul>"


HALF = '<span class="half" aria-hidden="true"></span>'  # "part of it": drawn, a glyph of that shape is missing from most fonts
MARKS = {"yes": ("✓", "sdk_yes"), "partial": (HALF, "sdk_partial"), "no": ("–", "sdk_no")}


def sdk_cell(catalog: dict, kind: str) -> str:
    mark, key = MARKS.get(kind, ("–", "sdk_no"))
    shown = mark if mark == HALF else f'<span aria-hidden="true">{mark}</span>'
    return f'{shown}<span class="sr">{catalog[key]}</span>'


def sdk_parity_list(catalog: dict, data: dict, langs: list) -> str:
    """The parity by language, for a narrow screen where the table of twelve columns does not fit: a fold a language,
    its summary says how far it goes, its rows are the families."""
    families = data.get("families", [])
    out = []
    for lang in langs:
        got = sdk_counts(data, lang)
        if got is None:
            continue
        rows = "".join(
            f'<tr><th scope="row"><code>{html.escape(str(row.get("family", "")))}</code></th>'
            + "".join(f'<td class="{"reached" if row.get("support", {}).get(lang, {}).get(side) == "yes" else "none"}">'
                      f'{sdk_cell(catalog, row.get("support", {}).get(lang, {}).get(side, "no"))}</td>' for side in ("client", "server"))
            + "</tr>" for row in families)
        out.append(f'<details data-lang="{lang}"><summary><span>{SDK_NAMES[lang]}</span> <small>{catalog["sdk_client"]} {got[0]}/{got[2]} · '
                   f'{catalog["sdk_server"]} {got[1]}/{got[2]}</small></summary><table><caption class="sr">{SDK_NAMES[lang]}</caption>'
                   f'<thead><tr><th scope="col">{catalog["sdk_family"]}</th><th scope="col">{catalog["sdk_client"]}</th>'
                   f'<th scope="col">{catalog["sdk_server"]}</th></tr></thead><tbody>{rows}</tbody></table></details>')
    return f'<div class="parity-list">{"".join(out)}</div>'


def sdk_parity(catalog: dict, data: dict) -> str:
    langs = [lang for lang in SDK_LANGS if any(lang in row.get("support", {}) for row in data.get("families", []))]
    heads = "".join(f'<th scope="col" colspan="2" data-lang="{lang}">{SDK_NAMES[lang]}</th>' for lang in langs)
    sub = "".join(f'<th scope="col" data-lang="{lang}">{catalog["sdk_client"]}</th><th scope="col" data-lang="{lang}">{catalog["sdk_server"]}</th>' for lang in langs)
    rows = []
    for row in data.get("families", []):
        cells = ""
        for lang in langs:
            cell = row.get("support", {}).get(lang, {})
            cells += (f'<td data-lang="{lang}" class="{"reached" if cell.get("client") == "yes" else "none"}">{sdk_cell(catalog, cell.get("client", "no"))}</td>'
                      f'<td data-lang="{lang}" class="{"reached" if cell.get("server") == "yes" else "none"}">{sdk_cell(catalog, cell.get("server", "no"))}</td>')
        rows.append(f'<tr><th scope="row"><code>{html.escape(str(row.get("family", "")))}</code></th>{cells}</tr>')
    families = data.get("families", [])
    total = ""
    for lang in langs:
        for side in ("client", "server"):
            got = sum(1 for row in families if row.get("support", {}).get(lang, {}).get(side) == "yes")
            total += f'<td data-lang="{lang}" class="sum {"reached" if got == len(families) else "none" if got == 0 else "some"}">{got}/{len(families)}</td>'
    return (f'<div class="table matrix" tabindex="0" role="region" aria-label="{html.escape(catalog["sdk_parity_title"], quote=True)}"><table><caption class="sr">{html.escape(catalog["sdk_parity_title"])}</caption>'
            f'<thead><tr><th scope="col" rowspan="2">{catalog["sdk_family"]}</th>{heads}</tr><tr>{sub}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody><tfoot><tr><th scope="row">{catalog["sdk_total"]}</th>{total}</tr></tfoot></table></div>'
            + sdk_parity_list(catalog, data, langs))


def sdk_levels(catalog: dict, data: dict, root: str) -> str:
    """The levels each checked server reaches in CI (the string is "Lantern Core +titles …"), a chip a level, each
    leading to its badge's page; /badge/ has the badges themselves, which are too heavy to repeat here."""
    known = dict(LEVELS)
    rows = []
    for lang, level in (data.get("levels") or {}).items():
        reached = [("core" if token == "Core" else token.lstrip("+")) for token in str(level).replace("Lantern ", "", 1).split()]
        chips = "".join(f'<li><a href="{root}badge/">{html.escape(known[k])}</a></li>' for k in reached if k in known)
        rows.append(f'<li><strong>{SDK_NAMES.get(lang, html.escape(lang))}</strong><ul class="chips">{chips}</ul></li>')
    return f'<ul class="plain levels">{"".join(rows)}</ul>' if rows else ""


def sdk_calls(catalog: dict, data: dict, root: str, home: str, sections: dict) -> str:
    calls = {c.get("id"): c for c in data.get("calls", [])}
    langs = [lang for lang in SDK_LANGS if any(lang in c.get("calls", {}) for c in calls.values())]
    heads = "".join(f'<th scope="col" data-lang="{lang}">{SDK_NAMES[lang]}</th>' for lang in langs)
    rows = []
    for gesture in SDK_CALLS:
        call = calls.get(gesture)
        if call is None:
            continue
        cells = "".join(
            (f'<td data-lang="{lang}"><a href="{SDK_REPO}/blob/main/{html.escape(call["where"][lang], quote=True)}"><code>{html.escape(call["calls"][lang])}</code></a></td>'
             if call["calls"].get(lang) and lang in call.get("where", {}) else f'<td data-lang="{lang}" class="none"><span aria-hidden="true">–</span>'
             f'<span class="sr">{catalog["sdk_no"]}</span></td>') for lang in langs)
        spec = str(call.get("spec", ""))
        anchor = sections.get(spec)
        mark = f'§&nbsp;{html.escape(spec)}'
        link = f'<a href="{root}{home}spec/#{anchor}">{mark}</a>' if anchor else mark
        rows.append(f'<tr><th scope="row">{catalog["sdk_g_" + gesture]} {link}</th>{cells}</tr>')
    later = [SDK_NAMES[lang["id"]] for lang in data.get("languages", []) if lang.get("id") in SDK_NAMES and lang["id"] not in langs]
    note = f'<p class="note">{catalog["sdk_calls_later"].replace("{langs}", ", ".join(later))}</p>' if later else ""
    return (f'<div class="table calls" tabindex="0" role="region" aria-label="{html.escape(catalog["sdk_calls_title"], quote=True)}"><table><caption class="sr">{html.escape(catalog["sdk_calls_title"])}</caption>'
            f'<thead><tr><th scope="col">{catalog["sdk_gesture"]}</th>{heads}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>{note}')


#: The examples are gathered by the task they do, from their file names: (task, the start of the name), then the
#: variant a name carries after it, shown beside the language ("Python (Flask)").
SDK_TASKS = (("read", ("read",)), ("pair", ("pair",)), ("serve", ("serve", "demo")), ("static", ("static",)))
SDK_VARIANTS = {"flask": "Flask", "fastapi": "FastAPI", "node": "node:http", "server": "server core"}


def sdk_task(path: str) -> tuple[str | None, str | None]:
    stem = re.split(r"[-_]", Path(path).stem, maxsplit=1)
    for task, starts in SDK_TASKS:
        if stem[0] in starts:
            return task, (stem[1] if len(stem) > 1 else None)
    return None, None


#: The keywords each language's examples are coloured with; the rest of a line is left as it is.
SDK_KEYWORDS = {
    "cpp": "auto bool break case catch class const constexpr continue co_await co_return else enum explicit false for if inline namespace new noexcept nullptr operator private public return static struct switch template this throw true try typename using virtual void while int char unsigned",
    "c": "break case char const continue else enum extern false for if int return sizeof static struct switch true typedef union unsigned void while",
    "python": "and as assert async await class def elif else except False finally for from if import in is lambda None not or pass raise return True try while with yield",
    "typescript": "as async await break case catch class const continue default else export extends false finally for from function if import in instanceof interface let new null of return static switch this throw true try type typeof undefined var void while",
    "go": "break case chan const continue default defer else false for func go if import interface map nil package range return select struct switch true type var",
    "rust": "as async await break const continue crate else enum false fn for if impl in let loop match mod move mut pub ref return self Self static struct trait true type unsafe use where while",
}
_DQ = r'"(?:\\.|[^"\\\n])*"'
_SQ = r"'(?:\\.|[^'\\\n])*'"
_CHAR = r"'(?:\\.|[^'\\\n])'"
_TICK = r"`[^`]*`"
_TRIPLE = r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\''
#: Per language: how a line comment starts and what a string looks like.
SDK_SYNTAX = {
    "cpp": (r"//[^\n]*", f"{_DQ}|{_CHAR}"), "c": (r"//[^\n]*", f"{_DQ}|{_CHAR}"),
    "python": (r"#[^\n]*", f"{_TRIPLE}|{_DQ}|{_SQ}"), "typescript": (r"//[^\n]*", f"{_DQ}|{_SQ}|{_TICK}"),
    "go": (r"//[^\n]*", f"{_DQ}|{_TICK}|{_CHAR}"), "rust": (r"//[^\n]*", _DQ),
}


def sdk_highlight(source: str, lang: str) -> str:
    """The source of an example, escaped and with spans for its comments, strings, numbers and keywords: a small
    tokenizer, not a parser (a miss only leaves a word uncoloured). Classes only, so the CSP stays as it is."""
    comment, strings = SDK_SYNTAX.get(lang, (r"//[^\n]*", _DQ))
    words = set(SDK_KEYWORDS.get(lang, "").split())
    pattern = re.compile(rf"(?P<c>{comment}|/\*[\s\S]*?\*/)|(?P<s>{strings})|(?P<n>\b\d[\w.]*)|(?P<k>\b[A-Za-z_]\w*\b)")
    out, last = [], 0
    for m in pattern.finditer(source):
        out.append(html.escape(source[last:m.start()]))
        kind, text = m.lastgroup, m.group()
        if kind == "k" and text not in words:
            out.append(html.escape(text))
        else:
            out.append(f'<span class="tk-{kind}">{html.escape(text)}</span>')
        last = m.end()
    out.append(html.escape(source[last:]))
    return "".join(out)


SDK_FOLD = 30  # lines above which an example is shown cut, with "show all"


def sdk_code(catalog: dict, ident: str, lang: str, source: str) -> str:
    """An example's source, coloured; a long one is cut with a toggle (a checkbox, so that it works without script)."""
    pre = f'<pre tabindex="0"><code class="language-{html.escape(lang, quote=True)}">{sdk_highlight(source, lang)}</code></pre>'
    lines = source.count("\n") + 1
    if lines <= SDK_FOLD:
        return pre
    more = catalog["sdk_show_all"].replace("{n}", str(lines))
    return (f'<div class="fold"><input type="checkbox" id="{ident}-fold" class="fold-toggle">'
            f'<div class="fold-body">{pre}</div>'
            f'<label for="{ident}-fold"><span class="fold-more">{more}</span><span class="fold-less">{catalog["sdk_show_less"]}</span></label></div>')


def sdk_examples(catalog: dict, data: dict) -> str:
    """One block per task, the examples of the languages as tabs: radio buttons and CSS, so that they work without
    script (the first tab shows; with the styles off, every one is listed)."""
    by_task: dict = {}
    for example in data.get("examples", []):
        task, variant = sdk_task(str(example.get("path", "")))
        if task:
            by_task.setdefault(task, []).append((example, variant))
    out = []
    for task, _ in SDK_TASKS:
        group = sorted(by_task.get(task, []), key=lambda e: (SDK_LANGS.index(e[0].get("language")) if e[0].get("language") in SDK_LANGS else 99,
                                                              str(e[0].get("path"))))
        if not group:
            continue
        inputs, panels = "", ""
        for n, (example, variant) in enumerate(group):
            lang = str(example.get("language"))
            label = SDK_NAMES.get(lang, lang) + (f" ({SDK_VARIANTS[variant]})" if variant in SDK_VARIANTS else "")
            ident = f"ex-{task}-{n}"
            path = html.escape(str(example.get("path", "")), quote=True)
            title = re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(str(example.get("title", ""))))
            inputs += (f'<input type="radio" name="ex-{task}" id="{ident}" data-lang="{html.escape(lang, quote=True)}"{" checked" if n == 0 else ""}>'
                       f'<label for="{ident}">{html.escape(label)}</label>')
            panels += (f'<div class="panel"><p class="note">{title} · <a href="{SDK_REPO}/blob/main/{path}">{path}</a></p>'
                       f'{sdk_code(catalog, ident, lang, str(example.get("source", "")))}</div>')
        out.append(f'<h3 id="ex-{task}-title">{catalog["sdk_task_" + task]}</h3><div class="tabs" role="radiogroup" aria-labelledby="ex-{task}-title">{inputs}<div class="panels">{panels}</div></div>')
    return "\n".join(out)


def sdk_versions(catalog: dict, data: dict) -> str:
    """The version of the SDK, the draft it follows and the C API it exposes, a row a release (the one in the
    source until there is a release: sdk.json has no list of past ones yet)."""
    sdk = data.get("sdk", {})
    capi = f'{sdk.get("c_api_version")} (ABI {sdk.get("c_abi_version")})' if sdk.get("c_api_version") else ""
    head = "".join(f'<th scope="col">{catalog[k]}</th>' for k in ("sdk_k_version", "sdk_k_draft", "sdk_k_capi", "sdk_k_release"))
    row = "".join(f"<td>{html.escape(str(v))}</td>" for v in (sdk.get("version", ""), sdk.get("spec_draft", ""), capi,
                                                              sdk.get("release") or catalog["sdk_none_yet"]))
    return (f'<div class="table versions" tabindex="0" role="region" aria-label="{html.escape(catalog["sdk_versions_title"], quote=True)}">'
            f'<table><caption class="sr">{html.escape(catalog["sdk_versions_title"])}</caption><thead><tr>{head}</tr></thead><tbody><tr>{row}</tr></tbody></table></div>')


def demo_cards(catalog: dict) -> str:
    """The demo library's three kinds of content, a card each, with the counts of demo_stats()."""
    st = demo_stats()

    def card(kind, icon, facts):
        rows = "".join(f"<div><dt>{catalog[k]}</dt><dd>{html.escape(str(v))}</dd></div>" for k, v in facts)
        return (f'<li class="card"><svg class="icon" viewBox="0 0 24 24" aria-hidden="true">{icon}</svg>'
                f'<h3>{catalog["demo_" + kind]}</h3><p class="count">{st[kind]["count"]}</p>'
                f'<p>{catalog["demo_" + kind + "_text"]}</p><dl class="facts">{rows}</dl></li>')
    return ('<ul class="cards cards-small stats">'
            + card("games", '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
                   [("demo_k_platforms", st["games"]["platforms"])])
            + card("homebrew", '<path d="M12 2.5 20.5 7v10L12 21.5 3.5 17V7z"/><path d="M3.5 7 12 11.5 20.5 7M12 11.5v10"/>',
                   [("demo_k_platforms", st["homebrew"]["platforms"]),
                    ("demo_k_signed", f'{st["homebrew"]["signed"]} / {st["homebrew"]["count"]}')])
            + card("cheats", '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2.2"/><circle cx="10" cy="17" r="2.2"/>',
                   [("demo_k_platforms", st["cheats"]["platforms"]), ("demo_k_cheats", st["cheats"]["codes"])])
            + "</ul>")


def default_crumbs(page: str, path: str, catalog: dict) -> list:
    if page == "spec" and path == "spec/":
        return [(catalog["nav_spec"], None)]
    if page == "demo" and path == "demo/":
        return [(catalog["footer_demo"], None)]
    if page == "start" and path == "start/":
        return [(catalog["footer_start"], None)]
    if page == "check" and path == "check/":
        return [(catalog["footer_check"], None)]
    if page == "examples" and path == "examples/":
        return [(catalog["footer_examples"], None)]
    if page == "translations" and path == "translations/":
        return [(catalog["footer_translations"], None)]
    if page == "sdk" and path == "sdk/":
        return [(catalog["nav_sdk"], None)]
    return []


def page_html(template: str, language: str, catalog: dict, path: str, page: str, spec: dict, versions: dict,
              body: str = "", extra: dict | None = None) -> str:
    depth = path.count("/") + (1 if language != ENGLISH else 0)
    root = "../" * depth
    extra = extra or {}
    hl = boreale.html_lang(language)
    values = dict(catalog)
    values.update({
        "lang": hl, "root": root, "home": folder(language), "site": SITE_URL, "page": page,
        "url": SITE_URL + folder(language) + path,
        "title": extra.get("title") or catalog[f"title_{page}"],
        "description": html.escape(extra.get("description") or catalog[f"description_{page}"], quote=True),
        "og_locale": OG_LOCALES[language],
        "first_visit": ' data-first-visit=""' if language == ENGLISH and path == "" else "",
        "indexing": indexing(language, path, extra.get("alternate", page in PAGES.values()), extra.get("noindex", False)),
        # The page chrome (boreale-site's chrome.css and chrome.js): the aurora behind the home page's header and
        # hero, a quieter sky elsewhere; the home's sections hold their own gutters, the other pages' main does.
        "skip": LANTERN.skip(catalog),
        "sky": LANTERN.sky(home=page == "home"),
        "header": page_header(language, catalog, root, extra.get("lang_path", path), page, versions),
        "main_class": "" if page == "home" else ' class="wrap"',
        "footer": page_footer(language, catalog, root),
        # The hero's line under the title, each of its parts kept whole ("SHA-256" never broken).
        "hero_sub_parts": "".join(f'<li>{part}</li>' for part in catalog["hero_sub"].split(" · ")),
        "audience": LANTERN.audience(root),
        "crumbs": crumbs_html(catalog, root, language, extra["crumbs"] if "crumbs" in extra else default_crumbs(page, path, catalog)),
        "hero": hero(page, catalog, root, language, spec, extra),
        "repo": REPO,
        "annex_d": spec["sections"].get("D", ""),
        "draft": DRAFT,
        # The specification's script: its contents, search and links (site/assets/spec.js).
        "spec_script": (f'<script src="{root}assets/spec.js" defer></script>' if page == "spec" else "")
                       + (f'<script src="{root}assets/figures.js" defer></script>' if page in ("spec", "start") else "")
        + (f'<script src="{root}assets/code.js" defer data-copy="{html.escape(catalog["ui_copy"], quote=True)}" data-copied="{html.escape(catalog["ui_copied"], quote=True)}" data-failed="{html.escape(catalog["ui_copy_failed"], quote=True)}"></script>' if page in ("spec", "start", "examples", "sdk") else "")
        + (f'<script src="{root}assets/check.js" defer></script>' if page == "check" else "")
        + (f'<script src="{root}assets/sdk.js" defer></script>' if page == "sdk" else "")
        + (f'<script src="{root}assets/rail.js" defer data-label="{html.escape(catalog["home_rail"], quote=True)}"></script>' if page == "home" else ""),
    })
    if page in ("home", "demo", "start", "check", "examples", "translations", "sdk") and not body:
        body = (SITE / f"{page}.html").read_text(encoding="utf-8")
        values["demo_url"] = SITE_URL + "demo/"
        values["diagram_overview"] = diagrams.render("overview", catalog)
        values["diagram_connect"] = diagrams.render("connect", catalog, None, None, stepper=True)
        values["demo_hash"] = DEMO_FILE
        # \x01…\x02 in an example mark what makes it differ from its twin (<mark>, after the escaping)
        values.update({f"ex_{k}": html.escape(v).replace("\x01", "<mark>").replace("\x02", "</mark>")
                       for k, v in example_blocks().items()})
        values["translations_table"] = translations_table(catalog, root, values["home"])
        values["check_options"] = "".join(
            f'<option value="{n}"{" selected" if n == "handshake" else ""}>{n}</option>' for n in schema_names())
        if page == "sdk":
            values.update(sdk_values(catalog, root, values["home"], spec["sections"]))
        if page == "demo":
            values["demo_qr"] = qr.svg(SITE_URL + "demo/", catalog["demo_qr_alt"])
            values["demo_cards"] = demo_cards(catalog)
    elif page == "spec" and not body:
        body = spec_body(spec, catalog, ui=hl, root=root, search=True, cards=True, drawn=True, meta=AIDS)
    values["body"] = fill(body, values)
    return LANTERN.links_out(fill(template, values))


def example_blocks() -> dict:
    """The worked examples' code (site/examples.html, /examples/), built from what the repository already checks:
    the signed request of vectors/signatures.json and its refused twin, the pairing documents of examples/v1/
    (their schemas check them) and the grant of vectors/grants.json. Nothing is written by hand, so that an
    example cannot drift from the text; tests/test_examples.py verifies the signatures and grants again."""
    def read(path):
        return json.loads((ROOT / path).read_text(encoding="utf-8"))
    sig = read("vectors/signatures.json")
    ok, refused = sig["accepted"][0], sig["refused"][0]
    url = urlparse(ok["uri"])
    refused_keys = set(refused["request"]["headers"])
    # the headers the refused twin lacks are marked: they are the whole difference between the two requests
    request = (f"{ok['method']} {url.path}{'?' + url.query if url.query else ''} HTTP/1.1\nHost: {url.netloc}\n"
               + "\n".join((f"{k}: {v}" if k in refused_keys else f"\x01{k}: {v}\x02") for k, v in ok["headers"].items()))
    key = sig["key"]
    pairing = read("examples/v1/pairing-request.json")
    code, token = read("examples/v1/pairing-code.json"), read("examples/v1/pairing-token.json")
    host = urlparse(code["verify"]).netloc
    dumps = lambda d: json.dumps(d, indent=2, ensure_ascii=False)   # noqa: E731
    grants = read("vectors/grants.json")
    return {
        "sign_request": request,
        "sign_base": ok["signature_base"],
        "sign_key": (f"private key (seed): {key['seed']}\npublic key:         {key['public_key']}\n"
                     f"keyid:              {key['keyid']}\nshort fingerprint:  {key['short_fingerprint']}"),
        "sign_refused_headers": "\n".join(f"{k}: {v}" for k, v in refused["request"]["headers"].items()),
        "sign_refused_code": f"\x01401 · {refused['code']}\x02",
        "pair_1": f"POST /api/lantern/v1/pairing HTTP/1.1\nHost: {host}\nContent-Type: application/json\n\n{dumps(pairing)}",
        "pair_2": f"HTTP/1.1 200 OK\nContent-Type: application/json\n\n{dumps(code)}",
        "pair_3": f"GET {code['poll']} HTTP/1.1\nHost: {host}\nSignature-Input: lantern=(\"@method\" \"@target-uri\");created=…;nonce=\"…\";keyid=\"…\";alg=\"ed25519\"\nSignature: lantern=:…:",
        "pair_4": f"HTTP/1.1 200 OK\nContent-Type: application/json\n\n{dumps(token)}",
        "grant_payload": grants["payload"],
        "grant": grants["grant"],
        "grant_key": f"public key (peers.key): {grants['key']['public_key']}",
    }


# What each language has of the specification (filled by main(): translation_rows()).
TRANSLATION_ROWS: list = []


def translation_rows(translations: dict, spec_text: str) -> list:
    """For each language of the site: (code, name, folder, state, draft): the state of its translation of the
    specification, "original" for English, "current" when its text translates this SPEC.md, "behind" when
    SPEC.md has changed since, "none" when there is none (translations/, TRANSLATIONS)."""
    current = hashlib.sha256(spec_text.encode("utf-8")).hexdigest()
    rows = []
    for code, folder_, name, _ in LANGUAGES:
        if code == ENGLISH:
            rows.append((code, name, folder_, "original", DRAFT))
        elif code in TRANSLATIONS:
            t, _ = translations[TRANSLATIONS[code]]
            m = STATUS.search(t["text"])
            rows.append((code, name, folder_, "current" if t["sha256"] == current else "behind", m.group(1) if m else ""))
        else:
            rows.append((code, name, folder_, "none", ""))
    return rows


def translations_table(catalog: dict, root: str, home: str) -> str:
    """The translations page's table, in the page's language: for each language, its site and its specification."""
    def spec_cell(state, draft):
        if state == "original":
            return html.escape(catalog["tr_original"])
        if state == "current":
            return html.escape(catalog["tr_spec_current"].replace("{v}", draft))
        if state == "behind":
            return html.escape(catalog["tr_spec_behind"].replace("{v}", draft))
        return html.escape(catalog["tr_spec_none"])
    rows = "".join(
        f'<tr><th scope="row"><a href="{root}{folder_}{"/" if folder_ else ""}" hreflang="{html.escape(code)}" lang="{html.escape(code)}">{html.escape(name)}</a></th>'
        f'<td>{html.escape(catalog["tr_original"] if state == "original" else catalog["tr_site"])}</td><td>{spec_cell(state, draft)}</td></tr>'
        for code, name, folder_, state, draft in TRANSLATION_ROWS)
    return (f'<div class="table"><table><thead><tr><th scope="col">{html.escape(catalog["tr_col_lang"])}</th>'
            f'<th scope="col">{html.escape(catalog["tr_col_site"])}</th><th scope="col">{html.escape(catalog["tr_col_spec"])}</th>'
            f'</tr></thead><tbody>{rows}</tbody></table></div>')


def schema_names() -> list:
    """The names of the schemas the site publishes (schemas/v1/<name>.json), which its checking page offers."""
    return sorted(p.stem for p in (ROOT / "schemas" / "v1").glob("*.json"))


def copy_schemas(out: Path) -> int:
    """Each schema of schemas/ at its $id's path (https://lantern.boreale.dev/schemas/v1/<name>.json is
    schemas/v1/<name>.json), byte for byte (SPEC.md § 3.2): no tracking, no tag, nothing added."""
    count = 0
    for source in sorted((ROOT / "schemas").rglob("*.json")):
        sid = json.loads(source.read_text(encoding="utf-8")).get("$id", "")
        path = urlparse(sid).path.lstrip("/")
        if urlparse(sid).hostname != "lantern.boreale.dev" or not path.startswith("schemas/"):
            sys.exit(f"build_site: {source.relative_to(ROOT)}'s $id is not an address of the site: {sid!r}")
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        count += 1
    return count


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = Path(sys.argv[1])
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copytree(SITE / "assets", out / "assets")
    boreale.copy_assets(out)
    schemas = copy_schemas(out)
    catalogs = boreale.catalogs(SITE / "i18n")
    # "{draft}" in a text is the current draft, so that no catalog keeps an older one.
    catalogs = {code: {k: v.replace("{draft}", DRAFT) if isinstance(v, str) else v for k, v in texts.items()}
                for code, texts in catalogs.items()}
    template = (SITE / "template.html").read_text(encoding="utf-8")
    spec = read_spec()
    AIDS.update(section_aids(SPEC.read_text(encoding="utf-8")))
    versions = boreale.latest_versions()
    urls = []
    written = 0

    def write(path: str, text: str, listed: bool = True) -> None:
        """A page; `listed`, in the sitemap (not an earlier draft, nor the trapped libraries)."""
        nonlocal written
        target = out / path / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        written += 1
        if listed:
            urls.append(SITE_URL + path)

    # The figures as files of their own, in every language: what a figure's buttons download.
    (out / "figures").mkdir()
    for code, _, _, hl in LANGUAGES:
        for name in diagrams.DIAGRAMS:
            (out / "figures" / f"{name}.{hl}.svg").write_text(diagrams.standalone(name, catalogs[code]), encoding="utf-8")

    # The demo library and its trapped variant (tools/make_demo.py), before its page.
    demo = make_demo.build(out / "demo")
    translations = {}
    for language, name in TRANSLATIONS.items():
        if name not in translations:
            t = read_translation(name)
            translations[name] = (t, read_spec(t["text"], anchors=spec["sections"], errors_needed=False))
    TRANSLATION_ROWS[:] = translation_rows(translations, SPEC.read_text(encoding="utf-8"))
    for language, _, _, _ in LANGUAGES:
        catalog = catalogs[language]
        for path, page in PAGES.items():
            if page == "demo" and demo is None:
                continue
            body, extra = "", {}
            if page == "spec" and language in TRANSLATIONS:
                t, translated = translations[TRANSLATIONS[language]]
                body = spec_body(translated, catalog, lang=t["language"], source=f"{REPO}/blob/main/site/translations/{t['name']}",
                                 label=html.escape(t["source"]), ui=boreale.html_lang(language), cards=True, drawn=True, meta=AIDS)
                if t["language"].split("-")[0] == "fr":
                    body = french_spaces(body)
                extra = {"translation": {"lang": t["language"], "banner": t["banner"], "english": t["english"]}}
            write(folder(language) + path, page_html(template, language, catalog, path, page, spec, versions, body, extra))
    en = catalogs[ENGLISH]
    # The drafts, each as it was published (DRAFTS), out of the sitemap and of search engines; and what changed.
    drafts = []
    if DRAFTS[-1][0] != DRAFT or any(commit is None for _, commit, _ in DRAFTS[:-1]):
        sys.exit(f"build_site: DRAFTS ends with draft {DRAFT}, and only the last one may be without a commit")
    for v, commit, pr in DRAFTS:
        # The draft not merged yet (commit None) is the working tree's SPEC.md.
        text = spec_at(commit) if commit else SPEC.read_text(encoding="utf-8")
        if not text.split("\n")[2].startswith(f"Draft {v},"):
            sys.exit(f"build_site: SPEC.md at {(commit or 'the working tree')[:7]} is not draft {v}")
        ref = commit or "main"
        d = read_spec(text, ref=ref, errors_needed=False)
        drafts.append((v, commit, pr, d))
        write(f"spec/{v}/", page_html(template, ENGLISH, en, f"spec/{v}/", "spec", d, versions, spec_body(
            d, en, source=f"{REPO}/blob/{ref}/SPEC.md",
            label=f"SPEC.md at {commit[:7]}, on GitHub" if commit else "SPEC.md on GitHub"), {
            "title": f"Draft {v} · Specification · Lantern", "eyebrow": f"Specification · draft {v}",
            "h1": f"The Lantern protocol, draft {v}",
            "lede": (f"SPEC.md as it was when draft {v} was merged (lantern#{pr}), kept as it was." if commit else
                     f"SPEC.md of draft {v}, the current draft, as it is now: it is kept as it was once merged."),
            "description": f"The Lantern protocol's draft {v}, as it was published; superseded by later drafts.",
            "noindex": True, "alternate": False, "lang_path": "spec/",
            "crumbs": [(en["nav_spec"], "spec/"), (f"Draft {v}", None)],
            "after": (draft_banner(v, pr) + "\n    " + status_chips(d, en) + "\n    "
                      + drafts_nav(en, "../../", ENGLISH, v))}), listed=False)
    (out / "spec" / "search.json").write_text(json.dumps(search_index(spec), ensure_ascii=False, separators=(",", ":")) + "\n",
                                              encoding="utf-8")
    write("spec/changes/", page_html(template, ENGLISH, en, "spec/changes/", "spec", spec, versions, changes_body(drafts), {
        "title": "What changed, draft by draft · Lantern", "eyebrow": "Specification · its drafts",
        "h1": "What changed, draft by draft",
        "lede": "Each draft of the specification, what it says it changed, and its sections against the one before.",
        "description": "The Lantern protocol's drafts, from 0.1 to the current one, and what each one changed.",
        "alternate": False, "lang_path": "spec/", "crumbs": [(en["nav_spec"], "spec/"), (en["spec_changes"], None)],
        "after": drafts_nav(en, "../../", ENGLISH, "changes")}))
    if demo is not None:
        write("demo/trapped/", page_html(template, ENGLISH, en, "demo/trapped/", "demo", spec, versions, trapped_body(), {
            "title": "Trapped libraries, for testing clients · Lantern", "eyebrow": "Demo · broken on purpose",
            "h1": "Trapped libraries", "lede": "Static libraries with one fault each, and what a client must do about it.",
            "description": "Lantern static libraries broken on purpose, for testing clients.",
            "noindex": True, "alternate": False, "lang_path": "demo/",
            "crumbs": [(en["footer_demo"], "demo/"), ("Trapped libraries", None)]}), listed=False)
    # The error types, in English: their addresses are the `type` of SPEC.md's section of errors.
    write("errors/", page_html(template, ENGLISH, en, "errors/", "errors", spec, versions, errors_body(spec, "../"), {
        "title": "Error types · Lantern", "eyebrow": "Errors · RFC 9457", "h1": "Error types",
        "lede": f"The <code>type</code> of each error a Lantern server returns, from the specification's §&nbsp;{spec['errors_section']}.",
        "description": "The error types of the Lantern protocol: each one's status, code and when a server returns it.",
        "lang_path": "spec/", "crumbs": [(en["footer_errors"], None)]}))
    pages = [("conformance/", "Conformance levels", "Conformance · SPEC.md § 17", "Who may say “Lantern compatible”, at which level, and how the suite decides.",
              "The conformance levels of the Lantern protocol, from Lantern Core to +deltas, Lantern Static, and how the suite decides.",
              conformance_body(spec, "../")),
             ("requirements/", "Requirements and their checks", "Traceability · SPEC.md § 3.5",
              "Each requirement of the specification, by its id, and the conformance suite's checks that cover it.",
              "Every MUST and SHOULD of the Lantern protocol, by id, and the conformance checks that cover it.",
              requirements_body(spec, "../")),
             ("implementations/", "Implementations", "Registry · SPEC.md § 17",
              "The servers and clients that pass the conformance suite, and the levels they reach.",
              "The registry of Lantern implementations and the conformance levels they reach.", registry_body("../")),
             ("releases/", "Releases", "Releases · SPEC.md § 3.6",
              "Each version of the text, its files, their sums and their attestations, and how to check them.",
              "How the Lantern protocol's versions are released, and how to verify a release's files with gh attestation verify.",
              releases_body("../")),
             ("badge/", "The “Lantern compatible” badge", "Badge · SPEC.md § 17",
              "For an implementation that passes the suite, at the level it reaches.",
              "The Lantern compatible badges, one per conformance level, and how to show them.", badge_body("../"))]
    for path, h1, eyebrow, lede, description, body in pages:
        write(path, page_html(template, ENGLISH, en, path, "conformance", spec, versions, body, {
            "title": f"{h1} · Lantern", "eyebrow": eyebrow, "h1": h1, "lede": lede, "description": description,
            "lang_path": "", "crumbs": ([(en["footer_conformance"], None)] if path == "conformance/" else
                                        [(en["footer_conformance"], "conformance/"), (h1, None)])}))
    (out / "assets" / "badges").mkdir(parents=True, exist_ok=True)
    for key, label in LEVELS:
        (out / "assets" / "badges" / badge_file(key)).write_text(badge_svg(key, label), encoding="utf-8")
    for error in spec["errors"]:
        write(f"errors/{error['name']}/", page_html(
            template, ENGLISH, en, f"errors/{error['name']}/", "errors", spec, versions, error_body(spec, error, "../../"), {
                "title": f"{error['name']} · Lantern errors", "eyebrow": f"Error type · {error['status']}",
                "h1": f"<code>{error['name']}</code>", "lede": inline(error["when"], {}) or f"HTTP {error['status']}.",
                "description": f"The Lantern protocol's {error['code']} error: HTTP {error['status']}.",
                "lang_path": "spec/", "crumbs": [(en["footer_errors"], "errors/"), (error["name"], None)]}))
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{html.escape(u)}</loc></url>\n" for u in urls) + "</urlset>\n", encoding="utf-8")
    (out / "feed.xml").write_text(atom_feed(changes_notes(SPEC.read_text(encoding="utf-8"))), encoding="utf-8")
    # The trapped libraries are for clients under test, not for search engines (their page says noindex too).
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nDisallow: /demo/trapped/\nSitemap: {SITE_URL}sitemap.xml\n",
                                    encoding="utf-8")
    host = urlparse(SITE_URL).hostname or ""
    if host and not host.endswith("github.io"):
        (out / "CNAME").write_text(host + "\n", encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"build_site: {written} pages ({len(urls)} in the sitemap), {len(DRAFTS)} drafts, {len(spec['errors'])} error "
          f"types, {schemas} schemas, {len(versions)} versions, {total / 1e6:.1f} MB in {out}")


if __name__ == "__main__":
    main()
