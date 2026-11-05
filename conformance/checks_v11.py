"""The conformance suite's checks of what draft 0.11 asks of a server, from the RFCs it relies on: no protocol
older than TLS 1.2 (SPEC.md § 2), `Strict-Transport-Security` for a server that browsers reach, a `uid` that is a
random UUID of version 4 or 7 in lower case (§ 4.2), and a long lifetime with `immutable` for what an address names by
its SHA-256 (§ 14). A mixin of run.py's Suite, which gives it http, hello, chunked() and the rest, as
checks_v05.py to checks_v09.py are.

What a server shows decides what the suite can see: the TLS and HSTS checks need an HTTPS address and skip on
plain HTTP; the lifetime check needs a library whose files carry chunk indexes (§ 22.1). The rule that a client
offers no protocol older than TLS 1.2 is one only a client keeps, on run.py's list of what the suite cannot see.
"""
import re
import socket
import ssl

# run.py's own (bind() sets them).
Fail = Skip = Blind = Warn = problem_detail = None

UID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[47][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")   # RFC 9562 § 4, versions 4 and 7
HSTS_MIN = 15552000                                                                          # six months, § 2
REFUSED = ("PROTOCOL_VERSION", "HANDSHAKE_FAILURE", "WRONG_VERSION", "NO_PROTOCOLS", "UNSUPPORTED_PROTOCOL")


def bind(**names):
    globals().update(names)


def expect(cond, msg):
    if not cond:
        raise Fail(msg)


class Eleven:
    """Draft 0.11's checks."""

    def c_tls_floor(self):
        if self.origin.scheme != "https":
            raise Skip("plain HTTP: no TLS to look at")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        try:
            ctx.minimum_version, ctx.maximum_version = ssl.TLSVersion.TLSv1, ssl.TLSVersion.TLSv1_1
            ctx.set_ciphers("ALL:@SECLEVEL=0")
        except (ValueError, ssl.SSLError, AttributeError):
            raise Skip("this machine's TLS library cannot offer TLS 1.1 or older") from None
        host, port = self.origin.hostname, self.origin.port or 443
        try:
            with socket.create_connection((host, port), timeout=self.args.timeout) as raw:
                with ctx.wrap_socket(raw, server_hostname=host) as tls:
                    raise Fail(f"the server negotiated {tls.version()}: TLS 1.2 is the oldest it may use")
        except ssl.SSLError as e:
            text = str(e).upper()
            if any(word in text for word in REFUSED):
                return "TLS 1.1 and older refused"
            raise Skip(f"this machine could not tell a refusal from its own limits: {e}") from None
        except ConnectionResetError:
            return "TLS 1.1 and older refused (connection closed)"

    def c_hsts(self):
        if self.origin.scheme != "https":
            raise Skip("plain HTTP: browsers do not reach it in HTTPS")
        r = self.http.request("GET", "/.well-known/lantern", auth="none")
        value = r.header("Strict-Transport-Security")
        if not value:
            raise Fail("no Strict-Transport-Security on /.well-known/lantern")
        age = re.search(r"max-age=(\d+)", value, re.I)
        expect(age and int(age.group(1)) >= HSTS_MIN, f"{value!r}: a max-age of {HSTS_MIN} seconds or more is asked")
        return value

    def c_uid(self):
        uid = self.hello.get("uid", "")
        expect(isinstance(uid, str) and UID.match(uid),
               f"uid {uid!r} is not a lower-case UUID of version 4 or 7 (RFC 9562 § 4)")
        return f"uid {uid}"

    def c_immutable(self):
        files = self.chunked()
        if not files:
            raise Skip("no app or homebrew package read carries chunks")
        bad = []
        for where, doc, platform in files[:3]:
            r = self.http.request("GET", self.file_path(doc["chunks"]["url"]), platform=platform)
            if r.status != 200:
                bad.append(f"{where}: {r}")
                continue
            cc = (r.header("Cache-Control") or "").lower()
            age = re.search(r"max-age=(\d+)", cc)
            if "immutable" not in cc or not age or int(age.group(1)) < 86400:
                bad.append(f"{where}: Cache-Control {cc or 'none'}, no long max-age with immutable")
        if bad:
            raise Fail("\n".join(bad))
        return f"{min(len(files), 3)} chunk index(es) with a long lifetime and immutable"
