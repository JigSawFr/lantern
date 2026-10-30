# Lantern — an open protocol for game library servers

Draft 0.1, 2026-10-30. Status: **draft**, open to change until 1.0.
This text is licensed under [CC BY 4.0](LICENSES/CC-BY-4.0.txt).

Lantern lets a client on a console (a homebrew) browse a library server the
user runs for their own games, download from it with integrity checks, and
keep save backups and cheats there. It is a small REST/JSON contract,
versioned so that a client and a server of different ages keep working
together.

The key words MUST, SHOULD and MAY are used as in RFC 2119.

## 1. Principles

1. **Small and fixed.** Few routes, fixed shapes, no query language. A server
   fits in a weekend; a client in a few hundred lines of C++.
2. **Versioned twice.** A major protocol version in the path (`/v1/`) for
   breaking changes; an integer `schema` in every document for the rest
   (§ 3).
3. **Declared, never guessed.** The server says what it offers (`features`);
   the client says who it is (`User-Agent`). No header sniffing.
4. **Structured identity, verifiable content.** Every package has its title
   id, app id, type, integer version, size, format and SHA-256. File names
   carry no meaning.
5. **Plain HTTP.** Real status codes, `application/problem+json` errors,
   ranges, `ETag`, `Repr-Digest`.
6. **Nothing hidden, nothing intrusive.** No hardware identifier, no
   proprietary encryption, no server-driven change to the client's settings.

## 2. Transport

- HTTPS. A client MUST verify the certificate against its CA store, or
  against a key it pinned on first use for a LAN server the user trusted
  (§ 5.3). Plain HTTP MAY be accepted by a client only for a LAN address the
  user typed, and never for credentials.
- All routes live under a base path the server chooses (default
  `/api/lantern`), announced by discovery (§ 4). Below, paths are relative to
  `<base>`.
- JSON bodies are UTF-8, `Content-Type: application/json`.
- The client MUST send `User-Agent: <Name>/<version>` and SHOULD send
  `Accept-Language`.
- Credentials (§ 5) are sent only to the server's origin (scheme, host,
  port), never to another host a document points at.

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

Lantern reuses Ownfoil's discovery, which three clients already speak:

- The client broadcasts the ASCII datagram `OWNFOIL_DISCOVER` to UDP port
  8465 (directed broadcast: the Switch drops 255.255.255.255).
- A server answers with a JSON object:

  ```json
  {"magic": "OWNFOIL", "uid": "6f1c2a8e-…", "name": "Living room shelf",
   "version": "2.7.0", "port": 8465, "public": false,
   "remote": "https://shelf.example.org",
   "lantern": {"schema": 1, "base": "/api/lantern", "versions": [1]}}
  ```

- The server's address is the datagram's source address. `lantern` is
  present only on servers that speak Lantern; a client that does not know
  it ignores it.
- The reply keeps Ownfoil's shape, which has no `schema`; Lantern's own
  part, `lantern`, carries one.

### 4.2 Handshake

