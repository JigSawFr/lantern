#!/usr/bin/env python3
"""A small fuzz harness for the reference server's parsers: seeded and
deterministic, standard library only.

    python3 tests/fuzz.py [--iterations 100000] [--seed 7] [--target NAME]

Each target feeds one parser of server/ inputs made from a few valid ones,
mutated (bytes flipped, inserted, removed, repeated, cut; brackets nested
deep; huge numbers; control characters), and checks its contract: it gives
an answer or refuses with what SPEC.md says (a Problem, a signature's
refusal, None), and never fails otherwise. The tests (tests/test_v04.py) run
every target a few hundred times with a fixed seed; a longer run, by hand or
in a nightly job, takes more iterations and another seed. A failure prints
the target, the seed, the iteration and the input, which replays it.

Targets: request documents (JSON input, its bounds), manifests (a zip's),
.nro files (NACP), homebrew.json's port and requirements, rating caps,
signature headers (RFC 9421), Content-Digest, Range, Accept-Language and
Accept-Encoding, LAN discovery datagrams (a server's and a peer's), grants,
sync's times and merge rule, Lantern-Save-Encryption and an encrypted
backup's header, and multicast DNS queries. Lantern has no multipart body:
nothing of the kind to fuzz.
"""
import argparse
import base64
import io
import json
import random
import struct
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from server import ed25519, mdns, nro, peer, signatures
from server import lantern_server as ls

ls.log = lambda msg: None


def mutate(rng, data, rounds=None):
    """`data` (bytes) changed a few times, as a fuzzer would."""
    data = bytearray(data)
    for _ in range(rounds or rng.randint(1, 6)):
        op = rng.randrange(9)
        at = rng.randrange(len(data) + 1)
        if op == 0 and data:
            data[min(at, len(data) - 1)] ^= 1 << rng.randrange(8)
        elif op == 1:
            data[at:at] = bytes([rng.randrange(256)])
        elif op == 2 and data:
            del data[at:at + rng.randint(1, 16)]
        elif op == 3 and data:
            chunk = data[at:at + rng.randint(1, 32)]
            data[at:at] = chunk * rng.randint(1, 50)
        elif op == 4:
            data = data[:at]
        elif op == 5:
            depth = rng.choice((8, 17, 100, 5000))
            data[at:at] = b"[" * depth + b"]" * depth
        elif op == 6:
            data[at:at] = rng.choice((b"1e999999", b"-0", b"18446744073709551616", b"\x00", b"\xff\xfe", b"\"\\u0000\"",
                                      b"NaN", b"\\", b"\"" * 3, "é\u202e".encode()))
        elif op == 7 and data:
            data[at:] = bytes(rng.randrange(256) for _ in range(rng.randint(0, 64)))
        else:
            data += data[:rng.randint(0, 64)]
    return bytes(data)


def text(rng, s):
    return mutate(rng, s.encode()).decode("utf-8", "replace")


# The targets: each takes (rng) and raises AssertionError on a broken contract.

DOCS = [b'{"schema":1,"installed":[{"app_id":"0100ABCD00010000","version_code":0}],"want":["update","dlc"]}',
        b'{"schema":1,"device":"Lea\'s Switch","scopes":["library"],"key":{"alg":"ed25519","public_key":"' + b"A" * 43
        + b'="}}', b'{"schema":2}', b'[]', b'{"schema":1,"name":"sam","scopes":["library"]}']


def t_document(rng):
    body = mutate(rng, rng.choice(DOCS))
    try:
        doc = ls.read_document(body, rng.choice(("application/json", "application/json; charset=utf-8", "text/plain")))
    except ls.Problem as p:
        assert p.status in (400, 422), p.status
        return
    assert isinstance(doc, dict) and doc["schema"] == 1 and not ls.too_deep(doc)


def zip_bytes(files):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return out.getvalue()


ZIPS = [zip_bytes({"switch/org.example.a/a.nro": b"x" * 100, "config/org.example.a/a.ini": b"[a]\n"}),
        zip_bytes({"../escape": b"x"}), zip_bytes({"a/" + "b" * 300: b"x"})]


