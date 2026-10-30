"""A small DNS-SD responder over multicast DNS (RFC 6762, RFC 6763), with the
standard library alone: enough for a Lantern server to advertise itself as
`_lantern._tcp` (SPEC.md § 4.1), and a peer as `_lantern-peer._tcp`
(§ 19.5).

It answers questions for the service type (PTR), its instance (SRV, TXT),
its host name (A) and the list of services (`_services._dns-sd._udp`), on
UDP 5353 by default: by multicast to a querier on port 5353 that does not
ask for a unicast reply, and unicast otherwise (a one-shot query from
another port, RFC 6762 § 6.7, as the conformance suite sends). It announces
itself once when it starts. IPv4 only; one service per responder. Names and
TXT values are cut to DNS's limits (63 bytes a label, 255 a string).
"""
import ipaddress
import socket
import struct
import threading

GROUP = "224.0.0.251"
PORT = 5353
A, PTR, TXT, SRV, ANY = 1, 12, 16, 33, 255
IN, FLUSH, QU = 1, 0x8000, 0x8000
TTL, HOST_TTL, LEGACY_TTL = 4500, 120, 10
SERVICES = "_services._dns-sd._udp.local"


def labels(name):
    return [part for part in name.rstrip(".").split(".") if part]


def encode_name(name):
    """A name's wire form, uncompressed; `name` may hold an instance label with dots escaped as `\\.`."""
    out, part, escaped = b"", "", False
    parts = []
    for c in name.rstrip("."):
        if escaped:
            part += c
            escaped = False
        elif c == "\\":
            escaped = True
        elif c == ".":
            parts.append(part)
            part = ""
        else:
            part += c
    parts.append(part)
    for p in parts:
        raw = p.encode()[:63]
        out += bytes([len(raw)]) + raw
    return out + b"\0"


def decode_name(data, pos, hops=0):
    """(name in lower case, the position after it) of the name at `pos`; ValueError when malformed."""
    parts, end = [], None
    while True:
        if pos >= len(data) or hops > 16:
            raise ValueError("name out of the message")
        n = data[pos]
        if n == 0:
            pos += 1
            break
        if n & 0xC0 == 0xC0:
            if pos + 1 >= len(data):
                raise ValueError("cut pointer")
            target = ((n & 0x3F) << 8) | data[pos + 1]
            if end is None:
                end = pos + 2
            if target >= pos:
                raise ValueError("pointer forward")
            pos, hops = target, hops + 1
            continue
        if n & 0xC0:
            raise ValueError("label type")
        parts.append(data[pos + 1:pos + 1 + n].decode("utf-8", "replace").replace(".", "\\."))
        pos += 1 + n
    return ".".join(parts).lower(), end if end is not None else pos


def record(name, rtype, ttl, rdata, flush=False):
    return encode_name(name) + struct.pack("!HHIH", rtype, IN | (FLUSH if flush else 0), ttl, len(rdata)) + rdata


def txt_data(txt):
    out = b""
    for k, v in txt.items():
        raw = f"{k}={v}".encode()[:255]
        out += bytes([len(raw)]) + raw
    return out or b"\0"


def questions(data):
    """(id, flags, [(name, type, unicast reply wanted)]) of a query; ValueError when it is not one."""
    if len(data) < 12:
        raise ValueError("short")
    qid, flags, qd = struct.unpack("!HHH", data[:6])
    if flags & 0x8000:
        raise ValueError("a response")
    pos, out = 12, []
    for _ in range(min(qd, 32)):
        name, pos = decode_name(data, pos)
        if pos + 4 > len(data):
            raise ValueError("cut question")
        qtype, qclass = struct.unpack("!HH", data[pos:pos + 4])
        pos += 4
        out.append((name, qtype, bool(qclass & QU)))
    return qid, flags, out


