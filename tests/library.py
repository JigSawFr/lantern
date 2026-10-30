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
import base64
import hashlib
import io
import json
import os
import struct
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import ed25519

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
     "video": "https://video.example.org/frostline/trailer", "atlas": "Q900001"},
    {"file": "Moss and Ember [0100EFEF00020000][v0].xci", "name": "Moss & Ember",
     "version_name": "1.0.0", "release": "2025-03-14", "installed_size": 8192,
     "ratings": [{"system": "PEGI", "rating": "16"}, {"system": "ESRB", "rating": "T"}]},
    {"file": "Moss and Ember [0100EFEF00020800][v131072].nsp", "name": "Moss & Ember",
     "version_name": "1.2.0"},
    {"file": "more/Tidewalker [0100C3D400040000][v0].nsp", "release": "2026-01-20",
     "ratings": [{"system": "CERO", "rating": "A"}],
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


def ed25519_sign(seed, message):
    """An Ed25519 signature (RFC 8032, § 5.1.6), for the tests only: the
    server verifies, it never signs. (public key, signature), raw bytes."""
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    public = ed25519.encode(ed25519.multiply(a, ed25519.G))
    r = int.from_bytes(hashlib.sha512(h[32:] + message).digest(), "little") % ed25519.L
    big_r = ed25519.encode(ed25519.multiply(r, ed25519.G))
    k = int.from_bytes(hashlib.sha512(big_r + public + message).digest(), "little") % ed25519.L
    return public, big_r + ((r + k * a) % ed25519.L).to_bytes(32, "little")


def signed_message(hid, platform, build, data, path):
    """SPEC.md § 8.4's bytes for a single-file package `data` installed at `path`."""
    sha = hashlib.sha256(data).hexdigest()
    canonical = '[{"path":%s,"sha256":"%s","size":%d}]' % (json.dumps(path, ensure_ascii=False), sha, len(data))  # noqa: UP031 - the canonical bytes, spelled out
    return ('{"build":%d,"id":"%s","manifest_sha256":"%s","platform":"%s","purpose":"lantern-homebrew-1",'  # noqa: UP031 - the canonical bytes, spelled out
            '"sha256":"%s"}' % (build, hid, hashlib.sha256(canonical.encode()).hexdigest(), platform, sha)).encode()


def signature(seed, message):
    public, value = ed25519_sign(seed, message)
    return {"alg": "ed25519", "public_key": base64.b64encode(public).decode(), "value": base64.b64encode(value).decode()}


def zipped(files, executable=()):
    """A zip of `files` (name: bytes); the names in `executable` get mode 0755, the others 0644."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, (2026, 10, 30, 12, 0, 0))
            info.external_attr = (0o100755 if name in executable else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return out.getvalue()


def zip_message(hid, platform, build, data):
    """SPEC.md § 8.4's bytes for a zip package `data`, its manifest its files at "/" + their names."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        manifest = sorted(({"path": "/" + i.filename, "sha256": hashlib.sha256(z.read(i)).hexdigest(),
                            "size": i.file_size} for i in z.infolist() if not i.is_dir()),
                          key=lambda e: e["path"].encode())
    canonical = "[" + ",".join('{"path":%s,"sha256":"%s","size":%d}' % (  # noqa: UP031 - the canonical bytes, spelled out
        json.dumps(e["path"], ensure_ascii=False), e["sha256"], e["size"]) for e in manifest) + "]"
    return ('{"build":%d,"id":"%s","manifest_sha256":"%s","platform":"%s","purpose":"lantern-homebrew-1",'  # noqa: UP031 - the canonical bytes, spelled out
            '"sha256":"%s"}' % (build, hid, hashlib.sha256(canonical.encode()).hexdigest(), platform,
                                hashlib.sha256(data).hexdigest())).encode()


FROSTLINE_ZIP = {
    f"switch/{FROSTLINE}/frostline.nro": nro("Frostline", "Noor", "1.4.0"),
    f"config/{FROSTLINE}/settings.ini": b"[journal]\nfolder=/switch/org.example.frostline/notes\n",
}
PAPERLAMP = "org.example.paperlamp"
PAPERLAMP_NRO = nro("Paper Lamp", "Ines", "0.9.2")
INES_KEY = hashlib.sha256(b"Ines's fictional signing key").digest()     # a seed, for the tests only
PAPERLAMP_SIGNATURE = signature(INES_KEY, signed_message(
    PAPERLAMP, "switch", 902, PAPERLAMP_NRO, f"/switch/{PAPERLAMP}/{PAPERLAMP}.nro"))
