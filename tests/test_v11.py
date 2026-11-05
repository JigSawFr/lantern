"""What draft 0.11 asks of a server, on the reference server and the suite: TLS 1.2 at least and
`Strict-Transport-Security` (SPEC.md § 2), the form of `uid` (§ 4.2), and a long lifetime with `immutable` for
what an address names by its SHA-256 (§ 14).

    python3 -m unittest discover -s tests

Each test names the requirements it checks (SPEC.md § 3.5).
"""
import json
import re
import shutil
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "conformance"))

import checks_v11
from test_conformance import Running, run_suite

from server import lantern_server as ls


class Rules(unittest.TestCase):
    def test_uid_is_a_lower_case_random_uuid(self):
        """L-4.2-9: versions 4 and 7 in lower case pass; 1 and 6 (hardware address), 5 and upper case do not."""
        good = ("6f1c2a8e-0b3d-4c5e-9a7f-1d2e3f4a5b6c", "01926f3c-7a4e-7b2a-8c9d-0e1f2a3b4c5d")
        bad = ("6f1c2a8e-0b3d-1c5e-9a7f-1d2e3f4a5b6c", "6f1c2a8e-0b3d-6c5e-9a7f-1d2e3f4a5b6c",
               "6f1c2a8e-0b3d-5c5e-9a7f-1d2e3f4a5b6c", "6F1C2A8E-0B3D-4C5E-9A7F-1D2E3F4A5B6C", "6f1c2a8e0b3d4c5e9a7f1d2e3f4a5b6c")
        for uid in good:
            self.assertRegex(uid, checks_v11.UID, uid)
        for uid in bad:
            self.assertNotRegex(uid, checks_v11.UID, uid)

    def test_the_reference_server_makes_a_version_4_uid(self):
        """L-4.2-9."""
        srv = Running()
        self.addCleanup(srv.close)
        doc = json.loads(srv.get("/.well-known/lantern")[2])
        self.assertRegex(doc["uid"], checks_v11.UID)

    def test_the_server_asks_for_tls_1_2_and_says_hsts_over_tls(self):
        """L-2-10 and L-2-11: the server's context starts at TLS 1.2, and its heads carry Strict-Transport-Security
        when the connection is TLS (and only then)."""
        source = (ROOT / "server" / "lantern_server.py").read_text(encoding="utf-8")
        self.assertIn("tls.minimum_version = ssl.TLSVersion.TLSv1_2", source)
        self.assertIsNotNone(re.search(r"isinstance\(self\.connection, ssl\.SSLSocket\).*\n.*Strict-Transport-Security", source))
        self.assertGreaterEqual(ls.HSTS_AGE, 15552000)


class SuiteAgainstReference(unittest.TestCase):
    def test_the_new_checks_see_what_the_server_shows(self):
        """The suite's checks of 0.11: uid and the chunk indexes' lifetime pass; TLS and HSTS skip on plain HTTP."""
        srv = Running()
        self.addCleanup(srv.close)
        code, report = run_suite(srv.url)
        self.assertEqual(code, 0, report)
        for cid in ("handshake.uid", "cache.immutable"):
            self.assertRegex(report, rf"PASS  § \S+\s+{cid} ", report)
        for cid in ("transport.tls", "transport.hsts"):
            self.assertRegex(report, rf"SKIP  § \S+\s+{cid} ", report)

    @unittest.skipUnless(shutil.which("openssl"), "openssl makes the certificate")
    def test_over_tls_the_suite_sees_the_floor_and_hsts(self):
        """L-2-10 and L-2-11: the checks pass over TLS, or the first skips where this machine's library cannot
        offer TLS 1.1 to try it; and the server says Strict-Transport-Security."""
        srv = Running(tls=True)
        self.addCleanup(srv.close)
        code, report = run_suite(srv.url, "--cafile", srv.cafile)
        self.assertEqual(code, 0, report)
        self.assertRegex(report, r"(PASS|SKIP)  § \S+\s+transport.tls ", report)
        self.assertRegex(report, r"PASS  § \S+\s+transport.hsts ", report)
        self.assertNotRegex(report, r"FAIL.*transport\.tls")


if __name__ == "__main__":
    unittest.main()
