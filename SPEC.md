# Lantern — an open protocol for game library servers

Draft 0.2, 2026-10-30. Status: **draft**, open to change until 1.0.
This text is licensed under [CC BY 4.0](LICENSES/CC-BY-4.0.txt).

Lantern lets a client on a console (a homebrew) browse a library server the
user runs for their own games, download from it with integrity checks, and
keep save backups and cheats there. It is a small REST/JSON contract,
versioned so that a client and a server of different ages keep working
together. It is a protocol of its own: it owes nothing to the protocols in
use before it and keeps nothing for their sake.

The key words MUST, SHOULD and MAY are used as in RFC 2119.

## 1. Principles

1. **Small and fixed.** Few routes, fixed shapes, no query language. A server
   fits in a weekend; a client in a few hundred lines of C++.
2. **Versioned twice.** A major protocol version in the path (`/v1/`) for
   breaking changes; an integer `schema` in every document for the rest
   (§ 3).
3. **Declared, never guessed.** The server says what it offers (`features`);
   the client says who it is (`User-Agent`). No header sniffing.
4. **Structured identity, verified content.** Every package has its title
   id, app id, type, integer version, size, format and SHA-256, and every
   download is checked against it. File names carry no meaning.
5. **Secure by default.** HTTPS everywhere, a key pinned at pairing on the
   LAN, a revocable token per device. No password ever goes through the
   console.
6. **HTTP as it is.** Real status codes, `application/problem+json` errors,
   ranges, `ETag`, `Repr-Digest`.
7. **Nothing hidden, nothing intrusive.** No hardware identifier, no
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
- The client MUST send `User-Agent: <Name>/<version>` and SHOULD send
  `Accept-Language`.
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

## 4. Discovery and handshake

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
 "motd": "New this week: two co-op games.",
 "account": {"name": "lea", "state": "active", "scopes": ["library", "saves"]},
 "features": {"library": 1, "media": 1, "changes": 1, "sections": 1,
              "saves": 1, "cheats": 1, "requests": 0, "pairing": 1},
 "limits": {"page_size": 500}}
```

- `uid`: a UUID that never changes for this server. A client uses it to
  recognise the same server on the LAN and on the WAN, and to find the key
  it pinned (§ 5.3).
- `account.state`: `anonymous` (no token), `active`, or `frozen` (the
  account exists but may do nothing; `motd` says why).
- `account.scopes`: what this caller may do: `library`, `saves`,
  `cheats`, `cheats.write`, `requests`, `admin`.
- `features.<family>`: the `schema` the server writes for that family, or
  `0` when it does not offer it **to this caller**. `pairing` is the same
  for every caller, anonymous included: whoever can reach the server can ask
  to pair.
- A call without a token to a private server returns the document with
  `account.state` `anonymous` and every feature at 0 but `pairing`, so a
  client can show the server's name and pair. A wrong token gives `401` here
  as elsewhere (§ 5.1): only its absence gives that document.
- A route of a family at 0 answers `404` (the server does not offer it) or
  `401`/`403` (not to this caller), never `2xx`.

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
 "title_id": "0100ABCD00010000",
 "app_id": "0100ABCD00010800",
 "type": "update",
 "version": 196608,
 "display_version": "1.3.0",
 "name": "Frostline Tales",
 "size": 734003200,
 "format": "nsz",
 "sha256": "3a7bd3e2…",
 "added": "2026-10-28T19:02:11Z",
 "file": "<base>/v1/files/f_Zk…"}
```

- `id`: opaque, stable while the file does not change.
- `title_id`: the base game's id; `app_id`: this package's id. Both 16
  upper-case hex digits.
- `type`: `base`, `update` or `dlc`.
- `version`: an integer; clients compare integers, never text.
- `size`: bytes, a 64-bit integer.
- `format`: `nsp`, `nsz`, `xci` or `xcz`.
- `sha256`: of the file as served, lower-case hex. Required: a server hashes
  a file before it lists it.

### 6.2 Listing

`GET <base>/v1/apps?type=&title_id=&q=&sort=&page_size=&cursor=` →

```json
{"schema": 1, "items": [App, …], "total": 4123, "next": "c_…"}
```

- `sort`: `name` (the default), `added` or `release` (both newest first);
  ties are broken by `id`, so the order is stable.
- `cursor` is opaque; `next` is `null` on the last page. Reading with a
  cursor while the library changes neither skips nor repeats an app.
- An expired cursor gives `410`, and the client reads the list from its
  start. One the server never gave, or gave for another listing, gives
  `400`, or `410` when the server cannot tell it from an expired one.
- `page_size` is at most `limits.page_size`; a larger one is lowered to it.

### 6.3 What the console is missing

`POST <base>/v1/apps/missing`

```json
{"schema": 1,
 "installed": [{"app_id": "0100ABCD00010000", "version": 0},
               {"app_id": "0100ABCD00010800", "version": 131072}],
 "want": ["update", "dlc"]}
```

→ a listing (§ 6.2) of the newest update of each installed game newer than
the installed one, the add-ons of installed games not installed, and, with
`base` in `want`, the games not installed. Paginated with `cursor` in the
query.

### 6.4 Changes (feature `changes`)

`GET <base>/v1/changes?since=<token>` → `{"schema":1, "added":[App…],
"removed":["a_…"], "since":"<next token>"}`. Without `since`, it returns no
apps and the current token. A token too old for the server gives `410`: the
client reads the whole library again. One it never gave gives `400` (or
`410`, as for a cursor, § 6.2).

### 6.5 Sections (feature `sections`)

`GET <base>/v1/sections` → `{"schema":1, "sections":[{"id":"new",
"title":"New", "apps":["a_…", …]}, …]}`: shelves the server curates. A
client MAY show them next to its own.

