#!/usr/bin/env python3
"""Writes Lantern's test vectors (vectors/*.json), for client and server
libraries: the bytes SPEC.md spells out, case by case, with what a reader
decides.

    python3 tools/make_vectors.py           # writes vectors/
    python3 tools/make_vectors.py --check   # fails when vectors/ differs

- signatures.json: signed requests (SPEC.md § 5.4, RFC 9421): a test key,
  each request's signature base, Signature-Input and Signature, then
  requests a server refuses, with their code;
- homebrew-signatures.json: manifests' canonical bytes and digests
  (§ 8.2), and the bytes an author signs, with their signatures (§ 8.4);
- spki.json: certificates and their SPKI fingerprints, whole and short
  (§ 5.3);
- paths.json: device paths accepted and refused (§ 8.2);
- version-codes.json: version_code and version_name per profile (Annex A);
- requires.json: requirements and devices, and whether a client offers the
  package, warns or refuses (§ 8.7);
- rating-caps.json: ratings and caps, and whether a server hides (§ 5.6);
- ed25519-refused.json: Ed25519 signatures a verifier refuses whatever the
  equation says (§ 8.4, § 5.4): keys and R of small order (each pair of the
  8, with S = 0, which the cofactorless equation accepts for about one
  message in 8), encodings that are not canonical, S >= L;
- encrypted-saves.json: end-to-end encrypted backups (§ 9.4): HKDF,
  HChaCha20 and XChaCha20-Poly1305 cases, save keys with their id, phrase
  and QR text, backups whole, and those a reader refuses;
- grants.json: grants (§ 19.3), and what a peer decides of each (§ 19.4);
- sync-merge.json: sync's merge rule (§ 20.4), item by item;
- static-layout.json: each read route's file in a static library, and the
  paths a document may point at (§ 21.1).

Everything is computed by the reference (conformance/lantern_client.py and
server/), deterministically: the keys are RFC 8032's first test key and
seeds made of fixed bytes, the times and nonces fixed. The certificates of
spki.json were made once with openssl and are kept as they are; only their
fingerprints are computed again. tests/test_v04.py checks the vectors
against the reference, both ways. Standard library only.
"""
import base64
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "conformance"))
import lantern_client as client
import lantern_e2e as e2e

from server import ed25519 as server_ed25519
from server import lantern_server as ls
from server import static

OUT = ROOT / "vectors"
SEED = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")    # RFC 8032 § 7.1, test 1
AUTHOR = bytes(range(32))       # a homebrew author's fictional key
CREATED = 1793345400            # 2026-10-30T09:30:00Z
TOKEN = "et_c8V1nQ0xYbExampleVectorToken0000000000"
SKEW = 300                      # auth.skew, SPEC.md § 5.4
ABOUT = "Lantern test vectors (https://lantern.boreale.dev/spec/). Fictional keys, tokens and names; MIT."


def b64(raw):
    return base64.b64encode(raw).decode()


def doc(name, description, **body):
    return {"schema": 1, "about": ABOUT, "vectors": name, "description": description, **body}


def signed(method, uri, authorization, body, nonce, created=CREATED, seed=SEED):
    digest = client.content_digest(body) if body else None
    base, params = client.signature_base(method, uri, authorization, digest, created, nonce,
                                         client.key_thumbprint(client.ed25519_public(seed)))
    headers = {}
    if authorization is not None:
        headers["Authorization"] = authorization
    if digest:
        headers["Content-Digest"] = digest
    headers["Signature-Input"] = "lantern=" + params
    headers["Signature"] = "lantern=:" + b64(client.ed25519_sign(seed, base.encode())) + ":"
    return {"method": method, "uri": uri, "body": body.decode() if body else "", "headers": headers,
            "signature_base": base}


