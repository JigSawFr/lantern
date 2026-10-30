# Lantern protocol

An open, versioned protocol between console homebrews and the game library
servers people run at home for their own games: browse the library, download
with integrity checks, keep save backups and cheats.

Website: <https://lantern.boreale.dev/?utm_source=github&utm_medium=readme>.

**Status: draft 0.1.** The text may still change before 1.0; comments and
issues are welcome, from client and server authors especially.

- **[The specification](SPEC.md)**: REST and JSON, versioned by path (`/v1/`)
  and by a `schema` in every document, so a client and a server of
  different ages keep working together.
- **What it keeps from the protocols in use today** (Tinfoil's index,
  Ownfoil, AeroFoil): their discovery on the local network, opaque download
  links, range requests, server-side filtering of what a console is missing.
- **What it adds**: a SHA-256 for every file, cursor pages, a declared list
  of features instead of guessed ones, pairing a console with a revocable
  token, errors with real status codes, and nothing hidden: no hardware
  identifier, no proprietary encryption, no server-driven change to the
  client.

- **[JSON Schemas](schemas/v1/)** for every document, with
  [examples](examples/v1/), and an **[OpenAPI description](openapi.yaml)**;
  `tools/check_schemas.py` checks them, in CI too.

Coming here: a conformance suite to run against a server (`conformance/`)
and a small reference server (`server/`). PlayShelf, a homebrew package
manager for the Nintendo Switch, will be the first client.

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
