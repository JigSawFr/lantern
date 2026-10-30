# Lantern — an open protocol for game library servers

Draft 0.3, 2026-10-30. Status: **draft**, open to change until 1.0.
This text is licensed under [CC BY 4.0](LICENSES/CC-BY-4.0.txt).

Lantern lets a client (a homebrew on a console, or an app on a phone, a
computer or in a browser) browse a library server the user runs for their
own games, download games and homebrew from it with integrity checks, read
what it knows about each game, and keep save backups and cheats there. It
is a small REST/JSON contract, versioned so that a client and a server of
different ages keep working together. It is a protocol of its own: it owes
nothing to the protocols in use before it and keeps nothing for their sake.

Its core knows no platform: listing, downloads, pairing and errors work the
same for a Nintendo Switch, a phone or a computer. What differs from one
platform to another (the form of a game's id, its package formats, where
cheats, saves and homebrew go) is in that platform's profile, in Annex A.

The key words MUST, SHOULD and MAY are used as in RFC 2119.

## 1. Principles

1. **Small and fixed.** Few routes, fixed shapes, no query language. A server
   fits in a weekend; a client in a few hundred lines of C++.
2. **Versioned twice.** A major protocol version in the path (`/v1/`) for
   breaking changes; an integer `schema` in every document for the rest
   (§ 3).
3. **Declared, never guessed.** The server says what it offers (`features`)
   and for which platforms; the client says who it is (`User-Agent`) and
   which platform it runs on (`Lantern-Platform`). No header sniffing.
4. **A neutral core, a profile per platform.** Every app says its
   `platform`; its ids, versions and formats follow that platform's profile
   (Annex A). Nothing else in the core depends on a platform.
5. **Structured identity, verified content.** Every package has its title
   id, app id, type, integer version, size, format and SHA-256, and every
   download is checked against it. File names carry no meaning.
6. **Secure by default.** HTTPS everywhere, a key pinned at pairing on the
   LAN, a revocable token per device. No password ever goes through the
   console. A homebrew writes only where its manifest says and the user
   allows.
7. **HTTP as it is.** Real status codes, `application/problem+json` errors,
   ranges, `ETag`, `Repr-Digest`, `Content-Digest`.
8. **Nothing hidden, nothing intrusive.** No hardware identifier, no
   proprietary encryption, no server-driven change to the client's settings.

## 2. Transport

- HTTPS. A client MUST verify the certificate against its CA store, or
  against the key it pinned at pairing (§ 5.3).
- Plain HTTP is allowed only on loopback addresses (`127.0.0.0/8`, `::1`),
  for testing. A client MUST NOT speak plain HTTP to any other address, and
  a server MUST NOT serve Lantern in plain HTTP on one.
- All routes live under a base path the server chooses (default
  `/api/lantern`), announced by discovery (§ 4.1) and the handshake (§ 4.2).
  Below, paths are relative to `<base>`.
- JSON bodies are UTF-8, `Content-Type: application/json`.
- The client MUST send `User-Agent: <Name>/<version>`, SHOULD send
  `Accept-Language`, and SHOULD send `Lantern-Platform` (§ 4.3).
- Tokens (§ 5) are sent only to the server's origin (scheme, host, port),
  never to another host a document points at.

## 3. Versions

### 3.1 Protocol version

The major version is in the path: `<base>/v1/…`. It changes only for a
break that `schema` cannot express. A server lists the versions it serves
(`versions` in § 4.2) and SHOULD keep an old major version while clients
still call it.

### 3.2 Document schema

Every JSON document a server returns, and every document a client sends,
has an integer `schema` at its top level.

- Adding a field keeps `schema`. A field that changes meaning, unit or type,
  or disappears, makes it go up.
- A reader MUST ignore fields it does not know.
- A reader that gets a `schema` higher than it knows MUST treat the document
  as absent (the feature is unavailable), not as an error, and MUST NOT
  write it back.
- Every document has a JSON Schema in `schemas/v1/` (2020-12), with an
  example in `examples/v1/`. The schemas describe schema 1 and allow fields
  they do not list, as a reader must.
- `features` (§ 4.2) gives, per family, the `schema` the server writes; a
  client MAY send `Accept-Schema: <family>=<n>, …` to ask for an older one,
  which a server SHOULD honour while it still can write it.

### 3.3 Extensions

Fields and routes of a vendor's own begin with `x-<vendor>-` (field) or
live under `<base>/x/<vendor>/` (routes). Clients ignore them unless they
know them.

## 4. Discovery, handshake and platforms

### 4.1 On the LAN

Lantern has its own discovery, on UDP port **47115**:

- The client sends the datagram `{"schema":1,"lantern":"discover"}` to port
  47115 as a directed broadcast (the subnet's broadcast address, such as
  `192.168.1.255`: the Switch drops `255.255.255.255`).
- A server answers unicast, to the datagram's source, with:

  ```json
  {"schema": 1, "lantern": "server", "uid": "6f1c2a8e-…",
   "name": "Living room shelf", "port": 443, "base": "/api/lantern",
   "versions": [1]}
  ```

- The server's address is the reply's source address; `port` is its HTTPS
  port, `base` and `versions` as in the handshake (§ 4.2).
- Each datagram is UTF-8 JSON of at most 1200 bytes. A server answers only a
  request it can read (§ 3.2) and stays silent otherwise. It SHOULD answer
  only addresses of its own networks, and only a few times a second to the
  same address.
- A server SHOULD also advertise itself with DNS-SD (RFC 6763) as
  `_lantern._tcp`, with the TXT keys `uid=<uid>`, `path=<base>` and `v=1`
  (the versions, comma-separated).
- Discovery is a hint: it finds an address and a name, nothing more. A
  reply proves nothing, and a client trusts a server only through TLS and
  pairing (§ 5).

### 4.2 Handshake

