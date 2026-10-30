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
     "genres": ["puzzle"], "tags": ["journal"], "summary": "…",
     "requires": {"text": "…", "min": {"atmosphere": "1.7.0"}},
     "system_id": "…", "arch": ["aarch64", "armhf"], "signer_sha256": "…",
     "signature": {"alg": "ed25519", "public_key": "…", "value": "…"}}

`kind` is app, game, port, emulator, tool, overlay, sysmodule or theme (an
unknown one is read as app). `genres` come from the titles' list (an entry
with another is not served), `tags` are free words. `requires` (SPEC.md
§ 8.7) is served as given once its known conditions are of their form
(`min.glibc` dotted, `min.ram_mb` an integer, `min.screen` "640x480", `gpu`
a list of gles2, gles3, gl, vulkan): the keys this server does not know are
kept. `arch` is a list (aarch64, armhf, x86, x86_64, riscv64;
none on a Switch, a 3DS, a Vita or a PS4, which have one architecture), `signer_sha256` the
platform's own signing certificate's SHA-256 (Android), `assets_license` an
SPDX expression, `system_id` the platform's own id of the homebrew where it
has one, and
`requires.homebrew` the homebrew it needs: [{"id", "min_build"}]. The NACP
has no integer version: `build` comes from homebrew.json (without one, this
server derives its own from the version, 1.4.2 giving 1004002).

An entry with a package per architecture lists its files under `packages`,
the first one being its `package`, each with its own `arch`, and its own
`signature` when the entry is signed (by the same key):

    {"schema": 1, "id": "org.example.harborlights", "platform": "linux", "build": 20100,
     "packages": [{"file": "harbor-arm.zip", "arch": ["aarch64", "armhf"], "signature": {…}},
                  {"file": "harbor-x86_64.zip", "arch": ["x86_64"], "signature": {…}}]}

Linux homebrew (Annex A.6) are zips, `"platform": "linux"` in homebrew.json;
their paths are in the folder the client chose ("/"). A port
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
one set per file (the Switch when no platform is named). With the scope
cheats.write, POST /v1/cheats writes a set there (its source the file's
name, "_" for a space), PUT replaces its text and note, DELETE removes it;
notes are kept in DIR/cheats/index.json. A set is for a build, 1 MiB at
most, and on a Switch or a 3DS holds only [names] and words of 8 hex digits.

Requests (SPEC.md § 11): each account's, kept in the state file; an account
withdraws its own with DELETE.

Save backups (SPEC.md § 9): kept under --saves (default DIR/.lantern-saves/),
an index.json and the archives, sent in one request or by resumable upload;
a backup encrypted on the device (§ 9.4) is kept as sent, its first bytes
checked against its scheme's header and key id, never read.

Events (SPEC.md § 18): /v1/events streams them (Server-Sent Events), and
/v1/changes?since=&wait= long-polls them, from a journal kept in memory,
whose ids are /v1/changes's tokens: a library changed (at a scan), a request
made, done (its title arrived in the library) or withdrawn, a pairing
waiting, a backup kept, a sync collection changed, and shutdown when the
server stops. Each caller gets only what its token may read; a heartbeat
every 15 seconds, 2 streams per token.

Grants (SPEC.md § 19.3): the server's own Ed25519 key, kept in the state
file ("grant_seed"), signs them; server/peer.py is a reference peer that
takes them. library.json's entries and homebrew.json's packages may give
`mirrors` ([{"url"}], HTTPS, or HTTP on a private network).

Sync (SPEC.md § 20): each account's wishes and installed items, in
--sync-file (default DIR/.lantern-sync.json), merged by § 20.4's rule,
deletions kept 30 days.

Static libraries (SPEC.md § 21): --export DIR writes the library as files
(server/static.py), then exits.

Each file is hashed once (SHA-256); the hashes are kept with the server's
uid and secret in a state file (--state, default DIR/.lantern-state.json).
Every file this server reads or writes has a `schema`: one newer than it
knows is treated as absent and never written over, and the keys it does
not know are kept.

Families offered: library, titles, changes, homebrew, cheats, saves,
encrypted_saves, requests, admin, events, peers and sync (to an account
with the scope), and pairing and signatures when there are accounts.
Sections stay at 0: their routes answer 404.

