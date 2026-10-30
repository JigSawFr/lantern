#!/usr/bin/env python3
"""Lantern conformance suite: checks a server against SPEC.md, from outside.

    python3 conformance/run.py https://shelf.example.org/ [--token TOKEN]

It reads the handshake at the URL's origin, then checks every MUST it can
see from a client's side: documents and their `schema` against schemas/v1/,
the features a server declares against the routes it answers, platforms and
their filter, the bearer token's challenge (and that no Basic one is ever
sent), pairing's shapes, cursor pages, what a console is missing, every
app's sha256, ranges and Repr-Digest on every file response, titles one by
one and in bulk, homebrew (manifests, kinds, genres and tags, arches and
packages, requirements, the kind and genre filters, ports and their data,
signatures, updates), cheat sets, requests, save backups, errors, limits,
signed requests (SPEC.md § 5.4: an unsigned, forged, stale or replayed one
refused), keyed pairing and its QR address, languages, compression,
`Deprecation` and `Sunset`, the cold start's budget (Annex B.8), and LAN
discovery when asked for (--discover); with the scope `admin`, the
administration API, invitations and their limits, and rating caps hiding
titles everywhere; then what 0.5 adds (checks_v05.py): event streams and
long polling, grants and mirrors (and a peer, with --peer), sync, encrypted
backups, deleting an account, DNS-SD (--dns-sd), and the rate limits of
pairing, last. With --static, it checks a static library instead
(static_check.py). Each check prints PASS, FAIL, WARN (a SHOULD not met) or
SKIP, with the SPEC.md section it comes from and the requirement ids it
covers (SPEC.md § 3.5); the exit code is 1 when one fails. At the end it
prints the conformance levels the server reaches (SPEC.md § 17): `Lantern
Core`, then `+titles`, `+homebrew`, `+saves`, `+cheats`, `+requests`,
`+admin`, `+events`, `+peers`, `+sync` and `+encrypted_saves`; or `Lantern
Static` for a static library.

The token is one a device got by pairing (SPEC.md § 5.2), and --key the file
of the device's key (its 32-byte Ed25519 seed, base64) when the token is
bound to it (§ 5.4); without them, the suite calls as an anonymous client.
It asks for a few pairing codes (feature `pairing`), which the server may
show to its users until they expire on their own. With a token that holds
`saves`, it sends save backups for a title id of its own (none of the
library's, so that no backup of the user's is dropped for them), in one
request and by resumable upload, and deletes them before it ends. With
`cheats.write`, it writes a cheat set for such a title, replaces it and
deletes it. With `requests`, it asks for such a title twice (the second
answer is the same request), then withdraws it. With `admin`, it pairs two
devices of its own through the administration API (one approved with a
rating cap, one refused), makes an invitation and redeems it, and revokes
what it paired and made; with --admin-writes, it also makes an account of
its own, `lantern-conformance-…`, freezes and thaws it, pairs a device to it
by an invitation, and deletes it (SPEC.md § 5.7). With `sync.write`, it
writes wishes for title ids of its own and deletes them (a deletion stays
listed, as § 20.5 keeps it). Last, it asks for pairing codes and redeems
wrong invitation codes until the server answers 429 (--rate-probe at most):
the server then limits pairing from its address for a while. It changes
nothing else.
Rules that the suite cannot see (a client's, such as ignoring unknown
fields, pinning, asking before a path that needs consent, checking a port's
data before launch; or a server's inside, such as keeping only tokens'
hashes) are listed, by requirement id, in CLIENT_RULES and UNSEEN, and on
the site's traceability page.

Standard library only, but for the schema checks: those need jsonschema and
referencing (tools/requirements.txt); --no-schemas runs without them.
"""
import argparse
import base64
import gzip
import hashlib
import http.client
import io
import ipaddress
import itertools
import json
import math
import re
import secrets
import socket
import ssl
import sys
import time
import zipfile
import zlib
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import checks_v05
import checks_v06
import lantern_client as client
import static_check

try:                    # Python 3.14 and later: zstd, to read what a server compresses with it
    from compression import zstd
except ImportError:
    zstd = None

VERSION = "0.6.0"
FAMILIES = ("library", "titles", "changes", "sections", "homebrew", "saves", "cheats", "requests", "pairing",
            "signatures", "admin", "events", "peers", "sync", "encrypted_saves")
LEVELS = ("core", "titles", "homebrew", "saves", "cheats", "requests", "admin", "events", "peers", "sync",
          "encrypted_saves")    # SPEC.md § 17; and Lantern Static, for a static library
LEVEL_NAMES = {"core": "Lantern Core", **{x: "+" + x for x in LEVELS[1:]}}
BUDGET = 256 << 10      # a cold start's JSON, as it travels (SPEC.md Annex B.8)
JSON_LIMIT = 32 << 20
CHEAT_LIMIT = 1 << 20
TITLES_AT_ONCE = 100
DISCOVERY_PORT = 47115
DATAGRAM_LIMIT = 1200
PLATFORM = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")    # SPEC.md § 4.3
NOT_A_PLATFORM = "Not a platform!"
NO_SUCH_PLATFORM = "x-lantern-conformance"
CODE = re.compile(r"[2-9A-HJ-NP-Z]{4}(-[2-9A-HJ-NP-Z]{4}){1,7}")  # SPEC.md § 5.2
PAIRING = {"schema": 1, "device": "Lantern conformance", "scopes": ["library"]}
SAVE_KINDS = ("account", "device", "bcat", "cache", "other")
NO_BUILD = ("3ds", "vita")      # profiles whose cheats have no build_id (Annex A.2, A.3)
# SPEC.md § 12: the codes each status may carry.
CODES = {400: {"bad_request", "key_required"},
         401: {"unauthorized", "signature_required", "signature_invalid", "signature_expired", "signature_replayed"}, 403: {"forbidden", "account_frozen"},
         404: {"not_found"}, 405: {"bad_request"}, 409: {"conflict"}, 410: {"gone"}, 412: {"precondition_failed"},
         413: {"too_large"}, 416: {"bad_request"}, 422: {"unsupported_schema", "digest_mismatch"},
         429: {"slow_down"}, 500: {"internal"}, 503: {"unavailable"}}
# A route per family, to see whether the server honours what it declares (SPEC.md § 4.2).
PROBES = {
    "library": ("GET", "/v1/apps?page_size=1", None, "apps"),
    "titles": ("GET", "/v1/titles?ids={title_id}", None, "titles"),
    "changes": ("GET", "/v1/changes", None, "changes"),
    "sections": ("GET", "/v1/sections", None, "sections"),
    "homebrew": ("GET", "/v1/homebrew?page_size=1", None, "homebrew-page"),
    "saves": ("GET", "/v1/saves", None, "saves"),
    "cheats": ("GET", "/v1/cheats", None, "cheats"),
    "requests": ("GET", "/v1/requests", None, "requests"),
    "pairing": ("POST", "/v1/pairing", PAIRING, "pairing-code"),
    "admin": ("GET", "/v1/admin/users?page_size=1", None, "admin-users"),
    "peers": ("GET", "/v1/grants/sha256/{sha256}", None, "grant"),
    "sync": ("GET", "/v1/sync", None, "sync"),
}
# Routes that take a JSON document, by family, with a document of schema 2
# (SPEC.md § 3.2, § 12), sent with a platform where the route needs one.
BODIES = {
    "library": ("/v1/apps/missing", {"schema": 2, "installed": [], "want": ["base"]}),
    "homebrew": ("/v1/homebrew/updates", {"schema": 2, "installed": []}),
    "saves": ("/v1/saves/{title_id}/uploads", {"schema": 2, "size": 1, "sha256": "0" * 64}),
    "pairing": ("/v1/pairing", {"schema": 2, "device": "Lantern conformance", "scopes": ["library"]}),
    "requests": ("/v1/requests", {"schema": 2, "title_id": "{title_id}"}),
}
# The requirements each check covers (SPEC.md § 3.5); the site's traceability page reads them.
REQS = {
    "transport.https": ["L-2-3"],
    "handshake.well-known": ["L-4.2-1", "L-3.2-5"], "handshake.v1": ["L-4.2-1"], "handshake.versions": ["L-4.2-1"],
    "handshake.anonymous": ["L-4.2-3"], "handshake.account": ["L-4.2-8"], "handshake.platforms": ["L-4.2-2"],
    "handshake.auth": ["L-4.2-5", "L-5.4-1"],
    "auth.unknown-token": ["L-5.1-5"], "auth.unknown-handshake": ["L-4.2-6"], "auth.basic-refused": ["L-5.1-1", "L-5.1-5"],
    "auth.missing": ["L-5.1-5"], "auth.frozen": ["L-5.1-6", "L-4.2-4"],
    "pairing.offered": ["L-5.2-1", "L-4.2-5"], "pairing.code": ["L-5.2-5", "L-5.2-6", "L-5.2-7"],
    "pairing.verify-complete": ["L-5.2-10", "L-5.2-11"], "pairing.verify-page": ["L-5.3-2"],
    "pairing.waiting": ["L-5.2-3"], "pairing.slow-down": ["L-5.2-9"], "pairing.unknown": ["L-5.2-3"],
    "pairing.key": ["L-5.4-1", "L-5.4-11", "L-5.4-12"], "pairing.bearer-only": ["L-5.4-1"],
    "apps.first-page": ["L-3.2-5"], "features": ["L-4.2-4", "L-4.2-7", "L-4.2-8"],
    "features.anonymous": ["L-4.2-4", "L-4.2-7"],
    "apps.pages": ["L-6.2-2", "L-6.2-3"], "apps.sha256": ["L-6.1-1"], "apps.platforms": ["L-4.2-2"],
    "apps.page-size": ["L-6.2-5", "L-6.2-6"], "apps.bad-cursor": ["L-6.2-4"], "apps.filters": ["L-6.2-1"], "apps.etag": ["L-14-1"],
    "platforms.filter": ["L-4.3-1"], "platforms.query": ["L-4.3-5"], "platforms.unknown": ["L-4.3-2"],
    "platforms.bad-name": ["L-4.3-3"], "platforms.vary": ["L-4.3-6"],
    "missing.no-platform": ["L-4.3-4"], "missing.installed": ["L-6.3-1"], "missing.up-to-date": ["L-6.3-1"],
    "missing.base": ["L-6.3-1"], "missing.malformed": ["L-12-1", "L-12-2"],
    "files.whole": ["L-6.6-1", "L-6.6-2", "L-6.6-3"], "files.ranges": ["L-6.6-1", "L-6.6-2"],
    "files.unsatisfiable": ["L-6.6-1"], "files.unknown": ["L-6.6-4"],
    "changes.token": ["L-6.4-1"], "changes.bad-token": ["L-6.4-2"],
    "titles.known": ["L-7.1-1", "L-7.1-3"], "titles.unknown": ["L-7.1-1"], "titles.bulk": ["L-7.2-1", "L-7.1-3"],
    "titles.bulk-limit": ["L-7.2-1"], "titles.changes": ["L-7.3-1"], "titles.bad-token": ["L-7.3-1"],
    "homebrew.pages": ["L-8.1-3"], "homebrew.entries": ["L-8.1-3", "L-8.2-1"],
    "homebrew.manifests": ["L-8.2-2", "L-8.2-4", "L-8.2-5"],
    "homebrew.kinds": ["L-8.1-2", "L-8.2-7", "L-8.2-9", "L-8.3-7"], "homebrew.filters": ["L-8.5-1", "L-8.5-2"],
    "homebrew.requires": ["L-8.7-1", "L-8.7-3"], "homebrew.ports": ["L-8.6-1", "L-8.6-2"],
    "homebrew.packages": ["L-8.2-3", "L-6.6-2"], "homebrew.signatures": ["L-8.4-1", "L-8.4-5"], "homebrew.updates": ["L-8.5-3"],
    "homebrew.updates-platform": ["L-4.3-4"], "homebrew.unknown": ["L-8.1-4"],
    "cheats.sets": ["L-10-1"], "cheats.text": ["L-6.6-2"], "cheats.unknown": ["L-10-2"], "cheats.write": ["L-10-4"],
    "cheats.write-cycle": ["L-10-3"],
    "requests.list": ["L-11-1"], "requests.create": ["L-11-1"], "requests.delete": ["L-11-2"],
    "saves.limits": ["L-4.2-8"], "saves.list": ["L-9.1-1"], "saves.no-platform": ["L-4.3-4"],
    "saves.upload": ["L-9.3-2", "L-9.3-3"], "saves.read": ["L-9.1-1", "L-6.6-2"], "saves.upload-digest": ["L-9.3-4"],
    "saves.upload-too-large": ["L-9.3-1"], "saves.single": ["L-9.2-1"], "saves.cleanup": ["L-9.1-3"],
    "schema.refused": ["L-3.2-6"], "versions.accept-schema": ["L-3.2-7"],
    "errors.unknown-route": ["L-12-3"], "discovery.reply": ["L-4.1-1"],
    "signatures.unsigned": ["L-5.4-6"], "signatures.invalid": ["L-5.4-6"], "signatures.stale": ["L-5.4-6"],
    "signatures.replayed": ["L-5.4-6", "L-5.4-9"], "signatures.digest": ["L-5.4-6"],
    "signatures.accept-signature": ["L-5.4-10"],
    "language.problem": ["L-2.2-1", "L-2.2-2", "L-2.2-3"], "language.handshake": ["L-2.2-2"],
    "compression.json": ["L-2.1-1"], "compression.etag": ["L-2.1-3"], "compression.files": ["L-2.1-2", "L-6.6-3"],
    "limits.depth": ["L-13-3"], "budget.cold-start": [],
    "admin.refused": ["L-5.7-1"], "admin.users": ["L-5.7-2"], "admin.users-write": ["L-5.7-3"],
    "admin.pairings": ["L-5.7-2", "L-5.7-4", "L-5.2-4", "L-5.2-3"], "admin.refuse": ["L-5.2-3"],
    "admin.rating-cap": ["L-5.6-1", "L-5.6-2"], "admin.devices": ["L-5.1-4", "L-5.7-2", "L-5.7-3"],
    "admin.invitations": ["L-5.5-1", "L-5.5-2", "L-5.5-4"],
    "errors.problem": ["L-12-1", "L-12-2"], "errors.never-200": ["L-12-1"], "errors.www-authenticate": ["L-5.1-5"],
    "auth.no-basic": ["L-5.1-1"], "documents.schema": ["L-3.2-1"], "documents.type": ["L-2-4"],
    "documents.limits": ["L-13-2"], "documents.date": ["L-5.4-7"], "caching.private": ["L-14-2"],
    "deprecation.headers": ["L-3.4-1", "L-3.4-2"],
    # Draft 0.5 (checks_v05.py, static_check.py).
    "events.stream": ["L-18.1-1", "L-18.1-2", "L-18.1-7", "L-18.4-1"], "events.heartbeat": ["L-18.1-6"],
    "events.resume": ["L-18.1-3", "L-18.1-10", "L-18.2-1", "L-18.3-2"], "events.bad-token": ["L-18.1-4"],
    "events.long-poll": ["L-18.3-1", "L-18.3-3"], "events.limit": ["L-18.4-2"], "events.revoked": ["L-18.1-8"],
    "peers.handshake": ["L-19.3-3"], "peers.grant": ["L-19.3-1", "L-19.3-2"], "peers.mirrors": ["L-19.2-2"],
    "peer.refused": ["L-19.4-1", "L-19.4-5"], "peer.serves": ["L-19.4-2"], "peer.rate": ["L-19.4-4"],
    "peer.discovery": ["L-19.5-1"],
    "sync.overview": [], "sync.write": ["L-20.4-1", "L-20.3-1"], "sync.future": ["L-20.4-2"],
    "sync.if-match": ["L-20.4-3"], "sync.generation": ["L-20.4-4"], "sync.installed": ["L-20.4-5"],
    "sync.malformed": ["L-20.4-6"], "sync.limits": ["L-20.5-4"],
    "e2e.upload": ["L-9.4-4"], "e2e.not-offered": ["L-9.4-5"],
    "admin.users-delete": ["L-5.7-6", "L-5.7-7", "L-20.5-1", "L-20.5-3"],
    "pairing.rate-limit": ["L-5.2-8"], "invitations.rate-limit": ["L-5.5-3"], "discovery.dns-sd": ["L-4.1-4"],
    "transport.pin": [],
    "static.handshake": ["L-21.2-1", "L-3.2-5"], "static.pages": ["L-21.1-1"], "static.titles": ["L-21.1-1"],
    "static.homebrew": ["L-21.1-1", "L-8.1-3"], "static.cheats": ["L-21.1-1"], "static.paths": ["L-21.1-2"],
    "static.files": ["L-21.1-1"], "static.manifests": ["L-8.2-2", "L-8.2-4", "L-8.2-5"],
    "static.signatures": ["L-8.4-1", "L-8.4-5"], "static.limits": ["L-13-2"],
    # Draft 0.6 (checks_v06.py, and admin.requests here).
    "values.i-json-refused": ["L-2.3-1"], "documents.i-json": ["L-2.3-1"], "documents.times": ["L-2.3-2"],
    "documents.nfc": ["L-2.3-5"], "values.hex-case": ["L-2.3-4"], "apps.search": ["L-2.3-6", "L-6.2-1"],
    "apps.empty": ["L-2.3-7"], "routes.paths": ["L-2.4-1"], "routes.no-redirect": ["L-2.4-1"],
    "routes.query-twice": ["L-2.4-3"], "routes.query-lenient": ["L-2.4-4", "L-2.4-5"], "routes.head": ["L-2.4-6"],
    "routes.content-type": ["L-2.4-7"], "homebrew.ambiguous": ["L-4.3-8"], "missing.want": ["L-6.3-2"],
    "files.if-range": ["L-6.6-6", "L-6.6-7"], "caching.not-modified": ["L-14-3", "L-14-4"],
    "admin.requests": ["L-11-3", "L-11-4", "L-11-5", "L-11-6"], "auth.tokens": ["L-5.1-2"],
    "titles.images": ["L-7.1-2"], "discovery.rate": ["L-4.1-3"], "peers.mirrors-fetch": ["L-19.2-2"],
    "peer.slots": ["L-19.4-4"],
}
# Rules only a client keeps: the suite cannot see them (SPEC.md § 17).
CLIENT_RULES = [
    ("2", ["L-2-1", "L-2-2"], "Certificates are verified; plain HTTP only to a loopback address"),
    ("2", ["L-2-5", "L-2-6", "L-2-7"], "User-Agent, Accept-Language and Lantern-Platform on every call"),
    ("2", ["L-2-8"], "Tokens and signatures go to the server's origin alone"),
    ("2.3", ["L-2.3-3"], "A time's fraction of 1 to 9 digits is read"),
    ("2.4", ["L-2.4-2"], "No redirect of a route is followed"),
    ("3.2", ["L-3.2-2"], "A reader ignores the fields it does not know"),
    ("3.2", ["L-3.2-3", "L-3.2-4"], "A reader treats a newer schema as absent and never writes it back"),
    ("3.4", ["L-3.4-5"], "A client records a Deprecation for its developers"),
    ("4.1", ["L-4.1-5"], "Discovery is a hint: nothing is trusted because of a reply"),
    ("4.3", ["L-4.3-7"], "Nothing is installed of a platform without a profile"),
    ("5.2", ["L-5.2-12", "L-5.2-13"], "verify_complete drawn as a QR code, the code and fingerprint beside it"),
    ("5.3", ["L-5.3-1"], "The device shows the short fingerprint of the key it sees, next to the code"),
    ("5.3", ["L-5.3-3", "L-5.3-4"], "The key compared at pairing is pinned; a changed key fails"),
    ("5.4", ["L-5.4-2", "L-5.4-3"], "A key sent at pairing, and every request of its token signed"),
    ("5.4", ["L-5.4-4", "L-5.4-5"], "The private key stays on the device, where the system protects keys"),
    ("5.4", ["L-5.4-8"], "A stale signature is signed again once, at the server's Date"),
    ("5.7", ["L-5.7-5"], "An admin app shows each waiting pairing's code and the server's fingerprint"),
    ("6.1", ["L-6.1-2"], "Nothing is installed or matched by an Atlas id alone"),
    ("6.6", ["L-6.6-5"], "A download's SHA-256 is checked before installing"),
    ("7.1", ["L-7.1-4", "L-7.1-5"], "No token or credential is sent to an external address; a video opens on request"),
    ("8.1", ["L-8.1-1"], "A kind the client does not know is read as app"),
    ("8.2", ["L-8.2-6", "L-8.2-8"], "A package of another or an unknown arch is skipped"),
    ("8.3", ["L-8.3-1", "L-8.3-2", "L-8.3-3", "L-8.3-4"],
     "Only the manifest's paths are written, checked; a path outside the free roots is shown and agreed to"),
    ("8.3", ["L-8.3-5"], "Nothing is installed over another entry's system id"),
    ("8.3", ["L-8.3-6"], "Uninstalling removes the manifest's files only"),
    ("8.4", ["L-8.4-2", "L-8.4-3"], "A signature is checked; the key is pinned per id, a changed key refused unless accepted"),
    ("8.4", ["L-8.4-4"], "An Ed25519 key or R of small order, not canonical, or S >= L never verifies"),
    ("8.6", ["L-8.6-3", "L-8.6-4", "L-8.6-5"],
     "A port's data is checked (presence, accepted hashes, one alternative) before launch, never fetched"),
    ("8.7", ["L-8.7-2"], "Requirements are checked before a package is offered"),
    ("9.1", ["L-9.1-2"], "A save is not restored on an older game without a warning"),
    ("12", ["L-12-4"], "A code the client does not know is read by its status"),
    ("13", ["L-13-1"], "What a client reads is bounded"),
    ("9.4", ["L-9.4-1", "L-9.4-2", "L-9.4-3"],
     "An encrypted backup is checked whole before it is restored; the key never leaves; a new file key each time"),
    ("9.4", ["L-9.4-6", "L-9.4-7", "L-9.4-8", "L-9.4-9"],
     "Profile and note left out of an encrypted backup; a phrase's check; the phrase shown on request only"),
    ("18.1", ["L-18.1-5", "L-18.1-9"], "Unknown events are skipped; a client waits retry and backs off"),
    ("18.4", ["L-18.4-3"], "One stream per server at most"),
    ("19.1", ["L-19.1-1", "L-19.1-2", "L-19.1-3"],
     "A mirror's or a peer's file is checked as the server's; no credential goes to them"),
    ("19.2", ["L-19.2-1"], "A mirror over plain HTTP only on a private network"),
    ("19.4", ["L-19.4-6"], "A grant over plain HTTP only on a private network"),
    ("19.5", ["L-19.5-2"], "Peers looked for at most once a minute, 2 at once"),
    ("20.1", ["L-20.1-1", "L-20.1-2", "L-20.1-3"], "Sync only with the user's consent, installed games by name"),
    ("20.3", ["L-20.3-2"], "Another generation: nothing written back, sync off, the user asked again"),
    ("21.3", ["L-21.3-1", "L-21.3-2"], "A static library's files read whatever their type, checked; missing computed"),
]
# A server's rules the suite cannot see from outside, and why.
UNSEEN = {
    "L-3.1-1": "keeping an old major version needs one",
    "L-3.4-3": "a Sunset is in the future of a run", "L-3.4-4": "as is an older schema's last day",
    "L-4.1-2": "the suite asks from one network",
    "L-5.1-3": "what a server keeps is inside it",
    "L-5.2-2": "the protocol has no route for it, which is what the rule says",
    "L-5.2-14": "a code is typed on the server's own page, behind its sign-in",
    "L-18.2-2": "a server stops when its owner says, not the suite",
    "L-19.4-3": "whether a peer's user allowed it, and its networks, are the device's",
    "L-20.5-2": "thirty days are longer than a run",
}


