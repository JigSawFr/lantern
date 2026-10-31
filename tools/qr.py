"""A QR code (ISO/IEC 18004) as an inline SVG, in pure Python: no package, no network.

    import qr
    qr.svg("https://lantern.boreale.dev/demo/", "The demo library's address")

Byte mode, error correction level M, versions 1 to 10 (up to 213 bytes), the
mask of the lowest penalty. `modules(text)` gives the matrix (rows of booleans,
True a dark module), `svg(text, label)` a vector image: a quiet zone of four
modules, one path, no script, no style, no external reference, the label as
its `<title>` and `aria-label`. tools/build_site.py draws the demo library's
address with it; the code is checked against a decoder by tests/test_qr.py
when one is installed (OpenCV), and its tables against the standard's.
"""
import html

# Level M, per version (1 to 10): error correction codewords per block, then
# (blocks, data codewords per block) groups.
BLOCKS = {
    1: (10, [(1, 16)]), 2: (16, [(1, 28)]), 3: (26, [(1, 44)]), 4: (18, [(2, 32)]), 5: (24, [(2, 43)]),
    6: (16, [(4, 27)]), 7: (18, [(4, 31)]), 8: (22, [(2, 38), (2, 39)]), 9: (22, [(3, 36), (2, 37)]),
    10: (26, [(4, 43), (1, 44)]),
}
ALIGNMENT = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42],
             9: [6, 26, 46], 10: [6, 28, 50]}
REMAINDER = {1: 0, 2: 7, 3: 7, 4: 7, 5: 7, 6: 7, 7: 0, 8: 0, 9: 0, 10: 0}
MASKS = [
    lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0, lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0, lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0, lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
]


def _tables():
    exp, log, x = [0] * 512, [0] * 256, 1
    for i in range(255):
        exp[i], log[x] = x, i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


EXP, LOG = _tables()


def _mul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else EXP[LOG[a] + LOG[b]]


def _remainder(data: list, count: int) -> list:
    """The Reed-Solomon error correction codewords of `data`, over GF(256) (x^8+x^4+x^3+x^2+1)."""
    generator = [1]
    for i in range(count):
        generator = [(generator[j] if j < len(generator) else 0) ^ _mul(generator[j - 1] if j else 0, EXP[i])
                     for j in range(len(generator) + 1)]
    result = [0] * count
    for byte in data:
        factor = byte ^ result[0]
        result = result[1:] + [0]
        for j in range(count):
            result[j] ^= _mul(generator[j + 1], factor)
    return result


def _capacity(version: int) -> int:
    return sum(n * k for n, k in BLOCKS[version][1])


def _bits(value: int, length: int) -> list:
    return [(value >> (length - 1 - i)) & 1 for i in range(length)]


