# Lantern — an open protocol for game library servers

Draft 0.4, 2026-10-30. Status: **draft**, open to change until 1.0.
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

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT and MAY are used
as in RFC 2119 and RFC 8174, in capitals only. Each requirement has a stable
id written next to it in brackets, such as [L-5.2-3]: § 3.5 says how ids are
kept, and the conformance suite (§ 17) names the ones each of its checks
covers. Annex B is advice to client authors, without requirements.

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
   LAN, a revocable token per device, bound to a key the device made. No
   password ever goes through the device. A homebrew writes only where its
   manifest says and the user allows.
7. **HTTP as it is.** Real status codes, `application/problem+json` errors,
   ranges, `ETag`, `Repr-Digest`, `Content-Digest`, HTTP Message Signatures.
8. **Nothing hidden, nothing intrusive.** No hardware identifier, no
   proprietary encryption, no server-driven change to the client's settings.

## 2. Transport

- HTTPS. A client MUST verify the certificate against its CA store, or
  against the key it pinned at pairing (§ 5.3). [L-2-1]
- Plain HTTP is allowed only on loopback addresses (`127.0.0.0/8`, `::1`),
  for testing. A client MUST NOT speak plain HTTP to any other address.
  [L-2-2] A server MUST NOT serve Lantern in plain HTTP on one. [L-2-3]
- All routes live under a base path the server chooses (default
  `/api/lantern`), announced by discovery (§ 4.1) and the handshake (§ 4.2).
  Below, paths are relative to `<base>`.
- JSON bodies MUST be UTF-8, sent with `Content-Type: application/json`
  (errors: `application/problem+json`, § 12). [L-2-4]
- The client MUST send `User-Agent: <Name>/<version>`. [L-2-5] It SHOULD
  send `Accept-Language` (§ 2.2). [L-2-6] It SHOULD send `Lantern-Platform`
  (§ 4.3). [L-2-7]
- A client MUST send its token (§ 5) and its signatures only to the
  server's origin (scheme, host, port), never to another host a document
  points at. [L-2-8]

### 2.1 Compression and HTTP versions

- A server SHOULD offer `Content-Encoding` on its JSON responses, as the
  client's `Accept-Encoding` asks: `zstd` (RFC 8878) or `br` (RFC 7932),
  and `gzip`. [L-2.1-1] A client MAY ask for them; one that does not ask
  gets JSON as it is.
- A server MUST NOT apply a `Content-Encoding` to a file response (§ 6.6),
  whatever `Accept-Encoding` says: packages are compressed by their own
  formats already, and ranges and `Repr-Digest` are about the bytes as
  stored. [L-2.1-2]
- A response a server compresses MUST carry `Vary: Accept-Encoding`, and an
  `ETag` other than the uncompressed one's (RFC 9110 § 8.8.3). [L-2.1-3]
- A client sends its request bodies without `Content-Encoding`. The limits
  of § 13 apply to a document once decompressed.
- Lantern works the same over HTTP/1.1 and HTTP/2 (RFC 9113); nothing in it
  depends on the version. A server MAY offer HTTP/2 through ALPN and a
  client MAY use it: one connection then carries a page, its titles and
  their images at once, and its header compression makes the headers every
  request repeats (`Authorization`, `Signature-Input`, `Lantern-Platform`)
  cheap. A signature covers `@target-uri` (§ 5.4), which HTTP/2's
  pseudo-headers give as HTTP/1.1's request line does.

### 2.2 Languages

The client's `Accept-Language` (RFC 9110 § 12.5.4) chooses the language of
the texts a server writes for people: a title's and a homebrew's `summary`,
`description` and `hint`s (§ 7.1, § 8), an error's `title` and `detail`
(§ 12), and the handshake's `motd` (§ 4.2).

- A server SHOULD answer in the best language it has for `Accept-Language`,
  and in English when it has none of them. [L-2.2-1]
- A document with such texts MUST say their language in its `language`
  (a title's, a homebrew's, a problem's, the handshake's). [L-2.2-2] Its
  response SHOULD also carry `Content-Language`. [L-2.2-3]
- Codes, field names and listed values (`code`, `kind`, `genres`, `state`)
  never change with the language.

## 3. Versions

### 3.1 Protocol version

The major version is in the path: `<base>/v1/…`. It changes only for a
break that `schema` cannot express. A server lists the versions it serves
(`versions` in § 4.2) and SHOULD keep an old major version while clients
still call it. [L-3.1-1]

### 3.2 Document schema

Every JSON document a server returns, and every document a client sends,
MUST have an integer `schema` at its top level. [L-3.2-1]

- Adding a field keeps `schema`. A field that changes meaning, unit or type,
  or disappears, makes it go up.
- A reader MUST ignore fields it does not know. [L-3.2-2]
- A reader that gets a `schema` higher than it knows MUST treat the document
  as absent (the feature is unavailable), not as an error. [L-3.2-3] It
  MUST NOT write it back. [L-3.2-4]
- Every document has a JSON Schema in `schemas/v1/` (2020-12), with an
  example in `examples/v1/`. The schemas describe schema 1 and allow fields
  they do not list, as a reader must. A server's documents MUST be valid
  against them. [L-3.2-5]
- A server MUST answer a request document of a `schema` it cannot read with
  `422` `unsupported_schema` (§ 12). [L-3.2-6]
- `features` (§ 4.2) gives, per family, the `schema` the server writes; a
  client MAY send `Accept-Schema: <family>=<n>, …` to ask for an older one,
  which a server SHOULD honour while it still can write it. [L-3.2-7]

### 3.3 Extensions

Fields and routes of a vendor's own begin with `x-<vendor>-` (field) or
live under `<base>/x/<vendor>/` (routes). Clients ignore them unless they
know them.

### 3.4 Deprecation and sunset

A route, a query parameter or a family's older `schema` that is going away
is announced on the responses that use it, with two headers:

```http
Deprecation: @1793318400
Sunset: Sun, 01 Aug 2027 00:00:00 GMT
Link: <https://lantern.boreale.dev/spec/#34-deprecation-and-sunset>; rel="deprecation"
```

- `Deprecation` (RFC 9745): since when it is deprecated, a Structured
  Fields date (`@` and Unix seconds). A server MUST send it on every
  response of a route, or in a schema, that it has deprecated. [L-3.4-1]
- `Sunset` (RFC 8594): the HTTP date after which it may stop answering. A
  server SHOULD send it once it knows that date. [L-3.4-2] It MUST NOT stop
  a deprecated route or schema before its `Sunset`. [L-3.4-3]
- An older schema stays served while clients read it: a server MUST keep
  writing it to the clients that ask for it with `Accept-Schema` (§ 3.2)
  at least until its `Sunset`. [L-3.4-4]
- A `Link` with `rel="deprecation"` MAY point at a page that says what
  replaces it.
- A client SHOULD record a `Deprecation` it gets where its developers will
  see it (a log, a report), and move to what replaces it before the
  `Sunset`. [L-3.4-5]

### 3.5 Changes and proposals

How the text changes:

1. A change starts as an issue with the repository's **Proposal** template:
   the problem, with a real case; the change (routes, fields, codes, the
   sections it touches); its effect on `schema`; how the conformance suite
   checks it; and what a client or a server that ignores it does.
2. Once it is agreed, one pull request changes SPEC.md, the schemas and
   their examples, `openapi.yaml`, the test vectors (§ 17), the suite and
   the reference server together, so that the suite never lags behind the
   text. The text's version and date go up, and its section "Changes" says
   what changed.
3. Its effect on versions:
   - an addition (a field, a route, a code, a value of a list a reader is
     told to tolerate, such as a `kind` or a genre) keeps `schema` and
     `/v1/`;
   - a field that changes meaning, unit or type, or disappears, raises the
     document's `schema`: the server writes the new one, and the old one,
     marked deprecated (§ 3.4), to the clients that ask for it;
   - a break `schema` cannot express (a route's meaning, the
     authentication) is a new major version, `/v2/`, served next to `/v1/`
     (§ 3.1).
4. Requirement ids: `L-<section>-<n>`, given once. A requirement keeps its
   id when its words or its place change; a new one takes the next free
   number of its section; the id of one that goes is never given again.

Until 1.0, the drafts keep `/v1/` and `schema` 1: a draft may still change
a shape another draft wrote, and its section "Changes" says so.

## 4. Discovery, handshake and platforms

### 4.1 On the LAN

Lantern has its own discovery, on UDP port **47115**:

- The client sends the datagram `{"schema":1,"lantern":"discover"}` to port
  47115 as a directed broadcast (the subnet's broadcast address, such as
  `192.168.1.255`: some consoles drop `255.255.255.255`).
- A server answers unicast, to the datagram's source, with:

  ```json
  {"schema": 1, "lantern": "server", "uid": "6f1c2a8e-…",
   "name": "Living room shelf", "port": 443, "base": "/api/lantern",
   "versions": [1]}
  ```

- The server's address is the reply's source address; `port` is its HTTPS
  port, `base` and `versions` as in the handshake (§ 4.2). A server's reply
  MUST give the `uid`, `base` and `versions` of its handshake, and the port
  it answers HTTPS on. [L-4.1-1]
- Each datagram is UTF-8 JSON of at most 1200 bytes. A server answers only a
  request it can read (§ 3.2) and stays silent otherwise. It SHOULD answer
  only addresses of its own networks. [L-4.1-2] It SHOULD answer only a few
  times a second to the same address. [L-4.1-3]
- A server SHOULD also advertise itself with DNS-SD (RFC 6763) as
  `_lantern._tcp`, with the TXT keys `uid=<uid>`, `path=<base>` and `v=1`
  (the versions, comma-separated). [L-4.1-4]
- Discovery is a hint: it finds an address and a name, nothing more. A
  reply proves nothing, and a client MUST trust a server only through TLS
  and pairing (§ 5). [L-4.1-5]

### 4.2 Handshake