class Manifests:
    """A Library to read zips with, in a folder of its own."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / "lib"
        root.mkdir()
        self.lib = ls.Library(root, Path(self.tmp.name) / "state.json")
        self.path = root / "f.zip"
        self.n = 0


MANIFESTS = None


def t_manifest(rng):
    global MANIFESTS
    if MANIFESTS is None:
        MANIFESTS = Manifests()
    MANIFESTS.n += 1
    data = mutate(rng, rng.choice(ZIPS), rng.randint(1, 3))
    MANIFESTS.path.write_bytes(data)
    st = MANIFESTS.path.stat()
    manifest = MANIFESTS.lib.zip_manifest(MANIFESTS.path, f"f{MANIFESTS.n}.zip", st)
    if manifest is not None:
        assert all(ls.device_path_ok(m["path"]) for m in manifest)
        assert len({m["path"].casefold() for m in manifest}) == len(manifest)


NROS = None


def t_nro(rng):
    global NROS
    if NROS is None:
        import library
        NROS = [library.nro("Frostline", "Noor", "1.4.0"), library.PAPERLAMP_NRO]
    data = mutate(rng, rng.choice(NROS))
    info = nro.read_nro(io.BytesIO(data), len(data))
    assert info is None or isinstance(info, dict)


PORT = {"original": {"name": "Frostline Tales", "stores": [{"store": "gog", "url": "https://store.example.org/x"}]},
        "engine": {"name": "Lanternlight"}, "data_root": "/switch/frostline/", "assets": "user_owned",
        "requires_data": [{"path": "data/frost.pak", "accept": [{"label": "1.0", "sha256": "a" * 64}], "hint": "Here."},
                          {"one_of": [[{"path": "m/a.pak", "hint": "A."}], [{"path": "m/b.pak", "hint": "B."}]]}]}
REQUIRES = {"text": "glibc 2.30", "min": {"glibc": "2.30", "ram_mb": 512, "screen": "640x480"}, "gpu": ["gles2"]}


def json_mutant(rng, doc):
    """A JSON value of `doc` mutated: valid JSON when the bytes still parse, else skipped."""
    for _ in range(10):
        try:
            return json.loads(mutate(rng, json.dumps(doc).encode()).decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            continue
    return doc


def t_homebrew_json(rng):
    port = json_mutant(rng, PORT)
    problem = ls.port_problem(port, ("/switch/", "/config/"))
    assert problem is None or isinstance(problem, str)
    if problem is None:
        assert ls.device_path_ok(port["data_root"][:-1])
    tmp = Path(tempfile.gettempdir())
    lib = ls.Library.__new__(ls.Library)     # homebrew_requires needs only skip()
    lib.skipped, lib.root = set(), tmp
    out = ls.Library.homebrew_requires(lib, json_mutant(rng, REQUIRES), "x")
    assert out is None or out is False or isinstance(out, dict)


def t_rating_cap(rng):
    cap = json_mutant(rng, rng.choice(({"age": 12}, {"system": "PEGI", "rating": "12", "unrated": "hide"})))
    problem = ls.rating_cap_problem(cap)
    if problem is None:
        ratings = json_mutant(rng, [{"system": "ESRB", "rating": "T"}, {"system": "PEGI", "rating": "16"}])
        if isinstance(ratings, list):
            assert ls.above_cap([r for r in ratings if isinstance(r, dict)], cap) in (True, False)


SEED = bytes(range(32))


class Headers(dict):
    def get(self, name, default=None):
        return next((v for k, v in self.items() if k.lower() == name.lower()), default)


def t_signature(rng):
    import lantern_client as client
    uri = "https://shelf.example.org/api/lantern/v1/apps?page_size=1"
    signed = client.sign(SEED, "GET", uri, "Bearer et_x", b"", created=1793345400, nonce="tQ0Vb3Yt7sXx2c1mZ8kq4A")
    headers = Headers({"Authorization": "Bearer et_x", **signed})
    key = rng.choice(("Signature-Input", "Signature", "Authorization"))
    headers[key] = text(rng, headers[key])
    try:
        signatures.check("GET", uri, headers, client.ed25519_public(SEED), True, 0, signatures.Nonces(),
                         now=1793345400)
    except signatures.Refused as e:
        assert e.code in ("signature_required", "signature_invalid", "signature_expired", "signature_replayed")


def t_headers(rng):
    try:
        digest = ls.content_digest(text(rng, "sha-256=:" + base64.b64encode(b"x" * 32).decode() + ":"))
        assert digest is None or len(digest) == 32
    except ls.Problem as p:
        assert p.status == 400
    size = rng.choice((0, 1, 1000, 1 << 40))
    rng_header = ls.parse_range(text(rng, "bytes=0-99"), size)
    assert rng_header in (None, "unsatisfiable") or (0 <= rng_header[0] <= rng_header[1] < size)
    assert isinstance(ls.languages(text(rng, "fr-CA, fr;q=0.9, en;q=0.5")), list)
    assert ls.accepted_coding(text(rng, "zstd, br;q=0.5, gzip")) in (None, "gzip", "zstd")
    assert ls.nesting(mutate(rng, b'{"a":[1,{"b":"]"}]}')) >= 0


class Server:
    uid, name = "6f1c2a8e-4b7d-4e2a-9c31-8d5e2f0a7b14", "Fuzz"

    class library:
        uid = "6f1c2a8e-4b7d-4e2a-9c31-8d5e2f0a7b14"


def t_datagram(rng):
    data = mutate(rng, b'{"schema":1,"lantern":"discover"}')
    limiter = ls.Limiter(10 ** 9, 1.0)
    reply = ls.discovery_reply(Server, 443, data, "192.0.2.10", limiter)
    assert reply is None or len(reply) <= ls.DATAGRAM_LIMIT


GRANT = {}


def t_grant(rng):
    if not GRANT:
        GRANT["key"] = ed25519.public_key(SEED)
        GRANT["grant"] = ls.make_grant(SEED, Server.uid, "0" * 64, 10, 4102444800)
    doc = ls.read_grant(text(rng, GRANT["grant"]), {Server.uid: GRANT["key"]}, now=0)
    assert doc is None or (doc["uid"] == Server.uid and isinstance(doc["sha256"], str))


def t_sync(rng):
    from datetime import datetime, timezone
    now = datetime(2026, 10, 30, 9, 30, tzinfo=timezone.utc)
    kept = ls.sync_time(text(rng, "2026-10-30T09:12:03.250Z"), now, 300)
    assert kept is None or ls.UPDATED.match(kept)
    have = {"value": json_mutant(rng, {"platform": "switch", "title_id": "0100ABCD00010000", "note": "Lea"}),
            "updated": "2026-10-30T09:12:03.250Z"}
    sent = {"value": json_mutant(rng, {"platform": "switch", "title_id": "0100ABCD00010000"}),
            "updated": kept or "2026-10-30T09:12:03.250Z"}
    if rng.random() < 0.3:
        sent = {"deleted": True, "updated": sent["updated"]}
    assert ls.sync_wins(sent, have) in (True, False)


def t_encryption(rng):
    try:
        enc = ls.encryption_header(text(rng, "lantern-save-e2e-1; key_id=0a1b2c3d4e5f6071"))
        assert enc["scheme"] == ls.E2E_SCHEME and ls.KEY_ID.match(enc["key_id"])
        ls.archive_check(mutate(rng, ls.E2E_MAGIC + bytes.fromhex("0a1b2c3d4e5f6071")), None, enc)
    except ls.Problem as p:
        assert p.status == 400


MDNS = {}


def t_mdns(rng):
    if not MDNS:
        MDNS["r"] = mdns.Responder("_lantern._tcp", "Fuzz", 443, {"uid": Server.uid}, "lantern-fuzz", "192.0.2.10", 0,
                                   "127.0.0.1")
    query = struct.pack("!HHHHHH", 7, 0, 1, 0, 0, 0) + mdns.encode_name("_lantern._tcp.local") + struct.pack("!HH", 12, 1)
    data = mutate(rng, query)
    try:
        mdns.questions(data)
    except ValueError:
        pass
    out = MDNS["r"].reply(data, ("192.0.2.20", rng.choice((5353, 40000))))
    assert out is None or (isinstance(out[0], bytes) and len(out[0]) < 9000)


def t_peer_datagram(rng):
    p = peer.Peer.__new__(peer.Peer)
    p.uid, p.name, p.base, p.tls, p.slots, p.keys = Server.uid, "Fuzz", "/lantern", False, 2, {Server.uid: b"k" * 32}
    p.server_address = ("127.0.0.1", 47116)
    data = mutate(rng, b'{"schema":1,"lantern":"discover","peers":true}')
    reply = p.reply(data, "192.168.1.20", ls.Limiter(10 ** 9, 1.0))
    assert reply is None or (len(reply) <= ls.DATAGRAM_LIMIT and json.loads(reply)["lantern"] == "peer")


TARGETS = {"document": t_document, "manifest": t_manifest, "nro": t_nro, "homebrew-json": t_homebrew_json,
           "rating-cap": t_rating_cap, "signature": t_signature, "headers": t_headers, "datagram": t_datagram,
           "grant": t_grant, "sync": t_sync, "encryption": t_encryption, "mdns": t_mdns, "peer-datagram": t_peer_datagram}


def run(target, iterations, seed):
    """Runs one target; returns the number of iterations, or raises with what replays a failure."""
    fn = TARGETS[target]
    for i in range(iterations):
        rng = random.Random(f"{seed}:{target}:{i}")
        try:
            fn(rng)
        except Exception as e:
            # every failure is reported with what replays it
            raise AssertionError(f"fuzz {target}, seed {seed}, iteration {i}: {type(e).__name__}: {e}") from e
    return iterations


def main(argv=None):
    p = argparse.ArgumentParser(description="Fuzz the reference server's parsers, deterministically.")
    p.add_argument("--iterations", type=int, default=2000)
    p.add_argument("--seed", default="lantern")
    p.add_argument("--target", choices=sorted(TARGETS), action="append")
    args = p.parse_args(argv)
    sys.path.insert(0, str(ROOT / "conformance"))
    for target in args.target or sorted(TARGETS):
        began = time.monotonic()
        n = run(target, args.iterations, args.seed)
        print(f"fuzz {target}: {n} inputs, nothing broken ({time.monotonic() - began:.1f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
