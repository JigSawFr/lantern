#!/usr/bin/env python3
"""Lantern reference server: a folder of packages, served by the protocol.

    python3 -m server --library DIR [--port 8080] [--users users.json]
    server/lantern_server.py --library DIR ...

A reference, not a product: it shows what SPEC.md asks of a server in a few
hundred lines of standard-library Python, and passes conformance/run.py.

What it serves (SPEC.md § 6): every .nsp, .nsz, .xci and .xcz below DIR
(dot folders skipped). An app's identity comes from DIR/library.json when
it lists the file, otherwise from the `[0100ABCD00010000]` and `[v196608]`
in its name; the title id and type follow from the app id. library.json:

    {"schema": 1, "apps": [{"file": "Frostline Tales [0100ABCD00010000][v0].nsp",
      "title_id": "0100ABCD00010000", "app_id": "0100ABCD00010000",
      "type": "base", "version": 0, "display_version": "1.0.0",
      "name": "Frostline Tales", "release": "2025-03-14"}]}

Each file is hashed once (SHA-256); the hashes are kept with the server's
uid and secret in a state file (--state, default DIR/.lantern-state.json).

Families offered: library, changes and media (a title's name, no images),
and pairing when there are accounts. Saves, cheats, requests and sections
stay at 0: their routes answer 404.

Accounts (SPEC.md § 5): without --users, the server is public, every caller
reads the library anonymously, and nobody pairs. With --users FILE:

    {"schema": 1, "public": false, "users": [
      {"name": "lea", "password": "pbkdf2-sha256$600000$<salt>$<hash>",
       "scopes": ["library"], "state": "active"}]}

`python3 -m server --hash-password` prints a password's hash. `state` is
`active` or `frozen`. A password is only ever typed on the server's own
page, /pair: a console gets a token by pairing (SPEC.md § 5.2), which the
user approves there, signed in, with the code the console shows. Tokens are
kept hashed in the state file ("tokens"); `--tokens` lists them and
`--revoke ID` revokes one, even while the server runs. `--token-days N`
makes new tokens expire after N days.

TLS: give --tls-cert and --tls-key; /pair then shows the short fingerprint
of the key (SPEC.md § 5.3). Without them the server speaks plain HTTP, and
only on a loopback address (127.0.0.0/8, ::1), for testing: SPEC.md § 2.

LAN discovery (SPEC.md § 4.1): --discovery answers Lantern's discovery
datagram on UDP 47115 (--discovery-port to change it), from local addresses
only (not global ones), a few times a second per address.
DNS-SD is not advertised: the standard library has no mDNS.
"""
import argparse
import base64
import getpass
import hashlib
import hmac
import html
import ipaddress
import json
import math
import re
import secrets
import socket
import ssl
import sys
import threading
import time
import traceback
import uuid
from collections import OrderedDict
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

VERSION = "0.2.0"
BASE = "/api/lantern"
FORMATS = {".nsp": "nsp", ".nsz": "nsz", ".xci": "xci", ".xcz": "xcz"}
FAMILIES = ("library", "media", "changes", "sections", "saves", "cheats", "requests", "pairing")
OFFERED = {"library": 1, "media": 1, "changes": 1}  # family -> the schema written; the others are 0
SCOPE_OF = {"library": "library", "media": "library", "changes": "library"}
PAGE_LIMIT = 500        # limits.page_size
PAGE_DEFAULT = 100
BODY_LIMIT = 1 << 20    # a request document, well under SPEC.md § 11's 32 MiB
JOURNAL_LIMIT = 10000   # changes kept for /v1/changes; older tokens are gone
CURSOR_LIMIT = 10000    # cursors kept; older ones are gone
ID16 = re.compile(r"^[0-9A-F]{16}$")
TID_IN_NAME = re.compile(r"\[([0-9A-Fa-f]{16})\]")
VERSION_IN_NAME = re.compile(r"\[v(\d+)\]")
APP_TYPES = ("base", "update", "dlc")
CHUNK = 1 << 20
SCOPES = ("library", "saves", "cheats", "cheats.write", "requests", "admin")
DISCOVERY_PORT = 47115
DATAGRAM_LIMIT = 1200   # SPEC.md § 4.1, § 11
CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # 5 bits a symbol; no 0, O, 1 or I
CODE_SYMBOLS = 8        # 40 bits
PAIR_EXPIRES = 600      # seconds a code lives (SPEC.md § 5.2: 10 minutes at most)
PAIR_INTERVAL = 5       # seconds between polls
PAIR_RATE = (10, 60.0)          # pairing requests per address, per window
PAIR_ATTEMPTS = (10, 600.0)     # failed sign-ins or codes on /pair per address, per window
PENDING_LIMIT = 1000            # pairings waiting at once
# check_password() against this when the name is unknown, so that it takes as long.
NO_USER = "pbkdf2-sha256$600000$AAAAAAAAAAAAAAAAAAAAAA$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"


def log(msg):
    print(f"lantern: {msg}", file=sys.stderr, flush=True)


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unb64url(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def clip(text, limit=512):
    """A string cut to `limit` UTF-8 bytes on a character boundary (SPEC.md § 11)."""
    return text.encode()[:limit].decode(errors="ignore")


def utc(ns):
    return datetime.fromtimestamp(ns / 1e9, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc(offset=0.0):
    return utc(time.time_ns() + int(offset * 1e9))


def is_loopback(host):
    """True for 127.0.0.0/8, ::1 and names that resolve only to them."""
    host = host.strip("[]")
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0].split("%")[0]).is_loopback for i in infos)


def der(data, pos):
    """(content start, content end, tag) of the DER element at `pos`."""
    tag, length, pos = data[pos], data[pos + 1], pos + 2
    if length & 0x80:
        n = length & 0x7F
        length, pos = int.from_bytes(data[pos:pos + n], "big"), pos + n
    return pos, pos + length, tag


def spki_sha256(cert_pem):
    """The SHA-256 of a certificate's SubjectPublicKeyInfo (SPEC.md § 5.3), hex."""
    first = re.search(r"-----BEGIN CERTIFICATE-----.+?-----END CERTIFICATE-----", cert_pem, re.DOTALL)
    data = ssl.PEM_cert_to_DER_cert(first.group(0))
    start, _, _ = der(data, 0)              # Certificate
    pos, end, _ = der(data, start)          # TBSCertificate
    fields = []
    while pos < end:
        _, after, tag = der(data, pos)
        fields.append((pos, after, tag))
        pos = after
    if fields[0][2] == 0xA0:                # [0] version
        fields = fields[1:]
    begin, after, _ = fields[5]             # serial, signature, issuer, validity, subject, SPKI
    return hashlib.sha256(data[begin:after]).hexdigest()


