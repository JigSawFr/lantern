"""The conformance suite's checks of what draft 0.6 settles (SPEC.md § 2.3
and § 2.4, the values and routes of the core; § 4.3, § 6.3, § 6.6 and § 14's
edge cases; § 11's states, with run.py's admin.requests) and of what it adds
to the suite: the bytes of the mirrors (--fetch-mirrors, § 19.2), a peer's
slots of downloads (§ 19.4), the rate of discovery replies (§ 4.1), the
images' cache lifetime (§ 7.1) and the tokens' length (§ 5.1). A mixin of
run.py's Suite, which gives it http, hello, validate(), expect_problem() and
the rest, as checks_v05.py is.
"""
import hashlib
import http.client
import json
import re
import select
import socket
import ssl
import time
import unicodedata
from urllib.parse import quote, urljoin, urlsplit

import lantern_client as client

# run.py's own (bind() sets them).
Fail = Skip = Blind = Warn = problem_detail = None

INT_LIMIT = (1 << 53) - 1
TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_KEYS = ("created", "updated", "added", "expires", "generated")
B64TOKEN = re.compile(r"^[A-Za-z0-9._~+/-]+=*$")     # RFC 6750 § 2.1
TOKEN_CHARS = 22        # 128 bits in RFC 6750's 66 symbols need 22 of them at least (SPEC.md § 5.1)
HOLD = 8 << 20          # a file larger than a socket's buffers hold, so that its download holds a peer's slot


def expect(cond, msg):
    if not cond:
        raise Fail(msg)


def bind(**names):
    globals().update(names)


def fold(text):
    """SPEC.md § 2.3's canonical caseless match."""
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", text).casefold())


def i_json_problem(body):
    """Why the bytes `body` are not an I-JSON document (RFC 7493; SPEC.md § 2.3), or None."""
    if body.startswith(b"\xef\xbb\xbf"):
        return "a byte order mark"

    def pairs(items):
        names = [k for k, _ in items]
        if len(set(names)) != len(names):
            raise ValueError(f"the member name {next(n for n in names if names.count(n) > 1)!r} twice")
        return dict(items)
    try:
        doc = json.loads(body.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, ValueError) as e:
        return str(e)[:120]
    stack = [doc]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            stack += list(x.keys()) + list(x.values())
        elif isinstance(x, list):
            stack += x
        elif isinstance(x, bool):
            continue
        elif isinstance(x, int) and not -INT_LIMIT <= x <= INT_LIMIT:
            return f"the integer {x}, beyond 2^53 - 1"
        elif isinstance(x, float) and x.is_integer() and abs(x) > INT_LIMIT:
            return f"the number {x}, beyond 2^53 - 1"
        elif isinstance(x, str) and any(0xD800 <= ord(c) <= 0xDFFF for c in x):
            return "an unpaired surrogate"
    return None


def strings(doc, path="$"):
    """(path, key, value) of every string of a document, keys included."""
    if isinstance(doc, dict):
        for k, v in doc.items():
            yield f"{path}.{k}", k, k
            if isinstance(v, str):
                yield f"{path}.{k}", k, v
            else:
                yield from strings(v, f"{path}.{k}")
    elif isinstance(doc, list):
        for i, v in enumerate(doc):
            if isinstance(v, str):
                yield f"{path}[{i}]", None, v
            else:
                yield from strings(v, f"{path}[{i}]")


