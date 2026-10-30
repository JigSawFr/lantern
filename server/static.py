"""A static library (SPEC.md § 21): the reference server's library written as
files, for a web host (GitHub Pages, a NAS), a USB key or an SD card.

    python3 -m server --library DIR --export OUT [--page-size 100] [--language en]

OUT gets lantern.json and v1/: the pages of apps, titles and homebrew per
platform, each title and homebrew entry, the cheat sets per title and their
texts, and every file by its SHA-256 (v1/blobs/sha256/<hex>). An export
replaces the lantern.json and v1/ of an earlier one, and nothing else in
OUT; the same library gives the same pages. Texts are in one language.
Standard library only.
"""
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

# The layout (SPEC.md § 21.1): each read route's file, below the root.
HANDSHAKE = "lantern.json"
NOT_STATIC = ("changes", "sections", "saves", "encrypted_saves", "requests", "pairing", "signatures", "admin",
              "events", "peers", "sync")
RELATIVE = re.compile(r"^(?![a-zA-Z][a-zA-Z0-9+.-]*:)(?!/)(?!.*(?:^|/)\.\.(?:/|$))[^\\?#]+$")


def layout_path(kind, platform=None, ident=None, page=None):
    """The file of a read route (SPEC.md § 21.1): kind is handshake, apps, titles, title, homebrew, entry,
    cheats, cheat or blob."""
    if kind == "handshake":
        return HANDSHAKE
    if kind in ("apps", "titles", "homebrew"):
        return f"v1/{kind}/{platform}/pages/{page}.json"
    if kind == "title":
        return f"v1/titles/{platform}/{ident}.json"
    if kind == "entry":
        return f"v1/homebrew/{platform}/{ident}.json"
    if kind == "cheats":
        return f"v1/cheats/{platform}/{ident}.json"
    if kind == "cheat":
        return f"v1/cheats/{ident}.txt"
    if kind == "blob":
        return f"v1/blobs/sha256/{ident}"
    raise ValueError(kind)


def relative_ok(path):
    """Whether a document's `file` or image `url` is a path relative to the root (SPEC.md § 21.1): no scheme,
    no leading /, no .. part, no backslash, no query."""
    return isinstance(path, str) and 0 < len(path) <= 4096 and bool(RELATIVE.match(path))


def pages(items, size, kind, platform, wrap):
    """[(path, document)] of a listing cut into pages of `size`, their cursors fixed (SPEC.md § 21.1)."""
    chunks = [items[i:i + size] for i in range(0, len(items), size)] or [[]]
    out = []
    for n, chunk in enumerate(chunks, 1):
        nxt = str(n + 1) if n < len(chunks) else None
        out.append((layout_path(kind, platform, page=n), wrap(chunk, nxt, len(items))))
    return out


def export(server_module, library, out, page_size=100, language="en", name="Lantern library"):
    """Writes `library` (a Library) as a static library into `out`; a summary of what it wrote."""
    ls = server_module
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    if (out / "v1").exists():
        shutil.rmtree(out / "v1")       # the earlier export's tree: replaced whole, nothing of it kept
    prefs = [language]
    files, blobs = {}, {}

    def blob(sha256, path):
        blobs[sha256] = path
        return layout_path("blob", ident=sha256)

    def put(rel, doc):
        files[rel] = doc

    with library.lock:
        platforms = library.platforms()
        apps = sorted(library.apps.values(), key=lambda e: e["keys"]["name"])
        for p in platforms:
            mine = []
            for e in apps:
                if e["doc"]["platform"] == p:
                    doc = dict(e["doc"], file=blob(e["doc"]["sha256"], e["path"]))
                    mine.append(doc)
            for rel, doc in pages(mine, page_size, "apps", p,
                                  lambda c, n, t: {"schema": 1, "items": c, "total": t, "next": n}):
                put(rel, doc)
            titles = sorted((k for k, t in library.titles.items() if t["platform"] == p),
                            key=lambda k: (library.titles[k]["name"].casefold(), library.titles[k]["title_id"]))
            docs = [library.title_doc(k, prefs) for k in titles]
            for d in docs:
                put(layout_path("title", p, d["title_id"]), {"schema": 1, **d})
            for rel, doc in pages(docs, page_size, "titles", p,
                                  lambda c, n, t: {"schema": 1, "titles": c, "unknown": [], "next": n}):
                put(rel, doc)
            entries = sorted((e for (q, _), e in library.homebrew.items() if q == p), key=lambda e: e["keys"]["name"])
            listed = []
            for e in entries:
                paths = {f["sha256"]: f["path"] for f in library.files.values()
                         if f.get("owner") == ("homebrew", p, e["doc"]["id"])}
                full, short = (json.loads(json.dumps(ls.homebrew_view(e, f, prefs))) for f in (True, False))
                for doc in (full, short):
                    for package in [doc["package"], *doc.get("packages", [])]:
                        package["file"] = blob(package["sha256"], paths[package["sha256"]])
                put(layout_path("entry", p, e["doc"]["id"]), {"schema": 1, **full})
                listed.append(short)
            for rel, doc in pages(listed, page_size, "homebrew", p,
                                  lambda c, n, t: {"schema": 1, "items": c, "total": t, "next": n}):
                put(rel, doc)
        by_title = {}
        for e in sorted(library.cheats.values(), key=lambda e: (e["doc"]["platform"], e["doc"]["title_id"],
                                                                 e["doc"].get("build_id", ""), e["doc"]["source"].casefold(),
                                                                 e["doc"]["id"])):
            by_title.setdefault((e["doc"]["platform"], e["doc"]["title_id"]), []).append(e["doc"])
            blobs[("cheat", e["doc"]["id"])] = e["path"]
        for (p, t), sets in by_title.items():
            put(layout_path("cheats", p, t), {"schema": 1, "cheats": sets})
        features = {f: 0 for f in ls.FAMILIES}
        features.update(library=1, titles=1, homebrew=1, cheats=1 if by_title else 0)
        generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        put(HANDSHAKE, {"schema": 1, "uid": library.uid, "name": name,
                        "software": {"name": "Lantern reference server", "version": ls.VERSION},
                        "base": ".", "versions": [1], "platforms": platforms, "language": language,
                        "account": {"state": "anonymous", "scopes": ["library", "cheats"] if by_title else ["library"]},
                        "features": features, "limits": {"page_size": page_size},
                        "static": {"generated": generated, "page_size": page_size}})
    for rel, doc in files.items():
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    for key, path in blobs.items():
        target = out / (layout_path("cheat", ident=key[1]) if isinstance(key, tuple) else layout_path("blob", ident=key))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return {"documents": len(files), "files": len(blobs), "platforms": platforms}
