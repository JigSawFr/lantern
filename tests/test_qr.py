"""tools/qr.py, the QR code of the demo library's address (site/README.md): pure Python, no decoder needed.

    python3 -m unittest discover -s tests

The known answer is the matrix of "https://lantern.boreale.dev/demo/" (version 3, level M), the same as the one
the `qrcode` package and OpenCV's decoder read back when it was written.
"""
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import qr  # noqa: E402

URL = "https://lantern.boreale.dev/demo/"
SHA256 = "d8ca93b2922443680d092aab5a0dfc0784e693271b8aa24e8fbbcadbd1160510"


def flat(matrix):
    return "\n".join("".join("1" if x else "0" for x in row) for row in matrix)


class QrTest(unittest.TestCase):
    def test_known_answer(self):
        m = qr.modules(URL)
        self.assertEqual(len(m), 29)                       # version 3
        self.assertEqual(hashlib.sha256(flat(m).encode()).hexdigest(), SHA256)

    def test_finder_patterns_and_timing(self):
        m = qr.modules(URL)
        n = len(m)
        for r, c in ((0, 0), (0, n - 7), (n - 7, 0)):
            self.assertTrue(all(m[r][c + i] and m[r + 6][c + i] and m[r + i][c] and m[r + i][c + 6] for i in range(7)))
            self.assertTrue(all(m[r + 3][c + 2 + i] for i in range(3)))   # the centre's 3 x 3
            self.assertFalse(m[r + 1][c + 1] or m[r + 5][c + 5])         # the light ring
        self.assertTrue(all(m[6][i] == (i % 2 == 0) for i in range(8, n - 8)))
        self.assertTrue(m[n - 8][8])                                      # the dark module

    def test_every_version_fits_its_size(self):
        for length, size in ((1, 21), (14, 21), (15, 25), (60, 33), (120, 45), (213, 57)):
            self.assertEqual(len(qr.modules("a" * length)), size, length)
        with self.assertRaises(ValueError):
            qr.modules("a" * 214)

    def test_tables(self):
        for version, (ec, groups) in qr.BLOCKS.items():       # the data capacity of level M, from the standard
            self.assertEqual(sum(n * k for n, k in groups), (16, 28, 44, 64, 86, 108, 124, 154, 182, 216)[version - 1])
            self.assertEqual(len(qr._codewords(b"x", version)), sum(n * (k + ec) for n, k in groups))

    def test_svg(self):
        svg = qr.svg(URL, "The demo's address <&>")
        self.assertIn('role="img"', svg)
        self.assertIn("&lt;&amp;&gt;</title>", svg)
        for forbidden in ("<script", "href=", "style="):
            self.assertNotIn(forbidden, svg)
        self.assertNotRegex(svg, r"\son\w+=")


if __name__ == "__main__":
    unittest.main()