class Fail(Exception):
    pass


class Skip(Exception):
    pass


class Blind(Skip):
    """A check the suite could not run for want of a token, a key or a scope: its level is not shown reached."""


class Warn(Exception):
    pass


def expect(cond, msg):
    if not cond:
        raise Fail(msg)


class Response:
    def __init__(self, method, path, auth, status, headers, body, truncated, raw, platform):
        self.method, self.path, self.auth = method, path, auth
        self.status, self.headers, self.body, self.truncated = status, headers, body, truncated
        self.raw, self.platform = raw, platform
        self._doc = None
        self.wire = len(body)       # the bytes as they travelled, before any Content-Encoding is undone
        self.encoding = (headers.get("Content-Encoding") or "").strip().lower()
        self.unreadable = False
        if self.encoding and body:
            try:
                if self.encoding == "gzip":
                    self.body = gzip.decompress(body)
                elif self.encoding == "zstd" and zstd is not None:
                    self.body = zstd.decompress(body)
                else:
                    self.unreadable = True      # br, or zstd without the module: its headers are checked alone
            except (OSError, EOFError, ValueError) as e:
                raise Fail(f"{method} {path}: its {self.encoding} body does not decompress ({e})") from None

    def header(self, name):
        return self.headers.get(name)

    @property
    def ctype(self):
        return (self.header("Content-Type") or "").split(";")[0].strip().lower()

    @property
    def is_json(self):
        return self.ctype in ("application/json", "application/problem+json")

    def json(self):
        if self._doc is None:
            expect(not self.truncated, f"{self}: document above {JSON_LIMIT} bytes")
            if self.unreadable:
                raise Skip(f"{self}: {self.encoding}, which this Python cannot read")
            try:
                self._doc = json.loads(self.body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as e:
                raise Fail(f"{self}: not JSON ({e})") from None
        return self._doc

    def __str__(self):
        where = f", {self.platform}" if self.platform else ""
        return f"{self.method} {self.path} ({self.auth}{where}) -> {self.status}"


class Client:
    """One HTTP request per connection, with the caller chosen per request; signed (SPEC.md § 5.4) when the
    token is bound to the key given."""

    def __init__(self, origin, token, context, timeout, seed=None, pin=None):
        self.origin, self.token, self.seed, self.pin = origin, token, seed, pin
        self.context, self.timeout, self.log = context, timeout, []
        self.offset = 0         # the server's clock minus this one's, from its Date (SPEC.md Annex B.9)
        self.peer_spki = None   # the SHA-256 of the key the server's certificate carries, over TLS

    def check_pin(self, conn):
        """The key of the server's certificate, which must be the pinned one with --pin (SPEC.md § 5.3)."""
        if self.origin.scheme != "https" or conn.sock is None:
            return
        der = conn.sock.getpeercert(binary_form=True)
        spki = spki_of(der) if der else None
        if self.peer_spki is None:
            self.peer_spki = spki
        if self.pin and spki != self.pin:
            conn.close()
            raise ConnectionError(f"the server's key {spki} is not the one pinned, {self.pin}: nothing sent")

    def uri(self, path):
        u = self.origin
        return client.target_uri(u.scheme, u.hostname, u.port, path)

    def signed(self, seed, method, path, authorization, body, created=None, nonce=None):
        created = int(time.time() + self.offset) if created is None else created
        return client.sign(seed, method, self.uri(path), authorization, body or b"", created, nonce)

    def authorization(self, auth):
        if auth == "token" and self.token is not None:
            return "Bearer " + self.token
        if auth == "unknown":
            return "Bearer et_lantern-conformance-" + secrets.token_hex(16)
        if auth == "basic":     # what a server MUST refuse (SPEC.md § 5.1)
            return "Basic " + base64.b64encode(f"lantern-conformance:{secrets.token_hex(8)}".encode()).decode()
        return None

    def request(self, method, path, auth="token", headers=None, body=None, limit=JSON_LIMIT, platform=None,
                raw=False, token=None, seed=None, sign=True, created=None, nonce=None):
        """`platform`: sent as Lantern-Platform; `raw`: a file, not a JSON document. `token` and `seed`: another
        device's token and key (else the suite's own, for auth "token"); a request with a key and no token is a
        pairing's poll. `sign` False sends it unsigned; `created` and `nonce` choose the signature's."""
        u = self.origin
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        kw = {"context": self.context} if u.scheme == "https" else {}
        conn = cls(u.hostname, u.port, timeout=self.timeout, **kw)
        hdrs = {"User-Agent": f"LanternConformance/{VERSION}", "Accept-Language": "en", **(headers or {})}
        if platform:
            hdrs["Lantern-Platform"] = platform
        authorization = "Bearer " + token if token else self.authorization(auth)
        if authorization:
            hdrs["Authorization"] = authorization
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        key = seed if seed is not None else (self.seed if auth == "token" and token is None and self.token else None)
        if key is not None and sign:
            hdrs.update(self.signed(key, method, path, authorization, body, created, nonce))
        label = "device" if token else "anonymous" if auth == "none" or (auth == "token" and self.token is None) else auth
        try:
            conn.request(method, path, body=body, headers=hdrs)
            self.check_pin(conn)
            r = conn.getresponse()
            data = b"" if method == "HEAD" else r.read(limit + 1)
            res = Response(method, path, label, r.status, r.headers, data[:limit], len(data) > limit, raw, platform)
        finally:
            conn.close()
        date = res.header("Date")
        if date:
            try:
                skew = parsedate_to_datetime(date).timestamp() - time.time()
                self.offset = skew if abs(skew) > 30 else 0
            except (TypeError, ValueError):
                pass
        self.log.append(res)
        return res


class Suite(checks_v05.NewFamilies, checks_v06.Sweep, static_check.StaticChecks):
    version = VERSION

    def __init__(self, args):
        self.args = args
        u = urlsplit(args.url if "://" in args.url else "https://" + args.url)
        self.origin = u
        if u.scheme == "https":
            ctx = ssl.create_default_context(cafile=args.cafile)
            if args.insecure or args.pin:   # with --pin, the pinned key is what is trusted (SPEC.md § 5.3)
                ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        else:
            ctx = None
        seed = None
        if args.key:
            try:
                seed = base64.b64decode(Path(args.key).read_text(encoding="ascii").strip(), validate=True)
            except (OSError, ValueError):
                sys.exit(f"conformance: {args.key} is not a device key (its 32-byte seed, base64)")
            if len(seed) != 32:
                sys.exit(f"conformance: {args.key} is not a device key (its 32-byte seed, base64)")
        pin = args.pin.lower().replace(":", "") if args.pin else None
        if pin and not re.fullmatch(r"[0-9a-f]{64}", pin):
            sys.exit("conformance: --pin is the SHA-256 of the server's SPKI, 64 hex digits (SPEC.md § 5.3)")
        self.http = Client(u, args.token, ctx, args.timeout, seed, pin)
        self.seed = seed
        self.results = []
        self.level = "core"     # the level the checks being run count for (SPEC.md § 17)
        self.validators = None if args.no_schemas else load_validators(Path(args.schemas))
        self.base = args.base
        self.hello = self.hello_anon = None
        self.sample = None    # an app from the first page
        self.apps = None      # the whole library, when it could be read
        self.bytes = {}       # app id -> the file, read whole
        self.pair = None      # a pairing code the suite asked for
        self.homebrew = None  # every homebrew entry of the listing, when it could be read
        self.entries = {}     # (platform, id) -> the entry, read on its own route
        self.cheats = None    # every cheat set
        self.upload = None    # the save the suite sent by resumable upload: {"title_id", "save_id", "platform", "data"}
        self.created = []     # (platform, title_id, save_id) of the backups the suite made, until deleted
        self.uploads = []     # upload addresses the suite opened, until finished or abandoned
        self.out = sys.stdout

    # Reporting.

    def check(self, cid, section, title, fn, level="must"):
        blind = False
        try:
            detail, status = fn(), "PASS"
        except Skip as e:
            detail, status, blind = str(e), "SKIP", isinstance(e, Blind)
        except Warn as e:
            detail, status = str(e), "WARN"
        except Fail as e:
            detail, status = str(e), "FAIL" if level == "must" else "WARN"
        except (OSError, http.client.HTTPException) as e:
            detail, status = f"connection: {e}", "FAIL"
        reqs = reqs_of(cid)
        self.results.append((status, section, cid, title, detail, self.level, blind, reqs))
        ids = f"  [{' '.join(reqs)}]" if reqs else ""
        print(f"{status:<4}  § {section:<5} {cid:<30} {title}{ids}", file=self.out)
        if detail:
            for line in str(detail).splitlines():
                print(f"{'':<14}{line}", file=self.out)
        self.out.flush()
        return status == "PASS"

    def validate(self, doc, name, where):
        if self.validators is None:
            return
        errors = list(self.validators[name].iter_errors(doc))
        expect(not errors, f"{where}: not a valid {name}.json: " + "; ".join(
            f"{e.json_path}: {e.message[:200]}" for e in errors[:3]))

    def api(self, path):
        return self.base.rstrip("/") + path

    def get_json(self, path, schema, auth="token", status=200, platform=None):
        r = self.http.request("GET", path, auth=auth, platform=platform)
        expect(r.status == status, f"{r}, expected {status}" + problem_detail(r))
        doc = r.json()
        self.validate(doc, schema, str(r))
        return r, doc

    def expect_problem(self, r, statuses, codes=None):
        expect(r.status in statuses, f"{r}, expected {' or '.join(map(str, statuses))}" + problem_detail(r))
        if codes and r.is_json:
            code = r.json().get("code") if isinstance(r.json(), dict) else None
            expect(code in codes, f"{r}: code {code!r}, expected {' or '.join(sorted(codes))}")

    def features(self, hello):
        return {f: hello.get("features", {}).get(f, 0) for f in FAMILIES} if hello else {f: 0 for f in FAMILIES}

    def scopes(self):
        return set(((self.hello or {}).get("account") or {}).get("scopes") or [])

    # The run.

    def run(self):
        print(f"Lantern conformance {VERSION}: {self.origin.scheme}://{self.origin.netloc}/"
              + (" with a token" if self.args.token else " anonymously")
              + (" and its device key" if self.seed else ""), file=self.out)
        self.level = "core"
        self.check("transport.https", "2", "HTTPS, or plain HTTP on loopback only", self.c_https)
        if not self.check("handshake.well-known", "4.2", "GET /.well-known/lantern is a valid handshake",
                          self.c_well_known):
            print("No handshake: nothing else can be checked.", file=self.out)
            if self.args.token and not self.seed:
                print("A token bound to a device key needs its key: --key FILE.", file=self.out)
            return self.summary()
        if self.args.pin:
            self.check("transport.pin", "5.3", "The server's certificate carries the pinned key", self.c_pin)
        self.check("handshake.v1", "4.2", "GET <base>/v1/ is the same handshake", self.c_v1)
        self.check("handshake.versions", "3.1", "The server serves version 1", self.c_versions)
        self.check("handshake.anonymous", "4.2", "Without credentials: account anonymous", self.c_anonymous)
        self.check("handshake.account", "4.2", "With a token: the account and its state", self.c_account)
        self.check("handshake.platforms", "4.3", "platforms: names, the same for every caller", self.c_platforms)
        self.check("handshake.auth", "5.4", "signatures and auth: the same for every caller, offered with pairing",
                   self.c_auth)
        self.check("auth.unknown-token", "5.1", "An unknown token gives 401 with WWW-Authenticate: Bearer",
                   self.c_unknown_token)
        self.check("auth.unknown-handshake", "4.2", "An unknown token gives 401 on the handshake too",
                   self.c_unknown_handshake)
        self.check("auth.basic-refused", "5.1", "HTTP Basic is refused: 401 with a Bearer challenge",
                   self.c_basic)
        self.check("auth.missing", "5.1", "A private server answers 401 without a token", self.c_missing)
        self.check("auth.frozen", "4.2", "A frozen account: every feature but pairing at 0, 403 account_frozen",
                   self.c_frozen)
        mine = self.features(self.hello)
        self.check("pairing.offered", "5.2", "A private server offers pairing, to every caller alike",
                   self.c_pairing_offered)
        if self.features(self.hello_anon)["pairing"]:
            self.check("pairing.code", "5.2", "A pairing code: its alphabet, length, interval and expiry",
                       self.c_pairing_code)
            self.check("pairing.verify-complete", "5.2", "verify_complete: on the origin, the code in it; opening "
                       "it approves nothing", self.c_verify_complete)
            self.check("pairing.verify-page", "5.3", "The approval page shows the short fingerprint of the server's "
                       "key", self.c_verify_page)
            self.check("pairing.waiting", "5.2", "Polling an unapproved pairing gives 202", self.c_pairing_waiting)
            self.check("pairing.slow-down", "5.2", "Polling faster than interval gives 429 slow_down",
                       self.c_pairing_slow, level="should")
            self.check("pairing.unknown", "5.2", "An unknown poll address gives 410", self.c_pairing_unknown)
            self.check("pairing.key", "5.4", "A pairing with a device key: a bad key gives 400, an unsigned poll 401, "
                       "a signed one 202", self.c_pairing_key)
            self.check("pairing.bearer-only", "5.4", "A server that takes only bound tokens refuses a pairing without "
                       "a key: 400 key_required", self.c_bearer_only)
        if mine["library"]:
            self.check("apps.first-page", "6.2", "GET <base>/v1/apps is a valid page", self.c_first_page)
        for family in FAMILIES:
            if family not in ("signatures", "encrypted_saves"):
                self.level = family if family in LEVELS else "core"
                self.check(f"features.{family}", "4.2", f"Feature {family} ({mine[family]}) is honoured",
                           lambda f=family: self.c_feature(f, "token", mine[f]))
        self.level = "core"
        if self.args.token is not None:
            self.check("features.anonymous", "4.2", "Without credentials, features are honoured too",
                       self.c_features_anonymous)
        if self.features(self.hello_anon)["pairing"] or mine["library"]:
            self.check("signatures.unsigned", "5.4", "A bound token without a signature gives 401 signature_required",
                       self.c_sig_unsigned)
            self.check("signatures.invalid", "5.4", "A signature that does not verify, or of another form, gives 401 "
                       "signature_invalid", self.c_sig_invalid)
            self.check("signatures.stale", "5.4", "A created outside the window gives 401 signature_expired",
                       self.c_sig_stale)
            self.check("signatures.replayed", "5.4", "A nonce taken twice gives 401 signature_replayed",
                       self.c_sig_replayed)
            self.check("signatures.digest", "5.4", "A signed body that does not match its Content-Digest gives 422",
                       self.c_sig_digest)
            self.check("signatures.accept-signature", "5.4", "A 401 for a signature carries Accept-Signature",
                       self.c_sig_accept, level="should")
        self.check("language.handshake", "2.2", "The motd says its language", self.c_language_handshake)
        self.check("language.problem", "2.2", "An error says its language, and follows Accept-Language",
                   self.c_language_problem)
        self.check("versions.accept-schema", "3.2", "Accept-Schema of the schemas written is honoured",
                   self.c_accept_schema, level="should")
        if mine["library"]:
            for sort in ("name", "added", "release"):
                self.check(f"apps.pages.{sort}", "6.2", f"Pages by {sort}: stable, no repeat, no skip",
                           lambda s=sort: self.c_walk(s))
            self.check("apps.sha256", "6.1", "Every app has its sha256", self.c_sha256)
            self.check("apps.platforms", "4.3", "Every app's platform is one the handshake lists",
                       self.c_app_platforms)
            self.check("apps.page-size", "6.2", "A larger page_size is lowered to limits.page_size; 0 gives 400",
                       self.c_page_size)
            self.check("apps.bad-cursor", "6.2", "An unknown cursor gives 400 or 410", self.c_bad_cursor)
            self.check("apps.filters", "6.2", "type and title_id filter; a bad value gives 400", self.c_filters)
            self.check("apps.etag", "14", "A listing has an ETag and honours If-None-Match", self.c_etag,
                       level="should")
            self.check("caching.not-modified", "14", "If-None-Match, weak or *: 304 with the 200's headers; a tag "
                       "per page and platform", self.c_not_modified)
            self.check("apps.search", "6.2", "q: names held, by canonical caseless match", self.c_apps_search)
            self.check("apps.empty", "2.3", "A listing of nothing: an empty page", self.c_apps_empty)
            self.check("routes.query-twice", "2.4", "A parameter given twice gives 400", self.c_query_twice)
            self.check("routes.query-lenient", "2.4", "Empty values are absent; an unknown parameter is ignored",
                       self.c_query_lenient)
            self.check("missing.want", "6.3", "want empty or of another type: 400; an unknown installed app ignored",
                       self.c_missing_want)
            self.check("platforms.filter", "4.3", "Lantern-Platform: that platform's apps only, all of them",
                       self.c_platform_filter)
            self.check("platforms.query", "4.3", "?platform= overrides Lantern-Platform", self.c_platform_query)
            self.check("platforms.unknown", "4.3", "A platform the server does not serve gives an empty list",
                       self.c_platform_unknown)
            self.check("platforms.bad-name", "4.3", "A name that is not a platform's gives 400",
                       self.c_platform_bad)
            self.check("platforms.vary", "14", "Answers that depend on the platform vary on Lantern-Platform",
                       self.c_platform_vary, level="should")
            self.check("missing.no-platform", "6.3", "Missing without a platform gives 400", self.c_missing_unnamed)
            self.check("missing.installed", "6.3", "Missing: newest update and add-ons of an installed game",
                       self.c_missing_installed)
            self.check("missing.up-to-date", "6.3", "Missing: nothing for an up-to-date game", self.c_missing_current)
            self.check("missing.base", "6.3", "Missing: with base, the games not installed", self.c_missing_base)
            self.check("missing.malformed", "12", "A malformed body gives 400 bad_request", self.c_malformed)
            self.check("limits.depth", "13", "A body nested deeper than 16 gives 400 or 413, not a failure",
                       self.c_depth)
            self.check("files.whole", "6.6", "Whole files and HEAD: length, ETag, sha256 and Repr-Digest",
                       self.c_files)
            self.check("files.ranges", "6.6", "Ranges: 206 with the right slice and the whole file's Repr-Digest",
                       self.c_ranges)
            self.check("files.unsatisfiable", "6.6", "A range outside the file gives 416 with Content-Range", self.c_416)
            self.check("files.unknown", "6.6", "An unknown file id gives 404 or 410", self.c_unknown_file)
            self.check("files.if-range", "6.6", "If-Range honoured; several ranges never multipart", self.c_if_range)
            self.check("compression.json", "2.1", "JSON compressed as Accept-Encoding asks: zstd or br, and gzip",
                       self.c_compression_json, level="should")
            self.check("compression.etag", "2.1", "Compressed JSON: Vary Accept-Encoding, an ETag of its own",
                       self.c_compression_etag)
            self.check("compression.files", "2.1", "A file is never sent with a Content-Encoding",
                       self.c_compression_files)
            self.check("budget.cold-start", "B.8", f"A cold start: 3 requests, {BUDGET >> 10} KiB of JSON at most",
                       self.c_budget, level="should")
        if mine["changes"]:
            self.check("changes.token", "6.4", "Changes: no apps and a token, then from it", self.c_changes)
            self.check("changes.bad-token", "6.4", "An unknown since token gives 400 or 410", self.c_bad_since)
        self.level = "titles"
        if mine["titles"]:
            self.check("titles.known", "7.1", "A title of the library is a valid sheet, of its platform",
                       self.c_title)
            self.check("titles.unknown", "7.1", "An unknown title gives 404", self.c_unknown_title)
            self.check("titles.bulk", "7.2", "Many titles at once: those known, and the ids unknown", self.c_titles)
            self.check("titles.bulk-limit", "7.2", f"More than {TITLES_AT_ONCE} ids give 400", self.c_titles_limit)
            self.check("titles.images", "7.1", "Images on the server's origin: a long cache lifetime", self.c_images,
                       level="should")
            self.check("titles.changes", "7.3", "Title changes: a token, then from it", self.c_title_changes)
            self.check("titles.bad-token", "7.3", "An unknown since token gives 400 or 410", self.c_title_bad_since)
        self.level = "homebrew"
        if mine["homebrew"]:
            self.check("homebrew.pages", "8.5", "The homebrew listing: pages, no manifest, each platform alone",
                       self.c_homebrew_pages)
            self.check("homebrew.entries", "8.1", "Each entry on its own route: valid, the same as listed",
                       self.c_homebrew_entries)
            self.check("homebrew.manifests", "8.2", "Manifests: sane paths, their digest, the profile's roots",
                       self.c_homebrew_manifests)
            self.check("homebrew.kinds", "8.1", "Kinds, genres, tags and arches of the lists, of the profile; "
                       "system ids unique", self.c_homebrew_kinds)
            self.check("homebrew.filters", "8.5", "The kind and genre filters: those entries, no others; a malformed "
                       "one gives 400", self.c_homebrew_filters)
            self.check("homebrew.requires", "8.7", "Requirements: text, min's and gpu's shapes", self.c_homebrew_requires)
            self.check("homebrew.ports", "8.1", "Ports: original, engine, data_root in the areas, relative data "
                       "paths, never served", self.c_homebrew_ports)
            self.check("homebrew.packages", "8.2", "Packages: sha256, Repr-Digest, an archive as its manifest says",
                       self.c_homebrew_packages)
            self.check("homebrew.signatures", "8.4", "A served signature verifies over the defined bytes",
                       self.c_homebrew_signatures, level="should")
            self.check("homebrew.updates", "8.5", "Updates: the entries newer than what is installed, no others",
                       self.c_homebrew_updates)
            self.check("homebrew.updates-platform", "8.5", "Updates without a platform give 400",
                       self.c_homebrew_updates_unnamed)
            self.check("homebrew.unknown", "8.1", "An unknown id gives 404", self.c_homebrew_unknown)
            self.check("homebrew.ambiguous", "4.3", "An id of two platforms gives 400 without a platform",
                       self.c_ambiguous)
        self.level = "cheats"
        if mine["cheats"]:
            self.check("cheats.sets", "10", "Cheat sets: valid, ids unique, filtered as asked", self.c_cheats)
            self.check("cheats.text", "10", "A set's text: a file of its size and sha256, 1 MiB at most",
                       self.c_cheat_text)
            self.check("cheats.unknown", "10", "An unknown set gives 404", self.c_cheat_unknown)
            self.check("cheats.write", "10", "Without cheats.write, writing is refused", self.c_cheat_write)
            self.check("cheats.write-cycle", "10", "With cheats.write: a set posted (201), listed, read, replaced "
                       "(204), deleted (204), then gone", self.c_cheat_write_cycle)
        self.level = "requests"
        if mine["requests"]:
            self.check("requests.list", "11", "The account's requests: valid, of the platform asked",
                       self.c_requests)
            self.check("requests.create", "11", "A request: 201, then 200 with the same open request, listed",
                       self.c_request_create)
            self.check("requests.delete", "11", "Withdrawing it: 204, then 404; an unknown one 404",
                       self.c_request_delete)
        self.level = "saves"
        if mine["saves"]:
            self.check("saves.limits", "4.2", "limits: save_body, save_size and saves_kept_per_title",
                       self.c_save_limits)
            self.check("saves.list", "9.1", "Save backups: valid, newest first per title", self.c_saves_list)
            if "saves" in self.scopes():
                self.check("saves.no-platform", "9.1", "Writing a save without a platform gives 400",
                           self.c_save_unnamed)
                self.check("saves.upload", "9.3", "Resumable upload: open, two chunks, HEAD's offset, 409, finish",
                           self.c_save_upload)
                self.check("saves.read", "9.1", "The uploaded backup: listed, then read back whole", self.c_save_read)
                self.check("saves.upload-digest", "9.3", "An upload of another SHA-256 gives 422 digest_mismatch",
                           self.c_save_upload_digest)
                self.check("saves.upload-too-large", "9.3", "An upload above limits.save_size gives 413",
                           self.c_save_too_large)
                self.check("saves.single", "9.2", "One request: Content-Digest required, checked, then kept",
                           self.c_save_single)
                self.level = "encrypted_saves"
                if mine["encrypted_saves"]:
                    self.check("e2e.upload", "9.4", "An encrypted backup: uploaded and sent in one request, kept as "
                               "sent, listed with its encryption", self.c_e2e_upload)
                self.level = "saves"
                self.check("e2e.not-offered", "9.4", "Without encrypted_saves, a backup with an encryption gives 400",
                           self.c_e2e_not_offered)
                self.check("saves.cleanup", "9.1", "What the suite made is deleted (204), then gone (404)",
                           self.c_save_cleanup)
            else:
                self.check("saves.upload", "9.3", "Resumable upload", lambda: _blind("the token lacks the scope saves"))
        self.level = "admin"
        self.check("admin.refused", "5.7", "Without the scope admin, the administration API is refused",
                   self.c_admin_refused)
        if mine["admin"]:
            self.check("admin.users", "5.7", "Accounts: a valid page, no password", self.c_admin_users)
            self.check("admin.users-write", "5.7", "An account made (201), made again (409), frozen (200)",
                       self.c_admin_users_write)
            self.check("admin.pairings", "5.7", "A keyed pairing listed with its code and key, approved for the scopes "
                       "asked and the account's", self.c_admin_pairings)
            self.check("admin.rating-cap", "5.6", "A rating cap hides what is above it, everywhere",
                       self.c_admin_rating_cap)
            self.check("admin.refuse", "5.7", "A pairing refused: its poll gives 410", self.c_admin_refuse)
            self.check("admin.devices", "5.7", "Devices listed without their token; one revoked loses its access at "
                       "once", self.c_admin_devices)
            self.check("admin.invitations", "5.5", "An invitation: made, listed, redeemed once, then 410; revoked",
                       self.c_admin_invitations)
            self.check("admin.requests", "11", "Requests decided: declined with a reason the requester reads, then "
                       "final; done; an event at each change", self.c_admin_requests)
            self.check("admin.users-delete", "5.7", "An account deleted: confirmed by its name, its token and "
                       "invitations dead, its sync data erased", self.c_admin_users_delete)
        self.level = "events"
        if mine["events"]:
            self.check("events.stream", "18.1", "The stream: retry, ready and its id, never compressed; limits",
                       self.c_events_stream)
            self.check("events.resume", "18.1", "An event of the suite's own: on the stream, again with "
                       "Last-Event-ID, in a long poll, not on another platform's stream", self.c_events_resume)
            self.check("events.bad-token", "18.1", "A Last-Event-ID never given: 400 or 410", self.c_events_bad_token)
            self.check("events.heartbeat", "18.1", "Something on the stream every limits.heartbeat seconds",
                       self.c_events_heartbeat)
            self.check("events.limit", "18.4", "Beyond limits.event_streams: 429 with Retry-After", self.c_events_limit)
            self.check("events.revoked", "18.1", "A revoked device's stream ends by its next heartbeat",
                       self.c_events_revoked)
        self.level = "peers"
        if mine["peers"]:
            self.check("peers.handshake", "19.3", "peers: a grant key of 32 bytes, the same for every caller",
                       self.c_peers_handshake)
            self.check("peers.grant", "19.3", "Grants for files of the library verify; an unknown file gives 404",
                       self.c_peers_grant)
            self.check("peers.mirrors", "19.2", "Mirrors: HTTPS, or HTTP on a private network, no token in them",
                       self.c_peers_mirrors)
            self.check("peers.mirrors-fetch", "19.2", "Mirrors serve the file's bytes, read without a credential",
                       self.c_mirrors_fetch)
            self.check("values.hex-case", "2.3", "A SHA-256 in a path, in upper case: 404", self.c_hex_case)
            self.check("peer.refused", "19.4", "The peer: without a grant, with a changed one or another file's, 403",
                       self.c_peer_refused)
            self.check("peer.serves", "19.4", "The peer serves a file granted: its bytes, Repr-Digest, ranges",
                       self.c_peer_serves)
            self.check("peer.discovery", "19.5", "The peer answers discovery that asks for peers, and only that",
                       self.c_peer_discovery)
            self.check("peer.slots", "19.4", "The peer's slots: its downloads at once, then 429", self.c_peer_slots)
            self.check("peer.rate", "19.4", "The peer limits requests: 429 with Retry-After", self.c_peer_rate)
        self.level = "sync"
        if mine["sync"]:
            self.check("sync.overview", "20.3", "GET <base>/v1/sync: generation, collections, the device's id",
                       self.c_sync_overview)
            self.check("sync.write", "20.4", "Items merged by the rule: kept, not replaced by an older, a deletion "
                       "wins a tie; listed since a revision", self.c_sync_write)
            self.check("sync.future", "20.4", "An updated far ahead is taken as the server's time", self.c_sync_future)
            self.check("sync.if-match", "20.4", "If-Match of another revision: 412, nothing changed",
                       self.c_sync_if_match)
            self.check("sync.generation", "20.4", "A write of another generation: 409", self.c_sync_generation)
            self.check("sync.installed", "20.4", "Another device's item of installed: 403", self.c_sync_installed)
            self.check("sync.malformed", "20.4", "An item of another form: 400", self.c_sync_malformed)
            self.check("sync.limits", "20.5", "limits.sync_items", self.c_sync_limits, level="should")
        if mine["events"]:
            # Late, so that its wait passed while the checks above ran (events.stream began it).
            self.level = "events"
            self.check("events.long-poll", "18.3", "changes with wait: answers by then; wait without since gives 400",
                       self.c_events_long_poll)
        self.level = "core"
        for family, (path, _) in BODIES.items():
            if mine[family] and (family != "saves" or "saves" in self.scopes()):
                self.level = family if family in LEVELS else "core"
                self.check(f"schema.refused.{family}", "3.2", f"POST {path} of schema 2 gives 422 unsupported_schema",
                           lambda f=family: self.c_schema_2(f))
        self.level = "core"
        self.check("errors.unknown-route", "12", "An unknown route gives 404 not_found", self.c_unknown_route)
        self.check("routes.paths", "2.4", "A trailing / is another path; <base>/v1 the handshake", self.c_routes)
        self.check("routes.head", "2.4", "HEAD as GET, without a body, on every GET route", self.c_head)
        self.check("routes.content-type", "2.4", "A document of another Content-Type gives 400", self.c_content_type)
        self.check("values.i-json-refused", "2.3", "A document that is not I-JSON gives 400", self.c_i_json_refused)
        self.check("discovery.reply", "4.1", "LAN discovery reply", self.c_discovery)
        self.check("discovery.rate", "4.1", "Discovery: 10 replies a second to an address at most",
                   self.c_discovery_rate, level="should")
        self.check("discovery.dns-sd", "4.1", "DNS-SD: _lantern._tcp, its uid, path, versions and port",
                   self.c_dns_sd, level="should")
        if self.features(self.hello_anon)["pairing"]:
            self.check("invitations.rate-limit", "5.5", "Wrong invitation codes from one address: 429 slow_down",
                       self.c_invitation_rate)
            self.check("pairing.rate-limit", "5.2", "Pairing requests from one address: 429 slow_down",
                       self.c_pairing_rate)
        for section, reqs, rule in CLIENT_RULES:
            self.check("client-rule", section, f"{rule} [{' '.join(reqs)}]", client_rule)
        # Over every response the run saw.
        self.check("errors.problem", "12", "Every error is a valid application/problem+json", self.g_problems)
        self.check("errors.never-200", "12", "No error is sent with a 2xx status", self.g_never_200)
        self.check("errors.www-authenticate", "5.1", "Every 401 has WWW-Authenticate: Bearer", self.g_401)
        self.check("auth.no-basic", "5.1", "No response asks for HTTP Basic", self.g_no_basic)
        self.check("documents.schema", "3.2", "Every document has an integer schema", self.g_schema)
        self.check("documents.type", "2", "Every document is application/json", self.g_ctype)
        self.check("documents.limits", "13", "Documents stay within the limits", self.g_limits)
        self.check("documents.date", "5.4", "Every response carries Date", self.g_date)
        self.check("documents.i-json", "2.3", "Every document is I-JSON", self.g_i_json)
        self.check("documents.times", "2.3", "Every time in UTC with Z, every date YYYY-MM-DD", self.g_times)
        self.check("documents.nfc", "2.3", "Text in Normalization Form C", self.g_nfc, level="should")
        self.check("routes.no-redirect", "2.4", "No route answers with a redirect", self.g_no_redirect)
        self.check("auth.tokens", "5.1", "Tokens of 128 bits at least, each its own", self.g_tokens)
        self.check("deprecation.headers", "3.4", "Deprecation and Sunset, where sent, are of their forms",
                   self.g_deprecation)
        self.check("caching.private", "14", "Authenticated answers: Cache-Control private, Vary Authorization",
                   self.g_private, level="should")
        return self.summary()

    def levels(self):
        """{level: None when reached, else why not} (SPEC.md § 17)."""
        mine = self.features(self.hello)
        out = {}
        for level in LEVELS:
            mine_results = [r for r in self.results if r[5] == level]
            offered = mine["library"] if level == "core" else mine[level]
            if not offered:
                why = "not offered to this caller" + (" (run it with a token)" if self.args.token is None else "")
            elif any(r[0] == "FAIL" for r in mine_results):
                why = "a check failed"
            elif any(r[6] for r in mine_results):
                why = "checks left out for want of a token, a key or a scope"
            elif level != "core" and out.get("core") is not None:
                why = "Lantern Core is not reached"
            else:
                why = None
            out[level] = why
        return out

    def summary(self):
        counts = {s: sum(1 for r in self.results if r[0] == s) for s in ("PASS", "FAIL", "WARN", "SKIP")}
        print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['WARN']} warning(s), "
              f"{counts['SKIP']} skipped; {len(self.http.log)} requests.", file=self.out)
        if self.hello is not None:
            levels = self.levels()
            reached = [LEVEL_NAMES[x] for x in LEVELS if levels[x] is None]
            print(f"Levels reached (SPEC.md § 17, draft {VERSION[:3]}): " + (" ".join(reached) or "none"), file=self.out)
            for x in LEVELS:
                if levels[x] is not None:
                    print(f"  not {LEVEL_NAMES[x]}: {levels[x]}", file=self.out)
        return 1 if counts["FAIL"] or not self.results else 0

    # Transport and handshake (SPEC.md § 2, 4).

    def c_pin(self):
        expect(self.http.peer_spki == self.http.pin, f"the server's key {self.http.peer_spki}, pinned {self.http.pin}")
        return f"SPKI {self.http.pin[:16]}…"

    def c_https(self):
        if self.origin.scheme == "https":
            return
        if not loopback(self.origin.hostname or ""):
            raise Fail(f"plain HTTP to {self.origin.hostname}, not a loopback address")
        raise Warn("plain HTTP on loopback: for testing only")

    def c_well_known(self):
        _, doc = self.get_json("/.well-known/lantern", "handshake")
        self.hello = doc
        if self.base is None:
            self.base = doc.get("base", "/api/lantern")
            expect(self.base.startswith("/"), f"base {self.base!r} is not a path on the origin")
        return f"base {self.base}, features " + ", ".join(f"{k}={v}" for k, v in self.features(doc).items())

    def c_v1(self):
        _, doc = self.get_json(self.api("/v1/"), "handshake")
        for key in ("schema", "uid", "name", "base", "versions", "platforms", "account", "features"):
            expect(doc.get(key) == self.hello.get(key), f"{key} differs from /.well-known/lantern")

    def c_versions(self):
        expect(1 in self.hello.get("versions", []), f"versions {self.hello.get('versions')}")

    def c_anonymous(self):
        _, doc = self.get_json(self.api("/v1/"), "handshake", auth="none")
        self.hello_anon = doc
        expect(doc["account"]["state"] == "anonymous", f"account.state {doc['account']['state']!r}")
        expect(doc["uid"] == self.hello["uid"], "uid differs from the one with credentials")

    def c_account(self):
        if self.args.token is None:
            raise Skip("no token given")
        state = self.hello["account"]["state"]
        expect(state in ("active", "frozen"), f"account.state {state!r} although the token was accepted")
        return f"{state}, scopes {', '.join(self.hello['account']['scopes']) or 'none'}"

    def platforms(self):
        return list((self.hello or {}).get("platforms") or [])

    def c_platforms(self):
        names = self.hello.get("platforms")
        expect(isinstance(names, list), "no platforms list")
        bad = [n for n in names if not (isinstance(n, str) and PLATFORM.match(n))]
        expect(not bad, f"not platform names: {bad[:5]}")
        expect(len(set(names)) == len(names), "a platform listed twice")
        if self.hello_anon is not None:
            expect(self.hello_anon.get("platforms") == names, "platforms differ without credentials")
        return ", ".join(names) or "none yet"

    def expect_bearer(self, r):
        self.expect_problem(r, [401], {"unauthorized"})
        challenge = r.header("WWW-Authenticate") or ""
        expect(challenge.lower().startswith("bearer"), f"{r}: WWW-Authenticate {challenge or 'none'}, expected Bearer")

    def c_unknown_token(self):
        self.expect_bearer(self.http.request("GET", self.api("/v1/apps?page_size=1"), auth="unknown"))

    def c_unknown_handshake(self):
        self.expect_bearer(self.http.request("GET", self.api("/v1/"), auth="unknown"))

    def c_basic(self):
        for path in (self.api("/v1/"), self.api("/v1/apps?page_size=1")):
            r = self.http.request("GET", path, auth="basic")
            self.expect_bearer(r)
            expect("basic" not in (r.header("WWW-Authenticate") or "").lower(), f"{r}: a Basic challenge")

    def c_missing(self):
        anon = self.features(self.hello_anon)
        if self.args.token is None or anon["library"] or not self.features(self.hello)["library"]:
            raise Skip("not a private server, or no token given")
        self.expect_bearer(self.http.request("GET", self.api("/v1/apps?page_size=1"), auth="none"))

    def c_frozen(self):
        if self.hello["account"]["state"] != "frozen":
            raise Skip("the account is not frozen")
        on = [f for f, v in self.features(self.hello).items() if v and f not in ("pairing", "signatures")]
        expect(not on, f"features still offered: {', '.join(on)}")
        r = self.http.request("GET", self.api("/v1/apps?page_size=1"))
        self.expect_problem(r, [403], {"account_frozen"})

    # Pairing (SPEC.md § 5.2): its shapes, without approving anything.

    def c_pairing_offered(self):
        anon, mine = self.features(self.hello_anon), self.features(self.hello)
        expect(anon["pairing"] == mine["pairing"],
               f"pairing is {anon['pairing']} without a token, {mine['pairing']} with one")
        if anon["library"]:
            return "a public server" + (", which pairs" if anon["pairing"] else ", which does not pair")
        expect(anon["pairing"] > 0, "a private server without pairing: no console can get a token")

    def c_pairing_code(self):
        r = self.http.request("POST", self.api("/v1/pairing"), auth="none", body=PAIRING)
        expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
        doc = r.json()
        self.validate(doc, "pairing-code", str(r))
        code = doc["code"]
        expect(CODE.fullmatch(code), f"code {code!r}: not 8 to 32 symbols of 23456789ABCDEFGHJKLMNPQRSTUVWXYZ "
                                     "in groups of 4 joined by -")
        expect(isinstance(doc["interval"], int) and doc["interval"] >= 1, f"interval {doc['interval']!r}")
        expect(isinstance(doc["expires"], int) and 1 <= doc["expires"] <= 600,
               f"expires {doc['expires']!r}: a code lives 10 minutes at most")
        verify = urlsplit(doc["verify"])
        expect(verify.scheme == "https" or (verify.scheme == "http" and loopback(verify.hostname or "")),
               f"verify {doc['verify']}: not an HTTPS address")
        poll = urlsplit(doc["poll"])
        expect(not poll.netloc or poll.netloc == self.origin.netloc, f"poll {doc['poll']} is not on the origin")
        self.pair = doc
        return f"{len(code.replace('-', ''))} symbols, every {doc['interval']} s, for {doc['expires']} s"

    def poll_path(self):
        if not self.pair:
            raise Skip("no pairing code (pairing.code)")
        poll = urlsplit(self.pair["poll"])
        return poll.path + (f"?{poll.query}" if poll.query else "")

    def c_pairing_waiting(self):
        r = self.http.request("GET", self.poll_path(), auth="none")
        expect(r.status == 202, f"{r}, expected 202 while the user has not approved" + problem_detail(r))

    def c_pairing_slow(self):
        r = self.http.request("GET", self.poll_path(), auth="none")
        if r.status != 429:
            raise Warn(f"{r} right after another poll, expected 429 slow_down")
        self.expect_problem(r, [429], {"slow_down"})
        if not r.header("Retry-After"):
            raise Warn(f"{r}: no Retry-After")

    def c_pairing_unknown(self):
        r = self.http.request("GET", self.api("/v1/pairing/p_lantern-conformance-" + secrets.token_hex(16)),
                              auth="none")
        self.expect_problem(r, [404, 410], {"gone", "not_found"})

    # Features (SPEC.md § 4.2): a family at 0 is refused, one above 0 answers.

    def title_id(self):
        return self.sample["title_id"] if self.sample else "0100ABCD00010000"

    def probe(self, family, auth):
        method, path, body, schema = PROBES[family]
        sha = self.sample["sha256"] if self.sample else "0" * 64
        path = self.api(path.format(title_id=quote(self.title_id(), safe=""), sha256=sha))
        return self.http.request(method, path, auth=auth, body=body), schema

    def c_feature(self, family, auth, level):
        if family == "events":
            return self.c_feature_events(auth, level)
        if family == "peers" and level and not self.sample:
            raise Skip("no app to ask a grant for")
        r, schema = self.probe(family, auth)
        if not level:
            expect(r.status in (401, 403, 404), f"{r}: feature at 0, expected 401, 403 or 404")
            return f"{r.status}"
        expect(r.status == 200, f"{r}: feature at {level}, expected 200" + problem_detail(r))
        self.validate(r.json(), schema, str(r))

    def c_features_anonymous(self):
        anon = self.features(self.hello_anon)
        problems = []
        for family in FAMILIES:
            if family not in PROBES and family != "events":
                continue
            try:
                self.c_feature(family, "none", anon[family])
            except Fail as e:
                problems.append(f"{family}: {e}")
        expect(not problems, "\n".join(problems))
        return ", ".join(f"{k}={v}" for k, v in anon.items())

    # Library (SPEC.md § 6.1, 6.2).

    def limit(self):
        return self.hello.get("limits", {}).get("page_size", 1000)

    def c_first_page(self):
        _, doc = self.get_json(self.api("/v1/apps"), "apps")
        expect(len(doc["items"]) <= self.limit(), f"{len(doc['items'])} items, above limits.page_size")
        self.sample = doc["items"][0] if doc["items"] else None
        return f"total {doc.get('total')}, {len(doc['items'])} item(s) on the first page"

    def walk(self, path, size, method="GET", body=None, schema="apps", platform=None):
        """Every item of a listing, a page at a time."""
        items, cursor, pages, total = [], None, 0, None
        sep = "&" if "?" in path else "?"
        while True:
            url = f"{path}{sep}page_size={size}" + (f"&cursor={quote(cursor, safe='')}" if cursor else "")
            r = self.http.request(method, url, body=body, platform=platform)
            expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
            doc = r.json()
            self.validate(doc, schema, str(r))
            expect(len(doc["items"]) <= size, f"{r}: {len(doc['items'])} items for page_size {size}")
            items += doc["items"]
            total = doc.get("total", total)
            pages += 1
            cursor = doc["next"]
            if cursor is None:
                return items, pages, total
            expect(pages <= self.args.max_items // max(size, 1) + 10, f"{r}: still a next page after {pages} pages")

    def c_walk(self, sort):
        _, first = self.get_json(self.api(f"/v1/apps?sort={sort}&page_size=1"), "apps")
        total = first.get("total")
        if total is not None and total > self.args.max_items:
            raise Skip(f"{total} apps, above --max-items {self.args.max_items}")
        small = max(1, math.ceil((total or 4) / 4))
        items, pages, total = self.walk(self.api(f"/v1/apps?sort={sort}"), small)
        ids = [a["id"] for a in items]
        dup = {i for i in ids if ids.count(i) > 1}
        expect(not dup, f"repeated: {', '.join(sorted(dup)[:5])}")
        if total is not None:
            expect(len(ids) == total, f"{len(ids)} apps read in {pages} pages, total says {total}")
        big, _, _ = self.walk(self.api(f"/v1/apps?sort={sort}"), self.limit())
        expect([a["id"] for a in big] == ids, f"pages of {small} and of {self.limit()} give another order")
        if sort == "added" and all("added" in a for a in items):
            times = [datetime.fromisoformat(a["added"].replace("Z", "+00:00")) for a in items]
            expect(all(x >= y for x, y in itertools.pairwise(times)), "added is not newest first")
        if sort == "name":
            default, _, _ = self.walk(self.api("/v1/apps"), self.limit())
            expect([a["id"] for a in default] == ids, "without sort, not the order of sort=name")
            self.apps = items
        return f"{len(ids)} apps in {pages} page(s) of {small}"

    def c_sha256(self):
        apps = self.apps or ([self.sample] if self.sample else [])
        if not apps:
            raise Skip("no app in the library")
        bad = [a.get("id", "?") for a in apps if not re.fullmatch(r"[0-9a-f]{64}", str(a.get("sha256", "")))]
        expect(not bad, f"{len(bad)} app(s) without a lower-case hex sha256: {', '.join(bad[:5])}")
        return f"{len(apps)} app(s)"

    def c_app_platforms(self):
        apps = self.library()
        listed = set(self.platforms())
        bad = sorted({a["platform"] for a in apps} - listed)
        expect(not bad, f"apps of {', '.join(bad)}, which the handshake's platforms do not list")
        return ", ".join(f"{p}: {sum(1 for a in apps if a['platform'] == p)}" for p in sorted(listed))

    def c_page_size(self):
        limit = self.limit()
        for size in (limit + 1, 1001):
            r = self.http.request("GET", self.api(f"/v1/apps?page_size={size}"))
            expect(r.status == 200, f"{r}, expected 200 (lowered to the limit)" + problem_detail(r))
            n = len(r.json()["items"])
            expect(n <= limit, f"{r}: {n} items, above limits.page_size {limit}")
        r = self.http.request("GET", self.api("/v1/apps?page_size=0"))
        self.expect_problem(r, [400], {"bad_request"})

    def c_bad_cursor(self):
        r = self.http.request("GET", self.api("/v1/apps?cursor=lantern-conformance-" + secrets.token_hex(6)))
        self.expect_problem(r, [400, 410], {"bad_request", "gone"})

    def c_filters(self):
        for kind in ("base", "update", "dlc"):
            _, doc = self.get_json(self.api(f"/v1/apps?type={kind}&page_size={self.limit()}"), "apps")
            wrong = [a["id"] for a in doc["items"] if a["type"] != kind]
            expect(not wrong, f"type={kind} returned other types: {', '.join(wrong[:5])}")
        tid = self.title_id()
        _, doc = self.get_json(self.api(f"/v1/apps?title_id={quote(tid, safe='')}&page_size={self.limit()}"), "apps")
        wrong = [a["id"] for a in doc["items"] if a["title_id"] != tid]
        expect(not wrong, f"title_id={tid} returned other titles: {', '.join(wrong[:5])}")
        for query in ("type=Lantern", "sort=lantern", "title_id=not%20an%20id%21"):
            self.expect_problem(self.http.request("GET", self.api(f"/v1/apps?{query}")), [400], {"bad_request"})

    def c_etag(self):
        r = self.http.request("GET", self.api("/v1/apps?page_size=1"))
        etag = r.header("ETag")
        if not etag:
            raise Warn(f"{r}: no ETag")
        again = self.http.request("GET", self.api("/v1/apps?page_size=1"), headers={"If-None-Match": etag})
        if again.status != 304:
            raise Warn(f"{again} with If-None-Match, expected 304")

    # Platforms (SPEC.md § 4.3).

    def c_platform_filter(self):
        apps = self.library()
        out = []
        for platform in self.platforms()[:8]:
            items, _, _ = self.walk(self.api("/v1/apps"), self.limit(), platform=platform)
            wrong = [a["id"] for a in items if a["platform"] != platform]
            expect(not wrong, f"Lantern-Platform {platform}: apps of another platform: {', '.join(wrong[:5])}")
            expected = {a["id"] for a in apps if a["platform"] == platform}
            expect({a["id"] for a in items} == expected,
                   f"Lantern-Platform {platform}: {len(items)} apps, the whole library has {len(expected)} of it")
            out.append(f"{platform}: {len(items)}")
        return ", ".join(out) or "no platform listed"

    def c_platform_query(self):
        apps = self.library()
        names = sorted({a["platform"] for a in apps})
        if not names:
            raise Skip("no app in the library")
        wanted = names[0]
        other = names[1] if len(names) > 1 else NO_SUCH_PLATFORM
        items, _, _ = self.walk(self.api(f"/v1/apps?platform={wanted}"), self.limit(), platform=other)
        expect(items and all(a["platform"] == wanted for a in items),
               f"?platform={wanted} with Lantern-Platform {other}: not {wanted}'s apps")
        return f"?platform={wanted} over Lantern-Platform {other}"

    def c_platform_unknown(self):
        out = []
        for path, schema, key in (("/v1/apps", "apps", "items"), ("/v1/homebrew", "homebrew-page", "items"),
                                  ("/v1/cheats", "cheats", "cheats")):
            family = {"/v1/apps": "library", "/v1/homebrew": "homebrew", "/v1/cheats": "cheats"}[path]
            if not self.features(self.hello)[family]:
                continue
            _, doc = self.get_json(self.api(path), schema, platform=NO_SUCH_PLATFORM)
            expect(doc[key] == [], f"{path} for {NO_SUCH_PLATFORM}: {len(doc[key])} item(s), expected none")
            out.append(path)
        return ", ".join(out)

    def c_platform_bad(self):
        r = self.http.request("GET", self.api("/v1/apps?page_size=1"), platform=NOT_A_PLATFORM)
        self.expect_problem(r, [400], {"bad_request"})
        r = self.http.request("GET", self.api("/v1/apps?page_size=1&platform=" + quote(NOT_A_PLATFORM)))
        self.expect_problem(r, [400], {"bad_request"})

    def c_platform_vary(self):
        r = self.http.request("GET", self.api("/v1/apps?page_size=1"), platform=self.sample_platform())
        vary = (r.header("Vary") or "").lower()
        if "lantern-platform" not in vary and "*" not in vary:
            raise Warn(f"{r}: Vary {vary or 'none'}, without Lantern-Platform")

    def sample_platform(self):
        if self.sample:
            return self.sample["platform"]
        return "switch" if "switch" in self.platforms() or not self.platforms() else self.platforms()[0]

    # What the console is missing (SPEC.md § 6.3), against the whole library.

    def library(self):
        if self.apps is None:
            raise Skip("the whole library could not be read (apps.pages.name)")
        return self.apps

    def missing(self, platform, installed, want, size=None):
        body = {"schema": 1, "installed": installed, "want": want}
        items, _, _ = self.walk(self.api("/v1/apps/missing"), size or self.limit(), "POST", body, platform=platform)
        ids = [a["id"] for a in items]
        expect(len(ids) == len(set(ids)), "an app repeated across pages")
        wrong = [a["id"] for a in items if a["platform"] != platform]
        expect(not wrong, f"apps of another platform than {platform}: {', '.join(wrong[:5])}")
        return set(ids)

    def compare(self, got, expected, apps):
        name = {a["id"]: f"{a['name']} {a['app_id']} v{a['version_code']}" for a in apps}
        extra, lack = got - expected, expected - got
        expect(not extra and not lack, "; ".join(
            filter(None, [extra and "unexpected: " + ", ".join(name.get(i, i) for i in sorted(extra)[:5]),
                          lack and "missing: " + ", ".join(name.get(i, i) for i in sorted(lack)[:5])])))
        return f"{len(got)} app(s)"

    def installed_title(self, apps):
        """A base game with an update or an add-on, on a platform whose updates are packages of their own."""
        bases = [a for a in apps if a["type"] == "base" and a["platform"] != "android"]
        if not bases:
            raise Skip("no base game in the library (outside Android, whose updates replace the base)")
        rich = [b for b in bases if any(a["title_id"] == b["title_id"] and a["platform"] == b["platform"]
                                        and a["type"] != "base" for a in apps)]
        return (rich or bases)[0]

    def of_title(self, apps, base):
        return [a for a in apps if a["title_id"] == base["title_id"] and a["platform"] == base["platform"]]

    def c_missing_unnamed(self):
        body = {"schema": 1, "installed": [], "want": ["base"]}
        self.expect_problem(self.http.request("POST", self.api("/v1/apps/missing"), body=body), [400],
                            {"bad_request"})

    def c_missing_installed(self):
        apps = self.library()
        base = self.installed_title(apps)
        mine = self.of_title(apps, base)
        updates = [a for a in mine if a["type"] == "update"]
        newest = max((a["version_code"] for a in updates), default=-1)
        expected = {a["id"] for a in updates if a["version_code"] == newest and newest > base["version_code"]}
        expected |= {a["id"] for a in mine if a["type"] == "dlc"}
        got = self.missing(base["platform"], [{"app_id": base["app_id"], "version_code": base["version_code"]}],
                           ["update", "dlc"], size=1 if len(expected) > 1 else None)
        return f"{base['name']}: " + self.compare(got, expected, apps)

    def c_missing_current(self):
        apps = self.library()
        base = self.installed_title(apps)
        updates = [a for a in self.of_title(apps, base) if a["type"] == "update"]
        installed = [{"app_id": base["app_id"], "version_code": base["version_code"]}]
        if updates:
            newest = max(updates, key=lambda a: a["version_code"])
            installed.append({"app_id": newest["app_id"], "version_code": newest["version_code"]})
        return self.compare(self.missing(base["platform"], installed, ["update"]), set(), apps)

    def c_missing_base(self):
        apps = self.library()
        platform = self.sample_platform()
        expected = {a["id"] for a in apps if a["type"] == "base" and a["platform"] == platform}
        return f"{platform}: " + self.compare(self.missing(platform, [], ["base"]), expected, apps)

    def c_malformed(self):
        r = self.http.request("POST", self.api("/v1/apps/missing"), body=b'{"schema": 1, "installed": [',
                              headers={"Content-Type": "application/json"}, platform=self.sample_platform())
        self.expect_problem(r, [400], {"bad_request"})

    def c_schema_2(self, family):
        path, doc = BODIES[family]
        tid = quote(self.save_title()[1] if family == "saves" else self.title_id(), safe="")
        doc = json.loads(json.dumps(doc).replace("{title_id}", self.title_id()))
        platform = self.save_title()[0] if family == "saves" else self.sample_platform()
        r = self.http.request("POST", self.api(path.replace("{title_id}", tid)), body=doc, platform=platform)
        self.expect_problem(r, [422], {"unsupported_schema"})

    # Files (SPEC.md § 6.6).

    def chosen(self):
        apps = self.apps or ([self.sample] if self.sample else [])
        if not apps:
            raise Skip("no app in the library")
        picked, budget = [], self.args.max_download
        for a in sorted(apps, key=lambda a: a["size"]):
            if a["size"] > budget or len(picked) >= self.args.max_files:
                break
            picked.append(a)
            budget -= a["size"]
        return picked

    def file_path(self, url):
        return url if url.startswith("/") else urlsplit(url).path

    def fetch(self, url, size, sha256, platform=None):
        """A file the protocol points at, checked as SPEC.md § 6.6 wants; its bytes."""
        r = self.http.request("GET", self.file_path(url), limit=size, platform=platform, raw=True)
        expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
        expect(not r.truncated and len(r.body) == size, f"{r}: {len(r.body)} bytes, size says {size}")
        expect(r.header("Content-Length") == str(size), f"{r}: Content-Length {r.header('Content-Length')}")
        expect((r.header("Accept-Ranges") or "").lower() == "bytes", f"{r}: no Accept-Ranges: bytes")
        etag = r.header("ETag") or ""
        expect(etag.startswith('"'), f"{r}: no strong ETag ({etag or 'none'})")
        digest = hashlib.sha256(r.body).hexdigest()
        expect(digest == sha256, f"{r}: sha256 {digest}, the document says {sha256}")
        check_repr_digest(r, digest)
        head = self.http.request("HEAD", self.file_path(url), platform=platform, raw=True)
        expect(head.status == 200, f"{head}, expected 200")
        check_repr_digest(head, digest)
        return r.body

    def c_files(self):
        picked = self.chosen()
        if not picked:
            raise Skip(f"every file is above --max-download {self.args.max_download}")
        for app in picked:
            self.bytes[app["id"]] = self.fetch(app["file"], app["size"], app.get("sha256"))
        return f"{len(picked)} file(s), {sum(a['size'] for a in picked)} bytes"

    def c_ranges(self):
        picked = [a for a in self.chosen() if a["size"] >= 2]
        if not picked:
            raise Skip("no file of 2 bytes or more within --max-download")
        app = picked[-1]
        whole = self.bytes.get(app["id"])
        if whole is None:
            raise Skip("the file could not be read whole (files.whole)")
        size = len(whole)
        mid = size // 2
        cases = [("bytes=0-0", 0, 0), (f"bytes=0-{min(99, size - 1)}", 0, min(99, size - 1)),
                 (f"bytes={mid}-{min(mid + 9, size - 1)}", mid, min(mid + 9, size - 1)),
                 (f"bytes=-{min(10, size)}", size - min(10, size), size - 1),
                 (f"bytes={size - 1}-", size - 1, size - 1),
                 (f"bytes={max(0, size - 5)}-{size + 100}", max(0, size - 5), size - 1)]
        path = self.file_path(app["file"])
        for header, start, end in cases:
            r = self.http.request("GET", path, headers={"Range": header}, limit=size, raw=True)
            expect(r.status == 206, f"{r} for {header}, expected 206" + problem_detail(r))
            expect(r.header("Content-Range") == f"bytes {start}-{end}/{size}",
                   f"{r} for {header}: Content-Range {r.header('Content-Range')}, expected bytes {start}-{end}/{size}")
            expect(r.header("Content-Length") == str(end - start + 1), f"{r} for {header}: Content-Length")
            expect(r.body == whole[start:end + 1], f"{r} for {header}: not the bytes of the whole file")
            check_repr_digest(r, hashlib.sha256(whole).hexdigest())
        return f"{len(cases)} ranges of {app['name']} ({size} bytes)"

    def c_416(self):
        apps = self.apps or ([self.sample] if self.sample else [])
        if not apps:
            raise Skip("no app in the library")
        app = apps[0]
        r = self.http.request("GET", self.file_path(app["file"]), headers={"Range": f"bytes={app['size']}-"},
                              limit=1 << 16, raw=True)
        expect(r.status == 416, f"{r} for bytes={app['size']}-, expected 416")
        cr = r.header("Content-Range")
        expect(cr == f"bytes */{app['size']}", f"{r}: Content-Range {cr}, expected bytes */{app['size']}")

    def c_unknown_file(self):
        r = self.http.request("GET", self.api("/v1/files/f_lantern-conformance-" + secrets.token_hex(8)))
        self.expect_problem(r, [404, 410], {"not_found", "gone"})

    # Changes (SPEC.md § 6.4).

    def c_changes(self):
        _, doc = self.get_json(self.api("/v1/changes"), "changes")
        expect(doc["added"] == [] and doc["removed"] == [], "without since, apps were returned")
        _, later = self.get_json(self.api(f"/v1/changes?since={quote(doc['since'], safe='')}"), "changes")
        return f"{len(later['added'])} added, {len(later['removed'])} removed since the token"

    def c_bad_since(self):
        r = self.http.request("GET", self.api("/v1/changes?since=lantern-conformance-" + secrets.token_hex(6)))
        self.expect_problem(r, [400, 410], {"bad_request", "gone"})

    # Titles (SPEC.md § 7).

    def check_title(self, doc, where):
        images = [doc[k] for k in ("icon", "banner") if k in doc] + list(doc.get("screenshots", []))
        for img in images:
            url = urlsplit(img["url"])
            if img.get("external"):
                expect(url.scheme in ("http", "https"), f"{where}: external image {img['url']} is not an absolute URL")
            else:
                expect(not url.netloc or url.netloc == self.origin.netloc,
                       f"{where}: image {img['url']} is elsewhere but not marked external")
        if "video" in doc:
            expect(doc["video"].get("external") is True, f"{where}: video not marked external")
        return images

    def c_title(self):
        if not self.sample:
            raise Skip("no app in the library")
        tid, platform = self.sample["title_id"], self.sample["platform"]
        _, doc = self.get_json(self.api(f"/v1/titles/{quote(tid, safe='')}"), "title", platform=platform)
        expect(doc["title_id"] == tid and doc["platform"] == platform,
               f"{doc['platform']}/{doc['title_id']}, asked {platform}/{tid}")
        images = self.check_title(doc, "the title")
        return f"{doc['name']}, {len(images)} image(s)"

    def unknown_id(self):
        known = {a["title_id"] for a in (self.apps or [])}
        return next(t for t in (f"05{secrets.token_hex(7).upper()}" for _ in range(100)) if t not in known)

    def c_unknown_title(self):
        r = self.http.request("GET", self.api(f"/v1/titles/{self.unknown_id()}"), platform=self.sample_platform())
        self.expect_problem(r, [404], {"not_found"})

    def c_titles(self):
        apps = self.library()
        platform = self.sample_platform()
        ids = list(dict.fromkeys(a["title_id"] for a in apps if a["platform"] == platform))[:TITLES_AT_ONCE - 1]
        if not ids:
            raise Skip(f"no {platform} title in the library")
        unknown = self.unknown_id()
        path = self.api("/v1/titles?ids=" + ",".join(quote(i, safe="") for i in ids + [unknown]))
        _, doc = self.get_json(path, "titles", platform=platform)
        got = {t["title_id"] for t in doc["titles"]}
        expect(all(t["platform"] == platform for t in doc["titles"]), f"titles of another platform than {platform}")
        expect(got <= set(ids), f"titles not asked for: {sorted(got - set(ids))[:5]}")
        expect(unknown in doc["unknown"], f"{unknown} is not listed as unknown")
        expect(not (got & set(doc["unknown"])), "an id both known and unknown")
        expect(got | set(doc["unknown"]) >= set(ids) | {unknown}, "an id neither known nor unknown")
        for t in doc["titles"]:
            self.check_title(t, f"title {t['title_id']}")
        self.titles_read = doc["titles"]
        return f"{len(doc['titles'])} known, {len(doc['unknown'])} unknown, of {len(ids) + 1} ids on {platform}"

    def c_titles_limit(self):
        ids = ",".join(f"05{i:014X}" for i in range(TITLES_AT_ONCE + 1))
        r = self.http.request("GET", self.api(f"/v1/titles?ids={ids}"), platform=self.sample_platform())
        self.expect_problem(r, [400], {"bad_request"})

    def c_title_changes(self):
        _, doc = self.get_json(self.api("/v1/titles/changes"), "title-changes")
        _, later = self.get_json(self.api(f"/v1/titles/changes?since={quote(doc['since'], safe='')}"),
                                 "title-changes", platform=self.sample_platform())
        expect(all(t["platform"] == self.sample_platform() for t in later["titles"]),
               "titles of another platform than the one named")
        return f"{len(later['titles'])} changed, {len(later['removed'])} removed since the token"

    def c_title_bad_since(self):
        r = self.http.request("GET", self.api("/v1/titles/changes?since=lantern-conformance-" + secrets.token_hex(6)))
        self.expect_problem(r, [400, 410], {"bad_request", "gone"})

    # Homebrew (SPEC.md § 8).

    def all_homebrew(self):
        if self.homebrew is None:
            raise Skip("the homebrew listing could not be read (homebrew.pages)")
        return self.homebrew

    def c_homebrew_pages(self):
        _, first = self.get_json(self.api("/v1/homebrew?page_size=1"), "homebrew-page")
        total = first.get("total")
        if total is not None and total > self.args.max_items:
            raise Skip(f"{total} homebrew, above --max-items {self.args.max_items}")
        small = max(1, math.ceil((total or 4) / 4))
        items, pages, total = self.walk(self.api("/v1/homebrew"), small, schema="homebrew-page")
        keys = [(e["platform"], e["id"]) for e in items]
        expect(len(keys) == len(set(keys)), "an entry repeated (or an id twice on a platform)")
        if total is not None:
            expect(len(items) == total, f"{len(items)} entries read in {pages} pages, total says {total}")
        listed = [e["id"] for e in items if "manifest" in e["package"]]
        expect(not listed, f"a listing leaves manifest out (SPEC.md § 8.2): {', '.join(listed[:5])}")
        bad = sorted({e["platform"] for e in items} - set(self.platforms()))
        expect(not bad, f"homebrew of {', '.join(bad)}, which the handshake's platforms do not list")
        for platform in sorted({e["platform"] for e in items}):
            mine, _, _ = self.walk(self.api("/v1/homebrew"), self.limit(), schema="homebrew-page", platform=platform)
            expect({(e["platform"], e["id"]) for e in mine} == {k for k in keys if k[0] == platform},
                   f"Lantern-Platform {platform}: not that platform's homebrew, all of them")
        self.homebrew = items
        return f"{len(items)} entries in {pages} page(s) of {small}"

    def c_homebrew_entries(self):
        entries = self.all_homebrew()
        if not entries:
            raise Skip("no homebrew on this server")
        for e in entries[:self.args.max_entries]:
            path = self.api(f"/v1/homebrew/{quote(e['id'], safe='')}")
            _, doc = self.get_json(path, "homebrew", platform=e["platform"])
            for key in ("id", "platform", "build", "version"):
                expect(doc.get(key) == e.get(key), f"{path}: {key} {doc.get(key)!r}, listed {e.get(key)!r}")
            for key in ("sha256", "size", "manifest_sha256", "file"):
                expect(doc["package"].get(key) == e["package"].get(key), f"{path}: package.{key} differs from the listing")
            if doc["package"]["format"] == "zip":
                expect("manifest" in doc["package"], f"{path}: an archive without its manifest")
            self.entries[(e["platform"], e["id"])] = doc
        return f"{len(self.entries)} entr{'y' if len(self.entries) == 1 else 'ies'}"

    def read_entries(self):
        if not self.entries:
            raise Skip("no homebrew entry could be read (homebrew.entries)")
        return self.entries

    def c_homebrew_manifests(self):
        problems, plans = [], {"free": 0, "consent": 0}
        unchecked = set()
        for (platform, hid), entry in self.read_entries().items():
            for package in [entry["package"]] + list(entry.get("packages") or []):
                problems += self.manifest_problems(platform, hid, {**entry, "package": package}, plans, unchecked)
        expect(not problems, "\n".join(problems[:8]))
        note = f"; roots not checked for {', '.join(sorted(unchecked))} (a draft or no profile)" if unchecked else ""
        return f"{plans['free']} path(s) free to write, {plans['consent']} needing consent{note}"

    def manifest_problems(self, platform, hid, doc, plans, unchecked):
        package = doc["package"]
        manifest = client.manifest_of(package)
        bad = client.manifest_problems(manifest)
        if bad:
            return [f"{platform}/{hid}: " + "; ".join(bad[:3])]
        out = []
        if client.manifest_sha256(manifest) != package["manifest_sha256"]:
            out.append(f"{platform}/{hid}: manifest_sha256 is not the digest of its manifest")
        single = [{"path": package.get("path"), "size": package.get("size"), "sha256": package.get("sha256")}]
        if "path" in package and package.get("manifest", single) != single:
            out.append(f"{platform}/{hid}: a path, and a manifest that is not that one file")
        if platform not in client.ROOTS:
            unchecked.add(platform)
            return out
        try:
            plan = client.install_plan(doc)
        except client.Refused as e:
            return [*out, f"{platform}/{hid}: {e}"]
        plans["free"] += len(plan["free"])
        plans["consent"] += len(plan["consent"])
        return out

    def c_homebrew_kinds(self):
        problems, kinds, systems, unknown, unknown_genres = [], {}, {}, set(), set()
        for e in self.all_homebrew():
            kind = e.get("kind")
            if kind is not None and kind not in client.KINDS:
                problems.append(f"{e['platform']}/{e['id']}: kind {kind!r} is not one of {', '.join(client.KINDS)}")
            kinds[client.kind_of(e)] = kinds.get(client.kind_of(e), 0) + 1
            genres = e.get("genres", [])
            if not (isinstance(genres, list) and all(isinstance(g, str) for g in genres)):
                problems.append(f"{e['platform']}/{e['id']}: genres is not a list of names")
            else:
                unknown_genres.update(g for g in genres if g not in client.GENRES)
            tags = e.get("tags", [])
            if not (isinstance(tags, list) and len(tags) <= client.TAGS_LIMIT and all(
                    isinstance(t, str) and 1 <= len(t.encode()) <= 64 for t in tags)):
                problems.append(f"{e['platform']}/{e['id']}: tags: {client.TAGS_LIMIT} words at most, "
                                "each 64 bytes at most (SPEC.md § 13)")
            if "category" in e:
                problems.append(f"{e['platform']}/{e['id']}: category, gone in 0.3 (shelves come from kind and genres)")
            packages = [e["package"]] + list(e.get("packages") or [])
            if e.get("packages") and (e["platform"] in client.ONE_ARCH or len(e["packages"]) > client.PACKAGES_LIMIT):
                problems.append(f"{e['platform']}/{e['id']}: packages on a platform of one architecture, or above "
                                f"{client.PACKAGES_LIMIT}")
            for p in packages:
                arch = p.get("arch")
                if arch is not None and not client.arch_ok(p, e["platform"]):
                    problems.append(f"{e['platform']}/{e['id']}: arch {arch!r}: "
                                    + ("none on a platform of one architecture" if e["platform"] in client.ONE_ARCH
                                       else "not a list of architectures"))
                elif arch is not None:
                    unknown.update(a for a in arch if a not in client.ARCH_NAMES)
            if any("arch" not in p for p in packages[1:]):
                problems.append(f"{e['platform']}/{e['id']}: a package of packages without its arch")
            if e.get("system_id") is not None:
                other = systems.setdefault((e["platform"], e["system_id"]), e["id"])
                if other != e["id"]:
                    problems.append(f"{e['platform']}: {e['id']} and {other} have the same system_id")
        expect(not problems, "\n".join(problems[:8]))
        if unknown or unknown_genres:
            raise Warn("names this suite does not know (a later version's?); a client never takes such an arch "
                       "for its own (SPEC.md § 8.2) and shows such a genre as other: "
                       + ", ".join(sorted(unknown | unknown_genres)))
        return ", ".join(f"{k}: {n}" for k, n in sorted(kinds.items())) or "no homebrew"

    def c_homebrew_filters(self):
        entries = self.all_homebrew()
        checked = []
        for key, values in (("kind", {client.kind_of(e) for e in entries}),
                            ("genre", {g for e in entries for g in e.get("genres", []) if isinstance(g, str)})):
            for value in sorted(values)[:8]:
                got, _, _ = self.walk(self.api(f"/v1/homebrew?{key}={quote(value, safe='')}"), self.limit(),
                                      schema="homebrew-page")
                want = {(e["platform"], e["id"]) for e in entries
                        if (client.kind_of(e) == value if key == "kind" else value in e.get("genres", []))}
                expect({(e["platform"], e["id"]) for e in got} == want, f"{key}={value}: not those entries")
                checked.append(f"{key}={value}")
            r = self.http.request("GET", self.api(f"/v1/homebrew?{key}=Not%20a%20{key}"))
            self.expect_problem(r, [400], {"bad_request"})
            _, none = self.get_json(self.api(f"/v1/homebrew?{key}=lanternconformance"), "homebrew-page")
            expect(none["items"] == [], f"{key}=lanternconformance: entries, where the server knows no such {key}")
        return ", ".join(checked) or "no kind or genre to filter by"

    def c_homebrew_requires(self):
        problems, conditions, unread = [], 0, set()
        for e in self.all_homebrew():
            problems += [f"{e['platform']}/{e['id']}: {p}" for p in client.requires_problems(e)]
            requires = e.get("requires") if isinstance(e.get("requires"), dict) else {}
            conditions += len(requires.get("min") or {}) + ("gpu" in requires)
            _, unknown = client.offer(e, {})
            unread.update(u.split(" ")[0] for u in unknown if "unknown)" not in u)
        expect(not problems, "\n".join(problems[:8]))
        note = f"; a client warns for {', '.join(sorted(unread))}, which it cannot read" if unread else ""
        return f"{conditions} condition(s){note}"

    def c_homebrew_ports(self):
        ports = {k: d for k, d in self.read_entries().items() if d.get("kind") == "port"}
        if not ports:
            raise Skip("no port on this server")
        problems = []
        for (platform, hid), doc in ports.items():
            problems += [f"{platform}/{hid}: {p}" for p in client.port_problems(doc)]
            listed = next((e for e in self.all_homebrew() if (e["platform"], e["id"]) == (platform, hid)), {})
            if listed.get("port") != doc.get("port"):
                problems.append(f"{platform}/{hid}: port differs between the listing and the entry")
        expect(not problems, "\n".join(problems[:8]))
        files = sum(len(list(client.data_files(d["port"].get("requires_data", [])))) for d in ports.values())
        return f"{len(ports)} port(s), {files} data file(s) the user brings"

    def c_homebrew_packages(self):
        budget, read = self.args.max_download, 0
        arches, entries = 0, 0
        # Entries with a package per architecture first; --max-files counts entries, each read whole.
        for (platform, hid), doc in sorted(self.read_entries().items(), key=lambda kv: not kv[1].get("packages")):
            if entries >= self.args.max_files:
                break
            entries += 1
            for package in [doc["package"]] + list(doc.get("packages") or []):
                if package["size"] > budget:
                    continue
                where = f"{platform}/{hid}" + (f" ({', '.join(package['arch'])})" if package.get("arch") else "")
                data = self.fetch(package["file"], package["size"], package["sha256"], platform)
                budget -= package["size"]
                read += 1
                arches += package is not doc["package"]
                if "manifest" in package:
                    check_archive(where, data, package["manifest"])
                elif package.get("format") == "zip":
                    raise Fail(f"{where}: an archive without its manifest")
        if not read:
            raise Skip(f"every package is above --max-download {self.args.max_download}")
        return f"{read} package(s) of {entries} entr{'y' if entries == 1 else 'ies'}" + (
            f", {arches} of them for another architecture" if arches else "")

    def c_homebrew_signatures(self):
        signed = {k: d for k, d in self.read_entries().items() if "signature" in d}
        if not signed:
            raise Skip("no signed homebrew on this server")
        bad = []
        for (p, i), d in signed.items():
            if not client.verify_signature(d):
                bad.append(f"{p}/{i}")
            for extra in d.get("packages") or []:
                sig = extra.get("signature")
                if not sig or sig.get("public_key") != d["signature"]["public_key"] \
                        or not client.verify_signature({**d, "package": extra, "signature": sig}):
                    bad.append(f"{p}/{i} ({', '.join(extra.get('arch') or ['?'])})")
        expect(not bad, "signatures that do not verify, or by another key (a client refuses them): "
               + ", ".join(bad[:5]))
        return f"{len(signed)} signature(s), keys " + ", ".join(
            sorted({client.key_fingerprint(d["signature"]["public_key"]) for d in signed.values()})[:3])

    def c_homebrew_updates(self):
        entries = [e for e in self.all_homebrew() if e["build"] > 0]
        if not entries:
            raise Skip("no homebrew with a build above 0")
        out = []
        for platform in sorted({e["platform"] for e in entries}):
            mine = [e for e in entries if e["platform"] == platform]
            older, current = mine[0], mine[1:]
            installed = [{"id": older["id"], "build": older["build"] - 1}]
            installed += [{"id": e["id"], "build": e["build"]} for e in current]
            installed.append({"id": "org.example.lantern-conformance-absent", "build": 1})
            body = {"schema": 1, "installed": installed}
            items, _, _ = self.walk(self.api("/v1/homebrew/updates"), self.limit(), "POST", body,
                                    schema="homebrew-page", platform=platform)
            got = [(e["platform"], e["id"]) for e in items]
            expect(got == [(platform, older["id"])],
                   f"{platform}: updates {got}, expected only {older['id']} (installed at build {older['build'] - 1})")
            out.append(f"{platform}: {older['id']}")
        return ", ".join(out)

    def c_homebrew_updates_unnamed(self):
        r = self.http.request("POST", self.api("/v1/homebrew/updates"), body={"schema": 1, "installed": []})
        self.expect_problem(r, [400], {"bad_request"})

    def c_homebrew_unknown(self):
        hid = "org.example.lantern-conformance-" + secrets.token_hex(4)
        r = self.http.request("GET", self.api(f"/v1/homebrew/{hid}"), platform=self.sample_platform())
        self.expect_problem(r, [404], {"not_found"})

    # Cheats (SPEC.md § 10).

    def c_cheats(self):
        _, doc = self.get_json(self.api("/v1/cheats"), "cheats")
        sets = doc["cheats"]
        ids = [c["id"] for c in sets]
        expect(len(ids) == len(set(ids)), "a set id twice")
        bad = sorted({c["platform"] for c in sets} - set(self.platforms()))
        expect(not bad, f"cheats of {', '.join(bad)}, which the handshake's platforms do not list")
        self.cheats = sets
        if not sets:
            return "no cheat set"
        first = sets[0]
        query = f"title_id={quote(first['title_id'], safe='')}"
        if "build_id" in first:
            query += f"&build_id={quote(first['build_id'], safe='')}"
        _, some = self.get_json(self.api(f"/v1/cheats?{query}"), "cheats", platform=first["platform"])
        expected = {c["id"] for c in sets if c["platform"] == first["platform"] and c["title_id"] == first["title_id"]
                    and c.get("build_id") == first.get("build_id")}
        expect({c["id"] for c in some["cheats"]} == expected, f"{query} on {first['platform']}: not those sets")
        for platform in sorted({c["platform"] for c in sets}):
            _, mine = self.get_json(self.api("/v1/cheats"), "cheats", platform=platform)
            expect({c["id"] for c in mine["cheats"]} == {c["id"] for c in sets if c["platform"] == platform},
                   f"Lantern-Platform {platform}: not that platform's sets")
        self.expect_problem(self.http.request("GET", self.api("/v1/cheats?build_id=not%20a%20build")), [400],
                            {"bad_request"})
        return f"{len(sets)} set(s), {len(expected)} for {first['title_id']}"

    def c_cheat_text(self):
        if self.cheats is None:
            raise Skip("the sets could not be read (cheats.sets)")
        if not self.cheats:
            raise Skip("no cheat set")
        picked = self.cheats[:self.args.max_files]
        for c in picked:
            expect(c["size"] <= CHEAT_LIMIT, f"set {c['id']}: {c['size']} bytes, above 1 MiB")
            self.fetch(self.api(f"/v1/cheats/{quote(c['id'], safe='')}"), c["size"], c["sha256"], c["platform"])
        return f"{len(picked)} set(s)"

    def c_cheat_unknown(self):
        r = self.http.request("GET", self.api("/v1/cheats/cs_lantern-conformance-" + secrets.token_hex(6)))
        self.expect_problem(r, [404], {"not_found"})

    def c_cheat_write(self):
        if "cheats.write" in self.scopes():
            raise Skip("the token holds cheats.write: cheats.write-cycle writes a set instead")
        body = {"schema": 1, "platform": "switch", "title_id": "0100ABCD00010000", "build_id": "0123456789ABCDEF",
                "source": "Lantern conformance", "text": "[Nothing]\n"}
        r = self.http.request("POST", self.api("/v1/cheats"), body=body)
        self.expect_problem(r, [401, 403, 405])
        return f"{r.status}"

    def c_cheat_write_cycle(self):
        if "cheats.write" not in self.scopes():
            raise Skip("the token lacks cheats.write")
        # A platform with cheats: one of a set the server has, else one it serves (Annex A).
        served = [c["platform"] for c in self.cheats or []] + self.platforms()
        platform = next((p for p in served if p not in ("android", "linux")), None)
        if platform is None:
            raise Skip("no platform with cheats on this server (Annex A)")
        platform, tid = self.own_title(platform)
        text = "[Lantern conformance]\n04000000 00000000 00000000\n"
        body = {"schema": 1, "platform": platform, "title_id": tid, "build_id": "0123456789ABCDEF",
                "source": "Lantern conformance", "note": "Lantern conformance", "text": text}
        if platform in NO_BUILD:        # a set per game, without a build (Annex A.2, A.3)
            del body["build_id"]
        r = self.http.request("POST", self.api("/v1/cheats"), body=body, platform=platform)
        expect(r.status == 201, f"{r}, expected 201" + problem_detail(r))
        doc = r.json()
        self.validate(doc, "cheat", str(r))
        sid = doc["id"]
        path = self.api(f"/v1/cheats/{quote(sid, safe='')}")
        try:
            for key in ("platform", "title_id", "build_id", "source"):
                expect(doc.get(key) == body.get(key), f"{r}: {key} {doc.get(key)!r}, sent {body.get(key)!r}")
            expect(doc["size"] == len(text.encode()) and doc["sha256"] == hashlib.sha256(text.encode()).hexdigest(),
                   f"{r}: size and sha256 are not those of the text sent")
            query = f"title_id={quote(tid, safe='')}" + ("&build_id=0123456789ABCDEF" if "build_id" in body else "")
            _, listed = self.get_json(self.api(f"/v1/cheats?{query}"), "cheats", platform=platform)
            expect([c["id"] for c in listed["cheats"]] == [sid], f"{query}: not the set posted, alone")
            self.fetch(path, doc["size"], doc["sha256"], platform)
            again = self.http.request("POST", self.api("/v1/cheats"), body=body, platform=platform)
            expect(again.status in (200, 201, 409), f"{again}: the same set posted twice" + problem_detail(again))
            if again.status in (200, 201) and again.json().get("id") not in (None, sid):
                self.http.request("DELETE", self.api(f"/v1/cheats/{quote(again.json()['id'], safe='')}"),
                                  platform=platform)
            new = text + "[Lantern conformance, again]\n04000000 00000004 00000001\n"
            r = self.http.request("PUT", path, body={**body, "text": new}, platform=platform)
            expect(r.status == 204, f"{r}, expected 204" + problem_detail(r))
            _, listed = self.get_json(self.api(f"/v1/cheats?{query}"), "cheats", platform=platform)
            now = next((c for c in listed["cheats"] if c["id"] == sid), None)
            expect(now is not None and now["sha256"] == hashlib.sha256(new.encode()).hexdigest(),
                   "after PUT, the set is not listed with the new text's sha256")
            self.fetch(path, now["size"], now["sha256"], platform)
        finally:
            r = self.http.request("DELETE", path, platform=platform)
        expect(r.status == 204, f"{r}, expected 204" + problem_detail(r))
        gone = self.http.request("GET", path, platform=platform, raw=True)
        expect(gone.status in (404, 410), f"{gone} after DELETE, expected 404")
        return f"set {sid} for {platform}/{tid} posted, replaced and deleted"

    # Requests (SPEC.md § 11).

    def c_requests(self):
        if "requests" not in self.scopes():
            raise Blind("the token lacks the scope requests")
        _, doc = self.get_json(self.api("/v1/requests"), "requests")
        platform = self.sample_platform()
        _, mine = self.get_json(self.api("/v1/requests"), "requests", platform=platform)
        expect(all(q["platform"] == platform for q in mine["requests"]), f"Lantern-Platform {platform}: "
               "requests of another platform")
        return f"{len(doc['requests'])} request(s), {len(mine['requests'])} for {platform}"

    def c_request_create(self):
        if "requests" not in self.scopes():
            raise Blind("the token lacks the scope requests")
        platform, tid = self.save_title()
        body = {"schema": 1, "platform": platform, "title_id": tid}
        r = self.http.request("POST", self.api("/v1/requests"), body=body, platform=platform)
        expect(r.status in (200, 201), f"{r}, expected 201" + problem_detail(r))
        first = r.json()
        self.validate(first, "request", str(r))
        expect((first["platform"], first["title_id"], first["status"]) == (platform, tid, "open"),
               f"{r}: not an open request for {platform}/{tid}")
        self.request_made = (platform, first["id"])
        r = self.http.request("POST", self.api("/v1/requests"), body=body, platform=platform)
        expect(r.status == 200, f"{r}: the same title asked again, expected 200 with the open request"
               + problem_detail(r))
        self.validate(r.json(), "request", str(r))
        expect(r.json()["id"] == first["id"], f"{r}: another request, {r.json()['id']}, not {first['id']}")
        _, listed = self.get_json(self.api("/v1/requests"), "requests", platform=platform)
        expect(first["id"] in {q["id"] for q in listed["requests"]}, "the request is not listed")
        return f"request {first['id']} for {platform}/{tid}"

    # Save backups (SPEC.md § 9), with a token that holds `saves`.

    def c_save_limits(self):
        limits = self.hello.get("limits") or {}
        for key in ("save_body", "save_size", "saves_kept_per_title"):
            expect(isinstance(limits.get(key), int) and not isinstance(limits[key], bool) and limits[key] >= 1,
                   f"limits.{key} {limits.get(key)!r}: a server with saves announces it")
        expect(limits["save_body"] <= limits["save_size"], "save_body is above save_size")
        return f"save_body {limits['save_body']}, save_size {limits['save_size']}, " \
               f"kept {limits['saves_kept_per_title']} per title"

    def c_saves_list(self):
        _, doc = self.get_json(self.api("/v1/saves"), "saves")
        last = {}
        for s in doc["saves"]:
            key = (s["platform"], s["title_id"])
            if key in last:
                expect(s["created"] <= last[key], f"{key[0]}/{key[1]}: not newest first")
            last[key] = s["created"]
        return f"{len(doc['saves'])} backup(s)"

    def save_title(self):
        """(platform, title_id) for the suite's own backups: a title id of the
        platform's form that is none of the library's, so that no backup of the
        user's is dropped for it (limits.saves_kept_per_title)."""
        if not getattr(self, "_save_title", None):
            self._save_title = self.own_title(self.sample_platform())
        return self._save_title

    def own_title(self, platform):
        """(platform, title_id): a title id of the platform's form that is none of the library's."""
        known = {a["title_id"] for a in (self.apps or [])}
        while True:
            if platform in ("switch",):
                tid = f"05{secrets.token_hex(5).upper()}0000"
            elif platform == "3ds":
                tid = f"00040000F{secrets.token_hex(3).upper()}0"
            elif platform in ("vita", "ps4"):
                tid = "XLCF" + "".join(secrets.choice("0123456789") for _ in range(5))
            elif platform == "android":
                tid = "org.example.lanternconformance" + secrets.token_hex(3)
            else:
                tid = "lantern-conformance-" + secrets.token_hex(4)
            if tid not in known:
                return platform, tid

    def save_archive(self, size=3000):
        """A small zip, as a save archive (fictional bytes)."""
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
            z.writestr("lantern-conformance/save.dat", secrets.token_bytes(size))
        return out.getvalue()

    def open_upload(self, data, sha256=None, size=None):
        platform, tid = self.save_title()
        body = {"schema": 1, "size": len(data) if size is None else size,
                "sha256": sha256 or hashlib.sha256(data).hexdigest(), "kind": "account", "game_version_code": 0,
                "profile": "Lea", "slot": "lantern-conformance", "note": "Lantern conformance"}
        return self.http.request("POST", self.api(f"/v1/saves/{quote(tid, safe='')}/uploads"), body=body,
                                 platform=platform)

    def patch(self, upload, offset, chunk):
        return self.http.request("PATCH", self.file_path(upload), body=chunk, headers={
            "Upload-Offset": str(offset), "Content-Type": "application/offset+octet-stream"})

    def head_offset(self, upload):
        r = self.http.request("HEAD", self.file_path(upload), raw=True)
        expect(r.status in (200, 204), f"{r}, expected 204" + problem_detail(r))
        offset = r.header("Upload-Offset") or ""
        expect(offset.isdigit(), f"{r}: Upload-Offset {offset or 'none'}")
        return int(offset), r

    def c_save_unnamed(self):
        _, tid = self.save_title()
        data = self.save_archive(10)
        r = self.http.request("POST", self.api(f"/v1/saves/{quote(tid, safe='')}/uploads"),
                              body={"schema": 1, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        self.expect_problem(r, [400], {"bad_request"})
        digest = base64.b64encode(hashlib.sha256(data).digest()).decode()
        r = self.http.request("POST", self.api(f"/v1/saves/{quote(tid, safe='')}"), body=data, headers={
            "Content-Type": "application/zip", "Content-Digest": f"sha-256=:{digest}:"})
        self.expect_problem(r, [400], {"bad_request"})
        if r.status < 300:      # the server kept it after all: the suite deletes it
            self.created.append((None, tid, r.json().get("save_id")))

    def c_save_upload(self):
        data = self.save_archive()
        r = self.open_upload(data)
        expect(r.status == 201, f"{r}, expected 201" + problem_detail(r))
        doc = r.json()
        self.validate(doc, "upload", str(r))
        upload = doc["upload"]
        self.uploads.append(upload)
        expect(doc["offset"] == 0, f"offset {doc['offset']} for a new upload")
        chunk = min(doc["chunk_size"], math.ceil(len(data) / 2))
        offset, sent = 0, 0
        while offset < len(data):
            part = data[offset:offset + chunk]
            r = self.patch(upload, offset, part)
            sent += 1
            if offset + len(part) < len(data):
                expect(r.status == 204, f"{r} for a chunk, expected 204" + problem_detail(r))
                expect(r.header("Upload-Offset") == str(offset + len(part)),
                       f"{r}: Upload-Offset {r.header('Upload-Offset')}, expected {offset + len(part)}")
                at, head = self.head_offset(upload)
                expect(at == offset + len(part), f"{head}: Upload-Offset {at}, expected {offset + len(part)}")
                expect(head.header("Upload-Length") == str(len(data)),
                       f"{head}: Upload-Length {head.header('Upload-Length')}, expected {len(data)}")
                if sent == 1:
                    wrong = self.patch(upload, 0, part)
                    self.expect_problem(wrong, [409], {"conflict"})
                    expect(wrong.header("Upload-Offset") == str(at),
                           f"{wrong}: Upload-Offset {wrong.header('Upload-Offset')}, expected {at}")
            else:
                expect(r.status == 201, f"{r} for the last chunk, expected 201" + problem_detail(r))
                entry = r.json()
                self.validate(entry, "save", str(r))
                self.uploads.remove(upload)
                self.created.append((entry["platform"], entry["title_id"], entry["save_id"]))
                expect(entry["sha256"] == hashlib.sha256(data).hexdigest() and entry["size"] == len(data),
                       f"{r}: the entry's sha256 and size are not the archive's")
                expect((entry["platform"], entry["title_id"]) == self.save_title(), f"{r}: another platform or title")
                self.upload = {**entry, "data": data}
            offset += len(part)
        expect(sent >= 2, f"the archive went in {sent} chunk(s)")
        return f"{len(data)} bytes in {sent} chunks of at most {chunk}"

    def c_save_read(self):
        if not self.upload:
            raise Skip("no backup was uploaded (saves.upload)")
        u = self.upload
        _, doc = self.get_json(self.api(f"/v1/saves?title_id={quote(u['title_id'], safe='')}"), "saves",
                               platform=u["platform"])
        expect(any(s["save_id"] == u["save_id"] for s in doc["saves"]), "the new backup is not listed")
        self.fetch(self.api(f"/v1/saves/{quote(u['title_id'], safe='')}/{quote(u['save_id'], safe='')}"),
                   len(u["data"]), hashlib.sha256(u["data"]).hexdigest(), u["platform"])
        return f"{u['save_id']}, {len(u['data'])} bytes"

    def c_save_upload_digest(self):
        data = self.save_archive(100)
        r = self.open_upload(data, sha256=hashlib.sha256(data + b"!").hexdigest())
        expect(r.status == 201, f"{r}, expected 201" + problem_detail(r))
        upload = r.json()["upload"]
        self.uploads.append(upload)
        r = self.patch(upload, 0, data)
        self.expect_problem(r, [422], {"digest_mismatch"})
        self.uploads.remove(upload)
        head = self.http.request("HEAD", self.file_path(upload), raw=True)
        expect(head.status in (404, 410), f"{head}: the upload is still there after 422, expected 404 or 410")

    def c_save_too_large(self):
        size = (self.hello.get("limits") or {}).get("save_size")
        if not isinstance(size, int):
            raise Skip("no limits.save_size")
        r = self.open_upload(b"", sha256="0" * 64, size=size + 1)
        self.expect_problem(r, [413], {"too_large"})
        if r.status == 201:
            self.uploads.append(r.json()["upload"])

    def c_save_single(self):
        platform, tid = self.save_title()
        limit = (self.hello.get("limits") or {}).get("save_body", 0)
        data = self.save_archive(200)
        if len(data) > limit:
            raise Skip(f"limits.save_body {limit} is below a small archive")
        path = self.api(f"/v1/saves/{quote(tid, safe='')}")
        headers = {"Content-Type": "application/zip", "Lantern-Save-Kind": "account", "Lantern-Game-Version": "0",
                   "Lantern-Profile": quote("Léa"), "Lantern-Note": quote("Lantern conformance")}
        auth = "Bearer " + self.args.token if self.args.token else None
        if self.seed is None:
            r = self.http.request("POST", path, body=data, headers=headers, platform=platform)
            self.expect_problem(r, [400], {"bad_request"})
            wrong = base64.b64encode(hashlib.sha256(data + b"!").digest()).decode()
            r2 = self.http.request("POST", path, body=data, headers={**headers, "Content-Digest": f"sha-256=:{wrong}:"},
                                   platform=platform)
        else:
            # A signed request with a body carries its Content-Digest (SPEC.md § 5.4): without it, the signature
            # is refused; with another body's, signed, the body is.
            signed = self.http.signed(self.seed, "POST", path, auth, data)
            r = self.http.request("POST", path, body=data, platform=platform, sign=False,
                                  headers={**headers, **{k: v for k, v in signed.items() if k != "Content-Digest"}})
            self.expect_problem(r, [400, 401], {"bad_request", "signature_invalid"})
            r2 = self.http.request("POST", path, body=data, platform=platform, sign=False,
                                   headers={**headers, **self.http.signed(self.seed, "POST", path, auth, data + b"!")})
        self.keep(r)
        self.expect_problem(r2, [422], {"digest_mismatch"})
        self.keep(r2)
        right = base64.b64encode(hashlib.sha256(data).digest()).decode()
        r = self.http.request("POST", path, body=data, headers={**headers, "Content-Digest": f"sha-256=:{right}:"},
                              platform=platform)
        expect(r.status == 201, f"{r}, expected 201" + problem_detail(r))
        self.keep(r)
        entry = r.json()
        self.validate(entry, "save", str(r))
        expect(entry["sha256"] == hashlib.sha256(data).hexdigest(), f"{r}: another sha256")
        expect(entry.get("profile") == "Léa", f"{r}: profile {entry.get('profile')!r}, sent Léa (percent-encoded)")
        return f"{entry['save_id']}, {len(data)} bytes"

    def keep(self, r):
        if r.status == 201 and r.is_json and isinstance(r.json(), dict) and r.json().get("save_id"):
            doc = r.json()
            self.created.append((doc.get("platform"), doc.get("title_id"), doc["save_id"]))

    def c_save_cleanup(self):
        problems = []
        for upload in list(self.uploads):
            r = self.http.request("DELETE", self.file_path(upload))
            if r.status not in (204, 404, 410):
                problems.append(f"{r}, expected 204")
        self.uploads = []
        for platform, tid, sid in self.created:
            path = self.api(f"/v1/saves/{quote(tid, safe='')}/{quote(sid, safe='')}")
            r = self.http.request("DELETE", path, platform=platform)
            if r.status != 204:
                problems.append(f"{r}, expected 204" + problem_detail(r))
                continue
            again = self.http.request("GET", path, platform=platform, raw=True)
            if again.status != 404:
                problems.append(f"{again} after DELETE, expected 404")
        done = len(self.created)
        self.created = []
        expect(not problems, "\n".join(problems[:8]))
        if not done:
            raise Skip("nothing to delete")
        return f"{done} backup(s) deleted"

    def c_unknown_route(self):
        r = self.http.request("GET", self.api("/v1/lantern-conformance-no-such-route"))
        self.expect_problem(r, [404], {"not_found"})

    # LAN discovery (SPEC.md § 4.1), when asked for.

    def c_discovery(self):
        if not self.args.discover:
            raise Skip("no --discover address given")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(3)
        try:
            sock.sendto(json.dumps({"schema": 1, "lantern": "discover"}).encode(),
                        (self.args.discover, self.args.discover_port))
            data, peer = sock.recvfrom(65536)
        except TimeoutError:
            raise Fail(f"no reply from {self.args.discover}:{self.args.discover_port} in 3 s") from None
        finally:
            sock.close()
        expect(len(data) <= DATAGRAM_LIMIT, f"a reply of {len(data)} bytes, above {DATAGRAM_LIMIT}")
        try:
            doc = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise Fail(f"the reply is not JSON: {e}") from None
        expect(isinstance(doc, dict) and doc.get("schema") == 1 and doc.get("lantern") == "server",
               f"not a Lantern reply: {data[:200]!r}")
        self.validate(doc, "discovery", f"reply from {peer[0]}")
        expect(doc["uid"] == self.hello["uid"], "uid differs from the handshake's")
        expect(doc["base"] == self.base, f"base {doc['base']}, the handshake says {self.base}")
        expect(1 in doc["versions"], f"versions {doc['versions']}")
        port = self.origin.port or (443 if self.origin.scheme == "https" else 80)
        expect(doc["port"] == port, f"port {doc['port']}, the server answers on {port}")
        return f"{doc['name']} from {peer[0]}, port {doc['port']}"

    # Signed requests and device keys (SPEC.md § 5.4).

    def c_auth(self):
        mine, anon = self.features(self.hello), self.features(self.hello_anon)
        expect(mine["signatures"] == anon["signatures"],
               f"signatures is {anon['signatures']} without a token, {mine['signatures']} with one")
        if anon["pairing"]:
            expect(anon["signatures"] >= 1, "a server that pairs, and so issues tokens, offers signatures (§ 5.4)")
        auth = self.hello.get("auth")
        if mine["signatures"]:
            expect(isinstance(auth, dict) and isinstance(auth.get("bearer_only"), bool)
                   and isinstance(auth.get("skew"), int) and 60 <= auth["skew"] <= 900,
                   f"auth {auth!r}: bearer_only and a skew of 60 to 900 seconds")
        if self.args.token is not None:
            expect(self.hello["account"].get("bound") == (self.seed is not None) or self.seed is None,
                   "the token was used with its key, but account.bound is not true")
        return f"signatures {mine['signatures']}" + (f", auth {auth}" if auth else "")

    def bound(self):
        """The suite's own token, bound to the key given; Blind without them, Skip on a server of no tokens."""
        if not self.features(self.hello_anon)["signatures"]:
            raise Skip("the server issues no tokens (no pairing): nothing to sign")
        if self.args.token is None or self.seed is None or not self.hello["account"].get("bound"):
            raise Blind("needs a token bound to a device key, and the key (--token, --key)")
        return self.api("/v1/apps?page_size=1") if self.features(self.hello)["library"] else self.api("/v1/")

    def expect_signature_code(self, r, code):
        self.expect_problem(r, [401], {code})
        expect((r.header("WWW-Authenticate") or "").lower().startswith("bearer"), f"{r}: no Bearer challenge")

    def c_sig_unsigned(self):
        path = self.bound()
        r = self.http.request("GET", path, sign=False)
        self.expect_signature_code(r, "signature_required")
        self.unsigned = r

    def c_sig_invalid(self):
        path = self.bound()
        other = client.ed25519_keypair()[0]
        self.expect_signature_code(self.http.request("GET", path, seed=other), "signature_invalid")
        headers = self.http.signed(self.seed, "GET", path + "&lantern=conformance" if "?" in path else path + "?x=1",
                                   "Bearer " + self.args.token, None)
        self.expect_signature_code(self.http.request("GET", path, headers=headers, sign=False), "signature_invalid")
        params = headers["Signature-Input"].split(";", 1)[1]
        swapped = {**self.http.signed(self.seed, "GET", path, "Bearer " + self.args.token, None),
                   "Signature-Input": 'lantern=("@target-uri" "@method" "authorization");' + params}
        self.expect_signature_code(self.http.request("GET", path, headers=swapped, sign=False), "signature_invalid")
        return "another key, another target, components in another order"

    def c_sig_stale(self):
        path = self.bound()
        skew = (self.hello.get("auth") or {}).get("skew", 300)
        r = self.http.request("GET", path, created=int(time.time() + self.http.offset) - skew - 120)
        self.expect_signature_code(r, "signature_expired")
        r = self.http.request("GET", path, created=int(time.time() + self.http.offset) + skew + 120)
        self.expect_signature_code(r, "signature_expired")
        return f"created {skew + 120} s before and after the server's clock"

    def c_sig_replayed(self):
        path = self.bound()
        nonce = client.new_nonce()
        first = self.http.request("GET", path, nonce=nonce)
        expect(first.status == 200, f"{first}, expected 200" + problem_detail(first))
        self.expect_signature_code(self.http.request("GET", path, nonce=nonce), "signature_replayed")

    def c_sig_digest(self):
        self.bound()
        if not self.features(self.hello)["library"]:
            raise Skip("no route with a body to send (library)")
        path = self.api("/v1/apps/missing?page_size=1")
        body = json.dumps({"schema": 1, "installed": [], "want": ["base"]}).encode()
        headers = self.http.signed(self.seed, "POST", path, "Bearer " + self.args.token, body + b" ")
        r = self.http.request("POST", path, body=body, headers={**headers, "Content-Type": "application/json"},
                              platform=self.sample_platform(), sign=False)
        self.expect_problem(r, [422], {"digest_mismatch"})

    def c_sig_accept(self):
        r = getattr(self, "unsigned", None)
        if r is None:
            raise Skip("no unsigned request was refused (signatures.unsigned)")
        if not (r.header("Accept-Signature") or "").startswith("lantern="):
            raise Warn(f"{r}: no Accept-Signature for the label lantern")
        return r.header("Accept-Signature")

    def c_pairing_key(self):
        # Not a key; then the identity and a point of order 8, keys of small order (SPEC.md § 5.4).
        for public in ("AAAA", base64.b64encode(bytes([1]) + bytes(31)).decode(),
                       base64.b64encode(bytes.fromhex("26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05")).decode()):
            bad = {**PAIRING, "key": {"alg": "ed25519", "public_key": public}}
            self.expect_problem(self.http.request("POST", self.api("/v1/pairing"), auth="none", body=bad), [400],
                                {"bad_request"})
        seed, public = client.ed25519_keypair()
        r = self.http.request("POST", self.api("/v1/pairing"), auth="none",
                              body={**PAIRING, "key": {"alg": "ed25519", "public_key": base64.b64encode(public).decode()}})
        expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
        self.validate(r.json(), "pairing-code", str(r))
        poll = self.file_path(r.json()["poll"])
        unsigned = self.http.request("GET", poll, auth="none")
        self.expect_problem(unsigned, [401], {"signature_required", "signature_invalid"})
        other = self.http.request("GET", poll, auth="none", seed=client.ed25519_keypair()[0])
        self.expect_problem(other, [401], {"signature_invalid"})
        signed = self.http.request("GET", poll, auth="none", seed=seed)
        expect(signed.status in (202, 429), f"{signed}, expected 202 (or 429 after the refused polls)"
               + problem_detail(signed))
        return f"unsigned poll {unsigned.status} {unsigned.json().get('code')}, signed {signed.status}"

    def c_bearer_only(self):
        auth = self.hello.get("auth") or {}
        if auth.get("bearer_only", True):
            raise Skip("auth.bearer_only: the server still issues tokens without a key, as SPEC.md § 5.4 allows")
        r = self.http.request("POST", self.api("/v1/pairing"), auth="none", body=PAIRING)
        self.expect_problem(r, [400], {"key_required"})

    def c_verify_complete(self):
        if not self.pair:
            raise Skip("no pairing code (pairing.code)")
        verify, complete = urlsplit(self.pair["verify"]), urlsplit(self.pair.get("verify_complete") or "")
        expect(complete.netloc == verify.netloc and complete.scheme == verify.scheme,
               f"verify_complete {self.pair.get('verify_complete')!r} is not on verify's origin")
        typed = re.sub(r"[^0-9A-Z]", "", self.pair["code"].upper())
        expect(typed in re.sub(r"[^0-9A-Z]", "", unquote(complete.query).upper()),
               f"verify_complete {self.pair['verify_complete']}: the code is not in its query")
        if complete.netloc == self.origin.netloc:
            r = self.http.request("GET", complete.path + "?" + complete.query, auth="none", raw=True)
            expect(r.status == 200, f"{r}: the page verify_complete opens, expected 200")
        return "opened; pairing.waiting then checks that it approved nothing (202)"

    def c_verify_page(self):
        if self.origin.scheme != "https":
            raise Skip("plain HTTP: no key to compare")
        if not self.http.peer_spki:
            raise Skip("the server's certificate could not be read")
        verify = urlsplit(self.pair["verify"]) if self.pair else None
        if not verify or verify.netloc != self.origin.netloc:
            raise Skip("verify is not on the server's origin")
        r = self.http.request("GET", verify.path or "/", auth="none", raw=True)
        expect(r.status == 200, f"{r}, expected the approval page")
        short = self.http.peer_spki[:16].upper()
        page = re.sub(r"[^0-9A-F]", "", r.body.decode("utf-8", "replace").upper())
        expect(short in page, f"{r}: the page does not show {' '.join(short[i:i + 4] for i in range(0, 16, 4))}, "
                              "the short fingerprint of the key the suite sees")
        return " ".join(short[i:i + 4] for i in range(0, 16, 4))

    # Languages, versions, limits, compression and the cold start.

    def c_language_handshake(self):
        if "motd" not in self.hello:
            raise Skip("no motd")
        expect(isinstance(self.hello.get("language"), str), "a motd without its language (§ 2.2)")
        return f"{self.hello['language']}"

    def c_language_problem(self):
        r = self.http.request("GET", self.api("/v1/lantern-conformance-no-such-route"),
                              headers={"Accept-Language": "fr-CA, fr;q=0.9, en;q=0.5"})
        expect(r.status == 404 and r.is_json, f"{r}, expected a 404 problem")
        doc = r.json()
        expect(isinstance(doc.get("language"), str), f"{r}: the problem says no language")
        notes = []
        if not r.header("Content-Language"):
            notes.append("no Content-Language")
        if doc["language"].split("-")[0] not in ("fr", "en"):
            notes.append(f"language {doc['language']}, neither one asked for nor English")
        if notes:
            raise Warn(f"{r}: " + "; ".join(notes))
        return f"asked fr-CA, fr, en: {doc['language']}"

    def c_accept_schema(self):
        written = self.features(self.hello)["library"]
        if not written:
            raise Skip("no library to ask for")
        r = self.http.request("GET", self.api("/v1/apps?page_size=1"), headers={"Accept-Schema": f"library={written}"})
        if r.status != 200 or r.json().get("schema") != written:
            raise Warn(f"{r} with Accept-Schema library={written}, expected 200 and schema {written}")

    def c_depth(self):
        nested = "[" * 40 + "]" * 40
        body = ('{"schema":1,"installed":[],"want":["base"],"x-lantern-conformance":' + nested + "}").encode()
        r = self.http.request("POST", self.api("/v1/apps/missing"), body=body,
                              headers={"Content-Type": "application/json"}, platform=self.sample_platform())
        self.expect_problem(r, [400, 413], {"bad_request", "too_large"})

    def c_compression_json(self):
        r = self.http.request("GET", self.api("/v1/apps?page_size=50"), headers={"Accept-Encoding": "zstd, br, gzip"})
        expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
        self.compressed = r
        if r.encoding not in ("zstd", "br", "gzip"):
            raise Warn(f"{r}: sent as it is, without zstd, br or gzip")
        if r.encoding == "gzip":
            raise Warn(f"{r}: gzip, but neither zstd nor br (§ 2.1)")
        return f"{r.encoding}: {r.wire} bytes for {len(r.body)}"

    def c_compression_etag(self):
        r = getattr(self, "compressed", None)
        if r is None or r.encoding not in ("zstd", "br", "gzip"):
            raise Skip("the server compressed nothing")
        expect("accept-encoding" in (r.header("Vary") or "").lower() or "*" in (r.header("Vary") or ""),
               f"{r}: compressed, without Vary: Accept-Encoding")
        plain = self.http.request("GET", self.api("/v1/apps?page_size=50"))
        if r.header("ETag") and plain.header("ETag"):
            expect(r.header("ETag") != plain.header("ETag"), f"{r}: the same ETag compressed ({r.encoding}) and not")
        return f"Vary {r.header('Vary')}"

    def c_compression_files(self):
        apps = sorted(self.apps or ([self.sample] if self.sample else []), key=lambda a: a["size"])
        if not apps or apps[0]["size"] > self.args.max_download:
            raise Skip("no file to read within --max-download")
        app = apps[0]
        r = self.http.request("GET", self.file_path(app["file"]), headers={"Accept-Encoding": "zstd, br, gzip"},
                              limit=app["size"], raw=True)
        expect(r.status == 200, f"{r}, expected 200")
        expect(r.encoding in ("", "identity"), f"{r}: a file sent with Content-Encoding {r.encoding}")
        expect(hashlib.sha256(r.body).hexdigest() == app["sha256"], f"{r}: not the bytes of its sha256")

    def c_budget(self):
        enc = {"Accept-Encoding": "gzip"}
        platform = self.sample_platform()
        hello = self.http.request("GET", self.api("/v1/"), headers=enc, platform=platform)
        page = self.http.request("GET", self.api("/v1/apps?page_size=50"), headers=enc, platform=platform)
        expect(hello.status == 200 and page.status == 200, f"{hello}, {page}")
        used = [hello, page]
        ids = list(dict.fromkeys(a["title_id"] for a in page.json()["items"]))[:TITLES_AT_ONCE]
        if ids and self.features(self.hello)["titles"]:
            used.append(self.http.request("GET", self.api("/v1/titles?ids=" + ",".join(quote(i, safe="") for i in ids)),
                                          headers=enc, platform=platform))
        total = sum(r.wire for r in used)
        detail = f"{len(used)} requests, {total} bytes as they travelled ({', '.join(str(r.wire) for r in used)})"
        if total > BUDGET:
            raise Warn(detail + f": above {BUDGET} (SPEC.md Annex B.8)")
        return detail

    # Requests withdrawn (SPEC.md § 11).

    def c_request_delete(self):
        made = getattr(self, "request_made", None)
        if made is None:
            raise Skip("no request was made (requests.create)")
        platform, rid = made
        path = self.api(f"/v1/requests/{quote(rid, safe='')}")
        r = self.http.request("DELETE", path, platform=platform)
        expect(r.status == 204, f"{r}, expected 204" + problem_detail(r))
        self.request_made = None
        _, listed = self.get_json(self.api("/v1/requests"), "requests", platform=platform)
        expect(rid not in {q["id"] for q in listed["requests"]}, "still listed after DELETE")
        self.expect_problem(self.http.request("DELETE", path, platform=platform), [404], {"not_found"})
        self.expect_problem(self.http.request("DELETE", self.api("/v1/requests/r_lantern-conformance-"
                                                                 + secrets.token_hex(6))), [404], {"not_found"})
        return f"{rid} withdrawn"

    # Administration, invitations and rating caps (SPEC.md § 5.5–5.7).

    def admin_walk(self, path, schema):
        items, cursor = [], None
        for _ in range(1000):
            url = path + ("&" if "?" in path else "?") + "page_size=100" + (
                f"&cursor={quote(cursor, safe='')}" if cursor else "")
            _, doc = self.get_json(url, schema)
            items += doc["items"]
            cursor = doc["next"]
            if cursor is None:
                return items
        raise Fail(f"{path}: still a next page after 1000")

    def c_admin_requests(self):
        """SPEC.md § 11's states, by the administration API: a request declined with a reason, final; one done."""
        if not self.features(self.hello)["requests"]:
            raise Skip("the server does not offer requests to this caller")
        if not {"admin", "requests"} <= self.scopes():
            raise Blind("needs the scopes admin and requests")
        platform, tid = self.own_title(self.sample_platform())
        body = {"schema": 1, "platform": platform, "title_id": tid}
        since = self.events_token() if self.features(self.hello)["events"] else None
        made = []
        try:
            r = self.http.request("POST", self.api("/v1/requests"), body=body, platform=platform)
            expect(r.status == 201, f"{r}, expected 201" + problem_detail(r))
            rid = r.json()["id"]
            made.append(rid)
            listed = self.admin_walk(self.api("/v1/admin/requests?status=open"), "admin-requests")
            mine = next((q for q in listed if q["id"] == rid), None)
            expect(mine is not None and mine["user"] == self.hello["account"].get("name") and mine["status"] == "open",
                   f"request {rid} is not listed open, with its user, by GET /v1/admin/requests?status=open")
            expect(all(q["status"] == "open" for q in listed), "?status=open lists requests of another status")
            path = self.api(f"/v1/admin/requests/{quote(rid, safe='')}")
            self.expect_problem(self.http.request("POST", path, body={"schema": 1, "decision": "maybe"}), [400],
                                {"bad_request"})
            reason = "Lantern conformance: declined on purpose."
            r = self.http.request("POST", path, body={"schema": 1, "decision": "decline", "reason": reason})
            expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
            self.validate(r.json(), "request", str(r))
            expect((r.json()["status"], r.json().get("reason")) == ("declined", reason),
                   f"{r}: status {r.json()['status']}, reason {r.json().get('reason')!r}")
            _, own = self.get_json(self.api("/v1/requests"), "requests", platform=platform)
            seen = next((q for q in own["requests"] if q["id"] == rid), {})
            expect((seen.get("status"), seen.get("reason")) == ("declined", reason),
                   f"the requester reads {seen.get('status')!r} and reason {seen.get('reason')!r}, not declined "
                   "and the admin's reason")
            self.expect_problem(self.http.request("POST", path, body={"schema": 1, "decision": "done"}), [409],
                                {"conflict"})
            r = self.http.request("POST", self.api("/v1/requests"), body=body, platform=platform)
            expect(r.status == 201 and r.json()["id"] != rid,
                   f"{r}: the same title asked again after a decline, expected 201 and a new request" + problem_detail(r))
            again = r.json()["id"]
            made.append(again)
            r = self.http.request("POST", self.api(f"/v1/admin/requests/{quote(again, safe='')}"),
                                  body={"schema": 1, "decision": "done"})
            expect(r.status == 200 and r.json()["status"] == "done" and "reason" not in r.json(),
                   f"{r}: marked done, expected 200 done without a reason" + problem_detail(r))
            self.expect_problem(self.http.request("POST", self.api("/v1/admin/requests/r_lantern-conformance-"
                                                                   + secrets.token_hex(6)),
                                                  body={"schema": 1, "decision": "done"}), [404], {"not_found"})
            told = ""
            if since is not None:
                r = self.http.request("GET", self.api(f"/v1/changes?since={quote(since, safe='')}&wait=0"))
                expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
                got = [(e["data"].get("id"), e["data"].get("status")) for e in r.json().get("events", [])
                       if e.get("event") == "request"]
                for want in ((rid, "open"), (rid, "declined"), (again, "open"), (again, "done")):
                    expect(want in got, f"{r}: no event request {want[1]} for {want[0]} (SPEC.md § 18.2)")
                told = "; an event at each change"
        finally:
            for rid in made:
                self.http.request("DELETE", self.api(f"/v1/requests/{quote(rid, safe='')}"), platform=platform)
        return f"{made[0]} declined with its reason, then final (409); {made[1]} done{told}"

    def events_token(self):
        """The token events start from now: ready's id on a stream opened and closed at once (SPEC.md § 18.1)."""
        s = self.open_stream()
        if not isinstance(s, checks_v05.Stream):
            return None
        try:
            rid, _ = self.ready(s)
        finally:
            s.close()
        return rid

    def c_admin_refused(self):
        anon = self.http.request("GET", self.api("/v1/admin/users"), auth="none")
        self.expect_problem(anon, [401, 404], {"unauthorized", "not_found"})
        if "admin" in self.scopes():
            return f"anonymously {anon.status}"
        if self.args.token is None:
            return f"anonymously {anon.status}; no token to try"
        r = self.http.request("GET", self.api("/v1/admin/users"))
        self.expect_problem(r, [403, 404], {"forbidden", "account_frozen", "not_found"})
        return f"anonymously {anon.status}, without the scope {r.status}"

    def c_admin_users(self):
        users = self.admin_walk(self.api("/v1/admin/users"), "admin-users")
        me = self.hello["account"].get("name")
        expect(any(u["name"] == me for u in users), f"the caller's own account, {me}, is not listed")
        return f"{len(users)} account(s)"

    def c_admin_users_write(self):
        if not self.args.admin_writes:
            raise Skip("it makes an account of its own, then deletes it: run with --admin-writes")
        name = "lantern-conformance-" + secrets.token_hex(4)
        r = self.http.request("POST", self.api("/v1/admin/users"), body={
            "schema": 1, "name": name, "scopes": ["library", "admin", "sync.read", "sync.write"]})
        expect(r.status == 201, f"{r}, expected 201" + problem_detail(r))
        self.validate(r.json(), "admin-user", str(r))
        again = self.http.request("POST", self.api("/v1/admin/users"), body={"schema": 1, "name": name, "scopes": []})
        self.expect_problem(again, [409], {"conflict"})
        r = self.http.request("PATCH", self.api(f"/v1/admin/users/{name}"), body={"schema": 1, "state": "frozen"})
        expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
        self.validate(r.json(), "admin-user", str(r))
        expect(r.json()["state"] == "frozen", f"{r}: state {r.json()['state']}, frozen asked for")
        listed = {u["name"]: u for u in self.admin_walk(self.api("/v1/admin/users"), "admin-users")}
        expect(listed.get(name, {}).get("state") == "frozen", f"{name} is not listed frozen")
        r = self.http.request("PATCH", self.api(f"/v1/admin/users/{name}"), body={"schema": 1, "state": "active"})
        expect(r.status == 200 and r.json()["state"] == "active", f"{r}: thawed, expected 200 active" + problem_detail(r))
        self.made_account = name
        return f"{name}, frozen, then thawed"

    def sheets(self):
        """{(platform, title_id): ratings} of every title of the library, read with the suite's token."""
        if getattr(self, "_sheets", None) is None:
            apps = self.library()
            out = {}
            if self.features(self.hello)["titles"]:
                for platform in sorted({a["platform"] for a in apps}):
                    ids = sorted({a["title_id"] for a in apps if a["platform"] == platform})
                    for i in range(0, len(ids), TITLES_AT_ONCE):
                        _, doc = self.get_json(self.api("/v1/titles?ids=" + ",".join(
                            quote(x, safe="") for x in ids[i:i + TITLES_AT_ONCE])), "titles", platform=platform)
                        out.update({(t["platform"], t["title_id"]): t.get("ratings", []) for t in doc["titles"]})
            self._sheets = out
        return self._sheets

    def pick_cap(self):
        """A cap that hides some of the library and shows the rest, when its ratings allow (SPEC.md § 5.6)."""
        ages = sorted({a for r in self.sheets().values() for a in [client.rating_age(r, {"age": 0})] if a is not None})
        if len(ages) >= 2:
            return {"age": ages[0]}
        if ages and ages[0] >= 1:
            return {"age": ages[0] - 1}
        return {"age": 18, "unrated": "hide"}

    def keyed_pairing(self, scopes, invitation=None):
        seed, public = client.ed25519_keypair()
        body = {"schema": 1, "device": "Lantern conformance " + secrets.token_hex(3), "scopes": scopes,
                "key": {"alg": "ed25519", "public_key": base64.b64encode(public).decode()}}
        if invitation:
            body["invitation"] = invitation
        return seed, public, self.http.request("POST", self.api("/v1/pairing"), auth="none", body=body)

    def waiting(self, code):
        items = self.admin_walk(self.api("/v1/admin/pairings"), "admin-pairings")
        found = next((p for p in items if re.sub(r"\W", "", p["code"]) == re.sub(r"\W", "", code)), None)
        expect(found is not None, f"the pairing of code {code} is not among those waiting")
        return found

    def collect(self, poll, seed):
        """The token document of an approved pairing, polled with its key."""
        for _ in range(20):
            r = self.http.request("GET", self.file_path(poll), auth="none", seed=seed)
            if r.status == 200:
                self.validate(r.json(), "pairing-token", str(r))
                self.tokens_seen = getattr(self, "tokens_seen", []) + [r.json().get("token", "")]
                return r.json()
            expect(r.status in (202, 429), f"{r}, expected the token" + problem_detail(r))
            time.sleep(min(int(r.header("Retry-After") or 1), 5))
        raise Fail("no token after 20 polls")

    def c_admin_pairings(self):
        seed, public, r = self.keyed_pairing(["library"])
        expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
        code = r.json()
        found = self.waiting(code["code"])
        expect(found.get("key") == client.key_fingerprint(base64.b64encode(public).decode()),
               f"the waiting pairing's key {found.get('key')}, not the short fingerprint of the key sent")
        cap = self.pick_cap()
        decision = {"schema": 1, "decision": "approve", "scopes": ["library", "saves"], "rating_cap": cap}
        r = self.http.request("POST", self.api(f"/v1/admin/pairings/{quote(found['id'], safe='')}"), body=decision)
        expect(r.status == 204, f"{r}, expected 204" + problem_detail(r))
        doc = self.collect(code["poll"], seed)
        expect(doc["scopes"] == ["library"], f"scopes {doc['scopes']}: at most those asked for (library)")
        expect(doc.get("bound") is True, "the token of a pairing with a key is not bound")
        self.capped = {"token": doc["token"], "seed": seed, "public": public, "cap": cap,
                       "device": found["device"], "rating_cap": doc.get("rating_cap")}
        return f"{found['device']}, approved for library with the cap {cap}"

    def as_capped(self, method, path, platform=None, raw=False, body=None):
        c = self.capped
        return self.http.request(method, path, token=c["token"], seed=c["seed"], platform=platform, raw=raw, body=body)

    def c_admin_rating_cap(self):
        c = getattr(self, "capped", None)
        if c is None:
            raise Skip("no capped device (admin.pairings)")
        cap = c["cap"]
        expect(c["rating_cap"] == cap, f"the token's document says rating_cap {c['rating_cap']}, approved {cap}")
        r = self.as_capped("GET", self.api("/v1/"))
        expect(r.status == 200 and r.json()["account"].get("rating_cap") == cap,
               f"{r}: account.rating_cap {r.json().get('account', {}).get('rating_cap')}, expected {cap}")
        sheets, apps = self.sheets(), self.library()
        hidden = {a["id"] for a in apps if client.above_cap(sheets.get((a["platform"], a["title_id"]), []), cap)}
        seen, cursor = [], None
        while True:
            r = self.as_capped("GET", self.api("/v1/apps?page_size=500" + (f"&cursor={quote(cursor, safe='')}"
                                                                           if cursor else "")))
            expect(r.status == 200, f"{r}" + problem_detail(r))
            seen += [a["id"] for a in r.json()["items"]]
            cursor = r.json()["next"]
            if cursor is None:
                break
        expect(set(seen) == {a["id"] for a in apps} - hidden,
               f"the capped listing has {len(seen)} apps, {len(apps) - len(hidden)} expected")
        hidden_titles = {(a["platform"], a["title_id"]) for a in apps if a["id"] in hidden}
        for platform, tid in sorted(hidden_titles)[:3]:
            one = self.as_capped("GET", self.api(f"/v1/titles/{quote(tid, safe='')}"), platform=platform)
            self.expect_problem(one, [404], {"not_found"})
            bulk = self.as_capped("GET", self.api(f"/v1/titles?ids={quote(tid, safe='')}"), platform=platform)
            expect(bulk.status == 200 and tid in bulk.json()["unknown"], f"{bulk}: {tid} is not unknown to the cap")
        for a in [a for a in apps if a["id"] in hidden][:2]:
            f = self.as_capped("HEAD", self.file_path(a["file"]), raw=True)
            expect(f.status in (404, 410), f"{f}: the file of a hidden app, expected 404")
        platform = self.sample_platform()
        r = self.as_capped("POST", self.api("/v1/apps/missing?page_size=500"), platform=platform,
                           body={"schema": 1, "installed": [], "want": ["base"]})
        expect(r.status == 200, f"{r}" + problem_detail(r))
        expect(not ({a["id"] for a in r.json()["items"]} & hidden), "what is missing holds hidden apps")
        homebrew = [e for e in (self.homebrew or []) if client.above_cap(e.get("ratings", []), cap)]
        if self.features(self.hello)["homebrew"]:
            r = self.as_capped("GET", self.api("/v1/homebrew?page_size=500"))
            expect(r.status == 200, f"{r}" + problem_detail(r))
            shown = {(e["platform"], e["id"]) for e in r.json()["items"]}
            expect(not (shown & {(e["platform"], e["id"]) for e in homebrew}), "the homebrew listing holds hidden ones")
        return (f"cap {cap}: {len(hidden)} of {len(apps)} apps hidden, {len(homebrew)} homebrew; titles 404 and "
                "unknown, files 404, missing without them")

    def c_admin_refuse(self):
        seed, _, r = self.keyed_pairing(["library"])
        expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
        found = self.waiting(r.json()["code"])
        d = self.http.request("POST", self.api(f"/v1/admin/pairings/{quote(found['id'], safe='')}"),
                              body={"schema": 1, "decision": "refuse"})
        expect(d.status == 204, f"{d}, expected 204" + problem_detail(d))
        poll = self.http.request("GET", self.file_path(r.json()["poll"]), auth="none", seed=seed)
        self.expect_problem(poll, [410], {"gone"})

    def c_admin_devices(self):
        devices = self.admin_walk(self.api("/v1/admin/devices"), "admin-devices")
        c = getattr(self, "capped", None)
        if c is None:
            raise Skip("no device of the suite's own to revoke (admin.pairings)")
        mine = client.key_fingerprint(base64.b64encode(c["public"]).decode())
        found = next((d for d in devices if d.get("key") == mine), None)
        expect(found is not None and found["bound"] and found.get("rating_cap") == c["cap"],
               "the device the suite paired is not listed, bound, with its cap")
        path = self.api(f"/v1/admin/devices/{quote(found['id'], safe='')}")
        r = self.http.request("DELETE", path)
        expect(r.status == 204, f"{r}, expected 204" + problem_detail(r))
        after = self.as_capped("GET", self.api("/v1/"))
        self.expect_problem(after, [401], {"unauthorized"})
        self.expect_problem(self.http.request("DELETE", path), [404], {"not_found"})
        self.capped = None
        return f"{len(devices)} device(s); {found['id']} revoked, its token then 401"

    def c_admin_invitations(self):
        me = self.hello["account"]["name"]
        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = {"schema": 1, "user": me, "scopes": ["library"], "expires": expires, "devices": 1,
                "note": "Lantern conformance"}
        too_many = self.http.request("POST", self.api("/v1/admin/invitations"), body={**body, "devices": 101})
        self.expect_problem(too_many, [400], {"bad_request"})
        r = self.http.request("POST", self.api("/v1/admin/invitations"), body=body)
        expect(r.status == 201, f"{r}, expected 201" + problem_detail(r))
        inv = r.json()
        self.validate(inv, "invitation", str(r))
        path = self.api(f"/v1/admin/invitations/{quote(inv['id'], safe='')}")
        try:
            link = urlsplit(inv["link"])
            expect("invitation=" in link.query, f"link {inv['link']}: no invitation in its query")
            listed = self.admin_walk(self.api("/v1/admin/invitations"), "invitations")
            expect(inv["id"] in {i["id"] for i in listed}, "the invitation is not listed")
            typed = inv["code"].lower().replace("-", " ")     # as a user types it (SPEC.md § 5.5, L-5.5-4)
            seed, _, p = self.keyed_pairing(["library", "saves"], typed)
            expect(p.status == 200, f"{p}: redeeming the invitation typed {typed!r}, expected 200" + problem_detail(p))
            token = self.collect(p.json()["poll"], seed)
            expect(set(token["scopes"]) <= {"library"}, f"scopes {token['scopes']}: beyond the invitation's")
            _, _, again = self.keyed_pairing(["library"], inv["code"])
            self.expect_problem(again, [410], {"gone"})
            _, _, unknown = self.keyed_pairing(["library"], "ZZZZ-ZZZZ-ZZZZ-ZZZZ")
            self.expect_problem(unknown, [410], {"gone"})
        finally:
            gone = self.http.request("DELETE", path)
        expect(gone.status == 204, f"{gone}, expected 204" + problem_detail(gone))
        listed = self.admin_walk(self.api("/v1/admin/invitations"), "invitations")
        expect(inv["id"] not in {i["id"] for i in listed}, "the invitation is still listed after DELETE")
        devices = self.admin_walk(self.api("/v1/admin/devices"), "admin-devices")
        paired = [d for d in devices if d.get("invitation") == inv["id"]]
        expect(len(paired) == 1, f"{len(paired)} device(s) paired by an invitation of 1 device")
        for d in paired:
            self.http.request("DELETE", self.api(f"/v1/admin/devices/{quote(d['id'], safe='')}"))
        return f"{inv['id']}: redeemed once, then 410; revoked; its device revoked"

    # Over every response.

    def g_problems(self):
        bad = []
        for r in self.http.log:
            if r.status < 400 or r.method == "HEAD":
                continue
            if r.ctype != "application/problem+json":
                bad.append(f"{r}: Content-Type {r.ctype or 'none'}")
                continue
            try:
                doc = r.json()
                self.validate(doc, "problem", str(r))
                expect(doc["status"] == r.status, f"{r}: status {doc['status']} in the body")
                if r.status in CODES:
                    expect(doc["code"] in CODES[r.status], f"{r}: code {doc['code']} for {r.status}")
            except Fail as e:
                bad.append(str(e))
        expect(not bad, "\n".join(bad[:8]) + (f"\n… and {len(bad) - 8} more" if len(bad) > 8 else ""))
        return f"{sum(1 for r in self.http.log if r.status >= 400)} error(s) seen"

    def g_never_200(self):
        bad = [str(r) for r in self.http.log if r.status < 400 and r.ctype == "application/problem+json"]
        expect(not bad, "\n".join(bad[:8]))

    def g_401(self):
        bad = [str(r) for r in self.http.log
               if r.status == 401 and not (r.header("WWW-Authenticate") or "").lower().startswith("bearer")]
        expect(not bad, "\n".join(bad[:8]))

    def g_no_basic(self):
        bad = [str(r) for r in self.http.log if "basic" in (r.header("WWW-Authenticate") or "").lower()]
        expect(not bad, "\n".join(bad[:8]))

    def json_documents(self):
        for r in self.http.log:
            if r.is_json and r.body and r.method != "HEAD" and not r.raw:
                try:
                    yield r, r.json()
                except Fail:
                    yield r, None

    def g_schema(self):
        bad = [str(r) for r, d in self.json_documents()
               if not (isinstance(d, dict) and isinstance(d.get("schema"), int) and not isinstance(d["schema"], bool))]
        expect(not bad, "\n".join(bad[:8]))

    def g_ctype(self):
        bad = [f"{r}: {r.ctype}" for r in self.http.log
               if 200 <= r.status < 300 and r.method != "HEAD" and r.body and not r.raw
               and not r.path.startswith(self.api("/v1/files/")) and r.ctype != "application/json"]
        expect(not bad, "\n".join(bad[:8]))

    def g_limits(self):
        bad = []
        for r, doc in self.json_documents():
            if len(r.body) > JSON_LIMIT:
                bad.append(f"{r}: {len(r.body)} bytes")
            bad += [f"{r}: {p}" for p in limit_problems(doc)]
        expect(not bad, "\n".join(bad[:8]))

    def g_date(self):
        bad = [str(r) for r in self.http.log if not r.header("Date")]
        expect(not bad, "responses without Date:\n" + "\n".join(bad[:8]))
        return f"{len(self.http.log)} response(s)"

    def g_deprecation(self):
        bad, seen = [], 0
        for r in self.http.log:
            dep, sunset = r.header("Deprecation"), r.header("Sunset")
            if dep is None and sunset is None:
                continue
            seen += 1
            when = None
            if dep is not None:
                if not re.fullmatch(r"@-?[0-9]{1,15}", dep.strip()):
                    bad.append(f"{r}: Deprecation {dep!r} is not @<Unix seconds> (RFC 9745)")
                else:
                    when = int(dep.strip()[1:])
            if sunset is not None:
                try:
                    end = parsedate_to_datetime(sunset).timestamp()
                    if when is not None and end < when:
                        bad.append(f"{r}: Sunset before Deprecation")
                except (TypeError, ValueError):
                    bad.append(f"{r}: Sunset {sunset!r} is not an HTTP date (RFC 8594)")
        expect(not bad, "\n".join(bad[:8]))
        return f"{seen} response(s) deprecated" if seen else "nothing deprecated"

    def g_private(self):
        bad = []
        for r in self.http.log:
            if r.auth == "token" and 200 <= r.status < 300:
                cc, vary = (r.header("Cache-Control") or "").lower(), (r.header("Vary") or "").lower()
                if "private" not in cc and "no-store" not in cc:
                    bad.append(f"{r}: Cache-Control {cc or 'none'}")
                elif "authorization" not in vary and "*" not in vary:
                    bad.append(f"{r}: Vary {vary or 'none'}")
        if self.args.token is None:
            raise Skip("no token given")
        if bad:
            raise Warn("\n".join(bad[:8]))


def bind_checks():
    """Gives the checks' modules this module's exceptions and helpers: again at each run, since a program may
    load run.py twice, under two names (tools/make_demo.py does), each with classes of its own."""
    checks_v05.bind(Fail=Fail, Skip=Skip, Blind=Blind, Warn=Warn, Response=Response, Client=Client,
                    check_repr_digest=lambda r, d: check_repr_digest(r, d), problem_detail=lambda r: problem_detail(r))
    static_check.bind(Fail=Fail, Skip=Skip, Blind=Blind, Warn=Warn, Client=Client, client=client,
                      limit_problems=lambda doc: limit_problems(doc))
    checks_v06.bind(Fail=Fail, Skip=Skip, Blind=Blind, Warn=Warn, problem_detail=lambda r: problem_detail(r))


bind_checks()


def client_rule():
    raise Skip("a client rule, not visible from outside")


def _skip(why):
    raise Skip(why)


def _blind(why):
    raise Blind(why)


def reqs_of(cid):
    """The requirement ids a check covers (REQS), by its id or the family of ids it belongs to."""
    if cid in REQS:
        return REQS[cid]
    for prefix in ("features", "apps.pages", "schema.refused", "static.pages"):
        if cid.startswith(prefix + "."):
            return REQS[prefix]
    return []


def spki_of(der):
    """The SHA-256 of a DER certificate's SubjectPublicKeyInfo (SPEC.md § 5.3), hex."""
    def element(pos):
        tag, length, pos = der[pos], der[pos + 1], pos + 2
        if length & 0x80:
            n = length & 0x7F
            length, pos = int.from_bytes(der[pos:pos + n], "big"), pos + n
        return pos, pos + length, tag
    start, _, _ = element(0)
    pos, end, _ = element(start)
    fields = []
    while pos < end:
        _, after, tag = element(pos)
        fields.append((pos, after, tag))
        pos = after
    if fields[0][2] == 0xA0:
        fields = fields[1:]
    begin, after, _ = fields[5]
    return hashlib.sha256(der[begin:after]).hexdigest()


def loopback(host):
    """127.0.0.0/8, ::1 or localhost (SPEC.md § 2)."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def problem_detail(r):
    if r.is_json and r.status >= 400:
        try:
            d = r.json()
            return f" ({d.get('code')}: {d.get('detail') or d.get('title')})"
        except Fail:
            pass
    return ""


def check_repr_digest(r, digest):
    """Repr-Digest, a MUST on every file response (SPEC.md § 6.6): the whole file's SHA-256."""
    header = r.header("Repr-Digest")
    expect(header, f"{r}: no Repr-Digest")
    values = dict(part.strip().split("=", 1) for part in header.split(",") if "=" in part)
    value = values.get("sha-256", "").strip()
    expect(value.startswith(":") and value.endswith(":"), f"{r}: Repr-Digest {header!r} has no sha-256")
    try:
        got = base64.b64decode(value[1:-1], validate=True).hex()
    except ValueError:
        raise Fail(f"{r}: Repr-Digest sha-256 is not base64") from None
    expect(got == digest, f"{r}: Repr-Digest {got}, the bytes hash to {digest}")


def check_archive(where, data, manifest):
    """An archive holds each manifest file under its path without the leading / (SPEC.md § 8.2)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = {i.filename: i for i in z.infolist() if not i.is_dir()}
            for m in manifest:
                info = names.get(m["path"][1:])
                expect(info is not None, f"{where}: {m['path']} is not in the archive")
                expect(info.file_size == m["size"], f"{where}: {m['path']} is {info.file_size} bytes, the manifest "
                                                    f"says {m['size']}")
                with z.open(info) as f:
                    got = hashlib.sha256(f.read(m["size"] + 1)).hexdigest()
                expect(got == m["sha256"], f"{where}: {m['path']} does not match its manifest sha256")
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, ValueError, zlib.error) as e:
        raise Fail(f"{where}: not an archive a client can read ({e})") from None


def limit_problems(doc):
    """SPEC.md § 13, over one document."""
    out = []

    def walk(value, depth, key):
        if isinstance(value, (dict, list)):
            if depth > 16:
                out.append(f"nested deeper than 16 at {key}")
                return
            if isinstance(value, list):
                if key == "items" and len(value) > 1000:
                    out.append(f"{len(value)} items on a page")
                if key == "manifest" and len(value) > client.MANIFEST_LIMIT:
                    out.append(f"{len(value)} files in a manifest")
                for v in value:
                    walk(v, depth + 1, key)
            else:
                for k, v in value.items():
                    walk(v, depth + 1, k)
        elif isinstance(value, str):
            cap = {"name": 512, "note": 120, "profile": 64}.get(key, 4096)
            if len(value.encode()) > cap:
                out.append(f"{key}: {len(value.encode())} bytes, above {cap}")

    walk(doc, 1, None)
    return out


def load_validators(folder):
    try:
        from jsonschema import Draft202012Validator, FormatChecker
        from referencing import Registry, Resource
    except ImportError:
        sys.exit("conformance: the schema checks need jsonschema and referencing "
                 "(pip install -r tools/requirements.txt), or run with --no-schemas")
    schemas = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))}
    if not schemas:
        sys.exit(f"conformance: no schema in {folder}")
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas.values())
    return {name: Draft202012Validator(s, registry=registry, format_checker=FormatChecker())
            for name, s in schemas.items()}


def main(argv=None, out=None):
    p = argparse.ArgumentParser(prog="conformance/run.py", description="Checks a Lantern server against SPEC.md.")
    p.add_argument("url", nargs="?", help="the server, e.g. https://shelf.example.org/")
    p.add_argument("--token", help="a device's token, from pairing (Authorization: Bearer)")
    p.add_argument("--key", help="the file of the token's device key: its 32-byte Ed25519 seed, base64 (SPEC.md § 5.4)")
    p.add_argument("--admin-writes", action="store_true",
                   help="with the scope admin, also make an account of its own, then delete it (SPEC.md § 5.7)")
    p.add_argument("--pin", metavar="SPKI", help="trust the server by the SHA-256 of its key's SPKI, hex, as a paired "
                   "client does (SPEC.md § 5.3), instead of a CA")
    p.add_argument("--peer", metavar="URL", help="also check a peer (SPEC.md § 19.4): its address and base, e.g. "
                   "http://192.168.1.20:47116/lantern")
    p.add_argument("--fetch-mirrors", action="store_true", help="also read the bytes of every mirror the library "
                   "names, without any credential of the server, and check their size and SHA-256 (SPEC.md § 19.2)")
    p.add_argument("--peer-discover-port", type=int, help="the UDP port the peer answers discovery on (default: "
                   "--discover-port's)")
    p.add_argument("--dns-sd", metavar="ADDRESS[:PORT]", help="also ask DNS-SD for _lantern._tcp, unicast, at this "
                   "address (its port 5353 by default)")
    p.add_argument("--rate-probe", type=int, default=120, help="pairing requests sent at most to see 429 (§ 5.2, § 5.5)")
    p.add_argument("--static", metavar="URL_OR_FOLDER", help="check a static library (SPEC.md § 21) instead of a "
                   "server; the url argument is then not needed")
    p.add_argument("--base", help="the base path, when the handshake should not decide it")
    p.add_argument("--cafile", help="CA certificates to trust (PEM)")
    p.add_argument("--insecure", action="store_true", help="do not verify the certificate (a LAN server)")
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--max-items", type=int, default=20000, help="read every page up to this many apps")
    p.add_argument("--max-entries", type=int, default=200, help="homebrew entries read on their own route at most")
    p.add_argument("--max-download", type=int, default=64 << 20, help="bytes downloaded at most (default 64 MiB)")
    p.add_argument("--max-files", type=int, default=3, help="files downloaded whole at most, per family (homebrew: entries, each with every package)")
    p.add_argument("--discover", metavar="ADDRESS", help="also send LAN discovery to this address")
    p.add_argument("--discover-port", type=int, default=DISCOVERY_PORT)
    p.add_argument("--schemas", default=str(Path(__file__).resolve().parent.parent / "schemas" / "v1"))
    p.add_argument("--no-schemas", action="store_true", help="skip the JSON Schema checks")
    args = p.parse_args(argv)
    if not args.url and not args.static:
        p.error("the server's url, or --static")
    if args.static:
        args.url = args.url or "https://static.invalid/"
    bind_checks()
    suite = Suite(args)
    if out is not None:
        suite.out = out
    return suite.run_static() if args.static else suite.run()


if __name__ == "__main__":
    sys.exit(main())
