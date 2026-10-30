#!/usr/bin/env python3
"""Lantern reference server: a folder of packages, served by the protocol.

    python3 -m server --library DIR [--port 8080] [--users users.json]
    server/lantern_server.py --library DIR ...

A reference, not a product: it shows what SPEC.md asks of a server in
standard-library Python, and passes conformance/run.py.

Apps (SPEC.md § 6): every package below DIR (dot folders, homebrew/ and
cheats/ skipped). A Switch package (.nsp, .nsz, .xci, .xcz) is identified by
DIR/library.json when it lists the file, otherwise by the `[0100ABCD00010000]`
and `[v196608]` in its name; its title id and type follow from the app id.
A package of another platform (.cia, .vpk, .pkg, .apk: SPEC.md Annex A) is
served only when library.json gives its identity. library.json:

    {"schema": 1, "apps": [
      {"file": "Frostline Tales [0100ABCD00010000][v0].nsp",
       "title_id": "0100ABCD00010000", "app_id": "0100ABCD00010000",
       "type": "base", "version_code": 0, "version_name": "1.0.0",
       "name": "Frostline Tales", "release": "2025-03-14",
       "developer": "Fjord Works", "genres": ["adventure"], "players": {"min": 1, "max": 4},
       "summary": {"en": "Guide a lantern-bearer…", "fr": "Guidez un porteur de lanterne…"}},
      {"file": "android/frostline.apk", "platform": "android",
       "title_id": "org.example.frostlinetales", "version_code": 12, "name": "Frostline Tales"}]}

An entry's other fields (publisher, developer, genres, tags, players,
ratings, languages, summary, description, icon, banner, screenshots, video)
make its title's sheet (feature `titles`, SPEC.md § 7); summary and
description may be one text or one per language.

Homebrew (SPEC.md § 8): every .nro, .ovl, .3dsx, .zip, .apk, .vpk, .pkg and .cia
below DIR/homebrew/. An .nro's name, author and version come from its NACP
(server/nro.py); a homebrew.json next to a package gives the rest:

    {"schema": 1, "id": "org.example.frostline", "build": 10400, "kind": "tool",
     "license": "MIT", "source": "https://code.example.org/noor/frostline",
     "category": "tool", "summary": "…", "requires": {"text": "…", "min": {"atmosphere": "1.7.0"}},
     "system_id": "…", "arch": ["aarch64", "armhf"], "signer_sha256": "…",
     "signature": {"alg": "ed25519", "public_key": "…", "value": "…"}}

`kind` is app, game, port, emulator, tool, overlay, sysmodule or theme (an
unknown one is read as app). `arch` is a list (aarch64, armhf, x86, x86_64;
none on a Switch or a 3DS, which have one architecture), `signer_sha256` the
platform's own signing certificate's SHA-256 (Android), `assets_license` an
SPDX expression, `system_id` the platform's own id of the homebrew where it
has one, and
`requires.homebrew` the homebrew it needs: [{"id", "min_build"}]. The NACP
has no integer version: `build` comes from homebrew.json (without one, this
server derives its own from the version, 1.4.2 giving 1004002). A port
groups the rest under `port`:

    {"schema": 1, "id": "org.example.frostline-port", "kind": "port", "build": 300,
     "port": {
       "original": {"name": "Frostline Tales", "year": 2004, "developer": "Fjord Works",
                    "stores": [{"store": "example", "id": "frostline", "url": "https://store.example.org/frostline"}]},
       "engine": {"name": "Lanternlight", "version": "0.3.0", "license": "GPL-2.0-or-later"},
       "data_root": "/switch/frostline/",
       "assets": "user_owned",
       "requires_data": [
         {"path": "frost.pak", "size": 896,
          "accept": [{"label": "1.0", "sha256": "<hex>"}, {"label": "1.1", "md5": "<hex>"}],
          "hint": {"en": "frost.pak, in the folder the game is installed in."}},
         {"one_of": [[{"path": "music.pak", "hint": "…"}], [{"path": "music-demo.pak", "hint": "…"}]],
          "optional": true}]}}

`data_root` is the folder the port expects its data in, under the profile's
areas (/switch/ or /config/ on a Switch); each requires_data path is
relative to it, exact, case included, with its `hint` (required); an
unknown `assets` is served as user_owned. The server never serves those files: a
package that holds one of them, by path or by sha256, is not served.

A .zip's manifest is its files, each at "/" + its name in the archive; one
whose paths break SPEC.md § 8.2 or leave the platform's roots is not
served. A signature is served as given, never made here, and only when it
verifies (server/ed25519.py): a package whose signature does not verify is
not served. Without an id, a homebrew gets `local.<its file's name>`. A
homebrew.json of a newer schema is treated as absent: the packages next to
it are not served, since what it says of them is unknown.

Cheats (SPEC.md § 10): DIR/cheats/[<platform>/]<title id>/<build id>/<source>.txt,
one set per file (the Switch when no platform is named).

Save backups (SPEC.md § 9): kept under --saves (default DIR/.lantern-saves/),
an index.json and the archives, sent in one request or by resumable upload.

Each file is hashed once (SHA-256); the hashes are kept with the server's
uid and secret in a state file (--state, default DIR/.lantern-state.json).
Every file this server reads or writes has a `schema`: one newer than it
knows is treated as absent and never written over, and the keys it does
not know are kept.

Families offered: library, titles, changes, homebrew, cheats, saves (to an
account with the scope), and pairing when there are accounts. Requests and
sections stay at 0: their routes answer 404.

Accounts (SPEC.md § 5): without --users, the server is public, every caller
reads the library anonymously, and nobody pairs. With --users FILE:

    {"schema": 1, "public": false, "users": [
      {"name": "lea", "password": "pbkdf2-sha256$600000$<salt>$<hash>",
       "scopes": ["library", "saves", "cheats"], "state": "active"}]}

`python3 -m server --hash-password` prints a password's hash. `state` is
`active` or `frozen`. A password is only ever typed on the server's own
page, /pair: a console gets a token by pairing (SPEC.md § 5.2), which the
user approves there, signed in, with the code the console shows. Tokens are
kept hashed in the state file ("tokens"); `--tokens` lists them and
`--revoke ID` revokes one, even while the server runs. `--token-days N`
makes new tokens expire after N days.

TLS: give --tls-cert and --tls-key; /pair then shows the short fingerprint
of the key (SPEC.md § 5.3). Without them the server speaks plain HTTP, and
only on a loopback address (127.0.0.0/8, ::1), for testing: SPEC.md § 2.

LAN discovery (SPEC.md § 4.1): --discovery answers Lantern's discovery
datagram on UDP 47115 (--discovery-port to change it), from local addresses
only (not global ones), a few times a second per address.
DNS-SD is not advertised: the standard library has no mDNS.
"""
import argparse
import base64
import getpass
import hashlib
import hmac
import html
import ipaddress
import json
import math
import re
import secrets
import socket
import ssl
import sys
import threading
import time
import traceback
import uuid
import zipfile
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

try:
    from server import ed25519, nro
except ImportError:     # run as server/lantern_server.py
    import ed25519
    import nro

VERSION = "0.3.0"
BASE = "/api/lantern"
FAMILIES = ("library", "titles", "changes", "sections", "homebrew", "saves", "cheats", "requests", "pairing")
OFFERED = {"library": 1, "titles": 1, "changes": 1, "homebrew": 1, "saves": 1, "cheats": 1}  # the schema written
SCOPE_OF = {"library": "library", "titles": "library", "changes": "library", "homebrew": "library",
            "saves": "saves", "cheats": "cheats"}
PAGE_LIMIT = 500        # limits.page_size
PAGE_DEFAULT = 100
BODY_LIMIT = 1 << 20    # a request document, well under SPEC.md § 13's 32 MiB
DRAIN_LIMIT = 4 << 20   # a body left unread is read and dropped up to this, else the connection is closed
JOURNAL_LIMIT = 10000   # changes kept for /v1/changes and /v1/titles/changes; older tokens are gone
CURSOR_LIMIT = 10000    # cursors kept; older ones are gone
TITLES_AT_ONCE = 100    # SPEC.md § 7.2
CHEAT_LIMIT = 1 << 20   # SPEC.md § 10
MANIFEST_LIMIT = 4096   # SPEC.md § 8.2
SAVE_BODY = 8 << 20     # limits.save_body
SAVE_SIZE = 1 << 30     # limits.save_size
SAVE_CHUNK = 1 << 20    # an upload's chunk_size
SAVES_KEPT = 10         # limits.saves_kept_per_title
UPLOAD_HOURS = 24       # an upload not finished by then is gone
ID16 = re.compile(r"^[0-9A-F]{16}$")
PLATFORM = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")         # SPEC.md § 4.3
CORE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")            # SPEC.md § 6.1
WORD = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
HOMEBREW_ID = re.compile(r"^(?=.{1,128}$)[a-z][a-z0-9_-]*(?:\.[a-z0-9][a-z0-9_-]*)+$")
BUILD_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
DOTTED = re.compile(r"^[0-9]+(?:\.[0-9]+){0,3}$")
TID_IN_NAME = re.compile(r"\[([0-9A-Fa-f]{16})\]")
VERSION_IN_NAME = re.compile(r"\[v(\d+)\]")
# The profiles of SPEC.md's Annex A, as far as this server needs them: the
# id's form, the types and formats of apps, whether a newer base replaces the
# old one (§ 6.3), and for homebrew, each format's place (a single file's
# path, None for an archive and its manifest, "system" for a package the
# platform's installer installs), the roots a manifest may write to, and the
# areas a port's data_root may lie in (which the user approves once).
PROFILES = {
    "switch": {"id": ID16, "title": re.compile(r"^[0-9A-F]{12}[02468ACE]000$"), "types": ("base", "update", "dlc"), "formats": ("nsp", "nsz", "xci", "xcz"),
               "build_id": re.compile(r"^[0-9A-F]{1,64}$"), "homebrew": {"nro": "/switch/{id}/{id}.nro", "ovl": "/switch/.overlays/{file}", "zip": None},
               "roots": ("/switch/{id}/", "/config/{id}/", "/atmosphere/", "/switch/.overlays/"),
               "areas": ("/switch/", "/config/")},
    "3ds": {"id": ID16, "types": ("base", "update", "dlc"), "formats": ("cia",),
            "homebrew": {"3dsx": "/3ds/{id}/{id}.3dsx", "zip": None, "cia": "system"}, "roots": ("/3ds/{id}/", "/luma/", "/boot.firm", "/boot.3dsx", "/gm9/"),
            "areas": ("/3ds/",)},
    "vita": {"id": re.compile(r"^[A-Z]{4}[0-9]{5}$"), "types": ("base", "update", "dlc"), "formats": ("vpk",),
             "homebrew": {"vpk": "system"}, "roots": ()},
    "ps4": {"id": re.compile(r"^[A-Z]{4}[0-9]{5}$"), "types": ("base", "update", "dlc"), "formats": ("pkg",),
            "homebrew": {"pkg": "system"}, "roots": ()},
    "android": {"id": re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$"), "types": ("base",),
                "formats": ("apk",), "replaces": True, "homebrew": {"apk": "system"}, "roots": ()},
}
APP_EXT = {f: p for p, prof in PROFILES.items() for f in prof["formats"]}   # nsp -> switch, apk -> android…
HOMEBREW_EXT = {"nro": "switch", "ovl": "switch", "zip": "switch", "3dsx": "3ds", "cia": "3ds", "vpk": "vita", "pkg": "ps4",
                "apk": "android"}
GENRES = ("action", "adventure", "rpg", "strategy", "simulation", "sports", "racing", "puzzle", "platformer",
          "shooter", "fighting", "music", "party", "education", "other")
CATEGORIES = ("game", "emulator", "tool", "media", "system", "other")
KINDS = ("app", "game", "port", "emulator", "tool", "overlay", "sysmodule", "theme")   # unknown: app
ARCH = re.compile(r"^[a-z0-9_]{1,32}$")     # aarch64, armhf, x86, x86_64, or a later one (SPEC.md § 8.2)
ONE_ARCH = ("switch", "3ds")                # profiles of one architecture: no arch (Annex A)
ASSETS = ("included", "demo_included", "free_external", "user_owned")    # unknown: user_owned (§ 8.6)
DATA_LIMIT = 256        # files a port's requires_data names, alternatives included (SPEC.md § 13)
ACCEPT_LIMIT = 32       # accepted versions of one data file (SPEC.md § 13)
SLOT = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
HASH_FORMS = {"sha256": 64, "sha1": 40, "md5": 32}  # an accepted version's hashes, lower-case hex
SPDX = re.compile(r"^[A-Za-z0-9.+:() -]{1,256}$")
SAVE_KINDS = ("account", "device", "bcat", "cache", "other")
RATING_SYSTEM = re.compile(r"^[A-Z][A-Z0-9-]{1,15}$")
CHUNK = 1 << 20
SCOPES = ("library", "saves", "cheats", "cheats.write", "requests", "admin")
DISCOVERY_PORT = 47115
DATAGRAM_LIMIT = 1200   # SPEC.md § 4.1, § 13
CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # 5 bits a symbol; no 0, O, 1 or I
CODE_SYMBOLS = 8        # 40 bits
PAIR_EXPIRES = 600      # seconds a code lives (SPEC.md § 5.2: 10 minutes at most)
PAIR_INTERVAL = 5       # seconds between polls
PAIR_RATE = (10, 60.0)          # pairing requests per address, per window
PAIR_ATTEMPTS = (10, 600.0)     # failed sign-ins or codes on /pair per address, per window
PENDING_LIMIT = 1000            # pairings waiting at once
# check_password() against this when the name is unknown, so that it takes as long.
NO_USER = "pbkdf2-sha256$600000$AAAAAAAAAAAAAAAAAAAAAA$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def log(msg):
    print(f"lantern: {msg}", file=sys.stderr, flush=True)


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unb64url(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def clip(text, limit=512):
    """A string cut to `limit` UTF-8 bytes on a character boundary (SPEC.md § 13)."""
    return text.encode()[:limit].decode(errors="ignore")


def plain(value, limit=512):
    """A string from a file this server reads, without control characters and cut to `limit`; None otherwise."""
    if not isinstance(value, str):
        return None
    value = "".join(c for c in value if ord(c) >= 32 and ord(c) != 127 or c == "\n").strip()
    return clip(value, limit) or None


def utc(ns):
    return datetime.fromtimestamp(ns / 1e9, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc(offset=0.0):
    return utc(time.time_ns() + int(offset * 1e9))


def is_int(value, top=1 << 64):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < top


def is_loopback(host):
    """True for 127.0.0.0/8, ::1 and names that resolve only to them."""
    host = host.strip("[]")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0].split("%")[0]).is_loopback for i in infos)