def short_fingerprint(sha256_hex):
    """The first 16 hex digits, upper-case, in groups of 4 (SPEC.md § 5.3)."""
    return " ".join(sha256_hex[i:i + 4].upper() for i in range(0, 16, 4))


class Limiter:
    """At most `count` events per `window` seconds for each key (an address)."""

    def __init__(self, count, window):
        self.count, self.window, self.events, self.lock = count, window, {}, threading.Lock()

    def wait(self, key):
        """Seconds to wait before the next event, 0 when it may happen now."""
        now = time.monotonic()
        with self.lock:
            kept = [t for t in self.events.get(key, ()) if now - t < self.window]
            self.events[key] = kept
            if len(self.events) > 10000:
                self.events = {k: v for k, v in self.events.items() if v and now - v[-1] < self.window}
            return max(1, math.ceil(self.window - (now - kept[0]))) if len(kept) >= self.count else 0

    def record(self, key):
        with self.lock:
            self.events.setdefault(key, []).append(time.monotonic())

    def hit(self, key):
        wait = self.wait(key)
        if not wait:
            self.record(key)
        return wait


def slow_down(wait, detail):
    return Problem(429, "slow_down", "Slow down", detail, {"Retry-After": str(int(wait))})


def derive(app_id):
    """(title_id, type) from an app id: base ...000, update ...800, add-on otherwise."""
    n = int(app_id, 16)
    low = n & 0x1FFF
    kind = "base" if low == 0 else "update" if low == 0x800 else "dlc"
    return f"{n & ~0x1FFF:016X}", kind


class Problem(Exception):
    """An error answered as application/problem+json (SPEC.md § 10)."""

    def __init__(self, status, code, title, detail=None, headers=None):
        super().__init__(title)
        self.status, self.code, self.title, self.detail = status, code, title, detail
        self.headers = headers or {}

    def document(self):
        doc = {"schema": 1, "type": f"https://lantern.boreale.dev/errors/{self.code.replace('_', '-')}",
               "title": self.title, "status": self.status, "code": self.code}
        if self.detail:
            doc["detail"] = clip(self.detail, 4096)
        return doc


def bad_request(detail):
    return Problem(400, "bad_request", "Bad request", detail)


# --- State and library ----------------------------------------------------