def _codewords(data: bytes, version: int) -> list:
    """The data (byte mode), padded, cut into blocks, each with its error correction, interleaved."""
    total = _capacity(version)
    bits = _bits(0b0100, 4) + _bits(len(data), 8 if version < 10 else 16)
    for byte in data:
        bits += _bits(byte, 8)
    bits += [0] * min(4, total * 8 - len(bits))
    bits += [0] * (-len(bits) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = [0xEC, 0x11]
    while len(words) < total:
        words.append(pad[(len(words) - len(bits) // 8) % 2])
    ec, groups = BLOCKS[version]
    blocks, at = [], 0
    for n, k in groups:
        for _ in range(n):
            blocks.append(words[at:at + k])
            at += k
    checks = [_remainder(b, ec) for b in blocks]
    out = []
    for i in range(max(len(b) for b in blocks)):
        out += [b[i] for b in blocks if i < len(b)]
    for i in range(ec):
        out += [c[i] for c in checks]
    return out


def _format_bits(mask: int) -> int:
    data = (0b00 << 3) | mask      # level M is 00
    value = data << 10
    for i in range(14, 9, -1):
        if value >> i & 1:
            value ^= 0x537 << (i - 10)
    return ((data << 10) | value) ^ 0x5412


def _version_bits(version: int) -> int:
    value = version << 12
    for i in range(17, 11, -1):
        if value >> i & 1:
            value ^= 0x1F25 << (i - 12)
    return (version << 12) | value


def _penalty(m: list) -> int:
    n, score = len(m), 0
    for grid in (m, [list(col) for col in zip(*m)]):
        for row in grid:
            run = 1
            for i in range(1, n):
                if row[i] == row[i - 1]:
                    run += 1
                    if run == 5:
                        score += 3
                    elif run > 5:
                        score += 1
                else:
                    run = 1
            line = "".join("1" if v else "0" for v in row)
            score += 40 * (line.count("10111010000") + line.count("00001011101"))
    for r in range(n - 1):
        for c in range(n - 1):
            if m[r][c] == m[r][c + 1] == m[r + 1][c] == m[r + 1][c + 1]:
                score += 3
    dark = sum(sum(row) for row in m) * 100 // (n * n)
    return score + 10 * (abs(dark - 50) // 5)


def modules(text: str) -> list:
    """The code of `text` as rows of booleans (True is a dark module)."""
    data = text.encode("utf-8")
    version = next((v for v in BLOCKS if len(data) + (2 if v < 10 else 3) <= _capacity(v)), None)
    if version is None:
        raise ValueError(f"qr: {len(data)} bytes do not fit versions 1 to 10")
    n = 17 + 4 * version
    cell = [[False] * n for _ in range(n)]
    fixed = [[False] * n for _ in range(n)]

    def put(r, c, dark):
        cell[r][c], fixed[r][c] = dark, True

    for r, c in ((0, 0), (0, n - 7), (n - 7, 0)):          # finder patterns, with their separators
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                rr, cc = r + dr, c + dc
                if 0 <= rr < n and 0 <= cc < n:
                    ring = max(abs(dr - 3), abs(dc - 3))
                    put(rr, cc, ring <= 3 and ring != 2 if 0 <= dr < 7 and 0 <= dc < 7 else False)
    positions = ALIGNMENT[version]
    for r in positions:
        for c in positions:
            if fixed[r][c]:
                continue                                      # on a finder pattern
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    put(r + dr, c + dc, max(abs(dr), abs(dc)) != 1)
    for i in range(8, n - 8):                                 # timing patterns
        put(6, i, i % 2 == 0)
        put(i, 6, i % 2 == 0)
    put(n - 8, 8, True)                                       # the dark module
    for i in range(9):                                        # format areas, filled later
        fixed[8][i] = fixed[i][8] = True
    for i in range(8):
        fixed[8][n - 1 - i] = fixed[n - 1 - i][8] = True
    if version >= 7:
        for i in range(18):
            fixed[i // 3][n - 11 + i % 3] = fixed[n - 11 + i % 3][i // 3] = True
    bits = []
    for word in _codewords(data, version):
        bits += _bits(word, 8)
    bits += [0] * REMAINDER[version]
    at, up, c = 0, True, n - 1
    while c > 0:
        if c == 6:
            c -= 1
        for r in (range(n - 1, -1, -1) if up else range(n)):
            for cc in (c, c - 1):
                if not fixed[r][cc]:
                    cell[r][cc] = bool(bits[at]) if at < len(bits) else False
                    at += 1
        up, c = not up, c - 2
    best = None
    for mask in range(8):
        m = [row[:] for row in cell]
        for r in range(n):
            for c in range(n):
                if not fixed[r][c] and MASKS[mask](r, c):
                    m[r][c] = not m[r][c]
        f = _format_bits(mask)
        for i in range(15):
            dark = bool(f >> i & 1)
            m[i if i < 6 else i + 1 if i < 8 else n - 15 + i][8] = dark
            m[8][n - 1 - i if i < 8 else 15 - i if i < 9 else 14 - i] = dark
        if version >= 7:
            v = _version_bits(version)
            for i in range(18):
                m[i // 3][n - 11 + i % 3] = m[n - 11 + i % 3][i // 3] = bool(v >> i & 1)
        score = _penalty(m)
        if best is None or score < best[0]:
            best = (score, m)
    return best[1]


def svg(text: str, label: str) -> str:
    """The code as an SVG image with `label` as its text alternative."""
    m = modules(text)
    n = len(m)
    size = n + 8
    path = "".join(f"M{c + 4} {r + 4}h1v1h-1z" for r, row in enumerate(m) for c, dark in enumerate(row) if dark)
    label = html.escape(label, quote=True)
    return (f'<svg class="qr" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" role="img" '
            f'aria-label="{label}" shape-rendering="crispEdges"><title>{label}</title>'
            f'<rect width="{size}" height="{size}" fill="#fff"/><path d="{path}" fill="#000"/></svg>')