`GET /.well-known/lantern` (at the origin's root) and `GET <base>/v1/` return
the same document, with or without credentials:

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
  recognise the same server on the LAN and on the WAN.
- `account.state`: `anonymous` (no credentials, public server), `active`,
  or `frozen` (the account exists but may do nothing; `motd` says why).
- `account.scopes`: what this account may do: `library`, `saves`,
  `cheats`, `cheats.write`, `requests`, `admin`.
- `features.<family>`: the `schema` the server writes for that family, or
  `0` when it does not offer it **to this caller**.
- An unauthenticated call to a private server returns the document with
  `account.state` `anonymous` and every feature at 0, so a client can show
  the server's name before asking for credentials. Wrong credentials give
  `401` here as elsewhere (§ 5.1): only their absence gives that document.
- A route of a family at 0 answers `404` (the server does not offer it) or
  `401`/`403` (not to this caller), never `2xx`.

## 5. Authentication

### 5.1 HTTP Basic

Every server MUST accept HTTP Basic over TLS. A missing or wrong password,
or an unknown token (§ 5.2), gives `401` with
`WWW-Authenticate: Basic realm="…"`; a right password without the scope
gives `403`.

### 5.2 Pairing (feature `pairing`)

So that a console keeps a revocable token instead of a password. Modelled
on the OAuth device flow (RFC 8628), without OAuth's other parts:

1. `POST <base>/v1/pairing` `{"schema":1, "device":"Lea's Switch",
   "scopes":["library","saves"]}` → `{"schema":1, "code":"KQ4M-7TXD",
   "verify":"https://shelf.example.org/pair", "poll":"<base>/v1/pairing/p_…",
   "interval":5, "expires":600}`.
2. The console shows the code; the user enters it on the server's web page
   while signed in, and approves the scopes.
3. The console polls `GET poll` every `interval` seconds: `202` while
   waiting, then `200` `{"schema":1, "token":"et_…", "scopes":[…]}`, or
   `410` when refused or expired.
4. Later calls send `Authorization: Bearer et_…`. The server lists tokens
   by device name and lets the user revoke them.

### 5.3 Pinning on the LAN

A LAN server often has a self-signed certificate. A client MAY show the
SHA-256 of its public key (SPKI) and, once the user compared and accepted
it, pin it for that `uid`. A key that changes afterwards MUST fail.

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
- `sha256`: of the file as served, lower-case hex. A server that has not
  hashed a file yet omits it; a client MAY then refuse or warn.

### 6.2 Listing

`GET <base>/v1/apps?type=&title_id=&q=&sort=&page_size=&cursor=` →

```json
{"schema": 1, "items": [App, …], "total": 4123, "next": "c_…"}
```

- `sort`: `name` (the default), `added` or `release` (both newest first);
  ties are broken by `id`, so the order is stable.
- `cursor` is opaque; `next` is `null` on the last page. Reading with a
  cursor while the library changes neither skips nor repeats an app.
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
client reads the whole library again.

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
  elsewhere: the client MUST NOT send it credentials.

### 6.7 Files

`GET <file>`:

- MUST support `Range` (`206`, `416`) and send `Content-Length`,
  `Accept-Ranges: bytes`, a strong `ETag` and `Repr-Digest:
  sha-256=:<base64>:` (RFC 9530) when the hash is known.
- The id in the path is opaque and not enumerable. It MAY expire: the
  client then reads the app again.
- A server MAY offer a decompressed form of a compressed file under its own
  app entry (its own `format`, `size` and `sha256`), never silently.

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
| 400 | `bad_request` | A malformed query or body |
| 401 | `unauthorized` | No or wrong credentials (with `WWW-Authenticate`) |
| 403 | `forbidden`, `account_frozen` | A scope missing; a frozen account |
| 404 | `not_found` | |
| 405 | `bad_request` | A method the route does not take (with `Allow`) |
| 409 | `conflict` | |
| 410 | `gone` | An expired cursor, `since` token, pairing or file id |
| 413 | `too_large` | A save above the server's limit |
| 416 | `bad_request` | A range outside the file (with `Content-Range: bytes */<size>`) |
| 422 | `unsupported_schema` | A request document of a schema the server cannot read |
| 429 | `slow_down` | With `Retry-After` |
| 503 | `unavailable` | Scanning, maintenance (with `Retry-After`) |

`detail` is for people; a client shows it, bounded and without control
characters.

## 11. Limits

A client MUST bound what it reads and a server MUST stay within:

| What | At most |
|---|---|
| A JSON document | 32 MiB, nesting depth 16 |
| A string field | 4 KiB (`name` 512 bytes, `note` 120 bytes) |
| A page | 1000 items |
| A cheat file | 1 MiB |

## 12. Caching

Every `GET` returning JSON SHOULD carry an `ETag` and honour
`If-None-Match` with `304`. Responses to authenticated calls carry
`Cache-Control: private` and `Vary: Authorization`.

## 13. Security and privacy

- No hardware identifier, no tracking header. A server knows a device only
  by the name its user gave it during pairing.
- No proprietary encryption of documents: TLS protects them.
- A server cannot change a client's settings or add headers to its later
  requests.
- A client MUST check `sha256` after a download before installing, when the
  server gave one.
- Servers are for the user's own games.

## 14. Conformance

A conformance suite (`conformance/`) runs against a server's URL and
credentials and checks every MUST of this text it can see from outside:
shapes and `schema`, ranges, digests, error format, limits, the refusal of
an unknown request `schema`. A reference server (`server/`) serves a folder
of packages and passes the suite.

## Changes

- 0.1 (2026-10-30): first draft.
- 0.1 (2026-10-30), from the conformance suite: wrong credentials give 401
  on the handshake too, and so does an unknown token; a family at 0 answers
  404, 401 or 403; `sort` defaults to `name` and `release` is newest first;
  a `page_size` above the limit is lowered to it; codes for 405 and 416.