### 6.6 Titles and media (feature `media`)

`GET <base>/v1/titles/{title_id}` →

```json
{"schema": 1, "title_id": "0100ABCD00010000", "language": "en",
 "name": "Frostline Tales", "publisher": "Fjord Works",
 "release": "2025-03-14", "players": {"min": 1, "max": 4},
 "languages": ["en", "fr", "ja"], "age": {"system": "PEGI", "rating": 7},
 "description": "…",
 "media": {"icon": {"url": "<base>/v1/media/9f2c….jpg", "width": 256, "sha256": "9f2c…"},
           "banner": {…}, "screenshots": [{…}]}}
```

- `language` says which language was served for `Accept-Language`.
- A media URL on the server's origin SHOULD be content-addressed and served
  with a long cache lifetime. A media object with `"external": true` points
  elsewhere: the client MUST NOT send it a token.

### 6.7 Files

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

## 7. Save backups (feature `saves`, scope `saves`)

- `GET <base>/v1/saves` → `{"schema":1, "saves":[{"title_id", "save_id",
  "created", "size", "sha256", "note", "device"}…]}`, newest first per
  title.
- `POST <base>/v1/saves/{title_id}`: the zip archive as the body
  (`Content-Type: application/zip`, `Content-Digest: sha-256=:…:`), the note
  in `Lantern-Note` (UTF-8, percent-encoded, 120 bytes at most) →
  `201` with the save entry.
- `GET` and `DELETE <base>/v1/saves/{title_id}/{save_id}`.
- The zip holds the save's files as they are in the save filesystem, at the
  root of the archive.

## 8. Cheats (feature `cheats`)

- `GET <base>/v1/cheats?title_id=` → `{"schema":1, "cheats":[{"title_id",
  "build_id", "note", "size", "sha256"}…]}`. `build_id`: upper-case hex, 1 to
  64 digits.
- `GET <base>/v1/cheats/{title_id}/{build_id}` → the text
  (`text/plain; charset=utf-8`, 1 MiB at most), as Atmosphère reads it from
  `atmosphere/contents/<title_id>/cheats/<build_id>.txt`.
- With scope `cheats.write`: `PUT` and `DELETE` on the same path.

## 9. Requests (feature `requests`)

- `GET <base>/v1/requests` → `{"schema":1, "requests":[{"id", "title_id",
  "name", "status", "created"}…]}`. `status`: `open`, `done` or `declined`.
- `POST <base>/v1/requests` `{"schema":1, "title_id":"…"}` → `201`, or `200`
  with the open request for the same title.

## 10. Errors

Every error is `application/problem+json` (RFC 9457) with a real status
code, never `200`:

```json
{"schema": 1, "type": "https://lantern.boreale.dev/errors/account-frozen",
 "title": "Account frozen", "status": 403, "code": "account_frozen",
 "detail": "Your access is paused until Sunday."}
```

| Status | `code` | When |
|---|---|---|
| 400 | `bad_request` | A malformed query or body; a cursor or `since` token the server never gave |
| 401 | `unauthorized` | No token where one is needed, or an unknown, revoked or expired one (with `WWW-Authenticate: Bearer`) |
| 403 | `forbidden`, `account_frozen` | A scope missing; a frozen account |
| 404 | `not_found` | |
| 405 | `bad_request` | A method the route does not take (with `Allow`) |
| 409 | `conflict` | |
| 410 | `gone` | An expired cursor, `since` token, pairing or file id |
| 413 | `too_large` | A save above the server's limit |
| 416 | `bad_request` | A range outside the file (with `Content-Range: bytes */<size>`) |
| 422 | `unsupported_schema` | A request document of a schema the server cannot read |
| 429 | `slow_down` | Too many requests, pairing attempts or polls (with `Retry-After`) |
| 500 | `internal` | A failure of the server itself; the client may try again later |
| 503 | `unavailable` | Scanning, maintenance (with `Retry-After`) |

`detail` is for people; a client shows it, bounded and without control
characters.

New codes MAY come with later versions of this text: a client that gets a
`code` it does not know acts on the status alone.

## 11. Limits

A client MUST bound what it reads and a server MUST stay within:

| What | At most |
|---|---|
| A JSON document | 32 MiB, nesting depth 16 |
| A string field | 4 KiB (`name` 512 bytes, `note` 120 bytes) |
| A page | 1000 items |
| A cheat file | 1 MiB |
| A discovery datagram | 1200 bytes |

## 12. Caching

Every `GET` returning JSON SHOULD carry an `ETag` and honour
`If-None-Match` with `304`. Responses to authenticated calls carry
`Cache-Control: private` and `Vary: Authorization`.

## 13. Security and privacy

- No hardware identifier, no tracking header. A server knows a device only
  by the name its user gave it during pairing.
- No password goes through the console: it holds a token per server, which
  the user can revoke from the server (§ 5).
- No proprietary encryption of documents: TLS protects them, with a key
  pinned at pairing when no CA vouches for it (§ 5.3).
- Discovery is a hint, never a proof (§ 4.1).
- A server cannot change a client's settings or add headers to its later
  requests.
- A client MUST check a download's SHA-256 before installing it (§ 6.7).
- Servers are for the user's own games.

## 14. Conformance

A conformance suite (`conformance/`) runs against a server's URL, with a
token or without, and checks every MUST of this text it can see from
outside: shapes and `schema`, the token challenge, pairing's shapes,
ranges, digests, error format, limits, the refusal of an unknown request
`schema`. A reference server (`server/`) serves a folder of packages and
passes the suite.

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
  - Integrity (§ 6.1, § 6.7): `sha256` is required on every app,
    `Repr-Digest` on every file response, and a client always checks a
    download before installing it.
