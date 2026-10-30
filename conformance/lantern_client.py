"""What a Lantern client checks before it installs a homebrew (SPEC.md § 8),
as a small reference: standard library only, for client authors to read and
for the conformance suite to apply to what a server serves.

- path_problem() and manifest_problems(): the paths of § 8.2;
- install_plan(): where a manifest writes, by the profile's roots (Annex A):
  the paths a client writes without asking, and those it shows the user
  first; a manifest with a path outside every root is refused whole;
- manifest_sha256() and signed_message(): the canonical bytes of § 8.2 and
  § 8.4;
- ed25519_verify(): RFC 8032's verification, in pure Python (slow, but a
  check per homebrew);
- key_change(): the pinning rule of § 8.4;
- kind_of(), arch_ok(): an entry's kind (an unknown one is an app) and
  whether a package's arch runs here (§ 8.1, § 8.2);
- port_problems(): a port's object as a server must serve it (its data_root
  under the profile's areas, its requires_data relative to it, never in the
  package), and launch_check(): what a client checks of that data before it
  starts the port, alternatives (one_of) and accepted hashes included
  (§ 8.1);
- requires_problems() and offer(): the shapes of an entry's requirements,
  and whether a device offers its package, with a warning, or refuses it
  (§ 8.7);
- signed requests (§ 5.4): ed25519_keypair() and ed25519_sign() (RFC 8032,
  in pure Python), key_thumbprint(), signature_base() and sign(), which
  give a request its Content-Digest, Signature-Input and Signature;
- rating caps (§ 5.6): rating_age() and above_cap(), what a server hides;
- grants (§ 19.3): grant_payload() and read_grant(), what a peer checks
  before it serves a file, and mirror_ok(), the mirrors a client may read
  (§ 19.2);
- sync (§ 20.4): sync_time() and sync_wins(), the merge rule;
- version codes (Annex A): version_code() and version_name() per profile.

The roots are those of the Switch's profile, and of the draft Linux one
(Annex A.6). A client installs nothing of a platform it has no profile for
(§ 4.3).
"""
import base64
import hashlib
import json
import re
import unicodedata

# Annex A: the roots a homebrew may write to, "{id}" its id, and the areas a
# port's data_root may lie in (the user approves that folder once).
ROOTS = {
    "switch": {"free": ("/switch/{id}/", "/config/{id}/"), "consent": ("/atmosphere/", "/switch/.overlays/"),
               "areas": ("/switch/", "/config/")},
    # "/" is the folder the client chose (a handheld's ports folder, $XDG_DATA_HOME on a computer).
    "linux": {"free": ("/{id}/",), "consent": ("/",), "areas": ("/",)},
}
# A package's arch: a list of these names, or later ones of the same form,
# which a client never takes for its own; a profile of one architecture has
# none (Annex A).
ARCH_NAMES = ("aarch64", "armhf", "x86", "x86_64", "riscv64")
ARCH = re.compile(r"^[a-z0-9_]{1,32}$")
ONE_ARCH = ("switch", "3ds", "vita", "ps4")
GENRES = ("action", "adventure", "rpg", "strategy", "simulation", "sports", "racing", "puzzle", "platformer",
          "shooter", "fighting", "music", "party", "education", "other")
TAGS_LIMIT = 32
# Requirements (SPEC.md § 8.7): requires.min's keys this client reads, and requires.gpu's names.
DOTTED_KEYS = ("glibc", "firmware", "atmosphere", "luma", "goldhen", "sdk")
GPU = ("gles2", "gles3", "gl", "vulkan")
REQUIRES_KEYS = ("text", "min", "gpu", "homebrew")
DOTTED = re.compile(r"^[0-9]+(\.[0-9]+){0,3}$")
SCREEN = re.compile(r"^([1-9][0-9]{0,5})x([1-9][0-9]{0,5})$")
ASSETS = ("included", "demo_included", "free_external", "user_owned")
DATA_LIMIT, ACCEPT_LIMIT, PACKAGES_LIMIT = 256, 32, 16     # SPEC.md § 13
HASH_FORMS = {"sha256": 64, "sha1": 40, "md5": 32}
KINDS = ("app", "game", "port", "emulator", "tool", "overlay", "sysmodule", "theme")
MANIFEST_LIMIT = 4096


class Refused(Exception):
    """A homebrew a client must not install; its message says why."""