PORT = "org.example.frostline-port"
PORT_DATA_ROOT = "/switch/frostline/"       # where the upstream port looks for the game's data
# The versions of the original game's data file a port accepts (fictional bytes).
FROST_PAK = (b"frost.pak 1.0 " * 64, b"frost.pak 1.1 " * 64, b"frost.pak 1.1 gold " * 48)
PORT_DATA = [
    {"path": "data/frost.pak", "size": len(FROST_PAK[0]),
     "accept": [{"label": "1.0", "sha256": hashlib.sha256(FROST_PAK[0]).hexdigest()},
                {"label": "1.1", "sha256": hashlib.sha256(FROST_PAK[1]).hexdigest(),
                 "md5": hashlib.md5(FROST_PAK[1]).hexdigest()},
                {"label": "1.1 Gold edition", "sha1": hashlib.sha1(FROST_PAK[2]).hexdigest()}],
     "hint": {"en": "frost.pak, in the folder Frostline Tales is installed in.",
              "fr": "frost.pak, dans le dossier où Frostline Tales est installé."}},
    {"one_of": [[{"path": "music/full.pak", "hint": "From the soundtrack edition."},
                 {"path": "music/full.idx", "hint": "Next to full.pak."}],
                [{"path": "music/demo.pak", "hint": "From the free demo."}]]},
    {"path": "Extras/Bonus Maps.pak", "optional": True, "hint": "Bonus Maps.pak, from the soundtrack edition."},
]
PORT_OBJECT = {
    "original": {"name": "Frostline Tales", "year": 2004, "developer": "Fjord Works",
                 "stores": [{"store": "example", "id": "frostline-tales", "url": "https://store.example.org/frostline"}],
                 "title": {"platform": "switch", "title_id": "0100ABCD00010000"}},
    "engine": {"name": "Lanternlight", "version": "0.3.0", "source": "https://code.example.org/lea/lanternlight",
               "license": "GPL-2.0-or-later"},
    "data_root": PORT_DATA_ROOT, "assets": "user_owned", "requires_data": PORT_DATA}
PORT_META = {"schema": 1, "id": PORT, "name": "Frostline Port", "author": "Lea", "version": "0.3.0", "build": 300,
             "kind": "port", "genres": ["adventure"], "license": "GPL-2.0-or-later", "assets_license": "CC-BY-4.0",
             "requires": {"text": "Lanternlight runtime 2 or later",
                          "homebrew": [{"id": "org.example.lanternlight-runtime", "min_build": 200}]},
             "port": PORT_OBJECT}
# A Linux port (Annex A.6), PortMaster's layout: a launcher next to its
# folder, a package per architecture, each signed by Lea, and requirements a
# client checks (SPEC.md § 8.7), two of which it does not know.
HARBOR = "org.example.harborlights"
LEA_KEY = hashlib.sha256(b"Lea's fictional signing key").digest()      # a seed, for the tests only
HARBOR_LAUNCHER = b"#!/bin/sh\n# Harbor Lights, a fictional port\nexec ./org.example.harborlights/harbor\n"
HARBOR_ZIPS = {arch: zipped({"Harbor Lights.sh": HARBOR_LAUNCHER,
                             **{f"{HARBOR}/harbor.{a}": os.urandom(400) for a in names}},
                            executable=("Harbor Lights.sh", *(f"{HARBOR}/harbor.{a}" for a in names)))
               for arch, names in (("arm", ("aarch64", "armhf")), ("x86_64", ("x86_64",)), ("riscv64", ("riscv64",)))}
HARBOR_PAK = b"HARBOR fictional data, version 1.0\n" * 8
HARBOR_REQUIRES = {"text": "glibc 2.30, OpenGL ES 2 or Vulkan, 512 MiB of memory, a 640x480 screen",
                   "min": {"glibc": "2.30", "ram_mb": 512, "screen": "640x480", "kernel": "5.10"},
                   "gpu": ["gles2", "vulkan"], "vram_mb": 256}
