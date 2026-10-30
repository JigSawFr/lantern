"""The reference server against the conformance suite, and their own tests.

    python3 -m unittest discover -s tests

Each test starts the server in this process on a free port, over a tiny
fictional library made in a temporary folder (tests/library.py). A test
gets a device's token by pairing, approved through the server object or
its /pair page; the TLS tests make a self-signed certificate with openssl.
"""
import hashlib
import importlib.util
import io
import json
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
import urllib.error
import urllib.parse
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import library

from server import lantern_server as ls

ls.log = lambda msg: None  # the server's notes (skipped files…) stay out of the test output

spec = importlib.util.spec_from_file_location("lantern_conformance", ROOT / "conformance" / "run.py")
conformance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conformance)

USERS = {"schema": 1, "public": False, "users": [
    {"name": "lea", "password": ls.hash_password("frost-lantern", 1000), "scopes": ["library"], "state": "active"},
    {"name": "noor", "password": ls.hash_password("moss-ember", 1000), "scopes": ["library"], "state": "frozen"},
    {"name": "ines", "password": ls.hash_password("paper-comet", 1000), "scopes": ["saves"], "state": "active"},
]}
PAIRING = {"schema": 1, "device": "Lea's Switch", "scopes": ["library", "saves"]}


def self_signed(folder):
    """A self-signed certificate for 127.0.0.1 (openssl), and its key."""
    cert, key = Path(folder) / "cert.pem", Path(folder) / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
                    "-keyout", str(key), "-out", str(cert), "-days", "2", "-subj", "/CN=Lantern test",
                    "-addext", "subjectAltName=IP:127.0.0.1"], check=True, capture_output=True)
    return cert, key


class Running:
    """A reference server on a free port, over a fresh library."""

    def __init__(self, users=None, handler=ls.Handler, discovery=False, tls=False):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = library.make(Path(self.tmp.name) / "library")
        users_path = None
        if users is not None:
            users_path = Path(self.tmp.name) / "users.json"
            users_path.write_text(json.dumps(users), encoding="utf-8")
        self.state = Path(self.tmp.name) / "state.json"
        self.lib = ls.Library(self.root, self.state)
        context = spki = None
        self.cafile = None
        if tls:
            cert, key = self_signed(self.tmp.name)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            spki, self.cafile = ls.spki_sha256(cert.read_text()), str(cert)
        self.server = ls.LanternServer(("127.0.0.1", 0), self.lib, ls.Accounts(users_path), rescan=0,
                                       quiet=True, handler=handler, tls=context, spki=spki)
        self.port = self.server.server_address[1]
        self.url = f"{'https' if tls else 'http'}://127.0.0.1:{self.port}/"
        self.client_tls = ssl.create_default_context(cafile=self.cafile) if tls else None
        self.udp = ls.discovery(self.server, 0, self.port) if discovery else None
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        if self.udp:
            self.udp.close()
        self.tmp.cleanup()

    def request(self, path, token=None, headers=None, method=None, data=None):
        headers = dict(headers or {})
        if isinstance(data, dict):
            data = json.dumps(data).encode()
            headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(self.url.rstrip("/") + path, headers=headers, data=data, method=method)
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, context=self.client_tls) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def get(self, path, token=None, headers=None):
        return self.request(path, token, headers)

    def get_json(self, path, token=None):
        status, _, body = self.get(path, token)
        return status, json.loads(body)

    def form(self, fields):
        return self.request("/pair", data=urllib.parse.urlencode(fields).encode(),
                            headers={"Content-Type": "application/x-www-form-urlencoded"})

    def start_pairing(self, doc=PAIRING):
        status, _, body = self.request("/api/lantern/v1/pairing", data=doc)
        assert status == 200, body
        return json.loads(body)

    def pair(self, user, doc=PAIRING):
        """A token for `user`: asked for over HTTP, approved through the server object."""
        code = self.start_pairing(doc)
        pairing = self.server.pairing
        pairing.approve(pairing.by_code(code["code"]), user)
        status, _, body = self.get(code["poll"])
        assert status == 200, body
        return json.loads(body)["token"]


def run_suite(url, *args):
    out = io.StringIO()
    code = conformance.main([url, *args], out=out)
    return code, out.getvalue()


