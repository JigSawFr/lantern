"""The reference server against the conformance suite, and their own tests.

    python3 -m unittest discover -s tests

Each test starts the server in this process on a free port, over a tiny
fictional library made in a temporary folder (tests/library.py). A test
gets a device's token by pairing, approved through the server object or
its /pair page; the TLS tests make a self-signed certificate with openssl.
"""
import base64
import hashlib
import importlib.util
import io
import json
import re
import secrets
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

sys.path.insert(0, str(ROOT / "conformance"))
import lantern_client as client

ls.log = lambda msg: None  # the server's notes (skipped files…) stay out of the test output

spec = importlib.util.spec_from_file_location("lantern_conformance", ROOT / "conformance" / "run.py")
conformance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conformance)

USERS = {"schema": 1, "public": False, "users": [
    {"name": "lea", "password": ls.hash_password("frost-lantern", 1000), "scopes": ["library"], "state": "active"},
    {"name": "noor", "password": ls.hash_password("moss-ember", 1000), "scopes": ["library"], "state": "frozen"},
    {"name": "ines", "password": ls.hash_password("paper-comet", 1000), "scopes": ["saves"], "state": "active"},
    {"name": "mila", "password": ls.hash_password("ember-tide", 1000), "scopes": list(ls.SCOPES), "state": "active"},
]}
PAIRING = {"schema": 1, "device": "Lea's Switch", "scopes": ["library", "saves"]}
EVERY_SCOPE = {"schema": 1, "device": "Mila's Switch", "scopes": list(ls.SCOPES)}


def self_signed(folder):
    """A self-signed certificate for 127.0.0.1 (openssl), and its key."""
    cert, key = Path(folder) / "cert.pem", Path(folder) / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
                    "-keyout", str(key), "-out", str(cert), "-days", "2", "-subj", "/CN=Lantern test",
                    "-addext", "subjectAltName=IP:127.0.0.1"], check=True, capture_output=True)
    return cert, key


