"""Canonical JSON (SPEC.md § 2.3) and chunk indexes (SPEC.md § 22), for the
reference server: standard library only.

- canonical(): RFC 8785's JSON Canonicalization Scheme, as sync's merge
  rule compares values (§ 20.4) and a chunk index is written (§ 22.1);
- cut(): lantern-cdc-1, the chunker of § 22.2: a gear hash over each byte
  from a chunk's min-th on, a chunk ending where its top bits are clear;
- index(): a file's chunk index, its document and its canonical bytes.

conformance/lantern_client.py has the same, written apart, for clients;
tools/make_vectors.py checks that both agree with vectors/chunks.json and
vectors/canonical-json.json.
"""
import hashlib
import json
from decimal import Decimal

ALG = "lantern-cdc-1"
SIZES = tuple(1 << b for b in range(16, 23))     # a chunker's size: 64 KiB to 4 MiB
CHUNKS_LIMIT = 100000       # chunks in an index (SPEC.md § 13)
INDEX_LIMIT = 8 << 20       # an index's bytes (SPEC.md § 13)
GEAR = tuple(int.from_bytes(hashlib.sha256(ALG.encode() + bytes([i])).digest()[:8], "big") for i in range(256))
MASK64 = (1 << 64) - 1
INT_LIMIT = (1 << 53) - 1


def number(x):
    """A number as ECMAScript writes it (RFC 8785 § 3.2.2.3)."""
    if isinstance(x, int) and abs(x) <= INT_LIMIT:
        return str(x)
    x = float(x)
    if x != x or x in (float("inf"), float("-inf")):
        raise ValueError("JSON has no NaN nor infinity")
    if x == 0:
        return "0"
    t = Decimal(repr(abs(x))).as_tuple()
    whole = "".join(map(str, t.digits))
    digits = whole.rstrip("0") or "0"
    n, k = len(whole) + t.exponent, len(digits)     # the value is 0.<digits> x 10^n
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * -n + digits
    else:
        body = digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + ("+" if n > 0 else "-") + str(abs(n - 1))
    return ("-" if x < 0 else "") + body


def text(value):
    """`value`'s canonical JSON as text, without recursion: a value nested deep is written as one nested less."""
    out, stack = [], [value]
    while stack:
        v = stack.pop()
        if isinstance(v, Raw):
            out.append(v)
        elif v is None or isinstance(v, bool):
            out.append({None: "null", True: "true", False: "false"}[v])
        elif isinstance(v, str):
            out.append(json.dumps(v, ensure_ascii=False))
        elif isinstance(v, (int, float)):
            out.append(number(v))
        elif isinstance(v, list):
            parts = [Raw("[")]
            for i, item in enumerate(v):
                parts += [Raw(",")] if i else []
                parts.append(item)
            stack += reversed(parts + [Raw("]")])
        elif isinstance(v, dict):
            keys = sorted(v, key=lambda k: k.encode("utf-16-be", "surrogatepass"))
            parts = [Raw("{")]
            for i, k in enumerate(keys):
                parts += [Raw(("," if i else "") + json.dumps(k, ensure_ascii=False) + ":"), v[k]]
            stack += reversed(parts + [Raw("}")])
        else:
            raise TypeError(f"not JSON: {type(v).__name__}")
    return "".join(out)


class Raw(str):
    """A piece of punctuation already written."""


def canonical(value):
    """`value`'s canonical JSON, UTF-8 (SPEC.md § 2.3)."""
    return text(value).encode("utf-8")


def cut(data, size):
    """[(offset, length)] of lantern-cdc-1's chunks of `data`, for a chunker of `size` (SPEC.md § 22.2)."""
    bits = size.bit_length() - 1
    low, high, mask = size >> 2, size << 2, ((1 << bits) - 1) << (64 - bits)
    gear, out, start, n, view = GEAR, [], 0, len(data), memoryview(data)
    while start < n:
        if n - start <= low:
            out.append((start, n - start))
            break
        end = min(start + high, n)
        at, h, i = end, 0, start + low
        for byte in view[start + low:end]:
            h = ((h << 1) + gear[byte]) & MASK64
            i += 1
            if not h & mask:
                at = i
                break
        out.append((start, at - start))
        start = at
    return out


def size_for(length):
    """The chunker's size for a file of `length` bytes: the smallest whose chunks stay about 16,384 and, whatever
    the bytes, within 100,000; None for a file too large for any."""
    for size in SIZES:
        if length // ((size >> 2) + 1) + 1 <= CHUNKS_LIMIT and length <= size * 16384:
            return size
    return SIZES[-1] if length // ((SIZES[-1] >> 2) + 1) + 1 <= CHUNKS_LIMIT else None


def index(data, size=None):
    """(document, canonical bytes) of the chunk index of `data` (SPEC.md § 22.1)."""
    size = size or size_for(len(data))
    chunks = [[n, hashlib.sha256(data[o:o + n]).hexdigest()] for o, n in cut(data, size)]
    doc = {"schema": 1, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
           "chunker": {"alg": ALG, "size": size}, "chunks": chunks}
    return doc, canonical(doc)