class SuiteAgainstReference(unittest.TestCase):
    """conformance/run.py passes against server/, whoever calls."""

    def passes(self, srv, *args, expect=()):
        code, report = run_suite(srv.url, *args)
        fails = [line for line in report.splitlines() if line.startswith("FAIL")]
        self.assertEqual((code, fails), (0, []), report)
        for cid in expect:
            self.assertRegex(report, rf"PASS  § \S+\s+{re.escape(cid)} ", report)
        return report

    def test_public(self):
        srv = Running(discovery=True)
        self.addCleanup(srv.close)
        udp_port = srv.udp.getsockname()[1]
        report = self.passes(srv, "--discover", "127.0.0.1", "--discover-port", str(udp_port),
                             expect=["apps.pages.name", "apps.sha256", "missing.installed", "files.whole",
                                     "files.ranges", "discovery.reply", "schema.refused.library",
                                     "auth.unknown-token", "auth.basic-refused", "auth.no-basic",
                                     "pairing.offered"])
        self.assertIn(f"{library.SERVED} apps in", report)
        self.assertIn("plain HTTP on loopback", report)

    def test_private_with_a_token(self):
        srv = Running(USERS)
        self.addCleanup(srv.close)
        self.passes(srv, "--token", srv.pair("lea"),
                    expect=["auth.missing", "features.anonymous", "files.whole", "handshake.account",
                            "pairing.offered", "pairing.code", "pairing.waiting", "pairing.slow-down",
                            "pairing.unknown", "schema.refused.pairing", "errors.www-authenticate"])

    def test_private_anonymously(self):
        srv = Running(USERS)
        self.addCleanup(srv.close)
        report = self.passes(srv, expect=["features.library", "features.pairing", "pairing.code"])
        self.assertIn("library=0", report)

    def test_frozen_account(self):
        srv = Running(USERS)
        self.addCleanup(srv.close)
        self.passes(srv, "--token", srv.pair("noor"), expect=["auth.frozen"])

    def test_account_without_library_scope(self):
        srv = Running(USERS)
        self.addCleanup(srv.close)
        report = self.passes(srv, "--token", srv.pair("ines"), expect=["features.library"])
        self.assertIn("Feature library (0)", report)

    @unittest.skipUnless(shutil.which("openssl"), "openssl makes the certificate")
    def test_over_tls_with_a_self_signed_certificate(self):
        srv = Running(USERS, tls=True)
        self.addCleanup(srv.close)
        report = self.passes(srv, "--cafile", srv.cafile, "--token", srv.pair("lea"),
                             expect=["transport.https", "pairing.code", "files.ranges"])
        self.assertNotIn("WARN  § 2 ", report)


class SuiteCatchesFaults(unittest.TestCase):
    """The suite fails a server that breaks a MUST."""

    def fails(self, handler, cid, users=None):
        srv = Running(users, handler=handler)
        self.addCleanup(srv.close)
        code, report = run_suite(srv.url)
        self.assertEqual(code, 1, report)
        self.assertRegex(report, rf"FAIL  § \S+\s+{cid} ", report)

    def test_ranges_ignored(self):
        class NoRanges(ls.Handler):
            def handle_any(self, method):
                if "Range" in self.headers:
                    del self.headers["Range"]
                super().handle_any(method)
        self.fails(NoRanges, "files.ranges")

    def test_errors_sent_as_200(self):
        class Errors200(ls.Handler):
            def send_doc(self, status, doc, headers=None, problem=False):
                super().send_doc(200 if status == 404 else status, doc, headers, problem)
        self.fails(Errors200, "errors.never-200")

    def test_416_without_content_range(self):
        class NoContentRange(ls.Handler):
            def send_doc(self, status, doc, headers=None, problem=False):
                super().send_doc(status, doc, None if status == 416 else headers, problem)
        self.fails(NoContentRange, "files.unsatisfiable")

    def test_schema_2_accepted(self):
        class Lenient(ls.Handler):
            def request_document(self, body):
                try:
                    return {**json.loads(body), "schema": 1}
                except ValueError:
                    return super().request_document(body)
        self.fails(Lenient, "schema.refused.library")

    def test_feature_declared_but_absent(self):
        class Boasting(ls.Handler):
            def features(self, account):
                return {**super().features(account), "saves": 1}
        self.fails(Boasting, "features.saves")

    def test_repr_digest_missing(self):
        class NoDigest(ls.Handler):
            def send_head(self, status, length, headers):
                super().send_head(status, length, {k: v for k, v in headers.items() if k != "Repr-Digest"})
        self.fails(NoDigest, "files.whole")

    def test_digest_on_ranges_missing(self):
        class NoRangeDigest(ls.Handler):
            def send_head(self, status, length, headers):
                if status == 206:
                    headers = {k: v for k, v in headers.items() if k != "Repr-Digest"}
                super().send_head(status, length, headers)
        self.fails(NoRangeDigest, "files.ranges")

    def test_basic_challenge(self):
        class Basic(ls.Handler):
            def send_doc(self, status, doc, headers=None, problem=False):
                if status == 401:
                    headers = {"WWW-Authenticate": 'Basic realm="lantern"'}
                super().send_doc(status, doc, headers, problem)
        self.fails(Basic, "auth.no-basic")

    def test_private_server_without_pairing(self):
        class Closed(ls.Handler):
            def features(self, account):
                return {**super().features(account), "pairing": 0}
        self.fails(Closed, "pairing.offered", users=USERS)

    def test_ambiguous_code(self):
        class Ambiguous(ls.Handler):
            def send_doc(self, status, doc, headers=None, problem=False):
                if isinstance(doc, dict) and "code" in doc and "poll" in doc:
                    doc = {**doc, "code": "KQ0M-1TXO"}
                super().send_doc(status, doc, headers, problem)
        self.fails(Ambiguous, "pairing.code", users=USERS)