HARBOR_META = {
    "schema": 1, "id": HARBOR, "platform": "linux", "name": "Harbor Lights", "author": "Lea", "version": "2.1.0",
    "build": 20100, "kind": "port", "genres": ["adventure", "simulation"], "tags": ["lighthouse", "classic"],
    "license": "GPL-2.0-or-later", "requires": HARBOR_REQUIRES,
    "packages": [{"file": f"harbor-{arch}.zip", "arch": names,
                  "signature": signature(LEA_KEY, zip_message(HARBOR, "linux", 20100, HARBOR_ZIPS[arch]))}
                 for arch, names in (("arm", ["aarch64", "armhf"]), ("x86_64", ["x86_64"]), ("riscv64", ["riscv64"]))],
    "port": {"original": {"name": "Harbor Lights", "year": 1998, "developer": "Fjord Works"},
             "engine": {"name": "Lighthouse", "version": "2.1.0"},
             "data_root": f"/{HARBOR}/data/", "assets": "user_owned",
             "requires_data": [{"path": "HARBOR.PAK", "size": len(HARBOR_PAK),
                                "accept": [{"label": "1.0", "sha256": hashlib.sha256(HARBOR_PAK).hexdigest()}],
                                "hint": "HARBOR.PAK, in the folder where Harbor Lights is installed."}]}}


def port(**changes):
    """A port's homebrew.json, with fields of its `port` object changed (None removes one)."""
    meta = dict(PORT_META)
    for key in ("id", "arch", "platform"):
        if key in changes:
            meta[key] = changes.pop(key)
    obj = {**PORT_OBJECT, **changes}
    meta["port"] = {k: v for k, v in obj.items() if v is not None}
    meta = {k: v for k, v in meta.items() if v is not None}
    return json.dumps(meta).encode()


def port_zip(hid=PORT, **more):
    """A port's archive, its files under /switch/<hid>/, and `more` (name: bytes) there too."""
    files = {"frostline-port.nro": nro("Frostline Port", "Lea", "0.3.0"),
             "readme.txt": b"Bring frost.pak from your own copy of Frostline Tales.\n", **more}
    return zipped({f"switch/{hid}/{name}": data for name, data in files.items()})


