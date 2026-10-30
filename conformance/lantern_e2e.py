"""End-to-end encrypted save backups (SPEC.md § 9.4), scheme
`lantern-save-e2e-1`, as a small reference in pure Python (standard library
only), for client authors to read, for the test vectors
(tools/make_vectors.py) and for the conformance suite, which encrypts the
backups it sends.

- hkdf_sha256(): RFC 5869;
- chacha20_block(), hchacha20(), poly1305(): RFC 8439 and
  draft-irtf-cfrg-xchacha-03;
- xchacha20poly1305_seal() and _open(): the AEAD, a 24-byte nonce;
- key_id() and wrapping_key(): what comes of a save key;
- encrypt() and decrypt(): a backup, its 88-byte header (the wrapped file
  key) and its chunks of 64 KiB, each sealed with its counter and whether it
  is the last (age's STREAM, with XChaCha20-Poly1305);
- phrase() and key_from_phrase(), qr_text() and key_from_qr(): the save key
  as a recovery phrase in the pairing alphabet, with a 24-bit check, or as a
  QR code's text.

Slow (pure Python: a few hundred KiB a second), not constant-time: a
reference to read and to test against, not for a device's real work, which
uses its system's or libsodium's XChaCha20-Poly1305.
"""
import hashlib
import hmac
import struct

SCHEME = "lantern-save-e2e-1"
MAGIC = b"LTNE2E01"
HEADER = 88                 # magic 8, key id 8, wrap nonce 24, wrapped file key 32 + 16
CHUNK = 65536
TAG = 16
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"     # the pairing alphabet (SPEC.md § 5.2)
QR_PREFIX = "LANTERN-SAVE-KEY-1:"


class Refused(Exception):
    """An encrypted backup, a phrase or a QR code a reader must refuse; its message says why."""


# HKDF (RFC 5869).

