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
written into assets/badges/ by badge_svg()).

SITE_URL is the site's address (https://lantern.boreale.dev/ by default);
the links inside the site are relative, so it works at another one too.
SITE_OFFLINE=1 builds without reading boreale.dev's versions.json. Python's
standard library only.
"""
import html
import json
import os
import re
import shutil
import sys
import urllib.request
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "conformance"))
import requirements as spec_requirements  # noqa: E402  (tools/requirements.py)

SITE = ROOT / "site"
SPEC = ROOT / "SPEC.md"
REPO = "https://github.com/JigSawFr/lantern"
SITE_URL = os.environ.get("SITE_URL", "https://lantern.boreale.dev/").rstrip("/") + "/"
# The audience, counted by Umami Cloud (site/README.md): its tracker, served from
# assets/, sends each page seen to gateway.umami.is, without cookie, and only from
# the site's own address (not a preview or a local copy). Its site in Umami is
# Boréale's, shared by its projects' sites: Umami's Hostname filter tells them apart.
UMAMI_WEBSITE = "6410ffdd-ae2e-4ddb-8e18-0a77e9fa374e"
UMAMI_DOMAIN = urlparse(SITE_URL).hostname
# Boréale's sites' languages: the catalog's code, the folder ('' for the
# root), the name in its own words, the html lang.
LANGUAGES = [
    ("en", "", "English", "en"),
    ("fr", "fr", "Français", "fr"),
    ("fr-CA", "fr-ca", "Français (Canada)", "fr-CA"),
    ("de", "de", "Deutsch", "de"),
    ("es", "es", "Español", "es"),
    ("es-419", "es-419", "Español (Latinoamérica)", "es-419"),
    ("it", "it", "Italiano", "it"),
    ("nl", "nl", "Nederlands", "nl"),
    ("pt", "pt", "Português", "pt-PT"),
    ("pt-BR", "pt-br", "Português (Brasil)", "pt-BR"),
    ("ru", "ru", "Русский", "ru"),
    ("ja", "ja", "日本語", "ja"),
    ("ko", "ko", "한국어", "ko"),
    ("zh-Hans", "zh-hans", "简体中文", "zh-Hans"),
    ("zh-Hant", "zh-hant", "繁體中文", "zh-Hant"),
]
FLAGS = {"en": "US", "fr": "FR", "fr-CA": "CA", "de": "DE", "es": "ES", "es-419": "MX", "it": "IT", "nl": "NL",
         "pt": "PT", "pt-BR": "BR", "ru": "RU", "ja": "JP", "ko": "KR", "zh-Hans": "CN", "zh-Hant": "TW"}
OG_LOCALES = {"en": "en_US", "fr": "fr_FR", "fr-CA": "fr_CA", "de": "de_DE", "es": "es_ES", "es-419": "es_LA",
              "it": "it_IT", "nl": "nl_NL", "pt": "pt_PT", "pt-BR": "pt_BR", "ru": "ru_RU", "ja": "ja_JP",
              "ko": "ko_KR", "zh-Hans": "zh_CN", "zh-Hant": "zh_TW"}
# The pages in every language, by their path under each language's folder.
PAGES = {"": "home", "spec/": "spec"}

# Boréale's sites, in the header's menu (switcher()): boreale.dev's
# reference (boreale/tools/build_site.py), then the open data and protocols,
# Atlas and this one.
SITES = [(None, [("boreale", "Boréale", "https://boreale.dev/")]),
         ("sites_homebrew", [("playguard", "PlayGuard", "https://guard.boreale.dev/"),
                             ("playshelf", "PlayShelf", "https://shelf.boreale.dev/")]),
         ("sites_libraries", [("aurore", "Aurore", "https://aurore.boreale.dev/")]),
         ("sites_open", [("atlas", "Atlas", "https://atlas.boreale.dev/"),
                         ("lantern", "Lantern", "https://lantern.boreale.dev/")])]
HERE = "lantern"

# Where a visit to another of Boréale's sites came from, for Umami (workbench's
# "Mesure d'audience"): a link from this site to another *.boreale.dev site
# carries utm_source=lantern and a utm_medium telling where on the page it
# is: "nav" (the header, its sites menu), "footer", or "link" (the page's
# text). A link to this site itself carries none.
UTM_SOURCE = "lantern"

KEY = re.compile(r"\{\{([a-z0-9_]+)\}\}")
REQ = re.compile(r"\[(L-(?:\d+(?:\.\d+)?|[A-Z](?:\.\d+)?)-\d+)\]")
DRAFT = "0.5"   # the draft the badges name (SPEC.md § 17)
LEVELS = [("core", "Core"), ("titles", "+titles"), ("homebrew", "+homebrew"), ("saves", "+saves"),
          ("cheats", "+cheats"), ("requests", "+requests"), ("admin", "+admin"), ("events", "+events"),
          ("peers", "+peers"), ("sync", "+sync"), ("encrypted_saves", "+encrypted_saves"), ("static", "Static")]
# SPEC.md's section of errors, whatever its number: "## 12. Errors".
ERRORS_HEADING = re.compile(r"## (\d+)\. Errors$")


def folder(language: str) -> str:
    return next(f for c, f, _, _ in LANGUAGES if c == language) + ("/" if language != "en" else "")


def fill(text: str, values: dict) -> str:
    def one(match):
        key = match.group(1)
        if key not in values:
            sys.exit(f"build_site: no text for {{{{{key}}}}}")
        return values[key]
    return KEY.sub(one, KEY.sub(one, text))


def own(url: str) -> bool:
    """A link to Boréale's sites or to JigSawFr's GitHub: it keeps the origin."""
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if host == "boreale.dev" or host.endswith(".boreale.dev"):
        return True
    return host == "github.com" and u.path.lower().startswith("/jigsawfr/")


def utm(url: str, medium: str) -> str:
    """`url` (as written in the page's HTML) tagged for its medium, or as it is
    when it leads out of Boréale's sites or to this site itself."""
    u = urlsplit(html.unescape(url))
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not (host == "boreale.dev" or host.endswith(".boreale.dev")):
        return url
    query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if not k.startswith("utm_")]
    if host != (urlsplit(SITE_URL).hostname or ""):
        query += [("utm_source", UTM_SOURCE), ("utm_medium", medium)]
    tagged = urlunsplit(u._replace(query=urlencode(query)))
    return url if tagged == html.unescape(url) else html.escape(tagged, quote=True)


