#!/usr/bin/env python3
"""Lantern conformance suite: checks a server against SPEC.md, from outside.

    python3 conformance/run.py https://shelf.example.org/ [--user U --password P]

It reads the handshake at the URL's origin, then checks every MUST it can
see from a client's side: documents and their `schema` against schemas/v1/,
the features a server declares against the routes it answers, cursor pages,
what a console is missing, ranges, digests, errors, limits. Each check
prints PASS, FAIL, WARN (a SHOULD not met) or SKIP, with the SPEC.md section
it comes from; the exit code is 1 when one fails.

It changes nothing on the server, but for a pairing code it may ask for
(feature `pairing`), which expires on its own. Rules that only a client can
keep (ignoring unknown fields, pinning, checking a download) are listed as
skipped.

Standard library only, but for the schema checks: those need jsonschema and
referencing (tools/requirements.txt); --no-schemas runs without them.
"""
import argparse
import base64
import hashlib
import http.client
import itertools
import json
import math
import secrets
import socket
import ssl
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlsplit

VERSION = "0.1.0"
FAMILIES = ("library", "media", "changes", "sections", "saves", "cheats", "requests", "pairing")
JSON_LIMIT = 32 << 20
# SPEC.md § 10: the codes each status may carry.
CODES = {400: {"bad_request"}, 401: {"unauthorized"}, 403: {"forbidden", "account_frozen"},
         404: {"not_found"}, 405: {"bad_request"}, 409: {"conflict"}, 410: {"gone"},
         413: {"too_large"}, 416: {"bad_request"}, 422: {"unsupported_schema"},
         429: {"slow_down"}, 503: {"unavailable"}}