class Server(unittest.TestCase):
    def setUp(self):
        self.srv = Running()
        self.addCleanup(self.srv.close)

    def all_apps(self):
        status, doc = self.srv.get_json("/api/lantern/v1/apps?page_size=500")
        self.assertEqual(status, 200)
        return doc["items"]

    def private(self):
        srv = Running(USERS)
        self.addCleanup(srv.close)
        return srv

    def test_identity_from_names_and_library_json(self):
        apps = {f'{a["app_id"]}{a["format"]}{a["version"]}': a for a in self.all_apps()}
        self.assertEqual(len(apps), library.SERVED)
        moss = apps["0100EFEF00020000xci0"]
        self.assertEqual((moss["name"], moss["display_version"], moss["type"]), ("Moss & Ember", "1.0.0", "base"))
        update = apps["0100ABCD00010800nsz196608"]
        self.assertEqual((update["title_id"], update["type"]), ("0100ABCD00010000", "update"))
        self.assertEqual(apps["0100ABCD00011001nsp0"]["type"], "dlc")
        self.assertEqual(apps["0100E5F600050000nsp0"]["size"], 0)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{64}", a["sha256"]) for a in apps.values()))

    def test_cursor_survives_library_changes(self):
        everything = {a["id"]: a for a in self.all_apps()}
        status, first = self.srv.get_json("/api/lantern/v1/apps?page_size=3")
        seen = [a["id"] for a in first["items"]]
        removed = next(i for i, a in everything.items()
                       if a["name"] == "Paper Comets" and a["format"] == "nsp")
        self.assertNotIn(removed, seen)
        (self.srv.root / "Paper Comets [0100A1B200030000][v0].nsp").unlink()
        (self.srv.root / "Amber Signal [0100B7B700070000][v0].nsp").write_bytes(b"lantern")
        cursor = first["next"]
        while cursor:
            status, page = self.srv.get_json(f"/api/lantern/v1/apps?page_size=3&cursor={cursor}")
            self.assertEqual(status, 200)
            seen += [a["id"] for a in page["items"]]
            cursor = page["next"]
        self.assertEqual(len(seen), len(set(seen)), "an app repeated")
        self.assertEqual(set(seen), set(everything) - {removed}, "an app present all along was skipped")

    def test_changes(self):
        status, start = self.srv.get_json("/api/lantern/v1/changes")
        self.assertEqual((status, start["added"], start["removed"]), (200, [], []))
        gone = next(a for a in self.all_apps() if a["name"] == "Tidewalker")
        (self.srv.root / "more" / "Tidewalker [0100C3D400040000][v0].nsp").unlink()
        (self.srv.root / "Amber Signal [0100B7B700070000][v0].nsp").write_bytes(b"lantern")
        status, later = self.srv.get_json(f"/api/lantern/v1/changes?since={start['since']}")
        self.assertEqual(status, 200)
        self.assertEqual([a["name"] for a in later["added"]], ["Amber Signal"])
        self.assertEqual(later["removed"], [gone["id"]])
        status, problem = self.srv.get_json("/api/lantern/v1/changes?since=s_00000000_0")
        self.assertEqual((status, problem["code"]), (410, "gone"))

    def test_hashes_are_kept(self):
        state = json.loads(self.srv.state.read_text())
        self.assertEqual(state["schema"], 1)
        self.assertEqual(len(state["hashes"]), library.SERVED)
        again = ls.Library(self.srv.root, self.srv.state)
        self.assertEqual(again.uid, self.srv.lib.uid)
        self.assertEqual({a["doc"]["sha256"] for a in again.apps.values()},
                         {a["doc"]["sha256"] for a in self.srv.lib.apps.values()})

    def test_newer_state_is_never_written_over(self):
        newer = {"schema": 2, "uid": "kept", "something": "new"}
        self.srv.state.write_text(json.dumps(newer))
        lib = ls.Library(self.srv.root, self.srv.state)
        self.assertNotEqual(lib.uid, "kept")
        ls.Tokens(lib).issue("lea", "Lea's Switch", ["library"])   # kept in memory only
        self.assertEqual(json.loads(self.srv.state.read_text()), newer)
        with self.assertRaises(SystemExit):
            ls.main(["--state", str(self.srv.state), "--tokens"])

    def test_state_keeps_unknown_keys(self):
        state = json.loads(self.srv.state.read_text())
        state["x-example"] = {"kept": True}
        self.srv.state.write_text(json.dumps(state))
        (self.srv.root / "Amber Signal [0100B7B700070000][v0].nsp").write_bytes(b"lantern")
        lib = ls.Library(self.srv.root, self.srv.state)
        ls.Tokens(lib).issue("lea", "Lea's Switch", ["library"])
        self.assertEqual(json.loads(self.srv.state.read_text())["x-example"], {"kept": True})

    def test_newer_library_json_is_ignored(self):
        (self.srv.root / "library.json").write_text(json.dumps({"schema": 2, "apps": [
            {"file": "Moss and Ember [0100EFEF00020000][v0].xci", "name": "Renamed"}]}))
        names = {a["name"] for a in self.all_apps()}
        self.assertIn("Moss and Ember", names)
        self.assertNotIn("Renamed", names)

    def test_page_size_lowered_to_the_limit(self):
        status, doc = self.srv.get_json("/api/lantern/v1/apps?page_size=100000")
        self.assertEqual((status, len(doc["items"])), (200, library.SERVED))
        status, doc = self.srv.get_json("/api/lantern/v1/apps?page_size=0")
        self.assertEqual((status, doc["code"]), (400, "bad_request"))

    def test_private_server(self):
        srv = self.private()
        status, hello = srv.get_json("/.well-known/lantern")
        self.assertEqual((status, hello["account"]["state"]), (200, "anonymous"))
        self.assertEqual({k for k, v in hello["features"].items() if v}, {"pairing"})
        status, problem = srv.get_json("/api/lantern/v1/apps")
        self.assertEqual((status, problem["code"]), (401, "unauthorized"))
        status, hello = srv.get_json("/api/lantern/v1/", token=srv.pair("lea"))
        self.assertEqual((hello["account"]["name"], hello["features"]["library"], hello["features"]["pairing"]),
                         ("lea", 1, 1))
        status, problem = srv.get_json("/api/lantern/v1/apps", token=srv.pair("noor"))
        self.assertEqual((status, problem["code"]), (403, "account_frozen"))

    def test_public_server_does_not_pair(self):
        status, hello = self.srv.get_json("/api/lantern/v1/")
        self.assertEqual(hello["features"]["pairing"], 0)
        status, _, _ = self.srv.request("/api/lantern/v1/pairing", data=PAIRING)
        self.assertEqual(status, 404)
        self.assertEqual(self.srv.get("/pair")[0], 404)

    # Pairing (SPEC.md § 5.2).

    def test_pairing_end_to_end_through_the_page(self):
        srv = self.private()
        srv.server.pairing.interval = 1
        code = srv.start_pairing()
        self.assertRegex(code["code"], r"^[2-9A-HJ-NP-Z]{4}-[2-9A-HJ-NP-Z]{4}$")
        self.assertEqual((code["interval"], code["expires"]), (1, 600))
        self.assertEqual(code["verify"], f"http://127.0.0.1:{srv.port}/pair")
        self.assertEqual(srv.get(code["poll"])[0], 202)
        status, headers, page = srv.get("/pair")
        self.assertEqual((status, headers["Content-Type"]), (200, "text/html; charset=utf-8"))
        self.assertIn(b'name="password"', page)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        status, _, page = srv.form({"name": "lea", "password": "frost-lantern",
                                    "code": code["code"].lower().replace("-", " ")})
        self.assertEqual(status, 200, page)
        self.assertIn(b"Lea&#x27;s Switch", page)
        self.assertIn(b"for: library?", page)       # saves was asked for, but lea has only library
        nonce = re.search(rb'name="nonce" value="([^"]+)"', page).group(1).decode()
        status, _, page = srv.form({"nonce": nonce, "decision": "approve"})
        self.assertEqual(status, 200, page)
        self.assertIn(b"is paired", page)
        time.sleep(1)
        status, headers, body = srv.get(code["poll"])
        self.assertEqual((status, headers["Cache-Control"]), (200, "no-store"))
        token = json.loads(body)
        self.assertEqual(token["scopes"], ["library"])
        self.assertEqual(srv.get_json("/api/lantern/v1/apps?page_size=1", token=token["token"])[0], 200)
        status, problem = srv.get_json(code["poll"])
        self.assertEqual((status, problem["code"]), (410, "gone"))     # given once
        state = srv.state.read_text()
        self.assertNotIn(token["token"], state)                        # kept hashed
        self.assertIn(ls.token_hash(token["token"]), state)

    def test_pairing_refused(self):
        srv = self.private()
        code = srv.start_pairing()
        _, _, page = srv.form({"name": "lea", "password": "frost-lantern", "code": code["code"]})
        nonce = re.search(rb'name="nonce" value="([^"]+)"', page).group(1).decode()
        srv.form({"nonce": nonce, "decision": "refuse"})
        status, problem = srv.get_json(code["poll"])
        self.assertEqual((status, problem["code"]), (410, "gone"))

    def test_pair_page_refuses_wrong_passwords_and_codes(self):
        srv = self.private()
        srv.server.attempts = ls.Limiter(3, 600)
        code = srv.start_pairing()
        self.assertEqual(srv.form({"name": "lea", "password": "wrong", "code": code["code"]})[0], 403)
        self.assertEqual(srv.form({"name": "nobody", "password": "wrong", "code": code["code"]})[0], 403)
        self.assertEqual(srv.form({"name": "noor", "password": "moss-ember", "code": code["code"]})[0], 403)
        self.assertEqual(srv.form({"name": "lea", "password": "frost-lantern", "code": "AAAA-AAAA"})[0], 400)
        status, headers, _ = srv.form({"name": "lea", "password": "frost-lantern", "code": code["code"]})
        self.assertEqual(status, 429)
        self.assertTrue(int(headers["Retry-After"]) > 0)
        self.assertEqual(srv.get(code["poll"])[0], 202)    # nothing was approved

    def test_pairing_rate_limit(self):
        srv = self.private()
        srv.server.pair_limiter = ls.Limiter(3, 60)
        for _ in range(3):
            code = srv.start_pairing()
        status, headers, body = srv.request("/api/lantern/v1/pairing", data=PAIRING)
        self.assertEqual((status, json.loads(body)["code"]), (429, "slow_down"))
        self.assertTrue(int(headers["Retry-After"]) > 0)
        self.assertEqual(srv.get(code["poll"])[0], 202)
        status, headers, body = srv.get(code["poll"])         # again at once: faster than interval
        self.assertEqual((status, json.loads(body)["code"]), (429, "slow_down"))

    def test_pairing_requests_checked(self):
        srv = self.private()
        for doc in ({"schema": 1, "device": "", "scopes": ["library"]},
                    {"schema": 1, "device": "Lea's Switch", "scopes": ["shopping"]},
                    {"schema": 1, "device": "Lea\nSwitch", "scopes": ["library"]}):
            status, _, body = srv.request("/api/lantern/v1/pairing", data=doc)
            self.assertEqual((status, json.loads(body)["code"]), (400, "bad_request"), doc)
        status, _, body = srv.request("/api/lantern/v1/pairing", data={**PAIRING, "schema": 2})
        self.assertEqual(status, 422)

    # Tokens (SPEC.md § 5.1).

    def test_unknown_revoked_and_expired_tokens(self):
        srv = self.private()
        token = srv.pair("lea")
        self.assertEqual(srv.get_json("/api/lantern/v1/apps", token=token)[0], 200)
        for bad in ("et_" + "x" * 43, token + "x"):
            status, headers, _ = srv.get("/api/lantern/v1/apps", token=bad)
            self.assertEqual((status, headers["WWW-Authenticate"]), (401, 'Bearer realm="lantern", error="invalid_token"'))
        out = io.StringIO()
        with redirect_stdout(out):
            ls.main(["--state", str(srv.state), "--tokens"])
        self.assertIn("Lea's Switch", out.getvalue())
        with redirect_stdout(io.StringIO()):
            ls.main(["--state", str(srv.state), "--revoke", ls.token_hash(token)[:12]])
        status, headers, _ = srv.get("/api/lantern/v1/apps", token=token)     # the running server sees it
        self.assertEqual((status, headers["WWW-Authenticate"][:6]), (401, "Bearer"))
        old = srv.server.tokens.issue("lea", "Old Switch", ["library"], lifetime=-1)
        self.assertEqual(srv.get("/api/lantern/v1/", token=old)[0], 401)

    def test_token_without_scope(self):
        srv = self.private()
        token = srv.pair("ines")          # asked for library and saves; ines has only saves
        status, hello = srv.get_json("/api/lantern/v1/", token=token)
        self.assertEqual((hello["account"]["scopes"], hello["features"]["library"]), (["saves"], 0))
        status, problem = srv.get_json("/api/lantern/v1/apps", token=token)
        self.assertEqual((status, problem["code"]), (403, "forbidden"))

    def test_basic_is_refused(self):
        srv = self.private()
        basic = {"Authorization": "Basic bGVhOmZyb3N0LWxhbnRlcm4="}   # lea's right password
        for path in ("/api/lantern/v1/", "/api/lantern/v1/apps"):
            status, headers, body = srv.get(path, headers=basic)
            self.assertEqual((status, json.loads(body)["code"]), (401, "unauthorized"))
            self.assertTrue(headers["WWW-Authenticate"].startswith("Bearer"))
            self.assertNotIn("basic", headers["WWW-Authenticate"].lower())

    def test_tokens_survive_a_restart(self):
        srv = self.private()
        token = srv.pair("lea")
        again = ls.Tokens(ls.Library(srv.root, srv.state))
        self.assertEqual(again.find(token)["device"], "Lea's Switch")

    # Transport (SPEC.md § 2) and discovery (§ 4.1).

    def test_plain_http_refused_off_loopback(self):
        for host in ("0.0.0.0", "", "192.0.2.10"):
            with self.assertRaises(ValueError):
                ls.LanternServer((host, 0), self.srv.lib, ls.Accounts(None))
        with self.assertRaises(SystemExit), redirect_stdout(io.StringIO()), \
                unittest.mock.patch("sys.stderr", io.StringIO()):
            ls.main(["--library", str(self.srv.root), "--host", "0.0.0.0", "--port", "0"])
        self.assertTrue(all(map(ls.is_loopback, ("127.0.0.1", "127.8.9.10", "::1", "[::1]", "localhost"))))
        self.assertFalse(any(map(ls.is_loopback, ("0.0.0.0", "", "192.168.1.20", "::"))))

    def test_discovery_datagram(self):
        srv = Running(discovery=True)
        self.addCleanup(srv.close)
        address = ("127.0.0.1", srv.udp.getsockname()[1])

        def ask(data):
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(0.5)
                s.sendto(data, address)
                try:
                    return json.loads(s.recvfrom(2048)[0])
                except TimeoutError:
                    return None
        reply = ask(b'{"schema":1,"lantern":"discover","x-example":"ignored"}')
        self.assertEqual(reply, {"schema": 1, "lantern": "server", "uid": srv.lib.uid,
                                 "name": "Lantern reference server", "port": srv.port,
                                 "base": "/api/lantern", "versions": [1]})
        self.assertIsNone(ask(b"OWNFOIL_DISCOVER"))
        self.assertIsNone(ask(b'{"schema":2,"lantern":"discover"}'))
        self.assertIsNone(ask(b'{"schema":true,"lantern":"discover"}'))
        self.assertIsNone(ask(b'{"schema":1,"lantern":"discover","pad":"' + b"x" * 1200 + b'"}'))
        request = b'{"schema":1,"lantern":"discover"}'
        self.assertIsNone(ls.discovery_reply(srv.server, srv.port, request, "1.2.3.4", ls.Limiter(5, 1)))
        self.assertIsNotNone(ls.discovery_reply(srv.server, srv.port, request, "192.168.1.20", ls.Limiter(5, 1)))

    @unittest.skipUnless(shutil.which("openssl"), "openssl makes the certificate")
    def test_spki_fingerprint_on_the_pair_page(self):
        srv = Running(USERS, tls=True)
        self.addCleanup(srv.close)
        pub = subprocess.run(["openssl", "x509", "-in", srv.cafile, "-pubkey", "-noout"],
                             capture_output=True, check=True).stdout
        der = subprocess.run(["openssl", "pkey", "-pubin", "-outform", "DER"], input=pub,
                             capture_output=True, check=True).stdout
        expected = hashlib.sha256(der).hexdigest()
        self.assertEqual(srv.server.spki, expected)
        short = ls.short_fingerprint(expected)
        self.assertRegex(short, r"^[0-9A-F]{4}( [0-9A-F]{4}){3}$")
        status, _, page = srv.get("/pair")
        self.assertEqual(status, 200)
        self.assertIn(short.encode(), page)
        self.assertTrue(srv.start_pairing()["verify"].startswith("https://"))

    def test_a_bug_answers_500(self):
        class Broken(ls.Handler):
            def route(self, method, path, query, body):
                raise RuntimeError("a bug")
        srv = Running(handler=Broken)
        self.addCleanup(srv.close)
        Broken.log_error = lambda self, *args: None
        status, headers, body = srv.get("/api/lantern/v1/apps")
        problem = json.loads(body)
        self.assertEqual((status, headers["Content-Type"], problem["code"], problem["schema"]),
                         (500, "application/problem+json", "internal", 1))

    def test_newer_users_file_lets_nobody_in(self):
        srv = Running({"schema": 2, "public": True, "users": USERS["users"]})
        self.addCleanup(srv.close)
        status, _ = srv.get_json("/api/lantern/v1/apps")
        self.assertEqual(status, 401)
        token = srv.server.tokens.issue("lea", "Lea's Switch", ["library"])
        status, _ = srv.get_json("/api/lantern/v1/apps", token=token)
        self.assertEqual(status, 401)

    def test_ranges(self):
        self.assertEqual(ls.parse_range("bytes=0-9", 100), (0, 9))
        self.assertEqual(ls.parse_range("bytes=90-", 100), (90, 99))
        self.assertEqual(ls.parse_range("bytes=-10", 100), (90, 99))
        self.assertEqual(ls.parse_range("bytes=95-200", 100), (95, 99))
        self.assertEqual(ls.parse_range("bytes=100-", 100), "unsatisfiable")
        self.assertEqual(ls.parse_range("bytes=-0", 100), "unsatisfiable")
        self.assertIsNone(ls.parse_range("bytes=0-1,5-6", 100))
        self.assertIsNone(ls.parse_range("items=0-1", 100))
        self.assertIsNone(ls.parse_range("bytes=9-3", 100))

    def test_passwords(self):
        stored = ls.hash_password("frost-lantern", 1000)
        self.assertTrue(ls.check_password("frost-lantern", stored))
        self.assertFalse(ls.check_password("frost-lanterns", stored))
        self.assertFalse(ls.check_password("frost-lantern", "plain"))
        self.assertFalse(ls.check_password("", ls.NO_USER))


class SuiteHelpers(unittest.TestCase):
    def test_limits(self):
        self.assertEqual(conformance.limit_problems({"schema": 1, "name": "Lea"}), [])
        self.assertTrue(conformance.limit_problems({"name": "x" * 513}))
        self.assertTrue(conformance.limit_problems({"note": "é" * 61}))
        deep = {}
        for _ in range(17):
            deep = {"a": deep}
        self.assertTrue(conformance.limit_problems(deep))

    def test_nothing_listens(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        code, report = run_suite(f"http://127.0.0.1:{port}/", "--timeout", "2")
        self.assertEqual(code, 1)
        self.assertIn("No handshake", report)


if __name__ == "__main__":
    unittest.main()
