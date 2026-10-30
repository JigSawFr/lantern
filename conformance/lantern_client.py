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
  (§ 8.1).

The roots are those of the profiles this text settles: the Switch's. A
client installs nothing of a platform it has no profile for (§ 6.1).
"""
import base64
import hashlib
import json

# Annex A: the roots a homebrew may write to, "{id}" its id, and the areas a
# port's data_root may lie in (the user approves that folder once).
ROOTS = {
    "switch": {"free": ("/switch/{id}/", "/config/{id}/"), "consent": ("/atmosphere/", "/switch/.overlays/"),
               "areas": ("/switch/", "/config/")},
}
# A package's arch: a list of these; a profile may allow fewer (Annex A).
ARCH_NAMES = ("aarch64", "armhf", "x86_64", "x86")
ARCHES = {"switch": ("aarch64",)}
ASSETS = ("included", "demo_included", "free_external", "user_owned")
HASH_FORMS = {"sha256": 64, "sha1": 40, "md5": 32}
KINDS = ("app", "game", "port", "emulator", "tool", "overlay", "sysmodule", "theme")
MANIFEST_LIMIT = 4096


class Refused(Exception):
    """A homebrew a client must not install; its message says why."""


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
        folded = entry["path"].casefold()
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


_GY = 4 * pow(5, _P - 2, _P) % _P
_G = (_x(_GY, 0), _GY, 1, _x(_GY, 0) * _GY % _P)


def ed25519_verify(public, message, signature):
    """Whether `signature` (64 bytes) is `public`'s (32 bytes) over `message`."""
    if len(public) != 32 or len(signature) != 64:
        return False
    a, r = _point(public), _point(signature[:32])
    s = int.from_bytes(signature[32:], "little")
    if a is None or r is None or s >= _L:
        return False
    h = int.from_bytes(hashlib.sha512(signature[:32] + public + message).digest(), "little") % _L
    left, right = _mul(s, _G), _add(r, _mul(h, a))
    return (left[0] * right[2] - right[0] * left[2]) % _P == 0 and (left[1] * right[2] - right[1] * left[2]) % _P == 0


# Kinds, arches and ports (SPEC.md § 8.1, § 8.2).

def kind_of(entry):
    """An entry's kind, as a client reads it: one it does not know is an app."""
    kind = entry.get("kind")
    return kind if kind in KINDS else "app"


def arch_ok(package, platform, mine=None):
    """Whether a package may run here: no arch, or a list that holds `mine`
    (the device's), or, without `mine`, a list of known arches the profile
    allows. A client skips the others."""
    arch = package.get("arch")
    if arch is None:
        return True
    if not (isinstance(arch, list) and arch and all(a in ARCH_NAMES for a in arch)):
        return False
    if mine is not None:
        return mine in arch
    return all(a in ARCHES.get(platform, ARCH_NAMES) for a in arch)


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
    if port.get("assets") not in ASSETS:
        out.append(f"assets {port.get('assets')!r} is not one of {', '.join(ASSETS)}")
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
        if "optional" in f and not isinstance(f["optional"], bool):
            out.append(f"data {path!r}: optional is not true or false")
        if "size" in f and not (isinstance(f["size"], int) and not isinstance(f["size"], bool) and f["size"] >= 0):
            out.append(f"data {path!r}: size is not an integer")
        accept = f.get("accept", [])
        if not isinstance(accept, list):
            out.append(f"data {path!r}: accept is not a list")
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
                out["missing"] += tries[0]["missing"] or [f["path"] for f in d["one_of"][0]]
                out["wrong"] += [w for t in tries for w in t["wrong"]]
                out["choices"].append([[f["path"] for f in o] for o in d["one_of"]])
        else:
            check([d], out)
    return out