def read_versioned(path, what):
    """A JSON file with a `schema`: None when absent, unreadable or newer than schema 1."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        log(f"{path}: unreadable ({e}), ignored")
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("schema"), int):
        log(f"{path}: no schema, ignored")
        return None
    if doc["schema"] > 1:
        log(f"{path}: {what} of schema {doc['schema']}, newer than this server: treated as absent")
        return None
    return doc


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


class Library:
    def __init__(self, root, state_path):
        self.root = Path(root).resolve()
        self.state_path = Path(state_path)
        self.lock = threading.RLock()
        state = read_versioned(self.state_path, "state")
        # A state of a newer schema is never written over (it stays in memory only).
        self.writable = state is not None or not self.state_path.exists()
        self.state = state or {"schema": 1}
        self.state.setdefault("uid", str(uuid.uuid4()))
        self.state.setdefault("secret", secrets.token_hex(32))
        self.state.setdefault("hashes", {})
        self.secret = bytes.fromhex(self.state["secret"])
        self.epoch = secrets.token_hex(4)   # since tokens do not outlive the process
        self.seq = 0
        self.journal = []                   # (seq, "added" | "removed", app id)
        self.floor = 0                      # tokens below it are gone
        self.apps, self.files = {}, {}
        self.cursors = OrderedDict()
        self.skipped = set()                # files without an id, reported once
        self.scanned = None
        self.state_mtime = None
        self.scan(initial=True)
        self.state_mtime = self.mtime()

    @property
    def uid(self):
        return self.state["uid"]

    def mtime(self):
        try:
            return self.state_path.stat().st_mtime_ns
        except OSError:
            return None

    def save_state(self):
        if not self.writable:
            return
        try:
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, indent=1), encoding="utf-8")
            tmp.replace(self.state_path)
            self.state_mtime = self.mtime()
        except OSError as e:
            log(f"{self.state_path}: not written ({e}); kept in memory")
            self.writable = False

    def reload_tokens(self):
        """The tokens again, when another process (--revoke) changed the state file."""
        with self.lock:
            mtime = self.mtime()
            if not self.writable or mtime is None or mtime == self.state_mtime:
                return
            self.state_mtime = mtime
            doc = read_versioned(self.state_path, "state")
            if doc is not None:
                tokens = doc.get("tokens")
                self.state["tokens"] = tokens if isinstance(tokens, dict) else {}

    def metadata(self):
        doc = read_versioned(self.root / "library.json", "library.json")
        entries = doc.get("apps") if doc else None
        if not isinstance(entries, list):
            return {}
        return {e["file"]: e for e in entries if isinstance(e, dict) and isinstance(e.get("file"), str)}

    def identify(self, rel, entry):
        """An app's identity from its library.json entry, else from its file name."""
        name = Path(rel).name
        entry = entry or {}
        found = TID_IN_NAME.search(name)
        app_id = entry.get("app_id") if ID16.match(str(entry.get("app_id", ""))) else None
        app_id = app_id or (found.group(1).upper() if found else None)
        if not app_id:
            return None
        title_id, kind = derive(app_id)
        if ID16.match(str(entry.get("title_id", ""))):
            title_id = entry["title_id"]
        if entry.get("type") in APP_TYPES:
            kind = entry["type"]
        version = entry.get("version")
        if not (isinstance(version, int) and 0 <= version < 1 << 32):
            v = VERSION_IN_NAME.search(name)
            version = int(v.group(1)) if v and int(v.group(1)) < 1 << 32 else 0
        title = entry.get("name") if isinstance(entry.get("name"), str) else name.split("[")[0]
        app = {"title_id": title_id, "app_id": app_id, "type": kind, "version": version,
               "name": clip(title.strip() or app_id)}
        if isinstance(entry.get("display_version"), str):
            app["display_version"] = clip(entry["display_version"])
        try:
            release = date.fromisoformat(entry["release"]) if isinstance(entry.get("release"), str) else None
        except ValueError:
            release = None
        return app, release

    def scan(self, initial=False):
        with self.lock:
            meta, hashes, dirty = self.metadata(), self.state["hashes"], False
            apps, files, seen = {}, {}, set()
            for path in sorted(self.root.rglob("*")):
                rel = path.relative_to(self.root).as_posix()
                fmt = FORMATS.get(path.suffix.lower())
                if not fmt or any(p.startswith(".") for p in Path(rel).parts) or not path.is_file():
                    continue
                found = self.identify(rel, meta.get(rel))
                if not found:
                    if rel not in self.skipped:
                        log(f"{rel}: no app id in library.json nor in its name, skipped")
                        self.skipped.add(rel)
                    continue
                app, release = found
                st = path.stat()
                seen.add(rel)
                known = hashes.get(rel)
                if not (isinstance(known, dict) and known.get("size") == st.st_size
                        and known.get("mtime_ns") == st.st_mtime_ns):
                    known = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha256_file(path)}
                    hashes[rel], dirty = known, True
                app_key = hmac.new(self.secret, f"app\0{rel}\0{st.st_size}\0{st.st_mtime_ns}".encode(),
                                   "sha256").digest()
                aid = "a_" + b64url(app_key[:12])
                fid = "f_" + b64url(hmac.new(self.secret, b"file\0" + app_key, "sha256").digest()[:18])
                app = {"id": aid, **app, "size": st.st_size, "format": fmt, "sha256": known["sha256"],
                       "added": utc(st.st_mtime_ns), "file": f"{BASE}/v1/files/{fid}"}
                apps[aid] = {"doc": app, "path": path, "keys": {
                    "name": (app["name"].casefold(), aid),
                    "added": (-st.st_mtime_ns, aid),
                    "release": (release is None, -(release.toordinal() if release else 0), aid)}}
                files[fid] = aid
            for rel in [r for r in hashes if r not in seen]:
                del hashes[rel]
                dirty = True
            if not initial:
                for aid in apps.keys() - self.apps.keys():
                    self.seq += 1
                    self.journal.append((self.seq, "added", aid))
                for aid in self.apps.keys() - apps.keys():
                    self.seq += 1
                    self.journal.append((self.seq, "removed", aid))
                if len(self.journal) > JOURNAL_LIMIT:
                    self.floor = self.journal[-JOURNAL_LIMIT - 1][0]
                    del self.journal[:-JOURNAL_LIMIT]
            self.apps, self.files = apps, files
            self.scanned = time.monotonic()
            if dirty:
                self.save_state()

    def refresh(self, every):
        if time.monotonic() - self.scanned >= every:
            self.scan()

    # Pages (SPEC.md § 6.2): sorted by key, ties broken by id; a cursor keeps
    # the last key read, so a page after a change neither skips nor repeats.

    def page(self, entries, sort, size, cursor, scope):
        with self.lock:
            if cursor:
                if not cursor.startswith("c_"):
                    raise bad_request("Unknown cursor.")
                kept = self.cursors.get(cursor)
                if kept is None:
                    raise Problem(410, "gone", "Cursor expired", "Read the list again from its start.")
                if kept[0] != (sort, scope):
                    raise bad_request("This cursor belongs to another listing.")
                after = kept[1]
            ordered = sorted(entries, key=lambda e: e["keys"][sort])
            if cursor:
                ordered = [e for e in ordered if e["keys"][sort] > after]
            items, more = ordered[:size], len(ordered) > size
            nxt = None
            if more:
                # The same page always gives the same cursor, so a page keeps its ETag.
                last = items[-1]["keys"][sort]
                nxt = "c_" + b64url(hmac.new(self.secret, json.dumps([sort, scope, last]).encode(), "sha256").digest()[:12])
                self.cursors[nxt] = ((sort, scope), last)
                self.cursors.move_to_end(nxt)
                while len(self.cursors) > CURSOR_LIMIT:
                    self.cursors.popitem(last=False)
            total = len(entries)
        return {"schema": 1, "items": [e["doc"] for e in items], "total": total, "next": nxt}

    def missing(self, installed, want):
        """SPEC.md § 6.3, from the console's installed apps."""
        with self.lock:
            by_app = {e["doc"]["app_id"]: e["doc"] for e in self.apps.values()}
            have = {}
            for item in installed:
                known = by_app.get(item["app_id"])
                title, kind = (known["title_id"], known["type"]) if known else derive(item["app_id"])
                if kind in ("base", "update"):
                    have[title] = max(have.get(title, -1), item["version"])
            ids = {i["app_id"] for i in installed}
            out = []
            for title, version in have.items():
                mine = [e for e in self.apps.values() if e["doc"]["title_id"] == title]
                updates = [e for e in mine if e["doc"]["type"] == "update"]
                newest = max((e["doc"]["version"] for e in updates), default=-1)
                if "update" in want and newest > version:
                    out += [e for e in updates if e["doc"]["version"] == newest]
                if "dlc" in want:
                    out += [e for e in mine if e["doc"]["type"] == "dlc" and e["doc"]["app_id"] not in ids]
            if "base" in want:
                out += [e for e in self.apps.values() if e["doc"]["type"] == "base" and e["doc"]["title_id"] not in have]
            return out

    def changes(self, since):
        with self.lock:
            current = f"s_{self.epoch}_{self.seq}"
            if since is None:
                return {"schema": 1, "added": [], "removed": [], "since": current}
            m = re.fullmatch(r"s_([0-9a-f]{8})_(\d+)", since)
            if not m:
                raise bad_request("Unknown since token.")
            seq = int(m.group(2))
            if m.group(1) != self.epoch or seq < self.floor or seq > self.seq:
                raise Problem(410, "gone", "Token too old", "Read the whole library again.")
            added, removed = set(), set()
            for s, kind, aid in self.journal:
                if s > seq:
                    (added if kind == "added" else removed).add(aid)
            docs = sorted((self.apps[a] for a in added if a in self.apps), key=lambda e: e["keys"]["name"])
            return {"schema": 1, "added": [e["doc"] for e in docs],
                    "removed": sorted(a for a in removed if a not in self.apps), "since": current}


# --- Accounts -----------------------------------------------------------

def hash_password(password, iterations=600000):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2-sha256${iterations}${b64url(salt)}${b64url(digest)}"