`GET /.well-known/lantern` (at the origin's root) and `GET <base>/v1/` return
the same document, with or without a token:

```json
{"schema": 1,
 "uid": "6f1c2a8e-…",
 "name": "Living room shelf",
 "software": {"name": "ExampleShelf", "version": "2.7.0"},
 "base": "/api/lantern",
 "versions": [1],
 "platforms": ["switch", "android"],
 "motd": "New this week: two co-op games.",
 "account": {"name": "lea", "state": "active", "scopes": ["library", "saves"]},
 "features": {"library": 1, "titles": 1, "changes": 1, "sections": 1,
              "homebrew": 1, "saves": 1, "cheats": 1, "requests": 0,
              "pairing": 1},
 "limits": {"page_size": 500, "save_body": 8388608,
            "save_size": 1073741824, "saves_kept_per_title": 10}}
```

- `uid`: a UUID that never changes for this server. A client uses it to
  recognise the same server on the LAN and on the WAN, and to find the key
  it pinned (§ 5.3).
- `platforms`: the platforms the server has something for (§ 4.3), the
  same for every caller.
- `account.state`: `anonymous` (no token), `active`, or `frozen` (the
  account exists but may do nothing; `motd` says why).
- `account.scopes`: what this caller may do: `library`, `saves`,
  `cheats`, `cheats.write`, `requests`, `admin`. `library` covers every
  read of the catalogue: apps, titles and homebrew.
- `features.<family>`: the `schema` the server writes for that family, or
  `0` when it does not offer it **to this caller**. `pairing` is the same
  for every caller, anonymous included: whoever can reach the server can ask
  to pair.
- `limits`: `page_size`, the most items on a page (§ 6.2); with `saves`,
  `save_body`, the largest save a single request takes (§ 9.2),
  `save_size`, the largest save at all (§ 9.3), and
  `saves_kept_per_title`, how many backups the server keeps per title,
  platform and account before it drops the oldest (§ 9.1).
- A call without a token to a private server returns the document with
  `account.state` `anonymous` and every feature at 0 but `pairing`, so a
  client can show the server's name and pair. A wrong token gives `401` here
  as elsewhere (§ 5.1): only its absence gives that document.
- A route of a family at 0 answers `404` (the server does not offer it) or
  `401`/`403` (not to this caller), never `2xx`.

### 4.3 Platforms

A platform is a lower-case name: 1 to 32 letters, digits and `-`, starting
with a letter or a digit. The names are those of
[Atlas](https://github.com/JigSawFr/Atlas) where Atlas has one (`switch`,
`steam`, `gog`, `xbox`); for the others, this text adds `3ds` (the New
Nintendo 3DS and the 3DS family), `vita` (PlayStation Vita), `ps4`,
`android`, `ios` (iOS, iPadOS and tvOS), `windows`, `macos`, `linux` and
`web` (an app run in a browser). A later version adds names to this list; a
vendor's own begins with `x-<vendor>-`.

- Every app (§ 6.1), title (§ 7), homebrew (§ 8), save (§ 9) and cheat set
  (§ 10) carries its `platform`.
- A client says its own platform with the header
  `Lantern-Platform: <name>` on every call.
- With the header, a server answers for that platform only: the apps'
  listing, what is missing (§ 6.3), changes (§ 6.4), sections, titles,
  homebrew, saves and cheats list and read only what is of that platform;
  anything else is `404`. A platform the server does not serve gives empty
  lists, not an error. A name that is not a platform name gives `400`.
- Without the header, a server answers for every platform, but where a
  route needs one: `POST <base>/v1/apps/missing` (§ 6.3),
  `POST <base>/v1/homebrew/updates` (§ 8.5) and the routes that write a save
  (§ 9) give `400` without a platform. A route that names a `title_id` or a
  homebrew `id` known on several platforms gives `400` too, until the
  client names the platform.
- `?platform=<name>` on a listing (or on a route that needs a platform)
  overrides the header.
- Responses that depend on the platform carry `Vary: Lantern-Platform`
  (§ 14).

## 5. Authentication

### 5.1 Tokens

- Every authenticated call sends `Authorization: Bearer <token>` (RFC 6750).
  There is no other scheme: no password and no HTTP Basic, on any route.
- A token is opaque to the client and has at least 128 bits of entropy. The
  server keeps only a hash of it, gives one per device, with the scopes the
  user approved (§ 5.2), and lets the user list and revoke them. A token MAY
  expire.
- A missing token where one is needed, or an unknown, revoked or expired
  one, gives `401` with `WWW-Authenticate: Bearer` (and
  `error="invalid_token"` when a token was sent). So does an `Authorization`
  of another scheme. A valid token without the scope gives `403`
  `forbidden`; one of a frozen account, `403` `account_frozen`.
- A public server answers calls without a token, as the account
  `anonymous` (§ 4.2), for the scopes it gives everyone.

### 5.2 Pairing (feature `pairing`)

How a console gets its token, modelled on the OAuth device flow (RFC 8628)
without OAuth's other parts. A private server MUST offer it; a public one
MAY, for what it gives beyond anonymous calls.

1. `POST <base>/v1/pairing` `{"schema":1, "device":"Lea's Switch",
   "scopes":["library","saves"]}`, without a token → `200` `{"schema":1,
   "code":"KQ4M-7TXD", "verify":"https://shelf.example.org/pair",
   "poll":"<base>/v1/pairing/p_…", "interval":5, "expires":600}`.
2. The console shows the code, the address `verify`, and the short
   fingerprint of the server's key (§ 5.3). The user opens `verify` on
   another device, signs in there by the server's own means, enters the
   code, compares the fingerprint, and approves the device and its scopes.
   Approval happens only on the server's side (its web page, or any admin
   means it has), never on the console: no password goes through the
   console, and the protocol has no route to approve.
3. The console polls `GET poll` every `interval` seconds: `202` while
   waiting, then `200` `{"schema":1, "token":"et_…", "scopes":[…]}`, or
   `410` when refused, expired, already collected or unknown. The scopes
   are those approved, at most those asked for and those of the account.
   `expires`, when present, is the token's lifetime in seconds.
4. Later calls send `Authorization: Bearer et_…` (§ 5.1).