`GET /.well-known/lantern` (at the origin's root) and `GET <base>/v1/` MUST
return the same document, with or without a token. [L-4.2-1]

```json
{"schema": 1,
 "uid": "6f1c2a8e-…",
 "name": "Living room shelf",
 "software": {"name": "ExampleShelf", "version": "2.7.0"},
 "base": "/api/lantern",
 "versions": [1],
 "platforms": ["switch", "android"],
 "motd": "New this week: two co-op games.", "language": "en",
 "account": {"name": "lea", "state": "active", "scopes": ["library", "saves"],
             "bound": true, "rating_cap": {"age": 12}},
 "features": {"library": 1, "titles": 1, "changes": 1, "sections": 1,
              "homebrew": 1, "saves": 1, "cheats": 1, "requests": 0,
              "pairing": 1, "signatures": 1, "admin": 0},
 "auth": {"bearer_only": true, "skew": 300},
 "limits": {"page_size": 500, "save_body": 8388608,
            "save_size": 1073741824, "saves_kept_per_title": 10}}
```

- `uid`: a UUID that never changes for this server. A client uses it to
  recognise the same server on the LAN and on the WAN, and to find the key
  it pinned (§ 5.3).
- `platforms`: the platforms the server has something for (§ 4.3). It MUST
  list every platform of an app, a homebrew or a cheat set it serves, and
  be the same for every caller. [L-4.2-2]
- `motd`, optional: a message for people, in `language` (§ 2.2).
- `account.state`: `anonymous` (no token), `active`, or `frozen` (the
  account exists but may do nothing; `motd` says why). Without a token, the
  handshake MUST answer `200` with `account.state` `anonymous`. [L-4.2-3]
- `account.scopes`: what this caller may do: `library`, `saves`,
  `cheats`, `cheats.write`, `requests`, `admin`. `library` covers every
  read of the catalogue: apps, titles and homebrew.
- `account.bound`: whether the caller's token is bound to a device key
  (§ 5.4); `account.rating_cap`: the rating cap its token carries, if any
  (§ 5.6).
- `features.<family>`: the `schema` the server writes for that family, or
  `0` when it does not offer it **to this caller**. [L-4.2-4] `pairing` and
  `signatures` MUST be the same for every caller, anonymous included:
  whoever can reach the server can ask to pair. [L-4.2-5]
- `auth` (§ 5.4): `bearer_only`, whether the server still issues and takes
  tokens that no key binds; `skew`, how many seconds a signature's
  `created` may differ from the server's clock.
- `limits`: `page_size`, the most items on a page (§ 6.2); with `saves`,
  `save_body`, the largest save a single request takes (§ 9.2),
  `save_size`, the largest save at all (§ 9.3), and
  `saves_kept_per_title`, how many backups the server keeps per title,
  platform and account before it drops the oldest (§ 9.1).
- A call without a token to a private server returns the document with
  `account.state` `anonymous` and every feature at 0 but `pairing` and
  `signatures`, so a client can show the server's name and pair. A frozen
  account's handshake has every feature at 0 but those two. A wrong token
  MUST give `401` here as elsewhere (§ 5.1): only its absence gives that
  document. [L-4.2-6]
- A route of a family at 0 MUST answer `404` (the server does not offer it)
  or `401`/`403` (not to this caller), never `2xx`. [L-4.2-7] A route of a
  family above 0 MUST answer as this text says. [L-4.2-8]

### 4.3 Platforms

A platform is a lower-case name: 1 to 32 letters, digits and `-`, starting
with a letter or a digit. The names are those of
[Atlas](https://github.com/JigSawFr/Atlas) where Atlas has one (`switch`,
`steam`, `gog`, `xbox`); for the others, this text adds `3ds` (the New
Nintendo 3DS and the 3DS family), `vita` (PlayStation Vita), `ps4`,
`android`, `ios` (iOS, iPadOS and tvOS), `windows`, `macos`, `linux` (any
Linux system, a computer or a handheld, whatever its distribution: there is
no name per distribution) and `web` (an app run in a browser). A later
version adds names to this list; a vendor's own begins with `x-<vendor>-`.

- Every app (§ 6.1), title (§ 7), homebrew (§ 8), save (§ 9) and cheat set
  (§ 10) carries its `platform`.
- A client says its own platform with the header
  `Lantern-Platform: <name>` on every call.
- With the header, a server MUST answer for that platform only: the apps'
  listing, what is missing (§ 6.3), changes (§ 6.4), sections, titles,
  homebrew, saves and cheats list and read only what is of that platform;
  anything else is `404`. [L-4.3-1] A platform the server does not serve
  MUST give empty lists, not an error. [L-4.3-2] A name that is not a
  platform name MUST give `400`. [L-4.3-3]
- Without the header, a server answers for every platform, but where a
  route needs one: `POST <base>/v1/apps/missing` (§ 6.3),
  `POST <base>/v1/homebrew/updates` (§ 8.5) and the routes that write a save
  (§ 9) MUST give `400` without a platform. [L-4.3-4] A route that names a
  `title_id` or a homebrew `id` known on several platforms gives `400` too,
  until the client names the platform.
- `?platform=<name>` on a listing (or on a route that needs a platform)
  MUST override the header. [L-4.3-5]
- Responses that depend on the platform SHOULD carry
  `Vary: Lantern-Platform` (§ 14). [L-4.3-6]
- A platform's profile (Annex A) says what the core leaves open. On a
  platform with no profile yet (Annex A.7), a server MAY serve apps and
  homebrew under the core's rules alone; a client MUST NOT install
  anything of a platform it has no profile for. [L-4.3-7] The same holds
  for what a profile leaves out: Linux's has no apps yet (Annex A.6), so a
  client installs none of them.

## 5. Authentication and access

### 5.1 Tokens

- Every authenticated call sends `Authorization: Bearer <token>` (RFC 6750),
  signed when the token is bound to a key (§ 5.4). There is no other
  scheme: a server MUST refuse a password and HTTP Basic, on any route, and
  never ask for them. [L-5.1-1]
- A token is opaque to the client and has at least 128 bits of entropy.
  [L-5.1-2] The server MUST keep only a hash of it. [L-5.1-3] It gives one
  per device, with the scopes the user approved (§ 5.2), and MUST let the
  user list and revoke them. [L-5.1-4] A token MAY expire.
- A missing token where one is needed, or an unknown, revoked or expired
  one, MUST give `401` with `WWW-Authenticate: Bearer` (and
  `error="invalid_token"` when a token was sent). So does an
  `Authorization` of another scheme. [L-5.1-5] A valid token without the
  scope MUST give `403` `forbidden`; one of a frozen account, `403`
  `account_frozen`. [L-5.1-6]
- A token never holds a scope its account does not hold: an account's
  scopes cut back, its tokens' are too.
- A public server answers calls without a token, as the account
  `anonymous` (§ 4.2), for the scopes it gives everyone.

### 5.2 Pairing (feature `pairing`)

How a device gets its token, modelled on the OAuth device flow (RFC 8628)
without OAuth's other parts. A private server MUST offer it. [L-5.2-1] A
public one MAY, for what it gives beyond anonymous calls.

1. `POST <base>/v1/pairing` `{"schema":1, "device":"Lea's Switch",
   "scopes":["library","saves"], "key":{"alg":"ed25519",
   "public_key":"<base64>"}}`, without a token → `200` `{"schema":1,
   "code":"KQ4M-7TXD", "verify":"https://shelf.example.org/pair",
   "verify_complete":"https://shelf.example.org/pair?code=KQ4M-7TXD",
   "poll":"<base>/v1/pairing/p_…", "interval":5, "expires":600}`. `key`
   is the device's public key (§ 5.4); `invitation`, a code of an
   invitation (§ 5.5).
2. The device shows the code, the address `verify`, and the short
   fingerprint of the server's key (§ 5.3). The user opens `verify` on
   another device, signs in there by the server's own means, enters the
   code, compares the fingerprint, and approves the device and its scopes.
   Approval happens only on the server's side: its web page, or an admin's
   device through § 5.7. It MUST NOT happen through the device that pairs:
   no password goes through it. [L-5.2-2]
3. The device polls `GET poll` every `interval` seconds. The server MUST
   answer `202` while waiting, then `200` `{"schema":1, "token":"et_…",
   "scopes":[…], "bound":true}` once, and `410` when refused, expired,
   already collected or unknown. [L-5.2-3] The scopes MUST be those
   approved, at most those asked for and those of the account. [L-5.2-4]
   `expires`, when present, is the token's lifetime in seconds;
   `rating_cap`, the cap the token carries (§ 5.6). A pairing that sent a
   `key` polls with signed requests (§ 5.4).
4. Later calls send `Authorization: Bearer et_…` (§ 5.1), signed (§ 5.4).

- The code MUST use the alphabet `23456789ABCDEFGHJKLMNPQRSTUVWXYZ` (no
  `0`, `O`, `1` or `I`), have 8 to 32 symbols (at least 40 bits), and be
  shown in groups of 4 joined by `-`. [L-5.2-5] The server ignores case,
  spaces and dashes when the user types it.
- A code MUST expire within 10 minutes (`expires`, in seconds, at most
  600). [L-5.2-6] The poll address MUST be unguessable (at least 128 bits)
  and give the token once. [L-5.2-7]
- The server MUST limit pairing requests per address and attempts at a
  code: beyond them it answers `429` `slow_down` with `Retry-After`.
  [L-5.2-8] It SHOULD answer `429` `slow_down` to polls more often than
  `interval`. [L-5.2-9]

**With a QR code.** `verify_complete` is `verify` with the code in its
query (RFC 8628's `verification_uri_complete`), so that the user need not
type it:

- A server MUST give `verify_complete`, on its origin, the code in it.
  [L-5.2-10] Opening it MUST NOT approve anything by itself: the user still
  signs in, sees the device, its scopes and the fingerprint, and approves.
  [L-5.2-11]
- A client SHOULD show `verify_complete` as a QR code, which it draws
  itself: the server serves no image. [L-5.2-12] It MUST keep the code and
  the server's short fingerprint shown next to the QR code. [L-5.2-13] The
  user scans it with a phone, compares the fingerprint the page shows with
  the console's, and approves there.

### 5.3 Pinning, at pairing

A server whose certificate the client's CA store accepts needs nothing
more. Otherwise (a LAN server with a self-signed certificate):

- The fingerprint is the SHA-256 of the server's public key, its DER
  `SubjectPublicKeyInfo` (SPKI). Its short form, for people, is its first 16
  hex digits, upper-case, in groups of 4: `3F9A 1C07 B2E4 55D0`. Test
  vectors: `vectors/spki.json`.
- During pairing, the device MUST show the short form of the key it sees,
  next to the code. [L-5.3-1] The server's approval page MUST show the
  short form of its own. [L-5.3-2] The user approves only when they match.
- Once paired, the client MUST pin the whole SHA-256 for that server's
  `uid`. [L-5.3-3] It polls and calls only over connections with that key:
  a changed key MUST fail, whatever certificate carries it, until the user
  pairs again. [L-5.3-4]
- Before pairing, a client may read the handshake and ask for a code over a
  certificate it has not verified: it sends nothing secret then.
- A link of an invitation (§ 5.5) carries the whole fingerprint: a client
  that opens it pins that one, without asking the user to compare.

### 5.4 Device keys and signed requests (feature `signatures`)

A token bound to a key the device made is worth nothing without that key:
copied off the device, out of a log or a backup, it does not work on its
own.

**At pairing.** The device makes an Ed25519 key pair (RFC 8032) for this
server, keeps its private key with the token, and sends the public key with
its pairing request, `"key": {"alg": "ed25519", "public_key": "<base64 of
its 32 bytes>"}`. The server binds the token it issues to that key. A
device that pairs again makes a new key.

- A server that issues tokens MUST offer this feature: it takes `key` at
  pairing, binds the token to it, and checks the signatures below; its
  `features.signatures` is then 1, for every caller. [L-5.4-1]
- A client SHOULD send a key when it pairs. [L-5.4-2] A client that paired
  with a key MUST sign every request that carries its token. [L-5.4-3] It
  MUST NOT send its private key anywhere. [L-5.4-4] It SHOULD keep it where
  its system protects keys, when it has such a place. [L-5.4-5]
- A token issued without a key is **bearer-only**. A server MAY refuse to
  issue one, with `400` `key_required` to a pairing request without `key`,
  and MAY refuse the bearer-only tokens it issued before, with `401`
  `signature_required`. `auth.bearer_only` (§ 4.2) says whether it still
  issues and takes them.

**Signing a request** (RFC 9421, HTTP Message Signatures). A request that
carries a bound token carries a signature of these components, in this
order:

| Component | What |
|---|---|
| `"@method"` | The method, in capitals (`GET`). |
| `"@target-uri"` | The request's absolute URI (RFC 9421 § 2.2.2): the scheme, the host as in `Host`, in lower case, its port only when it is not the scheme's default, then the path and query exactly as sent, their percent-encoding unchanged. |
| `"authorization"` | The `Authorization` header's value as sent. |
| `"content-digest"` | Only when the request has a body: the `Content-Digest` header (RFC 9530, `sha-256`), which the request then carries. |

and these parameters, in this order: `created`, the client's time in Unix
seconds; `nonce`, 22 to 64 characters of base64url (`A`–`Z`, `a`–`z`,
`0`–`9`, `-`, `_`) holding at least 128 random bits, new for each request;
`keyid`, the key's thumbprint, the base64url of the SHA-256 of its 32
bytes, without padding; and `alg`, `"ed25519"`. The signature's label is
`lantern`:

```http
GET /api/lantern/v1/apps?page_size=50 HTTP/1.1
Host: shelf.example.org
Authorization: Bearer et_c8V1nQ0xYb
Signature-Input: lantern=("@method" "@target-uri" "authorization");created=1793345400;nonce="tQ0Vb3Yt7sXx2c1mZ8kq4A";keyid="Zp3pS0eHqf…";alg="ed25519"
Signature: lantern=:<base64 of the 64 bytes>:
```

The signature base (RFC 9421 § 2.5) is one line per component, then the
parameters, joined by a line feed (`\n`), with no line feed at the end:

```text
"@method": GET
"@target-uri": https://shelf.example.org/api/lantern/v1/apps?page_size=50
"authorization": Bearer et_c8V1nQ0xYb
"@signature-params": ("@method" "@target-uri" "authorization");created=1793345400;nonce="tQ0Vb3Yt7sXx2c1mZ8kq4A";keyid="Zp3pS0eHqf…";alg="ed25519"
```

`@signature-params` is the `lantern` member's value in `Signature-Input`,
exactly as sent. `Signature` is the Ed25519 signature of the base's UTF-8
bytes, in base64 (with padding) between colons. Both headers carry the
`lantern` member alone. The bytes are spelled out, case by case, in
`vectors/signatures.json`.

A server MUST check the signature of every request that carries a bound
token, in this order, and answer `401` (with `WWW-Authenticate: Bearer
realm="lantern", error="invalid_token"`) with the code given: [L-5.4-6]

1. no `Signature-Input` or no `Signature`: `signature_required`;
2. a `Signature-Input` not of the form above (components other or in
   another order, a parameter missing, another `alg`), a `keyid` that is not
   the token's key, a `Content-Digest` missing on a request with a body, or
   a signature that does not verify: `signature_invalid`;
3. a `created` more than `auth.skew` seconds before or after the server's
   clock: `signature_expired`;
4. a `nonce` the server saw for this key within the window:
   `signature_replayed`.

A body that does not match its `Content-Digest` gives `422`
`digest_mismatch`, as in § 9.2.

- **Clock.** `auth.skew` is 300 seconds, unless a server announces another,
  between 60 and 900. Every response of a server MUST carry `Date` (RFC
  9110 § 6.6.1). [L-5.4-7] A client whose signature was refused as
  `signature_expired` SHOULD take the offset of its clock to that `Date`
  and sign again with it, once: a console's clock is often wrong. [L-5.4-8]
- **Replay.** A server MUST keep each nonce it took, per key, for twice
  `auth.skew` at least, and refuse it again within that time. [L-5.4-9] A
  request is thus taken once, within its window, whatever the network
  replays.
- A `401` for a signature SHOULD carry `Accept-Signature` (RFC 9421 § 5.1)
  with the components and parameters it wants. [L-5.4-10]
- **Polling with a key.** A pairing that sent `key` polls with requests
  signed by it, without `Authorization`: their components are `"@method"`
  and `"@target-uri"` alone. The server MUST give the token only to a poll
  so signed, and answer `401` `signature_required` or `signature_invalid`
  to any other. [L-5.4-11] An address of a poll that leaks gives nothing.
- Revoking a device revokes its token and the binding with it; a device
  changes its key by pairing again.

### 5.5 Invitations

An invitation lets a device pair without anyone signing in: an admin makes
it (§ 5.7) and hands it over, as a link or a code.

```json
{"schema": 1, "id": "i_3VxQ", "code": "MZ7Q-4KHP-XW2N-8TRD",
 "link": "https://shelf.example.org/pair?invitation=MZ7Q-4KHP-XW2N-8TRD&spki=3f9a1c07…",
 "user": "sam", "scopes": ["library"], "expires": "2026-11-06T18:00:00Z",
 "devices": 2, "used": 0, "rating_cap": {"age": 12}, "note": "Sam's consoles",
 "created": "2026-10-30T18:00:00Z"}
```

- `code`: of the pairing alphabet (§ 5.2), 16 to 32 symbols (at least 80
  bits), in groups of 4. `link`: `verify` with `invitation=<code>` in its
  query and, when no CA vouches for the server's certificate,
  `spki=<its whole SHA-256, lower-case hex>` (§ 5.3).
- `user`: the account the devices join; `scopes`: what they may do, a
  subset of that account's; `expires`: when it stops, 30 days ahead at
  most; `devices`: how many devices may redeem it, 1 to 100; `used`: how
  many did; `rating_cap` (§ 5.6) and `note`, optional.
- A device redeems it by pairing (§ 5.2) with `"invitation": "<code>"`. The
  pairing is approved at once, for the invitation's account, with the
  scopes asked for that the invitation holds and its `rating_cap`: the
  first poll gives the token.
- A server MUST NOT pair a device with an invitation that is unknown,
  expired, revoked or used up: it answers `410` `gone`. [L-5.5-1] It MUST
  count each device it pairs with an invitation, and stop at `devices`,
  even when devices redeem it at once. [L-5.5-2] It MUST limit attempts at
  invitation codes per address as it does pairing codes (§ 5.2). [L-5.5-3]
- A device paired by an invitation keeps its token when the invitation is
  revoked or expires: an admin revokes the device itself (§ 5.7).
- An invitation is a secret while it can be redeemed: it is handed over by
  a channel the admin trusts, and whoever holds it pairs.

### 5.6 Rating caps

A token MAY carry a rating cap, set when its device is approved (on the
server's page, or through § 5.7) or by its invitation (§ 5.5), never by the
device itself: a parental control kept on the server, which a child's
console cannot loosen.

```json
"rating_cap": {"age": 12, "unrated": "show"}
"rating_cap": {"system": "PEGI", "rating": "12", "unrated": "hide"}
```

A cap is an `age`, or a rating of one `system`, read as the age the table
below gives it; `unrated` says what becomes of what has no rating this
table can read: `show` (when absent) or `hide`.

| `system` | `rating` → age |
|---|---|
| `PEGI` | `3` 3, `7` 7, `12` 12, `16` 16, `18` 18 |
| `ESRB` | `EC` 3, `E` 6, `E10+` 10, `T` 13, `M` 17, `AO` 18 |
| `CERO` | `A` 0, `B` 12, `C` 15, `D` 17, `Z` 18 |
| `USK` | `0` 0, `6` 6, `12` 12, `16` 16, `18` 18 |
| `ACB` | `G` 0, `PG` 8, `M` 15, `MA15+` 15, `R18+` 18, `X18+` 18 |
| `CLASSIND` | `L` 0, `10` 10, `12` 12, `14` 14, `16` 16, `18` 18 |
| `GRAC` | `ALL` 0, `12` 12, `15` 15, `18` 18 |

A rating of another system, or one its row does not list (`RP`), is one
this table cannot read. The age of a title (§ 7.1), or of a homebrew with
`ratings` (§ 8.1), is, for a cap of a `system`, its rating of that system
when it has one; otherwise, and for a cap of an `age`, the highest age of
its ratings the table can read: a parent's cap is never loosened by the
most lenient organisation. With none, it is unrated. It is above the cap
when its age is above the cap's.

A server MUST hide from a capped token every title above its cap (or
unrated, with `unrated` `hide`), the apps of such a title, and each
homebrew above it, everywhere: [L-5.6-1]

- listings, what is missing, updates and changes (§ 6.2–6.4, § 8.5) leave
  them out; a page's `total` counts only what the token sees;
- `GET <base>/v1/titles/{title_id}`, `GET <base>/v1/homebrew/{id}`, a
  hidden app's or homebrew's file, and a cheat set of a hidden title give
  `404`, as if the server had none; `GET <base>/v1/titles?ids=` lists
  hidden ids in `unknown`; title changes (§ 7.3) leave them out.

- The handshake's `account.rating_cap` MUST show the cap to its token.
  [L-5.6-2] No route lets a device change it.
- A rating cap is a filter, not a lock: an app downloaded before, a game a
  console already has, or another server, are out of its reach.

### 5.7 Administration (feature `admin`)

A small API for an admin app, on a phone say: accounts, devices, waiting
pairings and invitations. Every route below needs the scope `admin`; the
family is offered (`features.admin`) to callers that hold it. Lists are
pages, as in § 6.2: `{"schema":1, "items":[…], "total":3, "next":null}`,
with `cursor` and `page_size`.

| Route | What |
|---|---|
| `GET <base>/v1/admin/users` | The accounts: `{"name":"lea", "state":"active", "scopes":["library","saves"], "devices":2, "created":"…"}`. |
| `POST <base>/v1/admin/users` | `{"schema":1, "name":"sam", "scopes":["library"]}` → `201` the account; `409` `conflict` when the name is taken. |
| `PATCH <base>/v1/admin/users/{name}` | `{"schema":1, "state":"frozen"}`, or `"active"`, and `scopes` → `200` the account. |
| `GET <base>/v1/admin/devices?user=` | The devices, one token each: `{"id":"d_…", "user":"lea", "device":"Lea's Switch", "scopes":[…], "created":"…", "bound":true, "key":"<short fingerprint>", "rating_cap":{…}, "invitation":"i_…", "expires":"…"}`. |
| `DELETE <base>/v1/admin/devices/{id}` | Revokes the device's token → `204`. |
| `GET <base>/v1/admin/pairings` | The pairings waiting for approval: `{"id":"pr_…", "code":"KQ4M-7TXD", "device":"Lea's Switch", "scopes":[…], "key":"<short fingerprint>", "created":"…", "expires":"…"}`. |
| `POST <base>/v1/admin/pairings/{id}` | `{"schema":1, "decision":"approve", "user":"lea", "scopes":["library"], "rating_cap":{"age":12}}` → `204`; `"decision":"refuse"` → `204`, and the device's poll gets `410`. |
| `GET <base>/v1/admin/invitations` | The invitations that can still be redeemed (§ 5.5). |
| `POST <base>/v1/admin/invitations` | `{"schema":1, "user":"sam", "scopes":["library"], "expires":"2026-11-06T18:00:00Z", "devices":2, "rating_cap":{"age":12}, "note":"…"}` → `201` the invitation, with its `code` and `link`. |
| `DELETE <base>/v1/admin/invitations/{id}` | Revokes it → `204`: its code gives `410`. |

- A server MUST answer every route of this family with `403` `forbidden`
  to a token without the scope `admin` (`401` without a token). [L-5.7-1]
- A server MUST NOT return a token, a hash of one, a password or its hash
  in any document of this family. [L-5.7-2]
- A device revoked or an account frozen MUST lose its access at once, on
  its next request. [L-5.7-3]
- An approval MUST grant at most the scopes the device asked for and its
  account holds; `user` is the admin's own account when absent, and
  `scopes` those asked for. [L-5.7-4]
- An account's `name` is 1 to 64 letters, digits, `.`, `_` and `-`. An
  account made here has no password: its devices pair by invitation, or
  are approved here; the server's own means may give it one.
- An admin app MUST show, next to each waiting pairing, its code and the
  short fingerprint of the server's key as the app pinned it, so that its
  user compares them with the console's screen as on the server's page
  (§ 5.3). [L-5.7-5]

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
 "installed_size": 1073741824,
 "format": "nsz",
 "sha256": "3a7bd3e2…",
 "atlas": "Q900001",
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
  read (`1.3.0`), never compared. Test vectors: `vectors/version-codes.json`.
- `size`: bytes, a 64-bit integer. `installed_size`, optional: the bytes
  the app takes once installed, when the server knows them (an `nsz`'s,
  decompressed), which a client compares with its free space (§ 6.3).
- `format`: a lower-case word from the profile's list of package formats.
- `sha256`: of the file as served, lower-case hex. A server MUST give it,
  having hashed the file before it lists it. [L-6.1-1]
- `atlas`, optional: the game's id in [Atlas](https://atlas.boreale.dev/),
  the open data on games of Boréale: its Wikidata item, `Q` and digits
  (`Q900001`), the key of Atlas's `links.json`, which ties a game's ids on
  every platform together (a Switch title id, a Steam app id…). A client
  MAY read Atlas's data with it (how well known a game is, its prices,
  similar games); Atlas's files of one platform are keyed by that
  platform's own ids, which `links.json` gives. It is a hint about the
  game, never its identity: a client MUST NOT install or match anything by
  `atlas` alone. [L-6.1-2] Atlas is an external address (§ 7.1).

### 6.2 Listing

`GET <base>/v1/apps?platform=&type=&title_id=&q=&sort=&page_size=&cursor=` →

```json
{"schema": 1, "items": [App, …], "total": 4123, "next": "c_…"}
```

- `platform` overrides `Lantern-Platform` (§ 4.3); `type` and `title_id`
  MUST filter, and `q` searches names. [L-6.2-1]
- `sort`: `name` (the default), `added` or `release` (both newest first);
  ties MUST be broken by `id`, so the order is stable. [L-6.2-2]
- `cursor` is opaque; `next` is `null` on the last page. Reading with a
  cursor while the library changes MUST neither skip nor repeat an app.
  [L-6.2-3]
- A cursor MUST give `410` when it expired (the client then reads the list
  from its start), and `400` when the server never gave it, or gave it for
  another listing (or `410`, when the server cannot tell it from an expired
  one). [L-6.2-4]
- `page_size` is at most `limits.page_size`; a larger one MUST be lowered
  to it. [L-6.2-5]

### 6.3 What the device is missing

`POST <base>/v1/apps/missing`, with `Lantern-Platform` (or `?platform=`):
`400` without one.

```json
{"schema": 1,
 "installed": [{"app_id": "0100ABCD00010000", "version_code": 0},
               {"app_id": "0100ABCD00010800", "version_code": 131072}],
 "want": ["update", "dlc"]}
```

→ a listing (§ 6.2), for that platform, which MUST hold exactly: [L-6.3-1]

- with `update` in `want`: for each installed game, its newest update whose
  `version_code` is above the highest installed one of that game. An update
  is an app of type `update`, or, on a platform whose profile says that a
  newer package replaces the base, an app of type `base` of the same
  `app_id`;
- with `dlc`: the add-ons of installed games not installed;
- with `base`: the games not installed.

A server knows an installed app's game from its library, or from the
profile's rule when it has one. Paginated with `cursor` in the query.

**Free space.** The client decides what fits, not the server: it compares
its free space with each app's `installed_size` (its `size` when there is
none), and says which ones do not fit before it downloads them. The request
does not carry the device's free space. Only the device knows its storages
(a card, its own memory), what an install needs besides the package, and
what its user is about to remove; and the answer stays the same for every
device of a platform, which keeps it simple to compute and to cache.

### 6.4 Changes (feature `changes`)

`GET <base>/v1/changes?since=<token>` → `{"schema":1, "added":[App…],
"removed":["a_…"], "since":"<next token>"}`, for the platform the client
named, or every platform. Without `since`, it MUST return no apps and the
current token. [L-6.4-1] A `since` token MUST give `410` when it is too old
for the server (the client then reads the whole library again), and `400`
when the server never gave it (or `410`, as for a cursor, § 6.2). [L-6.4-2]

### 6.5 Sections (feature `sections`)

`GET <base>/v1/sections` → `{"schema":1, "sections":[{"id":"new",
"title":"New", "apps":["a_…", …]}, …]}`: shelves the server curates. A
client MAY show them next to its own.

### 6.6 Files

`GET <file>`:

- MUST support `Range` (`206`; `416` with `Content-Range: bytes */<size>`)
  and send `Content-Length`, `Accept-Ranges: bytes` and a strong `ETag`.
  [L-6.6-1]
- MUST send `Repr-Digest: sha-256=:<base64>:` (RFC 9530) on every response,
  whole (`200`) or ranged (`206`), and on `HEAD`: the digest of the whole
  file, the same as the app's `sha256`. [L-6.6-2]
- The bytes served MUST be those whose SHA-256 the document gives, of the
  size it gives, without a `Content-Encoding` (§ 2.1). [L-6.6-3]
- The id in the path is opaque and not enumerable. It MAY expire: the
  client then reads the app again. An unknown or expired one MUST give
  `404` or `410`. [L-6.6-4]
- A server MAY offer a decompressed form of a compressed file under its own
  app entry (its own `format`, `size` and `sha256`), never silently.
- A client MUST check the SHA-256 of what it downloaded against the app's
  `sha256` before installing it, and refuse it when they differ. [L-6.6-5]

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
 "atlas": "Q900001",
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
  the same game on two platforms has two titles. A title of the library
  MUST be served for its platform, and an unknown one give `404`.
  [L-7.1-1]
- `language` says which language `summary` and `description` are in, the
  best the server has for `Accept-Language` (§ 2.2).
- `atlas`, optional: the game's Atlas id (§ 6.1).
- `genres`: zero or more of a fixed list, `action`, `adventure`, `rpg`,
  `strategy`, `simulation`, `sports`, `racing`, `puzzle`, `platformer`,
  `shooter`, `fighting`, `music`, `party`, `education` and `other`. A later
  version may add genres: a client shows a genre it does not know as
  `other`. `tags` are free words (32 at most, 64 bytes each).
- `players`: `min` and `max` on one device; `online` whether it plays
  online, and `online_max` how many at most.
- `ratings`: the age ratings, each `system` an organisation's short name
  (`PEGI`, `ESRB`, `CERO`, `USK`, `ACB`, `CLASSIND`, `GRAC`…) and `rating`
  its rating as that organisation writes it (`7`, `E10+`, `A`). Rating caps
  read them (§ 5.6).
- `release`: the date the game came out; `updated`: when this sheet last
  changed.
- `icon`, `banner`, `screenshots` (16 at most): images. An image on the
  server's origin SHOULD be content-addressed and served with a long cache
  lifetime. [L-7.1-2] An image elsewhere MUST be marked
  `"external": true`. [L-7.1-3]
- `video`: a page or a video elsewhere, always `external`.
- A client MUST NOT send a token, or any credential, to an `external`
  address. [L-7.1-4] It SHOULD open a `video` only when the user asks.
  [L-7.1-5]

### 7.2 Many titles at once

`GET <base>/v1/titles?ids=<id>,<id>,…` (100 at most, comma-separated) →
`{"schema":1, "titles":[Title…], "unknown":["…"]}`: the titles the server
has among those ids, for the platform the client named (or for each
platform that has the id), and the ids it does not know. A server MUST put
every id asked for in one of the two lists, and answer `400` to more than
100 ids. [L-7.2-1]

### 7.3 Changes

`GET <base>/v1/titles/changes?since=<token>` → `{"schema":1,
"titles":[Title…], "removed":[{"platform":"switch","title_id":"…"}],
"since":"<next token>", "more":false}`: the titles added or changed, and
those removed, since the token; a server MUST follow § 6.4's rules for
them, its tokens likewise. [L-7.3-1] A server MAY give part of them: `more` is
then `true`, and the client asks again with the new `since`.

## 8. Homebrew (feature `homebrew`)

The homebrew a server offers: apps, games, ports and tools made by their
authors, read with the scope `library`. Mods (files that change a game) are
out of scope for this version.

### 8.1 An entry

`GET <base>/v1/homebrew/{id}` →

```json
{"schema": 1,
 "id": "org.example.frostline", "platform": "switch",
 "kind": "app", "name": "Frostline", "author": "Noor",
 "tags": ["journal", "night mode"], "version": "1.4.0", "build": 10400,
 "license": "MIT", "source": "https://code.example.org/noor/frostline",
 "language": "en", "summary": "A pocket journal for long nights.",
 "description": "…",
 "icon": {"url": "https://media.example.org/frostline/icon.jpg", "external": true},
 "screenshots": [],
 "requires": {"text": "Atmosphère 1.7 or later", "min": {"atmosphere": "1.7.0"}},
 "updated": "2026-10-29T08:00:00Z",
 "package": {"format": "zip", "file": "<base>/v1/files/f_…",
             "size": 482113, "installed_size": 471136,
             "sha256": "…", "manifest_sha256": "…",
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
- `system_id`: the id the platform itself gives the installed software,
  where it has one (Annex A: a Vita or PS4 title id, a 3DS title id, an
  Android package name).
- `kind`: what it is: `app`, `game` (a game of its own), `port` (a game
  ported to the platform, § 8.6), `emulator`, `tool`, `overlay` (shown over
  other software), `sysmodule` (runs in the background with the system) or
  `theme`. A reader MUST read a kind it does not know, or none, as `app`.
  [L-8.1-1]
- `genres`, optional: zero or more of the genres of a title (§ 7.1), from
  the same fixed list, read the same way (a genre a reader does not know is
  `other`). They are meant for a `game` or a `port`; another kind MAY have
  them.
- `tags`, optional: free words for the rest, such as `video player` or
  `file manager` (§ 13 bounds them, as a title's).
- A client builds its shelves from `kind` (Games, Ports, Emulators, Tools,
  Overlays…) and, within them, sub-shelves from `genres`. An entry has no
  other shelf field: an earlier draft's `category` is gone, and a server
  MUST NOT write it. [L-8.1-2]
- `name`, `author`, `summary` and `description` (localized, `language` as
  for a title, § 7.1), `icon` and `screenshots` (images, § 7.1).
- `license`: an SPDX licence expression; `source`: where its code is.
  `assets_license`, optional: the licence of the free or replacement
  assets it bundles, when it differs (SPDX, `LicenseRef-` allowed).
- `version` is for people; `build` is an integer that grows with every
  version, and the one a client compares.
- `requires`, optional: what the device needs (§ 8.7): `text` for people,
  the conditions a client checks before it offers the package (`min` and
  `gpu`), and `homebrew`, the homebrew it needs (a runtime, a loader, a
  plugin), each `{"id":…, "min_build":…}` of the same platform, which a
  client installs first, or says which one is missing.
- `ratings`, optional: age ratings, as a title's (§ 7.1); rating caps read
  them (§ 5.6).
- `atlas`, optional: for a `game` or a `port`, the Atlas id of the game
  (§ 6.1).
- `updated`: when this entry last changed.
- `package`: the package (§ 8.2); `packages`, optional, more packages of
  the same build for other architectures (§ 8.2).
- `port`, for a `kind` `port` only: what § 8.6 says.
- An entry MUST be the same on its own route as in a listing, but for the
  manifests the listing leaves out. [L-8.1-3] An unknown id MUST give
  `404`. [L-8.1-4]

### 8.2 Packages and manifests

A package is one file, downloaded like an app's (§ 6.6): `format`, `file`,
`size`, `sha256` and `manifest_sha256` are REQUIRED. [L-8.2-1]
`installed_size`, optional, is what it takes once installed (for an
archive, its manifest's sizes added up). It is either:

- **a single file**, of one of the profile's formats: `path` says where it
  goes on the device (the profile says where a format goes); or
- **an archive** (`zip`) with a **manifest**: every file it installs, its
  `path` on the device, `size` and `sha256`, all REQUIRED. [L-8.2-2] The
  archive MUST hold each of them under its path without the leading `/`,
  of that size and SHA-256; anything else in it is ignored. [L-8.2-3]

A single file is a manifest of one entry: its `path`, `size` and `sha256`.
Where the profile says the platform's own installer installs a format, the
package has no `path`, and its manifest is empty (`[]`).

A `path` is absolute on the device's storage, as the profile maps it: it
starts with `/`; its parts are separated by `/`, none empty, `.` or `..`;
it has no `\`, `:`, `"`, control character or NUL; a part is 255 bytes at
most, the path 1024. No two paths of a manifest are the same when case is
ignored. A server MUST NOT serve a manifest that breaks these rules, or
whose paths lie outside the profile's roots for homebrew (Annex A).
[L-8.2-4] Test vectors: `vectors/paths.json`.

`manifest_sha256` is the SHA-256, lower-case hex, of the manifest's
canonical form: the JSON array of its entries sorted by `path` (as UTF-8
bytes), each entry `{"path":…,"sha256":…,"size":…}` with its keys in that
order, no space, and characters other than ASCII written as they are, in
UTF-8. A server MUST give the digest of the manifest it serves. [L-8.2-5]
A listing (§ 8.5) leaves `manifest` out and keeps `manifest_sha256`; the
entry's own route has both.

On a platform with several architectures (Annex A), a package MAY carry
`arch`, the list of those it runs on: `aarch64`, `armhf` (32-bit ARM, hard
float), `x86`, `x86_64` or `riscv64` (64-bit RISC-V); a later version may
add others, of 1 to 32 lower-case letters, digits and `_`. A name not of
that form breaks this text. A reader MUST treat a well-formed name it does
not know as not its own architecture: it never installs a package for that
name alone. [L-8.2-6] A package without `arch` runs on every architecture
of its platform (a package for a runtime, such as a script or bytecode,
has none). Each package of `packages` MUST have an `arch`, and a
`signature` when the entry is signed (§ 8.4). [L-8.2-7] A client takes a
package whose `arch` lists its own, or else one without `arch`; it MUST
skip the others, and install nothing when none fits. [L-8.2-8] On a
platform with one architecture (Annex A says so), a package MUST NOT carry
`arch`. [L-8.2-9]

Where the profile says so (Android), a package also carries
`signer_sha256`: the SHA-256, lower-case hex, of the certificate the
platform's own signature of the package uses.

### 8.3 Installing

A client MUST:

- refuse a package whose download does not match its `sha256`, or a file
  of an archive that does not match its manifest entry; [L-8.3-1]
- refuse a manifest with a path that breaks § 8.2, or that lies outside the
  profile's roots for homebrew (Annex A), and install nothing of it;
  [L-8.3-2]
- write only the manifest's paths, and only files: never follow a link
  out of them; [L-8.3-3]
- write without asking only under the profile's roots that need no
  consent; for any path elsewhere, show every such path to the user and
  install only when they agree; [L-8.3-4]
- refuse an entry whose `system_id` is that of software another `id`
  installed, and install nothing of it; [L-8.3-5]
- keep each installed manifest, and uninstall by it alone: remove its
  files, then the folders it made that are left empty, nothing else. An
  update removes the files of the old manifest the new one no longer has.
  [L-8.3-6]

A server MUST NOT serve two entries of the same platform with the same
`system_id`. [L-8.3-7]

### 8.4 Signature

An author MAY sign their packages with ed25519 (RFC 8032). The entry then
carries `signature`: `alg` (`ed25519`), `public_key` (the 32 bytes of the
key, base64) and `value` (the 64 bytes of the signature, base64).

The signed bytes are the UTF-8 bytes of the JSON object

```text
{"build":<build>,"id":"<id>","manifest_sha256":"<hex>","platform":"<platform>","purpose":"lantern-homebrew-1","sha256":"<hex>"}
```

with these keys in this order, no space, `build` in decimal, and the
entry's values, `sha256` and `manifest_sha256` those of `package`. Each
value's form (§ 8.1, § 8.2, § 4.3) leaves nothing to escape, so the bytes
are the same for every writer. A package of `packages` carries its own
`signature`, by the same key, over the same object with its own `sha256`
and `manifest_sha256`. Test vectors: `vectors/homebrew-signatures.json`.

- A server MAY serve a signature it is given, as given; it does not sign
  for an author. It SHOULD check a signature before it serves it. [L-8.4-1]
- A client MUST check the signature of the package it installs when there
  is one, and refuse the package when it does not verify. [L-8.4-2]
- On the first install of an `id`, the client pins its `public_key` (or
  that it had none). A later version signed by another key, or unsigned
  after a signed one, MUST be refused unless the user explicitly accepts the
  change, after the client showed both keys' short fingerprints (the
  SHA-256 of the 32 bytes, in the form of § 5.3). [L-8.4-3]