library.json's and homebrew.json's entries may also give `atlas` (the
game's Atlas id, a Wikidata item such as "Q900001", SPEC.md § 6.1),
`installed_size` (an app's bytes once installed) and, for a homebrew,
`ratings` ([{"system": "PEGI", "rating": "3"}]), which rating caps read.

Deleting an account (SPEC.md § 5.7): only one the administration API made;
one of users.json gives 409 (remove it there). Its tokens, invitations,
pairings waiting, backups, requests and sync data go with it.

Accounts (SPEC.md § 5): without --users, the server is public, every caller
reads the library anonymously, and nobody pairs. With --users FILE:

    {"schema": 1, "public": false, "users": [
      {"name": "lea", "password": "pbkdf2-sha256$600000$<salt>$<hash>",
       "scopes": ["library", "saves", "cheats"], "state": "active"}]}

`python3 -m server --hash-password` prints a password's hash. `state` is
`active` or `frozen`. A password is only ever typed on the server's own
page, /pair: a console gets a token by pairing (SPEC.md § 5.2), which the
user approves there, signed in, with the code the console shows (or that
`verify_complete`, a QR code on the console, fills in), choosing a rating
cap if they want one (§ 5.6). An account with the scope admin may also
approve pairings, list and revoke devices, freeze accounts, make accounts
without a password and invitations, through the administration API
(SPEC.md § 5.5, § 5.7); what it changes is kept in the state file
("accounts", "invitations"), never in users.json. Tokens are kept hashed in
the state file ("tokens"), with the device's public key when it sent one at
pairing, which binds the token: its requests are then signed (SPEC.md
§ 5.4, server/signatures.py). `--bound-only` issues and takes only bound
tokens. `--tokens` lists them and `--revoke ID` revokes one, even while the
server runs. `--token-days N` makes new tokens expire after N days.

Languages (SPEC.md § 2.2): errors' titles and details in the fifteen
languages of Boréale's sites (server/texts.py), as Accept-Language asks; `--motd FILE` gives the handshake's message,
{"schema": 1, "motd": {"en": "…", "fr": "…"}} (or one text). JSON is sent
compressed when the client asks (gzip, and zstd where Python has it); files
never are (SPEC.md § 2.1).

TLS: give --tls-cert and --tls-key; /pair then shows the short fingerprint
of the key (SPEC.md § 5.3). Without them the server speaks plain HTTP, and
only on a loopback address (127.0.0.0/8, ::1), for testing: SPEC.md § 2.

LAN discovery (SPEC.md § 4.1): --discovery answers Lantern's discovery
datagram on UDP 47115 (--discovery-port to change it), from local addresses
only (not global ones), a few times a second per address. --dns-sd
advertises _lantern._tcp over multicast DNS (server/mdns.py, the standard
library alone), with the TXT keys uid, path and v.
"""
import argparse
import base64
import getpass
import gzip
import hashlib
import hmac
import html
import ipaddress
import json
import math
import re
import secrets
import select
import socket
import ssl
import sys
import threading
import time
import traceback
import uuid
import zipfile
import zlib
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

try:
    from server import ed25519, mdns, nro, signatures, texts
except ImportError:     # run as server/lantern_server.py
    import ed25519
    import mdns
    import nro
    import signatures
    import texts

try:                    # Python 3.14 and later: zstd in the standard library (SPEC.md § 2.1)
    from compression import zstd
except ImportError:
    zstd = None

VERSION = "0.5.0"
BASE = "/api/lantern"
FAMILIES = ("library", "titles", "changes", "sections", "homebrew", "saves", "cheats", "requests", "pairing",
            "signatures", "admin", "events", "peers", "sync", "encrypted_saves")
OFFERED = {"library": 1, "titles": 1, "changes": 1, "homebrew": 1, "saves": 1, "cheats": 1,
           "requests": 1, "admin": 1, "events": 1, "peers": 1, "sync": 1, "encrypted_saves": 1}  # the schema written
SCOPE_OF = {"library": "library", "titles": "library", "changes": "library", "homebrew": "library",
            "saves": "saves", "cheats": "cheats", "cheats.write": "cheats.write", "requests": "requests",
            "admin": "admin", "peers": "library", "sync": "sync.read", "sync.write": "sync.write",
            "encrypted_saves": "saves"}
# Events (SPEC.md § 18): who may read each event, by the scope it needs; ready and shutdown go to every stream.
EVENT_SCOPES = {"library": "library", "request": "requests", "save": "saves", "pairing": "admin", "sync": "sync.read"}
HEARTBEAT = 15          # limits.heartbeat: seconds between two heartbeats at most (5 to 60)
EVENT_STREAMS = 2       # limits.event_streams: streams a token (or an anonymous address) holds at once
WAIT_LIMIT = 60         # limits.wait: the longest wait of a long poll (30 to 300)
STREAM_MAX = 3600       # a stream ends after an hour; its client connects again with Last-Event-ID
RETRY_MS = 5000         # the stream's retry field
EVENTS_LIMIT = 10000    # events kept for Last-Event-ID and long polls; older ids are gone
# Peers (SPEC.md § 19): a grant's lifetime, at most 900 seconds; mirrors per file.
GRANT_LIFETIME = 600
MIRRORS_LIMIT = 8
PRIVATE_NETS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7",
                                                  "fe80::/10")]
# Sync (SPEC.md § 20).
SYNC_COLLECTIONS = ("wishes", "installed")
SYNC_ITEMS = 10000      # limits.sync_items
SYNC_WRITE = 1000       # items in one write (SPEC.md § 13)
TOMBSTONE_DAYS = 30     # deletions kept at least this long (SPEC.md § 20.5)
UPDATED = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d{1,3})?Z$")
# End-to-end encrypted saves (SPEC.md § 9.4).
E2E_SCHEME = "lantern-save-e2e-1"
E2E_MAGIC = b"LTNE2E01"
KEY_ID = re.compile(r"^[0-9a-f]{16}$")
PAGE_LIMIT = 500        # limits.page_size
PAGE_DEFAULT = 100
BODY_LIMIT = 1 << 20    # a request document, well under SPEC.md § 13's 32 MiB
DEPTH_LIMIT = 16        # a request document's nesting (SPEC.md § 13)
DRAIN_LIMIT = 4 << 20   # a body left unread is read and dropped up to this, else the connection is closed
JOURNAL_LIMIT = 10000   # changes kept for /v1/changes and /v1/titles/changes; older tokens are gone
CURSOR_LIMIT = 10000    # cursors kept; older ones are gone
TITLES_AT_ONCE = 100    # SPEC.md § 7.2
CHEAT_LIMIT = 1 << 20   # SPEC.md § 10
CHEAT_BODY = 3 << 20    # a cheat set's document: its text, escaped in JSON
CHEAT_SOURCE = re.compile(r"^[^\W_](?:[^\W_]|[ .'()-]){0,63}(?<! )$")   # a source, a file's name: no "_", "/" or "."-first
CHEAT_LINE = re.compile(r"^\s*(?:\[[^\]]{0,255}\]|\{[^}]{0,255}\}|[0-9A-Fa-f]{8}(?:\s+[0-9A-Fa-f]{8})*)?\s*$")
CHEAT_HEX = ("switch", "3ds")   # Atmosphère's and Luma3DS's formats: names in brackets, hex words (Annex A)
REQUESTS_OPEN = 1000    # open requests per account
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
    "3ds": {"id": re.compile(r"^0004(0000|0002|000E|008C)[0-9A-F]{8}$"), "title": re.compile(r"^0004000[02][0-9A-F]{8}$"),
            "types": ("base", "update", "dlc"), "formats": ("cia",),
            "homebrew": {"3dsx": "/3ds/{id}/{id}.3dsx", "zip": None, "cia": "system"}, "roots": ("/3ds/{id}/", "/luma/", "/boot.firm", "/boot.3dsx", "/gm9/"),
            "areas": ("/3ds/",)},
    "vita": {"id": re.compile(r"^[A-Z0-9]{9}$|^[A-Z]{2}[0-9]{4}-[A-Z0-9]{9}_[0-9]{2}-[A-Z0-9]{16}$"),
             "title": re.compile(r"^[A-Z0-9]{9}$"), "types": ("base", "update", "dlc"), "formats": ("vpk",),
             "homebrew": {"vpk": "system"}, "roots": ()},
    "ps4": {"id": re.compile(r"^[A-Z]{4}[0-9]{5}$|^[A-Z]{2}[0-9]{4}-[A-Z]{4}[0-9]{5}_[0-9]{2}-[A-Z0-9]{16}$"),
            "title": re.compile(r"^[A-Z]{4}[0-9]{5}$"), "types": ("base", "update", "dlc"), "formats": ("pkg",),
            "homebrew": {"pkg": "system"}, "roots": ()},
    "android": {"id": re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$"), "types": ("base",),
                "formats": ("apk",), "replaces": True, "homebrew": {"apk": "system"}, "roots": (), "cheats": False},
    # Linux (Annex A.6): homebrew only; apps follow the core's rules, as on an
    # open platform. "/" is the folder the client chose: "/<id>/" needs no
    # consent, the rest of it does; a port's data lies anywhere in it.
    "linux": {"id": None, "types": None, "formats": None, "homebrew": {"zip": None}, "roots": ("/",),
              "areas": ("/",), "cheats": False},
}
APP_EXT = {f: p for p, prof in PROFILES.items() for f in prof["formats"] or ()}   # nsp -> switch, apk -> android…
HOMEBREW_EXT = {"nro": "switch", "ovl": "switch", "zip": "switch", "3dsx": "3ds", "cia": "3ds", "vpk": "vita", "pkg": "ps4",
                "apk": "android"}
GENRES = ("action", "adventure", "rpg", "strategy", "simulation", "sports", "racing", "puzzle", "platformer",
          "shooter", "fighting", "music", "party", "education", "other")
GPU = ("gles2", "gles3", "gl", "vulkan")    # requires.gpu (SPEC.md § 8.7)
SCREEN = re.compile(r"^[1-9][0-9]{0,5}x[1-9][0-9]{0,5}$")
REQUIRES_KEYS = ("text", "min", "gpu", "homebrew")     # requires' keys this server reads; others are kept as given
TAGS_LIMIT = 32         # SPEC.md § 13
DOTTED_KEYS = ("glibc", "firmware", "atmosphere", "luma", "goldhen", "sdk")    # requires.min's dotted versions
KINDS = ("app", "game", "port", "emulator", "tool", "overlay", "sysmodule", "theme")   # unknown: app
ARCH = re.compile(r"^[a-z0-9_]{1,32}$")     # aarch64, armhf, x86, x86_64, or a later one (SPEC.md § 8.2)
ONE_ARCH = ("switch", "3ds", "vita", "ps4")  # profiles of one architecture: no arch (Annex A)
PACKAGES_LIMIT = 16     # a homebrew's packages (SPEC.md § 13)
ASSETS = ("included", "demo_included", "free_external", "user_owned")    # unknown: user_owned (§ 8.6)
DATA_LIMIT = 256        # files a port's requires_data names, alternatives included (SPEC.md § 13)
ACCEPT_LIMIT = 32       # accepted versions of one data file (SPEC.md § 13)
SLOT = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
HASH_FORMS = {"sha256": 64, "sha1": 40, "md5": 32}  # an accepted version's hashes, lower-case hex
SPDX = re.compile(r"^[A-Za-z0-9.+:() -]{1,256}$")
SAVE_KINDS = ("account", "device", "bcat", "cache", "other")
RATING_SYSTEM = re.compile(r"^[A-Z][A-Z0-9-]{1,15}$")
CHUNK = 1 << 20
SCOPES = ("library", "saves", "cheats", "cheats.write", "requests", "admin", "sync.read", "sync.write")
DISCOVERY_PORT = 47115
DATAGRAM_LIMIT = 1200   # SPEC.md § 4.1, § 13
CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # 5 bits a symbol; no 0, O, 1 or I
CODE_SYMBOLS = 8        # 40 bits
PAIR_EXPIRES = 600      # seconds a code lives (SPEC.md § 5.2: 10 minutes at most)
PAIR_INTERVAL = 5       # seconds between polls
PAIR_RATE = (30, 60.0)          # pairing requests per address, per window
PAIR_ATTEMPTS = (10, 600.0)     # failed sign-ins or codes on /pair per address, per window
PENDING_LIMIT = 1000            # pairings waiting at once
INVITATION_SYMBOLS = 16         # 80 bits (SPEC.md § 5.5)
INVITATION_DAYS = 30            # an invitation lives 30 days at most
INVITATIONS_LIMIT = 1000        # invitations kept at once
ACCOUNT_NAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
ATLAS = re.compile(r"^Q[1-9][0-9]{0,15}$")     # an Atlas id: a Wikidata item (SPEC.md § 6.1)
# Rating caps (SPEC.md § 5.6): each system's ratings, and the age each one means.
RATING_AGES = {
    "PEGI": {"3": 3, "7": 7, "12": 12, "16": 16, "18": 18},
    "ESRB": {"EC": 3, "E": 6, "E10+": 10, "T": 13, "M": 17, "AO": 18},
    "CERO": {"A": 0, "B": 12, "C": 15, "D": 17, "Z": 18},
    "USK": {"0": 0, "6": 6, "12": 12, "16": 16, "18": 18},
    "ACB": {"G": 0, "PG": 8, "M": 15, "MA15+": 15, "R18+": 18, "X18+": 18},
    "CLASSIND": {"L": 0, "10": 10, "12": 12, "14": 14, "16": 16, "18": 18},
    "GRAC": {"ALL": 0, "12": 12, "15": 15, "18": 18},
}
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
    pattern = profile and (profile.get("title") or profile["id"])
    return isinstance(title_id, str) and bool(CORE_ID.match(title_id)) and (
        pattern is None or bool(pattern.match(title_id)))


def app_id_ok(platform, app_id):
    """An app id of the core's form and of its profile's (Annex A)."""
    pattern = (PROFILES.get(platform) or {}).get("id")
    return isinstance(app_id, str) and bool(CORE_ID.match(app_id)) and (pattern is None or bool(pattern.match(app_id)))


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
    """An absolute HTTPS URL; a malformed one (an unclosed IPv6 bracket…) is none, never an error."""
    if not (isinstance(value, str) and len(value) <= 4096):
        return False
    try:
        u = urlsplit(value)
    except ValueError:
        return False
    return u.scheme == "https" and bool(u.netloc)


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


def signed_bytes(doc, package=None):
    """The bytes an author signs (SPEC.md § 8.4), over the entry's package or another of its packages."""
    p = package or doc["package"]
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
    if https_url(value):
        return {"url": value, "external": True}
    return None


def best_language(prefs):
    """The language of this server's own texts for the client's languages (SPEC.md § 2.2): one of the fifteen
    of server/texts.py, else English."""
    return texts.best(prefs)


class Problem(Exception):
    """An error answered as application/problem+json (SPEC.md § 12)."""

    def __init__(self, status, code, title, detail=None, headers=None):
        super().__init__(title)
        self.status, self.code, self.title, self.detail = status, code, title, detail
        self.headers = headers or {}

    def document(self, language="en"):
        """The problem in `language` (SPEC.md § 2.2): English, or one of server/texts.py's languages."""
        title, detail = self.title, self.detail
        translated = texts.error(self.code, language)
        if translated:
            title, generic = translated
            detail = generic if detail else None
        else:
            language = "en"
        doc = {"schema": 1, "type": f"https://lantern.boreale.dev/errors/{self.code.replace('_', '-')}",
               "title": title, "status": self.status, "code": self.code, "language": language}
        if detail:
            doc["detail"] = clip(detail, 4096)
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


def grant_payload(uid, sha256, size, exp):
    """A grant's payload (SPEC.md § 19.3): these keys in this order, no space."""
    return ('{"exp":%d,"purpose":"lantern-grant-1","sha256":"%s","size":%d,"uid":"%s"}'  # noqa: UP031 - the canonical bytes
            % (exp, sha256, size, uid)).encode()


def make_grant(seed, uid, sha256, size, exp):
    payload = grant_payload(uid, sha256, size, exp)
    return b64url(payload) + "." + b64url(ed25519.sign(seed, payload))


def read_grant(grant, keys, now=None):
    """The payload of a grant that verifies by the key of the server it names, among `keys` ({uid: the public
    key's 32 bytes}), and is not expired (SPEC.md § 19.4); None otherwise."""
    if not (isinstance(grant, str) and len(grant) <= 1024 and re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{86}", grant)):
        return None
    payload_b64, sig_b64 = grant.split(".")
    try:
        payload, signature = unb64url(payload_b64), unb64url(sig_b64)
        doc = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not (isinstance(doc, dict) and doc.get("purpose") == "lantern-grant-1" and isinstance(doc.get("uid"), str)
            and isinstance(doc.get("sha256"), str) and is_int(doc.get("exp")) and is_int(doc.get("size"))):
        return None
    key = keys.get(doc["uid"])
    if key is None or payload != grant_payload(doc["uid"], doc["sha256"], doc["size"], doc["exp"]):
        return None
    if doc["exp"] < (time.time() if now is None else now) or not ed25519.verify(key, payload, signature):
        return None
    return doc


def homebrew_view(entry, full, prefs):
    """A homebrew entry as served (SPEC.md § 8.1): its texts in the client's language, and without its manifests
    in a listing (`full` False)."""
    doc = dict(entry["doc"])
    if not full:
        doc["package"] = {k: v for k, v in doc["package"].items() if k != "manifest"}
        if "packages" in doc:
            doc["packages"] = [{k: v for k, v in p.items() if k != "manifest"} for p in doc["packages"]]
    language = None
    for k, value in entry["texts"].items():
        doc[k], lang = localized(value, prefs)
        language = language or lang
    if language:
        doc["language"] = language
    if "port" in doc:
        doc["port"] = json.loads(json.dumps(doc["port"]))
        for f in data_files(doc["port"].get("requires_data", [])):
            if "hint" in f:
                f["hint"] = localized(localizable(f["hint"]), prefs)[0]
    return doc


def request_event(r):
    """A request's event (SPEC.md § 18.2)."""
    return {"schema": 1, **{k: r[k] for k in ("id", "platform", "title_id", "status") if k in r}}


def mirrors_of(value):
    """A file's mirrors from library.json or homebrew.json (SPEC.md § 19.2): [{"url"}], each an HTTPS URL, or
    an HTTP one at an address of a private network; None when absent, False when not of that form."""
    if value is None:
        return None
    if not (isinstance(value, list) and len(value) <= MIRRORS_LIMIT and all(
            isinstance(m, dict) and mirror_url_ok(m.get("url")) for m in value)):
        return False
    return [{"url": m["url"]} for m in value]


def mirror_url_ok(url):
    if https_url(url):
        return True
    if not (isinstance(url, str) and len(url) <= 4096):
        return False
    try:
        u = urlsplit(url)
        ip = ipaddress.ip_address((u.hostname or "").split("%")[0])
    except ValueError:
        return False
    return u.scheme == "http" and any(ip in net for net in PRIVATE_NETS)


def ratings_of(items):
    """Age ratings from a file, checked (SPEC.md § 7.1): [{"system", "rating"}]."""
    return [{"system": r["system"], "rating": plain(r["rating"], 16)} for r in items
            if isinstance(r, dict) and isinstance(r.get("system"), str)
            and RATING_SYSTEM.match(r["system"]) and plain(r.get("rating"), 16)]


def rating_cap_problem(cap):
    """Why a rating cap breaks SPEC.md § 5.6, or None."""
    if not isinstance(cap, dict) or set(cap) - {"age", "system", "rating", "unrated"}:
        return "rating_cap is {age} or {system, rating}, and unrated"
    if cap.get("unrated", "show") not in ("show", "hide"):
        return "rating_cap.unrated is show or hide"
    if "age" in cap:
        if "system" in cap or "rating" in cap or not (is_int(cap["age"]) and cap["age"] <= 99):
            return "rating_cap.age is an age, 0 to 99, alone"
        return None
    if not (isinstance(cap.get("system"), str) and RATING_SYSTEM.match(cap["system"])
            and isinstance(cap.get("rating"), str) and 0 < len(cap["rating"]) <= 16):
        return "rating_cap is {age} or {system, rating}"
    if RATING_AGES.get(cap["system"], {}).get(cap["rating"]) is None:
        return f"{cap['system']} {cap['rating']}: a rating SPEC.md § 5.6's table does not read"
    return None


def rating_age(ratings, cap):
    """The age SPEC.md § 5.6 reads in `ratings` for `cap`; None when unrated."""
    def age(r):
        system, rating = r.get("system"), r.get("rating")
        return RATING_AGES.get(system, {}).get(rating) if isinstance(system, str) and isinstance(rating, str) else None
    if "system" in cap:
        own = [a for a in (age(r) for r in ratings if r.get("system") == cap["system"]) if a is not None]
        if own:
            return max(own)
    ages = [a for a in map(age, ratings) if a is not None]
    return max(ages) if ages else None


def above_cap(ratings, cap):
    """Whether a token of `cap` must not see what has these `ratings` (SPEC.md § 5.6)."""
    if not cap:
        return False
    limit = cap["age"] if "age" in cap else RATING_AGES.get(cap.get("system"), {}).get(cap.get("rating"))
    age = rating_age(ratings or [], cap)
    if age is None:
        return cap.get("unrated") == "hide"
    return limit is None or age > limit


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
        meta["ratings"] = ratings_of(entry["ratings"])
    if isinstance(entry.get("atlas"), str) and ATLAS.match(entry["atlas"]):
        meta["atlas"] = entry["atlas"]
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
        # The grant key (SPEC.md § 19.3): the server's own, for grants alone; its seed stays in the state file.
        if not (isinstance(self.state.get("grant_seed"), str) and re.fullmatch(r"[0-9a-f]{64}", self.state["grant_seed"])):
            self.state["grant_seed"] = secrets.token_hex(32)
        self.grant_seed = bytes.fromhex(self.state["grant_seed"])
        self.grant_public = ed25519.public_key(self.grant_seed)
        self.secret = bytes.fromhex(self.state["secret"])
        self.epoch = secrets.token_hex(4)   # since tokens do not outlive the process
        self.seq = 0
        self.journal = []                   # (seq, kind, ref, platform): kind added | removed | title | untitled
        self.events = []                    # SPEC.md § 18: {seq, event, data, audience, items}, in order
        self.changed = threading.Condition(self.lock)   # notified at each event
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
        if profile and profile["formats"] is not None and ext not in profile["formats"]:
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
            app_id = entry.get("app_id") if app_id_ok(platform, entry.get("app_id")) else title_id
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
        if is_int(entry.get("installed_size")):
            app["installed_size"] = entry["installed_size"]
        if isinstance(entry.get("atlas"), str) and ATLAS.match(entry["atlas"]):
            app["atlas"] = entry["atlas"]
        mirrors = mirrors_of(entry.get("mirrors"))
        if mirrors is False:
            self.skip(rel + " (mirrors)", "mirrors are [{url}], HTTPS, or HTTP on a private network (SPEC.md § 19.2)")
        elif mirrors:
            app["mirrors"] = mirrors
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
                files[fid] = {"path": path, "size": st.st_size, "sha256": sha,
                              "owner": ("app", app["platform"], app["title_id"])}
            mark = self.seq
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
            if not initial:
                items = self.library_changes(mark, apps, homebrew, cheats)
                if items:
                    self.emit("library", items=items)
            arrived = set(titles) - set(self.titles)
            self.apps, self.files, self.titles, self.homebrew, self.cheats = apps, files, titles, homebrew, cheats
            if not initial:
                self.requests_done(arrived)
            self.scanned = time.monotonic()
            if self.dirty:
                self.save_state()

    def library_changes(self, mark, apps, homebrew, cheats):
        """What a scan changed (SPEC.md § 18.2's event library): (family, platform, how, ref) for each app,
        title, homebrew and cheat set added, removed or changed, `how` saying how a rating cap reads it: by its
        title's ratings ("title", the title id) or by its own ("ratings", them as JSON)."""
        items = set()
        for seq, kind, ref, platform in self.journal:
            if seq <= mark:
                continue
            if kind in ("added", "removed"):
                doc = (apps.get(ref) or self.apps.get(ref) or {}).get("doc", {})
                items.add(("apps", platform, "title", doc.get("title_id", "")))
            elif kind in ("title", "untitled"):
                items.add(("titles", platform, "title", ref.split("/", 1)[1]))
        old = self.homebrew
        for key in old.keys() | homebrew.keys():
            a, b = (old.get(key) or {}).get("doc"), (homebrew.get(key) or {}).get("doc")
            if a != b:
                ratings = json.dumps((b or a).get("ratings", []), sort_keys=True)
                items.add(("homebrew", key[0], "ratings", ratings))
        for cid in self.cheats.keys() | cheats.keys():
            a, b = (self.cheats.get(cid) or {}).get("doc"), (cheats.get(cid) or {}).get("doc")
            if a != b:
                doc = b or a
                items.add(("cheats", doc["platform"], "title", doc["title_id"]))
        return sorted(items)

    def emit(self, event, data=None, audience=None, items=None):
        """Records an event (SPEC.md § 18), its id the next token of /v1/changes, and wakes the streams and
        long polls. `audience`: {"user"?, "platform"?} beside the event's scope; `items`: a library event's."""
        with self.lock:
            seq = self.next_seq()
            self.events.append({"seq": seq, "event": event, "data": data or {"schema": 1},
                                "audience": audience or {}, "items": items or []})
            if len(self.events) > EVENTS_LIMIT:
                self.floor = max(self.floor, self.events[-EVENTS_LIMIT - 1]["seq"])
                del self.events[:-EVENTS_LIMIT]
            self.changed.notify_all()
            return seq

    def token(self, seq):
        """The token of /v1/changes (and an event's id) at `seq` (SPEC.md § 6.4, § 18.1)."""
        return f"s_{self.epoch}_{seq}"

    def requests_done(self, arrived):
        """An open request whose title just arrived in the library (`arrived`, keys of titles a scan found new) is
        done (SPEC.md § 11), and its event sent (§ 18.2)."""
        for r in self.requests():
            if isinstance(r, dict) and r.get("status") == "open" and f"{r.get('platform')}/{r.get('title_id')}" in arrived:
                r["status"] = "done"
                self.dirty = True
                self.emit("request", request_event(r), {"user": r.get("user"), "platform": r.get("platform")})

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
            if meta is not None and "packages" in meta:
                # One entry, a package per architecture (SPEC.md § 8.2): homebrew.json names each file.
                found = self.listed_packages(folder, packages, meta["packages"])
                groups = [(found, meta)] if found else []
            else:
                groups = [([path], meta if meta and (meta.get("file") == path.name
                                                     or (not meta.get("file") and len(packages) == 1)) else {})
                          for path in packages]
            for paths, mine in groups:
                entry = self.homebrew_entry(paths, mine, seen, files)
                if entry is None:
                    continue
                key = (entry["doc"]["platform"], entry["doc"]["id"])
                if key in out:
                    self.skip(paths[0].relative_to(self.root).as_posix(), f"a second homebrew {key[1]} on {key[0]}")
                    continue
                out[key] = entry
        return out

    def listed_packages(self, folder, packages, listed):
        """The files homebrew.json's `packages` names, in its order; None (and every file skipped) when it
        names a file twice, one that is not there, more than the limit, or leaves one of the folder out."""
        by_name = {p.name: p for p in packages}
        names = [i.get("file") if isinstance(i, dict) else None for i in listed] if isinstance(listed, list) else []
        why = None
        if not names or len(names) > 1 + PACKAGES_LIMIT:
            why = f"homebrew.json's packages lists 1 to {1 + PACKAGES_LIMIT} files"
        elif len(set(names)) != len(names) or any(n not in by_name for n in names):
            why = "homebrew.json's packages names a file twice, or one that is not in its folder"
        if why:
            for path in packages:
                self.skip(path.relative_to(self.root).as_posix(), why)
            return None
        for path in packages:
            if path.name not in names:
                self.skip(path.relative_to(self.root).as_posix(), "not one of homebrew.json's packages")
        return [by_name[n] for n in names]

    def homebrew_package(self, path, item, platform, profile, hid, seen):
        """One package of an entry (SPEC.md § 8.2): (package, its manifest, its file id), or None when refused."""
        rel = path.relative_to(self.root).as_posix()
        ext = path.suffix.lower()[1:]
        if ext not in profile["homebrew"]:
            self.skip(rel, f"no {ext} homebrew on {platform}")
            return None
        st = path.stat()
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
            target = item.get("path") if device_path_ok(item.get("path")) else place.format(id=hid, file=path.name)
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
        if place != "system":
            package["installed_size"] = sum(m["size"] for m in manifest)
        arch = item.get("arch")
        if arch is not None:
            if platform in ONE_ARCH:
                self.skip(rel, f"{platform} has one architecture: no arch (Annex A)")
                return None
            if not (isinstance(arch, list) and 1 <= len(arch) <= 8 and len(set(arch)) == len(arch)
                    and all(isinstance(a, str) and ARCH.match(a) for a in arch)):
                self.skip(rel, f"arch is a list of architectures, such as aarch64 ({str(arch)[:40]})")
                return None
            package["arch"] = arch
        if item.get("signer_sha256") is not None:
            if not (isinstance(item["signer_sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", item["signer_sha256"])):
                self.skip(rel, "signer_sha256 is a lower-case hex SHA-256")
                return None
            package["signer_sha256"] = item["signer_sha256"]
        mirrors = mirrors_of(item.get("mirrors"))
        if mirrors is False:
            self.skip(rel, "mirrors are [{url}], HTTPS, or HTTP on a private network (SPEC.md § 19.2)")
            return None
        if mirrors:
            package["mirrors"] = mirrors
        return package, manifest, {"fid": fid, "path": path, "size": st.st_size, "sha256": sha, "mtime": st.st_mtime_ns}

    def homebrew_requires(self, requires, rel):
        """requires as served (SPEC.md § 8.7): the conditions this server reads checked for their form (an
        entry with a malformed one is not served, rather than served without it), the others kept as given;
        None when it is not served at all (no text), False when the entry is refused."""
        if not (isinstance(requires, dict) and plain(requires.get("text"), 4096)):
            return None
        out = {k: clean(v) for k, v in requires.items() if isinstance(k, str) and k not in REQUIRES_KEYS}
        out["text"] = plain(requires["text"], 4096)
        if "min" in requires:
            low = requires["min"]
            if not isinstance(low, dict) or not all(isinstance(k, str) and WORD.match(k) for k in low):
                self.skip(rel, "requires.min is an object of lower-case keys")
                return False
            for k, v in low.items():
                ok = (is_int(v) and 1 <= v <= 1 << 24) if k == "ram_mb" else \
                    (isinstance(v, str) and SCREEN.match(v)) if k == "screen" else \
                    (isinstance(v, str) and DOTTED.match(v)) if k in DOTTED_KEYS else \
                    (isinstance(v, str) and 1 <= len(v) <= 64) or is_int(v)
                if not ok:
                    self.skip(rel, f"requires.min.{k}: {str(v)[:40]!r} is not of its form (SPEC.md § 8.7)")
                    return False
            out["min"] = dict(low)
        if "gpu" in requires:
            gpu = requires["gpu"]
            if not (isinstance(gpu, list) and 1 <= len(gpu) <= 8 and len(set(map(str, gpu))) == len(gpu)
                    and all(g in GPU for g in gpu)):
                self.skip(rel, "requires.gpu lists " + ", ".join(GPU) + " (SPEC.md § 8.7)")
                return False
            out["gpu"] = list(gpu)
        if isinstance(requires.get("homebrew"), list):
            out["homebrew"] = [{"id": h["id"], "min_build": h["min_build"]} for h in requires["homebrew"]
                               if isinstance(h, dict) and HOMEBREW_ID.match(str(h.get("id", ""))) and is_int(h.get("min_build"))]
        return out

    def homebrew_entry(self, paths, meta, seen, files):
        first = paths[0]
        rel = first.relative_to(self.root).as_posix()
        ext = first.suffix.lower()[1:]
        platform = meta.get("platform") if PLATFORM.match(str(meta.get("platform", ""))) else HOMEBREW_EXT[ext]
        profile = PROFILES.get(platform)
        if profile is None:
            self.skip(rel, f"no homebrew on {platform}, which has no profile")
            return None
        info = {}
        if ext == "nro":
            with first.open("rb") as f:
                info = nro.read_nro(f, first.stat().st_size) or {}
        hid = meta.get("id") if HOMEBREW_ID.match(str(meta.get("id", ""))) else \
            "local." + (re.sub(r"[^a-z0-9]+", "-", first.stem.lower()).strip("-") or "homebrew")
        name = plain(meta.get("name")) or info.get("name") or first.stem
        version = plain(meta.get("version")) or info.get("version") or "0"
        build = meta["build"] if is_int(meta.get("build")) else build_of(version)
        if "packages" in meta:
            items = [i for i in meta["packages"]]
        else:
            items = [{k: meta.get(k) for k in ("arch", "signature", "signer_sha256", "path", "mirrors")}]
        if len(items) > 1 and platform in ONE_ARCH:
            self.skip(rel, f"{platform} has one architecture: one package (Annex A)")
            return None
        built = [self.homebrew_package(path, item, platform, profile, hid, seen) for path, item in zip(paths, items)]
        if None in built:
            return None
        if any("arch" not in package for package, _, _ in built[1:]):
            self.skip(rel, "each package after the first names its arch (SPEC.md § 8.2)")
            return None
        doc = {"id": hid, "platform": platform, "name": name, "version": version, "build": build}
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
        genres = meta.get("genres")
        if genres is not None:
            if not (isinstance(genres, list) and all(g in GENRES for g in genres)):
                self.skip(rel, "genres lists " + ", ".join(GENRES) + " (SPEC.md § 7.1)")
                return None
            doc["genres"] = list(dict.fromkeys(genres))
        if isinstance(meta.get("tags"), list):
            doc["tags"] = [t for t in (plain(x, 64) for x in meta["tags"][:TAGS_LIMIT]) if t]
        if isinstance(meta.get("ratings"), list):
            doc["ratings"] = ratings_of(meta["ratings"])
        if isinstance(meta.get("atlas"), str) and ATLAS.match(meta["atlas"]):
            doc["atlas"] = meta["atlas"]
        requires = self.homebrew_requires(meta.get("requires"), rel)
        if requires is False:
            return None
        if requires:
            doc["requires"] = requires
        kind = meta.get("kind")
        doc["kind"] = kind if kind in KINDS else "app"     # SPEC.md § 8.1: an unknown kind is an app
        if meta.get("assets_license") is not None:
            if not (isinstance(meta["assets_license"], str) and SPDX.match(meta["assets_license"])):
                self.skip(rel, "assets_license is an SPDX expression")
                return None
            doc["assets_license"] = meta["assets_license"]
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
            shipped = {m["path"] for _, manifest, _ in built for m in manifest}
            served = {f["sha256"] for _, _, f in built} | {m["sha256"] for _, manifest, _ in built for m in manifest}
            for f in data_files(port.get("requires_data", [])):
                if port["data_root"] + f["path"] in shipped or any(a.get("sha256") in served for a in f.get("accept", [])):
                    self.skip(rel, "it holds a file the user brings from their own copy (requires_data)")
                    return None
            doc["port"] = clean(port)       # a copy; its hints are localized when served
            if doc["port"]["assets"] not in ASSETS:
                doc["port"]["assets"] = "user_owned"    # SPEC.md § 8.6: an unknown one reads so
        mtimes = [f["mtime"] for _, _, f in built]
        try:
            mtimes.append((first.parent / "homebrew.json").stat().st_mtime_ns)
        except OSError:
            pass
        doc["updated"] = utc(max(mtimes))
        signatures = []
        for (package, _, _), item in zip(built, items):
            signature = item.get("signature")
            if isinstance(signature, dict) and signature.get("alg") == "ed25519" \
                    and re.fullmatch(r"[A-Za-z0-9+/]{43}=", str(signature.get("public_key", ""))) \
                    and re.fullmatch(r"[A-Za-z0-9+/]{86}==", str(signature.get("value", ""))):
                signature = {"alg": "ed25519", "public_key": signature["public_key"], "value": signature["value"]}
                if not self.verified(signed_bytes(doc, package), signature):
                    self.skip(rel, "its signature does not verify (SPEC.md § 8.4)")
                    return None
                signatures.append(signature)
            elif signature is not None:
                self.skip(rel, "its signature is not an ed25519 one")
                return None
            else:
                signatures.append(None)
        if any(signatures) and (None in signatures or len({s["public_key"] for s in signatures}) > 1):
            self.skip(rel, "a signed entry has every package signed, by the same key (SPEC.md § 8.4)")
            return None
        doc["package"] = built[0][0]
        if len(built) > 1:
            doc["packages"] = [package for package, _, _ in built[1:]]
            for package, signature in zip(doc["packages"], signatures[1:]):
                if signature:
                    package["signature"] = signature
        if signatures[0]:
            doc["signature"] = signatures[0]
        texts = {k: localizable(meta.get(k)) for k in ("summary", "description") if localizable(meta.get(k))}
        for _, _, f in built:
            files[f["fid"]] = {"path": f["path"], "size": f["size"], "sha256": f["sha256"],
                               "owner": ("homebrew", platform, hid)}
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
                links = [i.filename for i in members if (i.external_attr >> 16) & 0o170000 == 0o120000]
                bad = next((i.filename for i in members if not device_path_ok("/" + i.filename)), None)
                lower = [("/" + i.filename).casefold() for i in members]
                if len(members) > MANIFEST_LIMIT:
                    self.skip(rel, f"{len(members)} files, above {MANIFEST_LIMIT}")
                elif links:
                    self.skip(rel, f"a link, where a client writes only files ({links[0]!r})")
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
        except (zipfile.BadZipFile, OSError, ValueError, NotImplementedError, RuntimeError, EOFError, zlib.error) as e:
            self.skip(rel, f"not a zip this server can read ({e})")
        self.manifests = {k: v for k, v in self.manifests.items() if k[0] != rel}
        self.manifests[memo] = manifest
        return manifest

    # Cheats (SPEC.md § 10).

    def cheat_index(self):
        """cheats/index.json: the notes of the sets written through the API ({"schema":1, "notes":{path: note}}),
        None when it is of a newer schema (then it is never written over, and no set is written)."""
        path = self.root / "cheats" / "index.json"
        doc = read_versioned(path, "cheats/index.json")
        if doc is None:
            return None if path.exists() else {"schema": 1, "notes": {}}
        if not isinstance(doc.get("notes"), dict):
            doc["notes"] = {}
        return doc

    def scan_cheats(self, seen):
        root = self.root / "cheats"
        out = {}
        if not root.is_dir():
            return out
        notes = (self.cheat_index() or {}).get("notes", {})
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
            note = plain(notes.get(path.relative_to(root).as_posix()), 120)
            if note:
                out[cid]["doc"]["note"] = note
        return out

    def write_cheat(self, fields, replacing=None):
        """Writes a cheat set (SPEC.md § 10) to cheats/<platform>/<title id>/<build id>/<source>.txt, its note
        to cheats/index.json, and rescans; the new set's document. `replacing`: the set a PUT replaces."""
        root = self.root / "cheats"
        with self.lock:
            index = self.cheat_index()
            if index is None:
                raise Problem(503, "unavailable", "Unavailable", "cheats/index.json is of a newer schema than this "
                              "server: it writes no cheat set.", {"Retry-After": "3600"})
            rel = "/".join((fields["platform"], fields["title_id"], fields["build_id"],
                            fields["source"].replace(" ", "_") + ".txt"))
            target = root / rel
            if replacing is None:
                twins = [target] + ([root / rel.split("/", 1)[1]] if fields["platform"] == "switch" else [])
                if any(t.exists() for t in twins):
                    raise Problem(409, "conflict", "Conflict", "A set of this source exists for this build: "
                                  "PUT replaces it.")
            elif replacing["path"] != target:
                raise bad_request("PUT replaces a set's text and note; its platform, title_id, build_id and "
                                  "source stay those of the set.")
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".tmp")
            tmp.write_text(fields["text"], encoding="utf-8")
            tmp.replace(target)
            key = target.relative_to(root).as_posix()
            if fields.get("note"):
                index["notes"][key] = fields["note"]
            else:
                index["notes"].pop(key, None)
            write_json(root / "index.json", index)
            self.scan()
            return next(e["doc"] for e in self.cheats.values() if e["path"] == target)

    def delete_cheat(self, entry):
        root = self.root / "cheats"
        with self.lock:
            index = self.cheat_index()
            if index is None:
                raise Problem(503, "unavailable", "Unavailable", "cheats/index.json is of a newer schema than this "
                              "server: it deletes no cheat set.", {"Retry-After": "3600"})
            path = entry["path"]
            path.unlink(missing_ok=True)
            if index["notes"].pop(path.relative_to(root).as_posix(), None) is not None:
                write_json(root / "index.json", index)
            folder = path.parent
            while folder != root and folder.is_dir() and not any(folder.iterdir()):
                folder.rmdir()
                folder = folder.parent
            self.scan()

    # Requests (SPEC.md § 11), kept in the state file.

    def requests(self):
        if not isinstance(self.state.get("requests"), list):
            self.state["requests"] = []
        return self.state["requests"]

    def request(self, user, platform, title_id):
        """(201 or 200, the request): a new one, or the account's open one for the same title."""
        with self.lock:
            mine = [r for r in self.requests() if isinstance(r, dict) and r.get("user") == user]
            same = next((r for r in mine if r.get("status") == "open" and r.get("platform") == platform
                         and r.get("title_id") == title_id), None)
            if same is not None:
                return 200, same
            if sum(r.get("status") == "open" for r in mine) >= REQUESTS_OPEN:
                raise slow_down(3600, f"At most {REQUESTS_OPEN} open requests per account.")
            entry = {"id": "r_" + secrets.token_urlsafe(9), "user": user, "platform": platform,
                     "title_id": title_id, "status": "open", "created": now_utc()}
            title = next((t for t in self.titles.values() if t.get("platform") == platform
                          and t.get("title_id") == title_id), None)
            if title and title.get("name"):
                entry["name"] = title["name"]
            self.requests().append(entry)
            self.save_state()
            self.emit("request", request_event(entry), {"user": user, "platform": platform})
            return 201, entry

    def withdraw(self, user, rid):
        """Removes the account's own request `rid` (SPEC.md § 11); False when it has none of that id."""
        with self.lock:
            kept = [r for r in self.requests() if not (isinstance(r, dict) and r.get("user") == user
                                                       and r.get("id") == rid)]
            if len(kept) == len(self.requests()):
                return False
            gone = next(r for r in self.requests() if isinstance(r, dict) and r.get("user") == user and r.get("id") == rid)
            self.state["requests"] = kept
            self.save_state()
            self.emit("request", {"schema": 1, "id": rid, "platform": gone.get("platform"),
                                  "title_id": gone.get("title_id"), "deleted": True},
                      {"user": user, "platform": gone.get("platform")})
            return True

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
        for k in ("atlas", "publisher", "developer", "genres", "tags", "players", "ratings", "languages", "icon",
                  "banner", "screenshots", "video"):
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
              "profile", "slot", "note", "device", "encryption")

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
                with part.open("rb") as f:
                    archive_check(f.read(16), part, s.get("encryption"))
                fields = {k: s[k] for k in self.PUBLIC if k in s and k not in ("size", "sha256")}
                return self.add(s["user"], part, s["sha256"], s["size"], fields)
            finally:
                if part.exists():
                    part.unlink()
                self.write()

    def delete_user(self, user):
        """Erases every backup and upload of an account (SPEC.md § 5.7)."""
        with self.lock:
            for entry in self.mine(user):
                self.drop(entry)
            for uid, sess in list(self.index["uploads"].items()):
                if isinstance(sess, dict) and sess.get("user") == user:
                    self.abandon(uid, write=False)
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


def archive_check(start, path, encryption):
    """A backup's bytes as SPEC.md § 9 and § 9.4 want them: a zip in clear; encrypted, the header of
    lantern-save-e2e-1 with the key id of its metadata. 400 otherwise."""
    if encryption:
        if start[:8] != E2E_MAGIC or start[8:16].hex() != encryption["key_id"]:
            raise bad_request("An encrypted backup begins with LTNE2E01 and its key id (SPEC.md § 9.4); this one "
                              "was discarded.")
    elif not zipfile.is_zipfile(path):
        raise bad_request("A save is a zip archive; this one was discarded.")


def encryption_of(value):
    """A backup's encryption (SPEC.md § 9.4): {"scheme", "key_id"} of lantern-save-e2e-1; 400 otherwise."""
    if not (isinstance(value, dict) and value.get("scheme") == E2E_SCHEME and isinstance(value.get("key_id"), str)
            and KEY_ID.match(value["key_id"])):
        raise bad_request(f"encryption is {{scheme: {E2E_SCHEME}, key_id: 16 hex digits}} (SPEC.md § 9.4).")
    return {"scheme": E2E_SCHEME, "key_id": value["key_id"]}


def encryption_header(header):
    """Lantern-Save-Encryption: lantern-save-e2e-1; key_id=<16 hex> (SPEC.md § 9.4), as encryption_of() reads it."""
    scheme, _, params = header.partition(";")
    fields = dict(p.strip().partition("=")[::2] for p in params.split(";") if p.strip())
    return encryption_of({"scheme": scheme.strip(), "key_id": fields.get("key_id")})


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
    """users.json (SPEC.md § 5): who may sign in on /pair, and with which scopes;
    and what the administration API changed or made (SPEC.md § 5.7), kept in
    the state file under "accounts": {name: {"scopes"?, "state"?, "created"?}},
    which overrides users.json's scopes and state, and holds the accounts made
    without a password."""

    def __init__(self, path):
        self.public, self.users, self.store = True, {}, None
        self.pairing = path is not None     # a server with accounts pairs (a private one MUST)
        if path is None:
            return
        doc = read_versioned(Path(path), "users file")
        self.public = bool(doc and doc.get("public"))   # unreadable or newer: private, nobody signs in
        for u in (doc or {}).get("users", []):
            if isinstance(u, dict) and isinstance(u.get("name"), str) and isinstance(u.get("password"), str):
                self.users[u["name"]] = u

    def attach(self, store):
        """The Library whose state keeps the administration's changes."""
        self.store = store

    def changes(self):
        if self.store is None:
            return {}
        table = self.store.state.get("accounts")
        if not isinstance(table, dict):
            table = self.store.state["accounts"] = {}
        return table

    def get(self, name):
        """The account `name`, users.json's with the administration's changes; None when there is none."""
        if not isinstance(name, str):
            return None
        base, extra = self.users.get(name), self.changes().get(name)
        if base is None and not isinstance(extra, dict):
            return None
        user = dict(base or {"name": name, "scopes": [], "state": "active"})
        if isinstance(extra, dict):
            user.update({k: extra[k] for k in ("scopes", "state", "created") if k in extra})
        return user

    def names(self):
        return sorted(set(self.users) | {n for n, v in self.changes().items() if isinstance(v, dict)})

    def anonymous(self):
        return {"state": "anonymous", "scopes": ["library"] if self.public else []}

    def scopes(self, user):
        return [s for s in user.get("scopes", []) if s in SCOPES]

    def sign_in(self, name, password):
        """The user, when the password is theirs; None otherwise."""
        user = self.users.get(name)
        ok = check_password(password, user["password"] if user else NO_USER)
        return self.get(name) if ok and user else None

    def create(self, name, scopes, state="active"):
        """A new account, without a password (SPEC.md § 5.7); 409 when the name is taken."""
        with self.store.lock:
            if self.get(name) is not None:
                raise Problem(409, "conflict", "Conflict", f"An account named {name} exists already.")
            self.changes()[name] = {"scopes": list(scopes), "state": state, "created": now_utc()}
            self.store.save_state()
        return self.get(name)

    def update(self, name, state=None, scopes=None):
        with self.store.lock:
            if self.get(name) is None:
                raise not_found("No such account.")
            entry = self.changes().setdefault(name, {})
            if state is not None:
                entry["state"] = state
            if scopes is not None:
                entry["scopes"] = list(scopes)
            self.store.save_state()
        return self.get(name)

    def delete(self, name):
        """Removes an account the administration API made (SPEC.md § 5.7); 409 for one users.json defines, which
        this server only reads. What belongs to the account is erased by LanternServer.delete_account()."""
        with self.store.lock:
            if name in self.users:
                raise Problem(409, "conflict", "Conflict", f"The account {name} is defined in the server's users "
                              "file, which it only reads: remove it there.")
            self.changes().pop(name, None)
            self.store.save_state()

    def resolve(self, header, tokens):
        """(the caller's account, its token's record) from its bearer token, or a 401 Problem (SPEC.md § 5.1)."""
        if not header:
            return self.anonymous(), None
        scheme, _, value = header.strip().partition(" ")
        if scheme.lower() != "bearer" or not value.strip():
            raise unauthorized(CHALLENGE, "Send a token from pairing: Authorization: Bearer <token>.")
        record = tokens.find(value.strip())
        user = self.get(record["user"]) if record else None
        if user is None:
            raise unauthorized(CHALLENGE + ', error="invalid_token"', "Unknown, revoked or expired token.")
        mine = self.scopes(user)
        scopes = [s for s in record.get("scopes", []) if s in mine]
        state = "frozen" if user.get("state") == "frozen" else "active"
        account = {"name": clip(user["name"]), "state": state, "scopes": scopes, "bound": bool(record.get("key"))}
        if isinstance(record.get("rating_cap"), dict):
            account["rating_cap"] = record["rating_cap"]
        return account, record


# --- Sync (SPEC.md § 20) ------------------------------------------------------

def sync_time(text, now, skew):
    """An item's `updated`, to the millisecond (2026-10-30T09:12:03.250Z), one more than `skew` seconds ahead of
    `now` (a datetime) taken as `now` (SPEC.md § 20.4); None when it is not such a time."""
    m = UPDATED.match(text) if isinstance(text, str) else None
    if not m:
        return None
    try:
        when = datetime.fromisoformat(m.group(1) + (m.group(2) or ".0").ljust(4, "0") + "+00:00")
    except ValueError:
        return None
    if when > now + timedelta(seconds=skew):
        when = now
    return when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z"


def canonical(value):
    """A value's canonical JSON (SPEC.md § 20.4): keys sorted, no space, characters other than ASCII as they are."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sync_wins(sent, have):
    """Whether the item sent replaces the one kept (SPEC.md § 20.4's merge rule): the later `updated`; on the same,
    a deletion; between two values, the greater canonical JSON. An item the same as the one kept does not."""
    if have is None:
        return True
    if sent["updated"] != have["updated"]:
        return sent["updated"] > have["updated"]
    deleted, kept_deleted = bool(sent.get("deleted")), bool(have.get("deleted"))
    if deleted != kept_deleted:
        return deleted
    return not deleted and canonical(sent["value"]) > canonical(have["value"])


class Sync:
    """Sync data (SPEC.md § 20) in a file (schema 1): {"accounts": {name: {"generation", "collections":
    {collection: {"rev", "floor", "items": {key: item}}}}}}, an item {"key", "value" or "deleted", "updated",
    "rev", "kept"}, `kept` the server's time when it took it, for a deletion's retention, `floor` the revision
    below which deletions were dropped. A file of a newer schema, or unreadable, makes the family unavailable,
    and is never written over; its unknown keys are kept."""

    def __init__(self, path, limit=SYNC_ITEMS, skew=signatures.SKEW):
        self.path, self.limit, self.skew = Path(path), limit, skew
        self.lock = threading.RLock()
        doc = read_versioned(self.path, "sync file")
        self.available = doc is not None or not self.path.exists()
        self.doc = doc or {"schema": 1}
        if not isinstance(self.doc.get("accounts"), dict):
            self.doc["accounts"] = {}

    def write(self):
        if self.available:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            write_json(self.path, self.doc)

    def account(self, user):
        acc = self.doc["accounts"].get(user)
        if not (isinstance(acc, dict) and isinstance(acc.get("generation"), str)):
            acc = self.doc["accounts"][user] = {"generation": "g_" + secrets.token_urlsafe(9), "collections": {}}
        if not isinstance(acc.get("collections"), dict):
            acc["collections"] = {}
        return acc

    def collection(self, user, name):
        acc = self.account(user)
        col = acc["collections"].get(name)
        if not (isinstance(col, dict) and is_int(col.get("rev")) and isinstance(col.get("items"), dict)):
            col = acc["collections"][name] = {"rev": 0, "floor": 0, "items": {}}
        self.purge(col)
        return acc, col

    @staticmethod
    def purge(col):
        """Drops the deletions kept longer than TOMBSTONE_DAYS (SPEC.md § 20.5), and raises the floor."""
        limit = (datetime.now(timezone.utc) - timedelta(days=TOMBSTONE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for key, item in list(col["items"].items()):
            if isinstance(item, dict) and item.get("deleted") and str(item.get("kept", "")) < limit:
                col["floor"] = max(col.get("floor", 0), item.get("rev", 0))
                del col["items"][key]

    @staticmethod
    def public(item):
        return {k: item[k] for k in ("key", "value", "deleted", "updated", "rev") if k in item}

    def overview(self, user):
        with self.lock:
            acc = self.account(user)
            out = {}
            for name in SYNC_COLLECTIONS:
                _, col = self.collection(user, name)
                out[name] = {"rev": col["rev"], "items": sum(1 for i in col["items"].values() if not i.get("deleted"))}
            self.write()
            return acc["generation"], out

    def read(self, user, name, since):
        """(generation, rev, items): with `since`, every item changed after it, deletions included; without,
        every live item. 410 when the deletions that far back are gone, 400 for a revision never given."""
        with self.lock:
            acc, col = self.collection(user, name)
            if since is None:
                items = [i for i in col["items"].values() if not i.get("deleted")]
            else:
                if since > col["rev"]:
                    raise bad_request("This revision was never given: read the collection whole.")
                if since < col.get("floor", 0):
                    raise Problem(410, "gone", "Revision too old", "Its deletions are gone: read the collection whole.")
                items = [i for i in col["items"].values() if i.get("rev", 0) > since]
            return acc["generation"], col["rev"], [self.public(i) for i in items]

    def merge(self, user, name, generation, items, if_match=None):
        """Merges items sent (SPEC.md § 20.4): (generation, rev, each item as kept, changed or not)."""
        now = datetime.now(timezone.utc)
        with self.lock:
            acc, col = self.collection(user, name)
            if generation != acc["generation"]:
                raise Problem(409, "conflict", "Conflict", "This sync data was deleted since: ask the user again "
                              "before sending anything (SPEC.md § 20.3).")
            if if_match is not None and if_match != f'"{acc["generation"]}-{col["rev"]}"':
                raise Problem(412, "precondition_failed", "Precondition failed", "The collection changed since it "
                              "was read: read it again.")
            fresh = sum(1 for i in items if i["key"] not in col["items"])
            if len(col["items"]) + fresh > self.limit:
                raise Problem(413, "too_large", "Too large", f"A collection holds {self.limit} items at most here.")
            out = []
            for sent in items:
                sent = dict(sent, updated=sync_time(sent["updated"], now, self.skew))
                have = col["items"].get(sent["key"])
                if sync_wins(sent, have):
                    col["rev"] += 1
                    kept = {"key": sent["key"], "updated": sent["updated"], "rev": col["rev"],
                            "kept": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
                    if sent.get("deleted"):
                        kept["deleted"] = True
                    else:
                        kept["value"] = sent["value"]
                    col["items"][sent["key"]] = have = kept
                out.append(self.public(have))
            self.write()
            return acc["generation"], col["rev"], out

    def erase(self, user, name=None):
        """Erases a collection of the account, or all its sync data (SPEC.md § 20.5): a new generation."""
        with self.lock:
            acc = self.account(user)
            if name is None:
                acc["collections"] = {}
            else:
                acc["collections"].pop(name, None)
            acc["generation"] = "g_" + secrets.token_urlsafe(9)
            self.write()
            return acc["generation"]

    def forget(self, user):
        """Erases an account's sync data, the account being deleted (SPEC.md § 5.7, § 20.5)."""
        with self.lock:
            if self.doc["accounts"].pop(user, None) is not None:
                self.write()


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def device_id(key):
    """A device's id for the administration API (SPEC.md § 5.7): from its token's hash, never the token."""
    return "d_" + key[:16]


class Tokens:
    """Device tokens (SPEC.md § 5.1), hashed, in the state file under "tokens":
    {sha256 of the token: {"user", "device", "scopes", "created", "expires"?,
    "key"? (the device's public key, base64: SPEC.md § 5.4), "rating_cap"?,
    "invitation"?}}."""

    def __init__(self, store):
        self.store = store      # the Library: its state, lock and state file

    def table(self):
        tokens = self.store.state.get("tokens")
        if not isinstance(tokens, dict):
            tokens = self.store.state["tokens"] = {}
        return tokens

    def issue(self, user, device, scopes, lifetime=None, key=None, rating_cap=None, invitation=None):
        token = "et_" + secrets.token_urlsafe(32)   # 256 bits
        record = {"user": user, "device": device, "scopes": list(scopes), "created": now_utc()}
        if lifetime:
            record["expires"] = now_utc(lifetime)
        if key:
            record["key"] = base64.b64encode(key).decode()
        if rating_cap:
            record["rating_cap"] = dict(rating_cap)
        if invitation:
            record["invitation"] = invitation
        with self.store.lock:
            self.store.reload_tokens()
            self.table()[token_hash(token)] = record
            self.store.save_state()
        return token

    @staticmethod
    def live(record):
        if not isinstance(record, dict) or not isinstance(record.get("user"), str):
            return False
        expires = record.get("expires")
        if expires is not None:
            try:
                if datetime.fromisoformat(str(expires).replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                    return False
            except ValueError:
                return False     # an expiry it cannot read: not trusted
        return True

    def find(self, token):
        self.store.reload_tokens()
        with self.store.lock:
            record = self.table().get(token_hash(token))
        return record if self.live(record) else None

    def devices(self):
        """(device id, record) of every live token."""
        self.store.reload_tokens()
        with self.store.lock:
            return [(device_id(k), r) for k, r in self.table().items() if self.live(r)]

    def revoke_user(self, user):
        """Revokes every token of an account (SPEC.md § 5.7, an account deleted)."""
        with self.store.lock:
            self.store.reload_tokens()
            found = [k for k, r in self.table().items() if isinstance(r, dict) and r.get("user") == user]
            for k in found:
                del self.table()[k]
            if found:
                self.store.save_state()

    def revoke(self, did):
        """Revokes the token of device `did` (SPEC.md § 5.7); False when there is none."""
        with self.store.lock:
            self.store.reload_tokens()
            found = [k for k in self.table() if device_id(k) == did]
            for k in found:
                del self.table()[k]
            if found:
                self.store.save_state()
        return bool(found)


class Invitations:
    """Invitations (SPEC.md § 5.5), in the state file under "invitations":
    {id: {"code", "user", "scopes", "expires", "devices", "used", "created",
    "rating_cap"?, "note"?}}. A revoked one is removed."""

    def __init__(self, store):
        self.store = store

    def table(self):
        table = self.store.state.get("invitations")
        if not isinstance(table, dict):
            table = self.store.state["invitations"] = {}
        return table

    @staticmethod
    def redeemable(inv):
        try:
            alive = datetime.fromisoformat(str(inv.get("expires")).replace("Z", "+00:00")) > datetime.now(timezone.utc)
        except ValueError:
            alive = False
        return alive and is_int(inv.get("used")) and is_int(inv.get("devices")) and inv["used"] < inv["devices"]

    def create(self, user, scopes, expires, devices, rating_cap=None, note=None):
        with self.store.lock:
            table = self.table()
            for iid in [i for i, v in table.items() if not (isinstance(v, dict) and self.redeemable(v))]:
                del table[iid]
            if len(table) >= INVITATIONS_LIMIT:
                raise slow_down(3600, f"At most {INVITATIONS_LIMIT} invitations at once.")
            codes = {v.get("code") for v in table.values()}
            while (code := "".join(secrets.choice(CODE_ALPHABET) for _ in range(INVITATION_SYMBOLS))) in codes:
                pass
            iid = "i_" + secrets.token_urlsafe(9)
            inv = {"code": code, "user": user, "scopes": list(scopes), "expires": expires, "devices": devices,
                   "used": 0, "created": now_utc()}
            if rating_cap:
                inv["rating_cap"] = dict(rating_cap)
            if note:
                inv["note"] = note
            table[iid] = inv
            self.store.save_state()
            return iid, dict(inv)

    def listed(self):
        with self.store.lock:
            return [(i, dict(v)) for i, v in self.table().items() if isinstance(v, dict) and self.redeemable(v)]

    def revoke_user(self, user):
        with self.store.lock:
            for iid in [i for i, v in self.table().items() if isinstance(v, dict) and v.get("user") == user]:
                del self.table()[iid]
            self.store.save_state()

    def revoke(self, iid):
        with self.store.lock:
            if iid not in self.table():
                return False
            del self.table()[iid]
            self.store.save_state()
            return True

    def redeem(self, typed):
        """(id, invitation) whose code is `typed`, its use counted (SPEC.md § 5.5); None when it is unknown,
        expired, revoked or used up. Counted under the lock: two devices at once never go past `devices`."""
        code = re.sub(r"[\s-]", "", typed or "").upper()
        with self.store.lock:
            for iid, inv in self.table().items():
                if isinstance(inv, dict) and isinstance(inv.get("code"), str) and hmac.compare_digest(inv["code"], code):
                    if not self.redeemable(inv):
                        return None
                    inv["used"] += 1
                    self.store.save_state()
                    return iid, dict(inv)
        return None


class Pairing:
    """Pairings waiting for the user (SPEC.md § 5.2), in memory: a code lives
    PAIR_EXPIRES seconds, a token is collected once. Each has a poll address
    (the secret), and an id for the administration API, which is not."""

    def __init__(self, tokens, accounts, interval=PAIR_INTERVAL, expires=PAIR_EXPIRES, lifetime=None, announce=None):
        self.tokens, self.accounts, self.announce = tokens, accounts, announce   # announce(entry): the event
        self.interval, self.expires, self.lifetime = interval, expires, lifetime
        self.pending, self.lock = {}, threading.Lock()

    def purge(self):
        now = time.monotonic()
        for pid in [p for p, e in self.pending.items() if e["until"] <= now]:
            del self.pending[pid]

    def start(self, device, scopes, key=None, waiting=True):
        """A pairing waiting for its user; `waiting` False for one an invitation approves at once."""
        with self.lock:
            self.purge()
            if len(self.pending) >= PENDING_LIMIT:
                raise slow_down(self.interval, "Too many pairings are waiting; try again later.")
            codes = {e["code"] for e in self.pending.values()}
            while (code := "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_SYMBOLS))) in codes:
                pass
            pid = "p_" + secrets.token_urlsafe(24)  # 192 bits: whoever has it collects the token
            entry = {"pid": pid, "id": "pr_" + secrets.token_urlsafe(9), "code": code, "device": device,
                     "scopes": scopes, "key": key, "state": "pending", "until": time.monotonic() + self.expires,
                     "created": now_utc(), "expires": now_utc(self.expires), "polled": None,
                     "interval": self.interval}
            self.pending[pid] = entry
        if waiting and self.announce:
            self.announce(entry)
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

    def by_id(self, rid):
        with self.lock:
            self.purge()
            return next((e for e in self.pending.values() if e["state"] == "pending" and e["id"] == rid), None)

    def waiting(self):
        with self.lock:
            self.purge()
            return [e for e in self.pending.values() if e["state"] == "pending"]

    def peek(self, pid):
        with self.lock:
            self.purge()
            return self.pending.get(pid)

    def grant(self, entry, user, scopes=None):
        """The scopes an approval gives: those asked for (or `scopes`, among them) that the account has
        (SPEC.md § 5.2, § 5.7)."""
        mine = self.accounts.scopes(user)
        wanted = entry["scopes"] if scopes is None else [s for s in entry["scopes"] if s in scopes]
        return [s for s in wanted if s in mine]

    def prepare(self, entry, user):
        """Ties the code to the signed-in user until they approve or refuse it on /pair."""
        with self.lock:
            entry["user"], entry["nonce"] = user["name"], secrets.token_urlsafe(24)
            return entry["nonce"]

    def approve(self, entry, user_name, scopes=None, rating_cap=None, invitation=None):
        user = self.accounts.get(user_name)
        granted = self.grant(entry, user, scopes)
        token = self.tokens.issue(user_name, entry["device"], granted, self.lifetime, key=entry.get("key"),
                                  rating_cap=rating_cap, invitation=invitation)
        with self.lock:
            entry.update(state="approved", token=token, granted=granted, nonce=None, rating_cap=rating_cap,
                         user=user_name)

    def refuse(self, entry):
        with self.lock:
            entry.update(state="refused", nonce=None)

    def forget_user(self, user):
        """Refuses the pairings an account's user was approving, and drops its tokens not yet collected."""
        with self.lock:
            for pid, entry in list(self.pending.items()):
                if entry.get("user") == user:
                    if entry["state"] == "approved":
                        del self.pending[pid]
                    else:
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
        doc = {"schema": 1, "token": entry["token"], "scopes": entry["granted"], "bound": bool(entry.get("key"))}
        if self.lifetime:
            doc["expires"] = int(self.lifetime)
        if entry.get("rating_cap"):
            doc["rating_cap"] = entry["rating_cap"]
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
        self.account, self.record, self.signed_digest = None, None, None
        try:
            self.length = self.content_length()
            try:
                url = urlsplit(self.path)
            except ValueError:
                raise bad_request("Not a request target this server can read.") from None
            path = unquote(url.path)
            query = {k: v[-1] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
            self.server.library.refresh(self.server.rescan)
            self.route(method, path, query)
        except Problem as p:
            self.send_doc(p.status, p.document(self.language()), p.headers, problem=True)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:  # noqa: BLE001 - any bug of this server answers 500
            # A bug of this server: logged, answered as SPEC.md § 12 wants,
            # unless the reply had already begun.
            self.log_error("%s", traceback.format_exc())
            self.close_connection = True
            if not self.began:
                problem = Problem(500, "internal", "Internal error", "The server failed; try again later.")
                self.send_doc(500, problem.document(self.language()), problem=True)
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
        if self.signed_digest is not None and not hmac.compare_digest(hashlib.sha256(data).digest(), self.signed_digest):
            raise digest_mismatch("The body's SHA-256 is not the one its signed Content-Digest gives (SPEC.md § 5.4).")
        return data

    # Routes: the path below <base>/v1/, "{}" one segment; the first match wins.
    ROUTES = (
        ("pairing", ("POST",), "pairing", "pair_start"),
        ("pairing/{}", ("GET",), "pairing", "pair_poll"),
        ("apps", ("GET", "HEAD"), "library", "apps"),
        ("apps/missing", ("POST",), "library", "missing"),
        ("changes", ("GET", "HEAD"), None, "changes"),     # changes, or events with wait: chosen within
        ("events", ("GET",), "events", "events"),
        ("grants/sha256/{}", ("GET", "HEAD"), "peers", "grant"),
        ("sync", ("GET", "HEAD"), "sync", "sync_overview"),
        ("sync", ("DELETE",), "sync.write", "sync_erase"),
        ("sync/{}", ("GET", "HEAD"), "sync", "sync_read"),
        ("sync/{}", ("PATCH", "DELETE"), "sync.write", "sync_write"),
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
        ("cheats", ("POST",), "cheats.write", "cheat_post"),
        ("cheats/{}", ("GET", "HEAD"), "cheats", "cheat_text"),
        ("cheats/{}", ("PUT", "DELETE"), "cheats.write", "cheat_write"),
        ("requests", ("GET", "HEAD"), "requests", "requests_list"),
        ("requests", ("POST",), "requests", "request_post"),
        ("requests/{}", ("DELETE",), "requests", "request_delete"),
        ("files/{}", ("GET", "HEAD"), "library", "file"),
        ("admin/users", ("GET", "HEAD", "POST"), "admin", "admin_users"),
        ("admin/users/{}", ("PATCH", "DELETE"), "admin", "admin_user"),
        ("admin/devices", ("GET", "HEAD"), "admin", "admin_devices"),
        ("admin/devices/{}", ("DELETE",), "admin", "admin_device"),
        ("admin/pairings", ("GET", "HEAD"), "admin", "admin_pairings"),
        ("admin/pairings/{}", ("POST",), "admin", "admin_pairing"),
        ("admin/invitations", ("GET", "HEAD", "POST"), "admin", "admin_invitations"),
        ("admin/invitations/{}", ("DELETE",), "admin", "admin_invitation"),
    )

    def route(self, method, path, query):
        v1 = BASE + "/v1"
        if path in ("/.well-known/lantern", v1, v1 + "/"):
            return self.call(method, ("GET", "HEAD"), None, self.handshake, (), query)
        if path == "/pair":
            return self.pair_page(method, query)
        if path.startswith(v1 + "/"):
            segments = path[len(v1) + 1:].split("/")
            found = []      # a path may have a route per method (GET for the cheats, POST to write one)
            for pattern, methods, family, name in self.ROUTES:
                wanted = pattern.split("/")
                if len(wanted) == len(segments) and all(w == s or (w == "{}" and s) for w, s in zip(wanted, segments)):
                    args = tuple(s for w, s in zip(wanted, segments) if w == "{}")
                    if method in methods:
                        return self.call(method, methods, family, getattr(self, name), args, query)
                    found.append((methods, family, name, args))
            if found:
                every = tuple(m for methods, *_ in found for m in methods)
                _, family, name, args = found[0]
                return self.call(method, every, family, getattr(self, name), args, query)
        raise not_found("No such route on this server.")

    def call(self, method, methods, family, fn, args, query):
        self.account, self.record = self.server.accounts.resolve(self.headers.get("Authorization"),
                                                                 self.server.tokens)
        self.check_signature()
        if method not in methods:
            raise Problem(405, "bad_request", "Method not allowed", None, {"Allow": ", ".join(methods)})
        if family:
            self.allow(self.account, family)
        fn(query, *args)

    # Signed requests (SPEC.md § 5.4).

    def target_uri(self):
        """@target-uri: as the client sent it, the host as in Host, in lower case, without the scheme's
        default port."""
        scheme = "https" if self.server.tls else "http"
        host = (self.headers.get("Host") or "").strip().lower()
        host = host.removesuffix(":443" if scheme == "https" else ":80")
        return f"{scheme}://{host}{self.path}"

    def signature_problem(self, code, detail, with_token, keyid=None):
        titles = {"signature_required": "Signature required", "signature_invalid": "Signature invalid",
                  "signature_expired": "Signature expired", "signature_replayed": "Signature replayed"}
        wanted = " ".join(f'"{c}"' for c in signatures.components(with_token, self.length > 0))
        accept = f"lantern=({wanted})" + (f';keyid="{keyid}"' if keyid else "") + ';alg="ed25519"'
        headers = {"Accept-Signature": accept}
        if with_token:
            headers["WWW-Authenticate"] = CHALLENGE + ', error="invalid_token"'
        else:
            headers["WWW-Authenticate"] = CHALLENGE
        return Problem(401, code, titles[code], detail, headers)

    def verify(self, public, with_token):
        """Checks the request's signature by the key `public` (SPEC.md § 5.4), or raises its 401."""
        try:
            signatures.check(self.method, self.target_uri(), self.headers, public, with_token, self.length,
                             self.server.nonces, self.server.skew)
        except signatures.Refused as e:
            raise self.signature_problem(e.code, e.detail, with_token, signatures.thumbprint(public)) from None
        if self.length:
            self.signed_digest = content_digest(self.headers.get("Content-Digest"))

    def check_signature(self):
        if self.record is None:
            return
        key = self.record.get("key")
        if key:
            self.verify(base64.b64decode(key), True)
        elif self.server.bound_only:
            raise self.signature_problem("signature_required", "This server takes only tokens bound to a device "
                                                               "key: pair this device again, with a key.", True)

    # Rating caps (SPEC.md § 5.6).

    def cap(self):
        return (self.record or {}).get("rating_cap") or None

    def title_hidden(self, platform, title_id):
        cap = self.cap()
        if not cap:
            return False
        title = self.server.library.titles.get(f"{platform}/{title_id}")
        return above_cap((title or {}).get("meta", {}).get("ratings", []), cap)

    def app_hidden(self, doc):
        return self.title_hidden(doc["platform"], doc["title_id"])

    def homebrew_hidden(self, doc):
        return bool(self.cap()) and above_cap(doc.get("ratings", []), self.cap())

    def allow(self, account, family):
        if family == "pairing":     # anyone may ask to pair (SPEC.md § 4.2, § 5.2)
            if not self.server.accounts.pairing:
                raise not_found("This server does not pair.")
            return
        if family in ("saves", "encrypted_saves") and not self.server.saves.available:
            raise not_found("Save backups are unavailable on this server for now.")
        if family in ("sync", "sync.write") and not self.server.sync.available:
            raise not_found("Sync is unavailable on this server for now.")
        if account["state"] == "anonymous" and (not self.server.accounts.public or family in ("admin", "sync",
                                                                                              "sync.write")):
            raise unauthorized(CHALLENGE, "This server asks for a token: pair this device first.")
        if account["state"] == "frozen":
            raise Problem(403, "account_frozen", "Account frozen", "This account may do nothing for now.")
        if family == "events":      # SPEC.md § 18: offered to whoever may read one kind of event
            if not set(EVENT_SCOPES.values()) & set(account["scopes"]):
                raise Problem(403, "forbidden", "Forbidden", "This account may read no event.")
            return
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
        # The same for every caller (SPEC.md § 4.2): whoever reaches the server may pair, with a key.
        features["pairing"] = features["signatures"] = 1 if self.server.accounts.pairing else 0
        return features

    def may(self, family):
        """Whether the caller may use `family` (allow() without the error)."""
        try:
            self.allow(self.account, family)
            return True
        except Problem:
            return False

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

    def language(self):
        """The language of this server's own texts for this client (SPEC.md § 2.2)."""
        try:
            return best_language(self.prefs())
        except AttributeError:      # a request that failed before its headers were read
            return "en"

    # Routes.

    def handshake(self, query):
        lib, saves = self.server.library, self.server.saves
        doc = {"schema": 1, "uid": lib.uid, "name": self.server.name,
               "software": {"name": "Lantern reference server", "version": VERSION},
               "base": BASE, "versions": [1], "platforms": lib.platforms()}
        if self.server.motd:
            doc["motd"], doc["language"] = localized(self.server.motd, self.prefs())
            doc["language"] = doc["language"] or "en"
        doc.update({"account": self.account, "features": self.features(self.account),
                    "auth": {"bearer_only": not self.server.bound_only, "skew": self.server.skew},
                    "peers": {"key": base64.b64encode(lib.grant_public).decode(), "grant_lifetime": GRANT_LIFETIME},
                    "limits": {"page_size": PAGE_LIMIT, "save_body": saves.body, "save_size": saves.size,
                               "saves_kept_per_title": saves.kept, "heartbeat": self.server.heartbeat,
                               "event_streams": self.server.event_streams, "wait": self.server.wait_limit,
                               "sync_items": self.server.sync.limit}})
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
                       and (not q or q.casefold() in e["doc"]["name"].casefold())
                       and not self.app_hidden(e["doc"])]
            self.send_doc(200, lib.page(entries, sort, size, cursor, ("apps", platform, kind, title_id, q,
                                                                      json.dumps(self.cap()))))

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
        scope = ("missing", platform, hashlib.sha256(json.dumps([installed, sorted(set(want)), self.cap()],
                                                                sort_keys=True).encode()).hexdigest())
        with lib.lock:
            found = [e for e in lib.missing(platform, installed, set(want)) if not self.app_hidden(e["doc"])]
            self.send_doc(200, lib.page(found, sort, size, cursor, scope))

    def request_document(self, body):
        """A client's JSON document: 400 when malformed, 422 for a schema this server cannot read."""
        return read_document(body, self.headers.get("Content-Type"))

    def changes(self, query):
        """GET /v1/changes (SPEC.md § 6.4), and with wait, a long poll of events (§ 18.3)."""
        lib, platform = self.server.library, self.platform(query)
        self.events_platform = platform
        if "wait" not in query:
            self.allow(self.account, "changes")
            doc = lib.changes(query.get("since"), platform)
            doc["added"] = [a for a in doc["added"] if not self.app_hidden(a)]
            return self.send_doc(200, doc)
        wait, since = query["wait"], query.get("since")
        if not wait.isdigit() or since is None:
            raise bad_request("wait is a number of seconds, from 0, with since (SPEC.md § 18.3).")
        self.allow(self.account, "events")
        start = self.event_start(since)
        deadline = time.monotonic() + min(int(wait), self.server.wait_limit)
        while True:
            with lib.changed:
                found = self.visible_events(start)
                left = deadline - time.monotonic()
                if found or left <= 0 or self.server.stopping.is_set():
                    if self.may("changes"):
                        doc = lib.changes(since, platform)
                        doc["added"] = [a for a in doc["added"] if not self.app_hidden(a)]
                    else:
                        doc = {"schema": 1, "added": [], "removed": [], "since": lib.token(lib.seq)}
                    doc["events"] = [{"id": lib.token(seq), "event": e["event"], "data": data}
                                     for seq, e, data in found]
                    break
                lib.changed.wait(min(left, 1.0))
            lib.refresh(self.server.rescan)
        self.send_doc(200, doc, {"Cache-Control": "no-store"})

    # Events (SPEC.md § 18).

    def event_start(self, since):
        """The sequence number a stream or a long poll starts after: `since`'s, or now's; 400 or 410 as § 18.1
        says."""
        lib = self.server.library
        if since is None:
            return lib.seq
        with lib.lock:
            lib.since("s", since)       # 400 for a token never given, 410 for one too old
            return int(since.rsplit("_", 1)[1])

    def visible_events(self, after):
        """[(seq, event, data)] of the events after `after` the caller may see (SPEC.md § 18.2)."""
        out = []
        for e in self.server.library.events:
            if e["seq"] > after:
                data = self.event_for(e)
                if data is not None and e["event"] != "shutdown":
                    out.append((e["seq"], e, data))
        return out

    def event_for(self, e):
        """The data of event `e` for this caller, or None when it may not see it (SPEC.md § 18.2): of its scopes,
        its account, its platform and within its rating cap."""
        kind, audience = e["event"], e["audience"]
        if kind == "shutdown":
            return e["data"]
        scope = EVENT_SCOPES.get(kind)
        if scope is None or not self.may(scope if scope != "sync.read" else "sync"):
            return None
        platform = self.events_platform
        if kind == "library":
            families, platforms = set(), set()
            for family, p, how, ref in e["items"]:
                if platform is not None and p != platform:
                    continue
                hidden = self.title_hidden(p, ref) if how == "title" else \
                    bool(self.cap()) and above_cap(json.loads(ref), self.cap())
                if not hidden:
                    families.add(family)
                    platforms.add(p)
            if not families:
                return None
            return {"schema": 1, "families": sorted(families), "platforms": sorted(platforms)}
        if "user" in audience and audience["user"] != self.account.get("name"):
            return None
        if platform is not None and audience.get("platform") not in (None, platform):
            return None
        if kind == "save" and self.title_hidden(audience.get("platform"), e["data"].get("title_id")):
            return None
        return e["data"]

    def stream_key(self):
        """Whose streams count together (SPEC.md § 18.4): the token's, or an anonymous caller's address."""
        header = (self.headers.get("Authorization") or "").partition(" ")[2].strip()
        return ("token", token_hash(header)) if self.record is not None else ("address", self.client_address[0])

    def still_allowed(self):
        """Whether the stream's token still holds (SPEC.md § 18.1): not revoked, its account not frozen nor gone."""
        try:
            account, _ = self.server.accounts.resolve(self.headers.get("Authorization"), self.server.tokens)
        except Problem:
            return False
        if account["state"] == "frozen":
            return False
        self.account = account
        return True

    def events(self, query):
        lib, server = self.server.library, self.server
        self.events_platform = self.platform(query)
        since = query.get("since") or (self.headers.get("Last-Event-ID") or "").strip() or None
        last = self.event_start(since)
        key = self.stream_key()
        if not server.take_stream(key):
            raise slow_down(server.heartbeat, f"At most {server.event_streams} event streams at once for a token "
                                              "(SPEC.md § 18.4).")
        try:
            self.began = True
            self.close_connection = True        # the stream ends with the connection
            self.send_response(200)
            for k, v in (("Content-Type", "text/event-stream; charset=utf-8"), ("Cache-Control", "no-store"),
                         ("Connection", "close"), ("X-Accel-Buffering", "no"),
                         ("Vary", "Authorization, Lantern-Platform")):
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(f"retry: {RETRY_MS}\n\n".encode())
            self.write_event(lib.token(last), "ready", {"schema": 1})
            ends, beat = time.monotonic() + server.stream_max, time.monotonic()
            while True:
                with lib.changed:
                    found = self.visible_events(last)
                    newest = lib.events[-1]["seq"] if lib.events else last
                    if not found and not server.stopping.is_set():
                        lib.changed.wait(max(0.05, min(0.25, server.heartbeat - (time.monotonic() - beat))))
                        found = self.visible_events(last)
                        newest = lib.events[-1]["seq"] if lib.events else last
                if server.stopping.is_set():
                    self.write_event(lib.token(newest), "shutdown", {"schema": 1, "retry": max(1, RETRY_MS // 1000)})
                    return
                if not self.still_allowed() or self.client_gone():
                    return
                for seq, e, data in found:
                    self.write_event(lib.token(seq), e["event"], data)
                    last, beat = seq, time.monotonic()
                if time.monotonic() - beat >= server.heartbeat:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    beat = time.monotonic()
                if time.monotonic() >= ends:
                    return
                lib.refresh(server.rescan)
        except OSError:
            return              # the client went away
        finally:
            server.release_stream(key)

    def client_gone(self):
        """Whether the client closed its stream: its socket readable, and at its end (a client sends nothing on a
        stream), so that its slot of § 18.4 is free again within a second, not at the next heartbeat."""
        conn = self.connection
        try:
            readable, _, _ = select.select([conn], [], [], 0)
        except (OSError, ValueError):
            return True
        if not readable:
            return False
        try:
            conn.settimeout(0.05)
            data = conn.recv(1) if isinstance(conn, ssl.SSLSocket) else conn.recv(1, socket.MSG_PEEK)
        except (TimeoutError, ssl.SSLWantReadError, BlockingIOError, InterruptedError):
            return False
        except OSError:
            return True
        finally:
            try:
                conn.settimeout(None)
            except OSError:
                pass
        return not data

    def write_event(self, eid, event, data):
        line = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        self.wfile.write(f"id: {eid}\nevent: {event}\ndata: {line}\n\n".encode())
        self.wfile.flush()

    # Grants (SPEC.md § 19.3).

    def grant(self, query, hexdigest):
        if not re.fullmatch(r"[0-9a-f]{64}", hexdigest):
            raise not_found("A file is named by its SHA-256, lower-case hex.")
        lib, platform = self.server.library, self.platform(query)
        with lib.lock:
            found = None
            for entry in lib.files.values():
                kind, p, ref = entry.get("owner", (None, None, None))
                if entry["sha256"] != hexdigest or kind not in ("app", "homebrew") or (platform and p != platform):
                    continue
                hidden = self.title_hidden(p, ref) if kind == "app" else \
                    self.homebrew_hidden((lib.homebrew.get((p, ref)) or {}).get("doc", {}))
                if not hidden:
                    found = entry
                    break
        if found is None:
            raise not_found("No such file for this caller.")
        exp = int(time.time()) + GRANT_LIFETIME
        self.send_doc(200, {"schema": 1, "sha256": hexdigest, "size": found["size"],
                            "grant": make_grant(lib.grant_seed, lib.uid, hexdigest, found["size"], exp),
                            "expires": utc(exp * 10 ** 9)}, {"Cache-Control": "no-store"})

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
            keys = [k for k, t in lib.titles.items() if t["title_id"] in ids and (platform is None or t["platform"] == platform)
                    and not self.title_hidden(t["platform"], t["title_id"])]
            known = {lib.titles[k]["title_id"] for k in keys}
            doc = {"schema": 1, "titles": [lib.title_doc(k, prefs) for k in sorted(keys)],
                   "unknown": [i for i in dict.fromkeys(ids) if i not in known]}
        self.send_doc(200, doc)

    def title_changes(self, query):
        lib = self.server.library
        doc = lib.title_changes(query.get("since"), self.platform(query), self.prefs())
        doc["titles"] = [t for t in doc["titles"] if not self.title_hidden(t["platform"], t["title_id"])]
        doc["removed"] = [t for t in doc["removed"] if not self.title_hidden(t["platform"], t["title_id"])]
        self.send_doc(200, doc)

    def title(self, query, title_id):
        lib = self.server.library
        table = {(t["platform"], t["title_id"]): k for k, t in lib.titles.items()}
        key = lib.find({k: v for k, v in table.items() if not self.title_hidden(*k)}, title_id, self.platform(query))
        self.send_doc(200, {"schema": 1, **lib.title_doc(key, self.prefs())})

    # Homebrew (SPEC.md § 8).

    def homebrew_view(self, entry, full):
        return homebrew_view(entry, full, self.prefs())

    def homebrew_list(self, query):
        platform = self.platform(query)
        q, kind, genre = query.get("q"), query.get("kind"), query.get("genre")
        if kind is not None and not WORD.match(kind):
            raise bad_request("kind is a lower-case word: " + ", ".join(KINDS) + ".")
        if genre is not None and not WORD.match(genre):
            raise bad_request("genre is a lower-case word: " + ", ".join(GENRES) + ".")
        _, size, cursor = self.listing_args(query, ("name",))
        lib = self.server.library
        with lib.lock:
            entries = [e for (p, _), e in lib.homebrew.items()
                       if (platform is None or p == platform) and (kind is None or e["doc"]["kind"] == kind)
                       and (genre is None or genre in e["doc"].get("genres", ()))
                       and (not q or q.casefold() in e["doc"]["name"].casefold())
                       and not self.homebrew_hidden(e["doc"])]
            self.send_doc(200, lib.page(entries, "name", size, cursor, ("homebrew", platform, q, kind, genre,
                                                                        json.dumps(self.cap())),
                                        lambda e: self.homebrew_view(e, False)))

    def homebrew_entry(self, query, hid):
        lib = self.server.library
        visible = {k: e for k, e in lib.homebrew.items() if not self.homebrew_hidden(e["doc"])}
        entry = lib.find(visible, hid, self.platform(query))
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
        scope = ("updates", platform, hashlib.sha256(json.dumps([sorted(builds.items()), self.cap()]).encode())
                 .hexdigest())
        with lib.lock:
            newer = [e for (p, hid), e in lib.homebrew.items()
                     if p == platform and hid in builds and e["doc"]["build"] > builds[hid]
                     and not self.homebrew_hidden(e["doc"])]
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

    def save_fields(self, platform, title_id, kind, version, profile, note, slot=None, encryption=None):
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
        if encryption is not None and not self.may("encrypted_saves"):
            raise bad_request("This server keeps no encrypted backup (SPEC.md § 9.4).")
        fields = {"platform": platform, "title_id": title_id, "kind": kind, "game_version_code": version,
                  "profile": profile or None, "slot": slot or None, "note": note or None,
                  "device": (self.record or {}).get("device"), "encryption": encryption}
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
        encryption = self.headers.get("Lantern-Save-Encryption")
        fields = self.save_fields(platform, title_id, self.headers.get("Lantern-Save-Kind"),
                                  int(version) if version is not None else None,
                                  self.text_header("Lantern-Profile", 64), self.text_header("Lantern-Note", 120),
                                  self.text_header("Lantern-Save-Slot", 64),
                                  None if encryption is None else encryption_header(encryption))
        data = self.body(saves.body)
        if not hmac.compare_digest(hashlib.sha256(data).digest(), digest):
            raise digest_mismatch("The body's SHA-256 is not the one Content-Digest gives.")
        saves.folder.mkdir(parents=True, exist_ok=True)
        tmp = saves.folder / f".post-{secrets.token_hex(8)}"
        tmp.write_bytes(data)
        try:
            archive_check(data[:16], tmp, fields.get("encryption"))
            entry = saves.add(self.account["name"], tmp, hashlib.sha256(data).hexdigest(), len(data), fields)
        finally:
            if tmp.exists():
                tmp.unlink()
        self.saved(entry)
        self.send_doc(201, {"schema": 1, **entry})

    def saved(self, entry):
        """The event of a backup kept (SPEC.md § 18.2)."""
        self.server.library.emit("save", {"schema": 1, **{k: entry[k] for k in ("platform", "title_id", "save_id",
                                                                               "created", "device") if k in entry}},
                                 {"user": self.account["name"], "platform": entry["platform"]})

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
                                  doc.get("profile"), doc.get("note"), doc.get("slot"),
                                  None if doc.get("encryption") is None else encryption_of(doc["encryption"]))
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
        self.saved(entry)
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
                    and (build_id is None or e["doc"]["build_id"] == build_id)
                    and not self.app_hidden(e["doc"])]
        sets.sort(key=lambda d: (d["platform"], d["title_id"], d["build_id"], d["source"].casefold(), d["id"]))
        self.send_doc(200, {"schema": 1, "cheats": sets})

    def cheat_text(self, query, cid):
        platform = self.platform(query)
        lib = self.server.library
        with lib.lock:
            entry = lib.cheats.get(cid)
        if entry is None or (platform is not None and entry["doc"]["platform"] != platform) \
                or self.app_hidden(entry["doc"]):
            raise not_found("No such cheat set.")
        self.send_file(entry["path"], entry["doc"]["size"], entry["doc"]["sha256"], "text/plain; charset=utf-8")

    def cheat_fields(self, query):
        """A cheat set to write (SPEC.md § 10), checked: its place, size and format."""
        doc = self.request_document(self.body(CHEAT_BODY))
        platform = doc.get("platform") if doc.get("platform") is not None else self.platform(query, required=True)
        title_id, build_id, text = doc.get("title_id"), doc.get("build_id"), doc.get("text")
        source, note = doc.get("source", "Lantern"), doc.get("note")
        if not (isinstance(platform, str) and PLATFORM.match(platform)):
            raise bad_request("platform is a platform's name (SPEC.md § 4.3).")
        if (PROFILES.get(platform) or {}).get("cheats") is False:
            raise bad_request(f"{platform} has no cheats (Annex A).")
        if not title_id_ok(platform, title_id):
            raise bad_request(f"title_id is not a title id of {platform}.")
        pattern = (PROFILES.get(platform) or {}).get("build_id", BUILD_ID)
        if not (isinstance(build_id, str) and pattern.match(build_id)):
            raise bad_request(f"build_id is the game's build, in {platform}'s form: this server keeps a set per build.")
        if not (isinstance(source, str) and CHEAT_SOURCE.match(source)):
            raise bad_request("source is 1 to 64 letters, digits, spaces and . ' ( ) -, a letter or a digit first.")
        if note is not None and not (isinstance(note, str) and plain(note, 120) == note and len(note.encode()) <= 120):
            raise bad_request("note: 120 bytes at most, without control characters.")
        if not isinstance(text, str):
            raise bad_request("text is the set's text.")
        if len(text.encode()) > CHEAT_LIMIT:
            raise Problem(413, "too_large", "Too large", f"A cheat set is {CHEAT_LIMIT} bytes at most.")
        if any(ord(c) < 32 and c not in "\t\r\n" or ord(c) == 127 for c in text):
            raise bad_request("text has a control character.")
        if platform in CHEAT_HEX:
            bad = next((n for n, line in enumerate(text.splitlines(), 1) if not CHEAT_LINE.match(line)), None)
            if bad is not None:
                raise bad_request(f"line {bad} is neither a [name] nor words of 8 hex digits (Annex A).")
        return {"platform": platform, "title_id": title_id, "build_id": build_id, "source": source,
                "note": note, "text": text}

    def cheat_post(self, query):
        doc = self.server.library.write_cheat(self.cheat_fields(query))
        self.send_doc(201, {"schema": 1, **doc})

    def cheat_write(self, query, cid):
        platform = self.platform(query)
        lib = self.server.library
        with lib.lock:
            entry = lib.cheats.get(cid)
            if entry is None or (platform is not None and entry["doc"]["platform"] != platform):
                raise not_found("No such cheat set.")
            if self.method == "DELETE":
                lib.delete_cheat(entry)
            else:
                lib.write_cheat(self.cheat_fields(query), replacing=entry)
        self.send_head(204, None, {})

    # Requests (SPEC.md § 11).

    PUBLIC_REQUEST = ("id", "platform", "title_id", "name", "status", "created")

    def requests_list(self, query):
        platform = self.platform(query)
        lib = self.server.library
        with lib.lock:
            mine = [{k: r[k] for k in self.PUBLIC_REQUEST if k in r} for r in lib.requests()
                    if isinstance(r, dict) and r.get("user") == self.account["name"]
                    and (platform is None or r.get("platform") == platform)]
        mine.sort(key=lambda r: (r.get("created", ""), r.get("id", "")), reverse=True)
        self.send_doc(200, {"schema": 1, "requests": mine})

    def request_post(self, query):
        doc = self.request_document(self.body())
        platform = doc.get("platform") if doc.get("platform") is not None else self.platform(query, required=True)
        if not (isinstance(platform, str) and PLATFORM.match(platform)):
            raise bad_request("platform is a platform's name (SPEC.md § 4.3).")
        if not title_id_ok(platform, doc.get("title_id")):
            raise bad_request(f"title_id is not a title id of {platform}.")
        status, entry = self.server.library.request(self.account["name"], platform, doc["title_id"])
        self.send_doc(status, {"schema": 1, **{k: entry[k] for k in self.PUBLIC_REQUEST if k in entry}})

    def request_delete(self, query, rid):
        if not self.server.library.withdraw(self.account["name"], rid):
            raise not_found("No such request of this account.")
        self.send_head(204, None, {})

    # Sync (SPEC.md § 20).

    def device(self):
        """The caller's device id (SPEC.md § 5.7), its key in the collection installed; None without a token."""
        header = (self.headers.get("Authorization") or "").partition(" ")[2].strip()
        return device_id(token_hash(header)) if self.record is not None else None

    @staticmethod
    def sync_collection(name):
        if name not in SYNC_COLLECTIONS:
            raise not_found("No such collection: " + ", ".join(SYNC_COLLECTIONS) + ".")
        return name

    def sync_event(self, name, rev):
        self.server.library.emit("sync", {"schema": 1, "collection": name, "rev": rev},
                                 {"user": self.account["name"]})

    def sync_overview(self, query):
        generation, collections = self.server.sync.overview(self.account["name"])
        doc = {"schema": 1, "generation": generation, "collections": collections}
        if self.device():
            doc["device"] = self.device()
        self.send_doc(200, doc)

    def sync_erase(self, query):
        self.server.sync.erase(self.account["name"])
        for name in SYNC_COLLECTIONS:
            self.sync_event(name, 0)
        self.send_head(204, None, {})

    def sync_read(self, query, name):
        name = self.sync_collection(name)
        since = query.get("since")
        if since is not None and not since.isdigit():
            raise bad_request("since is a revision, an integer.")
        generation, rev, items = self.server.sync.read(self.account["name"], name, None if since is None else int(since))
        _, size, cursor = self.listing_args(query, ("name",))
        entries = [{"doc": i, "keys": {"name": (i["rev"], i["key"]) if since is not None else (i["key"],)}}
                   for i in items]
        page = self.server.library.page(entries, "name", size, cursor,
                                        ("sync", self.account["name"], name, since, generation))
        self.send_doc(200, {"schema": 1, "collection": name, "generation": generation, "rev": rev,
                            "items": page["items"], "next": page["next"]})

    def sync_item(self, name, item):
        """An item sent, checked against its collection's form (SPEC.md § 20.2, § 20.4); 400 otherwise."""
        if not (isinstance(item, dict) and isinstance(item.get("key"), str) and isinstance(item.get("updated"), str)
                and sync_time(item["updated"], datetime.now(timezone.utc), self.server.skew) is not None):
            raise bad_request("An item is {key, value, updated} or {key, deleted: true, updated}, updated a UTC time "
                              "to the millisecond (SPEC.md § 20.2).")
        key = item["key"]
        if "deleted" in item and "value" in item:
            raise bad_request("An item has a value, or deleted: true, not both.")
        if item.get("deleted") is True:
            out = {"key": key, "deleted": True, "updated": item["updated"]}
        elif "value" in item and "deleted" not in item:
            out = {"key": key, "value": item["value"], "updated": item["updated"]}
        else:
            raise bad_request("An item has a value, or deleted: true.")
        value = out.get("value")
        if name == "wishes":
            platform, _, title_id = key.partition("/")
            if not (PLATFORM.match(platform) and title_id_ok(platform, title_id)):
                raise bad_request(f"{key[:80]!r}: a wish's key is <platform>/<title_id> (SPEC.md § 20.2).")
            if value is not None and not (
                    isinstance(value, dict) and value.get("platform") == platform and value.get("title_id") == title_id
                    and all(k not in value or (isinstance(value[k], str) and len(value[k].encode()) <= limit
                                               and plain(value[k], limit) == value[k])
                            for k, limit in (("name", 512), ("note", 120)))):
                raise bad_request("A wish is {platform, title_id, name?, note?}, those of its key.")
        else:
            if not re.fullmatch(r"d_[0-9a-f]{16}", key):
                raise bad_request("An item of installed is keyed by its device's id, d_….")
            if value is not None and not (
                    isinstance(value, dict) and isinstance(value.get("device"), str) and 0 < len(value["device"].encode()) <= 512
                    and PLATFORM.match(str(value.get("platform", "")))
                    and isinstance(value.get("apps", []), list) and len(value.get("apps", [])) <= SYNC_ITEMS
                    and all(isinstance(a, dict) and CORE_ID.match(str(a.get("app_id", ""))) and is_int(a.get("version_code"))
                            for a in value.get("apps", []))
                    and isinstance(value.get("homebrew", []), list) and len(value.get("homebrew", [])) <= SYNC_ITEMS
                    and all(isinstance(h, dict) and HOMEBREW_ID.match(str(h.get("id", ""))) and is_int(h.get("build"))
                            for h in value.get("homebrew", []))):
                raise bad_request("installed is {device, platform, apps: [{app_id, version_code}], "
                                  "homebrew: [{id, build}]} (SPEC.md § 20.2).")
            if key != self.device():
                raise Problem(403, "forbidden", "Forbidden", "A device writes its own item of installed only "
                              "(SPEC.md § 20.4).")
        return out

    def sync_write(self, query, name):
        name = self.sync_collection(name)
        sync, user = self.server.sync, self.account["name"]
        if self.method == "DELETE":
            sync.erase(user, name)
            self.sync_event(name, 0)
            return self.send_head(204, None, {})
        doc = self.request_document(self.body())
        generation, items = doc.get("generation"), doc.get("items")
        if not isinstance(generation, str):
            raise bad_request("generation is the one a read gave (SPEC.md § 20.4).")
        if not (isinstance(items, list) and 1 <= len(items) <= SYNC_WRITE):
            raise bad_request(f"items lists 1 to {SYNC_WRITE} items.")
        checked = [self.sync_item(name, i) for i in items]
        if len({i["key"] for i in checked}) != len(checked):
            raise bad_request("An item's key twice in one write.")
        before = sync.overview(user)[1][name]["rev"]
        generation, rev, out = sync.merge(user, name, generation, checked, self.headers.get("If-Match"))
        if rev != before:
            self.sync_event(name, rev)
        self.send_doc(200, {"schema": 1, "collection": name, "generation": generation, "rev": rev, "items": out})

    # Administration (SPEC.md § 5.7), scope admin. Never a token, a hash or a password in its documents.

    def admin_page(self, docs, query, scope, key):
        _, size, cursor = self.listing_args(query, ("name",))
        entries = [{"doc": d, "keys": {"name": key(d)}} for d in docs]
        self.send_doc(200, self.server.library.page(entries, "name", size, cursor, scope))

    def scopes_field(self, value, what="scopes"):
        if not (isinstance(value, list) and all(isinstance(x, str) and x in SCOPES for x in value)
                and len(set(value)) == len(value)):
            raise bad_request(f"{what} is a list of scopes: " + ", ".join(SCOPES) + ".")
        return [x for x in SCOPES if x in value]

    def user_doc(self, user):
        accounts = self.server.accounts
        devices = sum(1 for _, r in self.server.tokens.devices() if r.get("user") == user["name"])
        doc = {"name": user["name"], "state": "frozen" if user.get("state") == "frozen" else "active",
               "scopes": accounts.scopes(user), "devices": devices}
        if isinstance(user.get("created"), str):
            doc["created"] = user["created"]
        return doc

    def admin_users(self, query):
        accounts = self.server.accounts
        if self.method != "POST":
            docs = [self.user_doc(accounts.get(n)) for n in accounts.names()]
            return self.admin_page(docs, query, ("admin-users",), lambda d: (d["name"],))
        doc = self.request_document(self.body())
        name, state = doc.get("name"), doc.get("state", "active")
        if not (isinstance(name, str) and ACCOUNT_NAME.match(name)):
            raise bad_request("name is 1 to 64 letters, digits, '.', '_' and '-'.")
        if "password" in doc:
            raise bad_request("An account made here has no password (SPEC.md § 5.7).")
        if state not in ("active", "frozen"):
            raise bad_request("state is active or frozen.")
        user = accounts.create(name, self.scopes_field(doc.get("scopes")), state)
        self.send_doc(201, {"schema": 1, **self.user_doc(user)})

    def admin_user(self, query, name):
        if self.method == "DELETE":     # SPEC.md § 5.7: confirmed by the name, never the caller's own
            if self.server.accounts.get(name) is None:
                raise not_found("No such account.")
            if query.get("confirm") != name:
                raise bad_request("confirm repeats the account's name: ?confirm=<name> (SPEC.md § 5.7).")
            if name == self.account["name"]:
                raise Problem(409, "conflict", "Conflict", "An admin does not delete the account they use.")
            self.server.delete_account(name)
            return self.send_head(204, None, {})
        doc = self.request_document(self.body())
        state, scopes = doc.get("state"), doc.get("scopes")
        if state is None and scopes is None:
            raise bad_request("Give state (active or frozen), scopes, or both.")
        if state is not None and state not in ("active", "frozen"):
            raise bad_request("state is active or frozen.")
        user = self.server.accounts.update(name, state, None if scopes is None else self.scopes_field(scopes))
        self.send_doc(200, {"schema": 1, **self.user_doc(user)})

    @staticmethod
    def device_doc(did, record):
        doc = {"id": did, "user": record["user"], "device": record.get("device") or "?",
               "scopes": [x for x in record.get("scopes", []) if x in SCOPES],
               "created": record.get("created") or now_utc(), "bound": bool(record.get("key"))}
        if record.get("key"):
            doc["key"] = signatures.short_fingerprint(base64.b64decode(record["key"]))
        for k in ("expires", "invitation", "rating_cap"):
            if record.get(k):
                doc[k] = record[k]
        return doc

    def admin_devices(self, query):
        user = query.get("user")
        docs = [self.device_doc(did, r) for did, r in self.server.tokens.devices()
                if user is None or r.get("user") == user]
        self.admin_page(docs, query, ("admin-devices", user), lambda d: (d["user"], d["created"], d["id"]))

    def admin_device(self, query, did):
        if not self.server.tokens.revoke(did):
            raise not_found("No such device.")
        self.send_head(204, None, {})

    def admin_pairings(self, query):
        docs = []
        for e in self.server.pairing.waiting():
            doc = {"id": e["id"], "code": Pairing.shown(e["code"]), "device": e["device"], "scopes": e["scopes"],
                   "created": e["created"], "expires": e["expires"]}
            if e.get("key"):
                doc["key"] = signatures.short_fingerprint(e["key"])
            docs.append(doc)
        self.admin_page(docs, query, ("admin-pairings",), lambda d: (d["created"], d["id"]))

    def cap_field(self, value):
        if value is None:
            return None
        problem = rating_cap_problem(value)
        if problem:
            raise bad_request(problem + " (SPEC.md § 5.6).")
        return dict(value)

    def admin_pairing(self, query, rid):
        doc = self.request_document(self.body())
        pairing = self.server.pairing
        entry = pairing.by_id(rid)
        if entry is None:
            raise not_found("No such pairing waiting: approved, refused or expired.")
        decision = doc.get("decision")
        if decision == "refuse":
            pairing.refuse(entry)
            return self.send_head(204, None, {})
        if decision != "approve":
            raise bad_request("decision is approve or refuse.")
        name = doc.get("user", self.account["name"])
        user = self.server.accounts.get(name)
        if user is None:
            raise bad_request(f"No account named {str(name)[:64]}.")
        scopes = None if doc.get("scopes") is None else self.scopes_field(doc["scopes"])
        pairing.approve(entry, name, scopes, self.cap_field(doc.get("rating_cap")))
        self.send_head(204, None, {})

    def invitation_doc(self, iid, inv):
        query = f"invitation={Pairing.shown(inv['code'])}"
        if self.server.spki:
            query += f"&spki={self.server.spki}"
        doc = {"id": iid, "code": Pairing.shown(inv["code"]), "link": f"{self.origin()}/pair?{query}"}
        doc.update({k: inv[k] for k in ("user", "scopes", "expires", "devices", "used", "rating_cap", "note", "created")
                    if k in inv})
        return doc

    def admin_invitations(self, query):
        invitations = self.server.invitations
        if self.method != "POST":
            docs = [self.invitation_doc(i, v) for i, v in invitations.listed()]
            return self.admin_page(docs, query, ("admin-invitations",), lambda d: (d["created"], d["id"]))
        doc = self.request_document(self.body())
        user = self.server.accounts.get(doc.get("user"))
        if user is None:
            raise bad_request("user is the account the devices join, which exists.")
        scopes = self.scopes_field(doc.get("scopes"))
        if not scopes or any(x not in self.server.accounts.scopes(user) for x in scopes):
            raise bad_request("scopes are some of the account's own (SPEC.md § 5.5).")
        try:
            expires = datetime.fromisoformat(str(doc.get("expires")).replace("Z", "+00:00"))
            if expires.tzinfo is None:
                raise ValueError
        except ValueError:
            raise bad_request("expires is an RFC 3339 time.") from None
        now = datetime.now(timezone.utc)
        if not now < expires <= now + timedelta(days=INVITATION_DAYS):
            raise bad_request(f"expires is in the next {INVITATION_DAYS} days (SPEC.md § 5.5).")
        devices = doc.get("devices")
        if not (is_int(devices) and 1 <= devices <= 100):
            raise bad_request("devices is how many devices may redeem it, 1 to 100.")
        note = doc.get("note")
        if note is not None and not (isinstance(note, str) and plain(note, 120) == note and len(note.encode()) <= 120):
            raise bad_request("note: 120 bytes at most, without control characters.")
        iid, inv = invitations.create(user["name"], scopes, expires.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"), devices, self.cap_field(doc.get("rating_cap")), note)
        self.send_doc(201, {"schema": 1, **self.invitation_doc(iid, inv)})

    def admin_invitation(self, query, iid):
        if not self.server.invitations.revoke(iid):
            raise not_found("No such invitation.")
        self.send_head(204, None, {})

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
        key = self.device_key(doc.get("key"))
        if key is None and self.server.bound_only:
            raise Problem(400, "key_required", "Device key required", "This server binds every token to a device "
                          "key: send one (key: {alg: ed25519, public_key}, SPEC.md § 5.4).")
        ip = self.client_address[0]
        wait = self.server.pair_limiter.hit(ip)
        if wait:
            raise slow_down(wait, "Too many pairing requests from this address.")
        invitation = None
        if doc.get("invitation") is not None:
            wait = self.server.attempts.wait(ip)
            if wait:
                raise slow_down(wait, "Too many attempts at invitations from this address.")
            invitation = self.server.invitations.redeem(doc["invitation"] if isinstance(doc["invitation"], str) else "")
            if invitation is None:
                self.server.attempts.record(ip)
                raise Problem(410, "gone", "Invitation gone", "This invitation is unknown, expired, revoked or used "
                              "up (SPEC.md § 5.5).")
        pairing = self.server.pairing
        entry = pairing.start(device.strip(), known, key, waiting=invitation is None)
        if invitation is not None:      # approved at once, as the invitation says (SPEC.md § 5.5)
            iid, inv = invitation
            pairing.approve(entry, inv["user"], inv["scopes"], inv.get("rating_cap"), iid)
        code = Pairing.shown(entry["code"])
        verify = self.origin() + "/pair"
        self.send_doc(200, {"schema": 1, "code": code, "verify": verify, "verify_complete": f"{verify}?code={code}",
                            "poll": f"{BASE}/v1/pairing/{entry['pid']}", "interval": entry["interval"],
                            "expires": int(pairing.expires)}, {"Cache-Control": "no-store"})

    @staticmethod
    def device_key(value):
        """A device's public key from a pairing request (SPEC.md § 5.4): its 32 bytes, None without one; 400
        when it is not an Ed25519 key."""
        if value is None:
            return None
        ok = isinstance(value, dict) and value.get("alg") == "ed25519" \
            and re.fullmatch(r"[A-Za-z0-9+/]{43}=", str(value.get("public_key", "")))
        public = base64.b64decode(value["public_key"]) if ok else b""
        point = ed25519.decode(public) if ok else None
        # A point of small order ([8]P is the identity) is no key: forgeries would verify for it (SPEC.md § 5.4).
        if point is None or ed25519.small_order(point):
            raise bad_request("key is {alg: ed25519, public_key: the 32 bytes of an Ed25519 key, base64}.")
        return public

    def pair_poll(self, query, pid):
        entry = self.server.pairing.peek(pid)
        if entry is not None and entry.get("key"):     # a pairing with a key polls signed by it (SPEC.md § 5.4)
            self.verify(entry["key"], False)
        doc = self.server.pairing.poll(pid)
        if doc is None:
            self.send_head(202, 0, {"Cache-Control": "no-store"})
        else:
            self.send_doc(200, doc, {"Cache-Control": "no-store"})

    def pair_page(self, method, query=None):
        """/pair: where a user signs in, enters the console's code and approves it.
        A password is typed here only, never on the console (SPEC.md § 5.2).
        ?code= fills the code in (verify_complete, a QR code: § 5.2): it approves nothing by itself.
        ?invitation= is an invitation's link (§ 5.5), for an app to open, not a browser."""
        if not self.server.accounts.pairing:
            raise not_found("This server does not pair.")
        if method not in ("GET", "HEAD", "POST"):
            raise Problem(405, "bad_request", "Method not allowed", None, {"Allow": "GET, HEAD, POST"})
        query = query or {}
        if method != "POST":
            if query.get("invitation"):
                return self.send_page(200, "<p>This is an invitation to pair a device with this server. Open this "
                                           "link in your Lantern app, on the device to pair, or type its code "
                                           "there.</p>")
            code = re.sub(r"[^2-9A-HJ-NP-Za-hj-np-z-]", "", query.get("code") or "")[:40].upper()
            return self.send_page(200, self.pair_form(code=code))
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
                cap = None
                if (form.get("cap") or "").isdigit():
                    cap = {"age": int(form["cap"])}
                    if form.get("unrated") == "hide":
                        cap["unrated"] = "hide"
                    if rating_cap_problem(cap):
                        return self.send_page(400, self.pair_form("That is not a rating cap."))
                pairing.approve(entry, entry["user"], rating_cap=cap)
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
        key = (f"<p>The device's own key: <code>{signatures.short_fingerprint(entry['key'])}</code> "
               "(its token will be bound to it).</p>") if entry.get("key") else \
            "<p>The device sent no key: its token works for whoever holds it.</p>"
        ages = "".join(f'<option value="{a}">{a}</option>' for a in (3, 7, 12, 16, 18))
        return self.send_page(200, f"""<p>Pair <strong>{html.escape(entry['device'])}</strong> with
<strong>{html.escape(user['name'])}</strong>'s account, for: {html.escape(scopes)}?</p>
{self.fingerprint()}
{key}
<form method="post" action="/pair">
<input type="hidden" name="nonce" value="{html.escape(nonce)}">
<p><label>Rating cap <select name="cap"><option value="">None</option>{ages}</select></label>
<label><input type="checkbox" name="unrated" value="hide"> and hide what has no rating</label></p>
<button name="decision" value="approve">Approve</button> <button name="decision" value="refuse">Refuse</button>
</form>""")

    def fingerprint(self):
        if not self.server.spki:
            return "<p>Plain HTTP on loopback: no key to compare.</p>"
        return (f"<p>This server's key: <code>{short_fingerprint(self.server.spki)}</code>. "
                "The console shows the same next to its code: approve only if they match.</p>")

    def pair_form(self, error=None, code=""):
        note = f'<p class="error">{html.escape(error)}</p>' if error else ""
        value = f' value="{html.escape(code)}"' if code else ""
        return f"""{note}<p>Sign in, then enter the code your console shows.</p>
{self.fingerprint()}
<form method="post" action="/pair">
<p><label>Name <input name="name" autocomplete="username" required></label></p>
<p><label>Password <input name="password" type="password" autocomplete="current-password" required></label></p>
<p><label>Code <input name="code" autocomplete="off" autocapitalize="characters" required{value}></label></p>
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
        owner = (entry or {}).get("owner", ())
        if entry is None or (owner[:1] == ("app",) and self.title_hidden(*owner[1:])) \
                or (owner[:1] == ("homebrew",) and self.homebrew_hidden(
                    (lib.homebrew.get(owner[1:]) or {}).get("doc", {}))):
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
        self.send_head(status, length, headers, encodings=False)
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

    def send_head(self, status, length, headers, encodings=True):
        """`encodings`: whether the response may vary on Accept-Encoding (JSON); a file never does."""
        self.began = True
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        if length is not None:
            self.send_header("Content-Length", str(length))
        self.send_header("Vary", "Authorization, Lantern-Platform, Accept-Language"
                         + (", Accept-Encoding" if encodings else ""))
        if "Cache-Control" not in headers:
            self.send_header("Cache-Control", "private" if self.authenticated else "no-cache")
        self.end_headers()

    def coding(self):
        return accepted_coding(self.headers.get("Accept-Encoding"))

    def send_doc(self, status, doc, headers=None, problem=False):
        body = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()
        headers = dict(headers or {})
        headers["Content-Type"] = "application/problem+json" if problem else "application/json"
        spoken = {doc.get("language")} | {i.get("language") for k in ("items", "titles") for i in doc.get(k, ())
                                          if isinstance(i, dict)}
        spoken = sorted(x for x in spoken if isinstance(x, str))
        if spoken:
            headers["Content-Language"] = ", ".join(spoken)
        coding = self.coding() if len(body) > 64 else None
        tag = hashlib.sha256(body).hexdigest()[:32]
        if coding:
            body = zstd.compress(body) if coding == "zstd" else gzip.compress(body, mtime=0)
            headers["Content-Encoding"] = coding
            tag += "-" + coding         # each representation its own ETag (SPEC.md § 2.1)
        if status == 200 and self.method in ("GET", "HEAD"):
            etag = f'"{tag}"'
            headers["ETag"] = etag
            if etag in [t.strip() for t in (self.headers.get("If-None-Match") or "").split(",")]:
                self.send_head(304, 0, {"ETag": etag})
                return
        self.send_head(status, len(body), headers)
        if not self.head:
            self.wfile.write(body)


def read_document(body, content_type):
    """A client's JSON document (SPEC.md § 3.2, § 13): 400 when it is not an object of JSON with an integer
    schema, or nests too deep; 422 for a schema this server cannot read. It never fails otherwise, whatever
    the bytes."""
    if (content_type or "").split(";")[0].strip().lower() != "application/json":
        raise bad_request("The body is application/json.")
    if nesting(body) > DEPTH_LIMIT:
        raise bad_request(f"The body nests deeper than {DEPTH_LIMIT} (SPEC.md § 13).")
    try:
        doc = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        raise bad_request("The body is not JSON.") from None
    if too_deep(doc):
        raise bad_request(f"The body nests deeper than {DEPTH_LIMIT} (SPEC.md § 13).")
    if not isinstance(doc, dict) or not isinstance(doc.get("schema"), int) or isinstance(doc["schema"], bool) \
            or doc["schema"] < 1:
        raise bad_request("The body is an object with an integer schema.")
    if doc["schema"] > 1:
        raise Problem(422, "unsupported_schema", "Unsupported schema",
                      f"This server reads schema 1 here, not {doc['schema']}.")
    return doc


def accepted_coding(header):
    """The Content-Encoding to send JSON with (SPEC.md § 2.1): zstd where Python has it, else gzip, as an
    Accept-Encoding allows; None for none."""
    accepted = {}
    for part in (header or "").split(","):
        name, _, params = part.strip().lower().partition(";")
        m = re.search(r"q\s*=\s*([0-9.]+)", params)
        try:
            accepted[name.strip()] = float(m.group(1)) if m else 1.0
        except ValueError:
            accepted[name.strip()] = 0.0
    for coding in ("zstd", "gzip"):
        if coding == "zstd" and zstd is None:
            continue
        q = accepted[coding] if coding in accepted else accepted.get("*", 0.0)
        if q > 0:
            return coding
    return None


def nesting(body):
    """The deepest nesting of brackets in a JSON body, outside its strings: read before parsing it, so that a
    document nested too deep is refused rather than parsed (SPEC.md § 13)."""
    depth = deepest = 0
    in_string = escaped = False
    for byte in body:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
        elif byte == 0x22:
            in_string = True
        elif byte in (0x5B, 0x7B):
            depth += 1
            deepest = max(deepest, depth)
        elif byte in (0x5D, 0x7D):
            depth -= 1
    return deepest


def too_deep(doc, depth=1):
    if depth > DEPTH_LIMIT:
        return True
    if isinstance(doc, dict):
        return any(too_deep(v, depth + 1) for v in doc.values())
    if isinstance(doc, list):
        return any(too_deep(v, depth + 1) for v in doc)
    return False


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
                 quiet=False, handler=Handler, tls=None, spki=None, token_lifetime=None, saves=None,
                 bound_only=False, motd=None, skew=signatures.SKEW, sync=None, heartbeat=HEARTBEAT,
                 event_streams=EVENT_STREAMS, wait_limit=WAIT_LIMIT, stream_max=STREAM_MAX):
        """`tls`: an ssl.SSLContext; without it, only a loopback address (SPEC.md § 2).
        `spki`: the SHA-256 of the certificate's key, for /pair (SPEC.md § 5.3).
        `saves`: a Saves, by default in the library's .lantern-saves/.
        `bound_only`: issue and take only tokens bound to a device key (SPEC.md § 5.4).
        `motd`: the handshake's message, a text or one per language (SPEC.md § 4.2, § 2.2).
        `sync`: a Sync, by default in the library's .lantern-sync.json (SPEC.md § 20).
        `heartbeat`, `event_streams`, `wait_limit`: limits.heartbeat, .event_streams and .wait (SPEC.md § 18.4);
        `stream_max`: the seconds a stream lasts at most."""
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
        accounts.attach(library)
        self.invitations = Invitations(library)
        self.pairing = Pairing(self.tokens, accounts, lifetime=token_lifetime, announce=self.announce_pairing)
        self.bound_only, self.motd, self.skew = bound_only, motd, skew
        self.sync = sync if sync is not None else Sync(library.root / ".lantern-sync.json", skew=skew)
        self.heartbeat, self.event_streams, self.wait_limit = heartbeat, event_streams, wait_limit
        self.stream_max = stream_max
        self.stopping = threading.Event()
        self.streams, self.streams_lock = {}, threading.Lock()
        self.nonces = signatures.Nonces(2 * skew)
        self.pair_limiter = Limiter(*PAIR_RATE)
        self.attempts = Limiter(*PAIR_ATTEMPTS)

    def announce_pairing(self, entry):
        """The event of a pairing waiting (SPEC.md § 18.2), as § 5.7 lists it."""
        data = {"schema": 1, "id": entry["id"], "code": Pairing.shown(entry["code"]), "device": entry["device"],
                "expires": entry["expires"]}
        if entry.get("key"):
            data["key"] = signatures.short_fingerprint(entry["key"])
        self.library.emit("pairing", data)

    def take_stream(self, key):
        with self.streams_lock:
            if self.streams.get(key, 0) >= self.event_streams:
                return False
            self.streams[key] = self.streams.get(key, 0) + 1
            return True

    def release_stream(self, key):
        with self.streams_lock:
            self.streams[key] -= 1
            if not self.streams[key]:
                del self.streams[key]

    def shutdown(self):
        """Stops serving: every stream first gets the event shutdown (SPEC.md § 18.2)."""
        self.stopping.set()
        with self.library.changed:
            self.library.changed.notify_all()
        deadline = time.monotonic() + 2
        while self.streams and time.monotonic() < deadline:
            time.sleep(0.02)
        ThreadingHTTPServer.shutdown(self)

    def delete_account(self, name):
        """Deletes an account and what is its (SPEC.md § 5.7): tokens, invitations, pairings waiting, save backups,
        requests and sync data, at once."""
        self.accounts.delete(name)      # 409 for an account of users.json
        self.tokens.revoke_user(name)
        self.invitations.revoke_user(name)
        self.pairing.forget_user(name)
        self.saves.delete_user(name)
        lib = self.library
        with lib.lock:
            lib.state["requests"] = [r for r in lib.requests() if not (isinstance(r, dict) and r.get("user") == name)]
            lib.save_state()
        self.sync.forget(name)
        with lib.changed:
            lib.changed.notify_all()    # its streams end at once


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


def advertise(server, http_port, port=mdns.PORT, address=None):
    """DNS-SD over multicast DNS (SPEC.md § 4.1): _lantern._tcp, with the TXT keys uid, path and v; None when
    the port cannot be bound."""
    try:
        return mdns.Responder("_lantern._tcp", server.name, http_port,
                              {"uid": server.library.uid, "path": BASE, "v": "1"},
                              "lantern-" + server.library.uid[:8], address, port).serve()
    except OSError as e:
        log(f"DNS-SD: UDP {port} not available ({e}); discovery's datagram still works")
        return None


def tokens_command(state_path, revoke):
    """--tokens and --revoke: the state file's tokens, listed or one revoked."""
    doc = read_versioned(Path(state_path), "state")
    if doc is None:
        sys.exit(f"{state_path}: no state this server can write (absent, unreadable or newer)")
    tokens = doc.get("tokens") if isinstance(doc.get("tokens"), dict) else {}
    if revoke is None:
        for key, t in sorted(tokens.items(), key=lambda kv: str(kv[1].get("created", ""))):
            print(f"{device_id(key)}  {t.get('user')}  {t.get('device')!r}  {', '.join(t.get('scopes', []))}  "
                  + ("bound  " if t.get("key") else "bearer-only  ") +
                  f"created {t.get('created')}" + (f", expires {t['expires']}" if t.get("expires") else ""))
        return 0
    wanted = revoke.removeprefix("d_")     # a device id (SPEC.md § 5.7) or a hash's start
    found = [k for k in tokens if len(wanted) >= 8 and k.startswith(wanted.lower())]
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
    p.add_argument("--bound-only", action="store_true",
                   help="issue and take only tokens bound to a device key (SPEC.md § 5.4)")
    p.add_argument("--motd", metavar="FILE", help='the handshake\'s message: {"schema": 1, "motd": {"en": "…"}}')
    p.add_argument("--tokens", action="store_true", help="list the paired devices' tokens, then exit")
    p.add_argument("--revoke", metavar="ID", help="revoke a token (its id from --tokens), then exit")
    p.add_argument("--discovery", action="store_true", help="answer LAN discovery on UDP")
    p.add_argument("--discovery-port", type=int, default=DISCOVERY_PORT)
    p.add_argument("--dns-sd", action="store_true", help="advertise _lantern._tcp with multicast DNS (SPEC.md § 4.1)")
    p.add_argument("--dns-sd-port", type=int, default=mdns.PORT, help=argparse.SUPPRESS)
    p.add_argument("--sync-file", help="where sync data is kept (default <library>/.lantern-sync.json)")
    p.add_argument("--export", metavar="DIR", help="write the library as a static library into DIR (SPEC.md § 21), "
                                                   "then exit")
    p.add_argument("--page-size", type=int, default=100, help="--export: items per page (1 to 1000)")
    p.add_argument("--language", default="en", help="--export: the language of its texts")
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
    if args.export:
        if not 1 <= args.page_size <= 1000:
            p.error("--page-size is 1 to 1000")
        try:
            from server import static
        except ImportError:
            import static
        done = static.export(sys.modules[__name__], library, args.export, args.page_size, args.language, args.name)
        log(f"exported {done['documents']} document(s) and {done['files']} file(s) to {args.export} "
            f"({', '.join(done['platforms']) or 'no platform'})")
        return 0
    saves = Saves(args.saves or Path(args.library) / ".lantern-saves")
    if not saves.available:
        log(f"{saves.path}: save backups unavailable (an index this server cannot read or write)")
    lifetime = args.token_days * 86400 if args.token_days else None
    motd = None
    if args.motd:
        doc = read_versioned(Path(args.motd), "motd file")
        motd = localizable((doc or {}).get("motd"), 4096)
        if motd is None:
            log(f"{args.motd}: no motd this server can read, none shown")
    try:
        server = LanternServer((args.host, args.port), library, Accounts(args.users), args.name, args.rescan,
                               args.quiet, tls=tls, spki=spki, token_lifetime=lifetime, saves=saves,
                               bound_only=args.bound_only, motd=motd,
                               sync=Sync(args.sync_file or Path(args.library) / ".lantern-sync.json"))
    except ValueError as e:
        p.error(str(e))
    port = server.server_address[1]
    if args.discovery:
        discovery(server, args.discovery_port, port)
    if args.dns_sd:
        advertise(server, port, args.dns_sd_port, None if args.host in ("0.0.0.0", "::", "") else args.host)
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
        server.stopping.set()       # the streams get shutdown (SPEC.md § 18.2) before the process ends
        with library.changed:
            library.changed.notify_all()
        time.sleep(0.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