def fold(text):
    """Text as SPEC.md § 2.3 compares names and paths: Unicode's canonical caseless match (NFD, default case
    folding, NFD)."""
    return unicodedata.normalize("NFD", unicodedata.normalize("NFD", text).casefold())

def path_problem(path):
    """Why `path` breaks SPEC.md § 8.2, or None."""
    if not isinstance(path, str):
        return "not a string"
    if not path.startswith("/"):
        return f"{path!r} is not absolute"
    if len(path.encode()) > 1024:
        return f"{path[:40]!r}…: above 1024 bytes"
    for part in path[1:].split("/"):
        if part in ("", ".", ".."):
            return f"{path!r} has an empty, . or .. part"
        if len(part.encode()) > 255:
            return f"{path!r} has a part above 255 bytes"
        if any(c in '\\:"' or ord(c) < 32 or ord(c) == 127 for c in part):
            return f"{path!r} has a \\, :, \" or control character"
    return None


def manifest_problems(manifest):
    """Every way `manifest` breaks SPEC.md § 8.2."""
    if not isinstance(manifest, list):
        return ["the manifest is not a list"]
    out = []
    if len(manifest) > MANIFEST_LIMIT:
        out.append(f"{len(manifest)} files, above {MANIFEST_LIMIT}")
    seen = set()
    for entry in manifest:
        if not isinstance(entry, dict):
            out.append("an entry is not an object")
            continue
        problem = path_problem(entry.get("path"))
        if problem:
            out.append(problem)
            continue
        folded = fold(entry["path"])
        if folded in seen:
            out.append(f"{entry['path']!r} twice, when case is ignored")
        seen.add(folded)
        if not isinstance(entry.get("size"), int) or not isinstance(entry.get("sha256"), str):
            out.append(f"{entry['path']!r} without its size and sha256")
    return out


def manifest_of(package):
    """A package's manifest: its own, a single file's, or none (the system's installer installs it)."""
    if "manifest" in package:
        return package["manifest"]
    if "path" in package:
        return [{"path": package["path"], "size": package["size"], "sha256": package["sha256"]}]
    return []


def install_plan(entry):
    """{"free": [...], "consent": [...]}: the paths a client writes without
    asking, and those it shows the user and writes only once they agree.
    Refused when the platform has no profile, or a path breaks § 8.2 or lies
    outside every root."""
    platform, hid = entry.get("platform"), entry.get("id")
    roots = ROOTS.get(platform)
    if roots is None:
        raise Refused(f"no profile for {platform!r}: nothing of it is installed")
    manifest = manifest_of(entry.get("package", {}))
    problems = manifest_problems(manifest)
    if problems:
        raise Refused("; ".join(problems[:3]))
    free = [r.format(id=hid) for r in roots["free"]]
    consent = [r.format(id=hid) for r in roots["consent"]]
    plan = {"free": [], "consent": []}
    for e in manifest:
        if any(e["path"].startswith(r) for r in free):
            plan["free"].append(e["path"])
        elif any(e["path"].startswith(r) for r in consent):
            plan["consent"].append(e["path"])
        else:
            raise Refused(f"{e['path']!r} is outside {platform}'s roots")
    return plan


def manifest_sha256(manifest):
    """The SHA-256 of the manifest's canonical form (SPEC.md § 8.2)."""
    entries = sorted(manifest, key=lambda e: e["path"].encode())
    canonical = "[" + ",".join('{"path":%s,"sha256":"%s","size":%d}' % (  # noqa: UP031 - the canonical bytes, spelled out
        json.dumps(e["path"], ensure_ascii=False), e["sha256"], e["size"]) for e in entries) + "]"
    return hashlib.sha256(canonical.encode()).hexdigest()


def signed_message(entry):
    """The bytes an author signs (SPEC.md § 8.4)."""
    p = entry["package"]
    return ('{"build":%d,"id":"%s","manifest_sha256":"%s","platform":"%s","purpose":"lantern-homebrew-1",'  # noqa: UP031 - the canonical bytes, spelled out
            '"sha256":"%s"}' % (entry["build"], entry["id"], p["manifest_sha256"], entry["platform"],
                                p["sha256"])).encode()


def verify_signature(entry):
    """True or False for a signed entry, None for an unsigned one."""
    sig = entry.get("signature")
    if sig is None:
        return None
    try:
        public, value = base64.b64decode(sig["public_key"], validate=True), base64.b64decode(sig["value"], validate=True)
    except (KeyError, TypeError, ValueError):
        return False
    return sig.get("alg") == "ed25519" and ed25519_verify(public, signed_message(entry), value)