### 8.5 Routes

- `GET <base>/v1/homebrew?platform=&q=&kind=&genre=&page_size=&cursor=` →
  a page (§ 6.2) of entries, sorted by name: `{"schema":1,
  "items":[Entry…], "total":12, "next":null}`. `q` keeps the entries whose
  name holds it, case ignored; `kind`, those of that kind (as a reader
  reads it, § 8.1); `genre`, those whose `genres` hold it. These filters
  MUST keep those entries and no others. [L-8.5-1] A `kind` or a `genre`
  that is not a lower-case word (1 to 32 letters, digits and `_`, starting
  with a letter) MUST give `400`; one the server does not know, an empty
  page. [L-8.5-2]
- `GET <base>/v1/homebrew/{id}` → the entry (§ 8.1), with its manifests.
- `POST <base>/v1/homebrew/updates`, with a platform (§ 4.3):
  `{"schema":1, "installed":[{"id":"org.example.frostline", "build":10300}]}`
  → a page that MUST hold the entries of those ids whose `build` is above
  the installed one, and only those, paginated with `cursor` in the query,
  like § 6.3. [L-8.5-3]

### 8.6 Game ports

A port (`kind` `port`) is a game ported to the platform, such as a source
port or a recreation of a game's engine, that may run on the data of the
user's own copy of the original game. A server MUST NOT serve that data: a
port's package holds the port and, at most, assets free to share, and no
route of this family serves a file the port requires from the user.
[L-8.6-1]