# A route per family, to see whether the server honours what it declares (SPEC.md § 4.2).
PROBES = {
    "library": ("GET", "/v1/apps?page_size=1", None, "apps"),
    "media": ("GET", "/v1/titles/{title_id}", None, "title"),
    "changes": ("GET", "/v1/changes", None, "changes"),
    "sections": ("GET", "/v1/sections", None, "sections"),
    "saves": ("GET", "/v1/saves", None, "saves"),
    "cheats": ("GET", "/v1/cheats", None, "cheats"),
    "requests": ("GET", "/v1/requests", None, "requests"),
    "pairing": ("POST", "/v1/pairing", {"schema": 1, "device": "Lantern conformance", "scopes": ["library"]},
                "pairing-code"),
}
# Routes that take a JSON document, by family, with a document of schema 2 (SPEC.md § 3.2, § 10).
BODIES = {
    "library": ("/v1/apps/missing", {"schema": 2, "installed": [], "want": ["base"]}),
    "pairing": ("/v1/pairing", {"schema": 2, "device": "Lantern conformance", "scopes": ["library"]}),
    "requests": ("/v1/requests", {"schema": 2, "title_id": "{title_id}"}),
}
CLIENT_RULES = [
    ("3.2", "A reader ignores the fields it does not know"),
    ("3.2", "A reader treats a newer schema as absent and never writes it back"),
    ("2", "Certificates are verified; credentials never go over plain HTTP"),
    ("5.3", "A pinned key that changes fails"),
    ("6.6", "No credentials sent to an external media URL"),
    ("13", "A download's sha256 is checked before installing"),
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
    def __init__(self, method, path, auth, status, headers, body, truncated):
        self.method, self.path, self.auth = method, path, auth
        self.status, self.headers, self.body, self.truncated = status, headers, body, truncated
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
        return f"{self.method} {self.path} ({self.auth}) -> {self.status}"


class Client:
    """One HTTP request per connection, with the caller chosen per request."""

    def __init__(self, origin, user, password, context, timeout):
        self.origin, self.user, self.password = origin, user, password
        self.context, self.timeout, self.log = context, timeout, []

    def authorization(self, auth):
        if auth == "user" and self.user is not None:
            return "Basic " + base64.b64encode(f"{self.user}:{self.password}".encode()).decode()
        if auth == "wrong":
            return "Basic " + base64.b64encode(
                f"{self.user or 'lantern-conformance'}:wrong-{secrets.token_hex(8)}".encode()).decode()
        if auth == "bearer":
            return "Bearer et_lantern-conformance-" + secrets.token_hex(8)
        return None

    def request(self, method, path, auth="user", headers=None, body=None, limit=JSON_LIMIT):
        u = self.origin
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        kw = {"context": self.context} if u.scheme == "https" else {}
        conn = cls(u.hostname, u.port, timeout=self.timeout, **kw)
        hdrs = {"User-Agent": f"LanternConformance/{VERSION}", "Accept-Language": "en", **(headers or {})}
        if self.authorization(auth):
            hdrs["Authorization"] = self.authorization(auth)
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        try:
            conn.request(method, path, body=body, headers=hdrs)
            r = conn.getresponse()
            data = b"" if method == "HEAD" else r.read(limit + 1)
            res = Response(method, path, "anonymous" if auth == "none" else auth, r.status, r.headers,
                           data[:limit], len(data) > limit)
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
        self.http = Client(u, args.user, args.password, ctx, args.timeout)
        self.results = []
        self.validators = None if args.no_schemas else load_validators(Path(args.schemas))
        self.base = args.base
        self.hello = self.hello_anon = None
        self.sample = None    # an app from the first page
        self.apps = None      # the whole library, when it could be read
        self.bytes = {}       # app id -> the file, read whole
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

    def get_json(self, path, schema, auth="user", status=200):
        r = self.http.request("GET", path, auth=auth)
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

    # The run.

    def run(self):
        print(f"Lantern conformance {VERSION}: {self.origin.scheme}://{self.origin.netloc}/"
              + (f" as {self.args.user}" if self.args.user else " anonymously"), file=self.out)
        self.check("transport.https", "2", "The server speaks HTTPS", self.c_https, level="should")
        if not self.check("handshake.well-known", "4.2", "GET /.well-known/lantern is a valid handshake",
                          self.c_well_known):
            print("No handshake: nothing else can be checked.", file=self.out)
            return self.summary()
        self.check("handshake.v1", "4.2", "GET <base>/v1/ is the same handshake", self.c_v1)
        self.check("handshake.versions", "3.1", "The server serves version 1", self.c_versions)
        self.check("handshake.anonymous", "4.2", "Without credentials: account anonymous", self.c_anonymous)
        self.check("handshake.account", "4.2", "With credentials: the account and its state", self.c_account)
        self.check("auth.wrong-password", "5.1", "A wrong password gives 401 with WWW-Authenticate", self.c_wrong)
        self.check("auth.wrong-handshake", "4.2", "A wrong password gives 401 on the handshake too",
                   self.c_wrong_handshake)
        self.check("auth.unknown-token", "5.2", "An unknown bearer token gives 401", self.c_bearer)
        self.check("auth.missing", "5.1", "A private server answers 401 without credentials", self.c_missing)
        self.check("auth.frozen", "4.2", "A frozen account: every feature at 0, 403 account_frozen",
                   self.c_frozen)
        mine = self.features(self.hello)
        if mine["library"]:
            self.check("apps.first-page", "6.2", "GET <base>/v1/apps is a valid page", self.c_first_page)
        for family in FAMILIES:
            self.check(f"features.{family}", "4.2", f"Feature {family} ({mine[family]}) is honoured",
                       lambda f=family: self.c_feature(f, "user", mine[f]))
        if self.args.user is not None:
            self.check("features.anonymous", "4.2", "Without credentials, features are honoured too",
                       self.c_features_anonymous)
        if mine["library"]:
            for sort in ("name", "added", "release"):
                self.check(f"apps.pages.{sort}", "6.2", f"Pages by {sort}: stable, no repeat, no skip",
                           lambda s=sort: self.c_walk(s))
            self.check("apps.page-size", "6.2", "A larger page_size is lowered to limits.page_size; 0 gives 400",
                       self.c_page_size)
            self.check("apps.bad-cursor", "6.2", "An unknown cursor gives 400 or 410", self.c_bad_cursor)
            self.check("apps.filters", "6.2", "type and title_id filter; a bad value gives 400", self.c_filters)
            self.check("apps.etag", "12", "A listing has an ETag and honours If-None-Match", self.c_etag,
                       level="should")
            self.check("missing.installed", "6.3", "Missing: newest update and add-ons of an installed game",
                       self.c_missing_installed)
            self.check("missing.up-to-date", "6.3", "Missing: nothing for an up-to-date game", self.c_missing_current)
            self.check("missing.base", "6.3", "Missing: with base, the games not installed", self.c_missing_base)
            self.check("missing.malformed", "10", "A malformed body gives 400 bad_request", self.c_malformed)
            self.check("files.whole", "6.7", "Whole files: length, ETag, sha256 and Repr-Digest", self.c_files)
            self.check("files.ranges", "6.7", "Ranges: 206 with the right slice", self.c_ranges)
            self.check("files.unsatisfiable", "6.7", "A range outside the file gives 416", self.c_416)
            self.check("files.unknown", "6.7", "An unknown file id gives 404 or 410", self.c_unknown_file)
        if mine["changes"]:
            self.check("changes.token", "6.4", "Changes: no apps and a token, then from it", self.c_changes)
            self.check("changes.bad-token", "6.4", "An unknown since token gives 400 or 410", self.c_bad_since)
        if mine["media"]:
            self.check("titles.known", "6.6", "A title of the library is a valid sheet", self.c_title)
            self.check("titles.unknown", "6.6", "An unknown title gives 404", self.c_unknown_title)
        for family, (path, _) in BODIES.items():
            if mine[family]:
                self.check(f"schema.refused.{family}", "3.2", f"POST {path} of schema 2 gives 422 unsupported_schema",
                           lambda f=family: self.c_schema_2(f))
        self.check("errors.unknown-route", "10", "An unknown route gives 404 not_found", self.c_unknown_route)
        self.check("discovery.reply", "4.1", "LAN discovery reply", self.c_discovery)
        for section, rule in CLIENT_RULES:
            self.check("client-rule", section, rule, client_rule)
        # Over every response the run saw.
        self.check("errors.problem", "10", "Every error is a valid application/problem+json", self.g_problems)
        self.check("errors.never-200", "10", "No error is sent with a 2xx status", self.g_never_200)
        self.check("errors.www-authenticate", "5.1", "Every 401 has WWW-Authenticate: Basic", self.g_401)
        self.check("documents.schema", "3.2", "Every document has an integer schema", self.g_schema)
        self.check("documents.type", "2", "Every document is application/json", self.g_ctype)
        self.check("documents.limits", "11", "Documents stay within the limits", self.g_limits)
        self.check("caching.private", "12", "Authenticated answers: Cache-Control private, Vary Authorization",
                   self.g_private, level="should")
        return self.summary()

    def summary(self):
        counts = {s: sum(1 for r in self.results if r[0] == s) for s in ("PASS", "FAIL", "WARN", "SKIP")}
        print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['WARN']} warning(s), "
              f"{counts['SKIP']} skipped; {len(self.http.log)} requests.", file=self.out)
        return 1 if counts["FAIL"] or not self.results else 0

    # Transport and handshake (SPEC.md § 2, 4).

    def c_https(self):
        if self.origin.scheme != "https":
            raise Warn("plain HTTP: acceptable for local testing only"
                       + ("; the credentials went in clear" if self.args.user else ""))

    def c_well_known(self):
        _, doc = self.get_json("/.well-known/lantern", "handshake")
        self.hello = doc
        if self.base is None:
            self.base = doc.get("base", "/api/lantern")
            expect(self.base.startswith("/"), f"base {self.base!r} is not a path on the origin")
        return f"base {self.base}, features " + ", ".join(f"{k}={v}" for k, v in self.features(doc).items())

    def c_v1(self):
        _, doc = self.get_json(self.api("/v1/"), "handshake")
        for key in ("schema", "uid", "name", "base", "versions", "account", "features"):
            expect(doc.get(key) == self.hello.get(key), f"{key} differs from /.well-known/lantern")

    def c_versions(self):
        expect(1 in self.hello.get("versions", []), f"versions {self.hello.get('versions')}")

    def c_anonymous(self):
        _, doc = self.get_json(self.api("/v1/"), "handshake", auth="none")
        self.hello_anon = doc
        expect(doc["account"]["state"] == "anonymous", f"account.state {doc['account']['state']!r}")
        expect(doc["uid"] == self.hello["uid"], "uid differs from the one with credentials")

    def c_account(self):
        if self.args.user is None:
            raise Skip("no credentials given")
        state = self.hello["account"]["state"]
        expect(state in ("active", "frozen"), f"account.state {state!r} although the credentials were accepted")
        return f"{state}, scopes {', '.join(self.hello['account']['scopes']) or 'none'}"

    def c_wrong(self):
        r = self.http.request("GET", self.api("/v1/apps?page_size=1"), auth="wrong")
        self.expect_problem(r, [401], {"unauthorized"})
        expect("basic" in (r.header("WWW-Authenticate") or "").lower(), f"{r}: no WWW-Authenticate: Basic")

    def c_wrong_handshake(self):
        self.expect_problem(self.http.request("GET", self.api("/v1/"), auth="wrong"), [401], {"unauthorized"})

    def c_bearer(self):
        self.expect_problem(self.http.request("GET", self.api("/v1/apps?page_size=1"), auth="bearer"),
                            [401], {"unauthorized"})

    def c_missing(self):
        anon = self.features(self.hello_anon)
        if self.args.user is None or anon["library"] or not self.features(self.hello)["library"]:
            raise Skip("not a private server, or no credentials given")
        r = self.http.request("GET", self.api("/v1/apps?page_size=1"), auth="none")
        self.expect_problem(r, [401], {"unauthorized"})

    def c_frozen(self):
        if self.hello["account"]["state"] != "frozen":
            raise Skip("the account is not frozen")
        on = [f for f, v in self.features(self.hello).items() if v]
        expect(not on, f"features still offered: {', '.join(on)}")
        r = self.http.request("GET", self.api("/v1/apps?page_size=1"))
        self.expect_problem(r, [403], {"account_frozen"})

    # Features (SPEC.md § 4.2): a family at 0 is refused, one above 0 answers.

    def title_id(self):
        return self.sample["title_id"] if self.sample else "0100ABCD00010000"

    def probe(self, family, auth):
        method, path, body, schema = PROBES[family]
        path = self.api(path.format(title_id=self.title_id()))
        return self.http.request(method, path, auth=auth, body=body), schema

    def c_feature(self, family, auth, level):
        r, schema = self.probe(family, auth)
        if not level:
            expect(r.status in (401, 403, 404), f"{r}: feature at 0, expected 401, 403 or 404")
            return f"{r.status}"
        if family == "media" and not self.sample and r.status == 404:
            return "no title to read (empty library)"
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

    def walk(self, path, size, method="GET", body=None):
        """Every item of a listing, a page at a time."""
        items, cursor, pages, total = [], None, 0, None
        sep = "&" if "?" in path else "?"
        while True:
            url = f"{path}{sep}page_size={size}" + (f"&cursor={quote(cursor, safe='')}" if cursor else "")
            r = self.http.request(method, url, body=body)
            expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
            doc = r.json()
            self.validate(doc, "apps", str(r))
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
        _, doc = self.get_json(self.api(f"/v1/apps?title_id={tid}&page_size={self.limit()}"), "apps")
        wrong = [a["id"] for a in doc["items"] if a["title_id"] != tid]
        expect(not wrong, f"title_id={tid} returned other titles: {', '.join(wrong[:5])}")
        for query in ("type=lantern", "sort=lantern", "title_id=0100abcd00010000"):
            self.expect_problem(self.http.request("GET", self.api(f"/v1/apps?{query}")), [400], {"bad_request"})

    def c_etag(self):
        r = self.http.request("GET", self.api("/v1/apps?page_size=1"))
        etag = r.header("ETag")
        if not etag:
            raise Warn(f"{r}: no ETag")
        again = self.http.request("GET", self.api("/v1/apps?page_size=1"), headers={"If-None-Match": etag})
        if again.status != 304:
            raise Warn(f"{again} with If-None-Match, expected 304")

    # What the console is missing (SPEC.md § 6.3), against the whole library.

    def library(self):
        if self.apps is None:
            raise Skip("the whole library could not be read (apps.pages.name)")
        return self.apps

    def missing(self, installed, want, size=None):
        body = {"schema": 1, "installed": installed, "want": want}
        items, _, _ = self.walk(self.api("/v1/apps/missing"), size or self.limit(), "POST", body)
        ids = [a["id"] for a in items]
        expect(len(ids) == len(set(ids)), "an app repeated across pages")
        return set(ids)

    def compare(self, got, expected, apps):
        name = {a["id"]: f"{a['name']} {a['app_id']} v{a['version']}" for a in apps}
        extra, lack = got - expected, expected - got
        expect(not extra and not lack, "; ".join(
            filter(None, [extra and "unexpected: " + ", ".join(name.get(i, i) for i in sorted(extra)[:5]),
                          lack and "missing: " + ", ".join(name.get(i, i) for i in sorted(lack)[:5])])))
        return f"{len(got)} app(s)"

    def installed_title(self, apps):
        bases = [a for a in apps if a["type"] == "base"]
        if not bases:
            raise Skip("no base game in the library")
        rich = [b for b in bases if any(a["title_id"] == b["title_id"] and a["type"] != "base" for a in apps)]
        return (rich or bases)[0]

    def c_missing_installed(self):
        apps = self.library()
        base = self.installed_title(apps)
        mine = [a for a in apps if a["title_id"] == base["title_id"]]
        updates = [a for a in mine if a["type"] == "update"]
        newest = max((a["version"] for a in updates), default=-1)
        expected = {a["id"] for a in updates if a["version"] == newest and newest > base["version"]}
        expected |= {a["id"] for a in mine if a["type"] == "dlc"}
        got = self.missing([{"app_id": base["app_id"], "version": base["version"]}], ["update", "dlc"],
                           size=1 if len(expected) > 1 else None)
        return f"{base['name']}: " + self.compare(got, expected, apps)

    def c_missing_current(self):
        apps = self.library()
        base = self.installed_title(apps)
        updates = [a for a in apps if a["title_id"] == base["title_id"] and a["type"] == "update"]
        installed = [{"app_id": base["app_id"], "version": base["version"]}]
        if updates:
            newest = max(updates, key=lambda a: a["version"])
            installed.append({"app_id": newest["app_id"], "version": newest["version"]})
        return self.compare(self.missing(installed, ["update"]), set(), apps)

    def c_missing_base(self):
        apps = self.library()
        expected = {a["id"] for a in apps if a["type"] == "base"}
        return self.compare(self.missing([], ["base"]), expected, apps)

    def c_malformed(self):
        r = self.http.request("POST", self.api("/v1/apps/missing"), body=b'{"schema": 1, "installed": [',
                              headers={"Content-Type": "application/json"})
        self.expect_problem(r, [400], {"bad_request"})

    def c_schema_2(self, family):
        path, doc = BODIES[family]
        doc = json.loads(json.dumps(doc).replace("{title_id}", self.title_id()))
        self.expect_problem(self.http.request("POST", self.api(path), body=doc), [422], {"unsupported_schema"})

    # Files (SPEC.md § 6.7).

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

    def download(self, app):
        r = self.http.request("GET", app["file"] if app["file"].startswith("/") else urlsplit(app["file"]).path,
                              limit=app["size"])
        return r

    def c_files(self):
        picked = self.chosen()
        if not picked:
            raise Skip(f"every file is above --max-download {self.args.max_download}")
        for app in picked:
            r = self.download(app)
            expect(r.status == 200, f"{r}, expected 200" + problem_detail(r))
            expect(not r.truncated and len(r.body) == app["size"], f"{r}: {len(r.body)} bytes, size says {app['size']}")
            expect(r.header("Content-Length") == str(app["size"]), f"{r}: Content-Length {r.header('Content-Length')}")
            expect((r.header("Accept-Ranges") or "").lower() == "bytes", f"{r}: no Accept-Ranges: bytes")
            etag = r.header("ETag") or ""
            expect(etag.startswith('"'), f"{r}: no strong ETag ({etag or 'none'})")
            digest = hashlib.sha256(r.body).hexdigest()
            if "sha256" in app:
                expect(digest == app["sha256"], f"{r}: sha256 {digest}, the app says {app['sha256']}")
            check_repr_digest(r, digest, required="sha256" in app)
            self.bytes[app["id"]] = r.body
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
        path = app["file"] if app["file"].startswith("/") else urlsplit(app["file"]).path
        for header, start, end in cases:
            r = self.http.request("GET", path, headers={"Range": header}, limit=size)
            expect(r.status == 206, f"{r} for {header}, expected 206" + problem_detail(r))
            expect(r.header("Content-Range") == f"bytes {start}-{end}/{size}",
                   f"{r} for {header}: Content-Range {r.header('Content-Range')}, expected bytes {start}-{end}/{size}")
            expect(r.header("Content-Length") == str(end - start + 1), f"{r} for {header}: Content-Length")
            expect(r.body == whole[start:end + 1], f"{r} for {header}: not the bytes of the whole file")
            check_repr_digest(r, hashlib.sha256(whole).hexdigest(), required=False)
        return f"{len(cases)} ranges of {app['name']} ({size} bytes)"

    def c_416(self):
        apps = self.apps or ([self.sample] if self.sample else [])
        if not apps:
            raise Skip("no app in the library")
        app = apps[0]
        path = app["file"] if app["file"].startswith("/") else urlsplit(app["file"]).path
        r = self.http.request("GET", path, headers={"Range": f"bytes={app['size']}-"}, limit=1 << 16)
        expect(r.status == 416, f"{r} for bytes={app['size']}-, expected 416")
        cr = r.header("Content-Range")
        if cr != f"bytes */{app['size']}":
            raise Warn(f"{r}: Content-Range {cr}, RFC 9110 asks for bytes */{app['size']}")

    def c_unknown_file(self):
        r = self.http.request("GET", self.api("/v1/files/f_lantern-conformance-" + secrets.token_hex(8)))
        self.expect_problem(r, [404, 410], {"not_found", "gone"})

    # Changes and titles (SPEC.md § 6.4, 6.6).

    def c_changes(self):
        _, doc = self.get_json(self.api("/v1/changes"), "changes")
        expect(doc["added"] == [] and doc["removed"] == [], "without since, apps were returned")
        _, later = self.get_json(self.api(f"/v1/changes?since={quote(doc['since'], safe='')}"), "changes")
        return f"{len(later['added'])} added, {len(later['removed'])} removed since the token"

    def c_bad_since(self):
        r = self.http.request("GET", self.api("/v1/changes?since=lantern-conformance-" + secrets.token_hex(6)))
        self.expect_problem(r, [400, 410], {"bad_request", "gone"})

    def c_title(self):
        if not self.sample:
            raise Skip("no app in the library")
        tid = self.sample["title_id"]
        _, doc = self.get_json(self.api(f"/v1/titles/{tid}"), "title")
        expect(doc["title_id"] == tid, f"title_id {doc['title_id']}, asked {tid}")
        media = doc.get("media", {})
        images = [media[k] for k in ("icon", "banner") if k in media] + list(media.get("screenshots", []))
        for img in images:
            url = urlsplit(img["url"])
            if img.get("external"):
                expect(url.scheme in ("http", "https"), f"external media {img['url']} is not an absolute URL")
            else:
                expect(not url.netloc or url.netloc == self.origin.netloc,
                       f"media {img['url']} is elsewhere but not marked external")
        return f"{doc['name']}, {len(images)} image(s)"

    def c_unknown_title(self):
        known = {a["title_id"] for a in (self.apps or [])}
        tid = next(t for t in (f"05{secrets.token_hex(7).upper()}" for _ in range(100)) if t not in known)
        self.expect_problem(self.http.request("GET", self.api(f"/v1/titles/{tid}")), [404], {"not_found"})

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
            sock.sendto(b"OWNFOIL_DISCOVER", (self.args.discover, self.args.discover_port))
            data, peer = sock.recvfrom(65536)
        except TimeoutError:
            raise Fail(f"no reply from {self.args.discover}:{self.args.discover_port} in 3 s") from None
        finally:
            sock.close()
        try:
            doc = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise Fail(f"the reply is not JSON: {e}") from None
        self.validate(doc, "discovery", f"reply from {peer[0]}")
        expect(doc["uid"] == self.hello["uid"], "uid differs from the handshake's")
        lantern = doc.get("lantern")
        expect(lantern is not None, "no lantern part: the server does not say it speaks Lantern")
        expect(lantern["base"] == self.base and 1 in lantern["versions"], f"lantern {lantern}")
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
               if r.status == 401 and "basic" not in (r.header("WWW-Authenticate") or "").lower()]
        expect(not bad, "\n".join(bad[:8]))

    def json_documents(self):
        for r in self.http.log:
            if r.is_json and r.body and r.method != "HEAD":
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
               if 200 <= r.status < 300 and r.method != "HEAD" and not r.path.startswith(self.api("/v1/files/"))
               and r.ctype != "application/json"]
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
            if r.auth == "user" and self.args.user is not None and 200 <= r.status < 300:
                cc, vary = (r.header("Cache-Control") or "").lower(), (r.header("Vary") or "").lower()
                if "private" not in cc and "no-store" not in cc:
                    bad.append(f"{r}: Cache-Control {cc or 'none'}")
                elif "authorization" not in vary and "*" not in vary:
                    bad.append(f"{r}: Vary {vary or 'none'}")
        if self.args.user is None:
            raise Skip("no credentials given")
        if bad:
            raise Warn("\n".join(bad[:8]))