- The code uses the alphabet `23456789ABCDEFGHJKLMNPQRSTUVWXYZ` (no `0`,
  `O`, `1` or `I`), has 8 to 32 symbols (at least 40 bits), and is shown in
  groups of 4 joined by `-`. The server ignores case, spaces and dashes
  when the user types it.
- A code expires within 10 minutes (`expires`, in seconds, at most 600).
  The poll address is unguessable (at least 128 bits) and gives the token
  once.
- The server limits pairing requests per address, attempts at a code, and
  polls more often than `interval`: beyond them it answers `429`
  `slow_down` with `Retry-After`.

### 5.3 Pinning, at pairing

A server whose certificate the client's CA store accepts needs nothing
more. Otherwise (a LAN server with a self-signed certificate):

- The fingerprint is the SHA-256 of the server's public key, its DER
  `SubjectPublicKeyInfo` (SPKI). Its short form, for people, is its first 16
  hex digits, upper-case, in groups of 4: `3F9A 1C07 B2E4 55D0`.
- During pairing, the console shows the short form of the key it sees,
  next to the code; the server's approval page shows the short form of its
  own. The user approves only when they match.
- Once paired, the client pins the whole SHA-256 for that server's `uid`. It
  polls and calls only over connections with that key: a changed key MUST
  fail, whatever certificate carries it, until the user pairs again.
- Before pairing, a client may read the handshake and ask for a code over a
  certificate it has not verified: it sends nothing secret then.

## 6. Library (feature `library`)

### 6.1 App

An app is one installable package: a base game, an update or an add-on.

```json
{"id": "a_9Qx2…",
 "platform": "switch",
 "title_id": "0100ABCD00010000",
 "app_id": "0100ABCD00010800",
 "type": "update",
 "version_code": 196608,
 "version_name": "1.3.0",
 "name": "Frostline Tales",
 "size": 734003200,
 "format": "nsz",
 "sha256": "3a7bd3e2…",
 "added": "2026-10-28T19:02:11Z",
 "file": "<base>/v1/files/f_Zk…"}
```

- `id`: opaque, stable while the file does not change.
- `platform`: the platform it is for (§ 4.3).
- `title_id`: the game's id; `app_id`: this package's id, the same as
  `title_id` where the platform has no other. Both are opaque strings of 1
  to 128 letters, digits, `.`, `_` and `-`, compared exactly (case
  included), whose form the platform's profile gives (Annex A). An id is
  unique within its platform only. `changes` is never a title id (§ 7.3).
- `type`: a lower-case word from the profile's list. `base` (a game),
  `update` (a newer version of a game, in a package of its own) and `dlc`
  (an add-on) mean the same on every platform that has them.
- `version_code`: an integer, as the profile derives it; clients compare
  integers, never text. `version_name`, optional, is the version people
  read (`1.3.0`), never compared.
- `size`: bytes, a 64-bit integer.
- `format`: a lower-case word from the profile's list of package formats.
- `sha256`: of the file as served, lower-case hex. Required: a server hashes
  a file before it lists it.

On a platform with no profile yet (Annex A.6), a server MAY serve apps under
these rules alone; a client MUST NOT install an app, or a homebrew, of a
platform it has no profile for.

### 6.2 Listing

`GET <base>/v1/apps?platform=&type=&title_id=&q=&sort=&page_size=&cursor=` →

```json
{"schema": 1, "items": [App, …], "total": 4123, "next": "c_…"}
```

- `platform` overrides `Lantern-Platform` (§ 4.3); `type` and `title_id`
  filter; `q` searches names.
- `sort`: `name` (the default), `added` or `release` (both newest first);
  ties are broken by `id`, so the order is stable.
- `cursor` is opaque; `next` is `null` on the last page. Reading with a
  cursor while the library changes neither skips nor repeats an app.
- An expired cursor gives `410`, and the client reads the list from its
  start. One the server never gave, or gave for another listing, gives
  `400`, or `410` when the server cannot tell it from an expired one.
- `page_size` is at most `limits.page_size`; a larger one is lowered to it.

### 6.3 What the console is missing

`POST <base>/v1/apps/missing`, with `Lantern-Platform` (or `?platform=`):
`400` without one.

```json
{"schema": 1,
 "installed": [{"app_id": "0100ABCD00010000", "version_code": 0},
               {"app_id": "0100ABCD00010800", "version_code": 131072}],
 "want": ["update", "dlc"]}
```

→ a listing (§ 6.2), for that platform, of:

- with `update` in `want`: for each installed game, its newest update whose
  `version_code` is above the highest installed one of that game. An update
  is an app of type `update`, or, on a platform whose profile says that a
  newer package replaces the base (Android), an app of type `base` of the
  same `app_id`;
- with `dlc`: the add-ons of installed games not installed;
- with `base`: the games not installed.

A server knows an installed app's game from its library, or from the
profile's rule when it has one. Paginated with `cursor` in the query.

### 6.4 Changes (feature `changes`)

`GET <base>/v1/changes?since=<token>` → `{"schema":1, "added":[App…],
"removed":["a_…"], "since":"<next token>"}`, for the platform the client
named, or every platform. Without `since`, it returns no apps and the
current token. A token too old for the server gives `410`: the client
reads the whole library again. One it never gave gives `400` (or `410`, as
for a cursor, § 6.2).

### 6.5 Sections (feature `sections`)

`GET <base>/v1/sections` → `{"schema":1, "sections":[{"id":"new",
"title":"New", "apps":["a_…", …]}, …]}`: shelves the server curates. A
client MAY show them next to its own.

### 6.6 Files

`GET <file>`:

- MUST support `Range` (`206`; `416` with `Content-Range: bytes */<size>`)
  and send `Content-Length`, `Accept-Ranges: bytes` and a strong `ETag`.
- MUST send `Repr-Digest: sha-256=:<base64>:` (RFC 9530) on every response,
  whole (`200`) or ranged (`206`), and on `HEAD`: the digest of the whole
  file, the same as the app's `sha256`.
