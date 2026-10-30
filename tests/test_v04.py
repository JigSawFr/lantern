"""What draft 0.4 adds, on the reference server and the suite: signed requests
and their test vectors, keyed pairing, invitations, rating caps, the
administration API, languages, compression, withdrawn requests, Atlas ids,
the fuzz harness, and the requirement ids the suite and these tests cite.

    python3 -m unittest discover -s tests

Each test names the requirements it checks (SPEC.md § 3.5), such as
L-5.4-6; test_requirements checks that every id cited here exists.
"""
import base64
import contextlib
import gzip
import hashlib
import io
import json
import re
import subprocess
import sys
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "conformance"))
sys.path.insert(0, str(ROOT / "tools"))

import fuzz
import lantern_client as client
import library
import make_vectors
import requirements
from test_conformance import EVERY_SCOPE, USERS, Running, conformance, run_suite

from server import lantern_server as ls
from server import signatures

VECTORS = ROOT / "vectors"
ADMIN = "mila"          # USERS: every scope, admin included
FROSTLINE_TITLE = "0100ABCD00010000"    # PEGI 7 (tests/library.py)
MOSS_TITLE = "0100EFEF00020000"         # PEGI 16, ESRB T
TIDEWALKER_TITLE = "0100C3D400040000"   # CERO A


def vector(name):
    return json.loads((VECTORS / f"{name}.json").read_text(encoding="utf-8"))


class Headers(dict):
    def get(self, name, default=None):
        return next((v for k, v in self.items() if k.lower() == name.lower()), default)


class Vectors(unittest.TestCase):
    """vectors/ against the reference, both ways (SPEC.md § 17)."""

    def test_written_by_the_reference(self):
        self.assertEqual(make_vectors.main(["--check"]), 0)

    def test_signatures(self):
        """L-5.4-6, L-5.4-9: each accepted request verifies, each refused one gets its code, in order."""
        v = vector("signatures")
        public = base64.b64decode(v["key"]["public_key"])
        self.assertEqual(client.ed25519_public(bytes.fromhex(v["key"]["seed"])), public)
        self.assertEqual(signatures.thumbprint(public), v["key"]["keyid"])
        nonces = signatures.Nonces()

        def check(r):
            with_token = "Authorization" in r["headers"]
            signatures.check(r["method"], r["uri"], Headers(r["headers"]), public, with_token,
                             len(r["body"].encode()), nonces, v["skew"], now=v["server_time"])
        for case in v["accepted"]:
            digest = client.content_digest(case["body"].encode()) if case["body"] else None
            base, params = client.signature_base(case["method"], case["uri"], case["headers"].get("Authorization"),
                                                 digest, v["server_time"], re.search(r'nonce="([^"]+)"',
                                                 case["headers"]["Signature-Input"]).group(1), v["key"]["keyid"])
            self.assertEqual(base, case["signature_base"], case["name"])
            self.assertEqual("lantern=" + params, case["headers"]["Signature-Input"])
            check(case)
        for case in v["refused"]:
            with self.assertRaises(signatures.Refused, msg=case["name"]) as refused:
                check(case["request"])
            self.assertEqual(refused.exception.code, case["code"], case["name"])

    def test_homebrew_signatures(self):
        v = vector("homebrew-signatures")
        for m in v["manifests"]:
            self.assertEqual(client.manifest_sha256(m["manifest"]), m["manifest_sha256"])
            self.assertEqual(ls.manifest_digest(m["manifest"]), m["manifest_sha256"])
            self.assertEqual(hashlib.sha256(m["canonical"].encode()).hexdigest(), m["manifest_sha256"])
        for s in v["signed"]:
            message = s["signed_bytes"].encode()
            self.assertEqual(ls.signed_bytes(s["entry"]) == message, s["verifies"] or ls.signed_bytes(s["entry"]) == message)
            sig = s["signature"]
            ok = ls.ed25519.verify(base64.b64decode(sig["public_key"]), message, base64.b64decode(sig["value"]))
            self.assertEqual(ok, s["verifies"])
            self.assertEqual(client.verify_signature({**s["entry"], "signature": sig}), s["verifies"])

    def test_spki(self):
        """L-5.3-2's short form, by the server's reading of a PEM and the suite's of DER."""
        import ssl
        for c in vector("spki")["certificates"]:
            self.assertEqual(ls.spki_sha256(c["pem"]), c["spki_sha256"])
            self.assertEqual(conformance.spki_of(ssl.PEM_cert_to_DER_cert(c["pem"])), c["spki_sha256"])
            self.assertEqual(ls.short_fingerprint(c["spki_sha256"]), c["short"])

    def test_paths(self):
        """L-8.2-4: the server serves only what a client accepts."""
        v = vector("paths")
        for p in v["paths"]:
            self.assertEqual(ls.device_path_ok(p["path"]), p["accepted"], p)
            self.assertEqual(client.path_problem(p["path"]) is None, p["accepted"], p)
        for m in v["manifests"]:
            self.assertEqual(not client.manifest_problems(m["manifest"]), m["accepted"])

    def test_version_codes_requires_and_caps(self):
        for c in vector("version-codes")["cases"]:
            self.assertEqual(client.version_code(c["platform"], c["version"]), c["version_code"])
            self.assertEqual(client.version_name(c["platform"], c["version_code"]), c["version_name"])
        for c in vector("requires")["cases"]:
            decision, reasons = client.offer({"requires": c["requires"]}, c["device"])
            self.assertEqual((decision, len(reasons)), (c["decision"], c["conditions"]), c["name"])
        for c in vector("rating-caps")["cases"]:
            self.assertEqual(ls.above_cap(c["ratings"], c["cap"]), c["hidden"], c["name"])
            self.assertEqual(client.above_cap(c["ratings"], c["cap"]), c["hidden"], c["name"])
            self.assertEqual(ls.rating_age(c["ratings"], c["cap"]), c["age"], c["name"])
        self.assertEqual(vector("rating-caps")["ages"], ls.RATING_AGES)


