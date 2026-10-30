#!/usr/bin/env python3
"""SPEC.md's requirements and their ids (SPEC.md § 3.5), read and checked.

    python3 tools/requirements.py            # checks SPEC.md, prints a summary
    python3 tools/requirements.py --json     # every requirement, as JSON

Every MUST, MUST NOT, REQUIRED, SHOULD and SHOULD NOT of SPEC.md has an id
written next to it in brackets, `[L-<section>-<n>]`: `L-5.2-3` is the third
requirement given an id in § 5.2, `L-A.1-1` the first of Annex A.1. This
reads them: each id with its section, its level (MUST or SHOULD) and its
words (the part of its paragraph, list item or table row that leads to it).
It checks that:

- every paragraph, list item and table row holds as many ids as keywords
  (a sentence that ends in "MUST:" before a list gives its keyword to the
  list's items, each with its own id);
- an id is given once, and in its own section;
- no keyword and no id appear in the non-normative Annex B (the text's
  conventions, before § 1, and its "Changes" speak of them freely).

The site's traceability page (tools/build_site.py) and the tests
(tests/test_v04.py) read requirements() too. Standard library only.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "SPEC.md"
ID = re.compile(r"\[(L-(?:\d+(?:\.\d+)?|[A-Z](?:\.\d+)?)-\d+)\]")
KEYWORD = re.compile(r"\b(MUST NOT|MUST|REQUIRED|SHOULD NOT|SHOULD)\b")
HEADING = re.compile(r"^(#{2,4}) (?:(\d+(?:\.\d+)?)\.? |Annex ([A-Z]) |([A-Z]\.\d+) )?(.*)$")


def blocks(lines):
    """(section, heading, text, kind, line number) of each paragraph, list item and table row."""
    section, heading, out = None, "", []
    buf, kind, start, fenced = [], None, 0, False

    def flush():
        nonlocal buf, kind
        if buf:
            out.append((section, heading, " ".join(x.strip() for x in buf), kind, start))
        buf, kind = [], None

    for n, line in enumerate(lines, 1):
        if line.startswith("```") or line.lstrip().startswith("```"):
            flush()
            fenced = not fenced
            continue
        if fenced:
            continue
        m = HEADING.match(line)
        if m:
            flush()
            number = m.group(2) or m.group(3) or m.group(4)
            if len(m.group(1)) == 2:
                section = number if number else ("changes" if m.group(5).startswith("Changes") else None)
            elif number:
                section = number
            heading = line.lstrip("# ").strip()
            continue
        if not line.strip():
            flush()
            continue
        if line.startswith("|"):
            flush()
            if not re.match(r"^\|[-| ]+\|$", line):
                out.append((section, heading, line.strip(), "row", n))
            continue
        item = re.match(r"^(\s*)(- |\d+\. )", line)
        if item:
            flush()
            buf, kind, start = [line[item.end():]], "item", n
            continue
        if not buf:
            kind, start = "para", n
        buf.append(line)
    flush()
    return out


def requirements(text=None):
    """Every requirement of SPEC.md: [{"id", "section", "level", "text", "line"}], in the text's order;
    and the problems found (a list of strings, empty when the text is sound)."""
    lines = (text if text is not None else SPEC.read_text(encoding="utf-8")).split("\n")
    found, problems, seen = [], [], set()
    lead = None         # the keyword a "MUST:" lead-in gives the list items that follow it
    for section, heading, body, kind, line in blocks(lines):
        ids = ID.findall(body)
        keywords = KEYWORD.findall(ID.sub("", body))
        if kind != "item":
            lead = None
        if section in (None, "changes"):
            continue    # the conventions and the history speak of the keywords and the ids
        if section == "B" or section.startswith("B."):
            if ids or keywords:
                problems.append(f"SPEC.md:{line}: a requirement in Annex B, which is not normative")
            continue
        if keywords and not ids and re.search(r"\b(MUST|SHOULD)(?: NOT)?:\s*$", body):
            lead = "SHOULD" if keywords[-1].startswith("SHOULD") else "MUST"
            continue
        if len(ids) < len(keywords):
            problems.append(f"SPEC.md:{line}: {len(keywords)} keyword(s), {len(ids)} id(s): {body[:90]}")
        if ids and not keywords and not (kind == "item" and lead):
            problems.append(f"SPEC.md:{line}: an id without a keyword: {body[:90]}")
        rest = body
        for rid in ids:
            before, _, rest = rest.partition(f"[{rid}]")
            if rid in seen:
                problems.append(f"SPEC.md:{line}: {rid} given twice")
            seen.add(rid)
            own = rid.split("-")[1]
            if own != section:
                problems.append(f"SPEC.md:{line}: {rid} is in § {section}, not § {own}")
            words = ID.sub("", before).strip()
            words = re.sub(r"\s+", " ", words).strip(" ;")
            level_words = KEYWORD.findall(words)
            level = ("SHOULD" if level_words[-1].startswith("SHOULD") else "MUST") if level_words else lead or "MUST"
            found.append({"id": rid, "section": section, "level": level, "text": words, "line": line,
                          "heading": heading})
    return found, problems


def main(argv):
    found, problems = requirements()
    if "--json" in argv:
        print(json.dumps(found, indent=1, ensure_ascii=False))
        return 0
    for p in problems:
        print(f"requirements: {p}")
    must = sum(r["level"] == "MUST" for r in found)
    print(f"requirements: {len(found)} ids ({must} MUST, {len(found) - must} SHOULD), {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
