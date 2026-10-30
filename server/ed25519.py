"""Ed25519 (RFC 8032), in pure Python: verification (§ 5.1.7), for the
reference server to check a homebrew's signature before it serves it
(SPEC.md § 8.4) and a request's (§ 5.4); and signing (§ 5.1.6), with the
server's own grant key only (§ 19.3): it never signs for an author.

Slow next to a C implementation (a few milliseconds a signature), which is
enough for a check per homebrew, remembered while the entry does not change.
Verification is not constant-time, and needs not be: it handles only
public data. Signing is not constant-time either: a reference, whose grant
key signs statements worth a file for a few minutes.
"""
import hashlib

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def recover_x(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P:
        return None
    return P - x if (x & 1) != sign else x


def add(a, b):
    """The sum of two points in extended coordinates."""
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    pa, pb = (y1 - x1) * (y2 - x2) % P, (y1 + x1) * (y2 + x2) % P
    pc, pd = 2 * t1 * t2 * D % P, 2 * z1 * z2 % P
    e, f, g, h = pb - pa, pd - pc, pd + pc, pb + pa
    return e * f % P, g * h % P, f * g % P, e * h % P


def multiply(s, point):
    q = (0, 1, 1, 0)
    while s:
        if s & 1:
            q = add(q, point)
        point, s = add(point, point), s >> 1
    return q


def decode(raw):
    """The point of a 32-byte encoding, or None."""
    if len(raw) != 32:
        return None
    y = int.from_bytes(raw, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % P)


def encode(point):
    x, y, z, _ = point
    zi = pow(z, P - 2, P)
    x, y = x * zi % P, y * zi % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


GY = 4 * pow(5, P - 2, P) % P
G = (recover_x(GY, 0), GY, 1, recover_x(GY, 0) * GY % P)


def same(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % P == 0 and (a[1] * b[2] - b[1] * a[2]) % P == 0


IDENTITY = (0, 1, 1, 0)


def small_order(point):
    """Whether a point is of small order: one of the 8 whose [8]P is the identity."""
    return same(multiply(8, point), IDENTITY)


def verify(public, message, signature):
    """Whether `signature` (64 bytes) is `public`'s (32 bytes) over `message`.

    Refused before the equation (SPEC.md § 8.4): a key or an R that does not
    decode, or not canonically (y >= p, or x = 0 with its sign bit set), a key
    or an R of small order, and S >= L. Without that, a key of small order, an
    R of small order and S = 0 satisfy the cofactorless equation for about one
    message in 8: anyone could forge."""
    if len(public) != 32 or len(signature) != 64:
        return False
    a, r = decode(public), decode(signature[:32])
    s = int.from_bytes(signature[32:], "little")
    if a is None or r is None or s >= L or small_order(a) or small_order(r):
        return False
    h = int.from_bytes(hashlib.sha512(signature[:32] + public + message).digest(), "little") % L
    return same(multiply(s, G), add(r, multiply(h, a)))


def _secret(seed):
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(seed):
    """The 32-byte public key of a 32-byte seed (RFC 8032 § 5.1.5)."""
    return encode(multiply(_secret(seed)[0], G))


def sign(seed, message):
    """The 64-byte signature of `message` by the key of `seed` (RFC 8032 § 5.1.6)."""
    a, prefix = _secret(seed)
    public = encode(multiply(a, G))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % L
    big_r = encode(multiply(r, G))
    h = int.from_bytes(hashlib.sha512(big_r + public + message).digest(), "little") % L
    return big_r + ((r + h * a) % L).to_bytes(32, "little")