An entry of kind `port` has a `port` object:

```json
"port": {
  "original": {"name": "Harbor Lights", "year": 1998, "developer": "Fjord Works",
               "stores": [{"store": "gog", "id": "1207658000",
                           "url": "https://store.example.org/harbor-lights"}]},
  "engine": {"name": "Lighthouse", "version": "2.1.0",
             "source": "https://code.example.org/lea/lighthouse"},
  "data_root": "/switch/harborlights/",
  "assets": "user_owned",
  "requires_data": [
    {"path": "data/HARBOR.PAK", "size": 214748364,
     "accept": [{"sha256": "…", "label": "1.0"}, {"sha256": "…", "md5": "…", "label": "1.1"}],
     "hint": "In the folder where the game is installed."},
    {"one_of": [[{"path": "music/THEME.OGG", "hint": "From the soundtrack edition."}],
                [{"path": "data/MUSIC.PAK", "hint": "Next to HARBOR.PAK."}]],
     "optional": true}]}
```

- `original`: the game it ports: its `name`, and, optional, its `year`, its
  `developer`, the `stores` that sell it (each `store` an Atlas store name,
  its `id` there, and its `url`, external: § 7.1) and its `title`
  (`{"platform", "title_id"}`) when a server has it as an app.
- `engine`: its `name`, and, optional, its `version`, its `source` and its
  `license` when it differs from the entry's.