def key_fingerprint(public_b64):
    """A key's short fingerprint, for people (SPEC.md § 8.4, in the form of § 5.3)."""
    digest = hashlib.sha256(base64.b64decode(public_b64)).hexdigest()
    return " ".join(digest[i:i + 4].upper() for i in range(0, 16, 4))


def key_change(pinned, entry):
    """SPEC.md § 8.4: "pin" on a first install (pinned is None), "same", or
    "changed": another key, or none after one; installed only if the user
    explicitly accepts it. `pinned` is "" for an id first installed unsigned."""
    offered = (entry.get("signature") or {}).get("public_key", "")
    if pinned is None:
        return "pin"
    return "same" if offered == pinned else "changed"


# Ed25519 verification (RFC 8032, § 5.1.7), after its reference code.

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _x(y, sign):
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P)
    if x2 % _P == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _I % _P
    if (x * x - x2) % _P:
        return None
    return _P - x if (x & 1) != sign else x


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    A, B = (y1 - x1) * (y2 - x2) % _P, (y1 + x1) * (y2 + x2) % _P
    C, D = 2 * t1 * t2 * _D % _P, 2 * z1 * z2 % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return E * F % _P, G * H % _P, F * G % _P, E * H % _P


def _mul(s, point):
    q = (0, 1, 1, 0)
    while s:
        if s & 1:
            q = _add(q, point)
        point, s = _add(point, point), s >> 1
    return q


def _point(raw):
    y = int.from_bytes(raw, "little")
    x = _x(y & ((1 << 255) - 1), y >> 255)
    return None if x is None else (x, y & ((1 << 255) - 1), 1, x * (y & ((1 << 255) - 1)) % _P)


def small_order(point):
    """Whether [8]P is the identity: one of the 8 points of small order."""
    q = _mul(8, point)
    return q[0] % _P == 0 and (q[1] - q[2]) % _P == 0


_GY = 4 * pow(5, _P - 2, _P) % _P
_G = (_x(_GY, 0), _GY, 1, _x(_GY, 0) * _GY % _P)


_TABLE = []         # _TABLE[i][j]: j * 16**i * G, made at the first use


def _base(s):
    """s * G, by windows of 4 bits over a table of G's multiples (the same point as _mul(s, _G), faster)."""
    if not _TABLE:
        point = _G
        for _ in range(64):
            row = [(0, 1, 1, 0), point]
            for _ in range(14):
                row.append(_add(row[-1], point))
            _TABLE.append(row)
            point = _add(row[-1], point)
    q, i = (0, 1, 1, 0), 0
    while s:
        if s & 15:
            q = _add(q, _TABLE[i][s & 15])
        s, i = s >> 4, i + 1
    return q


def ed25519_verify(public, message, signature):
    """Whether `signature` (64 bytes) is `public`'s (32 bytes) over `message`."""
    if len(public) != 32 or len(signature) != 64:
        return False
    a, r = _point(public), _point(signature[:32])
    s = int.from_bytes(signature[32:], "little")
    # A key or an R of small order, or not canonically encoded, is refused before the equation (SPEC.md
    # § 8.4): with S = 0 they satisfy it for about one message in 8.
    if a is None or r is None or s >= _L or small_order(a) or small_order(r):
        return False
    h = int.from_bytes(hashlib.sha512(signature[:32] + public + message).digest(), "little") % _L
    left, right = _base(s), _add(r, _mul(h, a))
    return (left[0] * right[2] - right[0] * left[2]) % _P == 0 and (left[1] * right[2] - right[1] * left[2]) % _P == 0


# Kinds, arches and ports (SPEC.md § 8.1, § 8.2).

def kind_of(entry):
    """An entry's kind, as a client reads it: one it does not know is an app."""
    kind = entry.get("kind")
    return kind if kind in KINDS else "app"


def arch_ok(package, platform, mine=None):
    """Whether a package may run here: without `mine`, whether its arch is
    well formed for the platform (none on a platform of one architecture, a
    list otherwise); with `mine` (the device's), whether the list holds it,
    or there is none. A client skips the packages that do not fit."""
    arch = package.get("arch")
    if arch is None:
        return True
    if platform in ONE_ARCH or not (isinstance(arch, list) and arch and all(
            isinstance(a, str) and ARCH.match(a) for a in arch)):
        return False
    return mine is None or mine in arch