LINK = re.compile(r'<a\s[^>]*href="(https?://[^"]+)"[^>]*>')


def links_out(text: str) -> str:
    """Every link to another site, as workbench's "Liens sortants anonymes"
    wants it: to Boréale's sites or JigSawFr's GitHub, referrerpolicy=
    "strict-origin" (and UTM tags to the other sites); to anyone else,
    rel="noreferrer", so they never learn the visit came from here."""
    main, footer = text.find("<main"), text.find("<footer")

    def one(m):
        at = m.start()
        medium = "footer" if 0 <= footer <= at else "nav" if main < 0 or at < main else "link"
        url = utm(m.group(1), medium)
        tag = m.group(0).replace(f'href="{m.group(1)}"', f'href="{url}"', 1)
        if "rel=" in tag or "referrerpolicy=" in tag:
            return tag
        extra = ' referrerpolicy="strict-origin"' if own(html.unescape(url)) else ' rel="noreferrer"'
        return tag[:-1] + extra + ">"
    return LINK.sub(one, text)


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


def inline(text: str, sections: dict, refs: bool = True) -> str:
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
            href = f"{REPO}/{'tree' if href.endswith('/') else 'blob'}/main/{href}"
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
        text = re.sub(r"Annex ([A-Z](?:\.\d+)?)\b", annex, text)
    return re.sub(r"\x00(\d+)\x00", lambda m: codes[int(m.group(1))], text)


def table(rows: list, sections: dict, label: str) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], cells[2:]
    out = [f'<div class="table" tabindex="0" role="region" aria-label="{html.escape(label)}"><table>',
           "<thead><tr>" + "".join(f'<th scope="col">{inline(c, sections)}</th>' for c in head) + "</tr></thead>",
           "<tbody>"]
    out += ["<tr>" + "".join(f"<td>{inline(c, sections)}</td>" for c in r) + "</tr>" for r in body]
    return "\n".join(out + ["</tbody></table></div>"])