def check_password(password, stored):
    try:
        algo, iterations, salt, digest = stored.split("$")
        assert algo == "pbkdf2-sha256"
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), unb64url(salt), int(iterations))
        return hmac.compare_digest(got, unb64url(digest))
    except (ValueError, AssertionError):
        return False


def unauthorized(challenge, detail):
    return Problem(401, "unauthorized", "Unauthorized", detail, {"WWW-Authenticate": challenge})


CHALLENGE = 'Bearer realm="lantern"'


class Accounts:
    """users.json (SPEC.md § 5): who may sign in on /pair, and with which scopes."""

    def __init__(self, path):
        self.public, self.users = True, {}
        self.pairing = path is not None     # a server with accounts pairs (a private one MUST)
        if path is None:
            return
        doc = read_versioned(Path(path), "users file")
        self.public = bool(doc and doc.get("public"))   # unreadable or newer: private, nobody signs in
        for u in (doc or {}).get("users", []):
            if isinstance(u, dict) and isinstance(u.get("name"), str) and isinstance(u.get("password"), str):
                self.users[u["name"]] = u

    def anonymous(self):
        return {"state": "anonymous", "scopes": ["library"] if self.public else []}

    def scopes(self, user):
        return [s for s in user.get("scopes", []) if s in SCOPES]

    def sign_in(self, name, password):
        """The user, when the password is theirs; None otherwise."""
        user = self.users.get(name)
        ok = check_password(password, user["password"] if user else NO_USER)
        return user if ok and user else None

    def resolve(self, header, tokens):
        """The caller's account from its bearer token, or a 401 Problem (SPEC.md § 5.1)."""
        if not header:
            return self.anonymous()
        scheme, _, value = header.strip().partition(" ")
        if scheme.lower() != "bearer" or not value.strip():
            raise unauthorized(CHALLENGE, "Send a token from pairing: Authorization: Bearer <token>.")
        record = tokens.find(value.strip())
        user = self.users.get(record["user"]) if record else None
        if user is None:
            raise unauthorized(CHALLENGE + ', error="invalid_token"', "Unknown, revoked or expired token.")
        mine = self.scopes(user)
        scopes = [s for s in record.get("scopes", []) if s in mine]
        state = "frozen" if user.get("state") == "frozen" else "active"
        return {"name": clip(user["name"]), "state": state, "scopes": scopes}


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Tokens:
    """Device tokens (SPEC.md § 5.1), hashed, in the state file under "tokens":
    {sha256 of the token: {"user", "device", "scopes", "created", "expires"?}}."""

    def __init__(self, store):
        self.store = store      # the Library: its state, lock and state file

    def table(self):
        tokens = self.store.state.get("tokens")
        if not isinstance(tokens, dict):
            tokens = self.store.state["tokens"] = {}
        return tokens

    def issue(self, user, device, scopes, lifetime=None):
        token = "et_" + secrets.token_urlsafe(32)   # 256 bits
        record = {"user": user, "device": device, "scopes": list(scopes), "created": now_utc()}
        if lifetime:
            record["expires"] = now_utc(lifetime)
        with self.store.lock:
            self.store.reload_tokens()
            self.table()[token_hash(token)] = record
            self.store.save_state()
        return token

    def find(self, token):
        self.store.reload_tokens()
        with self.store.lock:
            record = self.table().get(token_hash(token))
        if not isinstance(record, dict) or not isinstance(record.get("user"), str):
            return None
        expires = record.get("expires")
        if expires is not None:
            try:
                if datetime.fromisoformat(str(expires).replace("Z", "+00:00")) <= datetime.now(timezone.utc):
                    return None
            except ValueError:
                return None     # an expiry it cannot read: not trusted
        return record


