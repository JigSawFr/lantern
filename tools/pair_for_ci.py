#!/usr/bin/env python3
"""Starts the reference server as a private one, pairs a device with it as
a user would, with a device key, and prints the device's token: for running
the conformance suite with a token and its key (CI).

    python3 tools/pair_for_ci.py --library DIR --workdir DIR [--port 8081]
    python3 conformance/run.py http://127.0.0.1:8081/ --token TOKEN --key DIR/device.key

It writes WORKDIR/users.json (one fictional account, "mila", holding every
scope, with a password made for this run), starts `python3 -m server` on
that library, private, its state and save backups in WORKDIR (so that it
shares nothing with another server on the same library), and leaves it
running: its process id is in WORKDIR/server.pid, its log in
WORKDIR/server.log. Then it pairs as SPEC.md
§ 5.2 says, over HTTP on loopback: the console makes an Ed25519 key
(SPEC.md § 5.4), kept in WORKDIR/device.key (its 32-byte seed, base64),
and asks for a code with it; the user signs in on /pair, types the code, and
approves; the console polls, its polls signed by its key, and gets its
token, bound to the key, which this script prints on stdout, alone.
Standard library only.
"""
import argparse
import base64
import json
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "conformance"))
import lantern_client as client

from server import lantern_server as ls

DEVICE = {"schema": 1, "device": "Lantern CI", "scopes": list(ls.SCOPES)}


def call(url, data=None, form=None, timeout=10, headers=None):
    """(status, body) of a request to the server; a JSON body for `data`, a form for `form`."""
    headers = {"User-Agent": "LanternCI/1.0", **(headers or {})}
    if data is not None:
        body, headers["Content-Type"] = json.dumps(data).encode(), "application/json"
    elif form is not None:
        body, headers["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
    else:
        body = None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def start(library, workdir, port, cors=()):
    """The server, private, in the background, allowing the pages of the origins `cors` (SPEC.md § 2.5); the
    account's name and password."""
    password = secrets.token_urlsafe(18)
    users = {"schema": 1, "public": False, "users": [
        {"name": "mila", "password": ls.hash_password(password), "scopes": list(ls.SCOPES), "state": "active"}]}
    (workdir / "users.json").write_text(json.dumps(users), encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-m", "server", "--library", str(library), "--port", str(port), "--quiet",
         "--users", str(workdir / "users.json"), "--state", str(workdir / "state.json"),
         "--saves", str(workdir / "saves"), *(x for o in cors for x in ("--cors-origin", o))],
        cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=(workdir / "server.log").open("ab"), start_new_session=True)
    (workdir / "server.pid").write_text(f"{process.pid}\n", encoding="ascii")
    return process, "mila", password


def wait_for(origin, process, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            sys.exit(f"pair_for_ci: the server stopped (exit {process.returncode})")
        try:
            if call(origin + "/.well-known/lantern", timeout=2)[0] == 200:
                return
        except OSError:
            pass
        time.sleep(0.2)
    sys.exit("pair_for_ci: the server did not answer in time")


def pair(origin, name, password, seed):
    """A device's token, paired as a console and its user would (SPEC.md § 5.2), bound to the key of
    `seed` (§ 5.4)."""
    public = client.ed25519_public(seed)
    device = {**DEVICE, "key": {"alg": "ed25519", "public_key": base64.b64encode(public).decode()}}
    status, body = call(origin + ls.BASE + "/v1/pairing", data=device)
    if status != 200:
        sys.exit(f"pair_for_ci: pairing refused ({status}): {body[:200]!r}")
    code = json.loads(body)
    status, page = call(origin + "/pair", form={"name": name, "password": password, "code": code["code"]})
    nonce = re.search(rb'name="nonce" value="([^"]+)"', page)
    if status != 200 or nonce is None:
        sys.exit(f"pair_for_ci: signing in on /pair failed ({status})")
    status, _ = call(origin + "/pair", form={"nonce": nonce.group(1).decode(), "decision": "approve"})
    if status != 200:
        sys.exit(f"pair_for_ci: approving failed ({status})")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        status, body = call(origin + code["poll"], headers=client.sign(seed, "GET", origin + code["poll"]))
        if status == 200:
            return json.loads(body)["token"]
        if status != 202:
            sys.exit(f"pair_for_ci: polling failed ({status})")
        time.sleep(min(code.get("interval", 1), 1))
    sys.exit("pair_for_ci: no token in time")


def main(argv=None):
    p = argparse.ArgumentParser(description="Start a private reference server, pair with it, print the token.")
    p.add_argument("--library", required=True, help="the folder of packages (tests/library.py makes one)")
    p.add_argument("--workdir", required=True, help="where users.json, the state and server.pid go")
    p.add_argument("--port", type=int, default=8081)
    p.add_argument("--cors-origin", action="append", default=[], help="an origin whose pages may read the server")
    args = p.parse_args(argv)
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    process, name, password = start(Path(args.library).resolve(), workdir, args.port, args.cors_origin)
    origin = f"http://127.0.0.1:{args.port}"
    seed, _ = client.ed25519_keypair()
    key = workdir / "device.key"
    key.write_text(base64.b64encode(seed).decode() + "\n", encoding="ascii")
    key.chmod(0o600)
    try:
        wait_for(origin, process)
        print(pair(origin, name, password, seed))
    except BaseException:
        process.terminate()
        raise
    return 0


if __name__ == "__main__":
    sys.exit(main())