def blocks(lines: list, sections: dict, tight: bool = False) -> str:
    """Markdown `lines` (their indentation already taken off) as HTML."""
    out, i, heading = [], 0, ""
    para = []

    def flush():
        if para:
            text = inline(" ".join(s.strip() for s in para), sections)
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
            heading = plain(text)
            out.append(f'<h{level} id="{slug(text)}"><a class="anchor" href="#{slug(text)}">'
                       f'{inline(text, sections, refs=False)}</a></h{level}>')
            i += 1
        elif line.startswith("|"):
            flush()
            j = i
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            out.append(table(lines[i:j], sections, heading))
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
            out.append(f"<{tag}>" + "".join(f"<li>{blocks(item, sections, tight=True)}</li>" for item in items)
                       + f"</{tag}>")
        else:
            para.append(line)
            i += 1
    flush()
    return "\n".join(out)


def read_spec() -> dict:
    """SPEC.md: its title, its first lines (status, licence), its body, its
    table of contents, and its section of errors' table (ERRORS_HEADING).
    Numbered headings ("## 4.", "### 4.2") and the annexes' ("## Annex A —",
    "### A.1") are the targets of "§ 4.2", "Annex A" and "Annex A.1"."""
    lines = SPEC.read_text(encoding="utf-8").split("\n")
    title = lines[0].lstrip("# ").strip()
    rest = lines[1:]
    first = next(i for i, line in enumerate(rest) if line.startswith("## "))
    sections, toc = {}, []
    for line in rest:
        if m := re.match(r"(#{2,3}) ((\d+(?:\.\d+)?)\.? .*|Annex ([A-Z]) .*|([A-Z]\.\d+) .*|.*)", line):
            text = m.group(2)
            number = m.group(3) or m.group(4) or m.group(5)
            if number:
                sections[number] = slug(text)
            if len(m.group(1)) == 2:
                toc.append((slug(text), plain(text), []))
            elif toc:
                toc[-1][2].append((slug(text), plain(text)))
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
    if not errors:
        sys.exit("build_site: SPEC.md has no section of errors (## <n>. Errors) with its table")
    return {"title": title, "intro": blocks(rest[:first], sections), "body": blocks(rest[first:], sections),
            "toc": toc, "sections": sections, "errors": errors, "errors_section": errors_number}


def toc_html(spec: dict, label: str) -> str:
    items = []
    for anchor, text, subs in spec["toc"]:
        inner = ("<ol>" + "".join(f'<li><a href="#{a}">{html.escape(t)}</a></li>' for a, t in subs) + "</ol>") if subs else ""
        items.append(f'<li><a href="#{anchor}">{html.escape(text)}</a>{inner}</li>')
    return f'<nav class="toc" aria-label="{label}"><p class="toc-title">{label}</p><ol>' + "".join(items) + "</ol></nav>"


# ---- The page around them.

def flag(language: str) -> str:
    emoji = "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in FLAGS[language])
    return f'<span class="flag" aria-hidden="true">{emoji}</span>'


def languages(language: str, catalog: dict, root: str, path: str) -> str:
    """The header's languages: a button with the page's, and their menu (a
    popover), this page in each. Choosing one keeps it (assets/lang.js)."""
    name = next(n for c, _, n, _ in LANGUAGES if c == language)
    current = ' aria-current="true"'
    options = "\n".join(
        f'        <li><a href="{root}{folder(c)}{path}" data-lang="{d or c}" lang="{hl}" hreflang="{hl}"'
        f'{current if c == language else ""}>{flag(c)}{html.escape(n)}</a></li>'
        for c, d, n, hl in LANGUAGES)
    label = catalog["language"]
    return (f'<div class="settings">\n'
            f'      <button class="lang-button" type="button" popovertarget="languages" aria-label="{label} · {html.escape(name)}">'
            f'{flag(language)}<span class="lang-name">{html.escape(name)}</span>'
            f'<span class="lang-code">{language.split("-")[0].upper()}</span>'
            f'<svg class="chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></button>\n'
            f'      <ul id="languages" class="langs" popover aria-label="{label}">\n{options}\n      </ul>\n    </div>')