HOMEBREW = {
    # A zip and its manifest, with a homebrew.json (the signature, when a test adds one).
    "homebrew/frostline/frostline.zip": zipped(FROSTLINE_ZIP),
    "homebrew/frostline/homebrew.json": json.dumps({
        "schema": 1, "id": FROSTLINE, "name": "Frostline", "author": "Noor", "version": "1.4.0", "build": 10400,
        "kind": "tool", "tags": ["journal", "night mode"], "license": "MIT", "source": "https://code.example.org/noor/frostline",
        "summary": {"en": "A pocket journal for long nights.", "fr": "Un carnet de poche pour les longues nuits."},
        "requires": {"text": "Atmosphère 1.7 or later", "min": {"atmosphere": "1.7.0"}},
        "x-example-shelf": "unknown fields are ignored"}).encode(),
    # An .nro whose name, author and version come from its NACP; the rest from homebrew.json.
    # Signed by its author (SPEC.md § 8.4).
    "homebrew/paperlamp/paperlamp.nro": PAPERLAMP_NRO,
    "homebrew/paperlamp/homebrew.json": json.dumps({
        "schema": 1, "id": PAPERLAMP, "build": 902, "kind": "game", "genres": ["puzzle"], "atlas": "Q900002",
        "ratings": [{"system": "PEGI", "rating": "12"}],
        "license": "GPL-3.0-or-later", "icon": "https://media.example.org/paperlamp/icon.jpg",
        "signature": PAPERLAMP_SIGNATURE}).encode(),
    # A port: the user brings the original game's data (SPEC.md § 8.1).
    "homebrew/frostline-port/frostline-port.zip": port_zip(),
    "homebrew/frostline-port/homebrew.json": port(),
    # An overlay (a single .ovl, in a root that needs consent) that needs a loader.
    "homebrew/ember-overlay/ember.ovl": os.urandom(256),
    "homebrew/ember-overlay/homebrew.json": json.dumps({
        "schema": 1, "id": "org.example.ember-overlay", "name": "Ember Overlay", "author": "Noor", "version": "1.2.0",
        "build": 120, "kind": "overlay",
        "requires": {"text": "An overlay loader", "homebrew": [{"id": "org.example.overlay-loader", "min_build": 1}]}
    }).encode(),
    # The Linux port, a package per architecture.
    **{f"homebrew/harbor-linux/harbor-{arch}.zip": data for arch, data in HARBOR_ZIPS.items()},
    "homebrew/harbor-linux/homebrew.json": json.dumps(HARBOR_META).encode(),
    # An Android app, installed by the system: its own id, its arches, its signing certificate.
    "homebrew/moss-remote/moss-remote.apk": os.urandom(300),
    "homebrew/moss-remote/homebrew.json": json.dumps({
        "schema": 1, "id": "org.example.mossremote", "name": "Moss Remote", "author": "Ines", "version": "3.0",
        "build": 30, "kind": "tool", "arch": ["aarch64", "armhf"], "system_id": "org.example.mossremote",
        "signer_sha256": hashlib.sha256(b"Ines's fictional certificate").hexdigest()}).encode(),
    # A kind this server does not know: read as app.
    "homebrew/ember-widget/ember-widget.nro": nro("Ember Widget", "Noor", "1.0.0"),
    "homebrew/ember-widget/homebrew.json": json.dumps({
        "schema": 1, "id": "org.example.ember-widget", "build": 100, "kind": "widget"}).encode(),
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
    # Ports the server refuses: data outside the port's root, an escape, the
    # data itself in the package (by path, then by hash), no original, and an
    # arch the Switch does not run.
    "homebrew/port-outside/p.zip": port_zip("org.example.port-outside"),
    "homebrew/port-outside/homebrew.json": port(id="org.example.port-outside", data_root="/atmosphere/frost/"),
    "homebrew/port-area/p.zip": port_zip("org.example.port-area"),
    "homebrew/port-area/homebrew.json": port(id="org.example.port-area", data_root="/switch/"),
    "homebrew/port-escape/p.zip": port_zip("org.example.port-escape"),
    "homebrew/port-escape/homebrew.json": port(id="org.example.port-escape", requires_data=[
        {"path": "../../atmosphere/contents/x", "hint": "Nowhere."}]),
    "homebrew/port-absolute/p.zip": port_zip("org.example.port-absolute"),
    "homebrew/port-absolute/homebrew.json": port(id="org.example.port-absolute", requires_data=[
        {"path": "/switch/frostline/frost.pak", "hint": "Nowhere."}]),
    "homebrew/port-shipped/p.zip": port_zip("org.example.port-shipped", **{"data/frost.pak": b"x"}),
    "homebrew/port-shipped/homebrew.json": port(id="org.example.port-shipped",
                                                data_root="/switch/org.example.port-shipped/"),
    "homebrew/port-hashed/p.zip": port_zip("org.example.port-hashed", **{"game.dat": FROST_PAK[1]}),
    "homebrew/port-hashed/homebrew.json": port(id="org.example.port-hashed"),
    "homebrew/port-anonymous/p.zip": port_zip("org.example.port-anonymous"),
    "homebrew/port-anonymous/homebrew.json": port(id="org.example.port-anonymous", original=None),
    "homebrew/port-lonely/p.zip": port_zip("org.example.port-lonely"),
    "homebrew/port-lonely/homebrew.json": port(id="org.example.port-lonely", requires_data=[
        {"one_of": [[{"path": "music/full.pak", "hint": "Alone."}]]}]),
    "homebrew/port-x86/p.zip": port_zip("org.example.port-x86"),
    "homebrew/port-x86/homebrew.json": port(id="org.example.port-x86", arch=["aarch64"]),   # none on a Switch
    # A signature that does not verify, and a homebrew.json of a newer schema.
    "homebrew/forged/forged.nro": nro("Forged Lamp", "Ines", "0.9.3"),
    "homebrew/forged/homebrew.json": json.dumps({
        "schema": 1, "id": "org.example.forged", "build": 903, "signature": PAPERLAMP_SIGNATURE}).encode(),
    "homebrew/future/future.nro": nro("Future Lamp", "Ines", "9.0.0"),
    "homebrew/future/homebrew.json": json.dumps({"schema": 2, "id": "org.example.future", "build": 1}).encode(),
    # A genre not of the list, and a condition not of its form: not served (SPEC.md § 8.1, § 8.7).
    "homebrew/roguelite/roguelite.nro": nro("Ember Rogue", "Noor", "1.0.0"),
    "homebrew/roguelite/homebrew.json": json.dumps({
        "schema": 1, "id": "org.example.ember-rogue", "build": 100, "kind": "game", "genres": ["roguelite"]}).encode(),
    "homebrew/metal/metal.nro": nro("Moss Metal", "Noor", "1.0.0"),
    "homebrew/metal/homebrew.json": json.dumps({
        "schema": 1, "id": "org.example.moss-metal", "build": 100,
        "requires": {"text": "Metal", "gpu": ["metal"]}}).encode(),
}
SERVED_HOMEBREW = 9     # frostline (switch and 3ds), paperlamp, moss-clock, frostline-port, ember-widget,
#                         ember-overlay, moss-remote (android), harborlights (linux)
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