- The id in the path is opaque and not enumerable. It MAY expire: the
  client then reads the app again.
- A server MAY offer a decompressed form of a compressed file under its own
  app entry (its own `format`, `size` and `sha256`), never silently.
- A client MUST check the SHA-256 of what it downloaded against the app's
  `sha256` before installing it, and refuse it when they differ.

The same holds for every file the protocol points at: homebrew packages
(§ 8), save backups (§ 9) and cheat sets (§ 10).

## 7. Titles (feature `titles`)

What the server knows about a game, on one platform: the sheet a client
shows next to its apps. Read with the scope `library`.

### 7.1 A title

`GET <base>/v1/titles/{title_id}` →

```json
{"schema": 1, "platform": "switch", "title_id": "0100ABCD00010000",
 "language": "en", "name": "Frostline Tales",
 "publisher": "Fjord Works", "developer": "Fjord Works",
 "release": "2025-03-14", "updated": "2026-10-28T19:02:11Z",
 "genres": ["adventure", "puzzle"], "tags": ["co-op", "winter"],
 "players": {"min": 1, "max": 4, "online": true, "online_max": 8},
 "ratings": [{"system": "PEGI", "rating": "7"}, {"system": "ESRB", "rating": "E10+"}],
 "languages": ["en", "fr", "ja"],
 "summary": "Guide a lantern-bearer across a frozen archipelago.",
 "description": "…",
 "icon": {"url": "<base>/v1/media/9f2c….jpg", "width": 256, "sha256": "9f2c…"},
 "banner": {…}, "screenshots": [{…}],
 "video": {"url": "https://video.example.org/frostline", "external": true}}
```

- `platform` and `title_id`: as an app's (§ 6.1). A title is per platform:
  the same game on two platforms has two titles.
- `language` says which language `summary` and `description` are in, the
  best the server has for `Accept-Language`.
- `genres`: zero or more of a fixed list, `action`, `adventure`, `rpg`,
  `strategy`, `simulation`, `sports`, `racing`, `puzzle`, `platformer`,
  `shooter`, `fighting`, `music`, `party`, `education` and `other`. A later
  version may add genres: a client shows a genre it does not know as
  `other`. `tags` are free words (32 at most, 64 bytes each).
- `players`: `min` and `max` on one console; `online` whether it plays
  online, and `online_max` how many at most.
- `ratings`: the age ratings, each `system` an organisation's short name
  (`PEGI`, `ESRB`, `CERO`, `USK`, `ACB`, `CLASSIND`, `GRAC`…) and `rating`
  its rating as that organisation writes it (`7`, `E10+`, `A`).
- `release`: the date the game came out; `updated`: when this sheet last
  changed.
- `icon`, `banner`, `screenshots` (16 at most): images. An image on the
  server's origin SHOULD be content-addressed and served with a long cache
  lifetime. An image with `"external": true` points elsewhere.
- `video`: a page or a video elsewhere, always `external`.
- A client MUST NOT send a token, or any credential, to an `external`
  address, and SHOULD open a `video` only when the user asks.

### 7.2 Many titles at once

`GET <base>/v1/titles?ids=<id>,<id>,…` (100 at most, comma-separated; more
gives `400`) → `{"schema":1, "titles":[Title…], "unknown":["…"]}`: the
titles the server has among those ids, for the platform the client named
(or for each platform that has the id), and the ids it does not know.

### 7.3 Changes

`GET <base>/v1/titles/changes?since=<token>` → `{"schema":1,
"titles":[Title…], "removed":[{"platform":"switch","title_id":"…"}],
"since":"<next token>", "more":false}`: the titles added or changed, and
those removed, since the token, as `/v1/changes` does for apps (§ 6.4). A
server MAY give part of them: `more` is then `true`, and the client asks
again with the new `since`.

## 8. Homebrew (feature `homebrew`)

The homebrew a server offers: apps and tools made by their authors, read
with the scope `library`. Mods (LayeredFS and the like) are out of scope
for this version; a later one may describe them on the same model.

### 8.1 An entry

`GET <base>/v1/homebrew/{id}` →

```json
{"schema": 1,
 "id": "org.example.frostline", "platform": "switch",
 "name": "Frostline", "author": "Noor", "category": "tool",
 "version": "1.4.0", "build": 10400,
 "license": "MIT", "source": "https://code.example.org/noor/frostline",
 "language": "en", "summary": "A pocket journal for long nights.",
 "description": "…",
 "icon": {"url": "https://media.example.org/frostline/icon.jpg", "external": true},
 "screenshots": [],
 "requires": {"text": "Atmosphère 1.7 or later", "min": {"atmosphere": "1.7.0"}},
 "updated": "2026-10-29T08:00:00Z",
 "package": {"format": "zip", "file": "<base>/v1/files/f_…",
             "size": 482113, "sha256": "…", "manifest_sha256": "…",
             "manifest": [{"path": "/switch/org.example.frostline/frostline.nro",
                           "size": 471040, "sha256": "…"},
                          {"path": "/config/org.example.frostline/settings.ini",
                           "size": 96, "sha256": "…"}]},
 "signature": {"alg": "ed25519", "public_key": "<base64>", "value": "<base64>"}}
```

- `id`: stable, in reverse-DNS form, lower-case (`org.example.frostline`):
  the author's, and the same for every version. Ids under `local.` are a
  server's own, for a homebrew whose author gave none; they are stable on
  that server only. An id is unique within its platform.
- `name`, `author`, `summary` and `description` (localized, `language` as
  for a title, § 7.1), `icon` and `screenshots` (images, § 7.1).
- `category`: `game`, `emulator`, `tool`, `media`, `system` or `other`.
- `license`: an SPDX licence expression; `source`: where its code is.
- `version` is for people; `build` is an integer that grows with every
  version, and the one a client compares.
- `requires`, optional: what the console needs, `text` for people and
  `min`, the lowest versions in the profile's terms (Annex A), as dotted
  numbers. A client that does not know a key of `min` relies on `text`.