def hkdf_sha256(ikm, info, length=32, salt=b""):
    prk = hmac.new(salt or bytes(32), ikm, "sha256").digest()
    out, block = b"", b""
    for i in range(1, -(-length // 32) + 1):
        block = hmac.new(prk, block + info + bytes([i]), "sha256").digest()
        out += block
    return out[:length]


def key_id(save_key):
    """The save key's id: 8 bytes, 16 lower-case hex digits (SPEC.md § 9.4)."""
    return hkdf_sha256(save_key, b"lantern-save-e2e-1 key id", 8).hex()


def wrapping_key(save_key):
    return hkdf_sha256(save_key, b"lantern-save-e2e-1 wrap")


# ChaCha20, HChaCha20 and Poly1305 (RFC 8439, draft-irtf-cfrg-xchacha-03).

_MASK = 0xFFFFFFFF
_SIGMA = (0x61707865, 0x3320646E, 0x79622D32, 0x6B206574)


def _rounds(state):
    x = list(state)

    def qr(a, b, c, d):
        x[a] = (x[a] + x[b]) & _MASK
        x[d] ^= x[a]
        x[d] = ((x[d] << 16) | (x[d] >> 16)) & _MASK
        x[c] = (x[c] + x[d]) & _MASK
        x[b] ^= x[c]
        x[b] = ((x[b] << 12) | (x[b] >> 20)) & _MASK
        x[a] = (x[a] + x[b]) & _MASK
        x[d] ^= x[a]
        x[d] = ((x[d] << 8) | (x[d] >> 24)) & _MASK
        x[c] = (x[c] + x[d]) & _MASK
        x[b] ^= x[c]
        x[b] = ((x[b] << 7) | (x[b] >> 25)) & _MASK

    for _ in range(10):
        qr(0, 4, 8, 12)
        qr(1, 5, 9, 13)
        qr(2, 6, 10, 14)
        qr(3, 7, 11, 15)
        qr(0, 5, 10, 15)
        qr(1, 6, 11, 12)
        qr(2, 7, 8, 13)
        qr(3, 4, 9, 14)
    return x


def chacha20_block(key, counter, nonce):
    """One 64-byte block of ChaCha20 (RFC 8439 § 2.3): a 32-byte key, a 32-bit counter, a 12-byte nonce."""
    state = (*_SIGMA, *struct.unpack("<8I", key), counter & _MASK, *struct.unpack("<3I", nonce))
    out = _rounds(state)
    return struct.pack("<16I", *((a + b) & _MASK for a, b in zip(out, state)))


def chacha20_xor(key, counter, nonce, data):
    out = bytearray(len(data))
    for i in range(0, len(data), 64):
        block = chacha20_block(key, counter + i // 64, nonce)
        chunk = data[i:i + 64]
        out[i:i + len(chunk)] = bytes(a ^ b for a, b in zip(chunk, block))
    return bytes(out)


def hchacha20(key, nonce16):
    """HChaCha20 (draft-irtf-cfrg-xchacha-03 § 2.2): a 32-byte subkey from a key and 16 bytes of nonce."""
    x = _rounds((*_SIGMA, *struct.unpack("<8I", key), *struct.unpack("<4I", nonce16)))
    return struct.pack("<8I", *x[0:4], *x[12:16])


def poly1305(key, message):
    """Poly1305 (RFC 8439 § 2.5): a 16-byte tag of `message` under a 32-byte one-time key."""
    r = int.from_bytes(key[:16], "little") & 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
    s = int.from_bytes(key[16:], "little")
    p, acc = (1 << 130) - 5, 0
    for i in range(0, len(message), 16):
        n = int.from_bytes(message[i:i + 16] + b"\x01", "little")
        acc = (acc + n) * r % p
    return ((acc + s) & ((1 << 128) - 1)).to_bytes(16, "little")


def _pad16(data):
    return bytes(-len(data) % 16)


def _tag(key, nonce, aad, ciphertext):
    otk = chacha20_block(key, 0, nonce)[:32]
    mac = aad + _pad16(aad) + ciphertext + _pad16(ciphertext) + struct.pack("<QQ", len(aad), len(ciphertext))
    return poly1305(otk, mac)


def chacha20poly1305_seal(key, nonce, plaintext, aad=b""):
    """RFC 8439 § 2.8's AEAD: the ciphertext, then its 16-byte tag."""
    ciphertext = chacha20_xor(key, 1, nonce, plaintext)
    return ciphertext + _tag(key, nonce, aad, ciphertext)


def chacha20poly1305_open(key, nonce, sealed, aad=b""):
    """The plaintext; None when the tag does not match."""
    if len(sealed) < TAG:
        return None
    ciphertext, tag = sealed[:-TAG], sealed[-TAG:]
    if not hmac.compare_digest(_tag(key, nonce, aad, ciphertext), tag):
        return None
    return chacha20_xor(key, 1, nonce, ciphertext)


def xchacha20poly1305_seal(key, nonce24, plaintext, aad=b""):
    """XChaCha20-Poly1305 (draft-irtf-cfrg-xchacha-03 § 2.3): HChaCha20, then RFC 8439's AEAD."""
    return chacha20poly1305_seal(hchacha20(key, nonce24[:16]), bytes(4) + nonce24[16:], plaintext, aad)


def xchacha20poly1305_open(key, nonce24, sealed, aad=b""):
    return chacha20poly1305_open(hchacha20(key, nonce24[:16]), bytes(4) + nonce24[16:], sealed, aad)


# A backup (SPEC.md § 9.4).

def chunk_nonce(index, last):
    """Chunk `index`'s nonce: 16 zero bytes, the index on 7 bytes big-endian, 01 for the last chunk, 00 else."""
    return bytes(16) + index.to_bytes(7, "big") + (b"\x01" if last else b"\x00")


def header(save_key, file_key, wrap_nonce):
    """The 88-byte header: magic, key id, the wrap's nonce, and the file key sealed by the wrapping key."""
    start = MAGIC + bytes.fromhex(key_id(save_key))
    return start + wrap_nonce + xchacha20poly1305_seal(wrapping_key(save_key), wrap_nonce, file_key, start)


def encrypted_size(size):
    """The bytes of an encrypted backup of an archive of `size` bytes."""
    chunks = max(1, -(-size // CHUNK))
    return HEADER + size + TAG * chunks


def encrypt(save_key, archive, file_key, wrap_nonce):
    """The encrypted backup of `archive` (bytes). `file_key` (32 bytes) and `wrap_nonce` (24) are random, new
    for each backup (SPEC.md § 9.4): given here, so that the same ones give the same bytes (a resumed upload)."""
    head = header(save_key, file_key, wrap_nonce)
    pieces = [archive[i:i + CHUNK] for i in range(0, len(archive), CHUNK)] or [b""]
    out = [head]
    for i, piece in enumerate(pieces):
        out.append(xchacha20poly1305_seal(file_key, chunk_nonce(i, i == len(pieces) - 1), piece, head))
    return b"".join(out)


def read_header(data):
    """(key id, wrap nonce, wrapped file key) of an encrypted backup's header; Refused when it is not one."""
    if len(data) < HEADER or data[:8] != MAGIC:
        raise Refused("not a lantern-save-e2e-1 backup: no LTNE2E01 header")
    return data[8:16].hex(), data[16:40], data[40:88]


def decrypt(save_key, data):
    """The archive of an encrypted backup; Refused when its key id is another key's, its header or a chunk does
    not open, its last chunk is not marked last, or it goes on after it (SPEC.md § 9.4)."""
    kid, wrap_nonce, wrapped = read_header(data)
    if kid != key_id(save_key):
        raise Refused(f"a backup of the key {kid}, not of {key_id(save_key)}")
    head = data[:HEADER]
    file_key = xchacha20poly1305_open(wrapping_key(save_key), wrap_nonce, wrapped, head[:16])
    if file_key is None:
        raise Refused("the file key does not open: another key, or a header changed")
    body, out, index, pos = data[HEADER:], [], 0, 0
    while True:
        sealed = body[pos:pos + CHUNK + TAG]
        if len(sealed) < TAG:
            raise Refused(f"chunk {index} is cut, or missing: no last chunk")
        last = pos + len(sealed) >= len(body)
        piece = xchacha20poly1305_open(file_key, chunk_nonce(index, last), sealed, head)
        if piece is None:
            other = xchacha20poly1305_open(file_key, chunk_nonce(index, not last), sealed, head)
            if other is not None and last:
                raise Refused(f"chunk {index} ends the backup but is not marked last: chunks were dropped")
            if other is not None:
                raise Refused(f"chunk {index} is marked last, but more follows")
            raise Refused(f"chunk {index} does not open: changed, moved, or of another backup")
        if not last and len(piece) != CHUNK:
            raise Refused(f"chunk {index} is short but not the last")
        out.append(piece)
        pos += len(sealed)
        index += 1
        if last:
            return b"".join(out)


# Carrying the key (SPEC.md § 9.4).

def check_bytes(save_key):
    return hashlib.sha256(b"lantern-save-key" + save_key).digest()[:3]


def phrase(save_key):
    """The recovery phrase: 56 symbols of the pairing alphabet in 14 groups of 4, joined by '-'."""
    if len(save_key) != 32:
        raise ValueError("a save key is 32 bytes")
    n = int.from_bytes(save_key + check_bytes(save_key), "big")
    symbols = "".join(ALPHABET[(n >> (5 * (55 - i))) & 31] for i in range(56))
    return "-".join(symbols[i:i + 4] for i in range(0, 56, 4))


def key_from_phrase(text):
    """The save key a phrase gives, ignoring case, spaces and dashes; Refused when it is not 56 symbols of the
    alphabet or its check does not match."""
    symbols = "".join(c for c in str(text).upper() if c not in " -\t\r\n")
    if len(symbols) != 56 or any(c not in ALPHABET for c in symbols):
        raise Refused("a recovery phrase is 56 symbols of 23456789ABCDEFGHJKLMNPQRSTUVWXYZ")
    n = 0
    for c in symbols:
        n = n << 5 | ALPHABET.index(c)
    raw = n.to_bytes(35, "big")
    key, check = raw[:32], raw[32:]
    if not hmac.compare_digest(check, check_bytes(key)):
        raise Refused("the phrase's check does not match: a symbol is mistyped")
    return key


def qr_text(save_key):
    """The QR code's text: its alphanumeric mode holds it as it is."""
    return QR_PREFIX + phrase(save_key).replace("-", "")


def key_from_qr(text):
    if not str(text).startswith(QR_PREFIX):
        raise Refused(f"a save key's QR code begins with {QR_PREFIX}")
    return key_from_phrase(text[len(QR_PREFIX):])