def pick_package(entry, mine):
    """The package a device of arch `mine` installs (SPEC.md § 8.2): one whose
    arch lists it, or else one without arch; None when none fits."""
    packages = [entry.get("package") or {}] + list(entry.get("packages") or [])
    return next((p for p in packages if mine in (p.get("arch") or ())), None) or \
        next((p for p in packages if "arch" not in p), None)


def assets_of(entry):
    """A port's assets, as a client reads them: an unknown value is user_owned (SPEC.md § 8.6)."""
    assets = (entry.get("port") or {}).get("assets")
    return assets if assets in ASSETS else "user_owned"


def data_files(items):
    """Every file a requires_data names, those of each alternative (one_of) included."""
    for d in items if isinstance(items, list) else []:
        if isinstance(d, dict) and isinstance(d.get("one_of"), list):
            for option in d["one_of"]:
                yield from option if isinstance(option, list) else []
        else:
            yield d


def port_problems(entry):
    """Every way a port's `port` object breaks SPEC.md § 8.1: no original or
    engine, assets not of the list, a data_root outside the profile's areas,
    a data path that is not relative to it (absolute, `..`, a part § 8.2
    refuses), an alternative of one option, or a data file the package
    itself serves (its path in the manifest, or an accepted sha256 that is
    the package's or a manifest file's)."""
    port = entry.get("port")
    if not isinstance(port, dict):
        return ["no port object"]
    out = []
    original, engine = port.get("original"), port.get("engine")
    if not (isinstance(original, dict) and isinstance(original.get("name"), str) and original["name"]):
        out.append("original has no name")
    elif not isinstance(original.get("stores", []), list):
        out.append("original.stores is not a list")
    if not (isinstance(engine, dict) and isinstance(engine.get("name"), str) and engine["name"]):
        out.append("engine has no name")
    if not isinstance(port.get("assets"), str):
        out.append("no assets")
    root = port.get("data_root")
    if not (isinstance(root, str) and root.endswith("/") and path_problem(root[:-1]) is None):
        return out + [f"data_root {root!r} is not a folder's path"]
    areas = (ROOTS.get(entry.get("platform")) or {}).get("areas")
    if areas is not None and not any(root.startswith(a) and root != a for a in areas):
        out.append(f"data_root {root!r} is not under {', '.join(areas)}")
    items = port.get("requires_data", [])
    if not isinstance(items, list):
        return out + ["requires_data is not a list"]
    for d in items:
        if isinstance(d, dict) and "one_of" in d:
            options = d["one_of"]
            if not (isinstance(options, list) and len(options) >= 2 and all(isinstance(o, list) and o for o in options)):
                out.append("one_of has fewer than two alternatives, or an empty one")
    if len(list(data_files(items))) > DATA_LIMIT:
        out.append(f"more than {DATA_LIMIT} data files")
    def paths(files):
        return [f.get("path") for f in files if isinstance(f, dict)]
    single = paths([d for d in items if not (isinstance(d, dict) and "one_of" in d)])
    for group in [single] + [single + paths(o) for d in items if isinstance(d, dict) and isinstance(d.get("one_of"), list)
                             for o in d["one_of"] if isinstance(o, list)]:
        if len(set(map(str, group))) != len(group):
            out.append("a data path twice")
            break
    package = entry.get("package") or {}
    manifest = manifest_of(package) if isinstance(package, dict) else []
    shipped = {m.get("path") for m in manifest if isinstance(m, dict)}
    served = {package.get("sha256")} | {m.get("sha256") for m in manifest if isinstance(m, dict)}
    for f in data_files(items):
        if not isinstance(f, dict):
            out.append("a data file is not an object")
            continue
        path = f.get("path")
        if not isinstance(path, str) or path.startswith("/"):
            out.append(f"data path {path!r} is not relative to data_root")
            continue
        problem = path_problem(root + path)
        if problem:
            out.append(f"data path {path!r}: {problem}")
            continue
        if root + path in shipped:
            out.append(f"data {root + path!r} is in the package: Lantern never serves a port's data")
        if not isinstance(f.get("hint"), str) or not f["hint"]:
            out.append(f"data {path!r}: no hint saying where the user finds it")
        if "optional" in f and not isinstance(f["optional"], bool):
            out.append(f"data {path!r}: optional is not true or false")
        if "size" in f and not (isinstance(f["size"], int) and not isinstance(f["size"], bool) and f["size"] >= 0):
            out.append(f"data {path!r}: size is not an integer")
        accept = f.get("accept", [])
        if not isinstance(accept, list) or len(accept) > ACCEPT_LIMIT:
            out.append(f"data {path!r}: accept is not a list of {ACCEPT_LIMIT} versions at most")
            continue
        for a in accept:
            forms = [k for k in HASH_FORMS if isinstance(a, dict) and k in a]
            if not (isinstance(a, dict) and isinstance(a.get("label"), str) and forms and all(
                    isinstance(a[k], str) and len(a[k]) == HASH_FORMS[k]
                    and all(c in "0123456789abcdef" for c in a[k]) for k in forms)):
                out.append(f"data {path!r}: an accepted version without its label or a hash of a known form")
            elif a.get("sha256") in served:
                out.append(f"data {path!r}: the package serves a file of an accepted hash")
    return out