- `updated`: when this entry last changed.

### 8.2 Packages and manifests

A package is one file, downloaded like an app's (§ 6.6): `file`, `size` and
`sha256` are REQUIRED. It is either:

- **a single file** (`.nro`, `.3dsx`, `.vpk`, `.apk`…): `path` says where it
  goes on the device; or
- **an archive** (`zip`) with a **manifest**: every file it installs, its
  `path` on the device, `size` and `sha256`, all REQUIRED. The archive holds
  each of them under its path without the leading `/`; anything else in it
  is ignored.

A single file is a manifest of one entry: its `path`, `size` and `sha256`.
Where the profile says the platform's own installer installs a format
(`.apk`, `.vpk`…), the package has no `path`.

A `path` is absolute on the device's storage, as the profile maps it: it
starts with `/`; its parts are separated by `/`, none empty, `.` or `..`;
it has no `\`, `:`, `"`, control character or NUL; a part is 255 bytes at
most, the path 1024. No two paths of a manifest are the same when case is
ignored. A manifest has 4096 files at most.

`manifest_sha256` is the SHA-256, lower-case hex, of the manifest's
canonical form: the JSON array of its entries sorted by `path` (as UTF-8
bytes), each entry `{"path":…,"sha256":…,"size":…}` with its keys in that
order, no space, and characters other than ASCII written as they are, in
UTF-8. A listing (§ 8.5) leaves `manifest` out and keeps
`manifest_sha256`; the entry's own route has both.

### 8.3 Installing

A client MUST:

- refuse a package whose download does not match its `sha256`, or a file
  of an archive that does not match its manifest entry;
- refuse a manifest with a path that breaks § 8.2, or that lies outside the
  profile's roots for homebrew (Annex A), and install nothing of it;
- write only the manifest's paths, and only files: never follow a link
  out of them;
- write without asking only under the profile's roots that need no
  consent (`/switch/<id>/` on a Switch, where `<id>` is the entry's `id`);
  for any path elsewhere, show every such path to the user and install only
  when they agree;
- keep each installed manifest, and uninstall by it alone: remove its
  files, then the folders it made that are left empty, nothing else. An
  update removes the files of the old manifest the new one no longer has.

### 8.4 Signature

An author MAY sign their packages with ed25519 (RFC 8032). The entry then
carries `signature`: `alg` (`ed25519`), `public_key` (the 32 bytes of the
key, base64) and `value` (the 64 bytes of the signature, base64).

The signed bytes are the UTF-8 bytes of the JSON object

```text
{"build":<build>,"id":"<id>","manifest_sha256":"<hex>","platform":"<platform>","purpose":"lantern-homebrew-1","sha256":"<hex>"}
```

with these keys in this order, no space, `build` in decimal, and the
entry's values. Each value's form (§ 8.1, § 8.2, § 4.3) leaves nothing to
escape, so the bytes are the same for every writer.

- A server MAY serve a signature it is given, as given; it does not sign
  for an author. It SHOULD check a signature before it serves it.
- A client MUST check the signature when there is one, and refuse the
  package when it does not verify.
- On the first install of an `id`, the client pins its `public_key` (or
  that it had none). A later version signed by another key, or unsigned
  after a signed one, MUST be refused unless the user explicitly accepts the
  change, after the client showed both keys' short fingerprints (the
  SHA-256 of the 32 bytes, in the form of § 5.3).

### 8.5 Routes

- `GET <base>/v1/homebrew?platform=&q=&category=&page_size=&cursor=` → a
  page (§ 6.2) of entries, sorted by name: `{"schema":1,
  "items":[Entry…], "total":12, "next":null}`.
- `GET <base>/v1/homebrew/{id}` → the entry (§ 8.1), with its manifest.
- `POST <base>/v1/homebrew/updates`, with a platform (§ 4.3):
  `{"schema":1, "installed":[{"id":"org.example.frostline", "build":10300}]}`
  → a page of the entries of those ids whose `build` is above the
  installed one, paginated with `cursor` in the query, like § 6.3.

## 9. Save backups (feature `saves`, scope `saves`)

### 9.1 Backups

`GET <base>/v1/saves?platform=&title_id=` → `{"schema":1, "saves":[Save…]}`,
newest first per title, where a save is:

```json
{"platform": "switch", "title_id": "0100ABCD00010000", "save_id": "s_03",
 "created": "2026-10-30T09:12:00Z", "size": 1052672, "sha256": "…",
 "kind": "account", "game_version_code": 196608, "profile": "Lea",
 "note": "Chapter 4", "device": "Lea's Switch"}
```

- `kind`: `account` (a user's save), `device` (the console's, shared by
  its users), `bcat` (data the game downloaded), `cache`, or `other`, as
  the profile maps the platform's own kinds.
- `game_version_code`: the game's `version_code` (§ 6.1) when it was
  saved, so that a client warns before restoring a save on an older game.
- `profile`: the name the user gave the profile the save belongs to, as
  the console shows it. Never a hardware or account identifier.
- `device`: the name of the paired device that sent it (§ 5.2).
- The archive is a zip whose content the profile gives (Annex A).
- The server keeps at most `limits.saves_kept_per_title` backups per title,
  platform and account, and drops the oldest beyond it.
- `GET` and `DELETE <base>/v1/saves/{title_id}/{save_id}`: the archive, as
  a file (§ 6.6), and its removal (`204`).

Every route that writes a save needs a platform (§ 4.3).

### 9.2 In one request

For a save of at most `limits.save_body` bytes:
`POST <base>/v1/saves/{title_id}`, the zip archive as the body
(`Content-Type: application/zip`), with:

- `Content-Digest: sha-256=:<base64>:` (RFC 9530), REQUIRED: without it,
  `400`. The server checks it and answers `422` `digest_mismatch` when the
  body does not match.
- `Lantern-Save-Kind`, `Lantern-Game-Version` (the integer
  `game_version_code`), `Lantern-Profile` and `Lantern-Note` (UTF-8,
  percent-encoded; 64 and 120 bytes at most).

