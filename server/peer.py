"""Lantern reference peer (SPEC.md § 19.4): a paired console's profile for
sharing, the files it holds served to the other devices of its network by
their SHA-256, to the holders of a grant of its server.

    python3 -m server.peer --folder DIR --server URL [--token T --key FILE] [--cafile CA]
        [--host 127.0.0.1] [--port 47116] [--slots 2] [--name NAME] [--discovery] [--dns-sd]

It reads the server's handshake (its uid and `peers.key`, the key its grants
verify by), then its apps' and homebrew's listings, with the token and its
device key when the server is private: of DIR's files, it serves only those
whose size and SHA-256 are an app's or a homebrew package's of that server
(never a save, a key or anything named by a path). It serves:

    GET <base>/v1/blobs/sha256/<hex>     Lantern-Grant: <grant>

as a file (§ 6.6: ranges, ETag, Repr-Digest), and HEAD alike; a grant that
does not verify, names another file or another server, or expired gives
403; a file it does not hold 404; beyond `--slots` downloads at once, or a
few requests a second from one address, 429. It answers its own networks
only (not a global address). With --discovery it answers Lantern's discovery
datagram when it asks for peers (`"peers": true`, § 19.5), and with --dns-sd
it advertises `_lantern-peer._tcp`.

Plain HTTP on a loopback or private address (a peer's grants are worth one
file for a few minutes, § 19.4); give --tls-cert and --tls-key elsewhere.
Standard library only; a reference, not a product. Peer(…) runs one in a
program, as the tests do.
"""
import argparse
import base64
import ipaddress
import json
import re
import socket
import ssl
import sys
import threading
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    from server import ed25519, mdns, signatures
    from server import lantern_server as ls
except ImportError:     # run as server/peer.py
    import ed25519
    import lantern_server as ls
    import mdns
    import signatures

BASE = "/lantern"
PORT = 47116
SLOTS = 2
RATE = (10, 1.0)        # requests per address, per second


def local(address):
    """An address of this device's networks: loopback, private or link-local, never a global one."""
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    return ip.is_loopback or any(ip in net for net in ls.PRIVATE_NETS)


class PeerHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = f"LanternReferencePeer/{ls.VERSION}"

    def version_string(self):
        return self.server_version

    def setup(self):
        super().setup()
        try:    # no wait for the client's delayed ACK between the headers and the file (Nagle)
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

    def log_message(self, fmt, *args):
        if not self.server.quiet:
            super().log_message(fmt, *args)

    def do_GET(self):
        self.serve()

    def do_HEAD(self):
        self.serve()

    def problem(self, status, code, title, detail, headers=None):
        doc = ls.Problem(status, code, title, detail).document(ls.best_language(ls.languages(
            self.headers.get("Accept-Language"))))
        body = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(status)
        for k, v in {**(headers or {}), "Content-Type": "application/problem+json", "Content-Length": str(len(body)),
                     "Cache-Control": "no-store", "Content-Language": doc["language"]}.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def serve(self):
        peer = self.server
        if not local(self.client_address[0]):
            return self.problem(403, "forbidden", "Forbidden", "A peer answers its own networks only.")
        wait = peer.limiter.hit(self.client_address[0])
        if wait:
            return self.problem(429, "slow_down", "Slow down", "Too many requests from this address.",
                                {"Retry-After": str(wait)})
        m = re.fullmatch(re.escape(peer.base) + r"/v1/blobs/sha256/([0-9a-f]{64})", self.path.split("?", 1)[0])
        if not m:
            return self.problem(404, "not_found", "Not found", "A peer serves /v1/blobs/sha256/<hex> alone.")
        sha = m.group(1)
        grant = ls.read_grant(self.headers.get("Lantern-Grant"), peer.keys)
        if grant is None or grant["sha256"] != sha:
            return self.problem(403, "forbidden", "Forbidden", "A grant of a server this peer paired with, for this "
                                "file, not expired (SPEC.md § 19.4).")
        held = peer.files.get(sha)
        if held is None or held["size"] != grant["size"]:
            return self.problem(404, "not_found", "Not found", "This peer does not hold that file.")
        if not peer.take():
            return self.problem(429, "slow_down", "Slow down", f"{peer.slots} downloads at once at most.",
                                {"Retry-After": "5"})
        try:
            self.send_file(held["path"], held["size"], sha)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True        # the client went away mid-file: its slot is free again
        finally:
            peer.release()

    def send_file(self, path, size, sha256):
        etag = f'"{sha256[:32]}"'
        start, end, status = 0, size - 1, 200
        rng = self.headers.get("Range")
        if rng and self.headers.get("If-Range") in (None, etag):
            parsed = ls.parse_range(rng, size)
            if parsed == "unsatisfiable":
                return self.problem(416, "bad_request", "Range not satisfiable", f"The file is {size} bytes.",
                                    {"Content-Range": f"bytes */{size}"})
            if parsed:
                (start, end), status = parsed, 206
        length = end - start + 1 if size else 0
        self.send_response(status)
        headers = {"Content-Type": "application/octet-stream", "Accept-Ranges": "bytes", "ETag": etag,
                   "Content-Length": str(length), "Cache-Control": "no-store",
                   "Repr-Digest": f"sha-256=:{base64.b64encode(bytes.fromhex(sha256)).decode()}:"}
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command == "HEAD" or not length:
            return
        with Path(path).open("rb") as f:
            f.seek(start)
            while length > 0:
                chunk = f.read(min(ls.CHUNK, length))
                if not chunk:
                    self.close_connection = True
                    return
                self.wfile.write(chunk)
                length -= len(chunk)