def client_rule():
    raise Skip("a client rule, not visible from outside")


def problem_detail(r):
    if r.is_json and r.status >= 400:
        try:
            d = r.json()
            return f" ({d.get('code')}: {d.get('detail') or d.get('title')})"
        except Fail:
            pass
    return ""


def check_repr_digest(r, digest, required):
    header = r.header("Repr-Digest")
    if not header:
        expect(not required, f"{r}: no Repr-Digest although the hash is known")
        return
    values = dict(part.strip().split("=", 1) for part in header.split(",") if "=" in part)
    value = values.get("sha-256", "").strip()
    expect(value.startswith(":") and value.endswith(":"), f"{r}: Repr-Digest {header!r} has no sha-256")
    try:
        got = base64.b64decode(value[1:-1], validate=True).hex()
    except ValueError:
        raise Fail(f"{r}: Repr-Digest sha-256 is not base64") from None
    expect(got == digest, f"{r}: Repr-Digest {got}, the bytes hash to {digest}")


def limit_problems(doc):
    """SPEC.md § 11, over one document."""
    out = []

    def walk(value, depth, key):
        if isinstance(value, (dict, list)):
            if depth > 16:
                out.append(f"nested deeper than 16 at {key}")
                return
            if isinstance(value, list):
                if key == "items" and len(value) > 1000:
                    out.append(f"{len(value)} items on a page")
                for v in value:
                    walk(v, depth + 1, key)
            else:
                for k, v in value.items():
                    walk(v, depth + 1, k)
        elif isinstance(value, str):
            cap = {"name": 512, "note": 120}.get(key, 4096)
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
    p.add_argument("--user", help="an account's name (HTTP Basic)")
    p.add_argument("--password", help="its password")
    p.add_argument("--base", help="the base path, when the handshake should not decide it")
    p.add_argument("--cafile", help="CA certificates to trust (PEM)")
    p.add_argument("--insecure", action="store_true", help="do not verify the certificate (a LAN server)")
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--max-items", type=int, default=20000, help="read every page up to this many apps")
    p.add_argument("--max-download", type=int, default=64 << 20, help="bytes downloaded at most (default 64 MiB)")
    p.add_argument("--max-files", type=int, default=3, help="files downloaded whole at most")
    p.add_argument("--discover", metavar="ADDRESS", help="also send LAN discovery to this address")
    p.add_argument("--discover-port", type=int, default=8465)
    p.add_argument("--schemas", default=str(Path(__file__).resolve().parent.parent / "schemas" / "v1"))
    p.add_argument("--no-schemas", action="store_true", help="skip the JSON Schema checks")
    args = p.parse_args(argv)
    if (args.user is None) != (args.password is None):
        p.error("--user and --password go together")
    suite = Suite(args)
    if out is not None:
        suite.out = out
    return suite.run()


if __name__ == "__main__":
    sys.exit(main())