def signature_vectors():
    public = client.ed25519_public(SEED)
    bearer = "Bearer " + TOKEN
    body = json.dumps({"schema": 1, "installed": [{"app_id": "0100ABCD00010000", "version_code": 0}],
                       "want": ["update", "dlc"]}, separators=(",", ":")).encode()
    accepted = [
        {"name": "GET without a body", **signed("GET", "https://shelf.example.org/api/lantern/v1/apps?page_size=50",
                                                bearer, b"", "tQ0Vb3Yt7sXx2c1mZ8kq4A")},
        {"name": "POST with a JSON body: content-digest covered",
         **signed("POST", "https://shelf.example.org/api/lantern/v1/apps/missing?platform=switch", bearer, body,
                  "Wm9nZ2xlLWZyb3N0bGluZQ")},
        {"name": "A port other than the scheme's, and a query percent-encoded as sent",
         **signed("GET", "https://192.0.2.10:8443/api/lantern/v1/apps?q=Moss%20%26%20Ember&page_size=10", bearer,
                  b"", "bW9zcy1hbmQtZW1iZXItMDE")},
        {"name": "A DELETE without a body",
         **signed("DELETE", "https://shelf.example.org/api/lantern/v1/requests/r_Hk3", bearer, b"",
                  "ZGVsZXRlLXRoZS1yZXF1ZXN0")},
        {"name": "Polling a pairing made with a key: no authorization",
         **signed("GET", "https://shelf.example.org/api/lantern/v1/pairing/p_4Fh2Lm9Q", None, b"",
                  "cG9sbGluZy10aGUtcGFpcmluZw")},
    ]
    first = accepted[0]
    tampered = dict(first, method="DELETE")
    old = signed("GET", "https://shelf.example.org/api/lantern/v1/apps?page_size=50", bearer, b"",
                 "b2xkLXNpZ25hdHVyZS0wMDAx", created=CREATED - 301)
    reordered = {**first, "headers": {**first["headers"],
                                      "Signature-Input": 'lantern=("@target-uri" "@method" "authorization");'
                                                         f'created={CREATED};nonce="cmVvcmRlcmVkLWlucHV0LTAx";'
                                                         f'keyid="{client.key_thumbprint(public)}";alg="ed25519"'}}
    other_key = signed("GET", first["uri"], bearer, b"", "b3RoZXIta2V5LXNpZ25lZA", seed=bytes(32))
    without = {**first, "headers": {"Authorization": bearer}}
    no_digest = {**accepted[1], "headers": {k: v for k, v in accepted[1]["headers"].items() if k != "Content-Digest"}}
    refused = [
        {"name": "No signature", "request": without, "code": "signature_required"},
        {"name": "Another method than the one signed", "request": tampered, "code": "signature_invalid"},
        {"name": "Components in another order", "request": reordered, "code": "signature_invalid"},
        {"name": "Signed by another key (keyid is not the token's)", "request": other_key, "code": "signature_invalid"},
        {"name": "A body without its Content-Digest", "request": no_digest, "code": "signature_invalid"},
        {"name": "created 301 s before the server's clock", "request": old, "code": "signature_expired"},
        {"name": "The first request again: its nonce was taken", "request": first, "code": "signature_replayed",
         "after": ["GET without a body"]},
    ]
    return doc("signatures", "Signed requests (SPEC.md § 5.4, RFC 9421): each accepted request's signature base "
               "and headers, by the key below, at the server time below; then requests a server refuses, in "
               "order, each with the code it answers.",
               key={"seed": SEED.hex(), "public_key": b64(public), "keyid": client.key_thumbprint(public),
                    "short_fingerprint": client.key_fingerprint(b64(public)),
                    "note": "RFC 8032 § 7.1, test 1: a published test key, never a real one."},
               token=TOKEN, server_time=CREATED, skew=SKEW, accepted=accepted, refused=refused)