def der(data, pos):
    """(content start, content end, tag) of the DER element at `pos`."""
    tag, length, pos = data[pos], data[pos + 1], pos + 2
    if length & 0x80:
        n = length & 0x7F
        length, pos = int.from_bytes(data[pos:pos + n], "big"), pos + n
    return pos, pos + length, tag


def spki_sha256(cert_pem):
    """The SHA-256 of a certificate's SubjectPublicKeyInfo (SPEC.md § 5.3), hex."""
    first = re.search(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", cert_pem, re.DOTALL)
    data = ssl.PEM_cert_to_DER_cert(first.group(0))
    start, _, _ = der(data, 0)              # Certificate
    pos, end, _ = der(data, start)          # TBSCertificate
    fields = []
    while pos < end:
        _, after, tag = der(data, pos)
        fields.append((pos, after, tag))
        pos = after
    if fields[0][2] == 0xA0:                # [0] version
        fields = fields[1:]
    begin, after, _ = fields[5]             # serial, signature, issuer, validity, subject, SPKI
    return hashlib.sha256(data[begin:after]).hexdigest()


def short_fingerprint(sha256_hex):
    """The first 16 hex digits, upper-case, in groups of 4 (SPEC.md § 5.3)."""
    return " ".join(sha256_hex[i:i + 4].upper() for i in range(0, 16, 4))


class Limiter:
    """At most `count` events per `window` seconds for each key (an address)."""

    def __init__(self, count, window):
        self.count, self.window, self.events, self.lock = count, window, {}, threading.Lock()

    def wait(self, key):
        """Seconds to wait before the next event, 0 when it may happen now."""
        now = time.monotonic()
        with self.lock:
            kept = [t for t in self.events.get(key, ()) if now - t < self.window]
            self.events[key] = kept
            if len(self.events) > 10000:
                self.events = {k: v for k, v in self.events.items() if v and now - v[-1] < self.window}
            return max(1, math.ceil(self.window - (now - kept[0]))) if len(kept) >= self.count else 0

    def record(self, key):
        with self.lock:
            self.events.setdefault(key, []).append(time.monotonic())

    def hit(self, key):
        wait = self.wait(key)
        if not wait:
            self.record(key)
        return wait


def slow_down(wait, detail):
    return Problem(429, "slow_down", "Slow down", detail, {"Retry-After": str(int(wait))})


def derive(app_id):
    """(title_id, type) of a Switch app id: base ...000, update ...800, add-on otherwise."""
    n = int(app_id, 16)
    low = n & 0x1FFF
    kind = "base" if low == 0 else "update" if low == 0x800 else "dlc"
    return f"{n & ~0x1FFF:016X}", kind


def title_id_ok(platform, title_id):
    """A title id of the core's form (SPEC.md § 6.1) and of its profile's, when there is one
    (on a Switch, a base game's id: Annex A.1)."""
    profile = PROFILES.get(platform)
    return isinstance(title_id, str) and bool(CORE_ID.match(title_id)) and (
        profile is None or bool(profile.get("title", profile["id"]).match(title_id)))


def device_path_ok(path):
    """A path on the device as SPEC.md § 8.2 wants it."""
    if not isinstance(path, str) or not path.startswith("/") or len(path.encode()) > 1024:
        return False
    parts = path[1:].split("/")
    return all(p and p not in (".", "..") and len(p.encode()) <= 255
               and not any(c in '\\:"' or ord(c) < 32 or ord(c) == 127 for c in p) for p in parts)


def manifest_digest(manifest):
    """The SHA-256 of a manifest's canonical form (SPEC.md § 8.2)."""
    entries = sorted(manifest, key=lambda e: e["path"].encode())
    canonical = "[" + ",".join('{"path":%s,"sha256":"%s","size":%d}' % (  # noqa: UP031 - the canonical bytes, spelled out
        json.dumps(e["path"], ensure_ascii=False), e["sha256"], e["size"]) for e in entries) + "]"
    return hashlib.sha256(canonical.encode()).hexdigest()


def hex_of(value, length):
    return isinstance(value, str) and len(value) == length and all(c in "0123456789abcdef" for c in value)


def https_url(value):
    return isinstance(value, str) and len(value) <= 4096 and urlsplit(value).scheme == "https" \
        and bool(urlsplit(value).netloc)


def data_file_problem(d, root):
    """Why one file of a port's requires_data breaks SPEC.md § 8.1, or None:
    {path, size?, accept?: [{sha256?, sha1?, md5?, label}], hint?, optional?},
    the path relative to data_root, exact, case included."""
    if not isinstance(d, dict):
        return "a data file is not an object"
    path = d.get("path")
    if not isinstance(path, str) or path.startswith("/") or not device_path_ok(root + path):
        return f"{str(path)[:80]!r} is not a path relative to data_root (SPEC.md § 8.2)"
    accept = d.get("accept", [])
    if not isinstance(accept, list) or len(accept) > ACCEPT_LIMIT:
        return f"{path[:80]!r}: accept is a list of {ACCEPT_LIMIT} versions at most"
    for a in accept:
        if not (isinstance(a, dict) and plain(a.get("label"), 120)):
            return f"{path[:80]!r}: each accepted version has its label"
        hashes = [k for k in HASH_FORMS if k in a]
        if not hashes or not all(hex_of(a[k], HASH_FORMS[k]) for k in hashes):
            return f"{path[:80]!r}: an accepted version gives sha256, sha1 or md5, in lower-case hex"
    if "size" in d and not is_int(d["size"]):
        return f"{path[:80]!r}: size is an integer"
    if "optional" in d and not isinstance(d["optional"], bool):
        return f"{path[:80]!r}: optional is true or false"
    if localizable(d.get("hint")) is None:
        return f"{path[:80]!r}: hint, where the user finds it, is a text, or one per language"
    return None


def clean(value, key=None):
    """A copy of a document from a file, its texts without control characters
    and within SPEC.md § 13's limits; paths, urls and hashes kept exact."""
    if isinstance(value, dict):
        return {k: clean(v, k) for k, v in value.items() if isinstance(k, str)}
    if isinstance(value, list):
        return [clean(v, key) for v in value]
    if isinstance(value, str) and key not in ("path", "data_root", "url", "source", "sha256", "sha1", "md5"):
        return plain(value, 512 if key == "name" else 120 if key == "label" else 4096) or ""
    return value


def data_files(items):
    """Every file a requires_data names, those of each alternative included."""
    for d in items:
        if isinstance(d, dict) and "one_of" in d:
            for option in d["one_of"]:
                yield from option
        else:
            yield d


def port_problem(port, areas):
    """Why a port's object breaks SPEC.md § 8.1, or None."""
    if not isinstance(port, dict):
        return "no port object"
    original, engine = port.get("original"), port.get("engine")
    if not (isinstance(original, dict) and plain(original.get("name"))):
        return "original names the game"
    if "year" in original and not (is_int(original["year"]) and 1950 <= original["year"] <= 2200):
        return "original.year is a year"
    stores = original.get("stores", [])
    if not (isinstance(stores, list) and len(stores) <= 32 and all(
            isinstance(x, dict) and isinstance(x.get("store"), str) and PLATFORM.match(x["store"])
            and https_url(x.get("url")) and ("id" not in x or plain(x["id"], 128)) for x in stores)):
        return "original.stores is a list of {store, id?, url}, an HTTPS url each"
    title = original.get("title")
    if title is not None and not (isinstance(title, dict) and PLATFORM.match(str(title.get("platform", "")))
                                  and title_id_ok(title["platform"], title.get("title_id"))):
        return "original.title is {platform, title_id}, of that platform's form"
    if not (isinstance(engine, dict) and plain(engine.get("name"))):
        return "engine names the engine"
    if "source" in engine and not https_url(engine["source"]):
        return "engine.source is an HTTPS url"
    if "license" in engine and not (isinstance(engine["license"], str) and SPDX.match(engine["license"])):
        return "engine.license is an SPDX expression"
    root = port.get("data_root")
    if not (isinstance(root, str) and root.endswith("/") and device_path_ok(root[:-1])):
        return f"data_root {str(root)[:80]!r} is not a folder's path (SPEC.md § 8.2)"
    if not any(root.startswith(a) and root != a for a in areas):
        return f"data_root {root[:80]!r} is not under " + (", ".join(areas) or "an area of this platform")
    items = port.get("requires_data", [])
    if not isinstance(items, list):
        return "requires_data is not a list"
    count = 0
    for d in items:
        if isinstance(d, dict) and "one_of" in d:
            options = d["one_of"]
            if not (isinstance(options, list) and 2 <= len(options) <= 16
                    and all(isinstance(o, list) and 1 <= len(o) <= 64 for o in options)):
                return "one_of is a list of 2 to 16 alternatives, each a list of 1 to 64 files"
            if "optional" in d and not isinstance(d["optional"], bool):
                return "a group's optional is true or false"
            files = [f for o in options for f in o]
            if any(isinstance(f, dict) and "one_of" in f for f in files):
                return "one_of does not nest"
        else:
            files = [d]
        for f in files:
            problem = data_file_problem(f, root)
            if problem:
                return problem
        count += len(files)
    if count > DATA_LIMIT:
        return f"{count} data files, above {DATA_LIMIT}"
    plain_paths = [d["path"] for d in items if "one_of" not in d]
    groups = [plain_paths] + [plain_paths + [f["path"] for f in o] for d in items if "one_of" in d for o in d["one_of"]]
    for paths in groups:
        if len(set(paths)) != len(paths):
            return "a data path twice"
    return None


def signed_bytes(doc):
    """The bytes an author signs (SPEC.md § 8.4)."""
    p = doc["package"]
    return ('{"build":%d,"id":"%s","manifest_sha256":"%s","platform":"%s","purpose":"lantern-homebrew-1",'  # noqa: UP031 - the canonical bytes, spelled out
            '"sha256":"%s"}' % (doc["build"], doc["id"], p["manifest_sha256"], doc["platform"], p["sha256"])).encode()


def build_of(version):
    """This server's own `build` for a homebrew that gives none: 1.4.2 is 1004002 (SPEC.md § 8.1)."""
    parts = re.findall(r"\d+", version or "")[:3]
    parts = [min(int(p), 999) for p in parts] + [0] * (3 - len(parts))
    return parts[0] * 1000000 + parts[1] * 1000 + parts[2]


def languages(header):
    """The tags of an Accept-Language, best first."""
    prefs = []
    for i, part in enumerate((header or "").split(",")):
        tag, _, params = part.strip().partition(";")
        q = 1.0
        m = re.search(r"q\s*=\s*([0-9.]+)", params)
        if m:
            try:
                q = float(m.group(1))
            except ValueError:
                q = 0.0
        if tag and tag != "*" and q > 0:
            prefs.append((-q, i, tag.lower()))
    return [t for _, _, t in sorted(prefs)]


def localized(value, prefs):
    """(text, language) of a text given once or per language, for the client's languages."""
    if isinstance(value, str):
        return value, None
    if not value:
        return None, None
    by_tag = {k.lower(): k for k in value}
    for tag in prefs + ["en"]:
        if tag in by_tag:
            return value[by_tag[tag]], by_tag[tag]
        primary = tag.split("-")[0]
        found = next((k for t, k in by_tag.items() if t.split("-")[0] == primary), None)
        if found:
            return value[found], found
    first = next(iter(value))
    return value[first], first


def localizable(value, limit=4096):
    """A text from a file: one string, or one per language; None when neither."""
    if isinstance(value, str):
        return plain(value, limit)
    if isinstance(value, dict):
        out = {k: plain(v, limit) for k, v in value.items() if isinstance(k, str) and 0 < len(k) <= 35}
        return {k: v for k, v in out.items() if v} or None
    return None


def image(value):
    """An image from a file: an absolute URL elsewhere, served as `external` (SPEC.md § 7.1)."""
    if isinstance(value, str) and urlsplit(value).scheme == "https" and len(value) <= 4096:
        return {"url": value, "external": True}
    return None


class Problem(Exception):
    """An error answered as application/problem+json (SPEC.md § 12)."""

    def __init__(self, status, code, title, detail=None, headers=None):
        super().__init__(title)
        self.status, self.code, self.title, self.detail = status, code, title, detail
        self.headers = headers or {}

    def document(self):
        doc = {"schema": 1, "type": f"https://lantern.boreale.dev/errors/{self.code.replace('_', '-')}",
               "title": self.title, "status": self.status, "code": self.code}
        if self.detail:
            doc["detail"] = clip(self.detail, 4096)
        return doc


def bad_request(detail):
    return Problem(400, "bad_request", "Bad request", detail)


def not_found(detail="Not here."):
    return Problem(404, "not_found", "Not found", detail)


def digest_mismatch(detail):
    return Problem(422, "digest_mismatch", "Digest mismatch", detail)


# --- State and library ----------------------------------------------------

def read_versioned(path, what):
    """A JSON file with a `schema`: None when absent, unreadable or newer than schema 1."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log(f"{path}: unreadable ({e}), ignored")
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("schema"), int):
        log(f"{path}: no schema, ignored")
        return None
    if doc["schema"] > 1:
        log(f"{path}: {what} of schema {doc['schema']}, newer than this server: treated as absent")
        return None
    return doc


def write_json(path, doc):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def title_metadata(entry):
    """The title's sheet (SPEC.md § 7.1) from a library.json entry's fields, checked."""
    meta = {}
    for key in ("publisher", "developer"):
        if plain(entry.get(key)):
            meta[key] = plain(entry[key])
    if isinstance(entry.get("genres"), list):
        genres = [g for g in dict.fromkeys(entry["genres"]) if g in GENRES]
        meta["genres"] = genres
    if isinstance(entry.get("tags"), list):
        meta["tags"] = [t for t in (plain(x, 64) for x in entry["tags"][:32]) if t]
    players = entry.get("players")
    if isinstance(players, dict):
        p = {k: players[k] for k in ("min", "max", "online_max") if is_int(players.get(k), 1 << 16) and players[k] >= 1}
        if isinstance(players.get("online"), bool):
            p["online"] = players["online"]
        meta["players"] = p
    if isinstance(entry.get("ratings"), list):
        meta["ratings"] = [{"system": r["system"], "rating": plain(r["rating"], 16)} for r in entry["ratings"]
                           if isinstance(r, dict) and isinstance(r.get("system"), str)
                           and RATING_SYSTEM.match(r["system"]) and plain(r.get("rating"), 16)]
    if isinstance(entry.get("languages"), list):
        meta["languages"] = [x for x in entry["languages"] if isinstance(x, str) and 0 < len(x) <= 35]
    for key in ("summary", "description"):
        if localizable(entry.get(key)):
            meta[key] = localizable(entry[key])
    for key in ("icon", "banner"):
        if image(entry.get(key)):
            meta[key] = image(entry[key])
    if isinstance(entry.get("screenshots"), list):
        meta["screenshots"] = [i for i in map(image, entry["screenshots"][:16]) if i]
    if image(entry.get("video")):
        meta["video"] = image(entry["video"])
    return meta


class Library:
    """Everything the server serves from its folder: apps, titles, homebrew and cheats."""

    def __init__(self, root, state_path):
        self.root = Path(root).resolve()
        self.state_path = Path(state_path)
        self.lock = threading.RLock()
        state = read_versioned(self.state_path, "state")
        # A state of a newer schema is never written over (it stays in memory only).
        self.writable = state is not None or not self.state_path.exists()
        self.state = state or {"schema": 1}
        self.state.setdefault("uid", str(uuid.uuid4()))
        self.state.setdefault("secret", secrets.token_hex(32))
        self.state.setdefault("hashes", {})
        if not isinstance(self.state.get("titles"), dict):
            self.state["titles"] = {}
        self.secret = bytes.fromhex(self.state["secret"])
        self.epoch = secrets.token_hex(4)   # since tokens do not outlive the process
        self.seq = 0
        self.journal = []                   # (seq, kind, ref, platform): kind added | removed | title | untitled
        self.floor = 0                      # tokens below it are gone
        self.apps, self.files, self.titles, self.homebrew, self.cheats = {}, {}, {}, {}, {}
        self.manifests = {}                 # (rel, size, mtime) -> a zip's manifest, or None when refused
        self.signatures = {}                # (signed bytes, key, value) -> whether it verifies
        self.cursors = OrderedDict()
        self.skipped = set()                # files not served, reported once
        self.scanned = None
        self.state_mtime = None
        self.dirty = False
        self.scan(initial=True)
        self.state_mtime = self.mtime()

    @property
    def uid(self):
        return self.state["uid"]

    def mtime(self):
        try:
            return self.state_path.stat().st_mtime_ns
        except OSError:
            return None

    def save_state(self):
        if not self.writable:
            return
        try:
            write_json(self.state_path, self.state)
            self.state_mtime = self.mtime()
        except OSError as e:
            log(f"{self.state_path}: not written ({e}); kept in memory")
            self.writable = False

    def reload_tokens(self):
        """The tokens again, when another process (--revoke) changed the state file."""
        with self.lock:
            mtime = self.mtime()
            if not self.writable or mtime is None or mtime == self.state_mtime:
                return
            self.state_mtime = mtime
            doc = read_versioned(self.state_path, "state")
            if doc is not None:
                tokens = doc.get("tokens")
                self.state["tokens"] = tokens if isinstance(tokens, dict) else {}

    def skip(self, rel, why):
        if rel not in self.skipped:
            log(f"{rel}: {why}, skipped")
            self.skipped.add(rel)

    def metadata(self):
        doc = read_versioned(self.root / "library.json", "library.json")
        entries = doc.get("apps") if doc else None
        if not isinstance(entries, list):
            return {}
        return {e["file"]: e for e in entries if isinstance(e, dict) and isinstance(e.get("file"), str)}

    def hashed(self, rel, path, st, seen):
        """A file's SHA-256, from the state's hashes while the file does not change."""
        hashes = self.state["hashes"]
        seen.add(rel)
        known = hashes.get(rel)
        if not (isinstance(known, dict) and known.get("size") == st.st_size
                and known.get("mtime_ns") == st.st_mtime_ns and isinstance(known.get("sha256"), str)):
            known = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha256_file(path)}
            hashes[rel], self.dirty = known, True
        return known["sha256"]

    def file_id(self, key):
        return "f_" + b64url(hmac.new(self.secret, b"file\0" + key, "sha256").digest()[:18])

    def identify(self, rel, entry):
        """An app's identity from its library.json entry, else (a Switch package) from its file name."""
        name, ext = Path(rel).name, Path(rel).suffix.lower()[1:]
        entry = entry or {}
        platform = entry.get("platform") if PLATFORM.match(str(entry.get("platform", ""))) else APP_EXT.get(ext)
        profile = PROFILES.get(platform)
        if profile and ext not in profile["formats"]:
            return None
        version = entry.get("version_code", entry.get("version"))
        if platform == "switch":
            found = TID_IN_NAME.search(name)
            app_id = entry.get("app_id") if ID16.match(str(entry.get("app_id", ""))) else None
            app_id = app_id or (found.group(1).upper() if found else None)
            if not app_id:
                return None
            title_id, kind = derive(app_id)
            if ID16.match(str(entry.get("title_id", ""))):
                title_id = entry["title_id"]
            if not is_int(version, 1 << 32):
                v = VERSION_IN_NAME.search(name)
                version = int(v.group(1)) if v and int(v.group(1)) < 1 << 32 else 0
        else:
            title_id = entry.get("title_id")
            if not title_id_ok(platform, title_id):
                return None
            app_id = entry.get("app_id") if title_id_ok(platform, entry.get("app_id")) else title_id
            kind = "base"
            version = version if is_int(version) else 0
        types = profile["types"] if profile else None
        if isinstance(entry.get("type"), str) and WORD.match(entry["type"]) and (types is None or entry["type"] in types):
            kind = entry["type"]
        title = entry.get("name") if isinstance(entry.get("name"), str) else \
            name.split("[")[0] if "[" in name else Path(name).stem
        app = {"platform": platform, "title_id": title_id, "app_id": app_id, "type": kind, "version_code": version,
               "name": clip(title.strip() or app_id)}
        version_name = plain(entry.get("version_name", entry.get("display_version")))
        if version_name:
            app["version_name"] = version_name
        try:
            release = date.fromisoformat(entry["release"]) if isinstance(entry.get("release"), str) else None
        except ValueError:
            release = None
        return app, release, ext

    def scan(self, initial=False):
        with self.lock:
            meta, seen, files = self.metadata(), set(), {}
            self.dirty = False
            apps, entries = {}, {}
            for path in sorted(self.root.rglob("*")):
                rel = path.relative_to(self.root).as_posix()
                parts = Path(rel).parts
                if path.suffix.lower()[1:] not in APP_EXT or any(p.startswith(".") for p in parts) \
                        or parts[0] in ("homebrew", "cheats") or not path.is_file():
                    continue
                found = self.identify(rel, meta.get(rel))
                if not found:
                    self.skip(rel, "no identity in library.json nor in its name")
                    continue
                app, release, fmt = found
                st = path.stat()
                sha = self.hashed(rel, path, st, seen)
                app_key = hmac.new(self.secret, f"app\0{rel}\0{st.st_size}\0{st.st_mtime_ns}".encode(),
                                   "sha256").digest()
                aid = "a_" + b64url(app_key[:12])
                fid = self.file_id(app_key)
                app = {"id": aid, **app, "size": st.st_size, "format": fmt, "sha256": sha,
                       "added": utc(st.st_mtime_ns), "file": f"{BASE}/v1/files/{fid}"}
                apps[aid] = {"doc": app, "path": path, "keys": {
                    "name": (app["name"].casefold(), aid),
                    "added": (-st.st_mtime_ns, aid),
                    "release": (release is None, -(release.toordinal() if release else 0), aid)},
                    "release": release}
                entries[aid] = meta.get(rel) or {}
                files[fid] = {"path": path, "size": st.st_size, "sha256": sha}
            titles = self.scan_titles(apps, entries, initial)
            homebrew = self.scan_homebrew(seen, files)
            cheats = self.scan_cheats(seen)
            hashes = self.state["hashes"]
            for rel in [r for r in hashes if r not in seen]:
                del hashes[rel]
                self.dirty = True
            if not initial:
                for aid in apps.keys() - self.apps.keys():
                    self.journal.append((self.next_seq(), "added", aid, apps[aid]["doc"]["platform"]))
                for aid in self.apps.keys() - apps.keys():
                    self.journal.append((self.next_seq(), "removed", aid, self.apps[aid]["doc"]["platform"]))
                if len(self.journal) > JOURNAL_LIMIT:
                    self.floor = self.journal[-JOURNAL_LIMIT - 1][0]
                    del self.journal[:-JOURNAL_LIMIT]
            self.apps, self.files, self.titles, self.homebrew, self.cheats = apps, files, titles, homebrew, cheats
            self.scanned = time.monotonic()
            if self.dirty:
                self.save_state()

    def next_seq(self):
        self.seq += 1
        return self.seq

    def scan_titles(self, apps, entries, initial):
        """The titles of the apps (SPEC.md § 7): a name, a release, the entries' metadata, and when it changed."""
        groups = {}
        for e in apps.values():
            groups.setdefault((e["doc"]["platform"], e["doc"]["title_id"]), []).append(e)
        known, titles = self.state["titles"], {}
        for (platform, title_id), mine in groups.items():
            mine.sort(key=lambda e: (e["doc"]["type"] != "base", e["keys"]["name"]))
            meta = {}
            for e in reversed(mine):      # the base's fields last, so they win
                meta.update(title_metadata(entries[e["doc"]["id"]]))
            release = min((e["release"] for e in mine if e["release"]), default=None)
            name = mine[0]["doc"]["name"]
            digest = hashlib.sha256(json.dumps([name, str(release), meta], sort_keys=True).encode()).hexdigest()
            key = f"{platform}/{title_id}"
            record = known.get(key)
            if not (isinstance(record, dict) and record.get("digest") == digest and isinstance(record.get("updated"), str)):
                record = {"digest": digest, "updated": now_utc()}
                known[key], self.dirty = record, True
                if not initial:
                    self.journal.append((self.next_seq(), "title", key, platform))
            titles[key] = {"platform": platform, "title_id": title_id, "name": name, "release": release,
                           "meta": meta, "updated": record["updated"]}
        for key in [k for k in known if k not in titles]:
            del known[key]
            self.dirty = True
            if not initial:
                self.journal.append((self.next_seq(), "untitled", key, key.split("/", 1)[0]))
        return titles

    # Homebrew (SPEC.md § 8).

    def scan_homebrew(self, seen, files):
        root = self.root / "homebrew"
        out = {}
        if not root.is_dir():
            return out
        folders = {}
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(self.root)
            if any(p.startswith(".") for p in rel.parts) or not path.is_file():
                continue
            if path.suffix.lower()[1:] in HOMEBREW_EXT:
                folders.setdefault(path.parent, []).append(path)
        for folder, packages in folders.items():
            meta = read_versioned(folder / "homebrew.json", "homebrew.json")
            if meta is None and (folder / "homebrew.json").exists():
                for path in packages:   # a homebrew.json it cannot read says nothing it may serve
                    self.skip(path.relative_to(self.root).as_posix(), "its homebrew.json is newer or unreadable")
                continue
            for path in packages:
                mine = meta if meta and (meta.get("file") == path.name
                                         or (not meta.get("file") and len(packages) == 1)) else None
                entry = self.homebrew_entry(path, mine or {}, seen, files)
                if entry is None:
                    continue
                key = (entry["doc"]["platform"], entry["doc"]["id"])
                if key in out:
                    self.skip(path.relative_to(self.root).as_posix(), f"a second homebrew {key[1]} on {key[0]}")
                    continue
                out[key] = entry
        return out

    def homebrew_entry(self, path, meta, seen, files):
        rel = path.relative_to(self.root).as_posix()
        ext = path.suffix.lower()[1:]
        st = path.stat()
        platform = meta.get("platform") if PLATFORM.match(str(meta.get("platform", ""))) else HOMEBREW_EXT[ext]
        profile = PROFILES.get(platform)
        if profile is None or ext not in profile["homebrew"]:
            self.skip(rel, f"no {ext} homebrew on {platform}")
            return None
        info = {}
        if ext == "nro":
            with path.open("rb") as f:
                info = nro.read_nro(f, st.st_size) or {}
        hid = meta.get("id") if HOMEBREW_ID.match(str(meta.get("id", ""))) else \
            "local." + (re.sub(r"[^a-z0-9]+", "-", path.stem.lower()).strip("-") or "homebrew")
        name = plain(meta.get("name")) or info.get("name") or path.stem
        version = plain(meta.get("version")) or info.get("version") or "0"
        build = meta["build"] if is_int(meta.get("build")) else build_of(version)
        sha = self.hashed(rel, path, st, seen)
        key = hmac.new(self.secret, f"homebrew\0{rel}\0{st.st_size}\0{st.st_mtime_ns}".encode(), "sha256").digest()
        fid = self.file_id(key)
        package = {"format": ext, "file": f"{BASE}/v1/files/{fid}", "size": st.st_size, "sha256": sha}
        place = profile["homebrew"][ext]
        if place == "system":
            manifest = package["manifest"] = []     # the platform's installer installs it (SPEC.md § 8.2)
        elif place is None:
            manifest = self.zip_manifest(path, rel, st)
            if manifest is None:
                return None
            package["manifest"] = manifest
        else:
            target = meta.get("path") if device_path_ok(meta.get("path")) else place.format(id=hid, file=path.name)
            if not device_path_ok(target):
                self.skip(rel, f"no place for it on the device ({target})")
                return None
            package["path"] = target
            manifest = [{"path": target, "size": st.st_size, "sha256": sha}]
        roots = [r.format(id=hid) for r in profile["roots"]]
        outside = [m["path"] for m in manifest if not any(m["path"].startswith(r) for r in roots)]
        if outside:
            self.skip(rel, f"writes outside {platform}'s roots ({outside[0]})")
            return None
        package["manifest_sha256"] = manifest_digest(manifest)
        doc = {"id": hid, "platform": platform, "name": name, "category": meta.get("category")
               if meta.get("category") in CATEGORIES else "other", "version": version, "build": build}
        author = plain(meta.get("author")) or info.get("author")
        if author:
            doc["author"] = author
        for k, limit in (("license", 256), ("source", 4096)):
            if plain(meta.get(k), limit):
                doc[k] = plain(meta[k], limit)
        if image(meta.get("icon")):
            doc["icon"] = image(meta["icon"])
        if isinstance(meta.get("screenshots"), list):
            doc["screenshots"] = [i for i in map(image, meta["screenshots"][:16]) if i]
        requires = meta.get("requires")
        if isinstance(requires, dict) and plain(requires.get("text"), 4096):
            doc["requires"] = {"text": plain(requires["text"], 4096)}
            if isinstance(requires.get("min"), dict):
                doc["requires"]["min"] = {k: v for k, v in requires["min"].items()
                                          if isinstance(k, str) and WORD.match(k) and isinstance(v, str) and DOTTED.match(v)}
            if isinstance(requires.get("homebrew"), list):
                doc["requires"]["homebrew"] = [{"id": h["id"], "min_build": h["min_build"]} for h in requires["homebrew"]
                                               if isinstance(h, dict) and HOMEBREW_ID.match(str(h.get("id", "")))
                                               and is_int(h.get("min_build"))]
        kind = meta.get("kind")
        doc["kind"] = kind if kind in KINDS else "app"     # SPEC.md § 8.1: an unknown kind is an app
        arch = meta.get("arch")
        if arch is not None:
            if platform in ONE_ARCH:
                self.skip(rel, f"{platform} has one architecture: no arch (Annex A)")
                return None
            if not (isinstance(arch, list) and 1 <= len(arch) <= 8 and len(set(arch)) == len(arch)
                    and all(isinstance(a, str) and ARCH.match(a) for a in arch)):
                self.skip(rel, f"arch is a list of architectures, such as aarch64 ({str(arch)[:40]})")
                return None
            package["arch"] = arch
        if meta.get("signer_sha256") is not None:
            if not (isinstance(meta["signer_sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", meta["signer_sha256"])):
                self.skip(rel, "signer_sha256 is a lower-case hex SHA-256")
                return None
            package["signer_sha256"] = meta["signer_sha256"]
        if meta.get("assets_license") is not None:
            if not (isinstance(meta["assets_license"], str) and SPDX.match(meta["assets_license"])):
                self.skip(rel, "assets_license is an SPDX expression")
                return None
            package["assets_license"] = meta["assets_license"]
        if meta.get("system_id") is not None:
            if not (isinstance(meta["system_id"], str) and CORE_ID.match(meta["system_id"])):
                self.skip(rel, "system_id is an id of the platform's form")
                return None
            doc["system_id"] = meta["system_id"]
        if doc["kind"] == "port":
            port = meta.get("port")
            problem = port_problem(port, profile.get("areas", ()))
            if problem:
                self.skip(rel, f"port: {problem}")
                return None
            shipped = {m["path"] for m in manifest}
            served = {sha} | {m["sha256"] for m in manifest}
            for f in data_files(port.get("requires_data", [])):
                if port["data_root"] + f["path"] in shipped or any(a.get("sha256") in served for a in f.get("accept", [])):
                    self.skip(rel, "it holds a file the user brings from their own copy (requires_data)")
                    return None
            doc["port"] = clean(port)       # a copy; its hints are localized when served
            if doc["port"]["assets"] not in ASSETS:
                doc["port"]["assets"] = "user_owned"    # SPEC.md § 8.6: an unknown one reads so
        mtimes = [st.st_mtime_ns]
        try:
            mtimes.append((path.parent / "homebrew.json").stat().st_mtime_ns)
        except OSError:
            pass
        doc["updated"] = utc(max(mtimes))
        doc["package"] = package
        signature = meta.get("signature")
        if isinstance(signature, dict) and signature.get("alg") == "ed25519" \
                and re.fullmatch(r"[A-Za-z0-9+/]{43}=", str(signature.get("public_key", ""))) \
                and re.fullmatch(r"[A-Za-z0-9+/]{86}==", str(signature.get("value", ""))):
            signature = {"alg": "ed25519", "public_key": signature["public_key"], "value": signature["value"]}
            if not self.verified(signed_bytes(doc), signature):
                self.skip(rel, "its signature does not verify (SPEC.md § 8.4)")
                return None
            doc["signature"] = signature
        elif signature is not None:
            self.skip(rel, "its signature is not an ed25519 one")
            return None
        texts = {k: localizable(meta.get(k)) for k in ("summary", "description") if localizable(meta.get(k))}
        files[fid] = {"path": path, "size": st.st_size, "sha256": sha}
        return {"doc": doc, "texts": texts, "keys": {"name": (name.casefold(), platform, hid)}}

    def verified(self, message, signature):
        """Whether an author's signature verifies, remembered (SPEC.md § 8.4)."""
        memo = (message, signature["public_key"], signature["value"])
        if memo not in self.signatures:
            public, value = base64.b64decode(signature["public_key"]), base64.b64decode(signature["value"])
            self.signatures[memo] = ed25519.verify(public, message, value)
            if len(self.signatures) > 10000:
                self.signatures.pop(next(iter(self.signatures)))
        return self.signatures[memo]

    def zip_manifest(self, path, rel, st):
        """A zip's manifest: every file in it, at "/" + its name; None when one breaks SPEC.md § 8.2."""
        memo = (rel, st.st_size, st.st_mtime_ns)
        if memo in self.manifests:
            return self.manifests[memo]
        manifest = None
        try:
            with zipfile.ZipFile(path) as z:
                members = [i for i in z.infolist() if not i.is_dir()]
                bad = next((i.filename for i in members if not device_path_ok("/" + i.filename)), None)
                lower = [("/" + i.filename).casefold() for i in members]
                if len(members) > MANIFEST_LIMIT:
                    self.skip(rel, f"{len(members)} files, above {MANIFEST_LIMIT}")
                elif bad is not None:
                    self.skip(rel, f"a path SPEC.md § 8.2 refuses ({bad!r})")
                elif len(set(lower)) != len(lower):
                    self.skip(rel, "two paths that differ only by case")
                else:
                    manifest = []
                    for i in members:
                        h, size = hashlib.sha256(), 0
                        with z.open(i) as f:
                            while chunk := f.read(CHUNK):
                                h.update(chunk)
                                size += len(chunk)
                        manifest.append({"path": "/" + i.filename, "size": size, "sha256": h.hexdigest()})
                    manifest.sort(key=lambda e: e["path"].encode())
        except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError, RuntimeError, EOFError) as e:
            self.skip(rel, f"not a zip this server can read ({e})")
        self.manifests = {k: v for k, v in self.manifests.items() if k[0] != rel}
        self.manifests[memo] = manifest
        return manifest

    # Cheats (SPEC.md § 10).

    def scan_cheats(self, seen):
        root = self.root / "cheats"
        out = {}
        if not root.is_dir():
            return out
        for path in sorted(root.rglob("*.txt")):
            parts = path.relative_to(root).parts
            rel = path.relative_to(self.root).as_posix()
            if any(p.startswith(".") for p in parts) or not path.is_file():
                continue
            if len(parts) == 4 and PLATFORM.match(parts[0]):
                platform, title_id, build_id = parts[:3]
            elif len(parts) == 3:
                platform, (title_id, build_id) = "switch", parts[:2]
            else:
                self.skip(rel, "not cheats/[<platform>/]<title id>/<build id>/<source>.txt")
                continue
            profile = PROFILES.get(platform)
            pattern = (profile or {}).get("build_id", BUILD_ID)
            if not title_id_ok(platform, title_id) or not pattern.match(build_id):
                self.skip(rel, "not a title id and a build id of its platform")
                continue
            st = path.stat()
            if st.st_size > CHEAT_LIMIT:
                self.skip(rel, f"above {CHEAT_LIMIT} bytes")
                continue
            cid = "cs_" + b64url(hmac.new(self.secret, b"cheat\0" + rel.encode(), "sha256").digest()[:12])
            out[cid] = {"path": path, "doc": {
                "id": cid, "platform": platform, "title_id": title_id, "build_id": build_id,
                "source": clip(path.stem.replace("_", " ")), "updated": utc(st.st_mtime_ns),
                "size": st.st_size, "sha256": self.hashed(rel, path, st, seen)}}
        return out

    def platforms(self):
        with self.lock:
            return sorted({e["doc"]["platform"] for e in self.apps.values()} | {p for p, _ in self.homebrew}
                          | {e["doc"]["platform"] for e in self.cheats.values()})

    def refresh(self, every):
        if time.monotonic() - self.scanned >= every:
            self.scan()

    # Pages (SPEC.md § 6.2): sorted by key, ties broken by id; a cursor keeps
    # the last key read, so a page after a change neither skips nor repeats.

    def page(self, entries, sort, size, cursor, scope, view=lambda e: e["doc"]):
        with self.lock:
            if cursor:
                if not cursor.startswith("c_"):
                    raise bad_request("Unknown cursor.")
                kept = self.cursors.get(cursor)
                if kept is None:
                    raise Problem(410, "gone", "Cursor expired", "Read the list again from its start.")
                if kept[0] != (sort, scope):
                    raise bad_request("This cursor belongs to another listing.")
                after = kept[1]
            ordered = sorted(entries, key=lambda e: e["keys"][sort])
            if cursor:
                ordered = [e for e in ordered if e["keys"][sort] > after]
            items, more = ordered[:size], len(ordered) > size
            nxt = None
            if more:
                # The same page always gives the same cursor, so a page keeps its ETag.
                last = items[-1]["keys"][sort]
                nxt = "c_" + b64url(hmac.new(self.secret, json.dumps([sort, scope, last]).encode(), "sha256").digest()[:12])
                self.cursors[nxt] = ((sort, scope), last)
                self.cursors.move_to_end(nxt)
                while len(self.cursors) > CURSOR_LIMIT:
                    self.cursors.popitem(last=False)
            total = len(entries)
        return {"schema": 1, "items": [view(e) for e in items], "total": total, "next": nxt}

    def missing(self, platform, installed, want):
        """SPEC.md § 6.3, on one platform, from the console's installed apps."""
        with self.lock:
            apps = [e for e in self.apps.values() if e["doc"]["platform"] == platform]
            replaces = PROFILES.get(platform, {}).get("replaces", False)
            by_app = {e["doc"]["app_id"]: e["doc"] for e in apps}
            have = {}
            for item in installed:
                known = by_app.get(item["app_id"])
                if known:
                    title, kind = known["title_id"], known["type"]
                elif platform == "switch" and ID16.match(item["app_id"]):
                    title, kind = derive(item["app_id"])
                else:
                    continue    # a game this server does not know
                if kind in ("base", "update"):
                    have[title] = max(have.get(title, -1), item["version_code"])
            ids = {i["app_id"] for i in installed}
            out = []
            for title, version in have.items():
                mine = [e for e in apps if e["doc"]["title_id"] == title]
                if replaces:
                    updates = [e for e in mine if e["doc"]["type"] == "base" and e["doc"]["app_id"] in ids]
                else:
                    updates = [e for e in mine if e["doc"]["type"] == "update"]
                newest = max((e["doc"]["version_code"] for e in updates), default=-1)
                if "update" in want and newest > version:
                    out += [e for e in updates if e["doc"]["version_code"] == newest]
                if "dlc" in want:
                    out += [e for e in mine if e["doc"]["type"] == "dlc" and e["doc"]["app_id"] not in ids]
            if "base" in want:
                out += [e for e in apps if e["doc"]["type"] == "base" and e["doc"]["title_id"] not in have]
            return out

    def since(self, prefix, since):
        """The journal's entries after a `since` token of /v1/changes (s_) or /v1/titles/changes (t_)."""
        current = f"{prefix}_{self.epoch}_{self.seq}"
        if since is None:
            return None, current
        m = re.fullmatch(prefix + r"_([0-9a-f]{8})_(\d+)", since)
        if not m:
            raise bad_request("Unknown since token.")
        seq = int(m.group(2))
        if m.group(1) != self.epoch or seq < self.floor or seq > self.seq:
            raise Problem(410, "gone", "Token too old", "Read them all again.")
        return [j for j in self.journal if j[0] > seq], current

    def changes(self, since, platform):
        with self.lock:
            journal, current = self.since("s", since)
            if journal is None:
                return {"schema": 1, "added": [], "removed": [], "since": current}
            added, removed = set(), set()
            for _, kind, aid, p in journal:
                if kind in ("added", "removed") and (platform is None or p == platform):
                    (added if kind == "added" else removed).add(aid)
            docs = sorted((self.apps[a] for a in added if a in self.apps), key=lambda e: e["keys"]["name"])
            return {"schema": 1, "added": [e["doc"] for e in docs],
                    "removed": sorted(a for a in removed if a not in self.apps), "since": current}

    def title_changes(self, since, platform, prefs):
        with self.lock:
            journal, current = self.since("t", since)
            doc = {"schema": 1, "titles": [], "removed": [], "since": current, "more": False}
            if journal is None:
                return doc
            keys = {key for _, kind, key, p in journal
                    if kind in ("title", "untitled") and (platform is None or p == platform)}
            doc["titles"] = [self.title_doc(k, prefs) for k in sorted(keys) if k in self.titles]
            doc["removed"] = [dict(zip(("platform", "title_id"), k.split("/", 1))) for k in sorted(keys)
                              if k not in self.titles]
            return doc

    def title_doc(self, key, prefs):
        t = self.titles[key]
        doc = {"platform": t["platform"], "title_id": t["title_id"], "name": t["name"], "updated": t["updated"]}
        if t["release"]:
            doc["release"] = t["release"].isoformat()
        meta = t["meta"]
        for k in ("publisher", "developer", "genres", "tags", "players", "ratings", "languages", "icon", "banner",
                  "screenshots", "video"):
            if k in meta:
                doc[k] = meta[k]
        for k in ("summary", "description"):
            if k in meta:
                text, language = localized(meta[k], prefs)
                doc[k] = text
                if language and "language" not in doc:
                    doc["language"] = language
        return doc

    def find(self, table, ident, platform):
        """The one entry of `table` (keyed (platform, id)) named `ident`; 400 when several platforms have it."""
        with self.lock:
            found = [v for (p, i), v in table.items() if i == ident and (platform is None or p == platform)]
        if not found:
            raise not_found("Not on this server" + (f" for {platform}." if platform else "."))
        if len(found) > 1:
            raise bad_request("Several platforms have it: name one (Lantern-Platform).")
        return found[0]


# --- Save backups -----------------------------------------------------------

class Saves:
    """Save backups (SPEC.md § 9) in a folder: index.json (schema 1: every
    backup and open upload, with the account it belongs to), archives/ and
    uploads/. An index of a newer schema, or one this server cannot read,
    makes the family unavailable, and is never written over."""

    PUBLIC = ("platform", "title_id", "save_id", "created", "size", "sha256", "kind", "game_version_code",
              "profile", "slot", "note", "device")

    def __init__(self, folder, body=SAVE_BODY, size=SAVE_SIZE, chunk=SAVE_CHUNK, kept=SAVES_KEPT,
                 hours=UPLOAD_HOURS):
        self.folder = Path(folder)
        self.body, self.size, self.chunk, self.kept, self.hours = body, size, chunk, kept, hours
        self.lock = threading.RLock()
        self.path = self.folder / "index.json"
        doc = read_versioned(self.path, "saves index")
        self.available = doc is not None or not self.path.exists()
        self.index = doc or {"schema": 1}
        if not isinstance(self.index.get("saves"), list):
            self.index["saves"] = []
        if not isinstance(self.index.get("uploads"), dict):
            self.index["uploads"] = {}

    def write(self):
        if not self.available:
            return
        self.folder.mkdir(parents=True, exist_ok=True)
        write_json(self.path, self.index)

    def archive(self, save_id):
        return self.folder / "archives" / f"{save_id}.zip"

    def part(self, upload_id):
        return self.folder / "uploads" / f"{upload_id}.part"

    @classmethod
    def public(cls, entry):
        return {k: entry[k] for k in cls.PUBLIC if k in entry}

    def mine(self, user):
        return [e for e in self.index["saves"] if isinstance(e, dict) and e.get("user") == user
                and isinstance(e.get("save_id"), str) and isinstance(e.get("created"), str)]

    def list(self, user, platform=None, title_id=None):
        with self.lock:
            found = [e for e in self.mine(user) if (platform is None or e.get("platform") == platform)
                     and (title_id is None or e.get("title_id") == title_id)]
            order = {id(e): i for i, e in enumerate(self.index["saves"])}
            found.sort(key=lambda e: (e.get("platform", ""), e.get("title_id", ""), e["created"], order[id(e)]))
            # Newest first per title.
            out, group = [], []
            for e in found:
                if group and (group[-1].get("platform"), group[-1].get("title_id")) != (e.get("platform"), e.get("title_id")):
                    out += reversed(group)
                    group = []
                group.append(e)
            return [self.public(e) for e in out + list(reversed(group))]

    def find(self, user, title_id, save_id, platform):
        """The backup `save_id` of `title_id`; None when there is none. Its id is
        the server's own, so it never names backups on two platforms."""
        with self.lock:
            return next((e for e in self.mine(user) if e["save_id"] == save_id and e.get("title_id") == title_id
                         and (platform is None or e.get("platform") == platform)), None)

    def add(self, user, source, sha256, size, fields):
        """Keeps the archive at `source` as a new backup, then drops the oldest beyond `kept`."""
        with self.lock:
            save_id = "s_" + secrets.token_urlsafe(9)
            target = self.archive(save_id)
            target.parent.mkdir(parents=True, exist_ok=True)
            source.replace(target)
            entry = {"user": user, **fields, "save_id": save_id, "created": now_utc(), "size": size, "sha256": sha256}
            self.index["saves"].append(entry)
            same = [e for e in self.mine(user) if e.get("platform") == entry["platform"]
                    and e.get("title_id") == entry["title_id"]]
            for old in same[:max(0, len(same) - self.kept)]:
                self.drop(old)
            self.write()
            return self.public(entry)

    def drop(self, entry):
        with self.lock:
            self.index["saves"] = [e for e in self.index["saves"] if e is not entry]
            try:
                self.archive(entry["save_id"]).unlink()
            except OSError:
                pass

    def delete(self, entry):
        with self.lock:
            self.drop(entry)
            self.write()

    # Resumable uploads (SPEC.md § 9.3).

    def purge(self):
        now = datetime.now(timezone.utc)
        for uid, s in list(self.index["uploads"].items()):
            try:
                gone = datetime.fromisoformat(str(s.get("expires")).replace("Z", "+00:00")) <= now
            except ValueError:
                gone = True
            if gone:
                self.abandon(uid, write=False)

    def open(self, user, fields, size, sha256):
        with self.lock:
            self.purge()
            uid = "u_" + secrets.token_urlsafe(18)
            expires = (datetime.now(timezone.utc) + timedelta(hours=self.hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
            self.index["uploads"][uid] = {"user": user, **fields, "size": size, "sha256": sha256,
                                          "expires": expires}
            part = self.part(uid)
            part.parent.mkdir(parents=True, exist_ok=True)
            part.write_bytes(b"")
            self.write()
            return uid, expires

    def session(self, uid, user):
        with self.lock:
            self.purge()
            s = self.index["uploads"].get(uid)
            return s if isinstance(s, dict) and s.get("user") == user else None

    def offset(self, uid):
        try:
            return self.part(uid).stat().st_size
        except OSError:
            return 0

    def append(self, uid, offset, data):
        """The new offset; a Problem when `offset` is not the server's (409) or goes past the size."""
        with self.lock:
            s = self.index["uploads"][uid]
            have = self.offset(uid)
            if offset != have:
                raise Problem(409, "conflict", "Wrong offset", f"This upload is at {have}.",
                              {"Upload-Offset": str(have)})
            if have + len(data) > s["size"]:
                raise bad_request(f"This chunk goes past the upload's size, {s['size']} bytes.")
            with self.part(uid).open("ab") as f:
                f.write(data)
            return have + len(data)

    def finish(self, uid):
        """The save entry once the whole archive is in and matches its sha256; 422 otherwise."""
        with self.lock:
            s = self.index["uploads"].pop(uid)
            part = self.part(uid)
            try:
                if sha256_file(part) != s["sha256"]:
                    raise digest_mismatch("The archive's SHA-256 is not the one announced; it was discarded.")
                if not zipfile.is_zipfile(part):
                    raise bad_request("A save is a zip archive; this one was discarded.")
                fields = {k: s[k] for k in self.PUBLIC if k in s and k not in ("size", "sha256")}
                return self.add(s["user"], part, s["sha256"], s["size"], fields)
            finally:
                if part.exists():
                    part.unlink()
                self.write()

    def abandon(self, uid, write=True):
        with self.lock:
            self.index["uploads"].pop(uid, None)
            try:
                self.part(uid).unlink()
            except OSError:
                pass
            if write:
                self.write()


# --- Accounts -----------------------------------------------------------

def hash_password(password, iterations=600000):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2-sha256${iterations}${b64url(salt)}${b64url(digest)}"


def check_password(password, stored):
    try:
        algo, iterations, salt, digest = stored.split("$")
        assert algo == "pbkdf2-sha256"
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), unb64url(salt), int(iterations))
        return hmac.compare_digest(got, unb64url(digest))
    except (ValueError, AssertionError):
        return False


def unauthorized(challenge, detail):
    return Problem(401, "unauthorized", "Unauthorized", detail, {"WWW-Authenticate": challenge})


CHALLENGE = 'Bearer realm="lantern"'


class Accounts:
    """users.json (SPEC.md § 5): who may sign in on /pair, and with which scopes."""

    def __init__(self, path):
        self.public, self.users = True, {}
        self.pairing = path is not None     # a server with accounts pairs (a private one MUST)
        if path is None:
            return
        doc = read_versioned(Path(path), "users file")
        self.public = bool(doc and doc.get("public"))   # unreadable or newer: private, nobody signs in
        for u in (doc or {}).get("users", []):
            if isinstance(u, dict) and isinstance(u.get("name"), str) and isinstance(u.get("password"), str):
                self.users[u["name"]] = u

    def anonymous(self):
        return {"state": "anonymous", "scopes": ["library"] if self.public else []}

    def scopes(self, user):
        return [s for s in user.get("scopes", []) if s in SCOPES]

    def sign_in(self, name, password):
        """The user, when the password is theirs; None otherwise."""
        user = self.users.get(name)
        ok = check_password(password, user["password"] if user else NO_USER)
        return user if ok and user else None

    def resolve(self, header, tokens):
        """(the caller's account, its token's record) from its bearer token, or a 401 Problem (SPEC.md § 5.1)."""
        if not header:
            return self.anonymous(), None
        scheme, _, value = header.strip().partition(" ")
        if scheme.lower() != "bearer" or not value.strip():
            raise unauthorized(CHALLENGE, "Send a token from pairing: Authorization: Bearer <token>.")
        record = tokens.find(value.strip())
        user = self.users.get(record["user"]) if record else None
        if user is None:
            raise unauthorized(CHALLENGE + ', error="invalid_token"', "Unknown, revoked or expired token.")
        mine = self.scopes(user)
        scopes = [s for s in record.get("scopes", []) if s in mine]
        state = "frozen" if user.get("state") == "frozen" else "active"
        return {"name": clip(user["name"]), "state": state, "scopes": scopes}, record


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Tokens:
    """Device tokens (SPEC.md § 5.1), hashed, in the state file under "tokens":
    {sha256 of the token: {"user", "device", "scopes", "created", "expires"?}}."""

    def __init__(self, store):
        self.store = store      # the Library: its state, lock and state file

    def table(self):
        tokens = self.store.state.get("tokens")
        if not isinstance(tokens, dict):
            tokens = self.store.state["tokens"] = {}
        return tokens

    def issue(self, user, device, scopes, lifetime=None):
        token = "et_" + secrets.token_urlsafe(32)   # 256 bits
        record = {"user": user, "device": device, "scopes": list(scopes), "created": now_utc()}
        if lifetime:
            record["expires"] = now_utc(lifetime)
        with self.store.lock:
            self.store.reload_tokens()
            self.table()[token_hash(token)] = record
            self.store.save_state()
        return token

    def find(self, token):
        self.store.reload_tokens()
        with self.store.lock:
            record = self.table().get(token_hash(token))
        if not isinstance(record, dict) or not isinstance(record.get("user"), str):
            return None
        expires = record.get("expires")
        if expires is not None:
            try:
                if datetime.fromisoformat(str(expires).replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                    return None
            except ValueError:
                return None     # an expiry it cannot read: not trusted
        return record


class Pairing:
    """Pairings waiting for the user (SPEC.md § 5.2), in memory: a code lives
    PAIR_EXPIRES seconds, a token is collected once."""

    def __init__(self, tokens, accounts, interval=PAIR_INTERVAL, expires=PAIR_EXPIRES, lifetime=None):
        self.tokens, self.accounts = tokens, accounts
        self.interval, self.expires, self.lifetime = interval, expires, lifetime
        self.pending, self.lock = {}, threading.Lock()

    def purge(self):
        now = time.monotonic()
        for pid in [p for p, e in self.pending.items() if e["until"] <= now]:
            del self.pending[pid]

    def start(self, device, scopes):
        with self.lock:
            self.purge()
            if len(self.pending) >= PENDING_LIMIT:
                raise slow_down(self.interval, "Too many pairings are waiting; try again later.")
            codes = {e["code"] for e in self.pending.values()}
            while (code := "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_SYMBOLS))) in codes:
                pass
            pid = "p_" + secrets.token_urlsafe(24)  # 192 bits: whoever has it collects the token
            entry = {"pid": pid, "code": code, "device": device, "scopes": scopes, "state": "pending",
                     "until": time.monotonic() + self.expires, "polled": None, "interval": self.interval}
            self.pending[pid] = entry
            return entry

    @staticmethod
    def shown(code):
        return "-".join(code[i:i + 4] for i in range(0, len(code), 4))

    def by_code(self, typed):
        code = re.sub(r"[\s-]", "", typed or "").upper()
        with self.lock:
            self.purge()
            return next((e for e in self.pending.values()
                         if e["state"] == "pending" and hmac.compare_digest(e["code"], code)), None)

    def by_nonce(self, nonce):
        with self.lock:
            self.purge()
            return next((e for e in self.pending.values() if e["state"] == "pending" and e.get("nonce")
                         and hmac.compare_digest(e["nonce"], nonce or "")), None)

    def grant(self, entry, user):
        """The scopes the user may approve: those asked for that the account has."""
        mine = self.accounts.scopes(user)
        return [s for s in entry["scopes"] if s in mine]

    def prepare(self, entry, user):
        """Ties the code to the signed-in user until they approve or refuse it on /pair."""
        with self.lock:
            entry["user"], entry["nonce"] = user["name"], secrets.token_urlsafe(24)
            return entry["nonce"]

    def approve(self, entry, user_name):
        user = self.accounts.users[user_name]
        scopes = self.grant(entry, user)
        token = self.tokens.issue(user_name, entry["device"], scopes, self.lifetime)
        with self.lock:
            entry.update(state="approved", token=token, granted=scopes, nonce=None)

    def refuse(self, entry):
        with self.lock:
            entry.update(state="refused", nonce=None)

    def poll(self, pid):
        """The token document once approved, None while waiting; 410 or 429 as a Problem."""
        with self.lock:
            self.purge()
            entry = self.pending.get(pid)
            if entry is None:
                raise Problem(410, "gone", "Pairing gone", "Refused, expired, already collected or unknown.")
            now = time.monotonic()
            if entry["polled"] is not None and now - entry["polled"] < entry["interval"] * 0.8:
                entry["polled"] = now
                raise slow_down(entry["interval"], f"Poll every {entry['interval']} seconds.")
            entry["polled"] = now
            if entry["state"] == "refused":
                del self.pending[pid]
                raise Problem(410, "gone", "Pairing refused", "The user refused this device.")
            if entry["state"] != "approved":
                return None
            del self.pending[pid]
        doc = {"schema": 1, "token": entry["token"], "scopes": entry["granted"]}
        if self.lifetime:
            doc["expires"] = int(self.lifetime)
        return doc


# --- HTTP ---------------------------------------------------------------

def content_digest(header):
    """The SHA-256 a Content-Digest (RFC 9530) gives, as bytes; None without one."""
    m = re.search(r"(?:^|,)\s*sha-256\s*=\s*:([A-Za-z0-9+/=]*):", header or "")
    if not m:
        return None
    try:
        raw = base64.b64decode(m.group(1), validate=True)
    except ValueError:
        raw = b""
    if len(raw) != 32:
        raise bad_request("Content-Digest's sha-256 is not a SHA-256.")
    return raw


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"LanternReference/{VERSION}"

    def version_string(self):
        return self.server_version

    def log_message(self, fmt, *args):
        if not self.server.quiet:
            super().log_message(fmt, *args)

    # Dispatch. Every route's family decides who may call it.

    def handle_any(self, method):
        self.method, self.head, self.began = method, method == "HEAD", False
        self.authenticated = bool(self.headers.get("Authorization"))
        self.length, self.body_read, self.body_data = 0, False, b""
        self.account, self.record = None, None
        try:
            self.length = self.content_length()
            url = urlsplit(self.path)
            path = unquote(url.path)
            query = {k: v[-1] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
            self.server.library.refresh(self.server.rescan)
            self.route(method, path, query)
        except Problem as p:
            self.send_doc(p.status, p.document(), p.headers, problem=True)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:  # noqa: BLE001 - any bug of this server answers 500
            # A bug of this server: logged, answered as SPEC.md § 12 wants,
            # unless the reply had already begun.
            self.log_error("%s", traceback.format_exc())
            self.close_connection = True
            if not self.began:
                problem = Problem(500, "internal", "Internal error", "The server failed; try again later.")
                self.send_doc(500, problem.document(), problem=True)
        if self.length and not self.body_read and not self.close_connection:
            # A body nobody read: dropped, so the connection can serve the next request.
            if self.length <= DRAIN_LIMIT:
                try:
                    self.rfile.read(self.length)
                except OSError:
                    self.close_connection = True
            else:
                self.close_connection = True

    def do_GET(self):
        self.handle_any("GET")

    def do_HEAD(self):
        self.handle_any("HEAD")

    def do_POST(self):
        self.handle_any("POST")

    def do_PUT(self):
        self.handle_any("PUT")

    def do_DELETE(self):
        self.handle_any("DELETE")

    def do_PATCH(self):
        self.handle_any("PATCH")

    def content_length(self):
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            raise bad_request("Send a Content-Length, not a chunked body.")
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length < 0:
                raise ValueError
        except ValueError:
            self.close_connection = True
            raise bad_request("Bad Content-Length.") from None
        return length

    def body(self, limit=BODY_LIMIT):
        """The request's body, read once, at most `limit` bytes (413 above)."""
        if self.body_read:
            return self.body_data
        if self.length > limit:
            self.close_connection = self.length > DRAIN_LIMIT
            raise Problem(413, "too_large", "Too large", f"At most {limit} bytes here.")
        data = self.rfile.read(self.length) if self.length else b""
        self.body_read, self.body_data = True, data
        if len(data) < self.length:     # the connection was cut: nothing of it is kept
            self.close_connection = True
            raise ConnectionResetError("the body was cut")
        return data

    # Routes: the path below <base>/v1/, "{}" one segment; the first match wins.
    ROUTES = (
        ("pairing", ("POST",), "pairing", "pair_start"),
        ("pairing/{}", ("GET",), "pairing", "pair_poll"),
        ("apps", ("GET", "HEAD"), "library", "apps"),
        ("apps/missing", ("POST",), "library", "missing"),
        ("changes", ("GET", "HEAD"), "changes", "changes"),
        ("titles", ("GET", "HEAD"), "titles", "titles"),
        ("titles/changes", ("GET", "HEAD"), "titles", "title_changes"),
        ("titles/{}", ("GET", "HEAD"), "titles", "title"),
        ("homebrew", ("GET", "HEAD"), "homebrew", "homebrew_list"),
        ("homebrew/updates", ("POST",), "homebrew", "homebrew_updates"),
        ("homebrew/{}", ("GET", "HEAD"), "homebrew", "homebrew_entry"),
        ("saves", ("GET", "HEAD"), "saves", "saves_list"),
        ("saves/{}", ("POST",), "saves", "save_post"),
        ("saves/{}/uploads", ("POST",), "saves", "upload_open"),
        ("saves/{}/{}", ("GET", "HEAD", "DELETE"), "saves", "save_one"),
        ("uploads/{}", ("HEAD", "PATCH", "DELETE"), "saves", "upload"),
        ("cheats", ("GET", "HEAD"), "cheats", "cheats_list"),
        ("cheats/{}", ("GET", "HEAD"), "cheats", "cheat_text"),
        ("files/{}", ("GET", "HEAD"), "library", "file"),
    )

    def route(self, method, path, query):
        v1 = BASE + "/v1"
        if path in ("/.well-known/lantern", v1, v1 + "/"):
            return self.call(method, ("GET", "HEAD"), None, self.handshake, (), query)
        if path == "/pair":
            return self.pair_page(method)
        if path.startswith(v1 + "/"):
            segments = path[len(v1) + 1:].split("/")
            for pattern, methods, family, name in self.ROUTES:
                wanted = pattern.split("/")
                if len(wanted) == len(segments) and all(w == s or (w == "{}" and s) for w, s in zip(wanted, segments)):
                    args = tuple(s for w, s in zip(wanted, segments) if w == "{}")
                    return self.call(method, methods, family, getattr(self, name), args, query)
        raise not_found("No such route on this server.")

    def call(self, method, methods, family, fn, args, query):
        self.account, self.record = self.server.accounts.resolve(self.headers.get("Authorization"),
                                                                 self.server.tokens)
        if method not in methods:
            raise Problem(405, "bad_request", "Method not allowed", None, {"Allow": ", ".join(methods)})
        if family:
            self.allow(self.account, family)
        fn(query, *args)

    def allow(self, account, family):
        if family == "pairing":     # anyone may ask to pair (SPEC.md § 4.2, § 5.2)
            if not self.server.accounts.pairing:
                raise not_found("This server does not pair.")
            return
        if family == "saves" and not self.server.saves.available:
            raise not_found("Save backups are unavailable on this server for now.")
        if account["state"] == "anonymous" and not self.server.accounts.public:
            raise unauthorized(CHALLENGE, "This server asks for a token: pair this device first.")
        if account["state"] == "frozen":
            raise Problem(403, "account_frozen", "Account frozen", "This account may do nothing for now.")
        if SCOPE_OF[family] not in account["scopes"]:
            raise Problem(403, "forbidden", "Forbidden", f"This account lacks the scope {SCOPE_OF[family]}.")

    def features(self, account):
        def offered(family):
            try:
                self.allow(account, family)
                return OFFERED[family]
            except Problem:
                return 0
        features = {f: offered(f) if f in OFFERED else 0 for f in FAMILIES}
        features["pairing"] = 1 if self.server.accounts.pairing else 0
        return features

    def platform(self, query, required=False):
        """The platform the client named (SPEC.md § 4.3): ?platform=, else Lantern-Platform; None for every one."""
        name = query.get("platform") or (self.headers.get("Lantern-Platform") or "").strip()
        if not name:
            if required:
                raise bad_request("Name a platform: Lantern-Platform or ?platform= (SPEC.md § 4.3).")
            return None
        if not PLATFORM.match(name):
            raise bad_request(f"{name[:40]!r} is not a platform's name.")
        return name

    def prefs(self):
        return languages(self.headers.get("Accept-Language"))

    # Routes.

    def handshake(self, query):
        lib, saves = self.server.library, self.server.saves
        doc = {"schema": 1, "uid": lib.uid, "name": self.server.name,
               "software": {"name": "Lantern reference server", "version": VERSION},
               "base": BASE, "versions": [1], "platforms": lib.platforms(), "account": self.account,
               "features": self.features(self.account),
               "limits": {"page_size": PAGE_LIMIT, "save_body": saves.body, "save_size": saves.size,
                          "saves_kept_per_title": saves.kept}}
        self.send_doc(200, doc)

    def listing_args(self, query, sorts=("name", "added", "release")):
        sort = query.get("sort") or "name"
        if sort not in sorts:
            raise bad_request("sort is " + ", ".join(sorts) + ".")
        size = query.get("page_size") or str(PAGE_DEFAULT)
        if not size.isdigit() or int(size) < 1:
            raise bad_request("page_size is a positive integer.")
        return sort, min(int(size), PAGE_LIMIT), query.get("cursor")

    def apps(self, query):
        platform = self.platform(query)
        kind, title_id, q = query.get("type"), query.get("title_id"), query.get("q")
        if kind is not None and not WORD.match(kind):
            raise bad_request("type is a lower-case word, such as base, update or dlc.")
        if title_id is not None and not CORE_ID.match(title_id):
            raise bad_request("title_id is 1 to 128 letters, digits, '.', '_' and '-'.")
        sort, size, cursor = self.listing_args(query)
        lib = self.server.library
        with lib.lock:
            entries = [e for e in lib.apps.values()
                       if (platform is None or e["doc"]["platform"] == platform)
                       and (kind is None or e["doc"]["type"] == kind)
                       and (title_id is None or e["doc"]["title_id"] == title_id)
                       and (not q or q.casefold() in e["doc"]["name"].casefold())]
            self.send_doc(200, lib.page(entries, sort, size, cursor, ("apps", platform, kind, title_id, q)))

    def missing(self, query):
        doc = self.request_document(self.body())
        platform = self.platform(query, required=True)
        installed, want = doc.get("installed"), doc.get("want")
        if not (isinstance(installed, list) and all(
                isinstance(i, dict) and CORE_ID.match(str(i.get("app_id", ""))) and is_int(i.get("version_code"))
                for i in installed)):
            raise bad_request("installed is a list of {app_id, version_code}.")
        if not (isinstance(want, list) and want and all(w in ("base", "update", "dlc") for w in want)):
            raise bad_request("want lists base, update or dlc.")
        sort, size, cursor = self.listing_args(query)
        lib = self.server.library
        scope = ("missing", platform, hashlib.sha256(json.dumps([installed, sorted(set(want))], sort_keys=True)
                                                     .encode()).hexdigest())
        with lib.lock:
            self.send_doc(200, lib.page(lib.missing(platform, installed, set(want)), sort, size, cursor, scope))

    def request_document(self, body):
        """A client's JSON document: 400 when malformed, 422 for a schema this server cannot read."""
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            raise bad_request("The body is application/json.")
        try:
            doc = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise bad_request("The body is not JSON.") from None
        if not isinstance(doc, dict) or not isinstance(doc.get("schema"), int) or isinstance(doc["schema"], bool) \
                or doc["schema"] < 1:
            raise bad_request("The body is an object with an integer schema.")
        if doc["schema"] > 1:
            raise Problem(422, "unsupported_schema", "Unsupported schema",
                          f"This server reads schema 1 here, not {doc['schema']}.")
        return doc

    def changes(self, query):
        self.send_doc(200, self.server.library.changes(query.get("since"), self.platform(query)))

    # Titles (SPEC.md § 7).

    def titles(self, query):
        platform = self.platform(query)
        ids = [i for i in (query.get("ids") or "").split(",") if i]
        if not ids:
            raise bad_request("ids lists the title ids, comma-separated.")
        if len(ids) > TITLES_AT_ONCE:
            raise bad_request(f"At most {TITLES_AT_ONCE} ids at once.")
        if not all(CORE_ID.match(i) for i in ids):
            raise bad_request("A title id is 1 to 128 letters, digits, '.', '_' and '-'.")
        lib, prefs = self.server.library, self.prefs()
        with lib.lock:
            keys = [k for k, t in lib.titles.items() if t["title_id"] in ids and (platform is None or t["platform"] == platform)]
            known = {lib.titles[k]["title_id"] for k in keys}
            doc = {"schema": 1, "titles": [lib.title_doc(k, prefs) for k in sorted(keys)],
                   "unknown": [i for i in dict.fromkeys(ids) if i not in known]}
        self.send_doc(200, doc)

    def title_changes(self, query):
        lib = self.server.library
        self.send_doc(200, lib.title_changes(query.get("since"), self.platform(query), self.prefs()))

    def title(self, query, title_id):
        lib = self.server.library
        table = {(t["platform"], t["title_id"]): k for k, t in lib.titles.items()}
        key = lib.find(table, title_id, self.platform(query))
        self.send_doc(200, {"schema": 1, **lib.title_doc(key, self.prefs())})

    # Homebrew (SPEC.md § 8).

    def homebrew_view(self, entry, full):
        doc = dict(entry["doc"])
        if not full and "manifest" in doc["package"]:
            doc["package"] = {k: v for k, v in doc["package"].items() if k != "manifest"}
        language = None
        for k, value in entry["texts"].items():
            doc[k], lang = localized(value, self.prefs())
            language = language or lang
        if language:
            doc["language"] = language
        if "port" in doc:
            doc["port"] = json.loads(json.dumps(doc["port"]))
            for f in data_files(doc["port"].get("requires_data", [])):
                if "hint" in f:
                    f["hint"] = localized(localizable(f["hint"]), self.prefs())[0]
        return doc

    def homebrew_list(self, query):
        platform = self.platform(query)
        q, category, kind = query.get("q"), query.get("category"), query.get("kind")
        if category is not None and category not in CATEGORIES:
            raise bad_request("category is " + ", ".join(CATEGORIES) + ".")
        if kind is not None and not WORD.match(kind):
            raise bad_request("kind is a lower-case word: " + ", ".join(KINDS) + ".")
        _, size, cursor = self.listing_args(query, ("name",))
        lib = self.server.library
        with lib.lock:
            entries = [e for (p, _), e in lib.homebrew.items()
                       if (platform is None or p == platform) and (category is None or e["doc"]["category"] == category)
                       and (kind is None or e["doc"]["kind"] == kind)
                       and (not q or q.casefold() in e["doc"]["name"].casefold())]
            self.send_doc(200, lib.page(entries, "name", size, cursor, ("homebrew", platform, q, category, kind),
                                        lambda e: self.homebrew_view(e, False)))

    def homebrew_entry(self, query, hid):
        entry = self.server.library.find(self.server.library.homebrew, hid, self.platform(query))
        self.send_doc(200, {"schema": 1, **self.homebrew_view(entry, True)})

    def homebrew_updates(self, query):
        doc = self.request_document(self.body())
        platform = self.platform(query, required=True)
        installed = doc.get("installed")
        if not (isinstance(installed, list) and all(
                isinstance(i, dict) and HOMEBREW_ID.match(str(i.get("id", ""))) and is_int(i.get("build"))
                for i in installed)):
            raise bad_request("installed is a list of {id, build}.")
        _, size, cursor = self.listing_args(query, ("name",))
        builds = {}
        for i in installed:
            builds[i["id"]] = max(builds.get(i["id"], -1), i["build"])
        lib = self.server.library
        scope = ("updates", platform, hashlib.sha256(json.dumps(sorted(builds.items())).encode()).hexdigest())
        with lib.lock:
            newer = [e for (p, hid), e in lib.homebrew.items()
                     if p == platform and hid in builds and e["doc"]["build"] > builds[hid]]
            self.send_doc(200, lib.page(newer, "name", size, cursor, scope, lambda e: self.homebrew_view(e, False)))

    # Save backups (SPEC.md § 9).

    def save_target(self, query, title_id):
        platform = self.platform(query, required=True)
        if not title_id_ok(platform, title_id):
            raise bad_request(f"Not a title id of {platform}.")
        return platform

    def text_header(self, name, limit):
        raw = self.headers.get(name)
        if raw is None:
            return None
        try:
            value = unquote(raw, errors="strict")
        except UnicodeDecodeError:
            raise bad_request(f"{name} is UTF-8, percent-encoded.") from None
        if len(value.encode()) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise bad_request(f"{name}: {limit} bytes at most, without control characters.")
        return value or None

    def save_fields(self, platform, title_id, kind, version, profile, note, slot=None):
        if kind is not None and kind not in SAVE_KINDS:
            raise bad_request("kind is " + ", ".join(SAVE_KINDS) + ".")
        if version is not None and not is_int(version):
            raise bad_request("game_version_code is an integer.")
        if slot is not None and not (isinstance(slot, str) and SLOT.match(slot)):
            raise bad_request("slot is 1 to 64 letters, digits, '.', '_' and '-'.")
        for value, limit, what in ((profile, 64, "profile"), (note, 120, "note")):
            if value is not None and (not isinstance(value, str) or len(value.encode()) > limit
                                      or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                raise bad_request(f"{what}: {limit} bytes at most, without control characters.")
        fields = {"platform": platform, "title_id": title_id, "kind": kind, "game_version_code": version,
                  "profile": profile or None, "slot": slot or None, "note": note or None,
                  "device": (self.record or {}).get("device")}
        return {k: v for k, v in fields.items() if v is not None}

    def saves_list(self, query):
        title_id = query.get("title_id")
        if title_id is not None and not CORE_ID.match(title_id):
            raise bad_request("title_id is 1 to 128 letters, digits, '.', '_' and '-'.")
        docs = self.server.saves.list(self.account["name"], self.platform(query), title_id)
        self.send_doc(200, {"schema": 1, "saves": docs})

    def save_post(self, query, title_id):
        platform = self.save_target(query, title_id)
        saves = self.server.saves
        digest = content_digest(self.headers.get("Content-Digest"))
        if digest is None:
            raise bad_request("Content-Digest: sha-256=:<base64>: is required (SPEC.md § 9.2).")
        version = self.headers.get("Lantern-Game-Version")
        if version is not None and not version.isdigit():
            raise bad_request("Lantern-Game-Version is an integer.")
        fields = self.save_fields(platform, title_id, self.headers.get("Lantern-Save-Kind"),
                                  int(version) if version is not None else None,
                                  self.text_header("Lantern-Profile", 64), self.text_header("Lantern-Note", 120),
                                  self.text_header("Lantern-Save-Slot", 64))
        data = self.body(saves.body)
        if not hmac.compare_digest(hashlib.sha256(data).digest(), digest):
            raise digest_mismatch("The body's SHA-256 is not the one Content-Digest gives.")
        saves.folder.mkdir(parents=True, exist_ok=True)
        tmp = saves.folder / f".post-{secrets.token_hex(8)}"
        tmp.write_bytes(data)
        try:
            if not zipfile.is_zipfile(tmp):
                raise bad_request("A save is a zip archive.")
            entry = saves.add(self.account["name"], tmp, hashlib.sha256(data).hexdigest(), len(data), fields)
        finally:
            if tmp.exists():
                tmp.unlink()
        self.send_doc(201, {"schema": 1, **entry})

    def upload_open(self, query, title_id):
        doc = self.request_document(self.body())
        platform = self.save_target(query, title_id)
        saves = self.server.saves
        size, sha = doc.get("size"), doc.get("sha256")
        if not is_int(size) or not (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)):
            raise bad_request("size is an integer and sha256 a lower-case hex SHA-256.")
        if size > saves.size:
            raise Problem(413, "too_large", "Too large", f"A save is {saves.size} bytes at most here.")
        fields = self.save_fields(platform, title_id, doc.get("kind"), doc.get("game_version_code"),
                                  doc.get("profile"), doc.get("note"), doc.get("slot"))
        uid, expires = saves.open(self.account["name"], fields, size, sha)
        self.send_doc(201, {"schema": 1, "upload": f"{BASE}/v1/uploads/{uid}", "chunk_size": saves.chunk,
                            "offset": 0, "expires": expires}, {"Location": f"{BASE}/v1/uploads/{uid}"})

    def upload(self, query, uid):
        saves = self.server.saves
        s = saves.session(uid, self.account["name"])
        if s is None:
            raise not_found("No such upload: it finished, expired or was abandoned.")
        if self.method == "HEAD":
            return self.send_head(204, None, {"Upload-Offset": str(saves.offset(uid)),
                                              "Upload-Length": str(s["size"]), "Cache-Control": "no-store"})
        if self.method == "DELETE":
            saves.abandon(uid)
            return self.send_head(204, None, {})
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/offset+octet-stream":
            raise bad_request("A chunk is application/offset+octet-stream.")
        offset = self.headers.get("Upload-Offset") or ""
        if not offset.isdigit():
            raise bad_request("Upload-Offset is the chunk's offset, an integer.")
        digest = content_digest(self.headers.get("Content-Digest"))
        data = self.body(saves.chunk)
        if digest is not None and not hmac.compare_digest(hashlib.sha256(data).digest(), digest):
            raise digest_mismatch("The chunk's SHA-256 is not the one Content-Digest gives; it was not kept.")
        at = saves.append(uid, int(offset), data)
        if at < s["size"]:
            return self.send_head(204, None, {"Upload-Offset": str(at), "Cache-Control": "no-store"})
        entry = saves.finish(uid)
        self.send_doc(201, {"schema": 1, **entry}, {"Upload-Offset": str(at)})

    def save_one(self, query, title_id, save_id):
        saves = self.server.saves
        entry = saves.find(self.account["name"], title_id, save_id, self.platform(query))
        if entry is None:
            raise not_found("No such save backup.")
        if self.method == "DELETE":
            saves.delete(entry)
            return self.send_head(204, None, {})
        self.send_file(saves.archive(save_id), entry["size"], entry["sha256"], "application/zip")

    # Cheats (SPEC.md § 10).

    def cheats_list(self, query):
        platform = self.platform(query)
        title_id, build_id = query.get("title_id"), query.get("build_id")
        if title_id is not None and not CORE_ID.match(title_id):
            raise bad_request("title_id is 1 to 128 letters, digits, '.', '_' and '-'.")
        if build_id is not None and not BUILD_ID.match(build_id):
            raise bad_request("build_id is 1 to 64 letters, digits, '.', '_' and '-'.")
        lib = self.server.library
        with lib.lock:
            sets = [e["doc"] for e in lib.cheats.values()
                    if (platform is None or e["doc"]["platform"] == platform)
                    and (title_id is None or e["doc"]["title_id"] == title_id)
                    and (build_id is None or e["doc"]["build_id"] == build_id)]
        sets.sort(key=lambda d: (d["platform"], d["title_id"], d["build_id"], d["source"].casefold(), d["id"]))
        self.send_doc(200, {"schema": 1, "cheats": sets})

    def cheat_text(self, query, cid):
        platform = self.platform(query)
        lib = self.server.library
        with lib.lock:
            entry = lib.cheats.get(cid)
        if entry is None or (platform is not None and entry["doc"]["platform"] != platform):
            raise not_found("No such cheat set.")
        self.send_file(entry["path"], entry["doc"]["size"], entry["doc"]["sha256"], "text/plain; charset=utf-8")

    # Pairing (SPEC.md § 5.2).

    def origin(self):
        host = self.headers.get("Host") or ""
        if not re.fullmatch(r"[A-Za-z0-9.\-]+(:\d+)?|\[[0-9A-Fa-f:.]+\](:\d+)?", host):
            host = f"{self.server.server_address[0]}:{self.server.server_address[1]}"
        return f"{'https' if self.server.tls else 'http'}://{host}"

    def pair_start(self, query):
        doc = self.request_document(self.body())
        device, scopes = doc.get("device"), doc.get("scopes")
        if not (isinstance(device, str) and device.strip() and len(device.encode()) <= 512
                and not any(ord(c) < 32 or ord(c) == 127 for c in device)):
            raise bad_request("device is the device's name, 512 bytes at most, without control characters.")
        if not (isinstance(scopes, list) and all(isinstance(x, str) for x in scopes)):
            raise bad_request("scopes is a list of scopes.")
        known = [x for x in SCOPES if x in scopes]     # the ones this server knows, without repeats
        if not known:
            raise bad_request("scopes names none of " + ", ".join(SCOPES) + ".")
        wait = self.server.pair_limiter.hit(self.client_address[0])
        if wait:
            raise slow_down(wait, "Too many pairing requests from this address.")
        entry = self.server.pairing.start(device.strip(), known)
        self.send_doc(200, {"schema": 1, "code": Pairing.shown(entry["code"]), "verify": self.origin() + "/pair",
                            "poll": f"{BASE}/v1/pairing/{entry['pid']}", "interval": entry["interval"],
                            "expires": int(self.server.pairing.expires)}, {"Cache-Control": "no-store"})

    def pair_poll(self, query, pid):
        doc = self.server.pairing.poll(pid)
        if doc is None:
            self.send_head(202, 0, {"Cache-Control": "no-store"})
        else:
            self.send_doc(200, doc, {"Cache-Control": "no-store"})

    def pair_page(self, method):
        """/pair: where a user signs in, enters the console's code and approves it.
        A password is typed here only, never on the console (SPEC.md § 5.2)."""
        if not self.server.accounts.pairing:
            raise not_found("This server does not pair.")
        if method not in ("GET", "HEAD", "POST"):
            raise Problem(405, "bad_request", "Method not allowed", None, {"Allow": "GET, HEAD, POST"})
        if method != "POST":
            return self.send_page(200, self.pair_form())
        if not self.server.tls and not is_loopback(self.client_address[0]):
            return self.send_page(403, "<p>Sign in only over HTTPS.</p>")
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/x-www-form-urlencoded":
            return self.send_page(400, self.pair_form("The form was not sent as a form."))
        body = self.body()
        form = {k: v[-1] for k, v in parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).items()}
        pairing = self.server.pairing
        if "nonce" in form:
            entry = pairing.by_nonce(form["nonce"])
            if entry is None:
                return self.send_page(410, self.pair_form("This pairing expired; ask the console for a new code."))
            if form.get("decision") == "approve":
                pairing.approve(entry, entry["user"])
                return self.send_page(200, f"<p>{html.escape(entry['device'])} is paired. "
                                           "The console finishes on its own.</p>")
            pairing.refuse(entry)
            return self.send_page(200, f"<p>{html.escape(entry['device'])} was refused.</p>")
        ip = self.client_address[0]
        wait = self.server.attempts.wait(ip)
        if wait:
            return self.send_page(429, self.pair_form("Too many attempts; try again later."),
                                  {"Retry-After": str(wait)})
        user = self.server.accounts.sign_in(form.get("name", ""), form.get("password", ""))
        if user is None:
            self.server.attempts.record(ip)
            return self.send_page(403, self.pair_form("Wrong name or password."))
        if user.get("state") == "frozen":
            return self.send_page(403, self.pair_form("This account is frozen."))
        entry = pairing.by_code(form.get("code", ""))
        if entry is None:
            self.server.attempts.record(ip)
            return self.send_page(400, self.pair_form("No such code, or it expired."))
        nonce = pairing.prepare(entry, user)
        scopes = ", ".join(pairing.grant(entry, user)) or "none"
        return self.send_page(200, f"""<p>Pair <strong>{html.escape(entry['device'])}</strong> with
<strong>{html.escape(user['name'])}</strong>'s account, for: {html.escape(scopes)}?</p>
{self.fingerprint()}
<form method="post" action="/pair">
<input type="hidden" name="nonce" value="{html.escape(nonce)}">
<button name="decision" value="approve">Approve</button> <button name="decision" value="refuse">Refuse</button>
</form>""")

    def fingerprint(self):
        if not self.server.spki:
            return "<p>Plain HTTP on loopback: no key to compare.</p>"
        return (f"<p>This server's key: <code>{short_fingerprint(self.server.spki)}</code>. "
                "The console shows the same next to its code: approve only if they match.</p>")

    def pair_form(self, error=None):
        note = f'<p class="error">{html.escape(error)}</p>' if error else ""
        return f"""{note}<p>Sign in, then enter the code your console shows.</p>
{self.fingerprint()}
<form method="post" action="/pair">
<p><label>Name <input name="name" autocomplete="username" required></label></p>
<p><label>Password <input name="password" type="password" autocomplete="current-password" required></label></p>
<p><label>Code <input name="code" autocomplete="off" autocapitalize="characters" required></label></p>
<p><button>Continue</button></p>
</form>"""

    def send_page(self, status, content, headers=None):
        title = html.escape(self.server.name)
        body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>Pair a device · {title}</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:32rem;margin:2rem auto;padding:0 1rem}}
code{{font-size:1.1em}}.error{{color:#b00020}}input{{font:inherit}}</style></head>
<body><h1>Pair a device</h1><p>{title}</p>
{content}
</body></html>
""".encode()
        self.send_head(status, len(body), {
            **(headers or {}), "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                                       "frame-ancestors 'none'; base-uri 'none'",
            "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"})
        if not self.head:
            self.wfile.write(body)

    # Files (SPEC.md § 6.6): packages, homebrew, save backups and cheat sets alike.

    def file(self, query, fid):
        lib = self.server.library
        with lib.lock:
            entry = lib.files.get(fid)
        if entry is None:
            raise not_found("No such file; read the app again.")
        self.send_file(entry["path"], entry["size"], entry["sha256"], "application/octet-stream")

    def send_file(self, path, size, sha256, ctype):
        etag = f'"{sha256[:32]}"'
        start, end = 0, size - 1
        status = 200
        rng = self.headers.get("Range")
        if_range = self.headers.get("If-Range")
        if rng and (if_range is None or if_range == etag):
            parsed = parse_range(rng, size)
            if parsed == "unsatisfiable":
                raise Problem(416, "bad_request", "Range not satisfiable", f"The file is {size} bytes.",
                              {"Content-Range": f"bytes */{size}"})
            if parsed:
                start, end = parsed
                status = 206
        headers = {"Content-Type": ctype, "Accept-Ranges": "bytes", "ETag": etag,
                   "Repr-Digest": f"sha-256=:{base64.b64encode(bytes.fromhex(sha256)).decode()}:"}
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        length = end - start + 1 if size else 0
        self.send_head(status, length, headers)
        if self.head or not length:
            return
        with Path(path).open("rb") as f:
            f.seek(start)
            while length > 0:
                chunk = f.read(min(CHUNK, length))
                if not chunk:  # the file shrank under us: cut the connection rather than lie
                    self.close_connection = True
                    return
                self.wfile.write(chunk)
                length -= len(chunk)

    # Responses.

    def send_head(self, status, length, headers):
        self.began = True
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Vary", "Authorization, Lantern-Platform, Accept-Language")
        if "Cache-Control" not in headers:
            self.send_header("Cache-Control", "private" if self.authenticated else "no-cache")
        self.end_headers()

    def send_doc(self, status, doc, headers=None, problem=False):
        body = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()
        headers = dict(headers or {})
        headers["Content-Type"] = "application/problem+json" if problem else "application/json"
        if status == 200 and self.method in ("GET", "HEAD"):
            etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
            headers["ETag"] = etag
            if etag in [t.strip() for t in (self.headers.get("If-None-Match") or "").split(",")]:
                self.send_head(304, 0, {"ETag": etag})
                return
        self.send_head(status, len(body), headers)
        if not self.head:
            self.wfile.write(body)


def parse_range(header, size):
    """(start, end) of a single byte range, "unsatisfiable", or None to ignore it (RFC 9110 § 14)."""
    m = re.fullmatch(r"\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*", header)
    if not m or (m.group(1) == "" and m.group(2) == ""):
        return None  # another unit, several ranges or nonsense: the whole file
    if m.group(1) == "":
        n = int(m.group(2))
        return (max(0, size - n), size - 1) if n and size else "unsatisfiable"
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else size - 1
    if m.group(2) and end < start:
        return None  # invalid: ignored
    if start >= size:
        return "unsatisfiable"
    return start, min(end, size - 1)


class LanternServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, library, accounts, name="Lantern reference server", rescan=30.0,
                 quiet=False, handler=Handler, tls=None, spki=None, token_lifetime=None, saves=None):
        """`tls`: an ssl.SSLContext; without it, only a loopback address (SPEC.md § 2).
        `spki`: the SHA-256 of the certificate's key, for /pair (SPEC.md § 5.3).
        `saves`: a Saves, by default in the library's .lantern-saves/."""
        if tls is None and not is_loopback(address[0]):
            raise ValueError(f"plain HTTP only on a loopback address, not {address[0] or 'every address'}: "
                             "give --tls-cert and --tls-key (SPEC.md § 2)")
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, handler)
        if tls is not None:
            # The handshake happens in the request's thread, not in the accepting one.
            self.socket = tls.wrap_socket(self.socket, server_side=True, do_handshake_on_connect=False)
        self.tls, self.spki = tls is not None, spki
        self.library, self.accounts, self.name = library, accounts, name
        self.saves = saves if saves is not None else Saves(library.root / ".lantern-saves")
        self.rescan, self.quiet = rescan, quiet
        self.tokens = Tokens(library)
        self.pairing = Pairing(self.tokens, accounts, lifetime=token_lifetime)
        self.pair_limiter = Limiter(*PAIR_RATE)
        self.attempts = Limiter(*PAIR_ATTEMPTS)


def discovery(server, port, http_port):
    """Answer Lantern's discovery datagram on UDP (SPEC.md § 4.1)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", port))
    limiter = Limiter(5, 1.0)

    def loop():
        while True:
            try:
                data, peer = sock.recvfrom(DATAGRAM_LIMIT + 1)
            except OSError:
                return  # closed
            reply = discovery_reply(server, http_port, data, peer[0], limiter)
            if reply:
                try:
                    sock.sendto(reply, peer)
                except OSError:
                    pass

    threading.Thread(target=loop, daemon=True).start()
    return sock


def discovery_reply(server, http_port, data, address, limiter):
    """The reply to one datagram, or None to stay silent."""
    if len(data) > DATAGRAM_LIMIT:
        return None
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return None
    if ip.is_global:
        return None     # not from a local network
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not (isinstance(doc, dict) and type(doc.get("schema")) is int and doc["schema"] == 1
            and doc.get("lantern") == "discover"):
        return None     # not a request this server can read (SPEC.md § 3.2)
    if limiter.hit(address):
        return None
    reply = {"schema": 1, "lantern": "server", "uid": server.library.uid, "name": clip(server.name),
             "port": http_port, "base": BASE, "versions": [1]}
    return json.dumps(reply, ensure_ascii=False, separators=(",", ":")).encode()


def tokens_command(state_path, revoke):
    """--tokens and --revoke: the state file's tokens, listed or one revoked."""
    doc = read_versioned(Path(state_path), "state")
    if doc is None:
        sys.exit(f"{state_path}: no state this server can write (absent, unreadable or newer)")
    tokens = doc.get("tokens") if isinstance(doc.get("tokens"), dict) else {}
    if revoke is None:
        for key, t in sorted(tokens.items(), key=lambda kv: str(kv[1].get("created", ""))):
            print(f"{key[:12]}  {t.get('user')}  {t.get('device')!r}  {', '.join(t.get('scopes', []))}  "
                  f"created {t.get('created')}" + (f", expires {t['expires']}" if t.get("expires") else ""))
        return 0
    found = [k for k in tokens if len(revoke) >= 8 and k.startswith(revoke.lower())]
    if len(found) != 1:
        sys.exit(f"--revoke {revoke}: {'no' if not found else 'more than one'} token with this id")
    del tokens[found[0]]
    doc["tokens"] = tokens
    write_json(Path(state_path), doc)
    print(f"revoked {found[0][:12]}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m server", description="Lantern reference server.")
    p.add_argument("--library", help="the folder of packages")
    p.add_argument("--host", default="127.0.0.1",
                   help="address to listen on (default 127.0.0.1; any other needs --tls-cert and --tls-key)")
    p.add_argument("--port", type=int, default=8080, help="TCP port (default 8080; 0: any)")
    p.add_argument("--name", default="Lantern reference server", help="the name the handshake shows")
    p.add_argument("--users", help="accounts file; without it the server is public and does not pair")
    p.add_argument("--state", help="state file (default <library>/.lantern-state.json)")
    p.add_argument("--saves", help="where save backups are kept (default <library>/.lantern-saves/)")
    p.add_argument("--rescan", type=float, default=30.0, help="seconds between library scans (0: every request)")
    p.add_argument("--tls-cert", help="certificate chain (PEM); with --tls-key, HTTPS")
    p.add_argument("--tls-key", help="private key (PEM)")
    p.add_argument("--token-days", type=float, help="new tokens expire after this many days (default: never)")
    p.add_argument("--tokens", action="store_true", help="list the paired devices' tokens, then exit")
    p.add_argument("--revoke", metavar="ID", help="revoke a token (its id from --tokens), then exit")
    p.add_argument("--discovery", action="store_true", help="answer LAN discovery on UDP")
    p.add_argument("--discovery-port", type=int, default=DISCOVERY_PORT)
    p.add_argument("--quiet", action="store_true", help="no request log")
    p.add_argument("--hash-password", action="store_true", help="print a password's hash for --users")
    args = p.parse_args(argv)
    if args.hash_password:
        password = getpass.getpass("Password: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
        print(hash_password(password))
        return 0
    if args.tokens or args.revoke:
        if not (args.state or args.library):
            p.error("--tokens and --revoke need --state or --library")
        return tokens_command(args.state or Path(args.library) / ".lantern-state.json", args.revoke)
    if not args.library or not Path(args.library).is_dir():
        p.error("--library DIR: a folder of packages")
    if bool(args.tls_cert) != bool(args.tls_key):
        p.error("--tls-cert and --tls-key go together")
    tls = spki = None
    if args.tls_cert:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(args.tls_cert, args.tls_key)
        spki = spki_sha256(Path(args.tls_cert).read_text(encoding="ascii"))
    library = Library(args.library, args.state or Path(args.library) / ".lantern-state.json")
    saves = Saves(args.saves or Path(args.library) / ".lantern-saves")
    if not saves.available:
        log(f"{saves.path}: save backups unavailable (an index this server cannot read or write)")
    lifetime = args.token_days * 86400 if args.token_days else None
    try:
        server = LanternServer((args.host, args.port), library, Accounts(args.users), args.name, args.rescan,
                               args.quiet, tls=tls, spki=spki, token_lifetime=lifetime, saves=saves)
    except ValueError as e:
        p.error(str(e))
    port = server.server_address[1]
    if args.discovery:
        discovery(server, args.discovery_port, port)
    log(f"{len(library.apps)} app(s), {len(library.homebrew)} homebrew, {len(library.cheats)} cheat set(s) "
        f"from {library.root}, {'public' if server.accounts.public else 'private'}, uid {library.uid}")
    scheme = "https" if tls else "http"
    if tls:
        log(f"key {short_fingerprint(spki)} (SPKI SHA-256 {spki})")
    else:
        log("plain HTTP on loopback: for local testing only (SPEC.md § 2)")
    if server.accounts.pairing:
        log(f"pairing: approve devices at {scheme}://{args.host}:{port}/pair")
    log(f"listening on {scheme}://{args.host}:{port}{BASE}/v1/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
