#!/usr/bin/env python3
"""Checks Lantern's built website (tools/build_site.py) and its sources.

    python3 tools/check_site.py <site-dir>

- what every one of Boréale's sites passes (library/boreale-site,
  boreale_site.check): no {{key}} left, links and #anchors that lead
  somewhere, links out by the rule "liens sortants anonymes" (no referrer;
  rel="noreferrer" to a third party, referrerpolicy="strict-origin" to
  boreale.dev, its subdomains and github.com/JigSawFr) and their UTM tags
  (utm_source=lantern, only to Boréale's other sites), nothing the
  Content-Security-Policy blocks, Umami's tracker, no e-mail address in a
  page, the data in pages read as JSON;
- the catalogs of site/i18n/ and boreale-site's: the same keys as
  en-US.json, none empty, the same {placeholders} and <em> as English's, no
  common text repeated here;
- no e-mail address and no mailto: link in any file of the site, its data
  included (contact goes through the issues);
- every error type of SPEC.md (its section "Errors") has its page (errors/<name>/), the
  address its `type` gives;
- every requirement id of SPEC.md (tools/requirements.py) is an anchor of the
  specification's page and has its entry on the traceability page
  (requirements/), and site/registry.json is of schema 1, each entry with
  its name, kind, url, draft and levels; the badges of every level are there;
- the drafts (spec/<draft>/) say noindex and stay out of the sitemap, which
  lists the current specification and spec/changes/;
- the demo library (demo/) is a static library whose files carry no tracking
  (no Umami, no UTM tag: only the pages count visits), and its trapped
  variant (demo/trapped/) stays out of the sitemap and of search engines;
- every schema of schemas/ is served at its `$id`
  (https://lantern.boreale.dev/schemas/v1/<name>.json is
  schemas/v1/<name>.json in the site), byte for byte, without tracking;
- each translation of the specification (site/translations/) names the
  English commit it translates: when SPEC.md has changed since, a warning
  (never a failure), and while it has not, the translation carries every
  requirement id of the English text, each an anchor of its page.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "library" / "boreale-site"))
import boreale_site as boreale  # noqa: E402
from boreale_site import check  # noqa: E402

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


def warn(message: str, file: str = "") -> None:
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::warning{' file=' + file if file else ''}::{message}")
    print(f"check_site: warning: {message}")


def git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True,
                              encoding="utf-8").stdout
    except (OSError, subprocess.CalledProcessError):
        return None


def check_translations(site: Path, ids: list) -> list:
    """Each translation's header against SPEC.md: stale is a warning; fresh, its ids and anchors must be all
    there."""
    errors = []
    english = (ROOT / "SPEC.md").read_bytes()
    for path in sorted((ROOT / "site" / "translations").glob("SPEC.*.md")):
        name = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        m = re.match(r"<!--\n(.*?)\n-->\n", text, re.DOTALL)
        fields = dict(re.findall(r"^([a-z0-9-]+): (.+)$", m.group(1), re.MULTILINE)) if m else {}
        if not {"language", "commit", "sha256"} <= set(fields):
            errors.append(f"{name}: no header with its language, commit and sha256")
            continue
        then = git("show", f"{fields['commit']}:SPEC.md")
        if then is not None and hashlib.sha256(then.encode()).hexdigest() != fields["sha256"]:
            errors.append(f"{name}: its sha256 is not SPEC.md's at {fields['commit'][:7]}")
        if hashlib.sha256(english).hexdigest() != fields["sha256"]:
            since = git("log", "--format=%h %s", f"{fields['commit']}..HEAD", "--", "SPEC.md")
            what = f": {len(since.splitlines())} commit(s) since, " + "; ".join(since.splitlines()[:3]) if since else ""
            warn(f"{name} translates SPEC.md at {fields['commit'][:7]}, and SPEC.md has changed since{what}. "
                 "Update the translation, then its header's commit and sha256.", name)
            continue
        found = re.findall(r"\[(L-(?:\d+(?:\.\d+)?|[A-Z](?:\.\d+)?)-\d+)\]", text)
        missing = [i for i in ids if i not in found]
        extra = sorted(set(found) - set(ids))
        if missing or extra:
            errors.append(f"{name}: requirement ids missing ({', '.join(missing[:5]) or 'none'}) or not English's "
                          f"({', '.join(extra[:5]) or 'none'})")
        folder = fields["language"].lower()
        page = site / folder / "spec" / "index.html"
        html = page.read_text(encoding="utf-8") if page.exists() else ""
        lacking = [i for i in ids if f'id="{i}"' not in html]
        if lacking:
            errors.append(f"{folder}/spec/index.html: no anchor for {len(lacking)} requirement(s), {', '.join(lacking[:5])}")
    return errors


def check_drafts_and_demo(site: Path) -> list:
    errors = []
    try:
        listed = [e.text or "" for e in ElementTree.parse(site / "sitemap.xml").getroot().iter()
                  if e.tag.endswith("loc")]
    except (OSError, ElementTree.ParseError):
        listed = []
    paths = [urlparse(u).path for u in listed]
    for p in paths:
        if re.match(r"^/spec/\d", p) or p.startswith("/demo/trapped/"):
            errors.append(f"sitemap.xml: lists {p}, which search engines are not to show")
    for p in ("/spec/", "/spec/changes/", "/demo/"):
        if p not in paths:
            errors.append(f"sitemap.xml: does not list {p}")
    drafts = sorted(site.glob("spec/[0-9]*/index.html"))
    if not drafts:
        errors.append("spec/: no draft (spec/<draft>/)")
    for page in [*drafts, site / "demo" / "trapped" / "index.html"]:
        text = page.read_text(encoding="utf-8") if page.exists() else ""
        if '<meta name="robots" content="noindex">' not in text:
            errors.append(f"{page.relative_to(site)}: not noindex")
    robots = (site / "robots.txt").read_text(encoding="utf-8") if (site / "robots.txt").exists() else ""
    if "Disallow: /demo/trapped/" not in robots:
        errors.append("robots.txt: does not keep crawlers out of /demo/trapped/")
    demo = site / "demo"
    try:
        hello = json.loads((demo / "lantern.json").read_text(encoding="utf-8"))
        if not isinstance(hello.get("static"), dict):
            errors.append("demo/lantern.json: not a static library's handshake")
    except (OSError, ValueError) as error:
        errors.append(f"demo/lantern.json: {error}")
    for path in sorted(demo.rglob("*")):
        if path.is_file() and path.suffix != ".html" and path.stat().st_size < (1 << 20):
            data = path.read_bytes()
            if b"umami" in data.lower() or b"utm_" in data:
                errors.append(f"{path.relative_to(site)}: tracking (Umami or a UTM tag) in a file of the demo library")
    return errors


def check_schemas(site: Path) -> list:
    """Each schema at its $id (SPEC.md § 3.2), as it is in schemas/: the address a validator fetches."""
    errors = []
    for source in sorted((ROOT / "schemas").rglob("*.json")):
        name = source.relative_to(ROOT).as_posix()
        try:
            sid = json.loads(source.read_text(encoding="utf-8")).get("$id", "")
        except ValueError as error:
            errors.append(f"{name}: not JSON ({error})")
            continue
        url = urlparse(sid)
        if url.scheme != "https" or url.hostname != "lantern.boreale.dev" or not url.path.startswith("/schemas/"):
            errors.append(f"{name}: its $id {sid!r} is not an address of the site's schemas/")
            continue
        built = site / url.path.lstrip("/")
        if not built.is_file():
            errors.append(f"{name}: its $id {sid} has no file in the site ({url.path})")
        elif built.read_bytes() != source.read_bytes():
            errors.append(f"{url.path}: not {name} as it is")
    for built in sorted((site / "schemas").rglob("*")) if (site / "schemas").exists() else []:
        if built.is_file():
            data = built.read_bytes()
            if b"umami" in data.lower() or b"utm_" in data:
                errors.append(f"{built.relative_to(site)}: tracking (Umami or a UTM tag) in a schema")
            if not (ROOT / built.relative_to(site)).is_file():
                errors.append(f"{built.relative_to(site)}: no such schema in the repository")
    return errors


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    site = Path(sys.argv[1])
    errors = boreale.check_catalogs(ROOT / "site" / "i18n")
    found, pages = check.pages(site, boreale.Site("lantern", os.environ.get("SITE_URL")))
    errors += found

    try:
        ElementTree.parse(site / "sitemap.xml")
    except (OSError, ElementTree.ParseError) as error:
        errors.append(f"sitemap.xml: {error}")
    spec = (ROOT / "SPEC.md").read_text(encoding="utf-8")
    for name in sorted(set(re.findall(r"https://lantern\.boreale\.dev/errors/([a-z-]+)", spec))):
        if not (site / "errors" / name / "index.html").exists():
            errors.append(f"SPEC.md: its error type {name} has no page (errors/{name}/)")
    sys.path.insert(0, str(ROOT / "tools"))
    import requirements
    ids = [r["id"] for r in requirements.requirements()[0]]
    for page in ("spec/index.html", "requirements/index.html"):
        target = site / page
        text = target.read_text(encoding="utf-8") if target.exists() else ""
        missing = [i for i in ids if f'id="{i}"' not in text]
        if missing:
            errors.append(f"{page}: no anchor for {len(missing)} requirement(s), {', '.join(missing[:5])}")
    registry = json.loads((ROOT / "site" / "registry.json").read_text(encoding="utf-8"))
    if registry.get("schema") != 1:
        errors.append("site/registry.json: not of schema 1")
    for entry in registry.get("implementations", []):
        lacking = [k for k in ("name", "kind", "url", "draft", "levels") if not entry.get(k)]
        if lacking:
            errors.append(f"site/registry.json: {entry.get('name', '?')} lacks {', '.join(lacking)}")
        if "core" not in entry.get("levels", []):
            errors.append(f"site/registry.json: {entry.get('name', '?')} without Lantern Core, which every level needs")
    errors += check_translations(site, ids)
    errors += check_drafts_and_demo(site)
    errors += check_schemas(site)
    for level in ("core", "titles", "homebrew", "saves", "cheats", "requests", "admin", "events", "peers", "sync",
                  "encrypted_saves", "deltas", "static"):
        if not list((site / "assets" / "badges").glob(f"lantern-*-{level}.svg")):
            errors.append(f"assets/badges: no badge for {level}")
    for path in sorted(site.rglob("*")):
        if path.is_file() and path.suffix in (".html", ".xml", ".txt", ".js", ".css", ".json"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if "mailto:" in text or EMAIL.search(text):
                errors.append(f"{path.relative_to(site)}: an e-mail address (contact goes through the issues)")

    for e in errors:
        print(f"check_site: {e}")
    if errors:
        sys.exit(1)
    print(f"check_site: {pages} pages, {len(boreale.CODES)} catalogs, nothing wrong")


if __name__ == "__main__":
    main()
