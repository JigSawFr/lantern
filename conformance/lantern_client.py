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
- key_change(): the pinning rule of § 8.4.

The roots are those of the profiles this text settles: the Switch's. A
client installs nothing of a platform it has no profile for (§ 6.1).
"""
import base64
import hashlib
import json

# Annex A: the roots a homebrew may write to, "{id}" its id.
ROOTS = {
    "switch": {"free": ("/switch/{id}/", "/config/{id}/"), "consent": ("/atmosphere/", "/switch/.overlays/")},
}
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
    canonical = "[" + ",".join('{"path":%s,"sha256":"%s","size":%d}' % (
        json.dumps(e["path"], ensure_ascii=False), e["sha256"], e["size"]) for e in entries) + "]"
    return hashlib.sha256(canonical.encode()).hexdigest()


def signed_message(entry):
    """The bytes an author signs (SPEC.md § 8.4)."""
    p = entry["package"]
    return ('{"build":%d,"id":"%s","manifest_sha256":"%s","platform":"%s","purpose":"lantern-homebrew-1",'
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