# versions.json's schema this build reads ({"schema": 1, "projects": {...}});
# the flat {project: "vX"} of before it had one is read too.
VERSIONS_SCHEMA = 1


def versions_of(data):
    """The projects' versions in versions.json's `data`, as {project: "vX"}:
    the flat shape of before, or {"schema": 1, "projects": {...}}. Another
    schema or shape is none (the menu shows no versions), never an error."""
    if not isinstance(data, dict):
        return {}
    if "schema" in data:
        projects = data.get("projects")
        if type(data["schema"]) is not int or data["schema"] != VERSIONS_SCHEMA or not isinstance(projects, dict):
            return {}
        data = projects
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}


def boreale_versions() -> dict:
    """The projects' latest releases as boreale.dev publishes them
    (versions.json, versions_of()), for the menu; none when it cannot be read
    (offline, SITE_OFFLINE=1), and the menu shows no versions."""
    if os.environ.get("SITE_OFFLINE"):
        return {}
    try:
        with urllib.request.urlopen("https://boreale.dev/versions.json", timeout=10) as r:
            return versions_of(json.load(r))
    except (OSError, ValueError):
        return {}


def switcher(language: str, catalog: dict, root: str, versions: dict) -> str:
    """The header's name, a button that opens the menu of Boréale's sites
    (site.css's and site.js's "site switcher" blocks, boreale.dev's), this
    one marked and leading home, each with its latest release. A popover:
    the browser closes it on Esc or a click elsewhere."""
    label = catalog["sites_label"]
    groups = []
    for title, sites in SITES:
        items = []
        for key, name, url in sites:
            href = f"{root}{folder(language)}" if key == HERE else url + folder(language)
            soon = f'<em class="soon">{catalog["sites_soon"]}</em>' if key == "playshelf" else ""
            version = f' <span class="sites-version">{html.escape(versions[key])}</span>' if key in versions else ""
            current = ' aria-current="true"' if key == HERE else ""
            items.append(f'<li><a href="{href}"{current}>'
                         f'<img src="{root}assets/marks/{key}.svg" alt="" width="36" height="36">'
                         f'<span><strong>{name}{version}</strong><small>{catalog[f"sites_{key}"]}</small></span>{soon}</a></li>')
        heading = f'<p class="sites-title">{catalog[title]}</p>' if title else ""
        groups.append(f'        {heading}<ul>\n          ' + "\n          ".join(items) + '\n        </ul>')
    return (f'<div class="switcher">\n'
            f'      <button class="brand switch" type="button" popovertarget="sites" aria-label="Lantern · {label}">'
            f'<img src="{root}assets/mark.svg" alt="" width="34" height="34">Lantern'
            f'<svg class="chevron" viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg></button>\n'
            f'      <div id="sites" class="sites" popover aria-label="{label}">\n'
            + "\n".join(groups) + '\n      </div>\n    </div>')


def indexing(language: str, path: str, alternate: bool) -> str:
    """The canonical address and, for a page in every language, the others'."""
    lines = [f'<link rel="canonical" href="{SITE_URL}{folder(language)}{path}">']
    if alternate:
        lines += [f'<link rel="alternate" hreflang="{hl}" href="{SITE_URL}{folder(c)}{path}">' for c, _, _, hl in LANGUAGES]
        lines.append(f'<link rel="alternate" hreflang="x-default" href="{SITE_URL}{path}">')
    return "\n".join(lines)


def hero(page: str, catalog: dict, root: str, language: str, spec: dict, extra: dict) -> str:
    if page == "home":
        return (f'<div class="wrap hero">\n    <span class="eyebrow">{catalog["hero_eyebrow"]}</span>\n'
                f'    <h1>{catalog["hero_title"]}</h1>\n    <p class="lede">{catalog["hero_lede"]}</p>\n'
                f'    <div class="actions"><a class="button primary" href="{root}{folder(language)}spec/">{catalog["cta_spec"]}</a>'
                f'<a class="button ghost" href="{REPO}">{catalog["cta_github"]}</a></div>\n  </div>')
    if page == "spec":
        note = f'\n    <p class="note-en">{catalog["spec_english"]}</p>' if language != "en" else ""
        return (f'<div class="wrap hero small">\n    <span class="eyebrow">{catalog["spec_eyebrow"]}</span>\n'
                f'    <h1>{catalog["spec_title"]}</h1>\n    <p class="lede">{catalog["spec_lede"]}</p>{note}\n  </div>')
    return (f'<div class="wrap hero small">\n    <span class="eyebrow">{extra["eyebrow"]}</span>\n'
            f'    <h1>{extra["h1"]}</h1>\n    <p class="lede">{extra["lede"]}</p>\n  </div>')


