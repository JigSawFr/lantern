"""The conformance suite's checks of what draft 0.7 adds: differential
updates (SPEC.md § 22: chunk indexes, their route, the chunks they name and
a newer version put together from an older one, as a client does), the
answers to a browser's page (§ 2.5, with --origin: preflights, the headers
of every answer; always: no credential in a cookie), the `web` platform
(Annex A.7), a pairing's poll after a slow_down (§ 5.2), and, with
--static, a static library's chunk indexes and its answers to a page
(§ 21). A mixin of run.py's Suite, which gives it http, hello, validate(),
expect_problem() and the rest, as checks_v05.py and checks_v06.py are.
"""
import hashlib
import secrets
import time

import lantern_client as client

# run.py's own (bind() sets them).
Fail = Skip = Blind = Warn = problem_detail = None

# SPEC.md § 2.5: what a preflight asks for, and what a page reads of an answer.
ASKED = ("Authorization", "Content-Type", "Content-Digest", "Signature", "Signature-Input", "Accept-Schema",
         "Lantern-Platform")
EXPOSED = ("Date", "ETag", "Content-Range", "Accept-Ranges", "Repr-Digest", "Retry-After", "WWW-Authenticate",
           "Accept-Signature", "Upload-Offset", "Upload-Length", "Lantern-Chunk-Size", "Allow", "Deprecation", "Sunset", "Link")
OTHER_ORIGIN = "https://lantern-conformance.invalid"
RANGES_PER_FILE = 8         # chunks read by their ranges, per file at most


def expect(cond, msg):
    if not cond:
        raise Fail(msg)


def bind(**names):
    globals().update(names)


def names(header):
    return {h.strip().lower() for h in (header or "").split(",") if h.strip()}


