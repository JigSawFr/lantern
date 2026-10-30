"""The reference server against the conformance suite, and their own tests.

    python3 -m unittest discover -s tests

Each test starts the server in this process on a free port, over a tiny
fictional library made in a temporary folder (tests/library.py).
"""
import base64
import importlib.util
import io
import json
import socket
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
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


class Running:
    """A reference server on a free port, over a fresh library."""

    def __init__(self, users=None, handler=ls.Handler, discovery=False):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = library.make(Path(self.tmp.name) / "library")
        users_path = None
        if users is not None:
            users_path = Path(self.tmp.name) / "users.json"
            users_path.write_text(json.dumps(users), encoding="utf-8")
        self.state = Path(self.tmp.name) / "state.json"
        self.lib = ls.Library(self.root, self.state)
        self.server = ls.LanternServer(("127.0.0.1", 0), self.lib, ls.Accounts(users_path), rescan=0,
                                       quiet=True, handler=handler)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}/"
        self.udp = ls.discovery(self.server, 0, self.port, None) if discovery else None
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        if self.udp:
            self.udp.close()
        self.tmp.cleanup()

    def get(self, path, auth=None, headers=None):
        req = urllib.request.Request(self.url.rstrip("/") + path, headers=headers or {})
        if auth:
            req.add_header("Authorization", "Basic " + base64.b64encode(":".join(auth).encode()).decode())
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def get_json(self, path, auth=None):
        status, _, body = self.get(path, auth)
        return status, json.loads(body)


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
            self.assertRegex(report, rf"PASS  § \S+\s+{cid} ", report)
        return report

    def test_public(self):
        srv = Running(discovery=True)
        self.addCleanup(srv.close)
        udp_port = srv.udp.getsockname()[1]
        report = self.passes(srv, "--discover", "127.0.0.1", "--discover-port", str(udp_port),
                             expect=["apps.pages.name", "missing.installed", "files.ranges", "discovery.reply",
                                     "schema.refused.library"])
        self.assertIn(f"{library.SERVED} apps in", report)

    def test_private_as_lea(self):
        srv = Running(USERS)
        self.addCleanup(srv.close)
        self.passes(srv, "--user", "lea", "--password", "frost-lantern",
                    expect=["auth.missing", "features.anonymous", "files.whole", "handshake.account"])

    def test_private_anonymously(self):
        srv = Running(USERS)
        self.addCleanup(srv.close)
        report = self.passes(srv, expect=["features.library"])
        self.assertIn("library=0", report)

    def test_frozen_account(self):
        srv = Running(USERS)
        self.addCleanup(srv.close)
        self.passes(srv, "--user", "noor", "--password", "moss-ember", expect=["auth.frozen"])

    def test_account_without_library_scope(self):
        srv = Running(USERS)
        self.addCleanup(srv.close)
        report = self.passes(srv, "--user", "ines", "--password", "paper-comet", expect=["features.library"])
        self.assertIn("Feature library (0)", report)


class SuiteCatchesFaults(unittest.TestCase):
    """The suite fails a server that breaks a MUST."""

    def fails(self, handler, cid):
        srv = Running(handler=handler)
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


class Server(unittest.TestCase):
    def setUp(self):
        self.srv = Running()
        self.addCleanup(self.srv.close)

    def all_apps(self):
        status, doc = self.srv.get_json("/api/lantern/v1/apps?page_size=500")
        self.assertEqual(status, 200)
        return doc["items"]

    def test_identity_from_names_and_library_json(self):
        apps = {f'{a["app_id"]}{a["format"]}{a["version"]}': a for a in self.all_apps()}
        self.assertEqual(len(apps), library.SERVED)
        moss = apps["0100EFEF00020000xci0"]
        self.assertEqual((moss["name"], moss["display_version"], moss["type"]), ("Moss & Ember", "1.0.0", "base"))
        update = apps["0100ABCD00010800nsz196608"]
        self.assertEqual((update["title_id"], update["type"]), ("0100ABCD00010000", "update"))
        self.assertEqual(apps["0100ABCD00011001nsp0"]["type"], "dlc")
        self.assertEqual(apps["0100E5F600050000nsp0"]["size"], 0)

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
        self.assertEqual(json.loads(self.srv.state.read_text()), newer)

    def test_state_keeps_unknown_keys(self):
        state = json.loads(self.srv.state.read_text())
        state["x-example"] = {"kept": True}
        self.srv.state.write_text(json.dumps(state))
        (self.srv.root / "Amber Signal [0100B7B700070000][v0].nsp").write_bytes(b"lantern")
        ls.Library(self.srv.root, self.srv.state)
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
        srv = Running(USERS)
        self.addCleanup(srv.close)
        status, hello = srv.get_json("/.well-known/lantern")
        self.assertEqual((status, hello["account"]["state"], set(hello["features"].values())), (200, "anonymous", {0}))
        status, problem = srv.get_json("/api/lantern/v1/apps")
        self.assertEqual((status, problem["code"]), (401, "unauthorized"))
        status, hello = srv.get_json("/api/lantern/v1/", auth=("lea", "frost-lantern"))
        self.assertEqual((hello["account"]["name"], hello["features"]["library"]), ("lea", 1))
        status, problem = srv.get_json("/api/lantern/v1/apps", auth=("noor", "moss-ember"))
        self.assertEqual((status, problem["code"]), (403, "account_frozen"))
        status, problem = srv.get_json("/api/lantern/v1/apps", auth=("ines", "paper-comet"))
        self.assertEqual((status, problem["code"]), (403, "forbidden"))

    def test_newer_users_file_lets_nobody_in(self):
        srv = Running({"schema": 2, "public": True, "users": USERS["users"]})
        self.addCleanup(srv.close)
        status, _ = srv.get_json("/api/lantern/v1/apps")
        self.assertEqual(status, 401)
        status, _ = srv.get_json("/api/lantern/v1/apps", auth=("lea", "frost-lantern"))
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