def spec_body(spec: dict, catalog: dict) -> str:
    return (f'<div class="spec-layout">\n{toc_html(spec, catalog["spec_toc"])}\n'
            f'<article class="prose" lang="en">\n<h2 class="spec-name">{html.escape(spec["title"])}</h2>\n'
            f'{spec["intro"]}\n{spec["body"]}\n'
            f'<p class="source"><a href="{REPO}/blob/main/SPEC.md">{catalog["spec_source"]}</a></p>\n'
            f'</article>\n</div>')


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
    return table(rows, spec["sections"], "Conformance levels").replace('href="#', f'href="{root}spec/#')


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
        groups[-1][2].append(
            f'<li id="{r["id"]}"><p class="req-head"><a class="req" href="{root}spec/#{r["id"]}">{r["id"]}</a>'
            f'<span class="state">{r["level"]}</span><span class="seen {kind}">{seen}</span></p>'
            f'<p>{to_spec(inline(r["text"], spec["sections"]), root)}</p></li>')
    body = "\n".join(
        f'<h2 id="s-{html.escape(section)}">{inline(heading, spec["sections"], refs=False)}</h2>\n<ul class="reqs">\n'
        + "\n".join(items) + "\n</ul>" for heading, section, items in groups)
    total = len(found)
    return (f'<section class="prose wide" lang="en">\n<p>Every MUST and SHOULD of the specification has an id '
            f'(<a href="{root}spec/#35-changes-and-proposals">§&nbsp;3.5</a>). Here is each one, and what sees it: the '
            f'checks of the <a href="{REPO}/blob/main/conformance/run.py">conformance suite</a> that cover it, or why the '
            f'suite cannot see it, a client\'s rule or one inside a server.</p>\n'
            f'<dl class="facts"><div><dt>In all</dt><dd>{total} requirements</dd></div>'
            f'<div><dt>Suite</dt><dd>{counts["suite"]} checked by the suite</dd></div>'
            f'<div><dt>Clients</dt><dd>{counts["client"]} a client keeps</dd></div>'
            f'<div><dt>Inside</dt><dd>{counts["unseen"]} inside a server</dd></div></dl>\n{body}\n</section>')


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