class Peer(ThreadingHTTPServer):
    """A peer on `address`: `files` {sha256: {"path", "size"}} it holds and checked, `keys` {server uid: grant
    key's 32 bytes} of the servers it paired with."""
    daemon_threads = True

    def __init__(self, address, files, keys, slots=SLOTS, name="Lantern peer", base=BASE, tls=None, quiet=True,
                 uid=None):
        if tls is None and not local(address[0]) and address[0] not in ("0.0.0.0", "::"):
            raise ValueError("plain HTTP only on a loopback or private address: give --tls-cert and --tls-key")
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, PeerHandler)
        if tls is not None:
            self.socket = tls.wrap_socket(self.socket, server_side=True, do_handshake_on_connect=False)
        self.files, self.keys, self.slots, self.name, self.base = files, keys, slots, name, base
        self.tls, self.quiet, self.uid = tls is not None, quiet, uid or str(uuid.uuid4())
        self.active, self.lock = 0, threading.Lock()
        self.limiter = ls.Limiter(*RATE)

    def take(self):
        with self.lock:
            if self.active >= self.slots:
                return False
            self.active += 1
            return True

    def release(self):
        with self.lock:
            self.active -= 1

    def reply(self, data, address, limiter):
        """The reply to a discovery datagram (SPEC.md § 19.5): only to one that asks for peers; None otherwise."""
        if len(data) > ls.DATAGRAM_LIMIT or not local(address):
            return None
        try:
            doc = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None
        if not (isinstance(doc, dict) and type(doc.get("schema")) is int and doc["schema"] == 1
                and doc.get("lantern") == "discover" and doc.get("peers") is True) or limiter.hit(address):
            return None
        reply = {"schema": 1, "lantern": "peer", "uid": self.uid, "name": ls.clip(self.name, 256),
                 "port": self.server_address[1], "base": self.base, "tls": self.tls, "slots": self.slots,
                 "servers": sorted(self.keys)[:16]}
        return json.dumps(reply, ensure_ascii=False, separators=(",", ":")).encode()

    def discovery(self, port=ls.DISCOVERY_PORT):
        """Answers discovery datagrams that ask for peers, on UDP `port`; the socket, to close."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind(("", port))
        limiter = ls.Limiter(5, 1.0)

        def loop():
            while True:
                try:
                    data, peer = sock.recvfrom(ls.DATAGRAM_LIMIT + 1)
                except OSError:
                    return
                out = self.reply(data, peer[0], limiter)
                if out:
                    try:
                        sock.sendto(out, peer)
                    except OSError:
                        pass
        threading.Thread(target=loop, daemon=True).start()
        return sock


def held_files(folder, wanted):
    """{sha256: {"path", "size"}} of the files of `folder` whose (sha256, size) is in `wanted`."""
    out = {}
    for path in sorted(Path(folder).rglob("*")):
        if path.is_file() and not any(p.startswith(".") for p in path.relative_to(folder).parts):
            sha, size = ls.sha256_file(path), path.stat().st_size
            if (sha, size) in wanted:
                out[sha] = {"path": path, "size": size}
    return out


def server_files(url, token=None, seed=None, context=None):
    """(uid, grant key, {(sha256, size)} of every app and homebrew package) of a server, read as a client."""
    origin = url.rstrip("/")

    def get(path):
        headers = {"User-Agent": f"LanternReferencePeer/{ls.VERSION}", "Accept": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
            if seed is not None:
                headers.update(signatures.sign(seed, ed25519.public_key(seed), "GET", origin + path,
                                               headers["Authorization"]))
        with urllib.request.urlopen(urllib.request.Request(origin + path, headers=headers), context=context,
                                    timeout=30) as r:
            return json.loads(r.read())

    hello = get("/.well-known/lantern")
    peers = hello.get("peers") or {}
    key = base64.b64decode(peers.get("key", ""))
    if len(key) != 32:
        raise SystemExit("peer: the server gives no peers.key: it offers no grants (SPEC.md § 19.3)")
    base, wanted = hello["base"], set()
    for route in ("apps", "homebrew"):
        if not hello.get("features", {}).get("library" if route == "apps" else "homebrew"):
            continue
        cursor = None
        while True:
            page = get(f"{base}/v1/{route}?page_size=500" + (f"&cursor={cursor}" if cursor else ""))
            for item in page["items"]:
                for f in ([item] if route == "apps" else [item["package"], *item.get("packages", [])]):
                    wanted.add((f["sha256"], f["size"]))
            cursor = page["next"]
            if cursor is None:
                break
    return hello["uid"], key, wanted


def main(argv=None):
    p = argparse.ArgumentParser(prog="python3 -m server.peer", description="Lantern reference peer.")
    p.add_argument("--folder", required=True, help="the files this console holds")
    p.add_argument("--server", required=True, help="its server, e.g. https://shelf.example.org/")
    p.add_argument("--token", help="the device's token, when the server is private")
    p.add_argument("--key", help="the file of the device's key (its 32-byte seed, base64)")
    p.add_argument("--cafile", help="the server's certificate, when no CA vouches for it")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--slots", type=int, default=SLOTS, help="downloads at once, 1 to 8")
    p.add_argument("--name", default=socket.gethostname()[:64] or "Lantern peer")
    p.add_argument("--tls-cert")
    p.add_argument("--tls-key")
    p.add_argument("--discovery", action="store_true", help="answer discovery datagrams that ask for peers")
    p.add_argument("--discovery-port", type=int, default=ls.DISCOVERY_PORT)
    p.add_argument("--dns-sd", action="store_true", help="advertise _lantern-peer._tcp with multicast DNS")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)
    if not 1 <= args.slots <= 8:
        p.error("--slots is 1 to 8")
    seed = base64.b64decode(Path(args.key).read_text().strip()) if args.key else None
    context = ssl.create_default_context(cafile=args.cafile) if args.server.startswith("https:") else None
    uid, key, wanted = server_files(args.server, args.token, seed, context)
    files = held_files(args.folder, wanted)
    tls = None
    if args.tls_cert:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(args.tls_cert, args.tls_key)
    try:
        peer = Peer((args.host, args.port), files, {uid: key}, args.slots, args.name, tls=tls, quiet=args.quiet)
    except ValueError as e:
        p.error(str(e))
    if args.discovery:
        peer.discovery(args.discovery_port)
    if args.dns_sd:
        try:
            mdns.Responder("_lantern-peer._tcp", args.name, peer.server_address[1],
                           {"servers": uid, "path": BASE, "v": "1", "tls": "1" if tls else "0"},
                           "lantern-peer-" + peer.uid[:8]).serve()
        except OSError as e:
            ls.log(f"peer: DNS-SD not available ({e})")
    ls.log(f"peer: {len(files)} file(s) of {uid} shared, on {'https' if tls else 'http'}://{args.host}:"
           f"{peer.server_address[1]}{BASE}/v1/blobs/sha256/")
    try:
        peer.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