def file_hashes(data):
    """The hashes a client compares a data file's accepted versions with."""
    return {k: hashlib.new(k, data).hexdigest() for k in HASH_FORMS}


def accepted(f, hashes):
    """Whether a present file (its file_hashes) is one of `f`'s accepted versions; any, without a list."""
    return not f.get("accept") or any(all(a[k] == hashes.get(k) for k in HASH_FORMS if k in a) for a in f["accept"])


def launch_check(entry, present):
    """What a client checks before it starts a port (SPEC.md § 8.1). `present`
    maps a path relative to data_root (exact, case included) to file_hashes()
    of the file there. Returns {"missing", "wrong", "absent_optional",
    "choices"}: the port starts only when missing and wrong are both empty;
    for a one_of group none of whose alternatives is complete and right,
    "missing" names the group's first files, and "choices" every alternative,
    so that the client can guide the user."""
    out = {"missing": [], "wrong": [], "absent_optional": [], "choices": []}

    def check(files, into):
        for f in files:
            if f["path"] not in present:
                (into["absent_optional"] if f.get("optional") else into["missing"]).append(f["path"])
            elif not accepted(f, present[f["path"]]):
                into["wrong"].append(f["path"])

    for d in (entry.get("port") or {}).get("requires_data", []):
        if "one_of" in d:
            tries = []
            for option in d["one_of"]:
                result = {"missing": [], "wrong": [], "absent_optional": []}
                check(option, result)
                tries.append(result)
            if not any(not t["missing"] and not t["wrong"] for t in tries):
                if d.get("optional") and not any(t["wrong"] for t in tries):
                    out["absent_optional"] += [f["path"] for f in d["one_of"][0]]
                    continue
                out["missing"] += tries[0]["missing"] or [f["path"] for f in d["one_of"][0]]
                out["wrong"] += [w for t in tries for w in t["wrong"]]
                out["choices"].append([[f["path"] for f in o] for o in d["one_of"]])
        else:
            check([d], out)
    return out


# Requirements (SPEC.md § 8.7).

def requires_problems(entry):
    """Every way an entry's requires breaks SPEC.md § 8.7's shapes (the keys
    this client knows; the others are a later version's, or a vendor's)."""
    requires = entry.get("requires")
    if requires is None:
        return []
    if not isinstance(requires, dict):
        return ["requires is not an object"]
    out = []
    if not isinstance(requires.get("text"), str) or not requires["text"]:
        out.append("requires has no text")
    low = requires.get("min", {})
    if not isinstance(low, dict):
        out.append("requires.min is not an object")
        low = {}
    for k, v in low.items():
        if k == "ram_mb" and not (isinstance(v, int) and not isinstance(v, bool) and v >= 1):
            out.append(f"requires.min.ram_mb {v!r} is not a positive integer")
        elif k == "screen" and not (isinstance(v, str) and SCREEN.match(v)):
            out.append(f"requires.min.screen {v!r} is not <width>x<height>")
        elif k in DOTTED_KEYS and not (isinstance(v, str) and DOTTED.match(v)):
            out.append(f"requires.min.{k} {v!r} is not a dotted version")
    gpu = requires.get("gpu")
    if gpu is not None and not (isinstance(gpu, list) and gpu and all(isinstance(g, str) and g for g in gpu)):
        out.append("requires.gpu is not a list of names")
    return out


def _dotted(value):
    parts = [int(p) for p in value.split(".")]
    return parts + [0] * (4 - len(parts))