class SmallOrder(unittest.TestCase):
    """Ed25519 forgeries with a key and an R of small order and S = 0 (SPEC.md § 8.4, § 5.4): never verified,
    by the server, the suite's reference client, a signed request or a device key at pairing. L-8.4-4, L-5.4-12."""

    def test_pairs_never_verify(self):
        v = vector("ed25519-refused")
        keys = [bytes.fromhex(h) for h in v["small_order"]]
        for key in keys:
            for r in keys:
                for m in v["messages"]:
                    self.assertFalse(ls.ed25519.verify(key, m.encode(), r + bytes(32)), (key.hex(), r.hex(), m))
                    self.assertFalse(client.ed25519_verify(key, m.encode(), r + bytes(32)))
        for c in v["cases"]:
            args = bytes.fromhex(c["public_key"]), c["message"].encode(), bytes.fromhex(c["signature"])
            self.assertEqual(ls.ed25519.verify(*args), c["verifies"], c["name"])
            self.assertEqual(client.ed25519_verify(*args), c["verifies"], c["name"])

    def test_small_order_r_with_a_real_key(self):
        key = client.ed25519_public(bytes(range(32)))
        for r in vector("ed25519-refused")["small_order"]:
            self.assertFalse(ls.ed25519.verify(key, b"Lea", bytes.fromhex(r) + bytes(32)))

    def test_a_signed_request_cannot_be_forged(self):
        """A device key of small order is refused at pairing (400), so no forged request can follow."""
        srv = Running(USERS)
        self.addCleanup(srv.close)
        for key in vector("ed25519-refused")["small_order"]:
            status, _, body = srv.request("/api/lantern/v1/pairing", data={
                "schema": 1, "device": "Forged", "scopes": ["library"],
                "key": {"alg": "ed25519", "public_key": base64.b64encode(bytes.fromhex(key)).decode()}})
            self.assertEqual((status, json.loads(body)["code"]), (400, "bad_request"), key)
        uri = "https://shelf.example.org/api/lantern/v1/apps"
        for key in vector("ed25519-refused")["small_order"]:
            for r in vector("ed25519-refused")["small_order"]:
                params = f'("@method" "@target-uri" "authorization");created=1793345400;nonce="tQ0Vb3Yt7sXx2c1mZ8kq4A";' \
                         f'keyid="{signatures.thumbprint(bytes.fromhex(key))}";alg="ed25519"'
                headers = Headers({"Authorization": "Bearer et_x", "Signature-Input": "lantern=" + params,
                                   "Signature": "lantern=:" + base64.b64encode(bytes.fromhex(r) + bytes(32)).decode() + ":"})
                with self.assertRaises(signatures.Refused):
                    signatures.check("GET", uri, headers, bytes.fromhex(key), True, 0, signatures.Nonces(),
                                     now=1793345400)

    def test_a_homebrew_signature_cannot_be_forged(self):
        entry = {"id": "org.example.forged", "platform": "switch", "build": 1,
                 "package": {"sha256": "a" * 64, "manifest_sha256": "b" * 64}}
        for key in vector("ed25519-refused")["small_order"]:
            for r in vector("ed25519-refused")["small_order"]:
                sig = {"alg": "ed25519", "public_key": base64.b64encode(bytes.fromhex(key)).decode(),
                       "value": base64.b64encode(bytes.fromhex(r) + bytes(32)).decode()}
                self.assertFalse(client.verify_signature({**entry, "signature": sig}))


