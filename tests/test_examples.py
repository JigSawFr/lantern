"""The worked examples (tools/build_site.py, example_blocks(); site/examples.html): read from the test vectors and
the examples the repository checks, and checked again here: the signed request's signature verifies with its
key, and the grant's with the server's grant key.

    python3 -m unittest discover -s tests
"""
import base64
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "server"))
import build_site  # noqa: E402
import lantern_server as ls  # noqa: E402


def vector(name):
    return json.loads((ROOT / "vectors" / f"{name}.json").read_text(encoding="utf-8"))


def b64url(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Examples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.blocks = build_site.example_blocks()

    def test_the_signed_request_is_one_whose_signature_verifies(self):
        sig = vector("signatures")
        accepted = sig["accepted"][0]
        signature = accepted["headers"]["Signature"].split(":")[1]
        ok = ls.ed25519.verify(base64.b64decode(sig["key"]["public_key"]), self.blocks["sign_base"].encode(),
                               base64.b64decode(signature))
        self.assertTrue(ok, "the example's signature does not verify against its base")
        # what is shown is what was signed: the request carries the base's components
        for line in self.blocks["sign_request"].split("\n")[2:]:
            self.assertIn(line.split(": ", 1)[0], ("Authorization", "Signature-Input", "Signature"))
        self.assertIn(accepted["headers"]["Authorization"], self.blocks["sign_base"])
        self.assertTrue(self.blocks["sign_request"].startswith("GET /api/lantern/v1/apps?page_size=50 HTTP/1.1\nHost: shelf.example.org\n"))

    def test_the_refused_twin_is_refused_for_what_the_page_says(self):
        self.assertEqual(self.blocks["sign_refused_code"], "401 · signature_required")
        self.assertNotIn("Signature", self.blocks["sign_refused_headers"])

    def test_the_grant_verifies_with_the_grant_key(self):
        grants = vector("grants")
        payload, signature = self.blocks["grant"].split(".")
        self.assertEqual(b64url(payload).decode(), self.blocks["grant_payload"])
        self.assertTrue(ls.ed25519.verify(base64.b64decode(grants["key"]["public_key"]), b64url(payload), b64url(signature)))
        body = json.loads(self.blocks["grant_payload"])
        self.assertEqual(list(body), ["exp", "purpose", "sha256", "size", "uid"], "the keys' order is part of the bytes")

    def test_the_pairing_is_the_examples_the_schemas_check(self):
        for key, name in (("pair_1", "pairing-request"), ("pair_2", "pairing-code"), ("pair_4", "pairing-token")):
            body = self.blocks[key].split("\n\n", 1)[1]
            self.assertEqual(json.loads(body), json.loads((ROOT / "examples" / "v1" / f"{name}.json").read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