class Running:
    """A reference server on a free port, over a fresh library."""

    def __init__(self, users=None, handler=ls.Handler, discovery=False, tls=False, large=False, mirror=None,
                 folder=None):
        """`large` and `mirror`: library.make()'s; `folder`: where to make the library, else in a folder of its
        own."""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = library.make(folder or Path(self.tmp.name) / "library", large, mirror)
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
                                       quiet=True, handler=handler, tls=context, spki=spki,
                                       heartbeat=5,     # limits.heartbeat's least (SPEC.md § 18.4)
                                       beat=0.25)       # heartbeats written more often, for short runs
        self.port = self.server.server_address[1]
        self.url = f"{'https' if tls else 'http'}://127.0.0.1:{self.port}/"
        self.client_tls = ssl.create_default_context(cafile=self.cafile) if tls else None
        self.udp = ls.discovery(self.server, 0, self.port) if discovery else None
        # A short poll interval: shutdown() waits for it, at every test's end.
        self.thread = threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True)
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
        """A bearer-only token for `user`, as a 0.3 client gets one: asked for over HTTP, approved through the
        server object."""
        code = self.start_pairing(doc)
        pairing = self.server.pairing
        pairing.approve(pairing.by_code(code["code"]), user)
        status, _, body = self.get(code["poll"])
        assert status == 200, body
        return json.loads(body)["token"]

    def pair_keyed(self, user, doc=PAIRING, rating_cap=None):
        """(token, the device key's seed, the file of the key) for `user`: a token bound to a key made here
        (SPEC.md § 5.4), its poll signed."""
        seed, public = client.ed25519_keypair()
        code = self.start_pairing({**doc, "key": {"alg": "ed25519", "public_key": base64.b64encode(public).decode()}})
        pairing = self.server.pairing
        pairing.approve(pairing.by_code(code["code"]), user, rating_cap=rating_cap)
        status, _, body = self.request(code["poll"], headers=client.sign(seed, "GET", self.url.rstrip("/") + code["poll"]))
        assert status == 200, body
        key = Path(self.tmp.name) / f"device-{secrets.token_hex(4)}.key"
        key.write_text(base64.b64encode(seed).decode(), encoding="ascii")
        return json.loads(body)["token"], seed, str(key)

    def signed(self, path, token, seed, method="GET", data=None, headers=None, **sign):
        """A request signed by the device key `seed` (SPEC.md § 5.4)."""
        headers = dict(headers or {})
        if isinstance(data, dict):
            data = json.dumps(data).encode()
            headers.setdefault("Content-Type", "application/json")
        auth = "Bearer " + token if token else None
        headers.update(client.sign(seed, method, self.url.rstrip("/") + path, auth, data or b"", **sign))
        if auth:
            headers["Authorization"] = auth
        return self.request(path, headers=headers, method=method, data=data)


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

    def test_private_with_every_scope(self):
        """A token bound to its device key, holding every scope: every level (SPEC.md § 17)."""
        srv = Running(USERS)
        self.addCleanup(srv.close)
        token, _, key = srv.pair_keyed("mila", EVERY_SCOPE)
        report = self.passes(srv, "--token", token, "--key", key, "--admin-writes",
                             expect=["saves.upload", "saves.read", "saves.upload-digest", "saves.single",
                                     "saves.cleanup", "schema.refused.saves", "schema.refused.homebrew",
                                     "cheats.sets", "cheats.text", "titles.bulk", "titles.bulk-limit",
                                     "homebrew.ports", "homebrew.signatures", "homebrew.updates",
                                     "homebrew.filters", "homebrew.requires", "homebrew.packages",
                                     "cheats.write-cycle", "requests.list", "requests.create",
                                     "schema.refused.requests", "platforms.filter", "missing.no-platform",
                                     "signatures.unsigned", "signatures.invalid", "signatures.stale",
                                     "signatures.replayed", "signatures.digest", "pairing.key", "requests.delete",
                                     "admin.users", "admin.users-write", "admin.pairings", "admin.rating-cap",
                                     "admin.refuse", "admin.devices", "admin.invitations", "language.problem",
                                     "compression.files", "limits.depth", "budget.cold-start"])
        self.assertIn("Levels reached (SPEC.md § 17, draft 0.6): Lantern Core +titles +homebrew +saves +cheats "
                      "+requests +admin +events +peers +sync +encrypted_saves\n", report)
        self.assertIn("4 backup(s) deleted", report)                     # two in clear, two encrypted (§ 9.4)
        self.assertIn("for another architecture", report)                # the Linux port's packages, read
        self.assertIn("posted, replaced and deleted", report)
        self.assertFalse((srv.root / "cheats" / "switch").exists())         # nor a cheat set
        self.assertEqual(json.loads((srv.root / "cheats" / "index.json").read_text())["notes"], {})
        self.assertEqual(srv.lib.requests(), [])                             # nor a request (SPEC.md § 11)
        self.assertEqual(srv.server.saves.index["saves"], [])         # the suite left nothing behind
        self.assertEqual(srv.server.saves.index["uploads"], {})
        devices = srv.server.tokens.devices()                               # nor a device: only its own token
        self.assertEqual([r["device"] for _, r in devices], ["Mila's Switch"])
        self.assertEqual(srv.server.invitations.listed(), [])
        made = [n for n in srv.server.accounts.names() if n.startswith("lantern-conformance-")]
        self.assertEqual(made, [])                                          # --admin-writes: made, then deleted

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
        token, _, key = srv.pair_keyed("mila", EVERY_SCOPE)
        report = self.passes(srv, "--cafile", srv.cafile, "--token", token, "--key", key,
                             expect=["transport.https", "pairing.code", "files.ranges", "saves.upload",
                                     "homebrew.packages", "pairing.verify-page", "signatures.replayed",
                                     "admin.invitations"])
        self.assertNotIn("WARN  § 2 ", report)


class PairForCI(unittest.TestCase):
    """tools/pair_for_ci.py: a private server, paired with as a user would, and its token."""

    def test_token_holds_every_scope(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = library.make(Path(tmp.name) / "library")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        work = Path(tmp.name) / "work"
        run = subprocess.run([sys.executable, str(ROOT / "tools" / "pair_for_ci.py"), "--library", str(root),
                              "--workdir", str(work), "--port", str(port)], capture_output=True, text=True,
                             timeout=120, check=False)
        pid = int((work / "server.pid").read_text())
        self.addCleanup(lambda: subprocess.run(["kill", str(pid)], check=False))
        self.assertEqual(run.returncode, 0, run.stderr)
        token = run.stdout.strip()
        seed = base64.b64decode((work / "device.key").read_text())
        url = f"http://127.0.0.1:{port}/.well-known/lantern"
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token,
                                                   **client.sign(seed, "GET", url, "Bearer " + token)})
        with urllib.request.urlopen(req, timeout=10) as r:
            hello = json.loads(r.read())
        self.assertEqual((hello["account"]["state"], hello["account"]["scopes"]), ("active", list(ls.SCOPES)))
        self.assertTrue(hello["account"]["bound"])                                  # SPEC.md § 5.4
        with self.assertRaises(urllib.error.HTTPError) as unsigned:
            urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": "Bearer " + token}), timeout=10)
        self.assertEqual(unsigned.exception.code, 401)
        self.assertEqual(hello["features"]["requests"], 1)
        users = json.loads((work / "users.json").read_text())
        self.assertTrue(users["users"][0]["password"].startswith("pbkdf2-sha256$"))     # only its hash is kept