class Live(unittest.TestCase):
    """A private reference server, its accounts USERS'."""

    users = USERS

    def setUp(self):
        self.srv = Running(self.users)
        self.addCleanup(self.srv.close)

    def admin(self):
        if not hasattr(self, "_admin"):
            self._admin = self.srv.pair_keyed(ADMIN, EVERY_SCOPE)
        token, seed, _ = self._admin
        return token, seed

    def as_admin(self, path, method="GET", data=None):
        token, seed = self.admin()
        status, headers, body = self.srv.signed(path, token, seed, method, data)
        return status, headers, (json.loads(body) if body and headers.get("Content-Type", "").endswith("json") else body)


class SignedRequests(Live):
    """SPEC.md § 5.4 on a live server."""

    def test_bound_token(self):
        """L-5.4-1, L-5.4-6, L-5.4-7: signed, it works; unsigned, 401 signature_required, with Date."""
        token, seed, _ = self.srv.pair_keyed("lea")
        status, headers, body = self.srv.signed("/api/lantern/v1/", token, seed)
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["account"]["bound"])
        self.assertTrue(headers.get("Date"))
        status, headers, body = self.srv.get("/api/lantern/v1/apps", token)
        self.assertEqual((status, json.loads(body)["code"]), (401, "signature_required"))
        self.assertTrue(headers["WWW-Authenticate"].startswith("Bearer"))
        self.assertIn('alg="ed25519"', headers["Accept-Signature"])                 # L-5.4-10

    def test_skew_and_replay(self):
        """L-5.4-6, L-5.4-9: created within auth.skew, a nonce taken once."""
        token, seed, _ = self.srv.pair_keyed("lea")
        path = "/api/lantern/v1/apps?page_size=1"
        now = int(time.time())
        self.assertEqual(self.srv.signed(path, token, seed, created=now - 290)[0], 200)
        self.assertEqual(self.srv.signed(path, token, seed, created=now + 290)[0], 200)
        for created in (now - 320, now + 320):
            status, _, body = self.srv.signed(path, token, seed, created=created)
            self.assertEqual((status, json.loads(body)["code"]), (401, "signature_expired"))
        nonce = client.new_nonce()
        self.assertEqual(self.srv.signed(path, token, seed, nonce=nonce)[0], 200)
        status, _, body = self.srv.signed(path, token, seed, nonce=nonce)
        self.assertEqual((status, json.loads(body)["code"]), (401, "signature_replayed"))

    def test_invalid(self):
        """L-5.4-6: another key, another target, a missing Content-Digest; a body that does not match (422)."""
        token, seed, _ = self.srv.pair_keyed("lea")
        status, _, body = self.srv.signed("/api/lantern/v1/apps", token, bytes(32))
        self.assertEqual(json.loads(body)["code"], "signature_invalid")
        headers = client.sign(seed, "GET", self.srv.url + "api/lantern/v1/apps?page_size=2", "Bearer " + token)
        status, _, body = self.srv.request("/api/lantern/v1/apps?page_size=1", token, headers)
        self.assertEqual((status, json.loads(body)["code"]), (401, "signature_invalid"))
        path = "/api/lantern/v1/apps/missing?platform=switch"
        doc = json.dumps({"schema": 1, "installed": [], "want": ["base"]}).encode()
        headers = client.sign(seed, "POST", self.srv.url.rstrip("/") + path, "Bearer " + token, doc)
        headers.pop("Content-Digest")
        status, _, body = self.srv.request(path, token, {**headers, "Content-Type": "application/json"}, "POST", doc)
        self.assertEqual(json.loads(body)["code"], "signature_invalid")
        headers = client.sign(seed, "POST", self.srv.url.rstrip("/") + path, "Bearer " + token, doc + b" ")
        status, _, body = self.srv.request(path, token, {**headers, "Content-Type": "application/json"}, "POST", doc)
        self.assertEqual((status, json.loads(body)["code"]), (422, "digest_mismatch"))

    def test_keyed_poll(self):
        """L-5.4-11: the poll of a pairing with a key is signed by it; a leaked poll address gives nothing."""
        seed, public = client.ed25519_keypair()
        code = self.srv.start_pairing({"schema": 1, "device": "Lea's Switch", "scopes": ["library"],
                                       "key": {"alg": "ed25519", "public_key": base64.b64encode(public).decode()}})
        pairing = self.srv.server.pairing
        pairing.approve(pairing.by_code(code["code"]), "lea")
        status, _, body = self.srv.get(code["poll"])
        self.assertEqual((status, json.loads(body)["code"]), (401, "signature_required"))
        status, _, body = self.srv.signed(code["poll"], None, bytes(32))
        self.assertEqual((status, json.loads(body)["code"]), (401, "signature_invalid"))
        time.sleep(0)
        status, _, body = self.srv.signed(code["poll"], None, seed)
        self.assertEqual(status, 200, body)
        self.assertTrue(json.loads(body)["bound"])

    def test_bad_key_and_bound_only(self):
        """L-5.4-1: a key not of Ed25519 gives 400; a server of bound tokens only refuses the others."""
        status, _, body = self.srv.request("/api/lantern/v1/pairing", data={
            "schema": 1, "device": "x", "scopes": ["library"], "key": {"alg": "ed25519", "public_key": "A" * 43 + "="}})
        self.assertEqual(status, 400)
        bearer = self.srv.pair("lea")
        self.assertEqual(self.srv.get("/api/lantern/v1/apps", bearer)[0], 200)      # 0.3's clients still work
        self.srv.server.bound_only = True
        status, _, body = self.srv.get("/api/lantern/v1/apps", bearer)
        self.assertEqual((status, json.loads(body)["code"]), (401, "signature_required"))
        status, _, body = self.srv.request("/api/lantern/v1/pairing", data={"schema": 1, "device": "x",
                                                                            "scopes": ["library"]})
        self.assertEqual((status, json.loads(body)["code"]), (400, "key_required"))
        hello = self.srv.get_json("/api/lantern/v1/")[1]
        self.assertEqual(hello["auth"], {"bearer_only": False, "skew": 300})

    def test_revoked_device(self):
        """L-5.7-3, L-5.1-4: a device revoked, by the administration API or the command line, gets 401 at once."""
        token, seed, _ = self.srv.pair_keyed("lea")
        devices = self.as_admin("/api/lantern/v1/admin/devices?user=lea")[2]["items"]
        self.assertEqual(len(devices), 1)
        self.assertEqual(self.as_admin(f"/api/lantern/v1/admin/devices/{devices[0]['id']}", "DELETE")[0], 204)
        status, _, body = self.srv.signed("/api/lantern/v1/apps", token, seed)
        self.assertEqual((status, json.loads(body)["code"]), (401, "unauthorized"))
        token, seed, _ = self.srv.pair_keyed("lea")
        did = self.as_admin("/api/lantern/v1/admin/devices?user=lea")[2]["items"][0]["id"]
        self.srv.lib.save_state()
        with contextlib.redirect_stdout(io.StringIO()):
            ls.tokens_command(self.srv.state, did)
        time.sleep(0.01)
        self.assertEqual(self.srv.signed("/api/lantern/v1/apps", token, seed)[0], 401)