→ `201` with the save entry. A larger body gives `413`.

### 9.3 Resumable upload

For any save up to `limits.save_size` bytes, sent in chunks that survive a
lost connection:

1. `POST <base>/v1/saves/{title_id}/uploads` `{"schema":1, "size":5242880,
   "sha256":"…", "kind":"account", "game_version_code":196608,
   "profile":"Lea", "note":"Chapter 4"}` → `201` `{"schema":1,
   "upload":"<base>/v1/uploads/u_…", "chunk_size":1048576, "offset":0,
   "expires":"2026-10-31T09:12:00Z"}`. A `size` above `limits.save_size`
   gives `413`.
2. `PATCH <upload>` with `Upload-Offset: <n>` and a chunk of at most
   `chunk_size` bytes as the body (`Content-Type:
   application/offset+octet-stream`) → `204` with the new `Upload-Offset`.
   An offset other than the server's gives `409` `conflict` with the
   server's `Upload-Offset`; a larger chunk, `413`. A chunk MAY carry its
   own `Content-Digest`, which the server then checks (`422`
   `digest_mismatch`).
3. `HEAD <upload>` → `204` with `Upload-Offset` and `Upload-Length`: where
   to resume after an interruption. A server keeps only whole chunks, or
   says in `Upload-Offset` how much of a cut one it kept.
4. The chunk that reaches `size` ends the upload: the server checks the
   whole archive's SHA-256, then answers `201` with the save entry, or `422`
   `digest_mismatch` and discards it.

`DELETE <upload>` abandons an upload (`204`). An upload not finished by
`expires` is gone (`404` or `410`). Only the account that opened an upload
sees it.

## 10. Cheats (feature `cheats`)

- `GET <base>/v1/cheats?platform=&title_id=&build_id=` →
  `{"schema":1, "cheats":[Set…]}`, where a set is
  `{"id":"cs_…", "platform":"switch", "title_id":"0100ABCD00010000",
  "build_id":"4A1B2C3D4E5F6071", "source":"Community list",
  "note":"Endless lamp oil", "updated":"2026-10-29T21:00:00Z",
  "size":512, "sha256":"…"}`. A build may have several sets, from several
  sources.
- `build_id`: the build of the game the set is for, in the profile's form
  (Annex A), on platforms whose cheats depend on it; absent elsewhere.