class SuiteCatchesFaults(unittest.TestCase):
    """The suite fails a server that breaks a MUST.

    The faults of a public server share one server, each with its own handler: the suite writes nothing on it
    without a token, and a public server does not pair, so no run leaves anything (a code, a rate limit) that
    the next one would meet. A private server is made for each fault."""
    shared = None

    @classmethod
    def tearDownClass(cls):
        if cls.shared is not None:
            cls.shared.close()
            cls.shared = None

    def public(self, handler):
        cls = type(self)
        if cls.shared is None:
            cls.shared = Running()
        cls.shared.server.RequestHandlerClass = handler
        self.addCleanup(setattr, cls.shared.server, "RequestHandlerClass", ls.Handler)
        return cls.shared

    def fails(self, handler, cid, users=None, token_for=None, level="FAIL"):
        if users is None and token_for is None:
            srv = self.public(handler)
        else:
            srv = Running(users, handler=handler)
            self.addCleanup(srv.close)
        args = ["--token", srv.pair(*token_for)] if token_for else []
        code, report = run_suite(srv.url, *args)
        if level == "FAIL":
            self.assertEqual(code, 1, report)
        self.assertRegex(report, rf"{level}  § \S+\s+{re.escape(cid)} ", report)

    def test_missing_without_a_platform(self):
        class AnyPlatform(ls.Handler):
            def platform(self, query, required=False):
                return super().platform(query) or ("switch" if required else None)
        self.fails(AnyPlatform, "missing.no-platform")

    def test_platform_ignored(self):
        class Everything(ls.Handler):
            def platform(self, query, required=False):
                return "switch" if required else None
        self.fails(Everything, "platforms.filter")

    def test_titles_without_a_limit(self):
        class Unbounded(ls.Handler):
            def titles(self, query):
                query = {**query, "ids": ",".join((query.get("ids") or "").split(",")[:ls.TITLES_AT_ONCE])}
                super().titles(query)
        self.fails(Unbounded, "titles.bulk-limit")

    def edit_entry(self, change):
        class Edited(ls.Handler):
            def homebrew_view(self, entry, full):
                doc = super().homebrew_view(entry, True)
                change(doc)
                if not full:
                    doc["package"] = {k: v for k, v in doc["package"].items() if k != "manifest"}
                    if "packages" in doc:
                        doc["packages"] = [{k: v for k, v in p.items() if k != "manifest"} for p in doc["packages"]]
                return doc
        return Edited

    def test_kind_filter_ignored(self):
        class Unfiltered(ls.Handler):
            def homebrew_list(self, query):
                super().homebrew_list({k: v for k, v in query.items() if k != "kind"})
        self.fails(Unfiltered, "homebrew.filters")

    def test_category_served(self):
        def category(doc):
            doc["category"] = "tool"
        self.fails(self.edit_entry(category), "homebrew.pages")             # the schema refuses it

    def test_unknown_arch_warns(self):
        def loong(doc):
            if doc["id"] == library.HARBOR:
                doc["packages"] = [{**doc["packages"][0], "arch": ["loongarch64"]}]
        self.fails(self.edit_entry(loong), "homebrew.kinds", level="WARN")

    def test_cheat_set_not_kept(self):
        class Forgetful(ls.Handler):
            def cheat_post(self, query):
                fields = self.cheat_fields(query)
                self.send_doc(201, {"schema": 1, "id": "cs_forgotten", "platform": fields["platform"],
                                    "title_id": fields["title_id"], "build_id": fields["build_id"],
                                    "source": fields["source"], "size": len(fields["text"].encode()),
                                    "sha256": hashlib.sha256(fields["text"].encode()).hexdigest()})
        self.fails(Forgetful, "cheats.write-cycle", USERS, ("mila", EVERY_SCOPE))

    def test_request_asked_twice(self):
        class Twice(ls.Handler):
            def request_post(self, query):
                self.server.library.state["requests"] = []          # forgets the open one
                super().request_post(query)
        self.fails(Twice, "requests.create", USERS, ("mila", EVERY_SCOPE))

    def test_manifest_outside_the_roots(self):
        def outside(doc):
            if doc["id"] == library.FROSTLINE and doc["platform"] == "switch":
                manifest = doc["package"]["manifest"] + [{"path": "/bootloader/hekate_ipl.ini", "size": 1,
                                                          "sha256": "0" * 64}]
                doc["package"] = {**doc["package"], "manifest": manifest,
                                  "manifest_sha256": ls.manifest_digest(manifest)}
        self.fails(self.edit_entry(outside), "homebrew.manifests")

    def test_port_data_served(self):
        def shipped(doc):
            if doc["id"] == library.PORT:
                port = doc["port"]
                data = port["requires_data"][0]
                manifest = doc["package"]["manifest"] + [{"path": port["data_root"] + data["path"], "size": 1,
                                                          "sha256": data["accept"][0]["sha256"]}]
                doc["package"] = {**doc["package"], "manifest": manifest,
                                  "manifest_sha256": ls.manifest_digest(manifest)}
        self.fails(self.edit_entry(shipped), "homebrew.ports")

    def test_port_data_root_outside_the_areas(self):
        def outside(doc):
            if doc["id"] == library.PORT:
                doc["port"] = {**doc["port"], "data_root": "/atmosphere/frostline/"}
        self.fails(self.edit_entry(outside), "homebrew.ports")

    def test_port_data_path_escapes(self):
        def escape(doc):
            if doc["id"] == library.PORT:
                doc["port"] = {**doc["port"], "requires_data": [{"path": "../../atmosphere/x"}]}
        self.fails(self.edit_entry(escape), "homebrew.pages")     # the schema refuses it first

    def test_unknown_kind_served(self):
        def widget(doc):
            if doc["id"] == "org.example.ember-widget":
                doc["kind"] = "widget"
        self.fails(self.edit_entry(widget), "homebrew.kinds")

    def test_foreign_arch(self):
        def x86(doc):
            if doc["id"] == library.PORT:
                doc["package"] = {**doc["package"], "arch": ["aarch64", "x86_64"]}
        self.fails(self.edit_entry(x86), "homebrew.kinds")

    def test_signature_that_does_not_verify(self):
        def forged(doc):
            if doc["id"] == library.PAPERLAMP:
                doc["build"] = doc["build"] + 1
        self.fails(self.edit_entry(forged), "homebrew.signatures", level="WARN")

    def test_updates_of_every_build(self):
        class Everything(ls.Handler):
            def homebrew_updates(self, query):
                doc = self.request_document(self.body())
                self.body_data = json.dumps({**doc, "installed": [{**i, "build": 0} for i in doc["installed"]]}
                                            ).encode()
                super().homebrew_updates(query)
        self.fails(Everything, "homebrew.updates")

    def test_upload_digest_not_checked(self):
        class Trusting(ls.Handler):
            def upload(self, query, uid):
                saves = self.server.saves
                s = saves.session(uid, self.account["name"])
                if s and self.method == "PATCH":
                    whole = saves.part(uid).read_bytes() + self.body(saves.chunk)
                    if len(whole) == s["size"]:
                        s["sha256"] = hashlib.sha256(whole).hexdigest()    # whatever came is right
                super().upload(query, uid)
        self.fails(Trusting, "saves.upload-digest", USERS, ("mila", EVERY_SCOPE))

    def test_single_save_without_digest_kept(self):
        class Lax(ls.Handler):
            def save_post(self, query, title_id):
                if not self.headers.get("Content-Digest"):
                    data = self.body(self.server.saves.body)
                    self.headers["Content-Digest"] = "sha-256=:" + __import__("base64").b64encode(
                        hashlib.sha256(data).digest()).decode() + ":"
                super().save_post(query, title_id)
        self.fails(Lax, "saves.single", USERS, ("mila", EVERY_SCOPE))

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
            def send_head(self, status, length, headers, **kw):
                super().send_head(status, length, {k: v for k, v in headers.items() if k != "Repr-Digest"}, **kw)
        self.fails(NoDigest, "files.whole")

    def test_digest_on_ranges_missing(self):
        class NoRangeDigest(ls.Handler):
            def send_head(self, status, length, headers, **kw):
                if status == 206:
                    headers = {k: v for k, v in headers.items() if k != "Repr-Digest"}
                super().send_head(status, length, headers, **kw)
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
        apps = {f'{a["app_id"]}{a["format"]}{a["version_code"]}': a for a in self.all_apps()}
        self.assertEqual(len(apps), library.SERVED)
        moss = apps["0100EFEF00020000xci0"]
        self.assertEqual((moss["name"], moss["version_name"], moss["type"]), ("Moss & Ember", "1.0.0", "base"))
        phone = apps["org.example.frostlinetalesapk12"]
        self.assertEqual((phone["platform"], phone["title_id"], phone["type"]), ("android", phone["app_id"], "base"))
        self.assertTrue(all(a["platform"] == "switch" for k, a in apps.items() if k != "org.example.frostlinetalesapk12"))
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
        served = {a["path"].relative_to(self.srv.root).as_posix() for a in self.srv.lib.apps.values()}
        self.assertEqual(len(served), library.SERVED)
        self.assertLessEqual(served, set(state["hashes"]))
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{64}", h["sha256"]) for h in state["hashes"].values()))
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
        self.assertEqual({k for k, v in hello["features"].items() if v}, {"pairing", "signatures"})
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
            def route(self, method, path, query):
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