def offer(entry, device):
    """Whether a client offers an entry's package on `device` (SPEC.md § 8.7):
    ("offer", []), ("warn", [conditions it cannot read]) or ("refuse",
    [conditions that fail, and why]). `device` says what the client knows of
    itself, each key absent when it does not know: {"glibc": "2.31",
    "ram_mb": 1024, "screen": "1280x720", "gpu": ["gles2", "gles3"], and the
    profile's keys, such as "firmware": "18.0.0"}. A refusal wins over a
    warning; requires.homebrew is not a condition (the client installs it
    first)."""
    requires = entry.get("requires") or {}
    if not isinstance(requires, dict):
        return "warn", ["requires is not an object"]
    fails, unknown = [], []
    low = requires.get("min") if isinstance(requires.get("min"), dict) else {}
    if "min" in requires and not isinstance(requires["min"], dict):
        unknown.append("min")
    for k, v in low.items():
        mine = device.get(k)
        if k == "ram_mb" and isinstance(v, int) and not isinstance(v, bool):
            if not isinstance(mine, int):
                unknown.append(f"ram_mb {v} (this device's memory is unknown)")
            elif mine < v:
                fails.append(f"ram_mb: {v} MiB or more; this device has {mine}")
        elif k == "screen" and isinstance(v, str) and SCREEN.match(v):
            want = tuple(map(int, SCREEN.match(v).groups()))
            have = SCREEN.match(mine) if isinstance(mine, str) else None
            if have is None:
                unknown.append(f"screen {v} (this device's screen is unknown)")
            elif any(h < w for h, w in zip(map(int, have.groups()), want)):
                fails.append(f"screen: {v} or larger; this device's is {mine}")
        elif k in DOTTED_KEYS and isinstance(v, str) and DOTTED.match(v):
            if not (isinstance(mine, str) and DOTTED.match(mine)):
                unknown.append(f"{k} {v} (this device's is unknown)")
            elif _dotted(mine) < _dotted(v):
                fails.append(f"{k}: {v} or later; this device has {mine}")
        else:
            unknown.append(f"min.{k} {v!r}")
    if "gpu" in requires:
        gpu = requires["gpu"] if isinstance(requires["gpu"], list) else []
        known = [g for g in gpu if g in GPU]
        mine = device.get("gpu")
        if not isinstance(mine, list):
            unknown.append("gpu " + ", ".join(map(str, gpu)) + " (this device's graphics are unknown)")
        elif not any(g in mine for g in known):
            if known and len(known) == len(gpu):
                fails.append("gpu: one of " + ", ".join(gpu) + "; this device has " + (", ".join(mine) or "none"))
            else:
                unknown.append("gpu " + ", ".join(str(g) for g in gpu if g not in GPU))
    for k in requires:
        if k not in REQUIRES_KEYS and not (isinstance(k, str) and k.startswith("x-")):
            unknown.append(k)
    if fails:
        return "refuse", fails
    return ("warn", unknown) if unknown else ("offer", [])


# Ed25519 signing (RFC 8032, § 5.1.5 and 5.1.6), for a client's device key
# (SPEC.md § 5.4). Pure Python: slow, but a request needs one signature.
# Not constant-time: a library on a device uses its platform's, or
# Monocypher's; this one is for the suite, the tests and the vectors.

def _encode(point):
    x, y, z, _ = point
    zi = pow(z, _P - 2, _P)
    x, y = x * zi % _P, y * zi % _P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _secret(seed):
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def ed25519_public(seed):
    """The 32-byte public key of a 32-byte seed (the private key)."""
    return _encode(_base(_secret(seed)[0]))


def ed25519_sign(seed, message):
    """The 64-byte Ed25519 signature of `message` by the key of `seed`."""
    a, prefix = _secret(seed)
    public = _encode(_base(a))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % _L
    big_r = _encode(_base(r))
    k = int.from_bytes(hashlib.sha512(big_r + public + message).digest(), "little") % _L
    return big_r + ((r + k * a) % _L).to_bytes(32, "little")


def ed25519_keypair():
    """(seed, public key): a new device key, from the system's randomness."""
    import secrets
    seed = secrets.token_bytes(32)
    return seed, ed25519_public(seed)


# Signed requests (SPEC.md § 5.4, RFC 9421).

LABEL = "lantern"


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def key_thumbprint(public):
    """keyid: the base64url, without padding, of the SHA-256 of the key's 32 bytes."""
    return b64url(hashlib.sha256(public).digest())


def content_digest(body):
    """Content-Digest (RFC 9530) of a request's body, sha-256."""
    return "sha-256=:" + base64.b64encode(hashlib.sha256(body).digest()).decode() + ":"