- `GET <base>/v1/cheats/{id}` → the set's text, as a file (§ 6.6), in the
  platform's own format and at most 1 MiB, which the client writes where
  the profile says (Atmosphère's text for a Switch).
- With scope `cheats.write`, a server MAY take
  `POST <base>/v1/cheats` and `PUT` and `DELETE <base>/v1/cheats/{id}`; the
  body of `POST` and `PUT` is `{"schema":1, "platform", "title_id",
  "build_id", "source", "note", "text"}`. A server without them answers
  `405`.

## 11. Requests (feature `requests`)

- `GET <base>/v1/requests` → `{"schema":1, "requests":[{"id", "platform",
  "title_id", "name", "status", "created"}…]}`. `status`: `open`, `done` or
  `declined`.
- `POST <base>/v1/requests` `{"schema":1, "platform":"switch",
  "title_id":"…"}` → `201`, or `200` with the open request for the same
  title. `platform` defaults to the client's (§ 4.3).

## 12. Errors

Every error is `application/problem+json` (RFC 9457) with a real status
code, never `200`:

```json
{"schema": 1, "type": "https://lantern.boreale.dev/errors/account-frozen",
 "title": "Account frozen", "status": 403, "code": "account_frozen",
 "detail": "Your access is paused until Sunday."}
```

| Status | `code` | When |
|---|---|---|
| 400 | `bad_request` | A malformed query or body; a cursor or `since` token the server never gave; a platform missing where one is needed |
| 401 | `unauthorized` | No token where one is needed, or an unknown, revoked or expired one (with `WWW-Authenticate: Bearer`) |
| 403 | `forbidden`, `account_frozen` | A scope missing; a frozen account |
| 404 | `not_found` | |
| 405 | `bad_request` | A method the route does not take (with `Allow`) |
| 409 | `conflict` | An upload's offset that is not the server's (with `Upload-Offset`) |
| 410 | `gone` | An expired cursor, `since` token, pairing or file id |
| 413 | `too_large` | A save or a chunk above the server's limit |
| 416 | `bad_request` | A range outside the file (with `Content-Range: bytes */<size>`) |
| 422 | `unsupported_schema`, `digest_mismatch` | A request document of a schema the server cannot read; a body whose SHA-256 is not the one announced |
| 429 | `slow_down` | Too many requests, pairing attempts or polls (with `Retry-After`) |
| 500 | `internal` | A failure of the server itself; the client may try again later |
| 503 | `unavailable` | Scanning, maintenance (with `Retry-After`) |

`detail` is for people; a client shows it, bounded and without control
characters.

New codes MAY come with later versions of this text: a client that gets a
`code` it does not know acts on the status alone.

## 13. Limits

A client MUST bound what it reads and a server MUST stay within:

| What | At most |
|---|---|
| A JSON document | 32 MiB, nesting depth 16 |
| A string field | 4 KiB (`name` 512 bytes, `note` 120 bytes, `profile` 64 bytes) |
| A page | 1000 items |
| Titles read at once | 100 |
| A manifest | 4096 files, each path 1024 bytes |
| A cheat set | 1 MiB |
| A discovery datagram | 1200 bytes |

## 14. Caching

Every `GET` returning JSON SHOULD carry an `ETag` and honour
`If-None-Match` with `304`. Responses to authenticated calls carry
`Cache-Control: private` and `Vary: Authorization`; responses that depend
on the platform or the language also vary on `Lantern-Platform` and
`Accept-Language`.

## 15. Security and privacy

- No hardware identifier, no tracking header. A server knows a device only
  by the name its user gave it during pairing, and a save's profile only by
  the name its user gave it.
- No password goes through the console: it holds a token per server, which
  the user can revoke from the server (§ 5).
- No proprietary encryption of documents: TLS protects them, with a key
  pinned at pairing when no CA vouches for it (§ 5.3).
- Discovery is a hint, never a proof (§ 4.1).
- A server cannot change a client's settings or add headers to its later
  requests.
- A client MUST check a download's SHA-256 before installing it (§ 6.6),
  and a homebrew's signature when it has one (§ 8.4).
- A homebrew writes only its manifest's files, under the profile's roots,
  and nothing outside the roots that need no consent without the user's
  agreement (§ 8.3).
- No credential goes to an external address (§ 7.1).
- Servers are for the user's own games.

## 16. Conformance

A conformance suite (`conformance/`) runs against a server's URL, with a
token or without, and checks every MUST of this text it can see from
outside: shapes and `schema`, platforms and their filter, the token
challenge, pairing's shapes, ranges, digests, homebrew manifests and
signatures, titles, cheats, error format, limits, the refusal of an unknown
request `schema`. With a token that holds `saves`, it also sends a save in
chunks and deletes it. A reference server (`server/`) serves a folder of
packages and homebrew and passes the suite.

## Annex A — Platform profiles

A profile says, for one platform, what the core leaves open. It gives:

- the form of `title_id` and `app_id`, with a regular expression;
- the app `type`s, and how `version_code` is derived;
- the package `format`s;
- for cheats: the file format, the form of `build_id` and where the client
  puts a set;
- for saves: the kinds, and what the archive holds, at which root;
- for homebrew: the package formats, the roots a client may write to
  without asking, those that need the user's consent, and the keys of
  `requires.min`.

Paths are written as § 8.2 says; the profile says how they map to the
device. The Switch's profile is complete. Those of the 3DS, the Vita, the
PS4 and Android are drafts, **to be reviewed by someone who knows the
platform**: what is marked "(to check)" is not settled. The other platforms
are open.

### A.1 Nintendo Switch (`switch`)

- **Ids.** `title_id`: the base game's id, 16 upper-case hex digits
  (`^[0-9A-F]{16}$`), its lowest 13 bits zero. `app_id`: the package's own
  id, of the same form: the `title_id` for the base, the `title_id` plus
  `800` (hex) for its update, and an add-on's own id above it.
- **Types**: `base`, `update`, `dlc`. An update is a package of its own.
- **Versions.** `version_code`: the integer title version, as the system
  reads it (`196608` for `v196608`); `version_name`: the display version of
  the game's control data (`1.3.0`).
- **Formats**: `nsp`, `nsz`, `xci`, `xcz`.
- **Paths**: `/` is the SD card's root.
- **Cheats.** Atmosphère's text format. `build_id`: upper-case hex, 1 to 64
  digits; Atmosphère names its files with the first 16, those of the main
  executable's build id. The client writes a set to
  `/atmosphere/contents/<title_id>/cheats/<build_id>.txt`.
- **Saves.** Kinds `account` (a user's save; `profile` is the user's
  nickname), `device`, `bcat`, `cache`, and `other` for the rest. The zip
  holds the save filesystem's files as they are in it, at the root of the
  archive.
- **Homebrew.** Formats `nro` (a single file, normally at
  `/switch/<id>/<name>.nro`) and `zip`. Roots without consent:
  `/switch/<id>/` and `/config/<id>/`. Roots that need consent:
  `/atmosphere/` (sysmodules in `/atmosphere/contents/<program id>/`, among
  others) and `/switch/.overlays/`. Nothing else. `requires.min` keys:
  `firmware` (the system version, `18.0.0`) and `atmosphere` (`1.7.0`).
  A server reads an `.nro`'s name, author and version from the control data
  (NACP) in its asset section.

### A.2 New Nintendo 3DS (`3ds`), draft

To be reviewed by someone who knows the platform.

- **Ids.** `title_id`: 16 upper-case hex digits (`^[0-9A-F]{16}$`), the
  game's id, which begins with `00040000`. `app_id`: the package's own id:
  an update's begins with `0004000E`, an add-on's with `0004008C`, with the
  same last 8 digits as the game's.
- **Types**: `base`, `update`, `dlc`. An update is a package of its own.
- **Versions.** `version_code`: the 16-bit title version of the title
  metadata; `version_name`: its major, minor and micro parts (6, 6 and 4
  bits) (to check).
- **Formats**: `cia`. Cartridge dumps (`3ds`, `cci`) are not installed as
  such (to check).
- **Paths**: `/` is the SD card's root.
- **Cheats.** Luma3DS's text format, one file per game, at
  `/cheats/<title_id>.txt` (to check). No `build_id`.
- **Saves.** The game's save data, as `device` (the 3DS has a single user)
  (to check); its extra data as `other` (to check). What the zip holds and
  at which root (to check).
- **Homebrew.** Formats `3dsx` (a single file, at `/3ds/<id>/<name>.3dsx`
  (to check)) and `zip`; a `cia` is installed by the system as a title,
  always after asking the user (to check). Roots without consent:
  `/3ds/<id>/` (to check). Roots that need consent: `/luma/` (to check).
  `requires.min` keys: `firmware` and `luma` (to check).

### A.3 PlayStation Vita (`vita`), draft

To be reviewed by someone who knows the platform.

- **Ids.** `title_id`: four upper-case letters and five digits
  (`^[A-Z]{4}[0-9]{5}$`, `PCSE00000`). `app_id`: the `title_id` for the
  game and its update; an add-on's content id (to check).
- **Types**: `base`, `update`, `dlc`.
- **Versions.** `version_code`: the application version `XX.YY` as the
  integer `XXYY` (`01.03` gives `103`) (to check); `version_name`: that
  version.
- **Formats**: `vpk` (to check for the others).
- **Paths**: `/ux0/…` is the storage `ux0:` (to check).
- **Cheats.** Each cheat plugin has its own format and folder: none is
  settled here (to check). No `build_id` (to check).
- **Saves.** The game's save data folder, as `account` (to check); what the
  zip holds and at which root (to check).
- **Homebrew.** Format `vpk`, installed by the system's installer after
  asking the user: no `path` (to check). Plugins and the files they need:
  no root is settled yet (to check), so a client installs no manifest
  here until the profile names its roots.

### A.4 PlayStation 4 (`ps4`), draft

To be reviewed by someone who knows the platform.

- **Ids.** `title_id`: four upper-case letters and five digits
  (`^[A-Z]{4}[0-9]{5}$`, `CUSA00000`). `app_id`: the `title_id` for the
  game and its update; an add-on's content id (to check).
- **Types**: `base`, `update`, `dlc`.
- **Versions.** `version_code`: the application version `XX.YY` as the
  integer `XXYY` (to check); `version_name`: that version.
- **Formats**: `pkg`.
- **Paths**: `/` is the system's root as homebrew see it (to check).
- **Cheats.** GoldHEN's cheat files (to check: their formats, their folder
  and how a file names the game's version). `build_id`: the game's version
  the set is for (to check).
- **Saves.** What a save holds and at which root (to check).
- **Homebrew.** Format `pkg`, installed by the system after asking the
  user: no `path`. Plugins: no root is settled yet (to check), so a client
  installs no manifest here until the profile names its roots.
  `requires.min` keys: `firmware` (to check).

### A.5 Android (`android`), draft

To be reviewed by someone who knows the platform.

- **Ids.** `title_id`: the app's package name
  (`^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$`); `app_id`: the same.
- **Types**: `base` only: a newer package of the same `app_id` replaces the
  old one, and is the update § 6.3 looks for. Add-ons and expansion files
  (to check).
- **Versions.** `version_code`: the package's `versionCode`;
  `version_name`: its `versionName`.
- **Formats**: `apk` (split packages: to check).
- **Cheats**: none.
- **Saves**: no profile yet (an app's data is its own) (to check).
- **Homebrew.** Format `apk`, installed by the system's installer, which
  always asks the user: no `path`. `requires.min` keys: `sdk` (the lowest
  API level, `26`).

### A.6 Open platforms

`ios`, `windows`, `macos`, `linux` and `web` have no profile yet, nor do
Atlas's store names (`steam`, `gog`, `xbox`). A server MAY serve apps of
these platforms under the core's rules (§ 6.1); a client MUST NOT install
anything of a platform it has no profile for.

## Changes

- 0.1 (2026-10-30): first draft.
- 0.1 (2026-10-30), from the conformance suite: wrong credentials give 401
  on the handshake too, and so does an unknown token; a family at 0 answers
  404, 401 or 403; `sort` defaults to `name` and `release` is newest first;
  a `page_size` above the limit is lowered to it; codes for 405 and 416.
- 0.1 (2026-10-30): an expired cursor or `since` token gives 410, one
  the server never gave 400 (or 410 if it cannot tell); a 416 carries `Content-Range: bytes */<size>`; a
  failure of the server answers 500 with the code `internal`.
- 0.2 (2026-10-30): a protocol of its own, with nothing kept for the
  protocols in use before it; still `/v1/` and `schema` 1, as a draft.
  - Discovery (§ 4.1): Lantern's own datagrams on UDP 47115, a DNS-SD
    `_lantern._tcp` advertisement, and discovery as a hint only. Ownfoil's
    datagram and port are gone.
  - Authentication (§ 5): bearer tokens only, per device, hashed by the
    server, revocable, possibly expiring; HTTP Basic is gone. Pairing is
    required of a private server, approved on the server's side only, with
    codes of an unambiguous alphabet (40 bits at least) that expire within
    10 minutes and are rate-limited (429 `slow_down`). `pairing` is offered
    to every caller, anonymous included.
  - Transport (§ 2, § 5.3): HTTPS everywhere, plain HTTP on loopback only;
    a self-signed key is pinned at pairing, after the user compared its
    SPKI fingerprint on the console and on the server.
  - Integrity (§ 6.1, § 6.6): `sha256` is required on every app,
    `Repr-Digest` on every file response, and a client always checks a
    download before installing it.
- 0.3 (2026-10-30): every platform, and four families; still `/v1/` and
  `schema` 1, as a draft. Files become § 6.6, and the sections from 7 on
  are renumbered.
  - Platforms (§ 4.3, Annex A): a neutral core and a profile per platform.
    Every app, title, homebrew, save and cheat set carries `platform`; the
    handshake lists `platforms`; a client names its own with
    `Lantern-Platform` (or `?platform=`), and the server answers for it
    alone. Atlas's platform names, and `3ds`, `vita`, `ps4`, `android`,
    `ios`, `windows`, `macos`, `linux` and `web`. Profiles: the Switch's
    complete; the 3DS's, the Vita's, the PS4's and Android's as drafts; the
    others open.
  - Apps (§ 6.1): `title_id` and `app_id` are opaque strings of the
    profile's form, `type` and `format` come from its lists, and `version`
    and `display_version` become `version_code` and `version_name`. What
    is missing (§ 6.3) needs a platform.
  - Titles (§ 7): `titles` replaces `media`, with developer, genres from a
    fixed list and tags, players on one console and online, age ratings
    per organisation, a localized summary and description, images and an
    external video, and `updated`; many titles in one request, and their
    changes.
  - Homebrew (§ 8): a new family: entries with a stable reverse-DNS id, a
    `build` to compare, packages of one file or a zip with a manifest, the
    rules a client follows to install and uninstall them, an optional
    ed25519 signature whose key is pinned per id, and the updates of what
    is installed. Mods are out of scope.
  - Saves (§ 9): resumable uploads in chunks; `Content-Digest` required on
    a save sent in one request, and checked (422 `digest_mismatch`); a
    save's `kind`, `game_version_code`, `profile` and `platform`; the
    handshake's `limits` say the sizes and how many backups are kept.
  - Cheats (§ 10): several sets per build, each with its id, source,
    update time and SHA-256, read by id.
  - Requests (§ 11) carry `platform`.
