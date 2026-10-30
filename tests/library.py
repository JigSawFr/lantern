#!/usr/bin/env python3
"""A tiny fictional library for the reference server and the suite.

    python3 tests/library.py DIR

Small files of random bytes, named as on a real shelf, and a library.json
that names some of them and gives their titles' sheets; two platforms (a
Switch's packages and an Android app); homebrew in homebrew/ (an .nro built
here, with its control data, a zip and its manifest, a 3DS build of the same
homebrew, and archives the server must refuse); cheat sets in cheats/.
Fictional games and names only; nothing is committed but this script.
"""
import io
import json
import os
import struct
import sys
import zipfile
from pathlib import Path

# (file, size): base games, updates, an add-on, a game in two formats, an
# empty file, a game in a subfolder, an Android app, and files the server
# must skip.
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
    ("android/Frostline Tales.apk", 2048),
    ("android/Unnamed.apk", 64),        # no identity in library.json: skipped
    ("more/shelf-notes.nsp", 10),       # no id: skipped
    ("more/cover.jpg", 10),             # not a package: skipped
    (".trash/Old Lanterns [0100FFEE00060000][v0].nsp", 10),  # dot folder: skipped
]
META = {"schema": 1, "apps": [
    {"file": "Frostline Tales [0100ABCD00010000][v0].nsp", "release": "2025-03-14",
     "publisher": "Fjord Works", "developer": "Fjord Works",
     "genres": ["adventure", "puzzle", "dating-sim"],     # not a genre: dropped
     "tags": ["co-op", "winter"], "players": {"min": 1, "max": 4, "online": True, "online_max": 8},
     "ratings": [{"system": "PEGI", "rating": "7"}, {"system": "pegi", "rating": "7"}],
     "languages": ["en", "fr", "ja"],
     "summary": {"en": "Guide a lantern-bearer across a frozen archipelago.",
                 "fr": "Guidez un porteur de lanterne sur un archipel gelé."},
     "video": "https://video.example.org/frostline/trailer"},
    {"file": "Moss and Ember [0100EFEF00020000][v0].xci", "name": "Moss & Ember",
     "version_name": "1.0.0", "release": "2025-03-14"},
    {"file": "Moss and Ember [0100EFEF00020800][v131072].nsp", "name": "Moss & Ember",
     "version_name": "1.2.0"},
    {"file": "more/Tidewalker [0100C3D400040000][v0].nsp", "release": "2026-01-20",
     "x-example-shelf": "unknown fields are ignored"},
    {"file": "android/Frostline Tales.apk", "platform": "android", "title_id": "org.example.frostlinetales",
     "version_code": 12, "version_name": "1.2.0", "name": "Frostline Tales", "genres": ["adventure"],
     "summary": "Frostline Tales, on a phone."},
]}

SERVED = 11         # the apps the server should list, every platform
SWITCH = 10         # of which on the Switch
PLATFORMS = ["android", "switch"]
FROSTLINE = "org.example.frostline"


def nro(name, author, version, code=b"\0" * 64):
    """A Switch homebrew as the server reads it: a header, code, and an asset
    section with an icon and its control data (NACP), name and author in the
    first language (SPEC.md Annex A.1, server/nro.py)."""
    nacp = bytearray(0x4000)
    for offset, text, size in ((0, name, 0x200), (0x200, author, 0x100), (0x3060, version, 0x10)):
        raw = text.encode()[:size - 1]
        nacp[offset:offset + len(raw)] = raw
    head = bytearray(0x80)
    head[0x10:0x14] = b"NRO0"
    struct.pack_into("<I", head, 0x18, 0x80 + len(code))
    icon = b"\xff\xd8\xff\xe0" + bytes(28)
    assets = b"ASET" + struct.pack("<I", 0) + struct.pack("<QQ", 0x38, len(icon)) \
        + struct.pack("<QQ", 0x38 + len(icon), len(nacp)) + struct.pack("<QQ", 0, 0)
    return bytes(head) + code + assets + icon + bytes(nacp)