def target_uri(scheme, host, port, path_and_query):
    """@target-uri (RFC 9421 § 2.2.2) as SPEC.md § 5.4 gives it: the host in
    lower case, its port only when not the scheme's default, the path and
    query as sent."""
    default = {"https": 443, "http": 80}[scheme]
    authority = host.lower() + ("" if port in (None, default) else f":{port}")
    return f"{scheme}://{authority}{path_and_query}"


def signature_params(components, created, nonce, keyid):
    """The value of Signature-Input's lantern member, which is also @signature-params."""
    inner = " ".join(f'"{c}"' for c in components)
    return f'({inner});created={created};nonce="{nonce}";keyid="{keyid}";alg="ed25519"'


def signature_base(method, uri, authorization, digest, created, nonce, keyid):
    """(the signature base, the Signature-Input's lantern member) of a request
    (SPEC.md § 5.4). `authorization` None for a pairing's poll; `digest` the
    request's Content-Digest, None without a body."""
    components, lines = ["@method", "@target-uri"], [f'"@method": {method.upper()}', f'"@target-uri": {uri}']
    if authorization is not None:
        components.append("authorization")
        lines.append(f'"authorization": {authorization}')
    if digest is not None:
        components.append("content-digest")
        lines.append(f'"content-digest": {digest}')
    params = signature_params(components, created, nonce, keyid)
    lines.append(f'"@signature-params": {params}')
    return "\n".join(lines), params


def new_nonce():
    import secrets
    return b64url(secrets.token_bytes(16))


def sign(seed, method, uri, authorization=None, body=b"", created=None, nonce=None):
    """The headers a signed request adds (SPEC.md § 5.4): Content-Digest when
    it has a body, Signature-Input and Signature."""
    import time
    created = int(time.time()) if created is None else created
    nonce = new_nonce() if nonce is None else nonce
    digest = content_digest(body) if body else None
    base, params = signature_base(method, uri, authorization, digest, created, nonce,
                                  key_thumbprint(ed25519_public(seed)))
    value = base64.b64encode(ed25519_sign(seed, base.encode())).decode()
    headers = {"Signature-Input": f"{LABEL}={params}", "Signature": f"{LABEL}=:{value}:"}
    if digest:
        headers["Content-Digest"] = digest
    return headers


# Grants and mirrors (SPEC.md § 19).

PRIVATE_NETS = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7", "fe80::/10")
LOOPBACK_NETS = ("127.0.0.0/8", "::1/128")     # plain HTTP for testing (SPEC.md § 2, § 19.2)


def grant_payload(uid, sha256, size, exp):
    """A grant's payload (SPEC.md § 19.3): these keys in this order, no space."""
    return (f'{{"exp":{exp},"purpose":"lantern-grant-1","sha256":"{sha256}","size":{size},"uid":"{uid}"}}').encode()


