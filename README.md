# Lantern protocol

An open, versioned protocol between the game library servers people run at
home for their own games and the homebrews and apps that read them, on
every platform [Aurore](https://aurore.boreale.dev/?utm_source=github&utm_medium=readme)
runs on: browse the library, download with integrity checks, read what the
server knows about each game, install homebrew and game ports, keep save
backups and cheats.

Website: <https://lantern.boreale.dev/?utm_source=github&utm_medium=readme>.

**Status: draft 0.3.** The text may still change before 1.0; comments and
issues are welcome, from client and server authors especially.

- **[The specification](SPEC.md)**: REST and JSON, versioned by path (`/v1/`)
  and by a `schema` in every document, so a client and a server of
  different ages keep working together.
- **Every platform Aurore runs on**: Nintendo Switch, New 3DS, PS Vita,
  PS4, Android, iOS and tvOS, Windows, macOS, Linux and the browser. A core
  that knows no platform, and a profile per platform in Annex A: the
  Switch's complete, the 3DS's, the Vita's, the PS4's and Android's as
  drafts to be reviewed, the others open.
- **What 0.3 adds**, each family optional and declared:
  - **game data** (`titles`): genres, players, age ratings, a localized
    summary and images, read a hundred at a time;
  - **homebrew**, game ports included: packages with a manifest that says
    where each file goes, nothing written elsewhere without the user's
    consent, an optional author signature pinned per homebrew; a port
    names the files the user supplies from their own copy of the game,
    which Lantern never serves;
  - **save backups**, resumable, checked by SHA-256 when they arrive;
  - **cheats**, several sets per game version, in each platform's format.
- **A protocol of its own**, compatible with no earlier one by design:
  nothing in it is kept for the sake of the protocols in use before it.
- **What makes it solid**: versioned twice (path and `schema`); a token per
  device, approved on the server, revocable, and no password ever on the
  device; HTTPS everywhere, with the key of a server at home pinned at
  pairing; a SHA-256 for every file, sent with every download and checked
  before installing; features declared instead of guessed; cursor pages,
  errors with real status codes, and nothing hidden: no hardware
  identifier, no proprietary encryption, no server-driven change to the
  client; and a conformance suite.

- **[JSON Schemas](schemas/v1/)** for every document, with
  [examples](examples/v1/) and refused ones, and an **[OpenAPI
  description](openapi.yaml)** of every route; `tools/check_schemas.py`
  checks them, in CI too.

[PlayShelf](https://shelf.boreale.dev/?utm_source=github&utm_medium=readme),
a homebrew package manager for the Nintendo Switch, will be the first
client.

## Conformance suite and reference server

The **[conformance suite](conformance/run.py)** checks a server from
outside, against every MUST it can see: handshake and declared features,
documents against the schemas, the bearer token's challenge (and no Basic
one), pairing's codes, platforms and their filter, cursor pages, what a
device is missing, every app's SHA-256, ranges and `Repr-Digest` on every
file response, titles, homebrew manifests and signatures, cheats, resumable
saves, errors, limits, and LAN discovery. Each check says PASS, FAIL, WARN (a SHOULD) or SKIP, with
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
packages and homebrew, for the platforms with a profile, with the families
`library`, `titles`, `changes`, `homebrew`, `cheats` and `saves`, and
`pairing` when it has accounts; `requests` and `sections` stay at 0. Its
docstring says how it reads the folder. Standard library only; a
reference, not a product:

```sh
python3 -m server --library ~/games [--users users.json] \
    [--host 0.0.0.0 --tls-cert cert.pem --tls-key key.pem] [--discovery]
```

- With `--users`, a device pairs: it asks for a code, and the user approves
  it on the server's page, `/pair`, signed in with their name and password,
  after comparing the key's fingerprint the device shows. Tokens are kept
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
