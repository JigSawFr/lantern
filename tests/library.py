#!/usr/bin/env python3
"""A tiny fictional library for the reference server and the suite.

    python3 tests/library.py DIR

Small files of random bytes, named as on a real shelf, and a library.json
that names some of them. Fictional games only; nothing is committed but this
script.
"""
import json
import os
import sys
from pathlib import Path

# (file, size): base games, updates, an add-on, a game in two formats, an
# empty file, a game in a subfolder, and files the server must skip.
FILES = [
    ("Frostline Tales [0100ABCD00010000][v0].nsp", 6000),
    ("Frostline Tales [0100ABCD00010800][v65536].nsz", 1500),
    ("Frostline Tales [0100ABCD00010800][v196608].nsz", 2500),
    ("Frostline Tales Harbor Pack [0100ABCD00011001][v0].nsp", 700),
    ("Moss and Ember [0100EFEF00020000][v0].xci", 4096),
    ("Moss and Ember [0100EFEF00020800][v131072].nsp", 900),
    ("Paper Comets [0100A1B200030000][v0].xcz", 3300),
    ("Paper Comets [0100A1B200030000][v0].nsp", 3100),
    ("Quiet Orchard [0100E5F600050000][v0].nsp", 0),
    ("more/Tidewalker [0100C3D400040000][v0].nsp", 1234),
    ("more/shelf-notes.nsp", 10),       # no id: skipped
    ("more/cover.jpg", 10),             # not a package: skipped
    (".trash/Old Lanterns [0100FFEE00060000][v0].nsp", 10),  # dot folder: skipped
]
META = {"schema": 1, "apps": [
    {"file": "Moss and Ember [0100EFEF00020000][v0].xci", "name": "Moss & Ember",
     "display_version": "1.0.0", "release": "2025-03-14"},
    {"file": "Moss and Ember [0100EFEF00020800][v131072].nsp", "name": "Moss & Ember",
     "display_version": "1.2.0"},
    {"file": "more/Tidewalker [0100C3D400040000][v0].nsp", "release": "2026-01-20",
     "x-example-shelf": "unknown fields are ignored"},
]}


def make(root):
    root = Path(root)
    for name, size in FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(os.urandom(size))
    (root / "library.json").write_text(json.dumps(META, indent=1), encoding="utf-8")
    return root


SERVED = 10  # the packages the server should list


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: tests/library.py DIR")
    print(f"{make(sys.argv[1])}: {len(FILES)} files")