def _unb64url(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def read_grant(grant, keys, now):
    """The payload of a grant a peer takes (SPEC.md § 19.4): it verifies by the grant key of the server it names,
    among `keys` ({uid: the key's 32 bytes}), and `exp` is not before `now`; None otherwise."""
    if not (isinstance(grant, str) and len(grant) <= 1024 and re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{86}", grant)):
        return None
    payload_b64, sig_b64 = grant.split(".")
    try:
        payload, signature = _unb64url(payload_b64), _unb64url(sig_b64)
        doc = json.loads(payload.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not (isinstance(doc, dict) and doc.get("purpose") == "lantern-grant-1" and isinstance(doc.get("uid"), str)
            and isinstance(doc.get("sha256"), str) and isinstance(doc.get("exp"), int)
            and isinstance(doc.get("size"), int)):
        return None
    key = keys.get(doc["uid"])
    if key is None or payload != grant_payload(doc["uid"], doc["sha256"], doc["size"], doc["exp"]):
        return None
    if doc["exp"] < now or not ed25519_verify(key, payload, signature):
        return None
    return doc


def mirror_ok(url):
    """Whether a client may read a mirror (SPEC.md § 19.2): HTTPS, or plain HTTP at an address of a private
    network, or of loopback for testing (§ 2)."""
    import ipaddress
    from urllib.parse import urlsplit
    if not isinstance(url, str):
        return False
    try:
        u = urlsplit(url)
    except ValueError:
        return False
    if u.scheme == "https" and u.netloc:
        return True
    try:
        ip = ipaddress.ip_address((u.hostname or "").split("%")[0])
    except ValueError:
        return False
    return u.scheme == "http" and any(ip in ipaddress.ip_network(n) for n in PRIVATE_NETS + LOOPBACK_NETS)


# Sync (SPEC.md § 20.4).

def sync_time(text, now, skew):
    """An item's updated (UTC, to the millisecond) as a server keeps it: one more than `skew` seconds ahead of
    `now` (a datetime) is `now`; None when it is not such a time."""
    from datetime import datetime, timedelta
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d{1,3})?Z", text or "")
    if not m:
        return None
    try:
        when = datetime.fromisoformat(m.group(1) + (m.group(2) or ".0").ljust(4, "0") + "+00:00")
    except ValueError:
        return None
    when = now if when > now + timedelta(seconds=skew) else when
    return f"{when.year:04d}-" + when.strftime("%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sync_wins(sent, have):
    """Whether the item sent replaces the one kept (SPEC.md § 20.4)."""
    if have is None:
        return True
    if sent["updated"] != have["updated"]:
        return sent["updated"] > have["updated"]
    if bool(sent.get("deleted")) != bool(have.get("deleted")):
        return bool(sent.get("deleted"))
    return not sent.get("deleted") and canonical(sent["value"]) > canonical(have["value"])


# Rating caps (SPEC.md § 5.6).

RATING_AGES = {
    "PEGI": {"3": 3, "7": 7, "12": 12, "16": 16, "18": 18},
    "ESRB": {"EC": 3, "E": 6, "E10+": 10, "T": 13, "M": 17, "AO": 18},
    "CERO": {"A": 0, "B": 12, "C": 15, "D": 17, "Z": 18},
    "USK": {"0": 0, "6": 6, "12": 12, "16": 16, "18": 18},
    "ACB": {"G": 0, "PG": 8, "M": 15, "MA15+": 15, "R18+": 18, "X18+": 18},
    "CLASSIND": {"L": 0, "10": 10, "12": 12, "14": 14, "16": 16, "18": 18},
    "GRAC": {"ALL": 0, "12": 12, "15": 15, "18": 18},
}


def cap_age(cap):
    """The age a cap allows: its age, or its rating's in the table; None when the table cannot read it."""
    if "age" in cap:
        return cap["age"]
    return RATING_AGES.get(cap.get("system"), {}).get(cap.get("rating"))


def rating_age(ratings, cap):
    """The age of a title or homebrew of these `ratings` for `cap`: its
    rating of the cap's system when it has one, else the highest age the
    table reads; None when unrated."""
    ratings = [r for r in ratings or [] if isinstance(r, dict) and isinstance(r.get("system"), str)
               and isinstance(r.get("rating"), str)]
    if "system" in cap:
        own = [RATING_AGES.get(r.get("system"), {}).get(r.get("rating")) for r in ratings if r.get("system") == cap["system"]]
        own = [a for a in own if a is not None]
        if own:
            return max(own)
    ages = [RATING_AGES.get(r.get("system"), {}).get(r.get("rating")) for r in ratings]
    ages = [a for a in ages if a is not None]
    return max(ages) if ages else None


def above_cap(ratings, cap):
    """Whether a capped token must not see what has these ratings (SPEC.md § 5.6)."""
    if not cap:
        return False
    limit, age = cap_age(cap), rating_age(ratings, cap)
    if age is None:
        return cap.get("unrated") == "hide"
    return limit is None or age > limit


# Version codes (SPEC.md Annex A).

def version_code(platform, version):
    """`version_code` from a platform's own version: an integer (Switch, 3DS,
    Android) as it is, an APP_VER "XX.YY" (Vita, PS4) as XX*100+YY."""
    if platform in ("vita", "ps4"):
        m = re.fullmatch(r"([0-9]{2})\.([0-9]{2})", version)
        if not m:
            raise ValueError(f"{version!r} is not an APP_VER XX.YY")
        return int(m.group(1)) * 100 + int(m.group(2))
    if isinstance(version, int) and not isinstance(version, bool) and version >= 0:
        if platform == "3ds" and version >= 1 << 16:
            raise ValueError("a 3DS title version is 16 bits")
        return version
    raise ValueError(f"{version!r} is not a version of {platform}")


def version_name(platform, code):
    """The version people read, where the profile derives it from version_code (the 3DS's)."""
    if platform == "3ds":
        return f"{code >> 10}.{(code >> 4) & 0x3F}.{code & 0xF}"
    if platform in ("vita", "ps4"):
        return f"{code // 100:02d}.{code % 100:02d}"
    return None
