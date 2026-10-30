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
signatures, updates), cheat sets, requests, save backups, errors, limits, and LAN
discovery when asked for (--discover). Each check prints PASS, FAIL, WARN (a
SHOULD not met) or SKIP, with the SPEC.md section it comes from; the exit
code is 1 when one fails.

The token is one a device got by pairing (SPEC.md § 5.2); without it, the
suite calls as an anonymous client. It approves nothing, but it asks for a
few pairing codes (feature `pairing`), which the server may show to its
users until they expire on their own. With a token that holds `saves`, it
sends save backups for a title id of its own (none of the library's, so
that no backup of the user's is dropped for them), in one request and by
resumable upload, and deletes them before it ends. With `cheats.write`, it
writes a cheat set for such a title, replaces it and deletes it. With
`requests`, it asks for such a title twice (the second answer is the same
request): SPEC.md has no route to delete a request, so that one request
stays on the server, open, for a title id of no game. It changes nothing
else.
Rules that only a client can keep (ignoring unknown fields, pinning, asking
before a path that needs consent, checking a port's data before launch…)
are listed as skipped.

Standard library only, but for the schema checks: those need jsonschema and
referencing (tools/requirements.txt); --no-schemas runs without them.
"""
import argparse
import base64
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
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lantern_client as client

VERSION = "0.3.0"
FAMILIES = ("library", "titles", "changes", "sections", "homebrew", "saves", "cheats", "requests", "pairing")
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
# SPEC.md § 12: the codes each status may carry.
CODES = {400: {"bad_request"}, 401: {"unauthorized"}, 403: {"forbidden", "account_frozen"},
         404: {"not_found"}, 405: {"bad_request"}, 409: {"conflict"}, 410: {"gone"},
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
CLIENT_RULES = [
    ("3.2", "A reader ignores the fields it does not know"),
    ("3.2", "A reader treats a newer schema as absent and never writes it back"),
    ("2", "Certificates are verified; plain HTTP only to a loopback address"),
    ("4.1", "Discovery is a hint: nothing is trusted because of a reply"),
    ("5.2", "No password is ever asked for on the console"),
    ("5.3", "The key compared at pairing is pinned; a changed key fails"),
    ("6.1", "Nothing is installed of a platform without a profile"),
    ("6.6", "A download's SHA-256 is checked before installing"),
    ("7.1", "No token or credential is sent to an external address"),
    ("8.1", "A kind the client does not know is read as app"),
    ("8.1", "A port's data_root is approved by the user once"),
    ("8.1", "A port's data is checked (presence, accepted hashes, one alternative) before launch, the user guided"),
    ("8.1", "Nothing is installed over another entry's system id"),
    ("8.2", "A package of another arch is skipped"),
    ("8.3", "Only the manifest's paths are written; a path outside the free roots is shown and agreed to"),
    ("8.3", "Uninstalling removes the manifest's files only"),
    ("8.4", "A signature is checked; the key is pinned per id, a changed key refused unless accepted"),
    ("9.1", "A save is not restored on an older game without a warning"),
]


class Fail(Exception):
    pass


class Skip(Exception):
    pass


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
            try:
                self._doc = json.loads(self.body.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as e:
                raise Fail(f"{self}: not JSON ({e})") from None
        return self._doc

    def __str__(self):
        where = f", {self.platform}" if self.platform else ""
        return f"{self.method} {self.path} ({self.auth}{where}) -> {self.status}"


class Client:
    """One HTTP request per connection, with the caller chosen per request."""

    def __init__(self, origin, token, context, timeout):
        self.origin, self.token = origin, token
        self.context, self.timeout, self.log = context, timeout, []

    def authorization(self, auth):
        if auth == "token" and self.token is not None:
            return "Bearer " + self.token
        if auth == "unknown":
            return "Bearer et_lantern-conformance-" + secrets.token_hex(16)
        if auth == "basic":     # what a server MUST refuse (SPEC.md § 5.1)
            return "Basic " + base64.b64encode(f"lantern-conformance:{secrets.token_hex(8)}".encode()).decode()
        return None

    def request(self, method, path, auth="token", headers=None, body=None, limit=JSON_LIMIT, platform=None,
                raw=False):
        """`platform`: sent as Lantern-Platform; `raw`: a file, not a JSON document."""
        u = self.origin
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        kw = {"context": self.context} if u.scheme == "https" else {}
        conn = cls(u.hostname, u.port, timeout=self.timeout, **kw)
        hdrs = {"User-Agent": f"LanternConformance/{VERSION}", "Accept-Language": "en", **(headers or {})}
        if platform:
            hdrs["Lantern-Platform"] = platform
        if self.authorization(auth):
            hdrs["Authorization"] = self.authorization(auth)
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        try:
            conn.request(method, path, body=body, headers=hdrs)
            r = conn.getresponse()
            data = b"" if method == "HEAD" else r.read(limit + 1)
            res = Response(method, path, "anonymous" if auth == "none" or (auth == "token" and self.token is None)
                           else auth, r.status, r.headers, data[:limit], len(data) > limit, raw, platform)
        finally:
            conn.close()
        self.log.append(res)
        return res


class Suite:
    def __init__(self, args):
        self.args = args
        u = urlsplit(args.url if "://" in args.url else "https://" + args.url)
        self.origin = u
        if u.scheme == "https":
            ctx = ssl.create_default_context(cafile=args.cafile)
            if args.insecure:
                ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        else:
            ctx = None
        self.http = Client(u, args.token, ctx, args.timeout)
        self.results = []
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
        try:
            detail, status = fn(), "PASS"
        except Skip as e:
            detail, status = str(e), "SKIP"
        except Warn as e:
            detail, status = str(e), "WARN"
        except Fail as e:
            detail, status = str(e), "FAIL" if level == "must" else "WARN"
        except (OSError, http.client.HTTPException) as e:
            detail, status = f"connection: {e}", "FAIL"
        self.results.append((status, section, cid, title, detail))
        print(f"{status:<4}  § {section:<5} {cid:<30} {title}", file=self.out)
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
              + (" with a token" if self.args.token else " anonymously"), file=self.out)
        self.check("transport.https", "2", "HTTPS, or plain HTTP on loopback only", self.c_https)
        if not self.check("handshake.well-known", "4.2", "GET /.well-known/lantern is a valid handshake",
                          self.c_well_known):
            print("No handshake: nothing else can be checked.", file=self.out)
            return self.summary()
        self.check("handshake.v1", "4.2", "GET <base>/v1/ is the same handshake", self.c_v1)
        self.check("handshake.versions", "3.1", "The server serves version 1", self.c_versions)
        self.check("handshake.anonymous", "4.2", "Without credentials: account anonymous", self.c_anonymous)
        self.check("handshake.account", "4.2", "With a token: the account and its state", self.c_account)
        self.check("handshake.platforms", "4.3", "platforms: names, the same for every caller", self.c_platforms)
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
            self.check("pairing.waiting", "5.2", "Polling an unapproved pairing gives 202", self.c_pairing_waiting)
            self.check("pairing.slow-down", "5.2", "Polling faster than interval gives 429 slow_down",
                       self.c_pairing_slow, level="should")
            self.check("pairing.unknown", "5.2", "An unknown poll address gives 410", self.c_pairing_unknown)
            self.check("pairing.rate-limit", "5.2", "Pairing requests are rate-limited", lambda: _skip(
                "not checked: it would take many requests; the reference server's tests check it"))
        if mine["library"]:
            self.check("apps.first-page", "6.2", "GET <base>/v1/apps is a valid page", self.c_first_page)
        for family in FAMILIES:
            self.check(f"features.{family}", "4.2", f"Feature {family} ({mine[family]}) is honoured",
                       lambda f=family: self.c_feature(f, "token", mine[f]))
        if self.args.token is not None:
            self.check("features.anonymous", "4.2", "Without credentials, features are honoured too",
                       self.c_features_anonymous)
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
            self.check("files.whole", "6.6", "Whole files and HEAD: length, ETag, sha256 and Repr-Digest",
                       self.c_files)
            self.check("files.ranges", "6.6", "Ranges: 206 with the right slice and the whole file's Repr-Digest",
                       self.c_ranges)
            self.check("files.unsatisfiable", "6.6", "A range outside the file gives 416 with Content-Range", self.c_416)
            self.check("files.unknown", "6.6", "An unknown file id gives 404 or 410", self.c_unknown_file)
        if mine["changes"]:
            self.check("changes.token", "6.4", "Changes: no apps and a token, then from it", self.c_changes)
            self.check("changes.bad-token", "6.4", "An unknown since token gives 400 or 410", self.c_bad_since)
        if mine["titles"]:
            self.check("titles.known", "7.1", "A title of the library is a valid sheet, of its platform",
                       self.c_title)
            self.check("titles.unknown", "7.1", "An unknown title gives 404", self.c_unknown_title)
            self.check("titles.bulk", "7.2", "Many titles at once: those known, and the ids unknown", self.c_titles)
            self.check("titles.bulk-limit", "7.2", f"More than {TITLES_AT_ONCE} ids give 400", self.c_titles_limit)
            self.check("titles.changes", "7.3", "Title changes: a token, then from it", self.c_title_changes)
            self.check("titles.bad-token", "7.3", "An unknown since token gives 400 or 410", self.c_title_bad_since)
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
        if mine["cheats"]:
            self.check("cheats.sets", "10", "Cheat sets: valid, ids unique, filtered as asked", self.c_cheats)
            self.check("cheats.text", "10", "A set's text: a file of its size and sha256, 1 MiB at most",
                       self.c_cheat_text)
            self.check("cheats.unknown", "10", "An unknown set gives 404", self.c_cheat_unknown)
            self.check("cheats.write", "10", "Without cheats.write, writing is refused", self.c_cheat_write)
            self.check("cheats.write-cycle", "10", "With cheats.write: a set posted (201), listed, read, replaced "
                       "(204), deleted (204), then gone", self.c_cheat_write_cycle)
        if mine["requests"]:
            self.check("requests.list", "11", "The account's requests: valid, of the platform asked",
                       self.c_requests)
            self.check("requests.create", "11", "A request: 201, then 200 with the same open request, listed",
                       self.c_request_create)
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
                self.check("saves.cleanup", "9.1", "What the suite made is deleted (204), then gone (404)",
                           self.c_save_cleanup)
            else:
                self.check("saves.upload", "9.3", "Resumable upload", lambda: _skip("the token lacks the scope saves"))
        for family, (path, _) in BODIES.items():
            if mine[family] and (family != "saves" or "saves" in self.scopes()):
                self.check(f"schema.refused.{family}", "3.2", f"POST {path} of schema 2 gives 422 unsupported_schema",
                           lambda f=family: self.c_schema_2(f))
        self.check("errors.unknown-route", "12", "An unknown route gives 404 not_found", self.c_unknown_route)
        self.check("discovery.reply", "4.1", "LAN discovery reply", self.c_discovery)
        for section, rule in CLIENT_RULES:
            self.check("client-rule", section, rule, client_rule)
        # Over every response the run saw.
        self.check("errors.problem", "12", "Every error is a valid application/problem+json", self.g_problems)
        self.check("errors.never-200", "12", "No error is sent with a 2xx status", self.g_never_200)
        self.check("errors.www-authenticate", "5.1", "Every 401 has WWW-Authenticate: Bearer", self.g_401)
        self.check("auth.no-basic", "5.1", "No response asks for HTTP Basic", self.g_no_basic)
        self.check("documents.schema", "3.2", "Every document has an integer schema", self.g_schema)
        self.check("documents.type", "2", "Every document is application/json", self.g_ctype)
        self.check("documents.limits", "13", "Documents stay within the limits", self.g_limits)
        self.check("caching.private", "14", "Authenticated answers: Cache-Control private, Vary Authorization",
                   self.g_private, level="should")
        return self.summary()

    def summary(self):
        counts = {s: sum(1 for r in self.results if r[0] == s) for s in ("PASS", "FAIL", "WARN", "SKIP")}
        print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['WARN']} warning(s), "
              f"{counts['SKIP']} skipped; {len(self.http.log)} requests.", file=self.out)
        return 1 if counts["FAIL"] or not self.results else 0

    # Transport and handshake (SPEC.md § 2, 4).

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
        on = [f for f, v in self.features(self.hello).items() if v and f != "pairing"]
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
        path = self.api(path.format(title_id=quote(self.title_id(), safe="")))
        return self.http.request(method, path, auth=auth, body=body), schema

    def c_feature(self, family, auth, level):
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
        r = self.http.request("POST", self.api("/v1/cheats"), body=body, platform=platform)
        expect(r.status == 201, f"{r}, expected 201" + problem_detail(r))
        doc = r.json()
        self.validate(doc, "cheat", str(r))
        sid = doc["id"]
        path = self.api(f"/v1/cheats/{quote(sid, safe='')}")
        try:
            for key in ("platform", "title_id", "build_id", "source"):
                expect(doc.get(key) == body[key], f"{r}: {key} {doc.get(key)!r}, sent {body[key]!r}")
            expect(doc["size"] == len(text.encode()) and doc["sha256"] == hashlib.sha256(text.encode()).hexdigest(),
                   f"{r}: size and sha256 are not those of the text sent")
            query = f"title_id={quote(tid, safe='')}&build_id=0123456789ABCDEF"
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
            raise Skip("the token lacks the scope requests")
        _, doc = self.get_json(self.api("/v1/requests"), "requests")
        platform = self.sample_platform()
        _, mine = self.get_json(self.api("/v1/requests"), "requests", platform=platform)
        expect(all(q["platform"] == platform for q in mine["requests"]), f"Lantern-Platform {platform}: "
               "requests of another platform")
        return f"{len(doc['requests'])} request(s), {len(mine['requests'])} for {platform}"

    def c_request_create(self):
        if "requests" not in self.scopes():
            raise Skip("the token lacks the scope requests")
        platform, tid = self.save_title()
        body = {"schema": 1, "platform": platform, "title_id": tid}
        r = self.http.request("POST", self.api("/v1/requests"), body=body, platform=platform)
        expect(r.status in (200, 201), f"{r}, expected 201" + problem_detail(r))
        first = r.json()
        self.validate(first, "request", str(r))
        expect((first["platform"], first["title_id"], first["status"]) == (platform, tid, "open"),
               f"{r}: not an open request for {platform}/{tid}")
        r = self.http.request("POST", self.api("/v1/requests"), body=body, platform=platform)
        expect(r.status == 200, f"{r}: the same title asked again, expected 200 with the open request"
               + problem_detail(r))
        self.validate(r.json(), "request", str(r))
        expect(r.json()["id"] == first["id"], f"{r}: another request, {r.json()['id']}, not {first['id']}")
        _, listed = self.get_json(self.api("/v1/requests"), "requests", platform=platform)
        expect(first["id"] in {q["id"] for q in listed["requests"]}, "the request is not listed")
        return (f"request {first['id']} for {platform}/{tid}, left on the server: SPEC.md has no route to "
                "delete one")

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
                tid = f"00040000F{secrets.token_hex(3).upper()}00"
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
        r = self.http.request("POST", path, body=data, headers=headers, platform=platform)
        self.expect_problem(r, [400], {"bad_request"})
        self.keep(r)
        wrong = base64.b64encode(hashlib.sha256(data + b"!").digest()).decode()
        r = self.http.request("POST", path, body=data, headers={**headers, "Content-Digest": f"sha-256=:{wrong}:"},
                              platform=platform)
        self.expect_problem(r, [422], {"digest_mismatch"})
        self.keep(r)
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


def client_rule():
    raise Skip("a client rule, not visible from outside")


def _skip(why):
    raise Skip(why)


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
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, ValueError) as e:
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
    p.add_argument("url", help="the server, e.g. https://shelf.example.org/")
    p.add_argument("--token", help="a device's token, from pairing (Authorization: Bearer)")
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
    suite = Suite(args)
    if out is not None:
        suite.out = out
    return suite.run()


if __name__ == "__main__":
    sys.exit(main())