class Pairing:
    """Pairings waiting for the user (SPEC.md § 5.2), in memory: a code lives
    PAIR_EXPIRES seconds, a token is collected once."""

    def __init__(self, tokens, accounts, interval=PAIR_INTERVAL, expires=PAIR_EXPIRES, lifetime=None):
        self.tokens, self.accounts = tokens, accounts
        self.interval, self.expires, self.lifetime = interval, expires, lifetime
        self.pending, self.lock = {}, threading.Lock()

    def purge(self):
        now = time.monotonic()
        for pid in [p for p, e in self.pending.items() if e["until"] <= now]:
            del self.pending[pid]

    def start(self, device, scopes):
        with self.lock:
            self.purge()
            if len(self.pending) >= PENDING_LIMIT:
                raise slow_down(self.interval, "Too many pairings are waiting; try again later.")
            codes = {e["code"] for e in self.pending.values()}
            while (code := "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_SYMBOLS))) in codes:
                pass
            pid = "p_" + secrets.token_urlsafe(24)  # 192 bits: whoever has it collects the token
            entry = {"pid": pid, "code": code, "device": device, "scopes": scopes, "state": "pending",
                     "until": time.monotonic() + self.expires, "polled": None, "interval": self.interval}
            self.pending[pid] = entry
            return entry

    @staticmethod
    def shown(code):
        return "-".join(code[i:i + 4] for i in range(0, len(code), 4))

    def by_code(self, typed):
        code = re.sub(r"[\s-]", "", typed or "").upper()
        with self.lock:
            self.purge()
            return next((e for e in self.pending.values()
                         if e["state"] == "pending" and hmac.compare_digest(e["code"], code)), None)

    def by_nonce(self, nonce):
        with self.lock:
            self.purge()
            return next((e for e in self.pending.values() if e["state"] == "pending" and e.get("nonce")
                         and hmac.compare_digest(e["nonce"], nonce or "")), None)

    def grant(self, entry, user):
        """The scopes the user may approve: those asked for that the account has."""
        mine = self.accounts.scopes(user)
        return [s for s in entry["scopes"] if s in mine]

    def prepare(self, entry, user):
        """Ties the code to the signed-in user until they approve or refuse it on /pair."""
        with self.lock:
            entry["user"], entry["nonce"] = user["name"], secrets.token_urlsafe(24)
            return entry["nonce"]

    def approve(self, entry, user_name):
        user = self.accounts.users[user_name]
        scopes = self.grant(entry, user)
        token = self.tokens.issue(user_name, entry["device"], scopes, self.lifetime)
        with self.lock:
            entry.update(state="approved", token=token, granted=scopes, nonce=None)

    def refuse(self, entry):
        with self.lock:
            entry.update(state="refused", nonce=None)

    def poll(self, pid):
        """The token document once approved, None while waiting; 410 or 429 as a Problem."""
        with self.lock:
            self.purge()
            entry = self.pending.get(pid)
            if entry is None:
                raise Problem(410, "gone", "Pairing gone", "Refused, expired, already collected or unknown.")
            now = time.monotonic()
            if entry["polled"] is not None and now - entry["polled"] < entry["interval"] * 0.8:
                entry["polled"] = now
                raise slow_down(entry["interval"], f"Poll every {entry['interval']} seconds.")
            entry["polled"] = now
            if entry["state"] == "refused":
                del self.pending[pid]
                raise Problem(410, "gone", "Pairing refused", "The user refused this device.")
            if entry["state"] != "approved":
                return None
            del self.pending[pid]
        doc = {"schema": 1, "token": entry["token"], "scopes": entry["granted"]}
        if self.lifetime:
            doc["expires"] = int(self.lifetime)
        return doc


# --- HTTP ---------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"LanternReference/{VERSION}"

    def version_string(self):
        return self.server_version

    def log_message(self, fmt, *args):
        if not self.server.quiet:
            super().log_message(fmt, *args)

    # Dispatch. Every route's family decides who may call it.

    def handle_any(self, method):
        self.method, self.head, self.began = method, method == "HEAD", False
        self.authenticated = bool(self.headers.get("Authorization"))
        try:
            body = self.read_body()
            url = urlsplit(self.path)
            path = unquote(url.path)
            query = {k: v[-1] for k, v in parse_qs(url.query, keep_blank_values=True).items()}
            self.server.library.refresh(self.server.rescan)
            self.route(method, path, query, body)
        except Problem as p:
            self.send_doc(p.status, p.document(), p.headers, problem=True)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:  # noqa: BLE001 - any bug of this server answers 500
            # A bug of this server: logged, answered as SPEC.md § 10 wants,
            # unless the reply had already begun.
            self.log_error("%s", traceback.format_exc())
            self.close_connection = True
            if not self.began:
                problem = Problem(500, "internal", "Internal error", "The server failed; try again later.")
                self.send_doc(500, problem.document(), problem=True)

    def do_GET(self):
        self.handle_any("GET")

    def do_HEAD(self):
        self.handle_any("HEAD")

    def do_POST(self):
        self.handle_any("POST")

    def do_PUT(self):
        self.handle_any("PUT")

    def do_DELETE(self):
        self.handle_any("DELETE")

    def do_PATCH(self):
        self.handle_any("PATCH")

    def read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.close_connection = True
            raise bad_request("Bad Content-Length.") from None
        if length > BODY_LIMIT:
            self.close_connection = True
            raise Problem(413, "too_large", "Too large", f"A request document is {BODY_LIMIT} bytes at most.")
        return self.rfile.read(length) if length > 0 else b""

    def route(self, method, path, query, body):
        v1 = BASE + "/v1"
        routes = [
            (("/.well-known/lantern", v1, v1 + "/"), ("GET", "HEAD"), None, self.handshake),
            ((v1 + "/pairing",), ("POST",), "pairing", self.pair_start),
            ((v1 + "/apps",), ("GET", "HEAD"), "library", self.apps),
            ((v1 + "/apps/missing",), ("POST",), "library", self.missing),
            ((v1 + "/changes",), ("GET", "HEAD"), "changes", self.changes),
        ]
        if path == "/pair":
            return self.pair_page(method, body)
        prefixes = [(v1 + "/pairing/", ("GET",), "pairing", self.pair_poll),
                    (v1 + "/titles/", ("GET", "HEAD"), "media", self.title),
                    (v1 + "/files/", ("GET", "HEAD"), "library", self.file)]
        for paths, methods, family, fn in routes:
            if path in paths:
                return self.call(method, methods, family, fn, query, body)
        for prefix, methods, family, fn in prefixes:
            rest = path[len(prefix):] if path.startswith(prefix) else ""
            if rest and "/" not in rest:
                return self.call(method, methods, family, lambda q, b, fn=fn, rest=rest: fn(rest, q, b), query, body)
        raise Problem(404, "not_found", "Not found", "No such route on this server.")

    def call(self, method, methods, family, fn, query, body):
        account = self.server.accounts.resolve(self.headers.get("Authorization"), self.server.tokens)
        if method not in methods:
            raise Problem(405, "bad_request", "Method not allowed", None, {"Allow": ", ".join(methods)})
        if family:
            self.allow(account, family)
        fn(query, body) if family else fn(account)

    def allow(self, account, family):
        if family == "pairing":     # anyone may ask to pair (SPEC.md § 4.2, § 5.2)
            if not self.server.accounts.pairing:
                raise Problem(404, "not_found", "Not found", "This server does not pair.")
            return
        if account["state"] == "anonymous" and not self.server.accounts.public:
            raise unauthorized(CHALLENGE, "This server asks for a token: pair this device first.")
        if account["state"] == "frozen":
            raise Problem(403, "account_frozen", "Account frozen", "This account may do nothing for now.")
        if SCOPE_OF[family] not in account["scopes"]:
            raise Problem(403, "forbidden", "Forbidden", f"This account lacks the scope {SCOPE_OF[family]}.")

    def features(self, account):
        def offered(family):
            try:
                self.allow(account, family)
                return OFFERED[family]
            except Problem:
                return 0
        features = {f: offered(f) if f in OFFERED else 0 for f in FAMILIES}
        features["pairing"] = 1 if self.server.accounts.pairing else 0
        return features

    # Routes.

    def handshake(self, account):
        doc = {"schema": 1, "uid": self.server.library.uid, "name": self.server.name,
               "software": {"name": "Lantern reference server", "version": VERSION},
               "base": BASE, "versions": [1], "account": account,
               "features": self.features(account), "limits": {"page_size": PAGE_LIMIT}}
        self.send_doc(200, doc)

    def listing_args(self, query):
        sort = query.get("sort") or "name"
        if sort not in ("name", "added", "release"):
            raise bad_request("sort is name, added or release.")
        size = query.get("page_size") or str(PAGE_DEFAULT)
        if not size.isdigit() or int(size) < 1:
            raise bad_request("page_size is a positive integer.")
        return sort, min(int(size), PAGE_LIMIT), query.get("cursor")

    def apps(self, query, body):
        kind, title_id, q = query.get("type"), query.get("title_id"), query.get("q")
        if kind is not None and kind not in APP_TYPES:
            raise bad_request("type is base, update or dlc.")
        if title_id is not None and not ID16.match(title_id):
            raise bad_request("title_id is 16 upper-case hex digits.")
        sort, size, cursor = self.listing_args(query)
        lib = self.server.library
        with lib.lock:
            entries = [e for e in lib.apps.values()
                       if (kind is None or e["doc"]["type"] == kind)
                       and (title_id is None or e["doc"]["title_id"] == title_id)
                       and (not q or q.casefold() in e["doc"]["name"].casefold())]
            self.send_doc(200, lib.page(entries, sort, size, cursor, ("apps", kind, title_id, q)))

    def missing(self, query, body):
        doc = self.request_document(body)
        installed, want = doc.get("installed"), doc.get("want")
        if not (isinstance(installed, list) and all(
                isinstance(i, dict) and ID16.match(str(i.get("app_id", "")))
                and isinstance(i.get("version"), int) and not isinstance(i.get("version"), bool)
                and 0 <= i["version"] < 1 << 32 for i in installed)):
            raise bad_request("installed is a list of {app_id, version}.")
        if not (isinstance(want, list) and want and all(w in APP_TYPES for w in want)):
            raise bad_request("want lists base, update or dlc.")
        sort, size, cursor = self.listing_args(query)
        lib = self.server.library
        scope = ("missing", hashlib.sha256(json.dumps([installed, sorted(set(want))], sort_keys=True).encode()).hexdigest())
        with lib.lock:
            self.send_doc(200, lib.page(lib.missing(installed, set(want)), sort, size, cursor, scope))

    def request_document(self, body):
        """A client's JSON document: 400 when malformed, 422 for a schema this server cannot read."""
        if (self.headers.get("Content-Type") or "").split(";")[0].strip().lower() != "application/json":
            raise bad_request("The body is application/json.")
        try:
            doc = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise bad_request("The body is not JSON.") from None
        if not isinstance(doc, dict) or not isinstance(doc.get("schema"), int) or isinstance(doc["schema"], bool) \
                or doc["schema"] < 1:
            raise bad_request("The body is an object with an integer schema.")
        if doc["schema"] > 1:
            raise Problem(422, "unsupported_schema", "Unsupported schema",
                          f"This server reads schema 1 here, not {doc['schema']}.")
        return doc

    def changes(self, query, body):
        self.send_doc(200, self.server.library.changes(query.get("since")))

    def title(self, title_id, query, body):
        lib = self.server.library
        with lib.lock:
            mine = [e for e in lib.apps.values() if e["doc"]["title_id"] == title_id]
        if not mine:
            raise Problem(404, "not_found", "Not found", "No such title here.")
        main = min(mine, key=lambda e: (e["doc"]["type"] != "base", e["keys"]["name"]))
        doc = {"schema": 1, "title_id": title_id, "name": main["doc"]["name"]}
        release = min((e["keys"]["release"] for e in mine), default=(True,))
        if not release[0]:
            doc["release"] = date.fromordinal(-release[1]).isoformat()
        self.send_doc(200, doc)

    # Pairing (SPEC.md § 5.2).

    def origin(self):
        host = self.headers.get("Host") or ""
        if not re.fullmatch(r"[A-Za-z0-9.\-]+(:\d+)?|\[[0-9A-Fa-f:.]+\](:\d+)?", host):
            host = f"{self.server.server_address[0]}:{self.server.server_address[1]}"
        return f"{'https' if self.server.tls else 'http'}://{host}"

    def pair_start(self, query, body):
        doc = self.request_document(body)
        device, scopes = doc.get("device"), doc.get("scopes")
        if not (isinstance(device, str) and device.strip() and len(device.encode()) <= 512
                and not any(ord(c) < 32 or ord(c) == 127 for c in device)):
            raise bad_request("device is the device's name, 512 bytes at most, without control characters.")
        if not (isinstance(scopes, list) and all(isinstance(x, str) for x in scopes)):
            raise bad_request("scopes is a list of scopes.")
        known = [x for x in SCOPES if x in scopes]     # the ones this server knows, without repeats
        if not known:
            raise bad_request("scopes names none of " + ", ".join(SCOPES) + ".")
        wait = self.server.pair_limiter.hit(self.client_address[0])
        if wait:
            raise slow_down(wait, "Too many pairing requests from this address.")
        entry = self.server.pairing.start(device.strip(), known)
        self.send_doc(200, {"schema": 1, "code": Pairing.shown(entry["code"]), "verify": self.origin() + "/pair",
                            "poll": f"{BASE}/v1/pairing/{entry['pid']}", "interval": entry["interval"],
                            "expires": int(self.server.pairing.expires)}, {"Cache-Control": "no-store"})

    def pair_poll(self, pid, query, body):
        doc = self.server.pairing.poll(pid)
        if doc is None:
            self.send_head(202, 0, {"Cache-Control": "no-store"})
        else:
            self.send_doc(200, doc, {"Cache-Control": "no-store"})

    def pair_page(self, method, body):
        """/pair: where a user signs in, enters the console's code and approves it.
        A password is typed here only, never on the console (SPEC.md § 5.2)."""
        if not self.server.accounts.pairing:
            raise Problem(404, "not_found", "Not found", "This server does not pair.")
        if method not in ("GET", "HEAD", "POST"):
            raise Problem(405, "bad_request", "Method not allowed", None, {"Allow": "GET, HEAD, POST"})
        if method != "POST":
            return self.send_page(200, self.pair_form())
        if not self.server.tls and not is_loopback(self.client_address[0]):
            return self.send_page(403, "<p>Sign in only over HTTPS.</p>")
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/x-www-form-urlencoded":
            return self.send_page(400, self.pair_form("The form was not sent as a form."))
        form = {k: v[-1] for k, v in parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).items()}
        pairing = self.server.pairing
        if "nonce" in form:
            entry = pairing.by_nonce(form["nonce"])
            if entry is None:
                return self.send_page(410, self.pair_form("This pairing expired; ask the console for a new code."))
            if form.get("decision") == "approve":
                pairing.approve(entry, entry["user"])
                return self.send_page(200, f"<p>{html.escape(entry['device'])} is paired. "
                                           "The console finishes on its own.</p>")
            pairing.refuse(entry)
            return self.send_page(200, f"<p>{html.escape(entry['device'])} was refused.</p>")
        ip = self.client_address[0]
        wait = self.server.attempts.wait(ip)
        if wait:
            return self.send_page(429, self.pair_form("Too many attempts; try again later."),
                                  {"Retry-After": str(wait)})
        user = self.server.accounts.sign_in(form.get("name", ""), form.get("password", ""))
        if user is None:
            self.server.attempts.record(ip)
            return self.send_page(403, self.pair_form("Wrong name or password."))
        if user.get("state") == "frozen":
            return self.send_page(403, self.pair_form("This account is frozen."))
        entry = pairing.by_code(form.get("code", ""))
        if entry is None:
            self.server.attempts.record(ip)
            return self.send_page(400, self.pair_form("No such code, or it expired."))
        nonce = pairing.prepare(entry, user)
        scopes = ", ".join(pairing.grant(entry, user)) or "none"
        return self.send_page(200, f"""<p>Pair <strong>{html.escape(entry['device'])}</strong> with
<strong>{html.escape(user['name'])}</strong>'s account, for: {html.escape(scopes)}?</p>
{self.fingerprint()}
<form method="post" action="/pair">
<input type="hidden" name="nonce" value="{html.escape(nonce)}">
<button name="decision" value="approve">Approve</button> <button name="decision" value="refuse">Refuse</button>
</form>""")

    def fingerprint(self):
        if not self.server.spki:
            return "<p>Plain HTTP on loopback: no key to compare.</p>"
        return (f"<p>This server's key: <code>{short_fingerprint(self.server.spki)}</code>. "
                "The console shows the same next to its code: approve only if they match.</p>")

    def pair_form(self, error=None):
        note = f'<p class="error">{html.escape(error)}</p>' if error else ""
        return f"""{note}<p>Sign in, then enter the code your console shows.</p>
{self.fingerprint()}
<form method="post" action="/pair">
<p><label>Name <input name="name" autocomplete="username" required></label></p>
<p><label>Password <input name="password" type="password" autocomplete="current-password" required></label></p>
<p><label>Code <input name="code" autocomplete="off" autocapitalize="characters" required></label></p>
<p><button>Continue</button></p>
</form>"""

    def send_page(self, status, content, headers=None):
        title = html.escape(self.server.name)
        body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>Pair a device · {title}</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:32rem;margin:2rem auto;padding:0 1rem}}
