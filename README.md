# Lantern protocol

An open, versioned protocol between the game library servers people run at
home for their own games and the homebrews and apps that read them, on
every platform [Aurore](https://aurore.boreale.dev/?utm_source=github&utm_medium=readme)
runs on: browse the library, download with integrity checks, read what the
server knows about each game, install homebrew and game ports, keep save
backups and cheats.

Website: <https://lantern.boreale.dev/?utm_source=github&utm_medium=readme>.

**Status: draft 0.5.** The text may still change before 1.0; comments and
issues are welcome, from client and server authors especially.

- **[The specification](SPEC.md)**: REST and JSON, versioned by path (`/v1/`)
  and by a `schema` in every document, so a client and a server of
  different ages keep working together.
- **Every platform Aurore runs on**: Nintendo Switch, New 3DS, PS Vita,
  PS4, Android, iOS and tvOS, Windows, macOS, Linux and the browser. A core
  that knows no platform, and a profile per platform in Annex A: the
  Switch's complete, the 3DS's, the Vita's, the PS4's, Android's and
  Linux's (one platform for computers and handhelds alike) as drafts to be
  reviewed, the others open.
- **What 0.3 adds**, each family optional and declared:
  - **game data** (`titles`): genres, players, age ratings, a localized
    summary and images, read a hundred at a time;
  - **homebrew**, game ports included: packages with a manifest that says
    where each file goes, nothing written elsewhere without the user's
    consent, an optional author signature pinned per homebrew, a package
    per architecture, shelves by kind and genre, and requirements (C
    library, graphics, memory, screen) a client checks before offering a
    package; a port names the files the user supplies from their own copy
    of the game, which Lantern never serves;
  - **save backups**, resumable, checked by SHA-256 when they arrive;
  - **cheats**, several sets per game version, in each platform's format.
- **A protocol of its own**, compatible with no earlier one by design:
  nothing in it is kept for the sake of the protocols in use before it.
- **What 0.4 adds**:
  - **tokens bound to the device**: a key made at pairing, and every request
    signed with it (RFC 9421), so that a token copied off a console works
    nowhere else; pairing by **QR code**;
  - **invitations** (a link or a code, for a few devices, for a while) and
    a small **administration API** under the `admin` scope, to approve a
    console from a phone; a **rating cap** carried by a token, which hides
    what is rated above it everywhere, as a parental control on the server;
  - an **id for every requirement** (`L-5.2-3`), which the suite's checks
    name, a **threat model**, **conformance levels** (`Lantern Core`,
    `+titles`, `+homebrew`, `+saves`, `+cheats`, `+requests`, `+admin`) and
    the "Lantern compatible" badge, `Deprecation` and `Sunset` and how the
    text changes, **test vectors** for libraries ([`vectors/`](vectors/)),
    and guidelines for clients (Annex B);
  - errors and the server's message in the client's language, compressed
    JSON, Atlas ids, installed sizes, and withdrawing one's own request.
- **What 0.5 adds**, four optional families, each declared:
  - **events**: what changes, pushed as Server-Sent Events whose ids are
    `changes` tokens, so that `Last-Event-ID` resumes where `changes?since=`
    would, each caller seeing only what it may read; long polling for a
    console that sleeps; made for a console in the background and a home
    automation integration;
  - **sharing on the LAN**: a file is its SHA-256, so a mirror the server
    names, or a paired console that holds it (a **peer**), may serve it;
    a peer serves only to the holders of a **grant** its server signed, and
    the client checks every byte as it does the server's;
  - **sync** of a user's wishes and of what each console has installed,
    only with their consent, merged item by item, and deleted at once;
  - **end-to-end encrypted save backups**: XChaCha20-Poly1305 in chunks,
    resumable, a key the server never sees, carried by a recovery phrase or
    a QR code;
  - **static libraries**: the read routes as plain files, for GitHub Pages,
    a NAS or a USB key, which the reference server exports;
  - deleting an account, DNS-SD on the reference server, the ids of every
    profile in the schemas, and what 1.0 waits for (Annex C).
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
outside, against every requirement it can see, and prints the
[conformance levels](https://lantern.boreale.dev/conformance/?utm_source=github&utm_medium=readme)
it reaches: handshake and declared features,
documents against the schemas, the bearer token's challenge (and no Basic
one), pairing's codes, platforms and their filter, cursor pages, what a
device is missing, every app's SHA-256, ranges and `Repr-Digest` on every
file response, titles, homebrew manifests, packages, requirements, filters
and signatures, cheats, requests, resumable saves, errors, limits, signed requests (bad,
stale and replayed signatures refused), compression, languages, the cold
start's budget, and LAN discovery; with `admin`, the administration API,
invitations and their limits, rating caps, and deleting an account; event
streams and long polling, grants and mirrors, sync, encrypted backups, DNS-SD
(`--dns-sd`), a peer (`--peer`), and the rate limits of pairing, last. Each check says PASS, FAIL,
WARN (a SHOULD) or SKIP, with its SPEC.md section and the requirement ids it
covers; the exit code is 1 when one fails. On a server that offers pairing
it asks for a few real pairing codes, which the server may show to its users
until they expire on their own. With a token, it writes only for a title id
of no game of the library, and deletes what it writes: save backups, a cheat
set, a request, sync items; with `admin`, it also pairs devices and makes
invitations, then revokes them, and with `--admin-writes` makes an account of
its own, which it then deletes. Last, it asks for pairing codes until the
server answers 429, which leaves its address limited for a while. With
`--static`, it checks a static library instead, at an address or in a
folder, and prints `Lantern Static` when it passes.

```sh
pip install -r tools/requirements.txt   # jsonschema, for the schema checks
python3 conformance/run.py https://shelf.example.org/ [--token et_… --key device.key] [--discover 192.168.1.255] \
    [--pin <SPKI SHA-256>] [--dns-sd 192.168.1.10] [--peer http://192.168.1.20:47116/lantern]
python3 conformance/run.py --static https://lea.example.org/library/      # or a folder
```

The token is one a device got by pairing, and `--key` the file of the
device's private key (its 32-byte seed, base64) when the token is bound to
it; without them, the suite calls anonymously. A server at home with a self-signed certificate: `--cafile`
its certificate.

The **[reference server](server/lantern_server.py)** serves a folder of
packages and homebrew, for the platforms with a profile, with the families
`library`, `titles`, `changes`, `homebrew`, `cheats` (writing included),
`saves` and `encrypted_saves`, `requests`, `events`, `peers` and `sync`, and
`pairing` and `admin` when it has accounts; `sections` stays at 0. Its
docstring says how it reads the folder. Standard library only; a
reference, not a product:

```sh
python3 -m server --library ~/games [--users users.json] \
    [--host 0.0.0.0 --tls-cert cert.pem --tls-key key.pem] [--discovery] [--dns-sd]
python3 -m server --library ~/games --export ~/static-library [--page-size 100]
python3 -m server.peer --folder ~/switch-sd --server https://shelf.example.org/ --token et_… --key device.key
```

- With `--users`, a device pairs: it asks for a code, and the user approves
  it on the server's page, `/pair` (or from an admin app, through the
  administration API), signed in with their name and password, after
  comparing the key's fingerprint the device shows. A device that sent a key
  gets a token bound to it; `--bound-only` refuses the others. Tokens are
  kept hashed in the state file; `--tokens` lists them, `--revoke ID`
  revokes one.
