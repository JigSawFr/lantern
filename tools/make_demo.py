#!/usr/bin/env python3
"""Lantern's demo library (site/demo/README.md): a static library (SPEC.md
§ 21) of fictional games, homebrew and cheat sets, and its trapped variant,
static libraries broken on purpose for testing clients.

    python3 tools/make_demo.py build OUT    # the demo into OUT, its trapped variant into OUT/trapped/
    python3 tools/make_demo.py check OUT    # the conformance suite against both (needs jsonschema)

tools/build_site.py builds it into the site's demo/ at each build. Its
source is site/demo/demo.json (schema 1): the apps, titles, homebrew and
cheat sets, written as a folder the reference server reads (server/), then
exported by it (server/static.py); this script then sets the export's time
to the source's, and gives each title and homebrew its artwork, a small PNG
drawn here (the night, a tint, one drawing in snow), stored as a file by its
SHA-256. The packages are placeholders of a few bytes of text, and the
homebrew archives hold a README only: nothing in it is software. The same
source gives the same files.

The trapped variant (OUT/trapped/<scenario>/, listed with what a client
must do in OUT/trapped/scenarios.json, schema 1) mirrors, scenario by
scenario, the malicious test server of lantern-sdk's Python library
(python/tools/hostile_server.py) where a static file can express the fault,
and adds the static layout's own (paths that leave the root). `check`
expects the suite to pass the demo at Lantern Static, and to refuse each
scenario by the checks it names.

Standard library only for `build`; `check` runs conformance/run.py, which
needs tools/requirements.txt.
"""
import base64
import contextlib
import functools
import hashlib
import io
import json
import math
import os
import shutil
import struct
import sys
import tempfile
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "site" / "demo" / "demo.json"
SCHEMA = 1                      # demo.json's and scenarios.json's
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "conformance"))
import lantern_client as client  # noqa: E402  (conformance/lantern_client.py)
from server import ed25519, static  # noqa: E402
from server import lantern_server as ls  # noqa: E402

ART = 256                       # the artwork's side, in pixels
# Where a homebrew archive puts its files, per platform (SPEC.md Annex A): the folder of its own.
HOMEBREW_HOME = {"switch": "switch/{id}/", "3ds": "3ds/{id}/", "linux": "{id}/"}


def read_source(path=SOURCE):
    """demo.json, or None when there is none or it is of a newer schema than this script reads (absent,
    without error); its unknown keys are skipped."""
    if not Path(path).is_file():
        return None
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or type(doc.get("schema")) is not int or doc["schema"] > SCHEMA:
        return None
    return doc


def dumps(doc):
    """A document as server/static.py writes it."""
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":"))