def homebrew_vectors():
    manifests = [
        [{"path": "/switch/org.example.frostline/frostline.nro", "size": 471040, "sha256": "1" * 64},
         {"path": "/config/org.example.frostline/settings.ini", "size": 96, "sha256": "2" * 64}],
        [{"path": "/switch/org.example.lanterne/données/carte.bin", "size": 12, "sha256": "3" * 64},
         {"path": "/switch/org.example.lanterne/Zeta.txt", "size": 1, "sha256": "4" * 64},
         {"path": "/switch/org.example.lanterne/alpha.txt", "size": 0, "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}],
        [],
    ]
    out = []
    for m in manifests:
        entries = sorted(m, key=lambda e: e["path"].encode())
        canonical = "[" + ",".join('{"path":%s,"sha256":"%s","size":%d}' % (  # noqa: UP031 - the canonical bytes
            json.dumps(e["path"], ensure_ascii=False), e["sha256"], e["size"]) for e in entries) + "]"
        out.append({"manifest": m, "canonical": canonical, "manifest_sha256": client.manifest_sha256(m)})
    public = client.ed25519_public(AUTHOR)
    entries = []
    for hid, platform, build, sha, man in (("org.example.frostline", "switch", 10400, "a" * 64, out[0]["manifest_sha256"]),
                                           ("org.example.harborlights", "linux", 20100, "b" * 64, out[1]["manifest_sha256"])):
        entry = {"id": hid, "platform": platform, "build": build,
                 "package": {"sha256": sha, "manifest_sha256": man}}
        message = client.signed_message(entry)
        sig = client.ed25519_sign(AUTHOR, message)
        entries.append({"entry": entry, "signed_bytes": message.decode(),
                        "signature": {"alg": "ed25519", "public_key": b64(public), "value": b64(sig)},
                        "key_short_fingerprint": client.key_fingerprint(b64(public)), "verifies": True})
    forged = json.loads(json.dumps(entries[0]))
    forged["entry"]["build"] += 1
    forged["signed_bytes"] = client.signed_message(forged["entry"]).decode()
    forged["verifies"] = False
    entries.append(forged)
    return doc("homebrew-signatures", "Manifests' canonical bytes and their manifest_sha256 (SPEC.md § 8.2), then "
               "the bytes an author signs and the signature (§ 8.4), by a fictional author's key; the last entry's "
               "build was changed after signing, and does not verify.",
               author_seed=AUTHOR.hex(), manifests=out, signed=entries)


def spki_vectors():
    old = OUT / "spki.json"
    certificates = json.loads(old.read_text(encoding="utf-8"))["certificates"] if old.exists() else make_certificates()
    for c in certificates:
        c["spki_sha256"] = ls.spki_sha256(c["pem"])
        c["short"] = ls.short_fingerprint(c["spki_sha256"])
    return doc("spki", "Self-signed certificates and the SHA-256 of their DER SubjectPublicKeyInfo, whole and "
               "short (SPEC.md § 5.3). Made once with openssl, kept as they are.", certificates=certificates)


def make_certificates():
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, args in (("ec-p256", ["-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256"]),
                           ("ed25519", ["-newkey", "ed25519"]), ("rsa-2048", ["-newkey", "rsa:2048"])):
            cert = Path(tmp) / f"{name}.pem"
            subprocess.run(["openssl", "req", "-x509", *args, "-nodes", "-keyout", str(Path(tmp) / "key.pem"),
                            "-out", str(cert), "-days", "3650", "-subj", "/CN=Lantern test vector",
                            "-addext", "subjectAltName=IP:192.0.2.10"], check=True, capture_output=True)
            out.append({"name": name, "pem": cert.read_text(encoding="ascii")})
    return out


def path_vectors():
    cases = [("/switch/org.example.frostline/frostline.nro", "a homebrew's file"),
             ("/config/org.example.frostline/données.ini", "UTF-8 beyond ASCII"),
             ("/a", "one part"),
             ("/" + "x" * 255, "a part of 255 bytes"),
             ("/" + "/".join(["y" * 200] * 5), "1004 bytes"),
             ("switch/frostline.nro", "relative"),
             ("/switch/../atmosphere/x", "a .. part"),
             ("/switch/./x", "a . part"),
             ("/switch//x", "an empty part"),
             ("/switch/", "ends with /: an empty last part"),
             ("/C:/x", "a drive letter"),
             ("/switch\\x", "a backslash"),
             ('/switch/"x"', "a double quote"),
             ("/switch/x\u0007", "a control character"),
             ("/switch/x\u0000y", "NUL"),
             ("/" + "x" * 256, "a part of 256 bytes"),
             ("/" + "/".join(["y" * 200] * 6), "above 1024 bytes"),
             ("/" + "é" * 128, "a part of 256 bytes in UTF-8")]
    out = [{"path": p, "accepted": client.path_problem(p) is None, "why": why} for p, why in cases]
    twice = [{"path": "/switch/x/Readme.txt", "size": 1, "sha256": "1" * 64},
             {"path": "/switch/x/README.txt", "size": 1, "sha256": "2" * 64}]
    return doc("paths", "Device paths (SPEC.md § 8.2): accepted or refused, each with why; then a manifest whose "
               "two paths differ only by case, which is refused.", paths=out,
               manifests=[{"manifest": twice, "accepted": not client.manifest_problems(twice),
                           "why": "two paths the same when case is ignored"}])


def version_vectors():
    cases = [("switch", 0), ("switch", 65536), ("switch", 196608), ("3ds", 0), ("3ds", 2069), ("3ds", 1024),
             ("3ds", 65535), ("vita", "01.00"), ("vita", "01.03"), ("vita", "02.10"), ("ps4", "01.03"), ("ps4", "10.50"),
             ("android", 12), ("android", 2147483647)]
    out = []
    for platform, version in cases:
        code = client.version_code(platform, version)
        out.append({"platform": platform, "version": version, "version_code": code,
                    "version_name": client.version_name(platform, code)})
    refused = []
    for platform, version in (("vita", "1.3"), ("ps4", "01.3"), ("3ds", 65536), ("switch", -1)):
        try:
            client.version_code(platform, version)
        except ValueError as e:
            refused.append({"platform": platform, "version": version, "why": str(e)})
    return doc("version-codes", "version_code from a platform's own version, and version_name where the profile "
               "derives it (SPEC.md Annex A: the 3DS's title version, the Vita's and the PS4's APP_VER); then "
               "versions that are none. A client compares version_code, never version_name.",
               cases=out, refused=refused)


def requires_vectors():
    switch = {"firmware": "18.1.0", "atmosphere": "1.7.1"}
    handheld = {"glibc": "2.31", "ram_mb": 1024, "screen": "640x480", "gpu": ["gles2", "gles3"]}
    cases = [
        ("Atmosphère at least, met", {"text": "Atmosphère 1.7", "min": {"atmosphere": "1.7.0"}}, switch),
        ("A missing part is 0: 1.7 is 1.7.0", {"text": "Atmosphère 1.7", "min": {"atmosphere": "1.7"}}, switch),
        ("A firmware above the device's", {"text": "System 19", "min": {"firmware": "19.0.0"}}, switch),
        ("Parts compare as numbers: 2.31 is above 2.4", {"text": "glibc 2.4", "min": {"glibc": "2.4"}}, handheld),
        ("glibc above the device's", {"text": "glibc 2.35", "min": {"glibc": "2.35"}}, handheld),
        ("Memory and screen, met", {"text": "1 GiB, 640×480", "min": {"ram_mb": 1024, "screen": "640x480"}}, handheld),
        ("A screen too small in one way", {"text": "720p", "min": {"screen": "1280x480"}}, handheld),
        ("One of the GPU interfaces is enough", {"text": "GLES 3 or Vulkan", "gpu": ["gles3", "vulkan"]}, handheld),
        ("None of the GPU interfaces", {"text": "Vulkan", "gpu": ["vulkan"]}, handheld),
        ("A GPU name this text does not know", {"text": "Metal", "gpu": ["metal"]}, handheld),
        ("A key this text does not know: a warning", {"text": "A pump", "min": {"pump": "2"}}, handheld),
        ("Unknown to the device: a warning", {"text": "glibc 2.30", "min": {"glibc": "2.30"}}, {}),
        ("A vendor's key is ignored", {"text": "Nothing", "x-example-dock": True}, handheld),
        ("A failure wins over a warning", {"text": "Mixed", "min": {"glibc": "2.40", "pump": "1"}}, handheld),
        ("A key of requires this text does not list", {"text": "Network", "network": "lan"}, handheld),
    ]
    out = []
    for name, requires, device in cases:
        decision, reasons = client.offer({"requires": requires}, device)
        out.append({"name": name, "requires": requires, "device": device, "decision": decision,
                    "conditions": len(reasons)})
    return doc("requires", "Requirements (SPEC.md § 8.7) and what a client knows of its device: offer, warn (a "
               "condition it cannot read: it still offers, naming it) or refuse (a condition the device fails); "
               "conditions counts those it names.", cases=out)


def cap_vectors():
    t = [{"system": "PEGI", "rating": "12"}, {"system": "ESRB", "rating": "T"}]
    cases = [
        ("An age cap reads the highest age", t, {"age": 12}),
        ("ESRB T is 13", t, {"age": 13}),
        ("A cap of a system reads that system's rating", t, {"system": "PEGI", "rating": "12"}),
        ("A system the title has no rating of: the highest age", [{"system": "USK", "rating": "16"}], {"system": "PEGI", "rating": "12"}),
        ("Unrated, shown by default", [], {"age": 7}),
        ("Unrated, hidden when asked", [], {"age": 7, "unrated": "hide"}),
        ("A rating the table does not list is unrated", [{"system": "ESRB", "rating": "RP"}], {"age": 7, "unrated": "hide"}),
        ("A system the table does not list is unrated", [{"system": "OFLC", "rating": "M"}], {"age": 18}),
        ("At the cap is not above it", [{"system": "CERO", "rating": "B"}], {"age": 12}),
        ("ACB MA15+", [{"system": "ACB", "rating": "MA15+"}], {"system": "CLASSIND", "rating": "14"}),
        ("GRAC ALL", [{"system": "GRAC", "rating": "ALL"}], {"age": 0}),
    ]
    return doc("rating-caps", "Ratings and rating caps (SPEC.md § 5.6): whether a server hides the title (or the "
               "homebrew) from a token of that cap, and the age it reads.",
               ages=client.RATING_AGES,
               cases=[{"name": n, "ratings": r, "cap": c, "age": client.rating_age(r, c), "hidden": client.above_cap(r, c)}
                      for n, r, c in cases])


# The eight encodings of the points of small order: the identity, and the points of order 2, 4 and 8.
SMALL_ORDER = ["0100000000000000000000000000000000000000000000000000000000000000",
               "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
               "0000000000000000000000000000000000000000000000000000000000000000",
               "0000000000000000000000000000000000000000000000000000000000000080",
               "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
               "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85",
               "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
               "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa"]
L = 2 ** 252 + 27742317777372353535851937790883648493


def ed25519_vectors():
    messages = [f"Frostline Tales {n}" for n in range(16)]
    public = client.ed25519_public(AUTHOR)
    good = client.ed25519_sign(AUTHOR, b"Lantern")
    s = int.from_bytes(good[32:], "little")
    p = 2 ** 255 - 19
    cases = [
        {"name": "A valid signature, for contrast", "public_key": public.hex(), "message": "Lantern",
         "signature": good.hex(), "verifies": True},
        {"name": "S + L: the same S, not reduced (S >= L)", "public_key": public.hex(), "message": "Lantern",
         "signature": good[:32].hex() + (s + L).to_bytes(32, "little").hex(), "verifies": False},
        {"name": "A key whose y is p (not canonical)", "public_key": p.to_bytes(32, "little").hex(),
         "message": "Lantern", "signature": good.hex(), "verifies": False},
        {"name": "A key whose y is p + 1, the identity not canonical", "public_key": (p + 1).to_bytes(32, "little").hex(),
         "message": "Lantern", "signature": bytes(64).hex(), "verifies": False},
        {"name": "The identity with its sign bit set (x = 0, not canonical)",
         "public_key": "0100000000000000000000000000000000000000000000000000000000000080",
         "message": "Lantern", "signature": bytes(64).hex(), "verifies": False},
        {"name": "A real key, R of small order, S = 0", "public_key": public.hex(), "message": "Lea",
         "signature": SMALL_ORDER[4] + "00" * 32, "verifies": False},
    ]
    for c in cases:
        got = client.ed25519_verify(bytes.fromhex(c["public_key"]), c["message"].encode(), bytes.fromhex(c["signature"]))
        assert got == c["verifies"], c["name"]
    return doc("ed25519-refused", "Ed25519 signatures a verifier MUST refuse whatever the verification equation says "
               "(SPEC.md § 8.4, § 5.4): every pair of the small-order encodings below as the key and as R, with S = 0, "
               "over each message, never verifies (the cofactorless equation alone accepts about one message in 8); "
               "then single cases, a valid one for contrast. Keys, R and signatures in hex; messages as UTF-8.",
               small_order=SMALL_ORDER, messages=messages, small_order_pairs_verify=False, cases=cases)


def pattern(size):
    """The bytes of a vector's archive given by its size: byte i is i % 251."""
    return bytes(i % 251 for i in range(size))


def chunk_tags(data, size):
    """The 16-byte tag of each chunk of an encrypted backup of an archive of `size` bytes, hex."""
    tags, pos = [], e2e.HEADER
    for i in range(max(1, -(-size // e2e.CHUNK))):
        pos += min(e2e.CHUNK, size - i * e2e.CHUNK) + e2e.TAG
        tags.append(data[pos - e2e.TAG:pos].hex())
    return tags


def e2e_vectors():
    keys = [hashlib.sha256(b"Lea's fictional save key").digest(), bytes(range(32))]
    file_key, wrap_nonce = hashlib.sha256(b"a fictional file key").digest(), bytes(range(100, 124))
    primitives = {
        "hkdf_sha256": [{"ikm": keys[0].hex(), "salt": "", "info": "lantern-save-e2e-1 key id", "length": 8,
                         "okm": e2e.hkdf_sha256(keys[0], b"lantern-save-e2e-1 key id", 8).hex()}],
        "hchacha20": [{"key": keys[1].hex(), "nonce": bytes(range(16)).hex(),
                       "subkey": e2e.hchacha20(keys[1], bytes(range(16))).hex()}],
        "xchacha20poly1305": [
            {"key": keys[1].hex(), "nonce": wrap_nonce.hex(), "aad": "4c616e7465726e", "plaintext": b"Frostline".hex(),
             "sealed": e2e.xchacha20poly1305_seal(keys[1], wrap_nonce, b"Frostline", b"Lantern").hex()},
            {"key": file_key.hex(), "nonce": e2e.chunk_nonce(0, True).hex(), "aad": "", "plaintext": "",
             "sealed": e2e.xchacha20poly1305_seal(file_key, e2e.chunk_nonce(0, True), b"").hex()}]}
    key_docs = [{"save_key": k.hex(), "key_id": e2e.key_id(k), "wrapping_key": e2e.wrapping_key(k).hex(),
                 "phrase": e2e.phrase(k), "qr": e2e.qr_text(k)} for k in keys]
    empty_zip = b"PK\x05\x06" + bytes(18)
    cases = [("An empty zip: one chunk", empty_zip), ("An empty archive: one empty chunk", b""),
             ("Exactly one chunk of 65,536 bytes", pattern(65536)), ("Two chunks: 65,536 and 100 bytes", pattern(65636))]
    backups = []
    for name, archive in cases:
        data = e2e.encrypt(keys[0], archive, file_key, wrap_nonce)
        assert e2e.decrypt(keys[0], data) == archive and len(data) == e2e.encrypted_size(len(archive))
        case = {"name": name, "save_key": keys[0].hex(), "file_key": file_key.hex(), "wrap_nonce": wrap_nonce.hex(),
                "archive": archive.hex() if len(archive) <= 64 else {"size": len(archive), "byte_i": "i % 251"},
                "header": data[:e2e.HEADER].hex(), "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "chunk_tags": chunk_tags(data, len(archive))}
        if len(data) <= 256:
            case["encrypted"] = data.hex()
        backups.append(case)
    small = e2e.encrypt(keys[0], empty_zip, file_key, wrap_nonce)
    two = e2e.encrypt(keys[0], pattern(65636), file_key, wrap_nonce)

    def flip(data, at):
        return data[:at] + bytes([data[at] ^ 1]) + data[at + 1:]

    refused = [
        ("A byte of the chunk changed", cases[0][0], "flip bit 0 of byte 90", flip(small, 90), keys[0]),
        ("A byte of the tag changed", cases[0][0], "flip bit 0 of the last byte", flip(small, len(small) - 1), keys[0]),
        ("The key id changed", cases[0][0], "flip bit 0 of byte 8", flip(small, 8), keys[0]),
        ("The wrapped file key changed", cases[0][0], "flip bit 0 of byte 40", flip(small, 40), keys[0]),
        ("Another save key", cases[0][0], "read with the second key", small, keys[1]),
        ("The last chunk cut short", cases[3][0], "drop the last byte", two[:-1], keys[0]),
        ("The last chunk dropped", cases[3][0], "keep the first 88 + 65552 bytes", two[:e2e.HEADER + e2e.CHUNK + e2e.TAG],
         keys[0]),
        ("Bytes after the last chunk", cases[0][0], "append 16 zero bytes", small + bytes(16), keys[0]),
        ("Chunks swapped", cases[3][0], "swap the two chunks",
         two[:e2e.HEADER] + two[e2e.HEADER + e2e.CHUNK + e2e.TAG:] + two[e2e.HEADER:e2e.HEADER + e2e.CHUNK + e2e.TAG], keys[0]),
        ("Not an encrypted backup", None, "a zip in clear", empty_zip, keys[0]),
    ]
    refused_docs = []
    for name, of, operation, data, key in refused:
        try:
            e2e.decrypt(key, data)
            raise AssertionError(name)
        except e2e.Refused:
            pass
        refused_docs.append({"name": name, "backup": of, "operation": operation, "save_key": key.hex(),
                             "sha256": hashlib.sha256(data).hexdigest(), "opens": False})
    good = key_docs[0]["phrase"]
    phrases = [("As shown", good, True), ("Lower case, spaces for dashes", good.lower().replace("-", " "), True),
               ("One symbol changed", ("3" if good[0] != "3" else "4") + good[1:], False),
               ("A symbol missing", good[:-1], False), ("An O, outside the alphabet", "O" + good[1:], False)]
    phrase_docs = []
    for name, text, ok in phrases:
        try:
            got = e2e.key_from_phrase(text) == keys[0]
        except e2e.Refused:
            got = False
        assert got == ok, name
        phrase_docs.append({"name": name, "phrase": text, "accepted": ok})
    return doc("encrypted-saves", "End-to-end encrypted backups, scheme lantern-save-e2e-1 (SPEC.md § 9.4): the "
               "primitives (HKDF-SHA-256, HChaCha20, XChaCha20-Poly1305), save keys with their id, wrapping key, "
               "recovery phrase and QR text, backups made with the file key and wrap nonce given (archive bytes in "
               "hex, or of the size given, byte i being i % 251), each chunk's tag, then backups a reader refuses "
               "(an operation on a backup above) and phrases. Fictional keys; hex.",
               chunk=e2e.CHUNK, header=e2e.HEADER, primitives=primitives, keys=key_docs, backups=backups,
               refused=refused_docs, phrases=phrase_docs)


GRANT_SEED = hashlib.sha256(b"Lantern vectors' fictional grant key").digest()
GRANT_UID = "6f1c2a8e-4b7d-4e2a-9c31-8d5e2f0a7b14"


def grant_vectors():
    public = server_ed25519.public_key(GRANT_SEED)
    sha, size, exp = "3a7bd3e2b4c1f0a9e8d7c6b5a4938271605f4e3d2c1b0a9f8e7d6c5b4a392817", 734003200, CREATED + 600
    grant = ls.make_grant(GRANT_SEED, GRANT_UID, sha, size, exp)
    signature = grant.split(".")[1]
    forged = client.b64url(ls.grant_payload(GRANT_UID, sha, size + 1, exp)) + "." + signature
    other = ls.make_grant(bytes(32), GRANT_UID, sha, size, exp)
    keys = {GRANT_UID: public}
    cases = [("Valid, before exp", grant, sha, CREATED, keys, True),
             ("Expired", grant, sha, exp + 1, keys, False),
             ("For another file than the path's", grant, "0" * 64, CREATED, keys, False),
             ("The payload changed (size), the signature kept", forged, sha, CREATED, keys, False),
             ("Signed by another key", other, sha, CREATED, keys, False),
             ("A server the peer did not pair with", grant, sha, CREATED, {"00000000-0000-4000-8000-000000000000": public},
              False),
             ("Not a grant", "not-a-grant", sha, CREATED, keys, False)]
    out = []
    for name, g, path_sha, now, known, ok in cases:
        doc_ = ls.read_grant(g, known, now)
        got = doc_ is not None and doc_["sha256"] == path_sha
        assert got == ok, name
        out.append({"name": name, "grant": g, "path_sha256": path_sha, "peer_time": now,
                    "servers": {u: b64(k) for u, k in known.items()}, "serves": ok})
    return doc("grants", "Grants (SPEC.md § 19.3) and what a peer decides of each (§ 19.4): a grant is the base64url "
               "payload, a dot, and the base64url Ed25519 signature of the payload's bytes by the server's grant key.",
               key={"seed": GRANT_SEED.hex(), "public_key": b64(public)},
               payload=ls.grant_payload(GRANT_UID, sha, size, exp).decode(), grant=grant, cases=out)


def sync_vectors():
    server_now = "2026-10-30T09:30:00.000Z"
    now = ls.datetime.fromisoformat("2026-10-30T09:30:00+00:00")
    wish = {"platform": "switch", "title_id": "0100ABCD00010000"}
    noted = {**wish, "note": "For the holidays"}
    cases = [
        ("Nothing kept: the item sent is kept", None, {"value": wish, "updated": "2026-10-30T09:00:00.000Z"}),
        ("A later updated wins", {"value": wish, "updated": "2026-10-30T09:00:00.000Z"},
         {"value": noted, "updated": "2026-10-30T09:00:00.001Z"}),
        ("An earlier updated loses", {"value": noted, "updated": "2026-10-30T09:10:00.000Z"},
         {"value": wish, "updated": "2026-10-30T09:05:00.000Z"}),
        ("The same updated: a deletion wins", {"value": wish, "updated": "2026-10-30T09:00:00.000Z"},
         {"deleted": True, "updated": "2026-10-30T09:00:00.000Z"}),
        ("The same updated: a value loses to the deletion kept", {"deleted": True, "updated": "2026-10-30T09:00:00.000Z"},
         {"value": wish, "updated": "2026-10-30T09:00:00.000Z"}),
        ("The same updated: the greater canonical JSON wins", {"value": wish, "updated": "2026-10-30T09:00:00.000Z"},
         {"value": noted, "updated": "2026-10-30T09:00:00.000Z"}),
        ("The same updated: the smaller canonical JSON loses", {"value": noted, "updated": "2026-10-30T09:00:00.000Z"},
         {"value": wish, "updated": "2026-10-30T09:00:00.000Z"}),
        ("The same item again: nothing changes", {"value": wish, "updated": "2026-10-30T09:00:00.000Z"},
         {"value": wish, "updated": "2026-10-30T09:00:00.000Z"}),
        ("A time without milliseconds reads as .000", {"value": wish, "updated": "2026-10-30T09:00:00.000Z"},
         {"value": noted, "updated": "2026-10-30T09:00:01Z"}),
        ("An updated an hour ahead is the server's time", {"value": wish, "updated": "2026-10-30T09:29:00.000Z"},
         {"value": noted, "updated": "2026-10-30T10:30:00.000Z"}),
    ]
    out = []
    for name, have, sent in cases:
        sent_n = dict(sent, key="switch/0100ABCD00010000")
        sent_n["updated"] = ls.sync_time(sent["updated"], now, SKEW)
        have_n = dict(have, key="switch/0100ABCD00010000") if have else None
        wins = ls.sync_wins(sent_n, have_n)
        kept = {k: v for k, v in (sent_n if wins else have_n).items() if k != "key"}
        case = {"name": name, "have": have, "sent": sent, "replaced": wins, "kept": kept}
        if have and "value" in have and "value" in sent:
            case["canonical"] = {"have": ls.canonical(have["value"]).decode(), "sent": ls.canonical(sent["value"]).decode()}
        out.append(case)
    return doc("sync-merge", "Sync's merge rule (SPEC.md § 20.4), item by item: the item a server keeps of the one "
               "it has (have) and the one sent, at the server's time below, with auth.skew 300 seconds; replaced "
               "says whether the item sent is the one kept (and takes the next rev).",
               server_time=server_now, skew=SKEW, cases=out)


def static_vectors():
    routes = [
        ("The handshake", "GET /.well-known/lantern", static.layout_path("handshake")),
        ("Apps of the Switch, page 1", "GET <base>/v1/apps?platform=switch", static.layout_path("apps", "switch", page=1)),
        ("Apps of the Switch, the page after cursor 2", "GET <base>/v1/apps?platform=switch&cursor=2",
         static.layout_path("apps", "switch", page=2)),
        ("A title", "GET <base>/v1/titles/0100ABCD00010000 (switch)", static.layout_path("title", "switch", "0100ABCD00010000")),
        ("Every title of Android, page 1", "titles of android", static.layout_path("titles", "android", page=1)),
        ("Homebrew of Linux, page 1", "GET <base>/v1/homebrew?platform=linux", static.layout_path("homebrew", "linux", page=1)),
        ("A homebrew entry", "GET <base>/v1/homebrew/org.example.frostline (switch)",
         static.layout_path("entry", "switch", "org.example.frostline")),
        ("A title's cheat sets", "GET <base>/v1/cheats?platform=switch&title_id=0100ABCD00010000",
         static.layout_path("cheats", "switch", "0100ABCD00010000")),
        ("A cheat set's text", "GET <base>/v1/cheats/cs_Jt3Vx0", static.layout_path("cheat", ident="cs_Jt3Vx0")),
        ("A file", "GET <file> of sha256 3a7b…", static.layout_path("blob", ident="3a7bd3e2b4c1f0a9e8d7c6b5a4938271605f4e3d2c1b0a9f8e7d6c5b4a392817")),
    ]
    paths = [("v1/blobs/sha256/3a7bd3e2b4c1f0a9e8d7c6b5a4938271605f4e3d2c1b0a9f8e7d6c5b4a392817", True),
             ("media/icons/frostline.png", True), ("/v1/blobs/sha256/3a7b", False),
             ("https://lea.example.org/library/v1/blobs/sha256/3a7b", False), ("../library/v1/blobs/sha256/3a7b", False),
             ("v1/blobs/../../secrets", False), ("v1\\blobs\\3a7b", False), ("v1/blobs/sha256/3a7b?download=1", False),
             ("file:v1/blobs", False)]
    for p_, ok in paths:
        assert static.relative_ok(p_) == ok, p_
    return doc("static-layout", "A static library's layout (SPEC.md § 21.1): each read route's file, relative to the "
               "library's root, and the paths a document's file or image url may hold (relative: no scheme, no "
               "leading /, no .. part, no backslash, no query).",
               routes=[{"name": n, "route": r, "file": f} for n, r, f in routes],
               paths=[{"path": p_, "accepted": ok} for p_, ok in paths])


def everything():
    return {"signatures": signature_vectors(), "homebrew-signatures": homebrew_vectors(), "spki": spki_vectors(),
            "paths": path_vectors(), "version-codes": version_vectors(), "requires": requires_vectors(),
            "rating-caps": cap_vectors(), "ed25519-refused": ed25519_vectors(), "encrypted-saves": e2e_vectors(),
            "grants": grant_vectors(), "sync-merge": sync_vectors(), "static-layout": static_vectors()}


def text(doc):
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


def main(argv):
    vectors = everything()
    if "--check" in argv:
        bad = [n for n, d in vectors.items() if not (OUT / f"{n}.json").exists()
               or (OUT / f"{n}.json").read_text(encoding="utf-8") != text(d)]
        for n in bad:
            print(f"make_vectors: vectors/{n}.json is not what the reference gives (run tools/make_vectors.py)")
        return 1 if bad else 0
    OUT.mkdir(exist_ok=True)
    for name, d in vectors.items():
        (OUT / f"{name}.json").write_text(text(d), encoding="utf-8")
    print(f"make_vectors: {len(vectors)} files in {OUT.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
