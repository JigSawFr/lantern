"""Ed25519 signature verification (RFC 8032, § 5.1.7), in pure Python, for
the reference server to check a homebrew's signature before it serves it
(SPEC.md § 8.4). It verifies only: the server never signs for an author.

Slow next to a C implementation (a few milliseconds a signature), which is
enough for a check per homebrew, remembered while the entry does not change.
It is not constant-time, and needs not be: it handles only public data.
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


def verify(public, message, signature):
    """Whether `signature` (64 bytes) is `public`'s (32 bytes) over `message`."""
    if len(public) != 32 or len(signature) != 64:
        return False
    a, r = decode(public), decode(signature[:32])
    s = int.from_bytes(signature[32:], "little")
    if a is None or r is None or s >= L:
        return False
    h = int.from_bytes(hashlib.sha512(signature[:32] + public + message).digest(), "little") % L
    return same(multiply(s, G), add(r, multiply(h, a)))
