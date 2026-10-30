"""Draft 0.3's additions, unit by unit: the NRO reader, manifests and port
data a server refuses, kinds, genres and arches, Linux homebrew with a
package per architecture, requirements and a client's decision, signatures
and pinning, the platform filter, titles, homebrew updates, cheats and
their writing, requests, resumable uploads, and the `schema` rule on every
state file.

    python3 -m unittest discover -s tests

Every NRO, archive and document is built here; fictional names only.
"""
import base64
import hashlib
import io
import json
import os
import random
import socket
import struct
import sys
import tempfile
import time
import unittest
import zipfile
import zlib
from pathlib import Path
from typing import ClassVar

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "conformance"))

import lantern_client as client
import library
from test_conformance import EVERY_SCOPE, USERS, Running

from server import ed25519, nro
from server import lantern_server as ls

API = "/api/lantern/v1"


def deflated_nacp(names, version="2.0.0"):
    """A NACP whose title block is Deflate-compressed (TitlesDataFormat 1,
    firmware 21.0.0 and later): `names` maps a language's index (0 to 31) to
    (name, author)."""
    titles = bytearray(0x6000)
    for i, (name, author) in names.items():
        titles[i * 0x300:i * 0x300 + len(name.encode())] = name.encode()
        titles[i * 0x300 + 0x200:i * 0x300 + 0x200 + len(author.encode())] = author.encode()
    packer = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = packer.compress(bytes(titles)) + packer.flush()
    nacp = bytearray(0x4000)
    struct.pack_into("<H", nacp, 0, len(packed))
    nacp[2:2 + len(packed)] = packed
    nacp[0x3060:0x3060 + len(version)] = version.encode()
    nacp[0x3215] = 1
    return bytes(nacp)


def with_nacp(nacp, code=b"\0" * 64):
    """An .nro around a given NACP (library.nro's layout)."""
    head = bytearray(0x80)
    head[0x10:0x14] = b"NRO0"
    struct.pack_into("<I", head, 0x18, 0x80 + len(code))
    assets = b"ASET" + struct.pack("<I", 0) + struct.pack("<QQ", 0x38, 0) + struct.pack("<QQ", 0x38, len(nacp)) \
        + struct.pack("<QQ", 0, 0)
    return bytes(head) + code + assets + nacp


class CountingReader(io.BytesIO):
    """A file that counts the bytes read from it."""

    def __init__(self, data):
        super().__init__(data)
        self.count = 0

    def read(self, size=-1):
        out = super().read(size)
        self.count += len(out)
        return out


