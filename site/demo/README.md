# The demo library

`https://lantern.boreale.dev/demo/` is a Lantern static library
([SPEC.md § 21](../../SPEC.md#21-static-libraries)) to point a client at
without a server of one's own. `tools/make_demo.py` writes it into the
site's `demo/` at each build, from `demo.json`:

```sh
python3 tools/make_demo.py build build/demo     # the demo, and its trapped variant in build/demo/trapped/
python3 tools/make_demo.py check build/demo     # the conformance suite against both
```

## What it holds

- **Fictional games** on the Nintendo Switch, the New 3DS, the PS Vita and
  Android: base games, an update and an add-on, with their sheets
  (genres, players, ratings, a summary) and an icon each, a small PNG drawn
  by the script (the night, a tint, one drawing in snow).
- **Homebrew** for the Switch, the 3DS and Linux, two of them signed by
  fictional keys (Ines's and Lea's, seeds written in `demo.json`).
- **Cheat sets** in the Switch's format (Atmosphère's text, `[name]` and
  words of eight hex digits), for games that do not exist.

Every game, studio and person in it is invented. A game may evoke a genre,
never a real game's name, characters, logo or icon.

## Placeholders, not software

**Nothing in it is software, and nothing in it can be installed.** An app's
file is text saying that it is a placeholder, a few hundred bytes (Moss &
Ember's, half a megabyte, numbers its lines with a digest of each, so that
the reference server's export gives it a chunk index of several chunks for
trying differential updates, SPEC.md § 22); a
homebrew archive holds a README and nothing else; a cheat set writes to
addresses of games that do not exist. A client may download, check and
"install" them to try its own code; a console's installer refuses them, and
none of them runs.

## How it is made

1. `demo.json` (schema 1) describes the library: the apps as the reference
   server's `library.json` gives them, with each file's size; the homebrew
   with its `homebrew.json` fields and its signer (its archive holds a
   README); the cheat sets; the time of the export and the library's uid.
2. The script writes that as a folder the reference server reads
   (`server/`), every file dated at the source's time, and exports it
   (`server/static.py`, as `python3 -m server --export` does).
3. It sets the export's `static.generated` and each title's `updated` to
   the source's time, and gives each title and homebrew its icon, stored as
   a file by its SHA-256 (`v1/blobs/sha256/<hex>`).

The same `demo.json` gives the same files, byte for byte. A `demo.json` of a
newer schema than the script reads gives no demo, without error.

## The trapped variant

`demo/trapped/<scenario>/` are static libraries with one fault each, for
testing clients: the demo's first Switch game, its cheat sets and Ines's
homebrew, with one thing broken. They mirror the malicious test server of
lantern-sdk's Python library (`python/tools/hostile_server.py`) wherever a
static file can express the fault (a wrong digest, hostile manifests, a
newer `schema`, documents beyond § 13's limits, a signature that does not
verify, a key of small order), and add the static layout's own (files that
leave the root). `demo/trapped/scenarios.json` (schema 1) lists them, with
what a client must do and the suite's checks that refuse each one; the
site's workflow checks that the suite does.

They are not in the sitemap, their page says `noindex`, and `robots.txt`
keeps crawlers out of them.

## No tracking

The library's handshake and files are plain JSON and bytes: no tracker, no
UTM tag (`check_site.py` checks it). Only the site's HTML pages count their
visits, as everywhere on the site.

## From a browser

GitHub Pages answers every file with `Access-Control-Allow-Origin: *`, so a
web client on another origin can read the library with `fetch()`, as long
as its requests stay simple: no credentials and no header of its own (not
even `Lantern-Platform`, which a static library does not need: the
platform is in its paths). A request that needs a preflight fails, since
GitHub Pages does not answer `OPTIONS` with the headers it would need.