class Responder:
    """Advertises one service: `service` (`_lantern._tcp`), `instance` (the server's name), its TCP `port`,
    its `txt` keys, and `host` (a label, `lantern-6f1c2a8e`) whose address is the one the querier reaches."""

    def __init__(self, service, instance, port, txt, host, address=None, mdns_port=PORT, bind="0.0.0.0"):
        self.service = service.rstrip(".") + ".local"
        self.instance = instance.replace("\\", "").replace(".", "\\.")[:63] + "." + self.service
        self.port, self.txt, self.host = port, txt, host[:63] + ".local"
        self.address, self.mdns_port = address, mdns_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        self.sock.bind((bind, mdns_port))
        self.multicast = True
        try:
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                                 socket.inet_aton(GROUP) + socket.inet_aton("0.0.0.0"))
            self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        except OSError:
            self.multicast = False      # no multicast here (a container): one-shot unicast queries still work

    def local_address(self, peer):
        """The address of this host that `peer` reaches, for the A record."""
        if self.address:
            return self.address
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect((peer if peer != "0.0.0.0" else GROUP, 9))
            found = probe.getsockname()[0]
            probe.close()
            return found
        except OSError:
            return "127.0.0.1"

    def answers(self, asked, peer, legacy):
        """(answers, additional records) for the questions asked."""
        ttl = LEGACY_TTL if legacy else TTL
        host_ttl = LEGACY_TTL if legacy else HOST_TTL
        flush = not legacy
        address = socket.inet_aton(self.local_address(peer))
        srv = record(self.instance, SRV, host_ttl, struct.pack("!HHH", 0, 0, self.port) + encode_name(self.host), flush)
        txt = record(self.instance, TXT, ttl, txt_data(self.txt), flush)
        a = record(self.host, A, host_ttl, address, flush)
        answers, extra = [], []
        for name, qtype, _ in asked:
            if name == self.service.lower() and qtype in (PTR, ANY):
                answers.append(record(self.service, PTR, ttl, encode_name(self.instance)))
                extra += [srv, txt, a]
            elif name == SERVICES and qtype in (PTR, ANY):
                answers.append(record(SERVICES, PTR, ttl, encode_name(self.service)))
            elif name == self.instance.lower():
                if qtype in (SRV, ANY):
                    answers.append(srv)
                    extra.append(a)
                if qtype in (TXT, ANY):
                    answers.append(txt)
            elif name == self.host.lower() and qtype in (A, ANY):
                answers.append(a)
        extra = [r for i, r in enumerate(extra) if r not in answers and r not in extra[:i]]
        return answers, extra

    def reply(self, data, peer):
        """The response to one datagram, and where it goes; None to stay silent."""
        try:
            qid, _, asked = questions(data)
        except ValueError:
            return None
        legacy = peer[1] != self.mdns_port
        answers, extra = self.answers(asked, peer[0], legacy)
        if not answers:
            return None
        head = struct.pack("!HHHHHH", qid if legacy else 0, 0x8400, len(asked) if legacy else 0, len(answers), 0,
                           len(extra))
        body = b""
        if legacy:      # a one-shot query: its questions echoed (RFC 6762 § 6.7)
            pos = 12
            for _ in asked:
                _, pos = decode_name(data, pos)
                pos += 4
            body = data[12:pos]
        message = head + body + b"".join(answers) + b"".join(extra)
        unicast = legacy or any(qu for _, _, qu in asked) or not self.multicast
        return message, (peer if unicast else (GROUP, self.mdns_port))

    def announce(self):
        if not self.multicast:
            return
        answers, extra = self.answers([(self.service.lower(), PTR, False)], GROUP, False)
        message = struct.pack("!HHHHHH", 0, 0x8400, 0, len(answers), 0, len(extra)) + b"".join(answers + extra)
        try:
            self.sock.sendto(message, (GROUP, self.mdns_port))
        except OSError:
            pass

    def serve(self):
        """Answers in a thread of its own; close() stops it."""
        def loop():
            while True:
                try:
                    data, peer = self.sock.recvfrom(9000)
                except OSError:
                    return
                try:
                    if ipaddress.ip_address(peer[0]).is_global:
                        continue    # multicast DNS is for the local link
                except ValueError:
                    continue
                out = self.reply(data, peer)
                if out:
                    try:
                        self.sock.sendto(*out)
                    except OSError:
                        pass
        threading.Thread(target=loop, daemon=True).start()
        self.announce()
        return self

    def close(self):
        self.sock.close()
