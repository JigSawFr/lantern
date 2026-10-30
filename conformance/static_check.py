"""The conformance suite's checks of a static library (SPEC.md § 21), with
--static: a mixin of run.py's Suite. The library is an address (read over
HTTPS, or plain HTTP on loopback) or a folder; the suite reads lantern.json,
then every page of every platform, each title, homebrew entry and cheat set,
and the files they point at within --max-download, by the layout of § 21.1.
Every document is held to § 13's limits (a file above 32 MiB is not read),
every homebrew manifest to § 8.2 and the profile's roots, and every
signature must verify (§ 8.4), as from a server.
"""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

Fail = Skip = Blind = Warn = Client = None     # run.py's (bind())
limit_problems = client = None                  # run.py's too
JSON_LIMIT = 32 << 20                           # SPEC.md § 13: a JSON document
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
        self.static_full = []       # every homebrew entry's own file, as read

    def read(self, rel, limit=JSON_LIMIT):
        """A file of the library, its bytes; None when it is not there. One above `limit` is not read
        (SPEC.md § 13: a client bounds what it reads): Fail."""
        if self.static_http is None:
            path = self.static_root / rel
            if not path.is_file():
                return None
            size = path.stat().st_size
            expect(size <= limit, f"{rel}: {size} bytes, above the {limit} a reader takes (SPEC.md § 13)")
            return path.read_bytes()
        r = self.static_http.request("GET", self.static_root + quote(rel), auth="none", raw=True, limit=limit)
        if r.status == 404:
            return None
        expect(r.status == 200, f"{r}, expected 200 or 404")
        expect(not r.truncated, f"{rel}: above the {limit} bytes a reader takes (SPEC.md § 13)")
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
        self.check("static.manifests", "8.2", "Every manifest: its paths, its digest, within the profile's roots",
                   self.s_manifests)
        self.check("static.signatures", "8.4", "Every homebrew signature verifies over the defined bytes",
                   self.s_signatures)
        self.check("static.limits", "13", "Every document within § 13's limits: depth, strings, items",
                   self.s_limits)
        self.check("static.chunks", "22.1", "Chunk indexes at v1/chunks/sha256/<hex>.json: of their file, in "
                   "canonical JSON, cut by lantern-cdc-1", self.s_chunks)
        self.check("static.cors", "21.3", "Over HTTP: Access-Control-Allow-Origin for a page of any origin",
                   self.s_cors, level="should")
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
                self.static_full.append(full)
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
        for full in self.static_full:
            for x in [full["package"], *full.get("packages", [])]:
                out.append((x["file"], x["size"], x["sha256"], f"homebrew {full['platform']}/{full['id']}"))
        for (family, _), items in getattr(self, "static_items", {}).items():
            if family == "titles":      # the images of the library, files by their SHA-256 like the others
                for t in items:
                    for img in [t.get("icon"), t.get("banner"), *t.get("screenshots", [])]:
                        if isinstance(img, dict) and not img.get("external") and isinstance(img.get("sha256"), str):
                            if str(img.get("url", "")).startswith("v1/blobs/"):
                                out.append((img["url"], None, img["sha256"], f"image of {t.get('title_id')}"))
        return out

    def s_paths(self):
        bad = [f"{where}: {path}" for path, _, _, where in self.static_files() if not RELATIVE.match(path)]
        for (family, _), items in getattr(self, "static_items", {}).items():
            for i in items:
                if isinstance(i.get("chunks"), dict) and not RELATIVE.match(str(i["chunks"].get("url"))):
                    bad.append(f"{family}: chunks {i['chunks'].get('url')}")
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
            if size is not None and size > budget:
                continue
            data = self.read(path, limit=size if size is not None else min(budget, JSON_LIMIT))
            expect(data is not None, f"{where}: {path} missing")
            expect((size is None or len(data) == size) and hashlib.sha256(data).hexdigest() == sha,
                   f"{where}: {path} is not of its size and SHA-256")
            budget -= len(data)
            read += 1
        return f"{read} of {len(files)} file(s) read and checked"

    def s_manifests(self):
        """SPEC.md § 8.2, as for a server's entries (run.py's manifest_problems): each path of the profile's
        form, the manifest's digest, and every path within the platform's roots (Annex A)."""
        if not self.static_full:
            raise Skip("no homebrew entry could be read (static.homebrew)")
        problems, plans, unchecked = [], {"free": 0, "consent": 0}, set()
        for entry in self.static_full:
            for package in [entry["package"], *(entry.get("packages") or [])]:
                problems += self.manifest_problems(entry["platform"], entry["id"], {**entry, "package": package},
                                                   plans, unchecked)
        expect(not problems, "\n".join(problems[:8]))
        note = f"; roots not checked for {', '.join(sorted(unchecked))} (a draft or no profile)" if unchecked else ""
        return f"{plans['free']} path(s) free to write, {plans['consent']} needing consent{note}"

    def s_signatures(self):
        """SPEC.md § 8.4: a signature that does not verify, a key or an R of small order, a package signed by
        another key: a client refuses them, and a library serves none."""
        signed = [e for e in self.static_full if "signature" in e]
        if not signed:
            raise Skip("no signed homebrew")
        bad = []
        for d in signed:
            if not client.verify_signature(d):
                bad.append(f"{d['platform']}/{d['id']}")
            for extra in d.get("packages") or []:
                sig = extra.get("signature")
                if not sig or sig.get("public_key") != d["signature"]["public_key"] \
                        or not client.verify_signature({**d, "package": extra, "signature": sig}):
                    bad.append(f"{d['platform']}/{d['id']} ({', '.join(extra.get('arch') or ['?'])})")
        expect(not bad, "signatures that do not verify, or by another key (a client refuses them): "
               + ", ".join(bad[:5]))
        return f"{len(signed)} signature(s)"

    def s_limits(self):
        """SPEC.md § 13 over every document read: nesting, strings, items on a page, files in a manifest."""
        bad = [f"{rel}: {p}" for rel, doc in self.static_docs.items() for p in limit_problems(doc)]
        expect(not bad, "\n".join(bad[:8]))
        return f"{len(self.static_docs)} document(s)"
