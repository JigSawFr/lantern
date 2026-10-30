"""The conformance suite's checks of a static library (SPEC.md § 21), with
--static: a mixin of run.py's Suite. The library is an address (read over
HTTPS, or plain HTTP on loopback) or a folder; the suite reads lantern.json,
then every page of every platform, each title, homebrew entry and cheat set,
and the files they point at within --max-download, by the layout of § 21.1.
"""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

Fail = Skip = Blind = Warn = Client = None     # run.py's (bind())
RELATIVE = re.compile(r"^(?![a-zA-Z][a-zA-Z0-9+.-]*:)(?!/)(?!.*(?:^|/)\.\.(?:/|$))[^\\?#]+$")
NOT_STATIC = ("changes", "sections", "saves", "encrypted_saves", "requests", "pairing", "signatures", "admin",
              "events", "peers", "sync")


def bind(**names):
    globals().update(names)


def expect(cond, msg):
    if not cond:
        raise Fail(msg)


class StaticChecks:
    """A static library's checks (SPEC.md § 21)."""

    def static_open(self):
        target = self.args.static
        if Path(target).is_dir():
            self.static_root, self.static_http = Path(target), None
        else:
            u = urlsplit(target if "://" in target else "https://" + target)
            import ssl
            ctx = ssl.create_default_context(cafile=self.args.cafile) if u.scheme == "https" else None
            self.static_root = u.path.rstrip("/") + "/"
            self.static_http = Client(u, None, ctx, self.args.timeout)
            self.http = self.static_http      # every response read, for the checks over all of them
        self.static_docs = {}

    def read(self, rel, limit=32 << 20):
        """A file of the library, its bytes; None when it is not there."""
        if self.static_http is None:
            path = self.static_root / rel
            return path.read_bytes() if path.is_file() else None
        r = self.static_http.request("GET", self.static_root + quote(rel), auth="none", raw=True, limit=limit)
        if r.status == 404:
            return None
        expect(r.status == 200, f"{r}, expected 200 or 404")
        return r.body

    def doc(self, rel, schema):
        """A document of the library, valid against `schema`; Fail when absent or not JSON."""
        if rel in self.static_docs:
            return self.static_docs[rel]
        data = self.read(rel)
        expect(data is not None, f"{rel}: missing")
        try:
            doc = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise Fail(f"{rel}: not JSON ({e})") from None
        self.validate(doc, schema, rel)
        self.static_docs[rel] = doc
        return doc

    def run_static(self):
        self.static_open()
        print(f"Lantern conformance {self.version}: the static library at {self.args.static}", file=self.out)
        self.level = "static"
        if not self.check("static.handshake", "21.2", "lantern.json: a static handshake, every server's family at 0",
                          self.s_handshake):
            print("No handshake: nothing else can be checked.", file=self.out)
            return self.summary_static()
        for family, schema in (("apps", "apps"), ("titles", "titles"), ("homebrew", "homebrew-page")):
            self.check(f"static.pages.{family}", "21.1", f"The pages of {family}, per platform: chained, sorted, "
                       "valid", lambda f=family, s=schema: self.s_pages(f, s))
        self.check("static.titles", "21.1", "Each title's file: valid, the same as on the pages", self.s_titles)
        self.check("static.homebrew", "21.1", "Each homebrew entry's file: valid, the same as listed but its "
                   "manifests", self.s_homebrew)
        self.check("static.cheats", "21.1", "Cheat sets per title, and each set's text: its size and SHA-256",
                   self.s_cheats)
        self.check("static.paths", "21.1", "Every file and image the documents point at: a path relative to the root",
                   self.s_paths)
        self.check("static.files", "21.1", "Every file at v1/blobs/sha256/<hex>, of its size and SHA-256",
                   self.s_files)
        return self.summary_static()

    def summary_static(self):
        counts = {s: sum(1 for r in self.results if r[0] == s) for s in ("PASS", "FAIL", "WARN", "SKIP")}
        print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['WARN']} warning(s), "
              f"{counts['SKIP']} skipped.", file=self.out)
        reached = bool(self.results) and not counts["FAIL"] and self.results[0][0] == "PASS"
        print(f"Levels reached (SPEC.md § 17, draft {self.version[:3]}): " + ("Lantern Static" if reached else "none"),
              file=self.out)
        return 1 if counts["FAIL"] or not self.results else 0

    def s_handshake(self):
        doc = self.doc("lantern.json", "handshake")
        static = doc.get("static")
        expect(isinstance(static, dict), "lantern.json has no static: not a static library's handshake")
        expect(doc["account"].get("state") == "anonymous", f"account.state {doc['account'].get('state')}")
        expect(set(doc["account"].get("scopes", [])) <= {"library", "cheats"}, f"scopes {doc['account'].get('scopes')}")
        on = [f for f in NOT_STATIC if doc["features"].get(f, 0)]
        expect(not on, f"families a static library cannot offer, above 0: {', '.join(on)}")
        self.static_hello = doc
        return f"generated {static['generated']}, pages of {static['page_size']}, platforms {', '.join(doc['platforms'])}"

    def pages_of(self, family, schema, platform):
        """Every item of a platform's listing, its pages chained by their fixed cursors (SPEC.md § 21.1)."""
        key = "titles" if family == "titles" else "items"
        items, n, size = [], 1, self.static_hello["static"]["page_size"]
        while True:
            rel = f"v1/{family}/{platform}/pages/{n}.json"
            doc = self.doc(rel, schema)
            expect(len(doc[key]) <= size, f"{rel}: {len(doc[key])} items, above static.page_size {size}")
            items += doc[key]
            nxt = doc.get("next")
            if nxt is None:
                return items
            expect(nxt == str(n + 1), f"{rel}: next {nxt!r}, the cursor of page {n + 1} is \"{n + 1}\"")
            expect(len(doc[key]) == size, f"{rel}: a page before the last holds {len(doc[key])} items, not {size}")
            n += 1
            expect(n <= 100000, f"{rel}: pages without end")

    def s_pages(self, family, schema):
        hello = self.static_hello
        offered = hello["features"].get({"apps": "library"}.get(family, family), 0)
        if not offered:
            raise Skip(f"{family} at 0")
        counts = []
        self.static_items = getattr(self, "static_items", {})
        for p in hello["platforms"]:
            items = self.pages_of(family, schema, p)
            wrong = [i for i in items if i.get("platform") != p]
            expect(not wrong, f"{family} of {p}: items of another platform")
            names = [(i["name"].casefold(), i.get("id", i.get("title_id"))) for i in items]
            if family != "titles":
                expect(names == sorted(names, key=lambda x: x[0]), f"{family} of {p}: not sorted by name")
            if family != "titles":
                first = self.doc(f"v1/{family}/{p}/pages/1.json", schema)
                expect(first.get("total", len(items)) == len(items), f"{family} of {p}: total {first.get('total')}, "
                       f"{len(items)} read")
            self.static_items[(family, p)] = items
            counts.append(f"{p} {len(items)}")
        return ", ".join(counts)

    def s_titles(self):
        items = getattr(self, "static_items", {})
        done = 0
        for (family, p), titles in items.items():
            if family != "titles":
                continue
            for t in titles:
                doc = self.doc(f"v1/titles/{p}/{t['title_id']}.json", "title")
                expect({k: v for k, v in doc.items() if k != "schema"} == t,
                       f"v1/titles/{p}/{t['title_id']}.json differs from its page")
                done += 1
        apps = [a for (f, _), xs in items.items() if f == "apps" for a in xs]
        known = {(t["platform"], t["title_id"]) for (f, _), xs in items.items() if f == "titles" for t in xs}
        if self.static_hello["features"].get("titles") and apps:
            missing = sorted({(a["platform"], a["title_id"]) for a in apps} - known)
            expect(not missing, f"apps without their title's file: {missing[:3]}")
        if not done:
            raise Skip("no title")
        return f"{done} title(s)"

    def s_homebrew(self):
        done = 0
        for (family, p), entries in getattr(self, "static_items", {}).items():
            if family != "homebrew":
                continue
            for e in entries:
                full = self.doc(f"v1/homebrew/{p}/{e['id']}.json", "homebrew")
                strip = {k: v for k, v in full.items() if k != "schema"}
                strip["package"] = {k: v for k, v in strip["package"].items() if k != "manifest"}
                if "packages" in strip:
                    strip["packages"] = [{k: v for k, v in x.items() if k != "manifest"} for x in strip["packages"]]
                expect(strip == e, f"v1/homebrew/{p}/{e['id']}.json differs from its listing, but its manifests")
                self.static_docs.setdefault("homebrew-full", []).append(full)
                done += 1
        if not done:
            raise Skip("no homebrew")
        return f"{done} entr{'y' if done == 1 else 'ies'}"

    def s_cheats(self):
        if not self.static_hello["features"].get("cheats"):
            raise Skip("cheats at 0")
        titles = {(t["platform"], t["title_id"]) for (f, _), xs in getattr(self, "static_items", {}).items()
                  if f in ("titles", "apps") for t in xs}
        sets = 0
        for p, tid in sorted(titles):
            data = self.read(f"v1/cheats/{p}/{tid}.json")
            if data is None:
                continue
            doc = self.doc(f"v1/cheats/{p}/{tid}.json", "cheats")
            for c in doc["cheats"]:
                expect((c["platform"], c["title_id"]) == (p, tid), f"v1/cheats/{p}/{tid}.json: a set of another title")
                text = self.read(f"v1/cheats/{c['id']}.txt", limit=1 << 20)
                expect(text is not None, f"v1/cheats/{c['id']}.txt: missing")
                expect(len(text) == c["size"] and hashlib.sha256(text).hexdigest() == c["sha256"],
                       f"v1/cheats/{c['id']}.txt: not of its size and SHA-256")
                sets += 1
        if not sets:
            raise Skip("no cheat set")
        return f"{sets} set(s)"

    def static_files(self):
        """[(path, size, sha256, where)] of every file the documents point at."""
        out = []
        for (family, p), items in getattr(self, "static_items", {}).items():
            if family == "apps":
                out += [(a["file"], a["size"], a["sha256"], f"app {a['id']}") for a in items]
        for full in self.static_docs.get("homebrew-full", []):
            for x in [full["package"], *full.get("packages", [])]:
                out.append((x["file"], x["size"], x["sha256"], f"homebrew {full['platform']}/{full['id']}"))
        return out

    def s_paths(self):
        bad = [f"{where}: {path}" for path, _, _, where in self.static_files() if not RELATIVE.match(path)]
        for (family, _), items in getattr(self, "static_items", {}).items():
            for i in items:
                for img in [i.get("icon"), i.get("banner"), *i.get("screenshots", [])]:
                    if isinstance(img, dict) and not img.get("external") and not RELATIVE.match(str(img.get("url"))):
                        bad.append(f"{family}: image {img.get('url')}")
        expect(not bad, "not paths relative to the root:\n" + "\n".join(bad[:8]))
        return f"{len(self.static_files())} file path(s)"

    def s_files(self):
        files = self.static_files()
        if not files:
            raise Skip("no file")
        budget, read = self.args.max_download, 0
        for path, size, sha, where in files:
            expect(path == f"v1/blobs/sha256/{sha}", f"{where}: {path}, not v1/blobs/sha256/{sha}")
            if size > budget:
                continue
            data = self.read(path, limit=size)
            expect(data is not None, f"{where}: {path} missing")
            expect(len(data) == size and hashlib.sha256(data).hexdigest() == sha, f"{where}: {path} is not of its "
                   "size and SHA-256")
            budget -= size
            read += 1
        return f"{read} of {len(files)} file(s) read and checked"
