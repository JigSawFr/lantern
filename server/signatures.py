"""Signed requests (SPEC.md § 5.4, RFC 9421), as the reference server checks
them: the strict form of Signature-Input and Signature, the signature base,
the window of `created`, and the nonces already taken.

A request that carries a token bound to a device key, or polls a pairing
made with one, is signed by that key over "@method", "@target-uri", then
"authorization" when it has a token and "content-digest" when it has a
body; its parameters are created, nonce, keyid and alg="ed25519", in that
order, under the label `lantern`, alone. Anything else is refused with the
code SPEC.md § 5.4 gives. Standard library only; verification is
server/ed25519.py's.
"""
import base64
import hashlib
import re
import threading
import time

try:
    from server import ed25519
except ImportError:     # run from server/
    import ed25519

SKEW = 300              # seconds a created may differ from this server's clock (auth.skew)
HEADER_LIMIT = 1024     # Signature-Input and Signature, each (SPEC.md § 13)
INPUT = re.compile(r'lantern=\(((?:"[a-z@-]+")(?: "[a-z@-]+")*)\);created=([0-9]{1,12});'
                   r'nonce="([A-Za-z0-9_-]{22,64})";keyid="([A-Za-z0-9_-]{43})";alg="ed25519"')
VALUE = re.compile(r'lantern=:([A-Za-z0-9+/]{86}==):')


class Refused(Exception):
    """A signature refused: `code` is SPEC.md § 5.4's (signature_required, signature_invalid,
    signature_expired, signature_replayed)."""

    def __init__(self, code, detail):
        super().__init__(detail)
        self.code, self.detail = code, detail


def thumbprint(public):
    """keyid: the base64url of the SHA-256 of the key's 32 bytes, without padding."""
    return base64.urlsafe_b64encode(hashlib.sha256(public).digest()).rstrip(b"=").decode()


def short_fingerprint(public):
    """A key's short fingerprint, for people (SPEC.md § 5.3's form)."""
    digest = hashlib.sha256(public).hexdigest()
    return " ".join(digest[i:i + 4].upper() for i in range(0, 16, 4))


def components(with_token, with_body):
    """The components a request covers, in their order."""
    return ["@method", "@target-uri"] + (["authorization"] if with_token else []) \
        + (["content-digest"] if with_body else [])


def base(method, uri, authorization, digest, params):
    """The signature base (RFC 9421 § 2.5) of SPEC.md § 5.4's components."""
    lines = [f'"@method": {method}', f'"@target-uri": {uri}']
    if authorization is not None:
        lines.append(f'"authorization": {authorization}')
    if digest is not None:
        lines.append(f'"content-digest": {digest}')
    lines.append(f'"@signature-params": {params}')
    return "\n".join(lines)


class Nonces:
    """The nonces taken, per key, for twice the window: one is never taken twice within it."""

    def __init__(self, keep=2 * SKEW, limit=200000):
        self.keep, self.limit, self.seen, self.lock = keep, limit, {}, threading.Lock()

    def take(self, keyid, nonce):
        """True the first time, False when it was taken within the window."""
        now = time.monotonic()
        with self.lock:
            if len(self.seen) >= self.limit:
                self.seen = {k: t for k, t in self.seen.items() if t > now}
                if len(self.seen) >= self.limit:    # a flood: the oldest go first, still kept for `keep`
                    for k in sorted(self.seen, key=self.seen.get)[:self.limit // 10]:
                        del self.seen[k]
            key = (keyid, nonce)
            if self.seen.get(key, 0) > now:
                return False
            self.seen[key] = now + self.keep
            return True


def check(method, uri, headers, public, with_token, body_length, nonces, skew=SKEW, now=None):
    """Checks a request's signature by the key `public` (32 bytes), in SPEC.md § 5.4's order; raises
    Refused. `headers` gives the request's headers (a get(name) that returns None when absent)."""
    sig_input, value = headers.get("Signature-Input"), headers.get("Signature")
    if not sig_input or not value:
        raise Refused("signature_required", "This token is bound to a device key: sign the request (Signature-Input, "
                                            "Signature).")
    if len(sig_input) > HEADER_LIMIT or len(value) > HEADER_LIMIT:
        raise Refused("signature_invalid", "Signature-Input and Signature are 1 KiB at most.")
    m, v = INPUT.fullmatch(sig_input.strip()), VALUE.fullmatch(value.strip())
    if not m or not v:
        raise Refused("signature_invalid", "Signature-Input or Signature is not of the form SPEC.md § 5.4 gives "
                                           "(the label lantern alone, its parameters in their order).")
    covered = [c.strip('"') for c in m.group(1).split(" ")]
    digest = headers.get("Content-Digest")
    if covered != components(with_token, body_length > 0):
        raise Refused("signature_invalid", "The signature covers " + " ".join(covered) + ", not "
                      + " ".join(components(with_token, body_length > 0)) + ".")
    if body_length > 0 and not digest:
        raise Refused("signature_invalid", "A signed request with a body carries its Content-Digest.")
    if m.group(4) != thumbprint(public):
        raise Refused("signature_invalid", "keyid is not this token's key.")
    params = sig_input.strip()[len("lantern="):]
    message = base(method, uri, headers.get("Authorization") if with_token else None,
                   digest if body_length > 0 else None, params).encode()
    if not ed25519.verify(public, message, base64.b64decode(v.group(1))):
        raise Refused("signature_invalid", "The signature does not verify over the signature base of SPEC.md § 5.4.")
    created = int(m.group(2))
    clock = time.time() if now is None else now
    if abs(created - clock) > skew:
        raise Refused("signature_expired", f"created is {int(created - clock)} s from this server's clock; take its "
                                           f"Date, and sign within {skew} s of it.")
    if not nonces.take(m.group(4), m.group(3)):
        raise Refused("signature_replayed", "This nonce was taken already: a new one for each request.")