class NroReader(unittest.TestCase):
    """server/nro.py: what it reads of an .nro, and what it survives."""

    def test_reads_the_control_data(self):
        info = nro.parse_nro(library.nro("Paper Lamp", "Ines", "0.9.2"))
        self.assertEqual(info, {"name": "Paper Lamp", "author": "Ines", "version": "0.9.2"})

    def test_deflated_title_block(self):
        data = with_nacp(deflated_nacp({0: ("Moss Clock", "Lea"), 17: ("Zegar z mchu", "Lea")}, "2.1.0"))
        self.assertEqual(nro.parse_nro(data), {"name": "Moss Clock", "author": "Lea", "version": "2.1.0"})
        # A seventeenth language alone: still found.
        data = with_nacp(deflated_nacp({17: ("Zegar z mchu", "Noor")}))
        self.assertEqual(nro.parse_nro(data)["name"], "Zegar z mchu")

    def test_deflated_block_broken_or_unknown(self):
        good = bytearray(deflated_nacp({0: ("Moss Clock", "Lea")}))
        size = struct.unpack_from("<H", good, 0)[0]
        cut = bytearray(good)
        struct.pack_into("<H", cut, 0, size // 2)                   # a stream cut short
        garbage = bytearray(good)
        garbage[2:2 + size] = os.urandom(size)                     # not Deflate
        zero = bytearray(good)
        struct.pack_into("<H", zero, 0, 0)
        huge = bytearray(good)
        struct.pack_into("<H", huge, 0, 0xFFFF)                    # past the block
        future = bytearray(good)
        future[0x3215] = 2                                          # a format it does not know
        for nacp in (cut, garbage, zero, huge, future):
            self.assertIsNone(nro.parse_nro(with_nacp(bytes(nacp))))

    def test_deflate_bomb_is_bounded(self):
        """A block that inflates to 10 MiB: read up to 0x6000 bytes, no more."""
        packer = zlib.compressobj(9, zlib.DEFLATED, -15)
        packed = packer.compress(b"A" * (10 << 20)) + packer.flush()
        self.assertLess(len(packed), 0x2FFE)
        nacp = bytearray(0x4000)
        struct.pack_into("<H", nacp, 0, len(packed))
        nacp[2:2 + len(packed)] = packed
        nacp[0x3215] = 1
        started = time.monotonic()
        info = nro.parse_nro(with_nacp(bytes(nacp)))
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(len(info["name"].encode()), 512)

    def test_truncated(self):
        data = library.nro("Paper Lamp", "Ines", "0.9.2")
        for n in (0, 1, 0x10, 0x14, 0x7F, 0x80, 0xC0, 0xC0 + 0x37, 0xC0 + 0x38 + 32 + 0x100, len(data) - 0x4000 + 0x3215):
            self.assertIsNone(nro.parse_nro(data[:n]), n)

    def test_garbage(self):
        rng = random.Random(47115)
        for _ in range(200):
            blob = bytes(rng.getrandbits(8) for _ in range(rng.randrange(0, 0x400)))
            self.assertIsNone(nro.parse_nro(blob))
        # The right magics around nonsense offsets.
        for nro_size, offset, size in ((0xFFFFFFFF, 0, 0), (0x80, 0, 0x4000), (0xC0, 1 << 63, 0x4000),
                                       (0xC0, 0x38, 1 << 63), (0xC0, (1 << 64) - 1, 0x4000), (0x10, 0x38, 0x4000)):
            head = bytearray(0x80)
            head[0x10:0x14] = b"NRO0"
            struct.pack_into("<I", head, 0x18, nro_size)
            assets = b"ASET" + bytes(20) + struct.pack("<QQ", offset, size) + bytes(16)
            self.assertIsNone(nro.parse_nro(bytes(head) + bytes(0x40) + assets + bytes(0x100)))

    def test_oversized_reads_only_what_it_needs(self):
        data = library.nro("Paper Lamp", "Ines", "0.9.2") + bytes(16 << 20)
        f = CountingReader(data)
        self.assertEqual(nro.read_nro(f, len(data))["name"], "Paper Lamp")
        self.assertLess(f.count, 0x4000)

    def test_hostile_texts(self):
        info = nro.parse_nro(library.nro("Lamp\x1b[31m\x07", "\xff\xfeNoor", "1.0\n"))
        self.assertEqual(info["name"], "Lamp[31m")
        self.assertNotIn("\x07", info["name"])
        self.assertTrue(info["author"].endswith("Noor"))
        self.assertEqual(info["version"], "1.0")
        long_name = nro.parse_nro(library.nro("é" * 400, "Lea", "1"))["name"]
        self.assertLessEqual(len(long_name.encode()), 512)


def zipped(files):
    return library.zipped(files)


def hinted(value):
    """`value` with a hint on every data file that has none (None removes it), so
    that each hostile case is refused for its own reason."""
    if isinstance(value, list):
        return [hinted(v) for v in value]
    if isinstance(value, dict):
        out = {k: hinted(v) for k, v in value.items()}
        if "path" in out:
            out.setdefault("hint", "In the game's folder.")
            if out["hint"] is None:
                del out["hint"]
        return out
    return value


class HostileHomebrew(unittest.TestCase):
    """What the reference server refuses to serve, and why the client would refuse it too."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "library"
        (self.root / "homebrew").mkdir(parents=True)
        self.n = 0

    def add(self, files, meta=None, name="p.zip"):
        self.n += 1
        folder = self.root / "homebrew" / f"h{self.n}"
        folder.mkdir()
        (folder / name).write_bytes(files if isinstance(files, bytes) else zipped(files))
        if meta is not None:
            (folder / "homebrew.json").write_text(json.dumps({"schema": 1, **meta}))
        return folder

    def served(self):
        return ls.Library(self.root, Path(self.tmp.name) / "state.json").homebrew

    def test_hostile_manifests(self):
        hid = "org.example.lamp"
        ok = {f"switch/{hid}/lamp.nro": b"lamp"}
        for files in ({f"switch/{hid}/../../atmosphere/x": b"x"},
                      {"/etc/lantern": b"x"},                                  # absolute in the archive
                      {"C:/switch/x.nro": b"x"},                               # a drive letter
                      {f"switch\\{hid}\\..\\x.nro": b"x"},                     # backslashes
                      {f"switch/{hid}/a\x01.nro": b"x"},                       # a control character
                      {f"switch/{hid}/Lamp.nro": b"x", f"switch/{hid}/LAMP.NRO": b"y"},   # twice, case ignored
                      {f"switch/{hid}/{'x' * 256}": b"x"},                     # a part above 255 bytes
                      {"bootloader/hekate_ipl.ini": b"x"},                     # outside the roots
                      {"switch/org.example.other/x.nro": b"x"},               # another homebrew's folder
                      {f"switch/{hid}/{i}.bin": b"" for i in range(4097)}):    # above 4096 files
            self.add({**ok, **files}, {"id": hid, "build": 1})
        self.add(b"PK\x03\x04 broken", {"id": hid, "build": 1})
        self.assertEqual(self.served(), {})

    def test_consent_paths_are_served_and_planned(self):
        hid = "org.example.overlay"
        self.add({f"switch/.overlays/{hid}.ovl": b"o", "atmosphere/contents/0100000000ABC000/exefs.nsp": b"s",
                  f"config/{hid}/a.ini": b"a"}, {"id": hid, "build": 1, "kind": "overlay"})
        entry = next(iter(self.served().values()))["doc"]
        plan = client.install_plan(entry)
        self.assertEqual(plan["free"], [f"/config/{hid}/a.ini"])
        self.assertEqual(sorted(plan["consent"]), sorted(["/atmosphere/contents/0100000000ABC000/exefs.nsp",
                                                         f"/switch/.overlays/{hid}.ovl"]))

    def test_client_refuses_hostile_manifests(self):
        base = {"platform": "switch", "id": "org.example.lamp"}
        for path in ("relative/x", "/switch/org.example.lamp/../x", "/switch//x", "/switch/a\\b", "C:/x",
                     "/switch/org.example.lamp/a:b", "/x\x00", "/" + "a" * 1025, "/bootloader/x"):
            entry = {**base, "package": {"path": path, "size": 1, "sha256": "0" * 64}}
            with self.assertRaises(client.Refused, msg=path):
                client.install_plan(entry)
        with self.assertRaises(client.Refused):
            client.install_plan({"platform": "vita", "id": "org.example.lamp", "package": {}})

    def test_hostile_requires_data(self):
        good = json.loads(library.port())
        for i, change in enumerate((
                {"data_root": "/atmosphere/frost/"},                   # outside the areas
                {"data_root": "/switch/"},                             # an area itself
                {"data_root": "/switch/frost"},                        # not a folder
                {"data_root": "/switch/../frost/"},
                {"requires_data": [{"path": "../../atmosphere/x"}]},
                {"requires_data": [{"path": "data/../../x"}]},
                {"requires_data": [{"path": "/switch/frostline/frost.pak"}]},
                {"requires_data": [{"path": "C:/frost.pak"}]},
                {"requires_data": [{"path": "data\\frost.pak"}]},
                {"requires_data": [{"path": ""}]},
                {"requires_data": [{"path": "a.pak"}, {"path": "a.pak"}]},
                {"requires_data": [{"path": "a.pak", "accept": [{"label": "1.0", "sha256": "ABC"}]}]},
                {"requires_data": [{"path": "a.pak", "accept": [{"sha256": "0" * 64}]}]},
                {"requires_data": [{"path": "a.pak", "accept": [{"label": "1.0"}]}]},
                {"requires_data": [{"path": "a.pak", "optional": "yes"}]},
                {"requires_data": [{"one_of": [[{"path": "a.pak"}]]}]},
                {"requires_data": [{"one_of": [[{"path": "a.pak"}], []]}]},
                {"requires_data": [{"one_of": [[{"one_of": []}], [{"path": "b.pak"}]]}]},
                {"requires_data": [{"path": f"{i}.pak"} for i in range(257)]},       # above 256 files
                {"requires_data": [{"path": "a.pak", "accept": [{"label": str(i), "md5": f"{i:032x}"}
                                                               for i in range(33)]}]},   # above 32 versions
                {"requires_data": [{"path": "a.pak", "hint": None}]},                 # no hint
                {"requires_data": "frost.pak"},
                {"engine": {"version": "1"}},
                {"original": {"name": "Frostline Tales", "stores": [{"store": "example", "url": "http://x"}]}})):
            hid = f"org.example.bad{i}"
            meta = {**good, "id": hid, "port": {**good["port"], **hinted(change)}}
            meta.pop("schema")
            self.add({f"switch/{hid}/p.nro": b"p"}, meta)
            served = self.served()
            self.assertNotIn(("switch", hid), served, change)
            doc = {"platform": "switch", "id": hid, "package": {"manifest": []}, "port": meta["port"]}
            self.assertTrue(client.port_problems(doc), change)
            (self.root / "homebrew" / f"h{self.n}" / "homebrew.json").unlink()   # leave the next ones alone

    def test_data_root_on_a_platform_without_areas(self):
        meta = json.loads(library.port())
        meta.pop("schema")
        self.add(os.urandom(32), {**meta, "platform": "vita", "arch": None, "id": "org.example.vitaport"},
                 name="port.vpk")
        self.assertEqual(self.served(), {})

    def test_good_port_data_passes(self):
        self.assertEqual(ls.port_problem(library.PORT_OBJECT, ("/switch/", "/config/")), None)


class Homebrew(unittest.TestCase):
    """The library's homebrew as the server serves them."""

    @classmethod
    def setUpClass(cls):
        cls.srv = Running()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def entry(self, hid, platform="switch", lang="en"):
        status, _, body = self.srv.request(f"{API}/homebrew/{hid}", headers={"Lantern-Platform": platform,
                                                                              "Accept-Language": lang})
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def test_port_entry(self):
        doc = self.entry(library.PORT)
        self.assertEqual(doc["kind"], "port")
        port = doc["port"]
        self.assertEqual(port["original"]["name"], "Frostline Tales")
        self.assertEqual(port["engine"]["name"], "Lanternlight")
        self.assertEqual((port["data_root"], port["assets"]), (library.PORT_DATA_ROOT, "user_owned"))
        frost, music, bonus = port["requires_data"]
        self.assertEqual([a["label"] for a in frost["accept"]], ["1.0", "1.1", "1.1 Gold edition"])
        self.assertEqual(set(frost["accept"][1]), {"label", "sha256", "md5"})
        self.assertEqual(set(frost["accept"][2]), {"label", "sha1"})
        self.assertTrue(frost["hint"].startswith("frost.pak, in the folder"))
        self.assertEqual(len(music["one_of"]), 2)
        self.assertTrue(bonus["optional"])
        self.assertNotIn("arch", doc["package"])                       # one architecture on a Switch
        self.assertEqual(doc["assets_license"], "CC-BY-4.0")
        self.assertEqual(doc["genres"], ["adventure"])
        self.assertEqual(doc["requires"]["homebrew"], [{"id": "org.example.lanternlight-runtime", "min_build": 200}])
        self.assertEqual(client.port_problems(doc), [])
        manifest = {m["path"] for m in doc["package"]["manifest"]}
        self.assertFalse(manifest & {library.PORT_DATA_ROOT + f["path"] for f in client.data_files(port["requires_data"])})
        self.assertTrue(self.entry(library.PORT, lang="fr")["port"]["requires_data"][0]["hint"].startswith("frost.pak, dans"))

    def test_launch_check(self):
        doc = self.entry(library.PORT)
        h = client.file_hashes
        nothing = client.launch_check(doc, {})
        self.assertEqual(nothing["missing"], ["data/frost.pak", "music/full.pak", "music/full.idx"])
        self.assertEqual(nothing["absent_optional"], ["Extras/Bonus Maps.pak"])
        self.assertEqual(nothing["choices"], [[["music/full.pak", "music/full.idx"], ["music/demo.pak"]]])
        for version in library.FROST_PAK:       # each accepted version, by sha256, by sha256 and md5, by sha1
            ready = client.launch_check(doc, {"data/frost.pak": h(version), "music/demo.pak": h(b"demo")})
            self.assertEqual((ready["missing"], ready["wrong"]), ([], []), version[:20])
        wrong = client.launch_check(doc, {"data/frost.pak": h(b"another game"), "music/demo.pak": h(b"x")})
        self.assertEqual(wrong["wrong"], ["data/frost.pak"])
        case = client.launch_check(doc, {"data/Frost.pak": h(library.FROST_PAK[0]), "music/demo.pak": h(b"x")})
        self.assertEqual(case["missing"], ["data/frost.pak"])          # exact, case included
        half = client.launch_check(doc, {"data/frost.pak": h(library.FROST_PAK[0]), "music/full.pak": h(b"x")})
        self.assertEqual(half["missing"], ["music/full.idx"])

    def test_unknown_kind_is_an_app(self):
        doc = self.entry("org.example.ember-widget")
        self.assertEqual(doc["kind"], "app")
        self.assertEqual(client.kind_of({"kind": "widget"}), "app")
        self.assertEqual(client.kind_of({}), "app")
        self.assertEqual(client.kind_of({"kind": "port"}), "port")

    def test_arches(self):
        self.assertTrue(client.arch_ok({}, "switch"))
        self.assertFalse(client.arch_ok({"arch": ["aarch64"]}, "switch"))     # none on a platform of one arch
        self.assertFalse(client.arch_ok({"arch": "aarch64"}, "android"))      # a list, not a string
        self.assertFalse(client.arch_ok({"arch": ["ARM 64"]}, "android"))
        self.assertTrue(client.arch_ok({"arch": ["riscv64"]}, "linux"))       # a later name, of the form
        self.assertTrue(client.arch_ok({"arch": ["x86_64", "aarch64"]}, "linux", mine="aarch64"))
        self.assertFalse(client.arch_ok({"arch": ["x86_64"]}, "linux", mine="armhf"))
        entry = {"package": {"arch": ["aarch64"], "sha256": "a"}, "packages": [
            {"arch": ["armhf"], "sha256": "b"}, {"arch": ["x86_64"], "sha256": "c"}]}
        self.assertEqual(client.pick_package(entry, "armhf")["sha256"], "b")
        self.assertIsNone(client.pick_package(entry, "x86"))
        entry["packages"].append({"sha256": "d"})
        self.assertEqual(client.pick_package(entry, "x86")["sha256"], "d")
        phone = self.entry("org.example.mossremote", "android")
        self.assertEqual((phone["package"]["arch"], phone["package"]["manifest"], phone["system_id"]),
                         (["aarch64", "armhf"], [], "org.example.mossremote"))
        self.assertNotIn("path", phone["package"])
        self.assertRegex(phone["package"]["signer_sha256"], r"^[0-9a-f]{64}$")

    def test_overlay(self):
        doc = self.entry("org.example.ember-overlay")
        self.assertEqual((doc["kind"], doc["package"]["format"], doc["package"]["path"]),
                         ("overlay", "ovl", "/switch/.overlays/ember.ovl"))
        self.assertEqual(client.install_plan(doc), {"free": [], "consent": ["/switch/.overlays/ember.ovl"]})
        self.assertEqual(doc["requires"]["homebrew"], [{"id": "org.example.overlay-loader", "min_build": 1}])

    def test_unknown_assets_read_as_user_owned(self):
        self.assertEqual(client.assets_of({"port": {"assets": "borrowed"}}), "user_owned")
        self.assertEqual(client.assets_of({"port": {"assets": "demo_included"}}), "demo_included")
        meta = json.loads(library.port(assets="borrowed"))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name) / "library" / "homebrew" / "p"
        folder.mkdir(parents=True)
        (folder / "p.zip").write_bytes(library.port_zip())
        (folder / "homebrew.json").write_text(json.dumps(meta))
        lib = ls.Library(Path(tmp.name) / "library", Path(tmp.name) / "state.json")
        self.assertEqual(lib.homebrew[("switch", library.PORT)]["doc"]["port"]["assets"], "user_owned")

    def test_nro_placed_and_named_from_its_nacp(self):
        doc = self.entry("local.moss-clock")
        self.assertEqual((doc["name"], doc["author"], doc["version"]), ("Moss Clock", "Lea", "2.1.0"))
        self.assertEqual(doc["package"]["path"], "/switch/local.moss-clock/local.moss-clock.nro")
        self.assertEqual(doc["build"], 2001000)
        paper = self.entry(library.PAPERLAMP)
        self.assertEqual((paper["name"], paper["build"]), ("Paper Lamp", 902))     # build from homebrew.json

    def test_same_id_on_two_platforms(self):
        status, _, body = self.srv.request(f"{API}/homebrew/{library.FROSTLINE}")
        self.assertEqual((status, json.loads(body)["code"]), (400, "bad_request"))
        self.assertEqual(self.entry(library.FROSTLINE, "3ds")["build"], 10100)
        self.assertEqual(self.entry(library.FROSTLINE, "switch")["build"], 10400)

    def updates(self, installed, platform="switch"):
        status, _, body = self.srv.request(f"{API}/homebrew/updates", data={"schema": 1, "installed": installed},
                                           headers={"Lantern-Platform": platform} if platform else {})
        return status, json.loads(body)

    def test_updates(self):
        status, doc = self.updates([{"id": library.FROSTLINE, "build": 10300}, {"id": library.PAPERLAMP, "build": 902},
                                    {"id": "org.example.nowhere", "build": 1}])
        self.assertEqual((status, [e["id"] for e in doc["items"]]), (200, [library.FROSTLINE]))
        self.assertNotIn("manifest", doc["items"][0]["package"])
        status, doc = self.updates([{"id": library.FROSTLINE, "build": 10000}], "3ds")
        self.assertEqual([(e["platform"], e["build"]) for e in doc["items"]], [("3ds", 10100)])
        status, doc = self.updates([{"id": library.FROSTLINE, "build": 10400}])
        self.assertEqual(doc["items"], [])
        status, doc = self.updates([], None)
        self.assertEqual((status, doc["code"]), (400, "bad_request"))
        status, doc = self.updates([{"id": "Not An Id", "build": 1}])
        self.assertEqual(status, 400)

    def test_listing_filters(self):
        _, _, body = self.srv.request(f"{API}/homebrew?kind=port")
        self.assertEqual([e["id"] for e in json.loads(body)["items"]], [library.PORT, library.HARBOR])
        _, _, body = self.srv.request(f"{API}/homebrew?kind=port", headers={"Lantern-Platform": "linux"})
        self.assertEqual([e["id"] for e in json.loads(body)["items"]], [library.HARBOR])
        _, _, body = self.srv.request(f"{API}/homebrew?kind=widget")       # served as an app
        self.assertEqual(json.loads(body)["items"], [])
        _, _, body = self.srv.request(f"{API}/homebrew?genre=puzzle")
        self.assertEqual([e["id"] for e in json.loads(body)["items"]], [library.PAPERLAMP])
        _, _, body = self.srv.request(f"{API}/homebrew?genre=adventure&kind=port")
        self.assertEqual([e["id"] for e in json.loads(body)["items"]], [library.PORT, library.HARBOR])
        _, _, body = self.srv.request(f"{API}/homebrew?genre=roguelite")    # well formed, unknown: empty
        self.assertEqual(json.loads(body)["items"], [])
        for bad in ("genre=Puzzle", "genre=a%20b", "kind=Port", "kind=" + "x" * 33):
            status, _, body = self.srv.request(f"{API}/homebrew?{bad}")
            self.assertEqual((status, json.loads(body)["code"]), (400, "bad_request"), bad)
        status, _, body = self.srv.request(f"{API}/homebrew?category=tool")    # gone: not a filter any more
        self.assertEqual((status, len(json.loads(body)["items"])), (200, library.SERVED_HOMEBREW))
        _, _, body = self.srv.request(f"{API}/homebrew?platform=3ds")
        self.assertEqual([e["platform"] for e in json.loads(body)["items"]], ["3ds"])
        _, _, body = self.srv.request(f"{API}/homebrew?q=lamp")
        self.assertEqual([e["id"] for e in json.loads(body)["items"]], [library.PAPERLAMP])