def page_html(template: str, language: str, catalog: dict, path: str, page: str, spec: dict, versions: dict,
              body: str = "", extra: dict | None = None) -> str:
    depth = path.count("/") + (1 if language != "en" else 0)
    root = "../" * depth
    extra = extra or {}
    hl = next(h for c, _, _, h in LANGUAGES if c == language)
    values = dict(catalog)
    values.update({
        "lang": hl, "root": root, "home": folder(language), "site": SITE_URL, "page": page,
        "url": SITE_URL + folder(language) + path,
        "title": extra.get("title") or catalog[f"title_{page}"],
        "description": html.escape(extra.get("description") or catalog[f"description_{page}"], quote=True),
        "og_locale": OG_LOCALES[language],
        "first_visit": ' data-first-visit=""' if language == "en" and path == "" else "",
        "indexing": indexing(language, path, page in PAGES.values()),
        "languages": languages(language, catalog, root, extra.get("lang_path", path)),
        "switcher": switcher(language, catalog, root, versions),
        "current_project": ' aria-current="page"' if page == "home" else "",
        "current_spec": ' aria-current="page"' if page == "spec" else "",
        "audience": f'<script src="{root}assets/umami.js" defer data-website-id="{UMAMI_WEBSITE}" '
                    f'data-domains="{UMAMI_DOMAIN}"></script>',
        "hero": hero(page, catalog, root, language, spec, extra),
        "repo": REPO,
    })
    if page == "home":
        body = (SITE / "home.html").read_text(encoding="utf-8")
    elif page == "spec":
        body = spec_body(spec, catalog)
    values["body"] = fill(body, values)
    return links_out(fill(template, values))


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = Path(sys.argv[1])
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copytree(SITE / "assets", out / "assets")
    catalogs = {c: json.loads((SITE / "i18n" / f"{c}.json").read_text(encoding="utf-8")) for c, _, _, _ in LANGUAGES}
    template = (SITE / "template.html").read_text(encoding="utf-8")
    spec = read_spec()
    versions = boreale_versions()
    urls = []

    def write(path: str, text: str) -> None:
        target = out / path / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        urls.append(SITE_URL + path)

    for language, _, _, _ in LANGUAGES:
        for path, page in PAGES.items():
            write(folder(language) + path, page_html(template, language, catalogs[language], path, page, spec, versions))
    # The error types, in English: their addresses are the `type` of SPEC.md's section of errors.
    en = catalogs["en"]
    write("errors/", page_html(template, "en", en, "errors/", "errors", spec, versions, errors_body(spec, "../"), {
        "title": "Error types · Lantern", "eyebrow": "Errors · RFC 9457", "h1": "Error types",
        "lede": f"The <code>type</code> of each error a Lantern server returns, from the specification's §&nbsp;{spec['errors_section']}.",
        "description": "The error types of the Lantern protocol: each one's status, code and when a server returns it.",
        "lang_path": "spec/"}))
    pages = [("conformance/", "Conformance levels", "Conformance · SPEC.md § 17", "Who may say “Lantern compatible”, at which level, and how the suite decides.",
              "The conformance levels of the Lantern protocol, from Lantern Core to +encrypted_saves, Lantern Static, and how the suite decides.",
              conformance_body(spec, "../")),
             ("requirements/", "Requirements and their checks", "Traceability · SPEC.md § 3.5",
              "Each requirement of the specification, by its id, and the conformance suite's checks that cover it.",
              "Every MUST and SHOULD of the Lantern protocol, by id, and the conformance checks that cover it.",
              requirements_body(spec, "../")),
             ("implementations/", "Implementations", "Registry · SPEC.md § 17",
              "The servers and clients that pass the conformance suite, and the levels they reach.",
              "The registry of Lantern implementations and the conformance levels they reach.", registry_body("../")),
             ("badge/", "The “Lantern compatible” badge", "Badge · SPEC.md § 17",
              "For an implementation that passes the suite, at the level it reaches.",
              "The Lantern compatible badges, one per conformance level, and how to show them.", badge_body("../"))]
    for path, h1, eyebrow, lede, description, body in pages:
        write(path, page_html(template, "en", en, path, "conformance", spec, versions, body, {
            "title": f"{h1} · Lantern", "eyebrow": eyebrow, "h1": h1, "lede": lede, "description": description,
            "lang_path": ""}))
    (out / "assets" / "badges").mkdir(parents=True, exist_ok=True)
    for key, label in LEVELS:
        (out / "assets" / "badges" / badge_file(key)).write_text(badge_svg(key, label), encoding="utf-8")
    for error in spec["errors"]:
        write(f"errors/{error['name']}/", page_html(
            template, "en", en, f"errors/{error['name']}/", "errors", spec, versions, error_body(spec, error, "../../"), {
                "title": f"{error['name']} · Lantern errors", "eyebrow": f"Error type · {error['status']}",
                "h1": f"<code>{error['name']}</code>", "lede": inline(error["when"], {}) or f"HTTP {error['status']}.",
                "description": f"The Lantern protocol's {error['code']} error: HTTP {error['status']}.",
                "lang_path": "spec/"}))
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(f"  <url><loc>{html.escape(u)}</loc></url>\n" for u in urls) + "</urlset>\n", encoding="utf-8")
    (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}sitemap.xml\n", encoding="utf-8")
    host = urlparse(SITE_URL).hostname or ""
    if host and not host.endswith("github.io"):
        (out / "CNAME").write_text(host + "\n", encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"build_site: {len(urls)} pages, {len(spec['errors'])} error types, "
          f"{len(versions)} versions, {total / 1e6:.1f} MB in {out}")


if __name__ == "__main__":
    main()