class Invitations(Live):
    """SPEC.md § 5.5."""

    def invite(self, **fields):
        body = {"schema": 1, "user": "lea", "scopes": ["library"], "devices": 2,
                "expires": (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"), **fields}
        return self.as_admin("/api/lantern/v1/admin/invitations", "POST", body)

    def redeem(self, code, scopes=("library",)):
        seed, public = client.ed25519_keypair()
        status, _, body = self.srv.request("/api/lantern/v1/pairing", data={
            "schema": 1, "device": "Sam's Switch", "scopes": list(scopes), "invitation": code,
            "key": {"alg": "ed25519", "public_key": base64.b64encode(public).decode()}})
        if status != 200:
            return status, json.loads(body)
        poll = json.loads(body)["poll"]
        status, _, body = self.srv.signed(poll, None, seed)
        return status, json.loads(body)

    def test_limits(self):
        """L-5.5-1, L-5.5-2: a number of devices, then 410; expired, revoked or unknown, 410."""
        status, _, inv = self.invite(rating_cap={"age": 12})
        self.assertEqual(status, 201, inv)
        self.assertIn("invitation=" + inv["code"], inv["link"])
        for _ in range(2):
            status, token = self.redeem(inv["code"], ("library", "saves"))
            self.assertEqual(status, 200, token)
            self.assertEqual((token["scopes"], token["rating_cap"], token["bound"]), (["library"], {"age": 12}, True))
        status, problem = self.redeem(inv["code"])
        self.assertEqual((status, problem["code"]), (410, "gone"))
        self.assertEqual(self.as_admin("/api/lantern/v1/admin/invitations")[2]["items"], [])     # used up
        devices = self.as_admin("/api/lantern/v1/admin/devices?user=lea")[2]["items"]
        self.assertEqual(sorted(d.get("invitation") for d in devices), [inv["id"], inv["id"]])
        _, _, other = self.invite(devices=5)
        self.assertEqual(self.as_admin(f"/api/lantern/v1/admin/invitations/{other['id']}", "DELETE")[0], 204)
        self.assertEqual(self.redeem(other["code"])[0], 410)
        _, _, late = self.invite()
        self.srv.lib.state["invitations"][late["id"]]["expires"] = "2020-01-01T00:00:00Z"
        self.assertEqual(self.redeem(late["code"])[0], 410)
        self.assertEqual(self.redeem("ZZZZ-ZZZZ-ZZZZ-ZZZZ")[0], 410)

    def test_redeemed_at_once(self):
        """L-5.5-2: ten devices at once, an invitation for one: one token."""
        _, _, inv = self.invite(devices=1)
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.redeem(inv["code"])[0])) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), [200] + [410] * 9)

    def test_refused_shapes(self):
        """An account's scopes at most, 30 days at most, 1 to 100 devices; attempts at codes limited (L-5.5-3)."""
        self.assertEqual(self.invite(scopes=["library", "admin"])[0], 400)       # lea has no admin
        far = (datetime.now(timezone.utc) + timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(self.invite(expires=far)[0], 400)
        self.assertEqual(self.invite(devices=0)[0], 400)
        self.assertEqual(self.invite(user="nobody")[0], 400)
        self.assertEqual(self.invite(rating_cap={"system": "PEGI", "rating": "13"})[0], 400)
        codes = [self.redeem("ZZZZ-ZZZZ-ZZZZ-ZZZ" + c)[0] for c in "23456789ABCD"]
        self.assertEqual(codes[-1], 429)

    def test_not_a_browser_page(self):
        status, _, body = self.srv.get("/pair?invitation=MZ7Q-4KHP-XW2N-8TRD")
        self.assertEqual(status, 200)
        self.assertIn(b"Lantern app", body)


class RatingCaps(Live):
    """L-5.6-1, L-5.6-2: a capped token sees nothing above its cap, anywhere."""

    def capped(self, cap):
        token, seed, _ = self.srv.pair_keyed("mila", EVERY_SCOPE, rating_cap=cap)
        return lambda path, method="GET", data=None, platform="switch": self.srv.signed(
            path, token, seed, method, data, headers={"Lantern-Platform": platform} if platform else None)

    def test_everywhere(self):
        call = self.capped({"age": 12})         # Frostline (PEGI 7) and Tidewalker shown; Moss (PEGI 16) hidden
        hello = json.loads(call("/api/lantern/v1/")[2])
        self.assertEqual(hello["account"]["rating_cap"], {"age": 12})
        apps = json.loads(call("/api/lantern/v1/apps?page_size=500")[2])
        titles = {a["title_id"] for a in apps["items"]}
        self.assertIn(FROSTLINE_TITLE, titles)
        self.assertNotIn(MOSS_TITLE, titles)
        self.assertEqual(apps["total"], len(apps["items"]))
        self.assertEqual(call(f"/api/lantern/v1/titles/{MOSS_TITLE}")[0], 404)
        bulk = json.loads(call(f"/api/lantern/v1/titles?ids={MOSS_TITLE},{FROSTLINE_TITLE}")[2])
        self.assertEqual((bulk["unknown"], [t["title_id"] for t in bulk["titles"]]), ([MOSS_TITLE], [FROSTLINE_TITLE]))
        missing = json.loads(call("/api/lantern/v1/apps/missing", "POST", {"schema": 1, "installed": [
            {"app_id": MOSS_TITLE, "version_code": 0}], "want": ["base", "update", "dlc"]})[2])
        self.assertFalse([a for a in missing["items"] if a["title_id"] == MOSS_TITLE])
        moss = [e["doc"] for e in self.srv.lib.apps.values() if e["doc"]["title_id"] == MOSS_TITLE]
        self.assertEqual(call(moss[0]["file"], "HEAD", platform=None)[0], 404)
        cheats = json.loads(call("/api/lantern/v1/cheats")[2])["cheats"]
        self.assertFalse([c for c in cheats if c["title_id"] == MOSS_TITLE])
        hidden = next(c for c in self.srv.lib.cheats.values() if c["doc"]["title_id"] == MOSS_TITLE)
        self.assertEqual(call(f"/api/lantern/v1/cheats/{hidden['doc']['id']}")[0], 404)
        # Changes: an update of the hidden game arrives; the capped token never sees it.
        since = json.loads(call("/api/lantern/v1/changes")[2])["since"]
        tsince = json.loads(call("/api/lantern/v1/titles/changes")[2])["since"]
        (self.srv.root / "Moss and Ember [0100EFEF00020800][v196608].nsp").write_bytes(b"x" * 99)
        later = json.loads(call(f"/api/lantern/v1/changes?since={since}")[2])
        self.assertEqual(later["added"], [])
        everyone = json.loads(self.as_admin(f"/api/lantern/v1/changes?since={since}")[2] and
                              json.dumps(self.as_admin(f"/api/lantern/v1/changes?since={since}")[2]))
        self.assertEqual([a["title_id"] for a in everyone["added"]], [MOSS_TITLE])
        tlater = json.loads(call(f"/api/lantern/v1/titles/changes?since={tsince}")[2])
        self.assertFalse([t for t in tlater["titles"] if t["title_id"] == MOSS_TITLE])

    def test_homebrew_and_unrated(self):
        call = self.capped({"system": "PEGI", "rating": "7", "unrated": "hide"})
        ids = {e["id"] for e in json.loads(call("/api/lantern/v1/homebrew?page_size=500", platform=None)[2])["items"]}
        self.assertEqual(ids, set())                    # Paper Lamp is PEGI 12, the others unrated
        self.assertEqual(call(f"/api/lantern/v1/homebrew/{library.PAPERLAMP}")[0], 404)
        updates = json.loads(call("/api/lantern/v1/homebrew/updates", "POST", {
            "schema": 1, "installed": [{"id": library.PAPERLAMP, "build": 1}]})[2])
        self.assertEqual(updates["items"], [])
        apps = json.loads(call("/api/lantern/v1/apps?page_size=500", platform=None)[2])["items"]
        self.assertEqual({a["title_id"] for a in apps}, {FROSTLINE_TITLE, TIDEWALKER_TITLE})   # rated, at most 7
        paper = next(e["doc"] for (p, i), e in self.srv.lib.homebrew.items() if i == library.PAPERLAMP)
        self.assertEqual(call(paper["package"]["file"], "HEAD")[0], 404)

    def test_set_on_the_pair_page(self):
        """The server's page sets a cap at approval; the device cannot change it (no route)."""
        seed, public = client.ed25519_keypair()
        code = self.srv.start_pairing({"schema": 1, "device": "Noa's Switch", "scopes": ["library"],
                                       "key": {"alg": "ed25519", "public_key": base64.b64encode(public).decode()}})
        _, _, page = self.srv.form({"name": "lea", "password": "frost-lantern", "code": code["code"]})
        self.assertIn(signatures.short_fingerprint(public).encode(), page)     # the device's key, shown
        nonce = re.search(rb'name="nonce" value="([^"]+)"', page).group(1).decode()
        self.srv.form({"nonce": nonce, "decision": "approve", "cap": "7", "unrated": "hide"})
        _, _, body = self.srv.signed(code["poll"], None, seed)
        self.assertEqual(json.loads(body)["rating_cap"], {"age": 7, "unrated": "hide"})


class Administration(Live):
    """SPEC.md § 5.7."""

    def test_scope(self):
        """L-5.7-1: 401 without a token, 403 without the scope admin."""
        self.assertEqual(self.srv.get("/api/lantern/v1/admin/users")[0], 401)
        token, seed, _ = self.srv.pair_keyed("lea")
        status, _, body = self.srv.signed("/api/lantern/v1/admin/users", token, seed)
        self.assertEqual((status, json.loads(body)["code"]), (403, "forbidden"))
        hello = json.loads(self.srv.signed("/api/lantern/v1/", token, seed)[2])
        self.assertEqual(hello["features"]["admin"], 0)
        self.assertEqual(self.as_admin("/api/lantern/v1/")[2]["features"]["admin"], 1)

    def test_users(self):
        """L-5.7-2, L-5.7-3: made without a password, 409 again, frozen at once, scopes cut at once."""
        status, _, user = self.as_admin("/api/lantern/v1/admin/users", "POST",
                                        {"schema": 1, "name": "sam", "scopes": ["library", "saves"]})
        self.assertEqual((status, user["name"], user["devices"]), (201, "sam", 0))
        self.assertEqual(self.as_admin("/api/lantern/v1/admin/users", "POST", {"schema": 1, "name": "lea",
                                                                               "scopes": []})[0], 409)
        self.assertEqual(self.as_admin("/api/lantern/v1/admin/users", "POST", {"schema": 1, "name": "x",
                                                                               "scopes": [], "password": "y"})[0], 400)
        listed = self.as_admin("/api/lantern/v1/admin/users?page_size=2")[2]
        self.assertEqual((len(listed["items"]), listed["total"]), (2, 5))
        self.assertNotIn("pbkdf2", json.dumps(self.as_admin("/api/lantern/v1/admin/users")[2]))
        token, seed, _ = self.srv.pair_keyed("lea")
        self.assertEqual(self.as_admin("/api/lantern/v1/admin/users/lea", "PATCH", {"schema": 1, "state": "frozen"})[0], 200)
        status, _, body = self.srv.signed("/api/lantern/v1/apps", token, seed)
        self.assertEqual((status, json.loads(body)["code"]), (403, "account_frozen"))
        self.as_admin("/api/lantern/v1/admin/users/lea", "PATCH", {"schema": 1, "state": "active", "scopes": []})
        status, _, body = self.srv.signed("/api/lantern/v1/apps", token, seed)
        self.assertEqual((status, json.loads(body)["code"]), (403, "forbidden"))
        self.assertEqual(self.as_admin("/api/lantern/v1/admin/users/nobody", "PATCH", {"schema": 1, "state": "frozen"})[0],
                         404)
        state = json.loads(self.srv.state.read_text())
        self.assertEqual(state["accounts"]["lea"]["scopes"], [])                 # kept in the state, not users.json

    def test_pairings(self):
        """L-5.7-4, L-5.2-4: listed with code and key, approved for another account, at most the scopes asked."""
        seed, public = client.ed25519_keypair()
        code = self.srv.start_pairing({"schema": 1, "device": "Ines's Switch", "scopes": ["library", "saves"],
                                       "key": {"alg": "ed25519", "public_key": base64.b64encode(public).decode()}})
        items = self.as_admin("/api/lantern/v1/admin/pairings")[2]["items"]
        mine = next(p for p in items if p["code"] == code["code"])
        self.assertEqual(mine["key"], signatures.short_fingerprint(public))
        self.assertNotIn(code["poll"].rsplit("/", 1)[1], json.dumps(items))          # never the poll address
        status, _, _ = self.as_admin(f"/api/lantern/v1/admin/pairings/{mine['id']}", "POST",
                                     {"schema": 1, "decision": "approve", "user": "ines", "scopes": ["saves", "admin"]})
        self.assertEqual(status, 204)
        token = json.loads(self.srv.signed(code["poll"], None, seed)[2])
        self.assertEqual(token["scopes"], ["saves"])
        devices = self.as_admin("/api/lantern/v1/admin/devices?user=ines")[2]["items"]
        self.assertEqual((devices[0]["device"], devices[0]["bound"]), ("Ines's Switch", True))
        self.assertNotIn(token["token"], json.dumps(devices))
        state_hashes = list(json.loads(self.srv.state.read_text())["tokens"])
        self.assertFalse([h for h in state_hashes if h in json.dumps(devices)])
        self.assertEqual(self.as_admin(f"/api/lantern/v1/admin/pairings/{mine['id']}", "POST",
                                       {"schema": 1, "decision": "refuse"})[0], 404)     # decided already


class Texts(Live):
    """Languages (SPEC.md § 2.2), compression (§ 2.1), requests withdrawn (§ 11), Atlas ids (§ 6.1)."""

    users = None    # a public server

    def test_languages(self):
        """L-2.2-1, L-2.2-2, L-2.2-3."""
        _, headers, body = self.srv.get("/api/lantern/v1/nowhere", headers={"Accept-Language": "fr-CA, en;q=0.5"})
        doc = json.loads(body)
        self.assertEqual((doc["language"], doc["title"], headers["Content-Language"]), ("fr-CA", "Introuvable", "fr-CA"))
        doc = json.loads(self.srv.get("/api/lantern/v1/nowhere", headers={"Accept-Language": "sv"})[2])
        self.assertEqual((doc["language"], doc["title"]), ("en", "Not found"))    # 0.5: fifteen languages, not Swedish
        self.srv.server.motd = {"en": "Two new co-op games.", "fr": "Deux nouveaux jeux à deux."}
        hello = json.loads(self.srv.get("/api/lantern/v1/", headers={"Accept-Language": "fr"})[2])
        self.assertEqual((hello["motd"], hello["language"]), ("Deux nouveaux jeux à deux.", "fr"))

    def test_compression(self):
        """L-2.1-1, L-2.1-2, L-2.1-3: JSON in gzip, its own ETag; never a file."""
        _, headers, body = self.srv.get("/api/lantern/v1/apps", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(headers["Content-Encoding"], "gzip")
        self.assertIn("Accept-Encoding", headers["Vary"])
        plain = self.srv.get("/api/lantern/v1/apps")
        self.assertEqual(json.loads(gzip.decompress(body)), json.loads(plain[2]))
        self.assertNotEqual(headers["ETag"], plain[1]["ETag"])
        again = self.srv.get("/api/lantern/v1/apps", headers={"Accept-Encoding": "gzip", "If-None-Match": headers["ETag"]})
        self.assertEqual(again[0], 304)
        app = json.loads(plain[2])["items"][0]
        _, headers, body = self.srv.get(app["file"], headers={"Accept-Encoding": "gzip, zstd, br"})
        self.assertIsNone(headers.get("Content-Encoding"))
        self.assertEqual(hashlib.sha256(body).hexdigest(), app["sha256"])

    def test_atlas_and_sizes(self):
        apps = json.loads(self.srv.get("/api/lantern/v1/apps?page_size=500")[2])["items"]
        frost = next(a for a in apps if a["title_id"] == FROSTLINE_TITLE and a["type"] == "base")
        self.assertEqual(frost["atlas"], "Q900001")
        moss = next(a for a in apps if a["title_id"] == MOSS_TITLE and a["type"] == "base")
        self.assertEqual(moss["installed_size"], 8192)
        title = json.loads(self.srv.get(f"/api/lantern/v1/titles/{FROSTLINE_TITLE}",
                                        headers={"Lantern-Platform": "switch"})[2])
        self.assertEqual(title["atlas"], "Q900001")
        paper = json.loads(self.srv.get(f"/api/lantern/v1/homebrew/{library.PAPERLAMP}")[2])
        self.assertEqual((paper["atlas"], paper["ratings"]), ("Q900002", [{"system": "PEGI", "rating": "12"}]))
        frostline = json.loads(self.srv.get(f"/api/lantern/v1/homebrew/{library.FROSTLINE}",
                                            headers={"Lantern-Platform": "switch"})[2])
        self.assertEqual(frostline["package"]["installed_size"], sum(m["size"] for m in frostline["package"]["manifest"]))

    def test_depth(self):
        """L-13-3: a document nested too deep is refused, never a failure."""
        body = b'{"schema":1,"installed":[],"want":["base"],"x":' + b"[" * 5000 + b"]" * 5000 + b"}"
        status, _, doc = self.srv.request("/api/lantern/v1/apps/missing?platform=switch", data=body,
                                          headers={"Content-Type": "application/json"})
        self.assertEqual((status, json.loads(doc)["code"]), (400, "bad_request"))
        status, _, _ = self.srv.get("//[x/api")
        self.assertIn(status, (400, 404))


class WithdrawnRequests(Live):
    def test_delete(self):
        """L-11-2: one's own, 204 then 404; another account's, 404."""
        token, seed, _ = self.srv.pair_keyed("mila", EVERY_SCOPE)
        _, _, body = self.srv.signed("/api/lantern/v1/requests", token, seed, "POST",
                                          {"schema": 1, "platform": "switch", "title_id": "0100AAAA00010000"})
        rid = json.loads(body)["id"]
        other, oseed, _ = self.srv.pair_keyed("mila", EVERY_SCOPE)
        self.srv.server.accounts.users["noor"]["scopes"] = ["requests"]
        self.srv.server.accounts.update("noor", "active")
        noor, nseed, _ = self.srv.pair_keyed("noor", {"schema": 1, "device": "Noor's Switch", "scopes": ["requests"]})
        self.assertEqual(self.srv.signed(f"/api/lantern/v1/requests/{rid}", noor, nseed, "DELETE")[0], 404)
        self.assertEqual(self.srv.signed(f"/api/lantern/v1/requests/{rid}", other, oseed, "DELETE")[0], 204)
        self.assertEqual(self.srv.signed(f"/api/lantern/v1/requests/{rid}", token, seed, "DELETE")[0], 404)
        self.assertEqual(self.srv.lib.requests(), [])


class VerifyComplete(Live):
    def test_qr_address(self):
        """L-5.2-10, L-5.2-11: the code in verify_complete fills the form in, and approves nothing."""
        code = self.srv.start_pairing()
        self.assertEqual(code["verify_complete"], code["verify"] + "?code=" + code["code"])
        _, _, page = self.srv.get("/pair?code=" + code["code"])
        self.assertIn(f'value="{code["code"]}"'.encode(), page)
        self.assertEqual(self.srv.get(code["poll"])[0], 202)


class Fuzzing(unittest.TestCase):
    """The reference server's parsers, fuzzed (tests/fuzz.py): seeded, so a failure replays."""

    def test_every_target(self):
        for target in fuzz.TARGETS:
            with self.subTest(target=target):
                fuzz.run(target, 60 if target == "signature" else 300, "tests")


class Requirements(unittest.TestCase):
    """SPEC.md's ids (§ 3.5): well formed, and each one checked by the suite or said to be out of its sight."""

    def test_ids(self):
        found, problems = requirements.requirements()
        self.assertEqual(problems, [])
        ids = [r["id"] for r in found]
        covered = {i for reqs in conformance.REQS.values() for i in reqs}
        client_side = {i for _, reqs, _ in conformance.CLIENT_RULES for i in reqs}
        unseen = set(conformance.UNSEEN)
        self.assertEqual(sorted((covered | client_side | unseen) - set(ids)), [])          # no id the text lacks
        self.assertEqual(sorted(set(ids) - covered - client_side - unseen), [])           # every id somewhere
        self.assertEqual(sorted(covered & client_side), [])
        self.assertEqual(sorted(covered & unseen), [])

    def test_cited_ids_exist(self):
        ids = {r["id"] for r in requirements.requirements()[0]}
        for path in [*sorted((ROOT / "tests").glob("*.py")), ROOT / "conformance" / "run.py"]:
            cited = set(re.findall(r"\bL-(?:\d+(?:\.\d+)?|[A-Z](?:\.\d+)?)-\d+\b", path.read_text(encoding="utf-8")))
            self.assertEqual(sorted(cited - ids), [], path.name)

    def test_a_server_without_tokens(self):
        """A public server that does not pair: its signature checks are skipped, not failed, and Core is reached."""
        srv = Running()
        self.addCleanup(srv.close)
        code, report = run_suite(srv.url)
        self.assertEqual(code, 0, report)
        self.assertIn("Levels reached (SPEC.md § 17, draft 0.6): Lantern Core +titles +homebrew +peers\n", report)


class PairForCIKey(unittest.TestCase):
    def test_key_file(self):
        out = subprocess.run([sys.executable, str(ROOT / "tools" / "pair_for_ci.py"), "--help"], capture_output=True,
                             text=True, check=True)
        self.assertIn("--workdir", out.stdout)


if __name__ == "__main__":
    unittest.main()