class Signatures(unittest.TestCase):
    """Ed25519 (RFC 8032) as the server checks it and the client pins it (SPEC.md § 8.4)."""

    # RFC 8032, § 7.1, test 1 (empty message) and test 2.
    VECTORS = (
        ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
         "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
         "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
        ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
         "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
         "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    )

    def test_rfc8032_vectors(self):
        for seed, public, message, signature in self.VECTORS:
            pub, sig = library.ed25519_sign(bytes.fromhex(seed), bytes.fromhex(message))
            self.assertEqual((pub.hex(), sig.hex()), (public, signature))
            for verify in (ed25519.verify, client.ed25519_verify):
                self.assertTrue(verify(bytes.fromhex(public), bytes.fromhex(message), bytes.fromhex(signature)))
                self.assertFalse(verify(bytes.fromhex(public), b"another message", bytes.fromhex(signature)))
                bad = bytearray.fromhex(signature)
                bad[63] ^= 0x10                                  # s above L
                self.assertFalse(verify(bytes.fromhex(public), bytes.fromhex(message), bytes(bad)))
                self.assertFalse(verify(b"\0" * 31, b"", bytes.fromhex(signature)))

    def test_canonical_bytes(self):
        entry = {"id": library.PAPERLAMP, "platform": "switch", "build": 902,
                 "package": {"sha256": "a" * 64, "manifest_sha256": "b" * 64}}
        expected = ('{"build":902,"id":"org.example.paperlamp","manifest_sha256":"' + "b" * 64 + '",'
                    '"platform":"switch","purpose":"lantern-homebrew-1","sha256":"' + "a" * 64 + '"}').encode()
        self.assertEqual(client.signed_message(entry), expected)
        self.assertEqual(ls.signed_bytes(entry), expected)

    def test_served_signature_verifies_and_pins(self):
        srv = Running()
        self.addCleanup(srv.close)
        _, _, body = srv.request(f"{API}/homebrew/{library.PAPERLAMP}")
        doc = json.loads(body)
        self.assertTrue(client.verify_signature(doc))
        self.assertIs(client.verify_signature(json.loads(srv.request(f"{API}/homebrew/local.moss-clock")[2])), None)
        self.assertFalse(client.verify_signature({**doc, "build": 903}))
        self.assertEqual(srv.request(f"{API}/homebrew/org.example.forged")[0], 404)   # not served
        key = doc["signature"]["public_key"]
        self.assertEqual(client.key_change(None, doc), "pin")
        self.assertEqual(client.key_change(key, doc), "same")
        other = {**doc, "signature": {**doc["signature"], "public_key": base64.b64encode(b"\1" * 32).decode()}}
        self.assertEqual(client.key_change(key, other), "changed")
        self.assertEqual(client.key_change(key, {k: v for k, v in doc.items() if k != "signature"}), "changed")
        self.assertEqual(client.key_change("", doc), "changed")         # signed after unsigned
        self.assertRegex(client.key_fingerprint(key), r"^[0-9A-F]{4}( [0-9A-F]{4}){3}$")


class Platforms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = Running()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def get(self, path, platform=None):
        status, headers, body = self.srv.request(path, headers={"Lantern-Platform": platform} if platform else {})
        return status, headers, json.loads(body)

    def test_handshake_lists_them(self):
        _, _, hello = self.get("/.well-known/lantern")
        self.assertEqual(hello["platforms"], ["3ds", "android", "linux", "switch"])
        self.assertEqual(hello["limits"]["saves_kept_per_title"], ls.SAVES_KEPT)

    def test_filter(self):
        _, headers, every = self.get(f"{API}/apps?page_size=500")
        _, _, switch = self.get(f"{API}/apps?page_size=500", "switch")
        _, _, phone = self.get(f"{API}/apps?page_size=500", "android")
        self.assertEqual((every["total"], switch["total"], phone["total"]), (library.SERVED, library.SWITCH, 1))
        self.assertEqual({a["platform"] for a in phone["items"]}, {"android"})
        _, _, query = self.get(f"{API}/apps?page_size=500&platform=android", "switch")
        self.assertEqual(query["items"], phone["items"])
        self.assertIn("Lantern-Platform", headers["Vary"])
        _, _, nobody = self.get(f"{API}/apps", "ps4")
        self.assertEqual((nobody["items"], nobody["total"]), ([], 0))
        for bad in ("Switch", "-switch", "x" * 33, "switch os"):
            status, _, problem = self.get(f"{API}/apps", bad)
            self.assertEqual((status, problem["code"]), (400, "bad_request"), bad)

    def test_missing_needs_a_platform(self):
        doc = {"schema": 1, "installed": [], "want": ["base"]}
        status, _, body = self.srv.request(f"{API}/apps/missing", data=doc)
        self.assertEqual((status, json.loads(body)["code"]), (400, "bad_request"))
        status, _, body = self.srv.request(f"{API}/apps/missing?platform=android", data=doc)
        self.assertEqual([a["platform"] for a in json.loads(body)["items"]], ["android"])

    def test_android_update_is_a_newer_base(self):
        doc = {"schema": 1, "installed": [{"app_id": "org.example.frostlinetales", "version_code": 11}],
               "want": ["update"]}
        _, _, body = self.srv.request(f"{API}/apps/missing", data=doc, headers={"Lantern-Platform": "android"})
        self.assertEqual([a["version_code"] for a in json.loads(body)["items"]], [12])

    def test_titles(self):
        _, _, sheet = self.get(f"{API}/titles/org.example.frostlinetales")
        self.assertEqual(sheet["platform"], "android")
        status, _, _ = self.get(f"{API}/titles/org.example.frostlinetales", "switch")
        self.assertEqual(status, 404)


class Titles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = Running()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def test_bulk(self):
        ids = ["0100ABCD00010000", "0100EFEF00020000", "05FFFFFFFFFF0000"]
        status, _, body = self.srv.request(f"{API}/titles?ids={','.join(ids)}", headers={"Accept-Language": "fr"})
        doc = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual([t["title_id"] for t in doc["titles"]], ids[:2])
        self.assertEqual(doc["unknown"], ids[2:])
        frost = doc["titles"][0]
        self.assertEqual((frost["language"], frost["summary"][:7]), ("fr", "Guidez "))
        self.assertEqual(frost["genres"], ["adventure", "puzzle"])        # dating-sim dropped
        self.assertEqual(frost["ratings"], [{"system": "PEGI", "rating": "7"}])
        self.assertEqual(frost["video"], {"url": "https://video.example.org/frostline/trailer", "external": True})

    def test_bulk_limit(self):
        ids = [f"05{i:010X}0000" for i in range(ls.TITLES_AT_ONCE)]
        self.assertEqual(self.srv.request(f"{API}/titles?ids={','.join(ids)}")[0], 200)
        status, _, body = self.srv.request(f"{API}/titles?ids={','.join(ids + ['0500000000FF0000'])}")
        self.assertEqual((status, json.loads(body)["code"]), (400, "bad_request"))
        self.assertEqual(self.srv.request(f"{API}/titles")[0], 400)
        self.assertEqual(self.srv.request(f"{API}/titles?ids=not%20an%20id")[0], 400)

    def test_changes(self):
        _, _, body = self.srv.request(f"{API}/titles/changes")
        start = json.loads(body)
        self.assertEqual((start["titles"], start["removed"], start["more"]), ([], [], False))
        meta = json.loads((self.srv.root / "library.json").read_text())
        meta["apps"][1]["developer"] = "Ember Folk"
        meta["apps"] = [a for a in meta["apps"] if "Tidewalker" not in a["file"]]
        (self.srv.root / "library.json").write_text(json.dumps(meta))
        (self.srv.root / "more" / "Tidewalker [0100C3D400040000][v0].nsp").unlink()
        _, _, body = self.srv.request(f"{API}/titles/changes?since={start['since']}")
        later = json.loads(body)
        self.assertEqual([t["title_id"] for t in later["titles"]], ["0100EFEF00020000"])
        self.assertEqual(later["titles"][0]["developer"], "Ember Folk")
        self.assertEqual(later["removed"], [{"platform": "switch", "title_id": "0100C3D400040000"}])
        _, _, body = self.srv.request(f"{API}/titles/changes?since={start['since']}",
                                           headers={"Lantern-Platform": "android"})
        self.assertEqual(json.loads(body)["titles"], [])
        self.assertEqual(self.srv.request(f"{API}/titles/changes?since=t_nope")[0], 400)


class Cheats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = Running(USERS)
        cls.token = cls.srv.pair("mila", EVERY_SCOPE)

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def test_sets_and_text(self):
        status, _, body = self.srv.request(f"{API}/cheats?title_id=0100ABCD00010000&build_id=4A1B2C3D4E5F6071",
                                           token=self.token)
        sets = json.loads(body)["cheats"]
        self.assertEqual([s["source"] for s in sets], ["Community list", "Noor"])
        status, headers, text = self.srv.request(f"{API}/cheats/{sets[0]['id']}", token=self.token)
        self.assertEqual((status, hashlib.sha256(text).hexdigest(), len(text)), (200, sets[0]["sha256"], sets[0]["size"]))
        self.assertIn("Repr-Digest", headers)
        self.assertEqual(self.srv.request(f"{API}/cheats/cs_nope", token=self.token)[0], 404)
        self.assertEqual(self.srv.request(f"{API}/cheats", token=self.token, method="POST", data={"schema": 1})[0], 400)
        status, headers, _ = self.srv.request(f"{API}/cheats", token=self.token, method="PATCH", data={"schema": 1})
        self.assertEqual((status, headers["Allow"]), (405, "GET, HEAD, POST"))
        self.assertEqual(self.srv.request(f"{API}/cheats?build_id=no%20build", token=self.token)[0], 400)

    def test_scope(self):
        lea = self.srv.pair("lea")
        self.assertEqual(self.srv.request(f"{API}/cheats", token=lea)[0], 403)


class Saves(unittest.TestCase):
    """Save backups (SPEC.md § 9): resumable uploads, one-request saves, and their index."""

    def setUp(self):
        self.srv = Running(USERS)
        self.addCleanup(self.srv.close)
        self.token = self.srv.pair("mila", EVERY_SCOPE)
        self.data = library.zipped({"save/slot1.dat": os.urandom(5000)})

    def call(self, path, method=None, data=None, headers=None, platform="switch"):
        headers = dict(headers or {})
        if platform:
            headers["Lantern-Platform"] = platform
        return self.srv.request(path, token=self.token, method=method, data=data, headers=headers)

    def open(self, data=None, **fields):
        data = self.data if data is None else data
        doc = {"schema": 1, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "kind": "account",
               "profile": "Mila", "slot": "slot1", **fields}
        status, _, body = self.call(f"{API}/saves/0100ABCD00010000/uploads", data=doc)
        self.assertEqual(status, 201, body)
        return json.loads(body)

    def patch(self, upload, offset, chunk, **headers):
        return self.call(upload, "PATCH", chunk, {"Upload-Offset": str(offset),
                                                  "Content-Type": "application/offset+octet-stream", **headers})

    def head(self, upload):
        status, headers, _ = self.call(upload, "HEAD")
        return status, headers

    def test_resumed_after_an_interruption(self):
        up = self.open()
        url = up["upload"]
        half = len(self.data) // 2
        self.assertEqual(self.patch(url, 0, self.data[:1000])[0], 204)
        # The connection drops in the middle of the next chunk: nothing of it is kept.
        with socket.create_connection(("127.0.0.1", self.srv.port)) as s:
            s.sendall((f"PATCH {url} HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {self.token}\r\n"
                       f"Upload-Offset: 1000\r\nContent-Type: application/offset+octet-stream\r\n"
                       f"Content-Length: {half - 1000}\r\n\r\n").encode() + self.data[1000:1500])
        for _ in range(50):
            status, headers = self.head(url)
            if headers["Upload-Offset"] == "1000":
                break
            time.sleep(0.05)
        self.assertEqual((status, headers["Upload-Offset"], headers["Upload-Length"]), (204, "1000", str(len(self.data))))
        # A chunk at the wrong offset: 409 with the server's.
        status, headers, body = self.patch(url, 1500, self.data[1500:2000])
        self.assertEqual((status, json.loads(body)["code"], headers["Upload-Offset"]), (409, "conflict", "1000"))
        # A chunk whose own digest is wrong: 422, and not kept.
        wrong = "sha-256=:" + base64.b64encode(hashlib.sha256(b"x").digest()).decode() + ":"
        status, _, body = self.patch(url, 1000, self.data[1000:half], **{"Content-Digest": wrong})
        self.assertEqual((status, json.loads(body)["code"]), (422, "digest_mismatch"))
        self.assertEqual(self.head(url)[1]["Upload-Offset"], "1000")
        right = "sha-256=:" + base64.b64encode(hashlib.sha256(self.data[1000:half]).digest()).decode() + ":"
        self.assertEqual(self.patch(url, 1000, self.data[1000:half], **{"Content-Digest": right})[0], 204)
        status, _, body = self.patch(url, half, self.data[half:])
        self.assertEqual(status, 201, body)
        entry = json.loads(body)
        self.assertEqual((entry["size"], entry["sha256"], entry["profile"], entry["slot"], entry["platform"]),
                         (len(self.data), hashlib.sha256(self.data).hexdigest(), "Mila", "slot1", "switch"))
        self.assertEqual(entry["device"], "Mila's Switch")
        status, _, archive = self.call(f"{API}/saves/0100ABCD00010000/{entry['save_id']}")
        self.assertEqual((status, archive), (200, self.data))
        self.assertEqual(self.head(url)[0], 404)       # finished: gone

    def test_upload_refusals(self):
        self.assertEqual(self.call(f"{API}/saves/0100ABCD00010000/uploads", data={
            "schema": 1, "size": 10, "sha256": "0" * 64}, platform=None)[0], 400)
        self.assertEqual(self.call(f"{API}/saves/0100abcd00010000/uploads", data={
            "schema": 1, "size": 10, "sha256": "0" * 64})[0], 400)          # not a Switch title id
        self.assertEqual(self.call(f"{API}/saves/0100ABCD00010800/uploads", data={
            "schema": 1, "size": 10, "sha256": "0" * 64})[0], 400)          # an update's id, not the game's
        status, _, body = self.call(f"{API}/saves/0100ABCD00010000/uploads", data={
            "schema": 1, "size": ls.SAVE_SIZE + 1, "sha256": "0" * 64})
        self.assertEqual((status, json.loads(body)["code"]), (413, "too_large"))
        self.srv.server.saves.chunk = 1000
        up = self.open()
        status, _, body = self.patch(up["upload"], 0, self.data[:1001])
        self.assertEqual((status, json.loads(body)["code"]), (413, "too_large"))
        bad = self.open(sha256=hashlib.sha256(b"another").hexdigest())
        offset = 0
        while offset < len(self.data):
            status, _, body = self.patch(bad["upload"], offset, self.data[offset:offset + 1000])
            offset += 1000
        self.assertEqual((status, json.loads(body)["code"]), (422, "digest_mismatch"))
        self.assertEqual(self.head(bad["upload"])[0], 404)
        # Another account does not see an upload.
        ines = self.srv.pair("ines")
        status, _, _ = self.srv.request(up["upload"], token=ines, method="HEAD")
        self.assertEqual(status, 404)
        self.assertEqual(self.call(up["upload"], "DELETE")[0], 204)
        self.assertEqual(self.head(up["upload"])[0], 404)
        self.assertEqual(list((self.srv.root / ".lantern-saves" / "uploads").iterdir()), [])

    def post(self, data, digest=True, **headers):
        if digest is True:
            headers["Content-Digest"] = "sha-256=:" + base64.b64encode(hashlib.sha256(data).digest()).decode() + ":"
        elif digest:
            headers["Content-Digest"] = digest
        return self.call(f"{API}/saves/0100ABCD00010000", data=data, headers={"Content-Type": "application/zip",
                                                                              **headers})

    def test_one_request(self):
        status, _, body = self.post(self.data, digest=False)
        self.assertEqual((status, json.loads(body)["code"]), (400, "bad_request"))
        status, _, body = self.post(self.data, digest="sha-256=:" + base64.b64encode(b"\0" * 32).decode() + ":")
        self.assertEqual((status, json.loads(body)["code"]), (422, "digest_mismatch"))
        status, _, body = self.post(self.data, **{"Lantern-Profile": "L%C3%A9a", "Lantern-Save-Slot": "slot2",
                                                  "Lantern-Game-Version": "196608", "Lantern-Save-Kind": "device"})
        entry = json.loads(body)
        self.assertEqual((status, entry["profile"], entry["slot"], entry["game_version_code"], entry["kind"]),
                         (201, "Léa", "slot2", 196608, "device"))
        self.assertEqual(self.post(b"not a zip")[0], 400)
        self.srv.server.saves.body = 100
        self.assertEqual(self.post(self.data)[0], 413)

    def test_kept_per_title(self):
        self.srv.server.saves.kept = 2
        made = [json.loads(self.post(self.data)[2])["save_id"] for _ in range(3)]
        _, _, body = self.call(f"{API}/saves?title_id=0100ABCD00010000")
        self.assertEqual([s["save_id"] for s in json.loads(body)["saves"]], made[:0:-1])   # newest first, oldest dropped

    def test_index_follows_the_schema_rule(self):
        self.post(self.data)
        index = self.srv.root / ".lantern-saves" / "index.json"
        doc = json.loads(index.read_text())
        doc["x-example"] = {"kept": True}
        doc["saves"][0]["x-example"] = "kept too"
        index.write_text(json.dumps(doc))
        saves = ls.Saves(index.parent)
        self.assertTrue(saves.available)
        saves.add("mila", self._zip_file(), hashlib.sha256(self.data).hexdigest(), len(self.data),
                  {"platform": "switch", "title_id": "0100ABCD00010000"})
        written = json.loads(index.read_text())
        self.assertEqual(written["x-example"], {"kept": True})
        self.assertEqual(written["saves"][0]["x-example"], "kept too")
        # A newer index: the family is unavailable, and the file is never written over.
        newer = {"schema": 2, "saves": "elsewhere"}
        index.write_text(json.dumps(newer))
        self.srv.server.saves = ls.Saves(index.parent)
        _, _, hello = self.call(f"{API}/")
        self.assertEqual(json.loads(hello)["features"]["saves"], 0)
        self.assertEqual(self.call(f"{API}/saves")[0], 404)
        self.assertEqual(self.post(self.data)[0], 404)
        self.assertEqual(json.loads(index.read_text()), newer)

    def _zip_file(self):
        path = Path(self.srv.tmp.name) / "save.zip"
        path.write_bytes(self.data)
        return path


class StateFiles(unittest.TestCase):
    """Every file the server reads has a `schema`; a newer one is absent and never written over."""

    def test_homebrew_json(self):
        srv = Running()
        self.addCleanup(srv.close)
        self.assertEqual(srv.request(f"{API}/homebrew/org.example.future")[0], 404)
        self.assertEqual(srv.request(f"{API}/homebrew/local.future")[0], 404)     # nor under a local id
        future = srv.root / "homebrew" / "future" / "homebrew.json"
        self.assertEqual(json.loads(future.read_text())["schema"], 2)
        # Unknown keys in homebrew.json are ignored, not refused.
        status, _, body = srv.request(f"{API}/homebrew/{library.FROSTLINE}?platform=switch")
        self.assertEqual(status, 200)
        self.assertNotIn("x-example-shelf", json.loads(body))

    def test_library_json_and_state(self):
        srv = Running()
        self.addCleanup(srv.close)
        state = json.loads(srv.state.read_text())
        self.assertEqual(state["schema"], 1)
        self.assertIn("switch/0100ABCD00010000", state["titles"])
        newer = {"schema": 2, "apps": "elsewhere"}
        (srv.root / "library.json").write_text(json.dumps(newer))
        _, _, body = srv.request(f"{API}/apps?platform=android")
        self.assertEqual(json.loads(body)["items"], [])     # the Android app is known only from library.json
        self.assertEqual(json.loads((srv.root / "library.json").read_text()), newer)


class LinuxHomebrew(unittest.TestCase):
    """A Linux port (Annex A.6): a package per architecture, each signed, and its requirements (SPEC.md § 8.7)."""

    @classmethod
    def setUpClass(cls):
        cls.srv = Running()

    @classmethod
    def tearDownClass(cls):
        cls.srv.close()

    def entry(self, listing=False):
        path = f"{API}/homebrew?platform=linux" if listing else f"{API}/homebrew/{library.HARBOR}"
        status, _, body = self.srv.request(path, headers={"Lantern-Platform": "linux"})
        self.assertEqual(status, 200, body)
        return json.loads(body)["items"][0] if listing else json.loads(body)

    def test_port_for_arm_with_glibc(self):
        doc = self.entry()
        self.assertEqual((doc["platform"], doc["kind"], doc["package"]["format"]), ("linux", "port", "zip"))
        self.assertEqual(doc["package"]["arch"], ["aarch64", "armhf"])
        self.assertEqual(doc["requires"]["min"]["glibc"], "2.30")
        self.assertEqual(doc["genres"], ["adventure", "simulation"])
        self.assertNotIn("system_id", doc)
        self.assertEqual(client.port_problems(doc), [])
        self.assertEqual(client.requires_problems(doc), [])
        plan = client.install_plan(doc)
        self.assertEqual(plan, {"free": [f"/{library.HARBOR}/harbor.aarch64", f"/{library.HARBOR}/harbor.armhf"],
                                "consent": ["/Harbor Lights.sh"]})

    def test_packages_per_arch(self):
        doc = self.entry()
        self.assertEqual([p["arch"] for p in doc["packages"]], [["x86_64"], ["riscv64"]])
        for package in [doc["package"], *doc["packages"]]:
            self.assertEqual(client.manifest_sha256(package["manifest"]), package["manifest_sha256"])
            status, _, data = self.srv.request(package["file"])
            self.assertEqual((status, hashlib.sha256(data).hexdigest()), (200, package["sha256"]))
        self.assertTrue(client.verify_signature(doc))
        for extra in doc["packages"]:
            self.assertEqual(extra["signature"]["public_key"], doc["signature"]["public_key"])
            self.assertTrue(client.verify_signature({**doc, "package": extra, "signature": extra["signature"]}))
        self.assertEqual(client.pick_package(doc, "armhf")["arch"], ["aarch64", "armhf"])
        self.assertEqual(client.pick_package(doc, "riscv64")["arch"], ["riscv64"])
        self.assertIsNone(client.pick_package(doc, "x86"))
        self.assertIsNone(client.pick_package(doc, "loongarch64"))     # an arch it does not know is never its own
        listed = self.entry(listing=True)
        self.assertNotIn("manifest", listed["package"])
        self.assertFalse(any("manifest" in p for p in listed["packages"]))
        self.assertEqual([p["sha256"] for p in listed["packages"]], [p["sha256"] for p in doc["packages"]])

    def test_unknown_requires_served_untouched(self):
        requires = self.entry()["requires"]
        self.assertEqual(requires, library.HARBOR_REQUIRES)
        self.assertEqual((requires["vram_mb"], requires["min"]["kernel"]), (256, "5.10"))

    def test_packages_refused(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "library"
        cases = {
            "unsigned-second": lambda m: m["packages"][1].pop("signature"),
            "another-key": lambda m: m["packages"][1].update(signature=library.signature(
                library.INES_KEY, library.zip_message(library.HARBOR, "linux", 20100, library.HARBOR_ZIPS["x86_64"]))),
            "no-arch": lambda m: m["packages"][1].pop("arch"),
            "missing-file": lambda m: m["packages"][1].update(file="nowhere.zip"),
            "twice": lambda m: m["packages"][1].update(file=m["packages"][0]["file"]),
            "glibc-text": lambda m: m["requires"]["min"].update(glibc="new enough"),
            "screen-star": lambda m: m["requires"]["min"].update(screen="640*480"),
            "ram-text": lambda m: m["requires"]["min"].update(ram_mb="1 GiB"),
            "gpu-metal": lambda m: m["requires"].update(gpu=["metal"]),
            "genre": lambda m: m.update(genres=["roguelite"]),
        }
        for name, change in cases.items():
            folder = root / "homebrew" / name
            folder.mkdir(parents=True)
            for arch, data in library.HARBOR_ZIPS.items():
                (folder / f"harbor-{arch}.zip").write_bytes(data)
            meta = json.loads(json.dumps(library.HARBOR_META))
            meta["id"] = library.HARBOR + "-" + name
            change(meta)
            (folder / "homebrew.json").write_text(json.dumps(meta))
        served = ls.Library(root, Path(tmp.name) / "state.json").homebrew
        self.assertEqual(served, {})

    def test_links_refused(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name) / "library" / "homebrew" / "link"
        folder.mkdir(parents=True)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            info = zipfile.ZipInfo("org.example.linky/data")
            info.external_attr = 0o120777 << 16     # a symbolic link
            z.writestr(info, "/etc")
        (folder / "l.zip").write_bytes(out.getvalue())
        (folder / "homebrew.json").write_text(json.dumps({"schema": 1, "id": "org.example.linky", "platform": "linux",
                                                          "build": 1}))
        self.assertEqual(ls.Library(Path(tmp.name) / "library", Path(tmp.name) / "s.json").homebrew, {})

    def test_category_is_not_served(self):
        for hid in (library.FROSTLINE,):
            status, _, body = self.srv.request(f"{API}/homebrew/{hid}?platform=switch")
            self.assertNotIn("category", json.loads(body))
        status, _, _ = self.srv.request(f"{API}/homebrew/org.example.ember-rogue?platform=switch")
        self.assertEqual(status, 404)                                   # a genre not of the list
        status, _, _ = self.srv.request(f"{API}/homebrew/org.example.moss-metal?platform=switch")
        self.assertEqual(status, 404)                                   # a gpu not of the list


class Requirements(unittest.TestCase):
    """What a client decides from requires (SPEC.md § 8.7): offer, offer with a warning, or refuse."""

    HANDHELD: ClassVar[dict] = {"glibc": "2.31", "ram_mb": 1024, "screen": "640x480", "gpu": ["gles2"]}

    def decide(self, requires, device=None):
        return client.offer({"requires": {"text": "…", **requires}}, self.HANDHELD if device is None else device)

    def test_offer(self):
        self.assertEqual(client.offer({}, {}), ("offer", []))
        self.assertEqual(self.decide({"min": {"glibc": "2.30", "ram_mb": 512, "screen": "640x480"},
                                      "gpu": ["gles2", "vulkan"]}), ("offer", []))
        self.assertEqual(self.decide({"min": {"glibc": "2.31.0"}}), ("offer", []))     # missing parts are 0
        self.assertEqual(self.decide({"x-example-badge": "gold"}), ("offer", []))      # a vendor's: ignored
        self.assertEqual(self.decide({"homebrew": [{"id": "org.example.runtime", "min_build": 1}]}), ("offer", []))

    def test_refuse(self):
        for requires, why in (({"min": {"glibc": "2.35"}}, "glibc"),
                              ({"min": {"glibc": "2.4"}}, None),          # 2.4 is below 2.31: offered
                              ({"min": {"ram_mb": 2048}}, "ram_mb"),
                              ({"min": {"screen": "1280x720"}}, "screen"),
                              ({"min": {"screen": "480x640"}}, "screen"),  # each side counts
                              ({"gpu": ["vulkan", "gl"]}, "gpu")):
            decision, reasons = self.decide(requires)
            if why is None:
                self.assertEqual(decision, "offer", requires)
                continue
            self.assertEqual(decision, "refuse", requires)
            self.assertTrue(reasons[0].startswith(why), reasons)
        decision, reasons = self.decide({"min": {"glibc": "2.35", "kernel": "5.10"}})
        self.assertEqual((decision, len(reasons)), ("refuse", 1))      # a refusal wins over a warning

    def test_warn(self):
        for requires, device in (({"min": {"kernel": "5.10"}}, None),            # a key it does not know
                                 ({"vram_mb": 256}, None),                         # nor this one
                                 ({"gpu": ["metal"]}, None),                       # a name it does not know
                                 ({"gpu": ["vulkan", "metal"]}, None),             # a known one fails, the other unknown
                                 ({"min": {"glibc": "2.30"}}, {"gpu": ["gles2"]}),  # its glibc is unknown
                                 ({"gpu": ["gles2"]}, {"glibc": "2.31"}),          # its graphics are unknown
                                 ({"min": {"screen": "640 by 480"}}, None),        # a value of another form
                                 ({"min": {"ram_mb": 512}}, {})):
            decision, reasons = self.decide(requires, device)
            self.assertEqual(decision, "warn", (requires, device))
            self.assertTrue(reasons)
        self.assertEqual(client.offer(library.HARBOR_META, self.HANDHELD)[0], "warn")    # kernel and vram_mb
        self.assertEqual(client.offer(library.HARBOR_META, {**self.HANDHELD, "glibc": "2.28"})[0], "refuse")

    def test_shapes(self):
        self.assertEqual(client.requires_problems({"requires": library.HARBOR_REQUIRES}), [])
        for requires in ({"min": {}}, {"text": "x", "min": {"ram_mb": "1"}}, {"text": "x", "min": {"screen": "640"}},
                         {"text": "x", "min": {"glibc": "2.x"}}, {"text": "x", "gpu": "gles2"}, {"text": "x", "gpu": []}):
            self.assertTrue(client.requires_problems({"requires": requires}), requires)


class CheatWriting(unittest.TestCase):
    """POST, PUT and DELETE of cheat sets, with cheats.write (SPEC.md § 10)."""

    SET: ClassVar[dict] = {"schema": 1, "platform": "switch", "title_id": "0100ABCD00010000", "build_id": "4A1B2C3D4E5F6071",
                           "source": "Lea's notes", "note": "Lamp oil", "text": "[Endless lamp oil]\n04000000 0123A4B0 00000063\n"}

    def setUp(self):
        self.srv = Running(USERS)
        self.addCleanup(self.srv.close)
        self.token = self.srv.pair("mila", EVERY_SCOPE)

    def call(self, path, method="GET", data=None, token=None):
        status, headers, body = self.srv.request(f"{API}{path}", token=token or self.token, method=method, data=data)
        return status, (json.loads(body) if body and headers.get("Content-Type", "").endswith("json") else body)

    def test_cycle(self):
        status, doc = self.call("/cheats", "POST", self.SET)
        self.assertEqual(status, 201, doc)
        self.assertEqual((doc["source"], doc["note"], doc["size"]), ("Lea's notes", "Lamp oil", len(self.SET["text"])))
        stored = self.srv.root / "cheats/switch/0100ABCD00010000/4A1B2C3D4E5F6071/Lea's_notes.txt"
        self.assertEqual(stored.read_text(), self.SET["text"])
        index = json.loads((self.srv.root / "cheats/index.json").read_text())
        self.assertEqual(index, {"schema": 1, "notes": {
            "switch/0100ABCD00010000/4A1B2C3D4E5F6071/Lea's_notes.txt": "Lamp oil"}})
        _, listed = self.call("/cheats?title_id=0100ABCD00010000&build_id=4A1B2C3D4E5F6071")
        self.assertEqual([s["source"] for s in listed["cheats"]], ["Community list", "Lea's notes", "Noor"])
        self.assertEqual(self.call("/cheats", "POST", self.SET)[0], 409)          # the same set again
        new = {**self.SET, "text": self.SET["text"] + "[Thin ice]\n04000000 0123A4C8 00000001\n", "note": None}
        status, _ = self.call(f"/cheats/{doc['id']}", "PUT", new)
        self.assertEqual(status, 204)
        status, text = self.call(f"/cheats/{doc['id']}")
        self.assertEqual(text.decode(), new["text"])
        self.assertEqual(json.loads((self.srv.root / "cheats/index.json").read_text())["notes"], {})
        status, problem = self.call(f"/cheats/{doc['id']}", "PUT", {**new, "source": "Someone else"})
        self.assertEqual((status, problem["code"]), (400, "bad_request"))         # a PUT does not move a set
        self.assertEqual(self.call(f"/cheats/{doc['id']}", "DELETE")[0], 204)
        self.assertFalse(stored.exists())
        self.assertFalse((self.srv.root / "cheats/switch").exists())              # its empty folders go too
        self.assertEqual(self.call(f"/cheats/{doc['id']}")[0], 404)
        self.assertEqual(self.call(f"/cheats/{doc['id']}", "DELETE")[0], 404)

    def test_refusals(self):
        for change, status in (({"text": "not a cheat"}, 400),
                               ({"text": "[x]\n04000000 0123\n"}, 400),
                               ({"text": "[x]\x00\n"}, 400),
                               ({"text": "[x]\n" + "04000000 0123A4B0 00000063\n" * 40000}, 413),
                               ({"title_id": "0100ABCD00010800"}, 400),        # an update's id, not a title's
                               ({"build_id": None}, 400),
                               ({"source": "../escape"}, 400),
                               ({"source": "under_score"}, 400),
                               ({"note": "x" * 121}, 400),
                               ({"platform": "android", "title_id": "org.example.frostlinetales"}, 400),
                               ({"schema": 2}, 422)):
            body = {k: v for k, v in {**self.SET, **change}.items() if v is not None}
            got, problem = self.call("/cheats", "POST", body)
            self.assertEqual(got, status, (change, problem))
        lea = self.srv.pair("lea")
        self.assertEqual(self.call("/cheats", "POST", self.SET, token=lea)[0], 403)
        self.assertFalse((self.srv.root / "cheats/switch").exists())

    def test_newer_index_is_never_written(self):
        index = self.srv.root / "cheats/index.json"
        index.write_text(json.dumps({"schema": 2, "notes": "elsewhere"}))
        status, problem = self.call("/cheats", "POST", self.SET)
        self.assertEqual((status, problem["code"]), (503, "unavailable"))
        self.assertEqual(json.loads(index.read_text()), {"schema": 2, "notes": "elsewhere"})
        index.write_text(json.dumps({"schema": 1, "x-example": "kept"}))
        self.assertEqual(self.call("/cheats", "POST", self.SET)[0], 201)
        self.assertEqual(json.loads(index.read_text())["x-example"], "kept")


class Requests(unittest.TestCase):
    """Requests for a game (SPEC.md § 11), each account's, kept in the state file."""

    def setUp(self):
        self.srv = Running(USERS)
        self.addCleanup(self.srv.close)
        self.token = self.srv.pair("mila", EVERY_SCOPE)

    def call(self, method="GET", data=None, token=None, platform=None, query=""):
        status, _, body = self.srv.request(f"{API}/requests{query}", token=token or self.token, method=method,
                                           data=data, headers={"Lantern-Platform": platform} if platform else {})
        return status, json.loads(body)

    def test_create_list_and_keep(self):
        status, first = self.call("POST", {"schema": 1, "platform": "switch", "title_id": "0100EFEF00020000"})
        self.assertEqual(status, 201, first)
        self.assertEqual((first["status"], first["name"]), ("open", "Moss & Ember"))     # named from the library
        status, again = self.call("POST", {"schema": 1, "title_id": "0100EFEF00020000"}, platform="switch")
        self.assertEqual((status, again["id"]), (200, first["id"]))
        status, other = self.call("POST", {"schema": 1, "title_id": "org.example.harborlights"}, platform="android")
        self.assertEqual(status, 201)
        self.assertNotIn("name", other)
        _, every = self.call()
        self.assertEqual({r["id"] for r in every["requests"]}, {first["id"], other["id"]})
        _, phone = self.call(platform="android")
        self.assertEqual([r["id"] for r in phone["requests"]], [other["id"]])
        state = json.loads(self.srv.state.read_text())
        self.assertEqual(state["schema"], 1)
        self.assertEqual({r["user"] for r in state["requests"]}, {"mila"})
        later = ls.Library(self.srv.root, self.srv.state)                 # kept across a restart
        self.assertEqual(len(later.requests()), 2)

    def test_each_account_its_own(self):
        users = json.loads(json.dumps(USERS))
        users["users"].append({"name": "lea2", "password": users["users"][0]["password"],
                               "scopes": ["library", "requests"], "state": "active"})
        srv = Running(users)
        self.addCleanup(srv.close)
        mila = srv.pair("mila", EVERY_SCOPE)
        other = srv.pair("lea2", {"schema": 1, "device": "Lea's phone", "scopes": ["library", "requests"]})
        body = {"schema": 1, "platform": "switch", "title_id": "0100EFEF00020000"}
        first = json.loads(srv.request(f"{API}/requests", token=mila, data=body)[2])
        status, _, mine = srv.request(f"{API}/requests", token=other, data=body)
        self.assertEqual(status, 201)                                     # not mila's request
        self.assertNotEqual(json.loads(mine)["id"], first["id"])
        listed = json.loads(srv.request(f"{API}/requests", token=other)[2])["requests"]
        self.assertEqual([r["id"] for r in listed], [json.loads(mine)["id"]])
        self.assertEqual(self.call(token=self.srv.pair("lea"))[0], 403)  # lea's account lacks the scope

    def test_refusals(self):
        for body, platform, status in (({"schema": 1, "title_id": "0100EFEF00020000"}, None, 400),   # no platform
                                       ({"schema": 1, "platform": "switch", "title_id": "0100EFEF00020800"}, None, 400),
                                       ({"schema": 1, "platform": "Switch", "title_id": "0100EFEF00020000"}, None, 400),
                                       ({"schema": 1, "platform": "3ds", "title_id": "0004000E00ABCD00"}, None, 400),
                                       ({"schema": 2, "platform": "switch", "title_id": "0100EFEF00020000"}, None, 422)):
            got, problem = self.call("POST", body, platform=platform)
            self.assertEqual(got, status, (body, problem))
        self.assertEqual(json.loads(self.srv.state.read_text()).get("requests", []), [])


if __name__ == "__main__":
    unittest.main()