- `assets`: where the game's assets come from: `included` (free assets in
  the package, under `assets_license`), `demo_included` (a demo's data, free
  to share, in the package), `free_external` (free data the user fetches
  elsewhere) or `user_owned` (from the user's own copy). A reader reads a
  value it does not know as `user_owned`.
- `data_root`: the folder where the port expects its data, as an absolute
  path (§ 8.2) that ends with `/`. It lies under the profile's areas for
  ports' data (Annex A); the user approves it once, at the first install.
  From then on the client may write the user's data files there without
  asking again; the port's own files still follow the manifest's roots
  (§ 8.3).
- `requires_data`: the files the user supplies, each either a file or a
  group:
  - a file: `path`, relative to `data_root`, exact (case included): parts
    separated by `/`, as § 8.2 says, but without the leading `/`, and with
    no drive letter; `size`, optional, in bytes; `accept`, optional, the
    known versions of the file the port takes, each with a `label` and one
    or more of `sha256`, `sha1` and `md5` (lower-case hex); `hint`, which
    every file has, where the user finds it in their copy, localized like `description`, and
    never pointing at a download of it; and `optional`, `true` when the
    port runs without it (`false` when absent);
  - a group: `one_of`, two or more lists of files, of which one is enough,
    and `optional` as for a file.
- A server MUST serve a port's object of these forms, its `data_root` in
  the profile's areas. [L-8.6-2]

A client MUST:

- refuse a port whose `data_root` or one of whose data paths breaks these
  rules, and install nothing of it; [L-8.6-3]
- before it launches the port, check that each file that is not optional
  is present, and, when an `accept` gives it, that its SHA-256 is one of
  them (it MAY check `sha1` and `md5` where no `sha256` is given);
  otherwise, launch nothing, and show the user each missing or unknown
  file with its `hint`; [L-8.6-4]
- never fetch that data from the network: the user copies it from their
  own copy, by the means the device has. [L-8.6-5]

A port's data files are never in its manifest: an update or an uninstall
(§ 8.3) never removes or overwrites them.

### 8.7 Requirements

`requires` says what a device needs to run an entry:

```json
"requires": {"text": "glibc 2.30, OpenGL ES 2 or Vulkan, 1 GiB of memory, 640×480",
             "min": {"glibc": "2.30", "ram_mb": 1024, "screen": "640x480"},
             "gpu": ["gles2", "vulkan"],
             "homebrew": [{"id": "org.example.lanternlight-runtime", "min_build": 200}]}
```

- `text`, REQUIRED: the requirements, for people. [L-8.7-1]
- `min`: the lowest the device may have. Its keys are those of the
  profile (Annex A), such as `firmware`, as dotted numbers (`18.0.0`),
  and these, which any profile may use:
  - `glibc`: the version of the GNU C library, dotted (`2.30`);
  - `ram_mb`: the memory, an integer, in MiB (`1024`);
  - `screen`: the screen's size in pixels, `<width>x<height>` (`640x480`):
    the device's width and height are each at least those.
- `gpu`: the graphics interfaces the entry can use, `gles2`, `gles3`
  (OpenGL ES 2 and 3), `gl` (desktop OpenGL) and `vulkan`: the device must
  offer at least one of them. A later version may add names.
- `homebrew`: the homebrew it needs (§ 8.1).

`min` and `gpu` are conditions. A client MUST check them before it offers a
package: [L-8.7-2]

- a condition it can read and that the device fails: the client does not
  install the package, and says which condition fails and why (`glibc
  2.30 or later; this device has 2.28`);
- a condition it cannot read (a key or a `gpu` name it does not know, a
  value of another form, or something it cannot learn of the device): the
  client still offers the package, with a warning that names the
  condition, and shows `text`;
- otherwise it offers the package. Two dotted versions compare part by
  part, as numbers, a missing part being `0`.

Test vectors: `vectors/requires.json`. A key of `requires` this text does
not list is a condition a client cannot read, but for a vendor's own
(`x-<vendor>-`, § 3.3), which it ignores.

A server only serves the conditions, as the entry's author gave them: it
MUST keep the keys it does not know, and never judge a device by them nor
filter a listing with them. [L-8.7-3]

## 9. Save backups (feature `saves`, scope `saves`)

### 9.1 Backups

`GET <base>/v1/saves?platform=&title_id=` → `{"schema":1, "saves":[Save…]}`,
which MUST hold the account's own backups, newest first per title, where a
save is: [L-9.1-1]

```json
{"platform": "switch", "title_id": "0100ABCD00010000", "save_id": "s_03",
 "created": "2026-10-30T09:12:00Z", "size": 1052672, "sha256": "…",
 "kind": "account", "game_version_code": 196608, "profile": "Lea",
 "note": "Chapter 4", "device": "Lea's Switch"}
```

- `slot`, optional: which of the title's save folders it is, where a title
  has several (Annex A), as the platform names it (1 to 64 letters,
  digits, `.`, `_` and `-`).
- `kind`: `account` (a user's save), `device` (the device's, shared by
  its users), `bcat` (data the system downloaded for the game), `cache`, or
  `other`, as the profile maps the platform's own kinds.
- `game_version_code`: the game's `version_code` (§ 6.1) when it was
  saved, so that a client SHOULD warn before restoring a save on an older
  game. [L-9.1-2]
- `profile`: the name the user gave the profile the save belongs to, as
  the device shows it. Never a hardware or account identifier.
- `device`: the name of the paired device that sent it (§ 5.2).
- The archive is a zip whose content the profile gives (Annex A).
- The server keeps at most `limits.saves_kept_per_title` backups per title,
  platform and account, and drops the oldest beyond it.
- `GET` and `DELETE <base>/v1/saves/{title_id}/{save_id}`: the archive, as
  a file (§ 6.6), and its removal, which MUST answer `204`, the backup then
  giving `404`. [L-9.1-3]

Every route that writes a save needs a platform (§ 4.3).

### 9.2 In one request

For a save of at most `limits.save_body` bytes:
`POST <base>/v1/saves/{title_id}`, the zip archive as the body
(`Content-Type: application/zip`), with:

- `Content-Digest: sha-256=:<base64>:` (RFC 9530): the server MUST answer
  `400` without it, and `422` `digest_mismatch` when the body does not
  match it. [L-9.2-1]
- `Lantern-Save-Kind`, `Lantern-Save-Slot` and `Lantern-Game-Version` (the
  integer `game_version_code`), in ASCII as they are; `Lantern-Profile` and
  `Lantern-Note` (UTF-8, percent-encoded); all within § 13's limits.

→ `201` with the save entry. A larger body gives `413`.

### 9.3 Resumable upload

For any save up to `limits.save_size` bytes, sent in chunks that survive a
lost connection:

1. `POST <base>/v1/saves/{title_id}/uploads` `{"schema":1, "size":5242880,
   "sha256":"…", "kind":"account", "game_version_code":196608,
   "profile":"Lea", "note":"Chapter 4"}` → `201` `{"schema":1,
   "upload":"<base>/v1/uploads/u_…", "chunk_size":1048576, "offset":0,
   "expires":"2026-10-31T09:12:00Z"}`. A `size` above `limits.save_size`
   MUST give `413`. [L-9.3-1]
2. `PATCH <upload>` with `Upload-Offset: <n>` and a chunk of at most
   `chunk_size` bytes as the body (`Content-Type:
   application/offset+octet-stream`) → `204` with the new `Upload-Offset`.
   An offset other than the server's MUST give `409` `conflict` with the
   server's `Upload-Offset`; a larger chunk, `413`. [L-9.3-2] A chunk MAY
   carry its own `Content-Digest`, which the server then checks (`422`
   `digest_mismatch`).
3. `HEAD <upload>` MUST answer `204` with `Upload-Offset` and
   `Upload-Length`: where to resume after an interruption. [L-9.3-3] A server keeps only whole
   chunks, or says in `Upload-Offset` how much of a cut one it kept.
4. The chunk that reaches `size` ends the upload: the server MUST check the
   whole archive's SHA-256, then answer `201` with the save entry, or `422`
   `digest_mismatch` and discard it. [L-9.3-4]

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
  sources. The filters MUST keep those sets and no others. [L-10-1]
- `build_id`: the build of the game the set is for, in the profile's form
  (Annex A), on platforms whose cheats depend on it; absent elsewhere.
- `GET <base>/v1/cheats/{id}` → the set's text, as a file (§ 6.6), in the
  platform's own format and at most 1 MiB, which the client writes where
  the profile says (Annex A). An unknown id MUST give `404`. [L-10-2]
- With scope `cheats.write`, a server MAY take
  `POST <base>/v1/cheats` and `PUT` and `DELETE <base>/v1/cheats/{id}`; the
  body of `POST` and `PUT` is `{"schema":1, "platform", "title_id",
  "build_id", "source", "note", "text"}`. `POST` answers `201` with the new
  set (`{"schema":1, "id":…}`, as listed), `PUT` and `DELETE` `204`. A
  `POST` of a set that exists (the same platform, title, build and source)
  answers `409` `conflict`: `PUT` replaces it. A server without them
  answers `405`. A server that takes them MUST answer so. [L-10-3] Without
  the scope, writing MUST be refused (`401`, `403` or `405`). [L-10-4]

## 11. Requests (feature `requests`)

- `GET <base>/v1/requests` → `{"schema":1, "requests":[{"id", "platform",
  "title_id", "name", "status", "created"}…]}`: the account's own, of the
  platform named (§ 4.3). `status`: `open`, `done` or `declined`.
- `POST <base>/v1/requests` `{"schema":1, "platform":"switch",
  "title_id":"…"}` → `201` with the new request (`{"schema":1, "id":…}`,
  as listed), or `200` with the open request for the same title.
  `platform` defaults to the client's (§ 4.3). A server MUST answer so.
  [L-11-1]
- `DELETE <base>/v1/requests/{id}`: the account withdraws its own request,
  whatever its status. A server MUST answer `204`, and `404` for another
  account's request or an unknown one. [L-11-2]

## 12. Errors

Every error MUST be `application/problem+json` (RFC 9457) with a real
status code, never `2xx`. [L-12-1]

```json
{"schema": 1, "type": "https://lantern.boreale.dev/errors/account-frozen",
 "title": "Account frozen", "status": 403, "code": "account_frozen",
 "detail": "Your access is paused until Sunday.", "language": "en"}
```

Its `status` MUST be the response's, and its `code` one the table gives for
that status. [L-12-2] Its `type` is the code's page,
`https://lantern.boreale.dev/errors/<code, with - for _>`.

| Status | `code` | When |
|---|---|---|
| 400 | `bad_request`, `key_required` | A malformed query or body; a cursor or `since` token the server never gave; a platform missing where one is needed; a pairing without a device key, on a server that issues only bound tokens (§ 5.4) |
| 401 | `unauthorized`, `signature_required`, `signature_invalid`, `signature_expired`, `signature_replayed` | No token where one is needed, or an unknown, revoked or expired one (with `WWW-Authenticate: Bearer`); a bound token without a signature (§ 5.4); a signature that does not verify or is not of the form § 5.4 gives; a signature's `created` outside the server's window; a signature's `nonce` seen before |
| 403 | `forbidden`, `account_frozen` | A scope missing; a frozen account |
| 404 | `not_found` | |
| 405 | `bad_request` | A method the route does not take (with `Allow`) |
| 409 | `conflict` | An upload's offset that is not the server's (with `Upload-Offset`); a cheat set or an account that exists already (§ 10, § 5.7) |
| 410 | `gone` | An expired cursor, `since` token, pairing, invitation or file id |
| 413 | `too_large` | A save or a chunk above the server's limit |
| 416 | `bad_request` | A range outside the file (with `Content-Range: bytes */<size>`) |
| 422 | `unsupported_schema`, `digest_mismatch` | A request document of a schema the server cannot read; a body whose SHA-256 is not the one announced |
| 429 | `slow_down` | Too many requests, pairing attempts or polls (with `Retry-After`) |
| 500 | `internal` | A failure of the server itself; the client may try again later |
| 503 | `unavailable` | Scanning, maintenance (with `Retry-After`) |

- An unknown route MUST give `404` `not_found`. [L-12-3]
- `title` and `detail` are for people, in `language` (§ 2.2); a client
  shows them bounded and without control characters, and acts on `status`
  and `code` alone.
- New codes MAY come with later versions of this text: a client that gets a
  `code` it does not know MUST act on the status alone. [L-12-4]

## 13. Limits

A client MUST bound what it reads. [L-13-1] A server MUST stay within:
[L-13-2]

| What | At most |
|---|---|
| A JSON document | 32 MiB, nesting depth 16 |
| A string field | 4 KiB (`name` 512 bytes, `note` 120 bytes, `profile` 64 bytes) |
| A page | 1000 items |
| Titles read at once | 100 |
| A manifest | 4096 files, each path 1024 bytes |
| A homebrew's `packages` | 16 |
| `tags` of a title or a homebrew | 32, each 64 bytes |
| A port's `requires_data` | 256 files, each `accept` list 32 |
| A cheat set | 1 MiB |
| A discovery datagram | 1200 bytes |
| `Signature-Input`, `Signature` | 1 KiB each |

A server MUST refuse a request document beyond these limits, or beyond
its own lower ones, with `400` or `413`, never fail on it. [L-13-3]

## 14. Caching

Every `GET` returning JSON SHOULD carry an `ETag` and honour
`If-None-Match` with `304`. [L-14-1] Responses to authenticated calls
SHOULD carry `Cache-Control: private` and `Vary: Authorization`; responses
that depend on the platform or the language also vary on
`Lantern-Platform` and `Accept-Language`, and compressed ones on
`Accept-Encoding` (§ 2.1). [L-14-2]

## 15. Security and privacy

- No hardware identifier, no tracking header. A server knows a device only
  by the name its user gave it during pairing, and a save's profile only by
  the name its user gave it.
- No password goes through the device: it holds a token per server, which
  the user can revoke from the server (§ 5), bound to a key the device made
  (§ 5.4).
- No proprietary encryption of documents: TLS protects them, with a key
  pinned at pairing when no CA vouches for it (§ 5.3).
- Discovery is a hint, never a proof (§ 4.1).
- A server cannot change a client's settings or add headers to its later
  requests.
- A client checks a download's SHA-256 before installing it (§ 6.6), and a
  homebrew's signature when it has one (§ 8.4).
- A homebrew writes only its manifest's files, under the profile's roots,
  and nothing outside the roots that need no consent without the user's
  agreement (§ 8.3).
- A server never serves the data a port needs from the user's own copy
  of the game (§ 8.6).
- No credential goes to an external address (§ 7.1).
- Servers are for the user's own games.

## 16. Threat model

What Lantern protects against, and what it leaves to others. Each threat
names the rules that answer it.

**A hostile network** (a café's Wi-Fi, a LAN with an intruder, a forged
DNS answer or discovery reply, someone recording the traffic).

- Protected: TLS everywhere, plain HTTP on loopback only (§ 2); a LAN
  server's key compared by the user and pinned at pairing, a changed key
  refused (§ 5.3); discovery a hint that is never trusted (§ 4.1); tokens
  and signatures sent only to the server's origin (§ 2); requests signed
  with a nonce and a time, so that one recorded is never taken twice
  (§ 5.4); every file checked against its SHA-256, the same in the
  document and in `Repr-Digest` (§ 6.6).
- Not protected: a first pairing where the user does not compare the
  fingerprints; what the sizes and times of the traffic tell (which game
  was downloaded); a network that cuts the connection.

**A malicious or compromised server.**

- Protected: a client writes only a manifest's paths, under the profile's
  roots, and asks before any root that needs consent (§ 8.2, § 8.3); an
  author's signature, its key pinned per homebrew, is checked whatever the
  server says, so a server cannot forge an author's update (§ 8.4); a
  homebrew cannot take over another's system id (§ 8.3); a port's data is
  never fetched from the network (§ 8.6); a server cannot change a
  client's settings (§ 15); credentials never go to external addresses
  (§ 7.1); every document is bounded (§ 13) and read by the `schema` rule
  (§ 3.2).
- Not protected: games and unsigned homebrew are what the server says they
  are: install them only from a server you trust. A server sees what its
  clients ask for, may hold back an update or lie about a game's sheet or
  its ratings (a rating cap trusts the server's ratings, § 5.6), and keeps
  save backups as they are sent.

**A stolen token or device.**

- Protected: a token bound to its device's key is useless without it
  (§ 5.4); every device has its own token, which the user revokes from
  the server's page or an admin app (§ 5.1, § 5.7); the server keeps only
  hashes of tokens (§ 5.1); scopes and a rating cap limit what a token can
  do (§ 5.1, § 5.6); a poll address that leaks gives nothing (§ 5.4).
- Not protected: a stolen device holds its key and its token until the user
  revokes it; a bearer-only token, which a server may refuse (§ 5.4),
  works for whoever copies it.

**A hostile manifest** (a path that climbs out of its folder, a link, two
paths that differ by case, a sysmodule slipped in, an archive larger than
it says).

- Protected: § 8.2's rules on paths, and the profile's roots (Annex A); a
  client writes files only, never through a link, and checks each against
  its manifest (§ 8.3); a manifest's digest is in an author's signature
  (§ 8.4); the limits of § 13; a port's data paths are relative to its
  data folder, which the user approves once (§ 8.6).
- Not protected: what a homebrew does once it runs.

**A malicious homebrew author.**

- Protected: a key change is refused unless the user accepts it, having
  seen both fingerprints (§ 8.4); a system id another homebrew installed is
  refused (§ 8.3); every path outside its own folders, such as a
  sysmodule's, is shown to the user first (§ 8.3); its requirements are
  checked before it is offered (§ 8.7).
- Not protected: a signature proves who made a homebrew, not that it is
  safe. Lantern reviews and sandboxes no code: that is the user's choice,
  and the platform's.

**A lost console.**

- Protected: it holds no password (§ 5.2); the user revokes its device from
  the server or an admin app on a phone (§ 5.7), and its token then fails
  at once; its backups stay on the server, for the account (§ 9).
- Not protected: what is on the console's own storage (its saves, its
  games, its key until revoked): protecting it is the platform's.

Out of scope: rights to games. Lantern serves a user's own games and
enforces nothing (§ 15).

## 17. Conformance

A conformance suite (`conformance/`) runs against a server's URL, with a
token or without, and checks every requirement of this text it can see
from outside; each check names the ids it covers. The rules it cannot see
(a client's, or a server's inside) are listed by id on the site's
traceability page, <https://lantern.boreale.dev/requirements/>. With a
token, it writes only what it then deletes: save backups, a cheat set, a
request, the devices it pairs and the invitations it makes (with
`--admin-writes`, an account of its own, frozen). A reference server
(`server/`) serves a folder of packages and homebrew and passes the suite.

**Levels.** An implementation is conformant at a level:

| Level | What |
|---|---|
| `Lantern Core` | Transport, versions and the handshake (§ 2–4); tokens, pairing and signed requests when it issues tokens (§ 5.1–5.4); the library, what is missing, changes and sections when offered, and files (§ 6); errors, limits and caching (§ 12–14) |
| `+titles` | Titles (§ 7) |
| `+homebrew` | Homebrew, packages, manifests, signatures, ports and requirements (§ 8) |
| `+saves` | Save backups (§ 9) |
| `+cheats` | Cheats, and writing them when offered (§ 10) |
| `+requests` | Requests (§ 11) |
| `+admin` | Administration, invitations and rating caps (§ 5.5–5.7) |

The suite prints the levels a server reaches: a level is reached when its
family is offered to the caller, none of its checks fails, and none was
left out for want of a token or a scope (run it with a token that holds
every scope, and anonymously on a public server). Every level needs
`Lantern Core`.

**The name.** Only an implementation that passes the suite at a level may
call itself "Lantern compatible" and show the badge, with that level and
the version of the text: "Lantern compatible 0.4 · Core +titles". The
badges and the registry of implementations are on the site,
<https://lantern.boreale.dev/conformance/>; an implementation joins the
registry by a pull request with its report.

**Test vectors** (`vectors/`), for the libraries of clients and servers:
signed requests (§ 5.4), homebrew signatures (§ 8.4), SPKI fingerprints
(§ 5.3), paths (§ 8.2), `version_code` per profile (Annex A) and
requirements (§ 8.7), each case with what a reader decides.

## Annex A — Platform profiles

A profile says, for one platform, what the core leaves open. It gives:

- the form of `title_id` and `app_id`, with a regular expression;
- the app `type`s, and how `version_code` is derived;
- the package `format`s;
- for cheats: the file format, the form of `build_id` and where the client
  puts a set;
- for saves: the kinds, the slots where a title has several, and what the
  archive holds, at which root;
- for homebrew: the package formats and where a single file goes, the
  `system_id` where there is one, the architectures (`arch`, § 8.2) when
  there are several, the roots a client may write to without asking, those
  that need the user's consent, the areas for a port's `data_root`
  (§ 8.6), and the keys of `requires.min`.

Paths are written as § 8.2 says; the profile says how they map to the
device. The Switch's profile is complete. Those of the 3DS, the Vita, the
PS4, Android and Linux are drafts, **to be reviewed by someone who knows
the platform**: what is marked "(to check)" is not settled. The other
platforms are open: no profile yet (Annex A.7).

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
  `/atmosphere/contents/<title_id>/cheats/<build_id>.txt`, never to
  `toggles.txt`, the file where Atmosphère keeps which cheats are on.
- **Saves.** Kinds `account` (a user's save; `profile` is the user's
  nickname), `device`, `bcat`, `cache`, and `other` for the rest
  (temporary, StreamPlay and system saves). No slots. The zip holds the
  save filesystem's files as they are in it, at the root of the archive.
- **Homebrew.** Formats `nro` (a single file, at `/switch/<id>/<id>.nro`:
  the homebrew menu takes a folder's `.nro` of the folder's name, or its
  only one), `ovl` (an overlay, a single file in `/switch/.overlays/`, under its own file name, which some loaders expect) and
  `zip`; an archive puts at most one `.nro` in a folder, or one of the
  folder's name. No `system_id`. One architecture, so no `arch`.
  Roots without consent: `/switch/<id>/` and `/config/<id>/` (a
  convention of homebrew, not a rule of the system). Roots that need
  consent: `/atmosphere/`, which holds sysmodules
  (`/atmosphere/contents/<program id>/`, with `exefs.nsp`,
  `flags/boot2.flag` and `toolbox.json`), LayeredFS files and
  `exefs_patches`; and `/switch/.overlays/`, which holds overlays (`.ovl`
  files, which need nx-ovlloader: `requires.homebrew`). Nothing else.
  Areas for a port's `data_root`: `/switch/` and `/config/`.
  `requires.min` keys: `firmware` (the system version, `18.0.0`) and
  `atmosphere` (`1.7.0`).
- **Reading an `.nro`.** A server reads its name and author from the control
  data (NACP) in its asset section; from system 21.0.0, its block of titles
  may be compressed with Deflate (`TitlesDataFormat` 1). The NACP's version
  is text only: `build` comes from the author's `homebrew.json`, never from
  the NACP.

### A.2 New Nintendo 3DS (`3ds`), draft

To be reviewed by someone who knows the platform.

- **Ids.** `title_id`: 16 upper-case hex digits, the game's id, which
  begins with `00040000` (a demo's with `00040002`):
  `^0004000[02][0-9A-F]{8}$`. `app_id`: the package's own id, the
  `title_id` for the game; an update's begins with `0004000E`, an
  add-on's with `0004008C`, with the same last 8 digits as the game's
  (`^0004(0000|0002|000E|008C)[0-9A-F]{8}$`).
- **Types**: `base`, `update`, `dlc`. An update is a package of its own.
- **Versions.** `version_code`: the 16-bit title version of the title
  metadata; `version_name`: its top 6 bits, next 6 bits and low 4 bits,
  as major, minor and micro (`2069` is `2.1.5`).
- **Formats**: `cia` only. Cartridge dumps (`3ds`, `cci`) are never
  installed.
- **Paths**: `/` is the SD card's root.
- **Cheats.** Gateshark codes in Luma3DS's text format, one file per game,
  at `/cheats/<title_id>.txt`. No `build_id`. Rosalina prefers
  `/luma/titles/<title_id>/cheats.txt`: when that file exists, the client
  warns the user that it, not the new set, is the one in use.
- **Saves.** The game's save data as `device` (the 3DS has a single
  user); its extra data as `other`, in an archive of its own, its `slot`
  the extra data's id (to check). What the zip holds and at which root
  (to check).
- **Homebrew.** Formats `3dsx` (a single file, at `/3ds/<id>/<id>.3dsx`)
  and `zip`; a `cia` is installed by the system as a title, which installs
  it without asking: the client always asks the user first, and its
  `system_id` is the title id. A server MAY read a `3dsx`'s name and author
  from its SMDH, which has no version: `build` comes from the author.
  One architecture, so no `arch`. Roots without consent: `/3ds/<id>/`.
  Roots that need consent: `/luma/` (plugins, titles' patches,
  sysmodules), `/boot.firm`, `/boot.3dsx` and `/gm9/`. Areas for a port's
  `data_root`: `/3ds/`. `requires.min` keys: `firmware` (the system
  version without its region, `11.17.0`) and `luma`.

### A.3 PlayStation Vita (`vita`), draft

To be reviewed by someone who knows the platform.

- **Ids.** `title_id`: nine upper-case letters and digits
  (`^[A-Z0-9]{9}$`); a game's is four letters and five digits
  (`PCSE00000`). `app_id`: the `title_id` for the game and its update; an
  add-on's content id
  (`^[A-Z]{2}[0-9]{4}-[A-Z0-9]{9}_[0-9]{2}-[A-Z0-9]{16}$`).
- **Types**: `base` (`CATEGORY` `gd` in its `param.sfo`), `update` (`gp`),
  `dlc` (`ac`).
- **Versions.** `version_code`: `APP_VER` `XX.YY` as `XX`×100+`YY`
  (`01.03` gives `103`); `version_name`: `APP_VER`.
- **Formats**: `vpk`, and `pkg` only with its licence.
- **Paths**: `/ux0/`, `/ur0/` and `/uma0/` are the storages `ux0:`, `ur0:`
  and `uma0:`.
- **Cheats.** VitaCheat's `.psv` files, at
  `/ux0/vitacheat/db/<title_id>.psv`; no `build_id` (to check: VitaCheat is
  closed source).
- **Saves.** The game's save data as `device`; the zip holds the decrypted
  folder `ux0:user/00/savedata/<title_id>/`, with its `sce_sys/`, at the
  root of the archive.
- **Homebrew.** Format `vpk`, unpacked and promoted by the client, which
  asks the user first: no `path`, and the app lands in
  `ux0:app/<title_id>/`. `system_id`: that title id. One architecture, so
  no `arch`. Roots without consent: `/ux0/data/<id>/`. Roots that need
  consent: `/ux0/tai/`, `/ur0/tai/` and the plugins' `config.txt` in them
  (to check: which of them takes precedence). Areas for a port's
  `data_root`: `/ux0/data/`.

### A.4 PlayStation 4 (`ps4`), draft

To be reviewed by someone who knows the platform.

- **Ids.** `title_id`: four upper-case letters and five digits
  (`^[A-Z]{4}[0-9]{5}$`, `CUSA00000`). `app_id`: the `title_id` for the
  game and its update; an add-on's content id
  (`^[A-Z]{2}[0-9]{4}-[A-Z]{4}[0-9]{5}_[0-9]{2}-[A-Z0-9]{16}$`).
- **Types**: `base`, `update`, `dlc`.
- **Versions.** `version_code`: `APP_VER` `XX.YY` as `XX`×100+`YY`;
  `version_name`: `APP_VER`.
- **Formats**: `pkg`.
- **Paths**: `/` is the system's root as homebrew see it; `/data/` is
  `/user/data/`.
- **Cheats.** GoldHEN's formats, `json`, `shn` and `mc4`, at
  `/data/GoldHEN/cheats/<format>/<title_id>_<build_id>.<format>`, one format
  per title and version. `build_id`: the game's `APP_VER` (`01.03`), with
  `_<process>` when a set is for another process than the game's.
- **Saves.** `account`, one backup per save directory, its `slot` the
  directory's name (to check: how they lie on the disk).
- **Homebrew.** Format `pkg`, installed by the system's package service,
  which shows nothing: the client asks the user first (to check). No
  `path`. `system_id`: its title id. One architecture, so no `arch`. Roots
  without consent: `/data/<id>/`. Roots that need consent:
  `/data/GoldHEN/`. Areas for a port's `data_root`: `/data/`.
  `requires.min` keys: `firmware` and `goldhen`.

### A.5 Android (`android`), draft

To be reviewed by someone who knows the platform.

- **Ids.** `title_id`: the app's package name
  (`^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$`); `app_id`: the same.
- **Types**: `base` only: a newer package of the same `app_id` replaces the
  old one, and is the update § 6.3 looks for. The system has no add-ons,
  and this version has no expansion files (OBB).
- **Versions.** `version_code`: the package's `versionCode`;
  `version_name`: its `versionName`.
- **Formats**: `apk`, and `apks` (split packages, installed in one session).
- **Cheats**: none.
- **Saves**: no profile (an app's data is its own).
- **Homebrew.** Formats `apk` and `apks`, installed by the system's
  installer: no `path`. The installer asks the user, unless the client is
  the app's installer of record and the conditions of `setRequireUserAction`
  hold. `system_id`: the package name. `signer_sha256` (§ 8.2): the
  SHA-256 of the signing certificate, which an update must share. `arch`,
  from Android's ABIs: `arm64-v8a` is `aarch64`, `armeabi-v7a` is
  `armhf`, `x86` is `x86` and `x86_64` is `x86_64`; a package without
  `arch` holds every ABI it needs. Areas for a
  port's `data_root`: a folder the user picks for it (to check).
  `requires.min` keys: `sdk` (the lowest API level, `26`). Android 14 and
  15 refuse a package whose `targetSdkVersion` is below 23 and 24.

### A.6 Linux (`linux`), draft

To be reviewed by someone who knows the platform.

One platform for every Linux system, a computer or a handheld, whatever its
distribution: what differs between them (architecture, C library,
graphics, memory, screen) is said by `arch` (§ 8.2) and `requires`
(§ 8.7), not by a platform name.

- **Ids.** Linux has no id of its own for installed software: no
  `system_id`. This version serves homebrew only: a server MAY serve apps
  under the core's rules, as on an open platform (§ 4.3), and a client
  installs none of them.
- **Paths.** `/` is the folder the client chose for homebrew, and showed
  the user: on a handheld, its ports folder as PortMaster uses it (to
  check: it differs between distributions, such as `/roms/ports/`); on a
  computer, `$XDG_DATA_HOME` (`~/.local/share/`), so that a homebrew's
  own folder is `$XDG_DATA_HOME/<id>/`. A client writes nothing outside
  that folder.
- **Homebrew.** Format `zip`, an archive with a manifest (§ 8.2); no single
  file. A file is made executable (mode `0755`, else `0644`) when the
  archive's entry for it has its owner's execute bit (the zip's external
  attributes); the client never sets another bit (setuid, setgid, sticky),
  and refuses a package whose archive holds a link at a manifest's path.
  Roots without consent: `/<id>/`. Roots that need consent: the rest of
  `/`, such as a launcher script next to the ports' folders, or a port's
  folder of the name PortMaster gives it; a client refuses a path that
  another installed homebrew's manifest holds. `arch`: `aarch64`, `armhf`,
  `x86`, `x86_64` and `riscv64`. Areas for a port's `data_root`: `/`, the
  client's folder (a port's data folder, such as `/<id>/data/`, lies in
  it). `requires.min` keys: `glibc`, `ram_mb` and `screen`; the graphics
  interfaces go in `requires.gpu` (§ 8.7; to check: how a client learns
  them, such as from EGL and Vulkan's loader).
- **Cheats**: none in this version.
- **Saves**: none in this version (no system saves).
- **PortMaster.** Most ports for Linux handhelds follow
  [PortMaster](https://portmaster.games/)'s packaging: a launcher script in
  the ports folder, the port's files in a folder next to it, and the
  game's data supplied by the user. A Lantern port of that kind keeps that
  layout (the script and the folder need consent, above) and says in
  `requires_data` (§ 8.6) what the user supplies. PortMaster names its
  architectures `aarch64`, `armhf` and `x86_64`, as Lantern does, so a
  port's list carries over as it is (to check).

### A.7 Open platforms

Open: no profile yet. `ios`, `windows`, `macos` and `web`, and Atlas's
store names (`steam`, `gog`, `xbox`), have none; § 4.3 says what a server
and a client do on them.

## Annex B — Client guidelines

Not normative: advice from what consoles and phones meet in use. A client
that follows it is kinder to its users and to the servers it reads.

### B.1 Timeouts

- Connect: 10 seconds, 3 on the LAN; the TLS handshake within the same
  time.
- A JSON request: 30 seconds without a byte, 60 in all.
- A file: no limit in all, but 60 seconds without a byte, then resume
  (B.4).
- Polling a pairing: as `interval` says, until `expires`.

### B.2 Retries

- Retry only what can be retried: `GET`, `HEAD`, `PUT` and `DELETE`; the
  `POST`s that only read (`apps/missing`, `homebrew/updates`); a `PATCH`
  of an upload after a `HEAD` that says where to resume. Never retry
  another `POST` blindly: a request posted twice is two requests.
- Retry after a connection lost, `408`, `429`, `500`, `502`, `503` and
  `504`; never after another `4xx`.
- Back off exponentially with full jitter: before try *n*, wait a random
  time between 0 and min(60, 2^*n*) seconds; give up after 5 tries, and
  say so.
- `Retry-After` is a floor: wait at least that long, whatever the backoff
  says.
- After `401` `signature_expired`, sign again once with the server's
  `Date` (§ 5.4); after any other `401`, ask the user to pair again
  rather than retry.

### B.3 Offline, from the cache

- Keep the last handshake, the pages read, the titles and their images,
  each with its `ETag`; revalidate with `If-None-Match` when online.
- With no server, show the cached library, marked offline with its age;
  what needs the server (a download, a backup) waits and says so.
- A cached document of a newer `schema` is absent, as on the wire (§ 3.2).
- Nothing is installed from the cache without its SHA-256 checked.

### B.4 Downloads that survive sleep

- Write to a partial file, and keep its URL, its `ETag` and the app's
  `sha256` beside it; hash as the bytes arrive, keeping the state of the
  hash, or hash the partial file again on resuming.
- After sleep or a lost connection, resume with `Range: bytes=<have>-` and
  `If-Range: <ETag>`. A `206` goes on; a `200` means the file changed:
  start again. A `404` or `410` means its id expired: read the app again
  and compare its `sha256`.
- On a console, hold a sleep lock while downloading if the system has one,
  and say that a download pauses with the console.
- A save's upload resumes the same way, from `HEAD`'s `Upload-Offset`
  (§ 9.3).

### B.5 Several servers

- A file is its SHA-256: two apps of the same `sha256` are the same
  package, whatever server lists them. Show it once, with its servers;
  take it from the fastest (the LAN first), and check it the same way.
- Titles merge by `platform` and `title_id`; homebrew by `platform` and
  `id`, the highest `build` first. A homebrew's pinned key is the id's,
  whatever the server: a server cannot bring another key (§ 8.4).
- Each server keeps its own token, key, pin and rating cap; a cap one
  server sets says nothing of another.

### B.6 Errors and fingerprints

- Show an error's `title` and `detail` (§ 12), bounded, without control
  characters, with the server's name; the status and `code` in small, for
  a report; never the raw JSON.
- Show a fingerprint in monospace, in groups of 4, large enough to compare
  across a room. At pairing, the code, the fingerprint and the QR code
  side by side (§ 5.2, § 5.3).
- A changed key is an alarm, not an error: say that the server's key
  changed, show both fingerprints, and pair again only when the user asks.

### B.7 A port's data, before launch

- Check § 8.6's files before each launch; keep their hashes by size and
  time of change, so that a launch needs no new hashing unless a file
  changed.
- Show each missing or unknown file with its `hint`; when a group
  (`one_of`) has several ways, show them all.
- Check again as soon as the user says they copied the files.

### B.8 A cold start's budget

The first start of a client on a server it paired with, before its first
screen, needs at most:

| Request | What |
|---|---|
| 1 | `GET <base>/v1/` (§ 4.2) |
| 2 | The first page of the library, `page_size=50` (§ 6.2), or of homebrew |
| 3 | The titles of the apps on screen, at once (`GET <base>/v1/titles?ids=`, § 7.2) |

that is 3 requests, and 256 KiB of JSON at most as they travel (compressed
when the server compresses, § 2.1). Images come after, lazily, cached by
their content. The conformance suite measures these three requests on a
server and warns when they take more than 256 KiB.

### B.9 Clocks

A console's clock is often wrong. Take the offset to the server's `Date`
from the handshake's response, and sign with it (§ 5.4); show times in the
device's own zone.

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
- 0.3 (2026-10-30): every platform Aurore runs on, and four families;
  still `/v1/` and `schema` 1, as a draft. Files become § 6.6, and the
  sections from 7 on are renumbered: errors are § 12.
  - Platforms (§ 4.3, Annex A): a core that knows no platform, and a
    profile per platform. Every app, title, homebrew, save and cheat set
    carries `platform`; the handshake lists `platforms`; a client names its
    own with `Lantern-Platform` (or `?platform=`), and the server answers
    for it alone. Atlas's platform names, and `3ds`, `vita`, `ps4`,
    `android`, `ios`, `windows`, `macos`, `linux` and `web`. Profiles: the
    Switch's complete; the 3DS's, the Vita's, the PS4's, Android's and
    Linux's (one platform for computers and handhelds alike) as drafts;
    the others open, where a client installs nothing.
  - Apps (§ 6.1): `title_id` and `app_id` are opaque strings of the
    profile's form, `type` and `format` come from its lists, and `version`
    and `display_version` become `version_code` and `version_name`. What
    is missing (§ 6.3) needs a platform.
  - Titles (§ 7): `titles` replaces `media`, with developer, genres from a
    fixed list and tags, players on one device and online, age ratings
    per organisation, a localized summary and description, images and an
    external video, and `updated`; many titles in one request, and their
    changes.
  - Homebrew (§ 8): a new family: entries with a stable reverse-DNS id, a
    `kind` and a `build` to compare, packages of one file or a zip with a
    manifest, per architecture where a platform has several, the rules a
    client follows to install and uninstall them, an optional ed25519
    signature whose key is pinned per id, and the updates of what is
    installed; dependencies on other homebrew, and the platform's own id
    of what is installed, which a client never lets two entries share.
    Game ports name their original game, engine and data folder, and the
    files the user supplies from their own copy, which a server never
    serves. Mods are out of scope.
    Shelves come from `kind` and `genres` (the titles' list), with free
    `tags`, and the listing filters by `kind` and `genre`. Requirements
    (§ 8.7) a client checks before it offers a package: `requires.min`
    (`glibc`, `ram_mb`, `screen`, and the profile's keys) and
    `requires.gpu`; one it cannot read gives a warning, one that fails a
    refusal. Architectures add `riscv64`; one a reader does not know is
    never its own.
  - Saves (§ 9): resumable uploads in chunks; `Content-Digest` required on
    a save sent in one request, and checked (422 `digest_mismatch`); a
    save's `kind`, `slot`, `game_version_code`, `profile` and `platform`; the
    handshake's `limits` say the sizes and how many backups are kept.
  - Cheats (§ 10): several sets per build, each with its id, source,
    update time and SHA-256, read by id; writing them needs
    `cheats.write`.
  - Requests (§ 11) carry `platform`.
- 0.4 (2026-10-30): access and the quality of the text; still `/v1/` and
  `schema` 1, as a draft. Every 0.3 route and field stays, with the
  additions below; § 5 becomes "Authentication and access".
  - Requirement ids (§ 3.5): every MUST and SHOULD has its id, `L-<section>-<n>`,
    which the suite's checks name. Rules the 0.3 suite already enforced as
    plain statements are now written as requirements (MUST), without
    changing their meaning; a client sends its token and signatures to the
    server's origin alone (§ 2).
  - Device keys and signed requests (§ 5.4, feature `signatures`): an
    Ed25519 key made at pairing, `key` in the pairing request; requests of a
    bound token signed by RFC 9421 (`@method`, `@target-uri`,
    `authorization`, `content-digest`; `created`, `nonce`, `keyid`, `alg`)
    within a skew of 300 seconds, nonces kept against replay; the poll of a
    keyed pairing signed; new codes `signature_required`,
    `signature_invalid`, `signature_expired`, `signature_replayed` (401) and
    `key_required` (400). Tokens without a key are bearer-only, which a
    server MAY refuse. The handshake adds `auth`, `account.bound` and
    `features.signatures`.
  - Pairing (§ 5.2): `verify_complete`, for a QR code a client draws, the
    code and fingerprint still shown next to it; the token's document adds
    `bound` and `rating_cap`.
  - Invitations (§ 5.5), rating caps (§ 5.6, with a table of ages per
    rating system) and an administration API (§ 5.7, feature and scope
    `admin`): accounts, devices, pairings waiting, invitations; 409 for an
    account that exists, 410 for an invitation that does not.
  - `Accept-Language` (§ 2.2) chooses the language of errors and of the
    handshake's `motd`; a problem and the handshake carry `language`.
  - Compression (§ 2.1): `zstd` or `br`, and `gzip`, recommended on JSON,
    never on files; a note on HTTP/2.
  - `Deprecation` and `Sunset` (§ 3.4); how the text changes (§ 3.5).
  - `atlas` on apps, titles and homebrew (§ 6.1); `installed_size` on apps
    and packages, and a client that decides what fits (§ 6.3); `ratings`
    on homebrew (§ 8.1).
  - `DELETE <base>/v1/requests/{id}` (§ 11).
  - A server refuses a document beyond the limits without failing (§ 13).
  - A threat model (§ 16); conformance levels, the name and the badge
    (§ 17); test vectors (`vectors/`); client guidelines (Annex B).