class Sweep:
    """The checks of SPEC.md § 2.3, § 2.4 and 0.6's other edge cases."""

    # Values (SPEC.md § 2.3).

    def json_route(self):
        """(path, a document it takes, platform) of a route that reads a JSON document and writes nothing: what
        is missing, or homebrew's updates; None when the caller has neither."""
        mine = self.features(self.hello)
        platform = self.sample_platform() if mine["library"] or mine["homebrew"] else None
        if mine["library"]:
            return self.api("/v1/apps/missing"), {"schema": 1, "installed": [], "want": ["base"]}, platform
        if mine["homebrew"]:
            return self.api("/v1/homebrew/updates"), {"schema": 1, "installed": []}, platform
        return None

    def c_i_json_refused(self):
        found = self.json_route()
        if found is None:
            raise Skip("no route that reads a document and writes nothing (library or homebrew)")
        path, doc, platform = found
        good = json.dumps(doc).encode()
        r = self.http.request("POST", path, body=good, headers={"Content-Type": "application/json"},
                              platform=platform)
        expect(r.status == 200, f"{r}: the document itself, expected 200" + problem_detail(r))
        cases = {"a member name twice": good[:-1] + b', "schema": 1}',
                 "an integer beyond 2^53 - 1": good[:-1] + b', "x-lantern-conformance": 9007199254740993}',
                 "a byte order mark": b"\xef\xbb\xbf" + good,
                 "an unpaired surrogate": good[:-1] + b', "x-lantern-conformance": "\\ud800"}'}
        for why, body in cases.items():
            r = self.http.request("POST", path, body=body, headers={"Content-Type": "application/json"},
                                  platform=platform)
            expect(r.status == 400, f"{r}: a document with {why}, expected 400" + problem_detail(r))
        return f"{len(cases)} documents that are not I-JSON: 400"

    def g_i_json(self):
        bad = []
        for r in self.http.log:
            if r.is_json and r.body and r.method != "HEAD" and not r.raw and not r.unreadable and not r.truncated:
                why = i_json_problem(r.body)
                if why:
                    bad.append(f"{r}: {why}")
        expect(not bad, "\n".join(bad[:8]))

    def g_times(self):
        bad = []
        for r, doc in self.json_documents():
            for where, key, value in strings(doc):
                if key in TIME_KEYS and value != key and not TIME.match(value):
                    bad.append(f"{r}: {where} {value!r}, not a time in UTC with Z")
                elif key == "release" and value != key and not DATE.match(value):
                    bad.append(f"{r}: {where} {value!r}, not a date")
        expect(not bad, "\n".join(bad[:8]))

    def g_nfc(self):
        bad = [f"{r}: {where}" for r, doc in self.json_documents() for where, _, value in strings(doc)
               if not unicodedata.is_normalized("NFC", value)]
        if bad:
            raise Warn("text not in NFC:\n" + "\n".join(bad[:8]))

    def c_hex_case(self):
        if not self.features(self.hello)["peers"]:
            raise Skip("no route of this caller takes a SHA-256 in its path (peers)")
        files = self.files_of_library()
        if not files:
            raise Skip("no file in the library")
        sha = files[0][0]
        r = self.http.request("GET", self.api(f"/v1/grants/sha256/{sha.upper()}"))
        self.expect_problem(r, [404], {"not_found"})
        return f"{sha[:12]}… in upper case: 404"

    def c_apps_search(self):
        apps = [a for a in self.library() if any(c.isalpha() for c in a.get("name", ""))]
        if not apps:
            raise Skip("no app with a name of letters")
        app = max(apps, key=lambda a: sum(not c.isascii() for c in a["name"]))
        name = app["name"]
        word = max(name.split(), key=len)
        done = []
        for q in (word.upper(), unicodedata.normalize("NFD", word.swapcase())):
            items, _, _ = self.walk(self.api(f"/v1/apps?q={quote(q, safe='')}"), self.limit(),
                                    platform=app["platform"])
            expect(app["id"] in {a["id"] for a in items}, f"q={q!r}: {name!r} is not among {len(items)} app(s)")
            wrong = [a["name"] for a in items if fold(q) not in fold(a["name"])]
            expect(not wrong, f"q={q!r} keeps apps whose name does not hold it: {wrong[:3]}")
            done.append(q)
        return f"{name!r} found by " + " and ".join(repr(q) for q in done)

    def c_apps_empty(self):
        platform, tid = self.own_title(self.sample_platform())
        r, doc = self.get_json(self.api(f"/v1/apps?title_id={quote(tid, safe='')}"), "apps", platform=platform)
        expect(doc["items"] == [] and doc["next"] is None and doc.get("total", 0) == 0,
               f"{r}: a listing of nothing, expected items [], next null and total 0")
        return f"title_id {tid}: an empty page"

    # Routes and queries (SPEC.md § 2.4).

    def c_routes(self):
        r = self.http.request("GET", self.api("/v1/apps/"))
        self.expect_problem(r, [404], {"not_found"})
        r = self.http.request("GET", self.api("/v1"))
        expect(r.status == 200, f"{r}, expected the handshake" + problem_detail(r))
        expect(r.json().get("uid") == self.hello["uid"], f"{r}: another uid than the handshake's")
        return "<base>/v1/apps/ 404; <base>/v1 the handshake"

    def g_no_redirect(self):
        bad = [f"{r}: {r.header('Location')}" for r in self.http.log if 300 <= r.status < 400 and r.status != 304]
        expect(not bad, "\n".join(bad[:8]))

    def c_query_twice(self):
        r = self.http.request("GET", self.api("/v1/apps?sort=name&sort=added"))
        self.expect_problem(r, [400], {"bad_request"})
        return "sort given twice: 400"

    def c_query_lenient(self):
        size = self.limit()
        _, plain = self.get_json(self.api(f"/v1/apps?page_size={size}"), "apps")
        for query in ("platform=&type=&title_id=&q=&sort=&cursor=", "x-lantern-conformance=1"):
            r, doc = self.get_json(self.api(f"/v1/apps?{query}&page_size={size}"), "apps")
            expect([a["id"] for a in doc["items"]] == [a["id"] for a in plain["items"]],
                   f"{r}: not the page asked without them")
        return "empty values read as absent, an unknown parameter ignored"

    def head_routes(self):
        mine, out = self.features(self.hello), [self.api("/v1/")]
        if mine["library"]:
            out.append(self.api("/v1/apps?page_size=1"))
            if self.sample:
                out.append(self.file_path(self.sample["file"]))
        if mine["changes"]:
            out.append(self.api("/v1/changes"))
        if mine["titles"] and self.sample:
            out.append(self.api(f"/v1/titles?ids={quote(self.sample['title_id'], safe='')}"))
        if mine["homebrew"]:
            out.append(self.api("/v1/homebrew?page_size=1"))
        for family, path in (("cheats", "/v1/cheats"), ("requests", "/v1/requests"), ("saves", "/v1/saves"),
                             ("sync", "/v1/sync"), ("admin", "/v1/admin/users?page_size=1")):
            if mine[family]:
                out.append(self.api(path))
        out.append(self.api("/v1/lantern-conformance-no-such-route"))
        return out

    def c_head(self):
        done = []
        for path in self.head_routes():
            raw = "/v1/files/" in path
            get = self.http.request("GET", path, raw=raw, limit=1 if raw else 32 << 20)
            head = self.http.request("HEAD", path, raw=raw)
            expect(head.status == get.status, f"{head}: GET gave {get.status}")
            expect(not head.body, f"{head}: a body")
            for name in ("Content-Type", "ETag", "Repr-Digest"):
                if get.header(name) is not None and get.status == 200:
                    expect(head.header(name) == get.header(name),
                           f"{head}: {name} {head.header(name)!r}, GET's {get.header(name)!r}")
            done.append(f"{urlsplit(path).path.removeprefix(self.base.rstrip('/'))} {head.status}")
        return ", ".join(done)

    def c_content_type(self):
        found = self.json_route()
        if found is None:
            raise Skip("no route that reads a document and writes nothing (library or homebrew)")
        path, doc, platform = found
        r = self.http.request("POST", path, body=json.dumps(doc).encode(), headers={"Content-Type": "text/plain"},
                              platform=platform)
        self.expect_problem(r, [400], {"bad_request"})
        return "a document sent as text/plain: 400"

    # Edge cases of § 4.3, § 6.3, § 6.6 and § 14.

    def c_ambiguous(self):
        by_id = {}
        for e in self.homebrew or []:
            by_id.setdefault(e["id"], set()).add(e["platform"])
        both = sorted(i for i, p in by_id.items() if len(p) > 1)
        if not both:
            raise Skip("no homebrew id on two platforms")
        hid = both[0]
        r = self.http.request("GET", self.api(f"/v1/homebrew/{quote(hid, safe='')}"))
        self.expect_problem(r, [400], {"bad_request"})
        platform = min(by_id[hid])
        r = self.http.request("GET", self.api(f"/v1/homebrew/{quote(hid, safe='')}"), platform=platform)
        expect(r.status == 200, f"{r}: with its platform, expected 200" + problem_detail(r))
        return f"{hid}, on {', '.join(sorted(by_id[hid]))}: 400 without a platform, 200 with one"

    def c_missing_want(self):
        platform = self.sample_platform()
        path = self.api("/v1/apps/missing")
        for want in ([], ["base", "patch"]):
            r = self.http.request("POST", path, body={"schema": 1, "installed": [], "want": want}, platform=platform)
            self.expect_problem(r, [400], {"bad_request"})
        size = self.limit()
        plain, _, _ = self.walk(path, size, "POST", {"schema": 1, "installed": [], "want": ["base"]},
                                platform=platform)
        unknown = {"app_id": self.own_title(platform)[1], "version_code": 1}
        other, _, _ = self.walk(path, size, "POST", {"schema": 1, "installed": [unknown], "want": ["base"]},
                                platform=platform)
        expect({a["id"] for a in other} == {a["id"] for a in plain},
               "an installed app_id the server does not know changed what is missing")
        return f"want [] and an unknown type: 400; an unknown installed app ignored ({len(plain)} base game(s))"

    def c_if_range(self):
        app = next((a for a in self.chosen() if a["size"] >= 4 and a["id"] in self.bytes), None)
        if app is None:
            raise Skip("no file of 4 bytes or more read whole (files.whole)")
        whole, path = self.bytes[app["id"]], self.file_path(app["file"])
        tag = self.http.request("HEAD", path, raw=True).header("ETag")
        if not tag:
            raise Fail(f"HEAD {path}: no ETag")
        r = self.http.request("GET", path, raw=True, limit=len(whole), headers={"Range": "bytes=1-", "If-Range": tag})
        expect(r.status == 206 and r.body == whole[1:], f"{r}: If-Range of its ETag, expected 206 and the rest")
        r = self.http.request("GET", path, raw=True, limit=len(whole),
                              headers={"Range": "bytes=1-", "If-Range": '"lantern-conformance"'})
        expect(r.status == 200 and r.body == whole, f"{r}: If-Range of another ETag, expected 200 and the whole file")
        r = self.http.request("GET", path, raw=True, limit=len(whole), headers={"Range": "bytes=0-0,2-2"})
        expect(r.status in (200, 206) and not r.ctype.startswith("multipart/"),
               f"{r}: two ranges, expected the whole file or one range, never multipart ({r.ctype})")
        expect(r.status != 200 or r.body == whole, f"{r}: 200, but not the whole file")
        return f"If-Range kept or dropped the range; two ranges gave {r.status}"

    def c_not_modified(self):
        path = self.api("/v1/apps?page_size=1")
        r = self.http.request("GET", path)
        tag = r.header("ETag")
        if not tag:
            raise Skip(f"{r}: no ETag (caching.etag warns)")
        for given in (f"W/{tag}" if not tag.startswith("W/") else tag, '"lantern-conformance", ' + tag, "*"):
            again = self.http.request("GET", path, headers={"If-None-Match": given})
            expect(again.status == 304 and not again.body, f"{again}: If-None-Match {given}, expected 304, no body")
            for name in ("ETag", "Vary", "Cache-Control"):
                expect(again.header(name) == r.header(name),
                       f"{again}: {name} {again.header(name)!r}, the 200's {r.header(name)!r}")
        other = self.http.request("GET", path, headers={"If-None-Match": '"lantern-conformance"'})
        expect(other.status == 200, f"{other}: another ETag, expected 200")
        tags = {tag}
        if r.json().get("next"):
            nxt = self.http.request("GET", path + f"&cursor={quote(r.json()['next'], safe='')}")
            expect(nxt.status == 200 and nxt.header("ETag") not in tags, f"{nxt}: the next page has the same ETag")
            tags.add(nxt.header("ETag"))
        platforms = self.platforms()
        if len(platforms) > 1:
            first = [self.http.request("GET", path, platform=p) for p in platforms[:2]]
            if first[0].json()["items"] != first[1].json()["items"]:
                expect(first[0].header("ETag") != first[1].header("ETag"),
                       f"{first[1]}: another platform's page, the same ETag")
        return f"304 with the 200's headers, weakly or *; {len(tags)} page(s), each its tag"

    # Tokens (SPEC.md § 5.1), the images (§ 7.1), discovery's rate (§ 4.1).

    def g_tokens(self):
        tokens = list(getattr(self, "tokens_seen", []))
        if self.args.token:
            tokens.append(self.args.token)
        if not tokens:
            raise Skip("no token given or got")
        bad = [f"{t[:4]}… ({len(t)} characters)" for t in tokens if len(t) < TOKEN_CHARS or not B64TOKEN.match(t)]
        expect(not bad, f"tokens too short for 128 bits, or not of RFC 6750's characters: {', '.join(bad[:4])}")
        expect(len(set(tokens)) == len(tokens), "the same token given twice")
        return f"{len(tokens)} token(s) of {min(map(len, tokens))} characters or more"

    def c_images(self):
        images = []
        for t in getattr(self, "titles_read", []):
            for key in ("icon", "banner"):
                if isinstance(t.get(key), dict) and not t[key].get("external"):
                    images.append(t[key]["url"])
            images += [s["url"] for s in t.get("screenshots", []) if isinstance(s, dict) and not s.get("external")]
        images = list(dict.fromkeys(i for i in images if isinstance(i, str)))[:3]
        if not images:
            raise Skip("no image on the server's origin among the titles read")
        bad = []
        for url in images:
            r = self.http.request("GET", self.file_path(url), raw=True, limit=4 << 20)
            if r.status != 200:
                bad.append(f"{r}")
                continue
            cc = (r.header("Cache-Control") or "").lower()
            age = re.search(r"max-age=(\d+)", cc)
            if "immutable" not in cc and not (age and int(age.group(1)) >= 86400):
                bad.append(f"{r}: Cache-Control {cc or 'none'}, not a long lifetime")
        if bad:
            raise Warn("\n".join(bad))
        return f"{len(images)} image(s), each with a long cache lifetime"

    def c_discovery_rate(self):
        if not self.args.discover:
            raise Skip("no --discover address given")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        replies, start = [], time.monotonic()
        try:
            for _ in range(30):
                sock.sendto(json.dumps({"schema": 1, "lantern": "discover"}).encode(),
                            (self.args.discover, self.args.discover_port))
            while time.monotonic() < start + 1.0:
                ready, _, _ = select.select([sock], [], [], max(0.0, start + 1.0 - time.monotonic()))
                if not ready:
                    break
                data, _ = sock.recvfrom(65536)
                if b'"server"' in data:
                    replies.append(data)
        finally:
            sock.close()
        if not replies:
            raise Warn("no reply to 30 datagrams")
        if len(replies) > 10:
            raise Warn(f"{len(replies)} replies within a second to one address: 10 at most")
        return f"{len(replies)} replies to 30 datagrams sent at once"

    # Mirrors (SPEC.md § 19.2), with --fetch-mirrors.

    def fetch_mirror(self, url, size, hops=3):
        """(status, bytes, why) of a mirror read whole, sending nothing of the server's: no token, signature or
        cookie (SPEC.md § 19.1); a redirect followed to another mirror's address, 3 at most."""
        u = urlsplit(url)
        kw = {}
        if u.scheme == "https":
            kw["context"] = ssl.create_default_context(cafile=self.args.cafile)
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        conn = cls(u.hostname, u.port, timeout=min(self.args.timeout, 10), **kw)
        try:
            conn.request("GET", (u.path or "/") + (f"?{u.query}" if u.query else ""),
                         headers={"User-Agent": f"LanternConformance/{self.version}"})
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308) and hops and r.getheader("Location"):
                target = urljoin(url, r.getheader("Location"))
                if not client.mirror_ok(target):
                    return r.status, b"", f"a redirect to {target}, not a mirror's address"
                return self.fetch_mirror(target, size, hops - 1)
            return r.status, r.read(size + 1) if r.status == 200 else b"", None
        finally:
            conn.close()

    def c_mirrors_fetch(self):
        if not self.args.fetch_mirrors:
            raise Skip("no --fetch-mirrors given")
        files = [(a["sha256"], a["size"], a.get("mirrors", []), f"app {a['id']}") for a in self.apps or []]
        files += [(p["sha256"], p["size"], p.get("mirrors", []), f"homebrew {e['platform']}/{e['id']}")
                  for e in self.homebrew or [] for p in [e["package"], *e.get("packages", [])]]
        mirrors = [(sha, size, m["url"], where) for sha, size, ms, where in files for m in ms
                   if isinstance(m, dict) and client.mirror_ok(m.get("url"))]
        if not mirrors:
            raise Skip("no mirror in the library read")
        read, unreachable, budget = 0, [], self.args.max_download
        for sha, size, url, where in mirrors:
            if size > budget:
                continue
            try:
                status, data, why = self.fetch_mirror(url, size)
            except (OSError, http.client.HTTPException) as e:
                unreachable.append(f"{url}: {e}")
                continue
            expect(why is None, f"{where}: mirror {url}: {why}")
            expect(status == 200, f"{where}: mirror {url} answers {status}, not the file")
            expect(len(data) == size, f"{where}: mirror {url} gives {len(data)} bytes, the file is {size}")
            expect(hashlib.sha256(data).hexdigest() == sha, f"{where}: mirror {url} gives other bytes than {sha[:12]}…")
            read += 1
            budget -= size
        if not read:
            raise Skip(f"no mirror reachable from here or within --max-download: {'; '.join(unreachable[:3])}")
        return f"{read} mirror(s) read whole, their size and SHA-256 those of the file; no credential sent" + (
            f"; {len(unreachable)} unreachable from here" if unreachable else "")

    # A peer's slots (SPEC.md § 19.4), with --peer.

    def c_peer_slots(self):
        self.peer_client()
        slots = getattr(self, "peer_slots", None)
        if not slots:
            raise Skip("the peer's slots are unknown (peer.discovery)")
        files = sorted((f for f in self.files_of_library() if f[1] >= HOLD), key=lambda f: f[1])
        if not files:
            raise Skip(f"no file of {HOLD >> 20} MiB or more, whose download holds a slot long enough")
        sha, size, _ = files[0]
        g = self.grant_for(sha)
        expect(g.status == 200, f"{g}: a grant, expected 200" + problem_detail(g))
        grant = g.json()["grant"]
        u = urlsplit(self.args.peer)
        held = []
        time.sleep(1.1)     # out of the peer's window of requests per second, which would answer 429 too
        try:
            for i in range(slots + 1):
                sock = socket.create_connection((u.hostname, u.port or 80), timeout=10)
                if u.scheme == "https":
                    ctx = ssl.create_default_context()
                    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
                    sock = ctx.wrap_socket(sock, server_hostname=u.hostname)
                held.append(sock)
                sock.sendall((f"GET {self.peer_path(sha)} HTTP/1.1\r\nHost: {u.netloc}\r\n"
                              f"User-Agent: LanternConformance/{self.version}\r\nLantern-Grant: {grant}\r\n\r\n").encode())
                head = b""
                while b"\r\n\r\n" not in head and len(head) < 65536:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    head += chunk
                status = int(head.split(b" ", 2)[1]) if head.startswith(b"HTTP/") else 0
                if i < slots:
                    expect(status == 200, f"download {i + 1} of {slots}: {status}, expected 200")
                else:
                    expect(status == 429, f"download {slots + 1}, beyond slots {slots}: {status}, expected 429")
                    expect(re.search(rb"(?im)^retry-after:\s*\d+", head), "a 429 without Retry-After")
        finally:
            for sock in held:
                try:
                    sock.close()
                except OSError:
                    pass
        time.sleep(0.5)     # the peer sees them closed, and frees its slots
        return f"{slots} download(s) of {size >> 20} MiB at once, then 429"