def placeholder(label, size):
    """`size` bytes of text that say what they are: no game, no software. One large enough for a chunk index
    (SPEC.md § 22, 128 KiB or more for the reference server) numbers its lines, so that its content-defined
    chunks end where its bytes say rather than at the chunker's largest size, as in a repeated line: each line its number and a digest of it."""
    line = f"Lantern demo library placeholder: {label}. Not a game, not software, not installable.\n".encode()
    if size < 128 * 1024:
        return (line * (size // len(line) + 1))[:size]
    out, n = bytearray(), 0
    while len(out) < size:
        n += 1
        out += f"{n:06d} {hashlib.sha256(f'{label} {n}'.encode()).hexdigest()} ".encode() + line
    return bytes(out[:size])


def zipped(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            info = zipfile.ZipInfo(name, (2026, 10, 30, 12, 0, 0))
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return out.getvalue()


def manifest_of(files):
    """A zip's manifest (SPEC.md § 8.2): each file at "/" + its name."""
    return sorted(({"path": "/" + name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                   for name, data in files.items()), key=lambda e: e["path"].encode())


def seed_of(phrase):
    return hashlib.sha256(phrase.encode()).digest()


def signature(seed, hid, platform, build, data, files):
    """SPEC.md § 8.4's signature of a zip package, by the fictional key `seed`."""
    entry = {"id": hid, "platform": platform, "build": build,
             "package": {"sha256": hashlib.sha256(data).hexdigest(), "manifest_sha256": client.manifest_sha256(manifest_of(files))}}
    value = ed25519.sign(seed, client.signed_message(entry))
    return {"alg": "ed25519", "public_key": base64.b64encode(ed25519.public_key(seed)).decode(),
            "value": base64.b64encode(value).decode()}


def readme(meta):
    return (f"Lantern demo library: {meta['name']}, by {meta['author']}, version {meta['version']}.\n"
            "Fictional: this archive is a placeholder that holds this text only. It is not software,\n"
            "and copying it anywhere does nothing.\n").encode()


# ---- The artwork: a 256 x 256 PNG, the night tinted by the game's hue, one
# drawing in snow (Boréale's palette, branding/README.md), its edges smoothed
# by signed distances.

SNOW = (232, 238, 247)
NIGHT = (11, 20, 36)


def hsl(h, s, light):
    c = (1 - abs(2 * light - 1)) * s
    x = c * (1 - abs((h / 60) % 2 - 1))
    m = light - c / 2
    r, g, b = [(c, x, 0), (x, c, 0), (0, c, x), (0, x, c), (x, 0, c), (c, 0, x)][int(h // 60) % 6]
    return tuple(round((v + m) * 255) for v in (r, g, b))


def circle(px, py, cx, cy, r):
    return math.hypot(px - cx, py - cy) - r


def box(px, py, cx, cy, hw, hh, r=0.0):
    qx, qy = abs(px - cx) - hw + r, abs(py - cy) - hh + r
    return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r


def segment(px, py, ax, ay, bx, by, r):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy) - r


def polygon(px, py, pts):
    d = (px - pts[0][0]) ** 2 + (py - pts[0][1]) ** 2
    inside = False
    j = len(pts) - 1
    for i, (xi, yi) in enumerate(pts):
        xj, yj = pts[j]
        ex, ey = xj - xi, yj - yi
        wx, wy = px - xi, py - yi
        t = max(0.0, min(1.0, (wx * ex + wy * ey) / (ex * ex + ey * ey)))
        d = min(d, (wx - ex * t) ** 2 + (wy - ey * t) ** 2)
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return -math.sqrt(d) if inside else math.sqrt(d)


STAR = [(128 + (70 if i % 2 == 0 else 30) * math.sin(i * math.pi / 5),
         136 - (70 if i % 2 == 0 else 30) * math.cos(i * math.pi / 5)) for i in range(10)]


def drawing(shape, x, y):
    """(snow, accent): the signed distances to the drawing and to its accent, in pixels."""
    far = 1e9
    if shape == "lantern":
        handle = max(abs(circle(x, y, 128, 84, 26)) - 6, y - 84)
        body = min(box(x, y, 128, 140, 38, 46, 12), box(x, y, 128, 92, 48, 8, 4), box(x, y, 128, 196, 44, 8, 4))
        return min(handle, max(body, -box(x, y, 128, 140, 26, 34, 6))), min(circle(x, y, 128, 150, 13),
                                                                           polygon(x, y, [(128, 116), (141, 148), (115, 148)]))
    if shape == "leaf":
        blade = max(circle(x, y, 100, 128, 74), circle(x, y, 156, 128, 74))
        return max(blade, -segment(x, y, 80, 176, 176, 80, 3)), segment(x, y, 64, 192, 86, 170, 5)
    if shape == "comet":
        tail = polygon(x, y, [(150, 104), (60, 70), (164, 132), (44, 150), (150, 150)])
        return min(circle(x, y, 162, 128, 30), tail), circle(x, y, 162, 128, 12)
    if shape == "wave":
        d1 = abs(y - (112 + 18 * math.sin((x - 20) / 26))) - 9
        d2 = abs(y - (156 + 18 * math.sin((x + 6) / 26))) - 9
        return max(min(d1, d2), box(x, y, 128, 134, 92, 60)), circle(x, y, 180, 70, 14)
    if shape == "tree":
        return min(circle(x, y, 128, 104, 54), box(x, y, 128, 178, 12, 34, 4)), min(
            circle(x, y, 108, 96, 8), circle(x, y, 148, 112, 8), circle(x, y, 124, 128, 8))
    if shape == "mountain":
        return polygon(x, y, [(128, 52), (212, 196), (44, 196)]), polygon(x, y, [(128, 52), (152, 92), (104, 92)])
    if shape == "star":
        return polygon(x, y, STAR), circle(x, y, 196, 64, 8)
    if shape == "moon":
        return max(circle(x, y, 128, 128, 66), -circle(x, y, 156, 108, 56)), circle(x, y, 182, 172, 8)
    if shape == "clock":
        ring = abs(circle(x, y, 128, 128, 66)) - 9
        return min(ring, segment(x, y, 128, 128, 128, 86, 6), segment(x, y, 128, 128, 160, 146, 6)), circle(x, y, 128, 128, 9)
    return far, far


@functools.cache
def artwork(hue, shape):
    """The PNG's bytes."""
    top, accent = hsl(hue, 0.55, 0.24), hsl(hue, 1.0, 0.62)
    rows = []
    for y in range(ART):
        t = y / (ART - 1)
        base = [round(top[i] * (1 - t) + NIGHT[i] * t) for i in range(3)]
        row = bytearray(b"\0")
        band_y = 54 + 16 * math.sin(y / 40)
        for x in range(ART):
            px, py = x + 0.5, y + 0.5
            c = list(base)
            # The aurora, once, across the top: a soft band of the hue.
            glow = max(0.0, 1 - abs(py - (band_y + 10 * math.sin(px / 30))) / 26) * max(0.0, 1 - py / 150) * 0.45
            c = [c[i] + (accent[i] - c[i]) * glow for i in range(3)]
            snow, lit = drawing(shape, px, py)
            a = max(0.0, min(1.0, 0.5 - snow))
            c = [c[i] + (SNOW[i] - c[i]) * a for i in range(3)]
            a = max(0.0, min(1.0, 0.5 - lit))
            c = [c[i] + (accent[i] - c[i]) * a for i in range(3)]
            row += bytes(round(v) for v in c)
        rows.append(bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", ART, ART, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


# ---- The library, written as the reference server reads it, then exported.

def write_library(folder, source):
    """The reference server's folder for `source` (server/lantern_server.py's docstring)."""
    folder.mkdir(parents=True)
    keys = {name: seed_of(phrase) for name, phrase in source.get("keys", {}).items()}
    apps = []
    for app in source.get("apps", []):
        (folder / app["file"]).parent.mkdir(parents=True, exist_ok=True)
        (folder / app["file"]).write_bytes(placeholder(Path(app["file"]).stem, app["size"]))
        apps.append({k: v for k, v in app.items() if k not in ("size", "art")})
    (folder / "library.json").write_text(json.dumps({"schema": 1, "apps": apps}, indent=1), encoding="utf-8")
    for hb in source.get("homebrew", []):
        meta = hb["meta"]
        home = HOMEBREW_HOME[hb["platform"]].format(id=hb["id"])
        files = hb.get("files") or {home + "README.txt": readme(meta)}
        data = zipped(files)
        target = folder / "homebrew" / hb["id"]
        target.mkdir(parents=True)
        (target / hb["file"]).write_bytes(data)
        doc = {"schema": 1, "id": hb["id"], "platform": hb["platform"], **meta}
        if hb.get("signed_by"):
            doc["signature"] = signature(keys[hb["signed_by"]], hb["id"], hb["platform"], meta["build"], data, files)
        (target / "homebrew.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    for c in source.get("cheats", []):
        path = folder / "cheats" / c["platform"] / c["title_id"] / c["build_id"] / f"{c['source']}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(c["text"], encoding="utf-8")


def export(source, out, name):
    """`source` as a static library in `out`, its time and uid the source's, its artwork added."""
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / "library"
        write_library(folder, source)
        # Every file of the source's time: the server's `added` and `updated` are its files' (the same
        # source, the same files).
        when = datetime.strptime(source["generated"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        for path in [*folder.rglob("*"), folder]:
            os.utime(path, (when, when))
        state = Path(tmp) / "state.json"
        state.write_text(json.dumps({"schema": 1, "uid": source["uid"],
                                     "secret": hashlib.sha256(b"demo secret " + source["uid"].encode()).hexdigest(),
                                     "grant_seed": hashlib.sha256(b"demo grant " + source["uid"].encode()).hexdigest()}),
                         encoding="utf-8")
        said = io.StringIO()
        with contextlib.redirect_stderr(said):
            library = ls.Library(folder, state)
        skipped = [line for line in said.getvalue().splitlines() if "skipped" in line or "absent" in line]
        if skipped:
            sys.exit("make_demo: the reference server skipped part of the demo:\n" + "\n".join(skipped))
        static.export(ls, library, out, source.get("page_size", 100), source.get("language", "en"), name)
    hello = json.loads((out / "lantern.json").read_text(encoding="utf-8"))
    hello["static"]["generated"] = source["generated"]
    (out / "lantern.json").write_text(dumps(hello), encoding="utf-8")
    # A title's `updated` is when the server first saw its sheet: the source's time here.
    for path in (out / "v1" / "titles").rglob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for title in doc.get("titles", [doc]):
            title["updated"] = source["generated"]
        path.write_text(dumps(doc), encoding="utf-8")
    add_artwork(source, out, hello["platforms"])
    return hello


def add_artwork(source, out, platforms):
    """Each title's and homebrew entry's icon, a file of the library by its SHA-256 (SPEC.md § 21.1)."""
    icons = {}

    def icon(art):
        data = artwork(art["hue"], art["shape"])
        sha = hashlib.sha256(data).hexdigest()
        path = out / static.layout_path("blob", ident=sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"url": static.layout_path("blob", ident=sha), "width": ART, "height": ART, "sha256": sha}

    for p in platforms:
        for n in range(1, 10000):
            page = out / static.layout_path("apps", p, page=n)
            if not page.exists():
                break
            for app in json.loads(page.read_text(encoding="utf-8"))["items"]:
                art = next((a["art"] for a in source.get("apps", []) if "art" in a and a.get("name") == app["name"]
                            and a.get("platform", "switch") == p), None)
                if art and ("titles", p, app["title_id"]) not in icons:
                    icons[("titles", p, app["title_id"])] = art
    for hb in source.get("homebrew", []):
        if "art" in hb:
            icons[("homebrew", hb["platform"], hb["id"])] = hb["art"]
    made = {}
    for (family, p, ident), art in icons.items():
        key = (art["hue"], art["shape"])
        made.setdefault(key, None)
        made[key] = made[key] or icon(art)
        image = made[key]
        single = out / static.layout_path("title" if family == "titles" else "entry", p, ident)
        if single.exists():
            doc = json.loads(single.read_text(encoding="utf-8"))
            doc["icon"] = image
            single.write_text(dumps(doc), encoding="utf-8")
        for n in range(1, 10000):
            page = out / static.layout_path(family, p, page=n)
            if not page.exists():
                break
            doc = json.loads(page.read_text(encoding="utf-8"))
            key_of = "title_id" if family == "titles" else "id"
            for item in doc["titles" if family == "titles" else "items"]:
                if item[key_of] == ident:
                    item["icon"] = image
            page.write_text(dumps(doc), encoding="utf-8")


# ---- The trapped variant: one small library per scenario, each broken in
# one way. `checks` are the suite's checks that must fail on it.

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, doc):
    path.write_text(dumps(doc), encoding="utf-8")


def first_app(root):
    page = root / "v1/apps/switch/pages/1.json"
    return page, load(page)


def entry_files(root, hid):
    return root / f"v1/homebrew/switch/{hid}.json", root / "v1/homebrew/switch/pages/1.json"


TRAPPED_HOMEBREW = "org.example.nightjournal"


def rebuild_homebrew(root, files, sign=True, mutate=None):
    """The trapped library's homebrew entry with an archive of `files` (name: bytes) and its manifest,
    signed by Ines's fictional key when `sign`, then `mutate(entry)`; its listing follows."""
    single, page_path = entry_files(root, TRAPPED_HOMEBREW)
    entry = load(single)
    data = zipped(files)
    sha = hashlib.sha256(data).hexdigest()
    (root / static.layout_path("blob", ident=sha)).write_bytes(data)
    manifest = manifest_of(files)
    entry["package"].update(file=static.layout_path("blob", ident=sha), size=len(data), sha256=sha, manifest=manifest,
                            manifest_sha256=client.manifest_sha256(manifest))
    entry.pop("signature", None)
    if sign:
        entry["signature"] = signature(seed_of("Ines's fictional signing key, for Lantern's demo library"),
                                       entry["id"], entry["platform"], entry["build"], data, files)
    if mutate:
        mutate(entry)
    save(single, entry)
    page = load(page_path)
    listed = {k: v for k, v in entry.items() if k != "schema"}
    listed["package"] = {k: v for k, v in entry["package"].items() if k != "manifest"}
    page["items"] = [listed if i["id"] == entry["id"] else i for i in page["items"]]
    save(page_path, page)


def t_bad_digest(root):
    _, page = first_app(root)
    blob = root / page["items"][0]["file"]
    data = bytearray(blob.read_bytes())
    data[0] ^= 0xFF
    blob.write_bytes(bytes(data))


def t_extra_bytes(root):
    _, page = first_app(root)
    blob = root / page["items"][0]["file"]
    blob.write_bytes(blob.read_bytes() + b"and more bytes than its size\n")


def t_truncated(root):
    _, page = first_app(root)
    blob = root / page["items"][0]["file"]
    data = blob.read_bytes()
    blob.write_bytes(data[:len(data) // 2])


def home(name):
    return f"switch/{TRAPPED_HOMEBREW}/{name}"


def t_manifest_dotdot(root):
    rebuild_homebrew(root, {home("README.txt"): b"trapped\n", f"switch/{TRAPPED_HOMEBREW}/../../bootloader/lantern-trap.txt":
                            b"A file that climbs out of its folder: a client refuses the whole entry.\n"}, sign=False)


def t_manifest_relative(root):
    def relative(entry):
        entry["package"]["manifest"][0]["path"] = entry["package"]["manifest"][0]["path"].lstrip("/")
        entry["package"]["manifest"][1]["path"] = "C:" + entry["package"]["manifest"][1]["path"]
        entry["package"]["manifest_sha256"] = client.manifest_sha256(entry["package"]["manifest"])
    rebuild_homebrew(root, {home("README.txt"): b"trapped\n", home("notes.txt"): b"trapped\n"}, sign=False,
                     mutate=relative)


def t_manifest_outside(root):
    rebuild_homebrew(root, {home("README.txt"): b"trapped\n",
                            "bootloader/payloads/lantern-trap.txt": b"Outside every root of the Switch's profile.\n"},
                     sign=False)


def t_manifest_too_long(root):
    rebuild_homebrew(root, {home(f"pages/{n:04}.txt"): b"" for n in range(4097)}, sign=False)


def t_newer_schema(root):
    for path in root.rglob("*.json"):
        doc = load(path)
        doc["schema"] = 2
        save(path, doc)


def t_oversized_document(root):
    path, page = first_app(root)
    path.write_bytes(dumps(page).encode() + b" " * ((33 << 20) - len(dumps(page))))


def t_deep_document(root):
    path, page = first_app(root)
    deep = "the bottom"
    for _ in range(40):
        deep = {"x": deep}
    page["items"][0]["x-deep"] = deep
    save(path, page)


def t_long_string(root):
    path, page = first_app(root)
    page["items"][0]["name"] = ("Frostline Tales, the long name " * 20)[:600]
    save(path, page)


def t_page_too_long(root):
    path, page = first_app(root)
    app = page["items"][0]
    page["items"] = [dict(app, id=f"{app['id']}-{n:04}") for n in range(1001)]
    page["total"] = 1001
    save(path, page)


def t_path_escape(root):
    path, page = first_app(root)
    app = page["items"][0]
    page["items"] = [dict(app, id=app["id"] + "-a", file="../outside/frostline-tales.nsp"),
                     dict(app, id=app["id"] + "-b", file="/" + app["file"]),
                     dict(app, id=app["id"] + "-c", file="https://files.example.org/frostline-tales.nsp")]
    page["total"] = 3
    save(path, page)


def t_bad_signature(root):
    def flip(entry):
        value = bytearray(base64.b64decode(entry["signature"]["value"]))
        value[10] ^= 0x01
        entry["signature"]["value"] = base64.b64encode(bytes(value)).decode()
    rebuild_homebrew(root, {home("README.txt"): b"trapped\n"}, mutate=flip)


def t_small_order_key(root):
    identity = bytes([1]) + bytes(31)        # a point of small order, the identity: [S]B = R + [k]A for S = 0

    def forge(entry):
        entry["signature"] = {"alg": "ed25519", "public_key": base64.b64encode(identity).decode(),
                              "value": base64.b64encode(identity + bytes(32)).decode()}
    rebuild_homebrew(root, {home("README.txt"): b"trapped\n"}, mutate=forge)


# (name, what, what a client does, the suite's checks that fail, the mutation): the SDK's hostile
# scenarios a static file can express, by their names there, then the static layout's own.
SCENARIOS = [
    ("bad-digest", ("A file whose bytes do not hash to the sha256 its document gives (a static library has no "
                    "Repr-Digest: the bytes are all there is)."),
     "Refuse the download once read (IntegrityError); keep nothing of it.", ["static.files"], t_bad_digest),
    ("extra-bytes", "A file with more bytes than its size.", "Refuse it as they arrive (IntegrityError).",
     ["static.files"], t_extra_bytes),
    ("truncated", "A file cut halfway.", "Fail the download and install nothing.", ["static.files"], t_truncated),
    ("manifest-dotdot", "A homebrew entry whose manifest climbs out of its folder with `..`.",
     "Refuse to install it (the install plan is refused).", ["static.homebrew"], t_manifest_dotdot),
    ("manifest-relative", "A homebrew entry whose manifest has a path that is not absolute, and a drive letter.",
     "Refuse to install it.", ["static.homebrew"], t_manifest_relative),
    ("manifest-outside", "A homebrew entry whose manifest writes outside every root of the platform's profile.",
     "Refuse to install it.", ["static.manifests"], t_manifest_outside),
    ("manifest-too-long", "A homebrew entry whose manifest has 4097 files (4096 at most).",
     "Refuse it (DocumentError).", ["static.homebrew"], t_manifest_too_long),
    ("newer-schema", "Every document has schema 2.",
     "Treat each as absent (NewerSchema), never as an error of the library, and write nothing back.",
     ["static.handshake"], t_newer_schema),
    ("oversized-document", "A page of apps of 33 MiB (32 MiB at most).",
     "Stop reading at 32 MiB and refuse it (DocumentError).", ["static.pages.apps"], t_oversized_document),
    ("deep-document", "A page nested 40 deep (16 at most).", "Refuse it (DocumentError).", ["static.limits"],
     t_deep_document),
    ("long-string", "An app whose name is 600 bytes (512 at most).", "Refuse it (DocumentError).",
     ["static.pages.apps"], t_long_string),
    ("page-too-long", "A page of 1001 apps (1000 at most).", "Refuse it (DocumentError).", ["static.pages.apps"],
     t_page_too_long),
    ("path-escape", "Apps whose file leaves the library's root: a `..` part, a leading `/`, another site.",
     "Read none of them (SPEC.md § 21.1): a static library's files are paths below its root.",
     ["static.paths", "static.files"], t_path_escape),
    ("bad-signature", "A homebrew entry whose signature does not verify.",
     "Refuse the signature, and the package with it.", ["static.signatures"], t_bad_signature),
    ("small-order-key", "A homebrew entry signed by a key of small order, S = 0: a forgery the bare equation accepts.",
     "Refuse the signature (it does not verify), whatever the message.", ["static.signatures"], t_small_order_key),
]


def trapped_source(source):
    """The demo's first Switch game, its cheat sets and Ines's homebrew: the base each scenario breaks."""
    app = next(a for a in source["apps"] if a["file"].startswith("switch/") and "art" in a)
    hb = next(h for h in source["homebrew"] if h["id"] == TRAPPED_HOMEBREW)
    return {**source, "uid": "0d1e2f3a-4b5c-4d6e-8f70-81a2b3c4d5e6", "apps": [app], "homebrew": [hb],
            "cheats": [c for c in source.get("cheats", []) if c["platform"] == "switch"
                       and c["title_id"] in app["file"]]}


def build(out, source_path=SOURCE):
    """The demo into `out` and its trapped variant into `out`/trapped/; a summary, or None without a source."""
    source = read_source(source_path)
    if source is None:
        print(f"make_demo: no {source_path.name}, or of a newer schema than this script: no demo", file=sys.stderr)
        return None
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    platforms = export(source, out, source["name"])["platforms"]
    trapped = out / "trapped"
    if trapped.exists():
        shutil.rmtree(trapped)
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base"
        mini = trapped_source(source)
        listed = []
        export(mini, base, "Lantern demo, trapped (broken on purpose, for testing clients)")
        for name, what, expect, checks, mutate in SCENARIOS:
            target = trapped / name
            shutil.copytree(base, target)
            hello = load(target / "lantern.json")
            hello["name"] = f"Lantern demo, trapped: {name} (broken on purpose, for testing clients)"
            save(target / "lantern.json", hello)
            mutate(target)
            listed.append({"name": name, "root": f"{name}/", "what": what, "expect": expect, "suite": checks})
    save(trapped / "scenarios.json", {"schema": SCHEMA, "about": "Static libraries broken on purpose, for testing "
                                      "Lantern clients (https://lantern.boreale.dev/demo/trapped/). Each one's root "
                                      "is its folder; `expect` is what a client does, `suite` the conformance "
                                      "suite's checks that refuse it.", "scenarios": listed})
    return {"platforms": platforms, "scenarios": len(listed)}


def run_suite(target):
    """conformance/run.py --static `target`: (exit code, report). Loading run.py binds its exceptions into
    the shared static_check and checks_v05 modules: what another copy of the suite bound there (a test's) is
    put back after the run."""
    import importlib.util

    import checks_v05
    import static_check
    saved = [(m, dict(vars(m))) for m in (static_check, checks_v05)]
    try:
        spec = importlib.util.spec_from_file_location("lantern_conformance_demo", ROOT / "conformance" / "run.py")
        suite = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(suite)
        out = io.StringIO()
        code = suite.main(["--static", str(target)], out=out)
        return code, out.getvalue()
    finally:
        for module, names in saved:
            vars(module).update(names)


def check(out):
    """The suite passes the demo at Lantern Static, and refuses each trapped scenario by its checks."""
    out = Path(out)
    problems = []
    code, report = run_suite(out)
    if code != 0 or "Lantern Static\n" not in report:
        problems.append("the demo does not reach Lantern Static:\n" + report)
    for s in load(out / "trapped" / "scenarios.json")["scenarios"]:
        code, report = run_suite(out / "trapped" / s["root"])
        failed = {line.split()[3] for line in report.splitlines() if line.startswith("FAIL")}
        missing = [c for c in s["suite"] if c not in failed]
        if code == 0 or "): none\n" not in report or missing:
            problems.append(f"trapped/{s['name']}: expected {', '.join(s['suite'])} to fail; failed: "
                            f"{', '.join(sorted(failed)) or 'nothing'}\n{report}")
        else:
            print(f"make_demo: trapped/{s['name']}: refused by {', '.join(sorted(failed))}")
    return problems


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("build", "check"):
        sys.exit(__doc__)
    if sys.argv[1] == "build":
        summary = build(sys.argv[2])
        print(f"make_demo: {summary}")
        return
    problems = check(sys.argv[2])
    for p in problems:
        print(f"make_demo: {p}")
    if problems:
        sys.exit(1)
    print("make_demo: the demo reaches Lantern Static, and every trapped scenario is refused as expected")


if __name__ == "__main__":
    main()
