# Lantern protocol

An open, versioned protocol between console homebrews and the game library
servers people run at home for their own games: browse the library, download
with integrity checks, keep save backups and cheats.

Website: <https://lantern.boreale.dev/?utm_source=github&utm_medium=readme>.

**Status: draft 0.2.** The text may still change before 1.0; comments and
issues are welcome, from client and server authors especially.

- **[The specification](SPEC.md)**: REST and JSON, versioned by path (`/v1/`)
  and by a `schema` in every document, so a client and a server of
  different ages keep working together.
- **A protocol of its own**, compatible with no earlier one by design:
  nothing in it is kept for the sake of the protocols in use before it.
- **What makes it solid**: versioned twice (path and `schema`); a token per
  device, approved on the server, revocable, and no password ever on the
  console; HTTPS everywhere, with the key of a server at home pinned at
  pairing; a SHA-256 for every file, sent with every download and checked
  before installing; features declared instead of guessed; and a
  conformance suite.
- **And also**: discovery on the local network, opaque download links,
  range requests, server-side filtering of what a console is missing,
  cursor pages, errors with real status codes, and nothing hidden: no
  hardware identifier, no proprietary encryption, no server-driven change
  to the client.

- **[JSON Schemas](schemas/v1/)** for every document, with
  [examples](examples/v1/), and an **[OpenAPI description](openapi.yaml)**;
  `tools/check_schemas.py` checks them, in CI too.

PlayShelf, a homebrew package manager for the Nintendo Switch, will be the
first client.

## Conformance suite and reference server

The **[conformance suite](conformance/run.py)** checks a server from
outside, against every MUST it can see: handshake and declared features,
documents against the schemas, the bearer token's challenge (and no Basic
one), pairing's codes, cursor pages, what a console is missing, every app's
SHA-256, ranges and `Repr-Digest` on every file response, errors, limits,
and LAN discovery. Each check says PASS, FAIL, WARN (a SHOULD) or SKIP, with
its SPEC.md section; the exit code is 1 when one fails. It changes nothing
on the server and approves nothing, but on a server that offers pairing it
asks for a few real pairing codes, which the server may show to its users
until they expire on their own.

```sh
pip install -r tools/requirements.txt   # jsonschema, for the schema checks
python3 conformance/run.py https://shelf.example.org/ [--token et_…] [--discover 192.168.1.255]
```

The token is one a device got by pairing; without it, the suite calls
anonymously. A server at home with a self-signed certificate: `--cafile`
its certificate.

The **[reference server](server/lantern_server.py)** serves a folder of
packages (`.nsp`, `.nsz`, `.xci`, `.xcz`), identified by a `library.json` or
by the `[title id][vN]` in their names, with the families `library`,
`changes` and `media` (names only), and `pairing` when it has accounts; the
others stay at 0. Standard library only; a reference, not a product:

```sh
python3 -m server --library ~/games [--users users.json] \
    [--host 0.0.0.0 --tls-cert cert.pem --tls-key key.pem] [--discovery]
```

- With `--users`, a console pairs: it asks for a code, and the user approves
  it on the server's page, `/pair`, signed in with their name and password,
  after comparing the key's fingerprint the console shows. Tokens are kept
  hashed in the state file; `--tokens` lists them, `--revoke ID` revokes
  one.
- Without `--tls-cert` and `--tls-key` it speaks plain HTTP, and only on a
  loopback address, for testing.
- `--discovery` answers Lantern's discovery datagram on UDP 47115.

`python3 -m unittest discover -s tests` runs the suite against it on a tiny
fictional library, over plain HTTP on loopback and over TLS, as the
`conformance` workflow does.

## Licences

- The specification's text: [CC BY 4.0](LICENSES/CC-BY-4.0.txt).
- Everything else (schemas, OpenAPI description, examples, conformance
  suite, reference server): [MIT](LICENSES/MIT.txt), so that any server or
  client, under any licence, can implement the protocol and copy its
  schemas as they are.

Only an implementation that passes the conformance suite should call itself
Lantern-compatible.

## Contact

Issues and pull requests on this repository.