class Seven:
    """Draft 0.7's checks."""

    # Differential updates (SPEC.md § 22).

    def chunked(self):
        """[(where, document, platform)] of the apps and homebrew packages read that carry chunks."""
        out = []
        for a in self.apps or ([self.sample] if self.sample else []):
            if isinstance(a.get("chunks"), dict):
                out.append((f"app {a['id']}", a, a.get("platform")))
        for e in (self.homebrew or []):
            for p in [e.get("package") or {}, *(e.get("packages") or [])]:
                if isinstance(p.get("chunks"), dict):
                    out.append((f"homebrew {e.get('platform')}/{e.get('id')}", p, e.get("platform")))
        return out

    def index_bytes(self, where, doc, platform):
        """The bytes of a file's index, read at its chunks.url (SPEC.md § 22.1), and the index, checked as a client
        checks it before it uses it (§ 22.3)."""
        ref = doc["chunks"]
        r = self.http.request("GET", self.file_path(ref["url"]), platform=platform, limit=client.INDEX_LIMIT)
        expect(r.status == 200, f"{where}: {r}, expected 200" + problem_detail(r))
        raw = r.body
        expect(len(raw) == ref["size"] and hashlib.sha256(raw).hexdigest() == ref["sha256"],
               f"{where}: the index's bytes are not of the size and SHA-256 its chunks gives")
        try:
            index = client.read_chunk_index(raw, ref, doc["sha256"], doc["size"])
        except client.Unusable as e:
            raise Fail(f"{where}: an index a client cannot use: {e}") from None
        self.validate(index, "chunk-index", where)
        expect(client.canonical(index) == raw, f"{where}: its index is not written in canonical JSON (§ 2.3)")
        return raw, index

    def c_feature_deltas(self, auth, level):
        sample = self.sample if self.sample and isinstance(self.sample.get("chunks"), dict) else None
        sha = (self.sample or {}).get("sha256") or "0" * 64
        r = self.http.request("GET", self.api(f"/v1/chunks/sha256/{sha}"), auth=auth)
        if not level:
            expect(r.status in (401, 403, 404), f"{r}: feature at 0, expected 401, 403 or 404")
            return f"{r.status}"
        if sample is None:
            expect(r.status == 404, f"{r}: an app without chunks, expected 404" + problem_detail(r))
            return "the first page's app has no chunks: 404"
        expect(r.status == 200, f"{r}: feature at {level}, expected 200" + problem_detail(r))
        self.validate(r.json(), "chunk-index", str(r))

    def c_deltas_index(self):
        files = self.chunked()
        if not files:
            raise Skip("no app or homebrew package read carries chunks")
        sizes = set()
        for where, doc, platform in files:
            _, index = self.index_bytes(where, doc, platform)
            sizes.add(index["chunker"]["size"])
        return f"{len(files)} index(es), chunkers of {', '.join(str(s) for s in sorted(sizes))} bytes"

    def c_deltas_cut(self):
        files = sorted(self.chunked(), key=lambda f: f[1]["size"])
        if not files:
            raise Skip("no app or homebrew package read carries chunks")
        budget, done, ranges = self.args.max_download, 0, 0
        for where, doc, platform in files:
            if doc["size"] > budget or done >= self.args.max_files:
                break
            raw, index = self.index_bytes(where, doc, platform)
            data = self.fetch(doc["file"], doc["size"], doc["sha256"], platform)
            budget -= doc["size"]
            done += 1
            _, mine = client.chunk_index(data, index["chunker"]["size"])
            expect(mine == raw, f"{where}: not cut as lantern-cdc-1 cuts it (§ 22.2): a client's seeds would not match")
            offset = 0
            for n, (length, digest) in enumerate(index["chunks"]):
                if n < RANGES_PER_FILE:
                    r = self.http.request("GET", self.file_path(doc["file"]), platform=platform, raw=True,
                                          limit=length, headers={"Range": f"bytes={offset}-{offset + length - 1}"})
                    expect(r.status == 206 and hashlib.sha256(r.body).hexdigest() == digest,
                           f"{where}: {r}, the range of chunk {n} is not its bytes")
                    ranges += 1
                offset += length
        if not done:
            raise Skip(f"every file with chunks is above --max-download {self.args.max_download}")
        return f"{done} file(s) cut again and compared, {ranges} chunk(s) read by their ranges"

    def c_deltas_route(self):
        files = self.chunked()
        if not files:
            raise Skip("no app or homebrew package read carries chunks")
        for where, doc, platform in files[:4]:
            raw, _ = self.index_bytes(where, doc, platform)
            r = self.http.request("GET", self.api(f"/v1/chunks/sha256/{doc['sha256']}"), platform=platform,
                                  limit=client.INDEX_LIMIT)
            expect(r.status == 200 and r.body == raw, f"{where}: {r}, not the index its chunks names"
                   + problem_detail(r))
        r = self.http.request("GET", self.api(f"/v1/chunks/sha256/{secrets.token_hex(32)}"))
        self.expect_problem(r, [404], {"not_found"})
        r = self.http.request("GET", self.api(f"/v1/chunks/sha256/{files[0][1]['sha256'].upper()}"))
        expect(r.status == 404, f"{r}: a SHA-256 in upper case, expected 404 (§ 2.3)")
        return f"{min(len(files), 4)} index(es) by their file's SHA-256; an unknown one 404"

    def c_deltas_update(self):
        """A newer version put together from an older one, as a client does (§ 22.3)."""
        apps = [(w, d, p) for w, d, p in self.chunked() if w.startswith("app ")]
        by_app = {}
        for w, d, p in apps:
            by_app.setdefault((p, d.get("app_id")), []).append(d)
        pairs = [sorted(v, key=lambda d: d["version_code"])[-2:] for v in by_app.values() if len(v) >= 2]
        pairs = [(old, new) for old, new in pairs if old["size"] + new["size"] <= self.args.max_download]
        if not pairs:
            raise Skip("no two versions of one app with chunks, within --max-download")
        old, new = pairs[0]
        platform = new["platform"]
        seed = self.fetch(old["file"], old["size"], old["sha256"], platform)
        _, index = self.index_bytes(f"app {new['id']}", new, platform)
        read = []

        def read_range(start, end):
            r = self.http.request("GET", self.file_path(new["file"]), platform=platform, raw=True,
                                  limit=end - start + 1, headers={"Range": f"bytes={start}-{end}"})
            expect(r.status == 206, f"{r}, expected 206 for bytes={start}-{end}")
            read.append(len(r.body))
            return r.body
        try:
            data = client.assemble(index, [seed], read_range, new["sha256"], new["size"])
        except client.Refused as e:
            raise Fail(f"app {new['id']}: put together from {old['id']}, {e}") from None
        expect(len(data) == new["size"], "the file put together is not of its size")
        return (f"version {new['version_code']} from {old['version_code']}: {sum(read)} of {new['size']} bytes "
                f"read, in {len(read)} range(s)")

    # Browsers (SPEC.md § 2.5).

    def origin_needed(self):
        if not self.args.origin:
            raise Skip("no --origin given: the origin a server allows is its owner's choice (§ 2.5)")
        return self.args.origin

    def expect_allowed(self, r, origin):
        allowed = r.header("Access-Control-Allow-Origin")
        expect(allowed in ("*", origin), f"{r}: Access-Control-Allow-Origin {allowed!r}, expected {origin} or *")
        if allowed == origin:
            expect("origin" in names(r.header("Vary")) or "*" in names(r.header("Vary")),
                   f"{r}: Access-Control-Allow-Origin names the origin, without Vary: Origin")

    def c_cors_preflight(self):
        origin = self.origin_needed()
        out = []
        for method, path, asked in (("GET", "/v1/apps?page_size=1", ASKED),
                                    ("POST", "/v1/apps/missing", ("Content-Type", "Content-Digest", "Authorization",
                                                                  "Signature", "Signature-Input", "Lantern-Platform")),
                                    ("PATCH", "/v1/sync/wishes", ("Authorization", "If-Match", "Content-Type")),
                                    ("GET", "/v1/no-such-route", ("Authorization",))):
            r = self.http.request("OPTIONS", self.api(path), auth="none", headers={
                "Origin": origin, "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": ", ".join(h.lower() for h in asked)})
            expect(r.status in (200, 204), f"{r}: a preflight, expected 204" + problem_detail(r))
            self.expect_allowed(r, origin)
            methods = names(r.header("Access-Control-Allow-Methods"))
            expect(method.lower() in methods, f"{r}: Access-Control-Allow-Methods {r.header('Access-Control-Allow-Methods')!r}"
                   f" lacks {method}")
            headers = names(r.header("Access-Control-Allow-Headers"))
            missing = [h for h in asked if h.lower() not in headers]
            expect(not missing, f"{r}: Access-Control-Allow-Headers lacks {', '.join(missing)} (* covers no "
                   "Authorization)")
            expect(not r.header("Access-Control-Allow-Credentials"), f"{r}: Access-Control-Allow-Credentials")
            out.append(f"{method} {path.split('?')[0]}")
        self.preflight = r
        return "; ".join(out)

    def c_cors_max_age(self):
        r = getattr(self, "preflight", None)
        if r is None:
            raise Skip("no preflight answered (cors.preflight)")
        age = r.header("Access-Control-Max-Age") or ""
        if not (age.isdigit() and int(age) >= 600):
            raise Warn(f"{r}: Access-Control-Max-Age {age or 'none'}, below 600 seconds")
        return f"{age} seconds"

    def c_cors_responses(self):
        origin = self.origin_needed()
        checked = []
        probes = [("GET", "/.well-known/lantern", "none"), ("GET", self.api("/v1/apps?page_size=1"), "token"),
                  ("GET", self.api("/v1/no-such-route"), "token"), ("GET", self.api("/v1/apps"), "unknown")]
        if self.sample:
            probes.append(("HEAD", self.file_path(self.sample["file"]), "token"))
        for method, path, auth in probes:
            r = self.http.request(method, path, auth=auth, headers={"Origin": origin}, raw=method == "HEAD")
            self.expect_allowed(r, origin)
            exposed = names(r.header("Access-Control-Expose-Headers"))
            missing = [h for h in EXPOSED if h.lower() not in exposed and "*" not in exposed]
            expect(not missing, f"{r}: Access-Control-Expose-Headers lacks {', '.join(missing)}")
            checked.append(str(r.status))
        return "answers " + ", ".join(checked) + f", each to {origin}"

    def c_cors_other_origin(self):
        r = self.http.request("GET", self.api("/v1/apps?page_size=1"), headers={"Origin": OTHER_ORIGIN})
        allowed = r.header("Access-Control-Allow-Origin")
        if allowed is None:
            return "no Access-Control-Allow-Origin for an origin its owner did not allow"
        expect(allowed in ("*", OTHER_ORIGIN), f"{r}: Access-Control-Allow-Origin {allowed!r} to {OTHER_ORIGIN}")
        self.expect_allowed(r, OTHER_ORIGIN)
        return f"every origin allowed ({allowed})"

    def g_cors_credentials(self):
        bad = [f"{r}: {h}" for r in self.http.log
               for h in ("Access-Control-Allow-Credentials", "Set-Cookie") if r.header(h)]
        expect(not bad, "\n".join(bad[:8]))
        return f"{len(self.http.log)} response(s)"

    # The web platform (Annex A.7).

    def c_platforms_web(self):
        expect("web" not in (self.hello or {}).get("platforms", []), "web among the handshake's platforms")
        bad = [f"app {a.get('id')}" for a in self.apps or [] if a.get("platform") == "web"]
        bad += [f"homebrew {e.get('id')}" for e in self.homebrew or [] if e.get("platform") == "web"]
        expect(not bad, "of platform web: " + ", ".join(bad[:5]))
        if self.features(self.hello)["library"]:
            _, doc = self.get_json(self.api("/v1/apps?platform=web"), "apps")
            expect(doc["items"] == [], "apps listed for platform web")
        return "nothing of platform web"

    # Pairing (SPEC.md § 5.2).

    def c_pairing_after_slow_down(self):
        slowed = getattr(self, "slowed", None)
        if slowed is None:
            raise Skip("no slow_down was answered (pairing.slow-down)")
        when, retry = slowed
        expect(retry <= int(self.pair.get("interval", 60)), f"Retry-After {retry}, above interval "
               f"{self.pair.get('interval')}: the time left until the next poll is answered")
        wait = when + retry - time.monotonic()
        if wait > 0:
            time.sleep(wait + 0.05)
        r = self.http.request("GET", self.poll_path(), auth="none")
        expect(r.status == 202, f"{r} after waiting Retry-After ({retry} s), expected 202: interval counts from the "
               "last poll answered, not from one refused" + problem_detail(r))
        return f"answered after {retry} s"

    # Static libraries (SPEC.md § 21, § 22).

    def s_chunks(self):
        files = []
        for (family, p), items in getattr(self, "static_items", {}).items():
            if family == "apps":
                files += [(f"app {a['id']}", a) for a in items if isinstance(a.get("chunks"), dict)]
        for full in self.static_full:
            files += [(f"homebrew {full['platform']}/{full['id']}", x) for x in [full["package"], *full.get("packages", [])]
                      if isinstance(x.get("chunks"), dict)]
        if not files:
            raise Skip("no file with chunks")
        expect(self.static_hello["features"].get("deltas", 0) >= 1, "files with chunks, but features.deltas is 0")
        budget, cut = self.args.max_download, 0
        for where, doc in files:
            ref = doc["chunks"]
            expect(ref["url"] == f"v1/chunks/sha256/{doc['sha256']}.json",
                   f"{where}: chunks.url {ref['url']}, not v1/chunks/sha256/{doc['sha256']}.json")
            raw = self.read(ref["url"], limit=client.INDEX_LIMIT)
            expect(raw is not None, f"{where}: {ref['url']} missing")
            try:
                index = client.read_chunk_index(raw, ref, doc["sha256"], doc["size"])
            except client.Unusable as e:
                raise Fail(f"{where}: an index a client cannot use: {e}") from None
            self.validate(index, "chunk-index", ref["url"])
            expect(client.canonical(index) == raw, f"{where}: its index is not in canonical JSON (§ 2.3)")
            if doc["size"] <= budget:
                data = self.read(doc["file"], limit=doc["size"])
                if data is not None and len(data) == doc["size"]:
                    expect(client.chunk_index(data, index["chunker"]["size"])[1] == raw,
                           f"{where}: not cut as lantern-cdc-1 cuts it (§ 22.2)")
                    budget -= doc["size"]
                    cut += 1
        return f"{len(files)} index(es), {cut} file(s) cut again and compared"

    def s_cors(self):
        if self.static_http is None:
            raise Skip("a folder: no HTTP answer to a page")
        origin = self.args.origin or OTHER_ORIGIN
        r = self.static_http.request("GET", self.static_root + "lantern.json", auth="none", raw=True,
                                     headers={"Origin": origin})
        allowed = r.header("Access-Control-Allow-Origin")
        if allowed not in ("*", origin):
            raise Warn(f"{r}: Access-Control-Allow-Origin {allowed!r}: a page of another origin cannot read it")
        expect(not r.header("Access-Control-Allow-Credentials"), f"{r}: Access-Control-Allow-Credentials")
        return f"Access-Control-Allow-Origin {allowed}"