def zipped(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


FROSTLINE_ZIP = {
    f"switch/{FROSTLINE}/frostline.nro": nro("Frostline", "Noor", "1.4.0"),
    f"config/{FROSTLINE}/settings.ini": b"[journal]\nfolder=/switch/org.example.frostline/notes\n",
}
HOMEBREW = {
    # A zip and its manifest, with a homebrew.json (the signature, when a test adds one).
    "homebrew/frostline/frostline.zip": zipped(FROSTLINE_ZIP),
    "homebrew/frostline/homebrew.json": json.dumps({
        "schema": 1, "id": FROSTLINE, "name": "Frostline", "author": "Noor", "version": "1.4.0", "build": 10400,
        "category": "tool", "license": "MIT", "source": "https://code.example.org/noor/frostline",
        "summary": {"en": "A pocket journal for long nights.", "fr": "Un carnet de poche pour les longues nuits."},
        "requires": {"text": "Atmosphère 1.7 or later", "min": {"atmosphere": "1.7.0"}},
        "x-example-shelf": "unknown fields are ignored"}).encode(),
    # An .nro whose name, author and version come from its NACP; the rest from homebrew.json.
    "homebrew/paperlamp/paperlamp.nro": nro("Paper Lamp", "Ines", "0.9.2"),
    "homebrew/paperlamp/homebrew.json": json.dumps({
        "schema": 1, "id": "org.example.paperlamp", "build": 902, "category": "game",
        "license": "GPL-3.0-or-later", "icon": "https://media.example.org/paperlamp/icon.jpg"}).encode(),
    # An .nro alone: a local id, its build from its version.
    "homebrew/tools/moss-clock.nro": nro("Moss Clock", "Lea", "2.1.0"),
    # The same homebrew, built for the 3DS.
    "homebrew/frostline-3ds/frostline.3dsx": os.urandom(512),
    "homebrew/frostline-3ds/homebrew.json": json.dumps({
        "schema": 1, "platform": "3ds", "id": FROSTLINE, "name": "Frostline", "author": "Noor",
        "version": "1.1.0", "build": 10100}).encode(),
    # Archives the server refuses to serve (SPEC.md § 8.2, Annex A.1).
    "homebrew/escape/escape.zip": zipped({"../atmosphere/contents/0100000000001000/exefs.nsp": b"x"}),
    "homebrew/outside/outside.zip": zipped({"bootloader/hekate_ipl.ini": b"[config]\n"}),
    "homebrew/broken/broken.zip": b"PK\x03\x04 not a zip",
}
SERVED_HOMEBREW = 4     # frostline (switch and 3ds), paperlamp, moss-clock
CHEATS = {
    "cheats/0100ABCD00010000/4A1B2C3D4E5F6071/Community_list.txt":
        "[Endless lamp oil]\n04000000 0123A4B0 00000063\n",
    "cheats/0100ABCD00010000/4A1B2C3D4E5F6071/Noor.txt": "[Walk on thin ice]\n04000000 0123A4C8 00000001\n",
    "cheats/0100EFEF00020000/0123456789ABCDEF/Community_list.txt": "[Embers never fade]\n04000000 00ABC010 0000FFFF\n",
    "cheats/not-a-title/xyz/Broken.txt": "skipped\n",
}


def make(root):
    root = Path(root)
    for name, size in FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(os.urandom(size))
    for name, data in {**HOMEBREW, **{k: v.encode() for k, v in CHEATS.items()}}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (root / "library.json").write_text(json.dumps(META, indent=1), encoding="utf-8")
    return root


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: tests/library.py DIR")
    print(f"{make(sys.argv[1])}: {len(FILES)} packages, {len(HOMEBREW)} homebrew files, {len(CHEATS)} cheat files")