- Without `--tls-cert` and `--tls-key` it speaks plain HTTP, and only on a
  loopback address, for testing.
- `--discovery` answers Lantern's discovery datagram on UDP 47115, and
  `--dns-sd` advertises `_lantern._tcp` over multicast DNS, with the
  standard library alone.
- `--export DIR` writes the library as a static library (SPEC.md § 21).
- [`server/peer.py`](server/peer.py) is a reference peer: it shares the
  files of a folder that are its server's, by their SHA-256, with the
  holders of a grant.

`python3 -m unittest discover -s tests` runs the suite against it on a tiny
fictional library, over plain HTTP on loopback and over TLS, as the
`conformance` workflow does; the workflow then runs the suite against the
server twice, anonymously and with a token holding every scope, which
`tools/pair_for_ci.py` gets by pairing through `/pair` as a user would,
with a device key.

**[Test vectors](vectors/)** give the bytes libraries must agree on:
signature bases and signatures of requests, homebrew signatures, SPKI
fingerprints, paths accepted and refused, `version_code` per profile,
requirements' decisions, rating caps, encrypted backups and recovery
phrases, grants, sync's merge rule and the static layout;
`tools/make_vectors.py` writes them, and the tests check them against the
reference.

## Licences

- The specification's text: [CC BY 4.0](LICENSES/CC-BY-4.0.txt).
- Everything else (schemas, OpenAPI description, examples, conformance
  suite, reference server): [MIT](LICENSES/MIT.txt), so that any server or
  client, under any licence, can implement the protocol and copy its
  schemas as they are.

Only an implementation that passes the conformance suite at a level may call
itself "Lantern compatible" and show the badge, with that level (SPEC.md
§ 17).

## Contact

Issues and pull requests on this repository: see
[CONTRIBUTING.md](CONTRIBUTING.md), which also says how to propose a
change to the protocol. A security flaw is reported privately, as
[SECURITY.md](SECURITY.md) says. Everyone follows the
[code of conduct](CODE_OF_CONDUCT.md).