code{{font-size:1.1em}}.error{{color:#b00020}}input{{font:inherit}}</style></head>
<body><h1>Pair a device</h1><p>{title}</p>
{content}
</body></html>
""".encode()
        self.send_head(status, len(body), {
            **(headers or {}), "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
                                       "frame-ancestors 'none'; base-uri 'none'",
            "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer"})
        if not self.head:
            self.wfile.write(body)

    # Files (SPEC.md § 6.7).

    def file(self, fid, query, body):
        lib = self.server.library
        with lib.lock:
            entry = lib.apps.get(lib.files.get(fid, ""))
        if entry is None:
            raise Problem(404, "not_found", "Not found", "No such file; read the app again.")
        doc, size = entry["doc"], entry["doc"]["size"]
        etag = f'"{doc["sha256"][:32]}"'
        start, end = 0, size - 1
        status = 200
        rng = self.headers.get("Range")
        if_range = self.headers.get("If-Range")
        if rng and (if_range is None or if_range == etag):
            parsed = parse_range(rng, size)
            if parsed == "unsatisfiable":
                raise Problem(416, "bad_request", "Range not satisfiable", f"The file is {size} bytes.",
                              {"Content-Range": f"bytes */{size}"})
            if parsed:
                start, end = parsed
                status = 206
        headers = {"Content-Type": "application/octet-stream", "Accept-Ranges": "bytes", "ETag": etag,
                   "Repr-Digest": f"sha-256=:{base64.b64encode(bytes.fromhex(doc['sha256'])).decode()}:"}
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        length = end - start + 1 if size else 0
        self.send_head(status, length, headers)
        if self.head or not length:
            return
        with entry["path"].open("rb") as f:
            f.seek(start)
            while length > 0:
                chunk = f.read(min(CHUNK, length))
                if not chunk:  # the file shrank under us: cut the connection rather than lie
                    self.close_connection = True
                    return
                self.wfile.write(chunk)
                length -= len(chunk)

    # Responses.

    def send_head(self, status, length, headers):
        self.began = True
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(length))
        self.send_header("Vary", "Authorization")
        if "Cache-Control" not in headers:
            self.send_header("Cache-Control", "private" if self.authenticated else "no-cache")
        self.end_headers()

    def send_doc(self, status, doc, headers=None, problem=False):
        body = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()
        headers = dict(headers or {})
        headers["Content-Type"] = "application/problem+json" if problem else "application/json"
        if status == 200 and self.method in ("GET", "HEAD"):
            etag = '"' + hashlib.sha256(body).hexdigest()[:32] + '"'
            headers["ETag"] = etag
            if etag in [t.strip() for t in (self.headers.get("If-None-Match") or "").split(",")]:
                self.send_head(304, 0, {"ETag": etag})
                return
        self.send_head(status, len(body), headers)
        if not self.head:
            self.wfile.write(body)


def parse_range(header, size):
    """(start, end) of a single byte range, "unsatisfiable", or None to ignore it (RFC 9110 § 14)."""
    m = re.fullmatch(r"\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*", header)
    if not m or (m.group(1) == "" and m.group(2) == ""):
        return None  # another unit, several ranges or nonsense: the whole file
    if m.group(1) == "":
        n = int(m.group(2))
        return (max(0, size - n), size - 1) if n and size else "unsatisfiable"
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else size - 1
    if m.group(2) and end < start:
        return None  # invalid: ignored
    if start >= size:
        return "unsatisfiable"
    return start, min(end, size - 1)


class LanternServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, library, accounts, name="Lantern reference server", rescan=30.0,
                 quiet=False, handler=Handler, tls=None, spki=None, token_lifetime=None):
        """`tls`: an ssl.SSLContext; without it, only a loopback address (SPEC.md § 2).
        `spki`: the SHA-256 of the certificate's key, for /pair (SPEC.md § 5.3)."""
        if tls is None and not is_loopback(address[0]):
            raise ValueError(f"plain HTTP only on a loopback address, not {address[0] or 'every address'}: "
                             "give --tls-cert and --tls-key (SPEC.md § 2)")
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, handler)
        if tls is not None:
            # The handshake happens in the request's thread, not in the accepting one.
            self.socket = tls.wrap_socket(self.socket, server_side=True, do_handshake_on_connect=False)
        self.tls, self.spki = tls is not None, spki
        self.library, self.accounts, self.name = library, accounts, name
        self.rescan, self.quiet = rescan, quiet
        self.tokens = Tokens(library)
        self.pairing = Pairing(self.tokens, accounts, lifetime=token_lifetime)
        self.pair_limiter = Limiter(*PAIR_RATE)
        self.attempts = Limiter(*PAIR_ATTEMPTS)


def discovery(server, port, http_port):
    """Answer Lantern's discovery datagram on UDP (SPEC.md § 4.1)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", port))
    limiter = Limiter(5, 1.0)

    def loop():
        while True:
            try:
                data, peer = sock.recvfrom(DATAGRAM_LIMIT + 1)
            except OSError:
                return  # closed
            reply = discovery_reply(server, http_port, data, peer[0], limiter)
            if reply:
                try:
                    sock.sendto(reply, peer)
                except OSError:
                    pass

    threading.Thread(target=loop, daemon=True).start()
    return sock


def discovery_reply(server, http_port, data, address, limiter):
    """The reply to one datagram, or None to stay silent."""
    if len(data) > DATAGRAM_LIMIT:
        return None
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return None
    if ip.is_global:
        return None     # not from a local network
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not (isinstance(doc, dict) and type(doc.get("schema")) is int and doc["schema"] == 1
            and doc.get("lantern") == "discover"):
        return None     # not a request this server can read (SPEC.md § 3.2)
    if limiter.hit(address):
        return None
    reply = {"schema": 1, "lantern": "server", "uid": server.library.uid, "name": clip(server.name),
             "port": http_port, "base": BASE, "versions": [1]}
    return json.dumps(reply, ensure_ascii=False, separators=(",", ":")).encode()


def tokens_command(state_path, revoke):
    """--tokens and --revoke: the state file's tokens, listed or one revoked."""
    doc = read_versioned(Path(state_path), "state")
    if doc is None:
        sys.exit(f"{state_path}: no state this server can write (absent, unreadable or newer)")
    tokens = doc.get("tokens") if isinstance(doc.get("tokens"), dict) else {}
    if revoke is None:
        for key, t in sorted(tokens.items(), key=lambda kv: str(kv[1].get("created", ""))):
            print(f"{key[:12]}  {t.get('user')}  {t.get('device')!r}  {', '.join(t.get('scopes', []))}  "
                  f"created {t.get('created')}" + (f", expires {t['expires']}" if t.get("expires") else ""))
        return 0
    found = [k for k in tokens if len(revoke) >= 8 and k.startswith(revoke.lower())]
    if len(found) != 1:
        sys.exit(f"--revoke {revoke}: {'no' if not found else 'more than one'} token with this id")
    del tokens[found[0]]
    doc["tokens"] = tokens
    tmp = Path(state_path).with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    tmp.replace(state_path)
    print(f"revoked {found[0][:12]}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m server", description="Lantern reference server.")
    p.add_argument("--library", help="the folder of packages")
    p.add_argument("--host", default="127.0.0.1",
                   help="address to listen on (default 127.0.0.1; any other needs --tls-cert and --tls-key)")
    p.add_argument("--port", type=int, default=8080, help="TCP port (default 8080; 0: any)")
    p.add_argument("--name", default="Lantern reference server", help="the name the handshake shows")
    p.add_argument("--users", help="accounts file; without it the server is public and does not pair")
    p.add_argument("--state", help="state file (default <library>/.lantern-state.json)")
    p.add_argument("--rescan", type=float, default=30.0, help="seconds between library scans (0: every request)")
    p.add_argument("--tls-cert", help="certificate chain (PEM); with --tls-key, HTTPS")
    p.add_argument("--tls-key", help="private key (PEM)")
    p.add_argument("--token-days", type=float, help="new tokens expire after this many days (default: never)")
    p.add_argument("--tokens", action="store_true", help="list the paired devices' tokens, then exit")
    p.add_argument("--revoke", metavar="ID", help="revoke a token (its id from --tokens), then exit")
    p.add_argument("--discovery", action="store_true", help="answer LAN discovery on UDP")
    p.add_argument("--discovery-port", type=int, default=DISCOVERY_PORT)
    p.add_argument("--quiet", action="store_true", help="no request log")
    p.add_argument("--hash-password", action="store_true", help="print a password's hash for --users")
    args = p.parse_args(argv)
    if args.hash_password:
        password = getpass.getpass("Password: ") if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
        print(hash_password(password))
        return 0
    if args.tokens or args.revoke:
        if not (args.state or args.library):
            p.error("--tokens and --revoke need --state or --library")
        return tokens_command(args.state or Path(args.library) / ".lantern-state.json", args.revoke)
    if not args.library or not Path(args.library).is_dir():
        p.error("--library DIR: a folder of packages")
    if bool(args.tls_cert) != bool(args.tls_key):
        p.error("--tls-cert and --tls-key go together")
    tls = spki = None
    if args.tls_cert:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(args.tls_cert, args.tls_key)
        spki = spki_sha256(Path(args.tls_cert).read_text(encoding="ascii"))
    library = Library(args.library, args.state or Path(args.library) / ".lantern-state.json")
    lifetime = args.token_days * 86400 if args.token_days else None
    try:
        server = LanternServer((args.host, args.port), library, Accounts(args.users), args.name, args.rescan,
                               args.quiet, tls=tls, spki=spki, token_lifetime=lifetime)
    except ValueError as e:
        p.error(str(e))
    port = server.server_address[1]
    if args.discovery:
        discovery(server, args.discovery_port, port)
    log(f"{len(library.apps)} app(s) from {library.root}, "
        f"{'public' if server.accounts.public else 'private'}, uid {library.uid}")
    scheme = "https" if tls else "http"
    if tls:
        log(f"key {short_fingerprint(spki)} (SPKI SHA-256 {spki})")
    else:
        log("plain HTTP on loopback: for local testing only (SPEC.md § 2)")
    if server.accounts.pairing:
        log(f"pairing: approve devices at {scheme}://{args.host}:{port}/pair")
    log(f"listening on {scheme}://{args.host}:{port}{BASE}/v1/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
