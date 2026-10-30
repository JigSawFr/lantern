#!/usr/bin/env python3
"""The files of a release of the specification (SPEC.md § 3.6).

    python3 tools/release.py --out dist [--tag spec-v0.7] [--notes notes.md]

Writes into --out, for the version SPEC.md gives ("Draft 0.7" is 0.7):

- SPEC.md and openapi.yaml, as they are;
- lantern-schemas-<v>.zip (schemas/v1/), lantern-examples-<v>.zip
  (examples/v1/, the refused ones included), lantern-vectors-<v>.zip
  (vectors/), lantern-conformance-<v>.zip (the suite, conformance/, with the
  schemas it reads and tools/requirements.txt);
- lantern-<v>.zip: all of them, with the licences (LICENSES/, REUSE.toml)
  and the README;
- SHA256SUMS: the SHA-256 of each, as `sha256sum --check` reads it.

The zips are reproducible: their entries sorted, of fixed modes, dated by
SOURCE_DATE_EPOCH (the release workflow gives the tagged commit's time), so
that the same tree gives the same bytes. With --tag, the tag must name the
version SPEC.md gives (spec-v0.7), or nothing is written. With --notes, the
release's notes: SPEC.md's "Changes" for this version, and how to verify
the files. The release workflow (.github/workflows/release.yml) runs it on
a tag, then attests every file it wrote. Standard library only.
"""
import argparse
import hashlib
import os
import re
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPOSITORY = "JigSawFr/lantern"
SITE = "https://lantern.boreale.dev"


def version():
    """The text's version, from SPEC.md's first lines: "Draft 0.7" or "Version 1.0" gives "0.7" or "1.0"."""
    head = (ROOT / "SPEC.md").read_text(encoding="utf-8")[:2000]
    m = re.search(r"^(?:Draft|Version) (\d+\.\d+(?:\.\d+)?),", head, re.MULTILINE)
    if not m:
        sys.exit("release: SPEC.md does not say its version (Draft 0.7, …)")
    return m.group(1)


def files(*globs):
    out = []
    for pattern in globs:
        out += [p for p in ROOT.glob(pattern) if p.is_file() and "__pycache__" not in p.parts]
    return sorted(set(out), key=lambda p: p.relative_to(ROOT).as_posix())


def write_zip(path, members, when):
    """A zip of `members` (files of the tree), at their paths in it, reproducible."""
    stamp = max(when, 315532800)        # a zip's dates start in 1980
    date = time.gmtime(stamp)[:6]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for member in members:
            info = zipfile.ZipInfo(member.relative_to(ROOT).as_posix(), date_time=date)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if os.access(member, os.X_OK) else 0o644) << 16
            info.create_system = 3      # Unix, whatever builds it
            z.writestr(info, member.read_bytes())


def changes(v):
    """SPEC.md's "Changes" for version `v`: its entries, as written."""
    text = (ROOT / "SPEC.md").read_text(encoding="utf-8")
    part = text[text.index("\n## Changes\n"):]
    out, keep = [], False
    for line in part.splitlines()[2:]:
        if line.startswith("- "):
            keep = line.startswith(f"- {v} ")
        if keep:
            out.append(line)
    return "\n".join(out)


def notes(v, tag, names):
    link = f"{SITE}/spec/?utm_source=release&utm_medium=release-notes&utm_campaign={v}"
    return f"""Lantern {v}: the specification, its schemas, examples, test vectors, OpenAPI description and
conformance suite. Read it at <{link}>, or in SPEC.md below.

## What changed

{changes(v) or "See SPEC.md, section Changes."}

## Verifying these files

Each file below was built from the tag `{tag}` by this repository's release workflow, which attested
its provenance (SLSA, signed through Sigstore); `SHA256SUMS` holds their SHA-256.

```sh
gh attestation verify lantern-{v}.zip --repo {REPOSITORY}
sha256sum --check --ignore-missing SHA256SUMS
```

Files: {", ".join(f"`{n}`" for n in names)}.
"""


def main(argv=None):
    p = argparse.ArgumentParser(prog="tools/release.py", description="The files of a release of the specification.")
    p.add_argument("--out", default="dist", help="where to write them (default dist/)")
    p.add_argument("--tag", help="the release's tag, spec-v<version>, checked against SPEC.md")
    p.add_argument("--notes", metavar="FILE", help="also write the release's notes there")
    args = p.parse_args(argv)
    v = version()
    if args.tag is not None and args.tag != f"spec-v{v}":
        sys.exit(f"release: the tag {args.tag} does not name SPEC.md's version, {v} (spec-v{v})")
    when = int(os.environ.get("SOURCE_DATE_EPOCH") or 0)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*"):
        if old.is_file():
            old.unlink()
    schemas = files("schemas/v1/*.json")
    parts = {
        f"lantern-schemas-{v}.zip": schemas,
        f"lantern-examples-{v}.zip": files("examples/v1/*.json", "examples/v1/invalid/*.json"),
        f"lantern-vectors-{v}.zip": files("vectors/*.json"),
        f"lantern-conformance-{v}.zip": files("conformance/*.py") + schemas + files("tools/requirements.txt"),
    }
    every = sorted({m for members in parts.values() for m in members} | set(files(
        "SPEC.md", "openapi.yaml", "README.md", "REUSE.toml", "LICENSES/MIT.txt", "LICENSES/CC-BY-4.0.txt")),
        key=lambda m: m.relative_to(ROOT).as_posix())
    parts[f"lantern-{v}.zip"] = every
    for name, members in parts.items():
        write_zip(out / name, members, when)
    for name in ("SPEC.md", "openapi.yaml"):
        (out / name).write_bytes((ROOT / name).read_bytes())
    names = sorted(p.name for p in out.iterdir() if p.is_file())
    sums = "".join(f"{hashlib.sha256((out / n).read_bytes()).hexdigest()}  {n}\n" for n in names)
    (out / "SHA256SUMS").write_text(sums, encoding="ascii")
    if args.notes:
        Path(args.notes).write_text(notes(v, args.tag or f"spec-v{v}", names + ["SHA256SUMS"]), encoding="utf-8")
    for n in names + ["SHA256SUMS"]:
        print(f"{out / n}  {(out / n).stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
