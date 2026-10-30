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
- rating-caps.json: ratings and caps, and whether a server hides (§ 5.6).

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
import lantern_client as client  # noqa: E402

from server import lantern_server as ls  # noqa: E402

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


def everything():
    return {"signatures": signature_vectors(), "homebrew-signatures": homebrew_vectors(), "spki": spki_vectors(),
            "paths": path_vectors(), "version-codes": version_vectors(), "requires": requires_vectors(),
            "rating-caps": cap_vectors()}


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
