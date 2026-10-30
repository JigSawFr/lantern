# Lantern — an open protocol for game library servers

Draft 0.7, 2026-10-30. Status: **draft**, open to change until 1.0 (Annex C says what it
waits for).
This text is licensed under [CC BY 4.0](LICENSES/CC-BY-4.0.txt).

Lantern lets a client (a homebrew on a console, or an app on a phone, a
computer or in a browser) browse a library server the user runs for their
own games, download games and homebrew from it with integrity checks, read
what it knows about each game, and keep save backups and cheats there. It
is a small REST/JSON contract, versioned so that a client and a server of
different ages keep working together. Its read routes also work as plain
files (§ 21), on a web host or a USB key. It is a protocol of its own: it owes
nothing to the protocols in use before it and keeps nothing for their sake.

Its core knows no platform: listing, downloads, pairing and errors work the
same for a Nintendo Switch, a phone or a computer. What differs from one
platform to another (the form of a game's id, its package formats, where
cheats, saves and homebrew go) is in that platform's profile, in Annex A.

The key words MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT and MAY are used
as in RFC 2119 and RFC 8174, in capitals only. Each requirement has a stable
id written next to it in brackets, such as `[L-5.2-3]`: § 3.5 says how ids are
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
  for testing. A client MUST NOT speak plain HTTP to any other address,
  but to fetch a file by its SHA-256 from a mirror or a peer on a private
  network, as § 19 allows. [L-2-2] A server MUST NOT serve Lantern in plain HTTP on one. [L-2-3]
- All routes live under a base path the server chooses (default
  `/api/lantern`), announced by discovery (§ 4.1) and the handshake (§ 4.2).
  Below, paths are relative to `<base>`.
- JSON bodies MUST be UTF-8, sent with `Content-Type: application/json`
  (errors: `application/problem+json`, § 12). [L-2-4]
- The client MUST send `User-Agent: <Name>/<version>`, but a client in a
  browser, whose browser writes it (Annex A.7). [L-2-5] It SHOULD send
  `Accept-Language` (§ 2.2). [L-2-6] It SHOULD send `Lantern-Platform`
  (§ 4.3), but a client in a browser, which names the platform it shows
  in the query instead (Annex A.7). [L-2-7]
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

### 2.3 Values

The forms every document and every route share, so that two readers never
read one value two ways:

- **JSON.** Every document is I-JSON (RFC 7493): UTF-8 without a byte order
  mark, no member name twice in one object, no unpaired surrogate, and
  every integer between −(2^53 − 1) and 2^53 − 1, written without a
  fraction or an exponent (`size` and `version_code` included). A server
  MUST write only such documents, and answer `400` to a request document
  that is not one. [L-2.3-1]
- **Times.** A time is RFC 3339's `date-time` in UTC, with `Z` and no
  offset: `2026-10-30T09:12:03Z`, or with a fraction of a second,
  `2026-10-30T09:12:03.250Z`. A date, such as a title's `release`, is
  `2026-03-14`. A server MUST write every time and date of its documents in
  these forms. [L-2.3-2] A reader MUST read a fraction of 1 to 9 digits
  where this text does not bound it (a sync item's `updated` has 3 at
  most, § 20.2). [L-2.3-3]
- **Digests in hex** are lower-case: `sha256`, `manifest_sha256`,
  `signer_sha256`, a save key's id, and the `{hex}` of a path (§ 19.3,
  § 19.4, § 21.1). A server MUST write them in lower case, and answer
  `404` to a route whose path holds a SHA-256 that is not 64 lower-case
  hex digits. [L-2.3-4] A reader compares them as they are, case included.
  A short fingerprint (§ 5.3), for people, is the only hex in upper case;
  the ids of a platform (Annex A) have their own forms.
- **Base64** is RFC 4648 § 4's, with its padding; **base64url**, § 5's,
  without it. Each field says which.
- **Canonical JSON**, where this text compares or hashes a value by its
  bytes (a sync item's value, § 20.4; a chunk index, § 22.1), is RFC
  8785's JSON Canonicalization Scheme: no space; the members of each object
  sorted by their names as UTF-16 code units; in strings, only `"`, `\`
  and the control characters escaped (`\b`, `\t`, `\n`, `\f`, `\r`, the
  others as `\u00xx`, in lower case), every other character as it is, in
  UTF-8; and numbers as ECMAScript writes them: an integer without a
  fraction or an exponent (`1.0` and `1` are both `1`, `-0` is `0`), any
  other in the shortest form that reads back the same number (`0.5`,
  `1e+21`, `1e-7`, but `100000000000000000000` and `0.000001`). A reader
  keeps a number as the document wrote it until it writes it so. The
  canonical forms of § 8.2, § 8.4 and § 19.3, spelled out where they are
  given, agree with it. Test vectors: `vectors/canonical-json.json`.
- **Text for people** (names, summaries, notes) is Unicode. A server SHOULD
  write it in Normalization Form C. [L-2.3-5] Where this text compares or
  searches names (`q`, § 6.2 and § 8.5; the paths of a manifest, § 8.2), it
  compares them by Unicode's canonical caseless match (The Unicode
  Standard § 3.13, D145: NFD, then default case folding, then NFD), so that
  `É` and `é`, or `ß` and `ss`, are the same; a server MUST compare them
  so. [L-2.3-6] Ids, codes, tokens, keys and listed values (a platform, a
  `kind`, a genre) are compared exactly, byte for byte.
- **Nothing** is an empty list, never an error: a listing that has nothing
  for its caller and its filters MUST answer `200` with `"items": []`,
  `"next": null` and, when it gives one, `"total": 0`. [L-2.3-7] A file
  may be empty: its `size` is 0, it has a SHA-256 like any other
  (`e3b0c442…`), and any `Range` of it gives `416` (RFC 9110 § 14.1.1).

### 2.4 Routes and queries

- A route's path is the one this text writes, below `<base>`, its segments
  percent-encoded as RFC 3986 says (the ids of this text need no encoding).
  A trailing `/` makes another path: `<base>/v1/apps/` is not a route, and
  gives `404`; `<base>/v1` and `<base>/v1/` are both the handshake. A
  server MUST NOT answer a route of this text with a redirect (`3xx`).
  [L-2.4-1] A client MUST NOT follow a redirect of a route, so that its
  token and its signatures go only where it sent them (§ 2). [L-2.4-2]
- Each query parameter is given once: a server MUST answer `400` to a
  request that gives one twice (`?type=base&type=dlc`). [L-2.4-3] A list is
  one parameter, its values comma-separated (`ids`, § 7.2).
- A parameter with an empty value is absent: `?platform=&type=` asks for
  every platform and every type, so that a client may fill in a template
  as this text writes it. A server MUST read it so. [L-2.4-4] It MUST
  ignore a parameter this text does not give for that route, so that a
  later version can add one; that version says how a client learns that a
  server reads it. [L-2.4-5]
- Every route that answers `GET` MUST answer `HEAD` as it answers `GET`:
  the same status and headers, without a body (RFC 9110 § 9.3.2).
  [L-2.4-6] But a pairing's poll (§ 5.2), which a `HEAD` would not
  collect, and the event stream (§ 18.1), which never ends, MAY answer
  `HEAD` with `405`.
- A request document is sent with `Content-Type: application/json`, a
  `charset=utf-8` parameter allowed. A server MUST answer `400` to a
  route's document of another type. [L-2.4-7]

### 2.5 Browsers

A client in a web browser (Annex A.7) reads a server of another origin
only as the browser's CORS rules let it (the WHATWG Fetch standard): the
server names the origins whose pages may read its answers, and before any
request that is not a simple one, the browser asks first with a
**preflight**, an `OPTIONS` request that carries no token. Nearly every
Lantern request needs one: a request with a token, a signature, a JSON
body, `Lantern-Platform`, `Accept-Schema`, `If-None-Match`, `If-Match` or
`Upload-Offset`, and every `PUT`, `PATCH` and `DELETE`. Only a `GET` or a
`HEAD` without them, with at most `Accept`, `Accept-Language` and a single
`Range`, goes without one.

- A server SHOULD let its owner name the origins whose pages may read it
  (`https://app.example.org`), or every one (`*`), and allow none until
  they do. [L-2.5-1]
- To a request whose `Origin` it allows, on a route of this text
  (`/.well-known/lantern`, and every route below `<base>`), a server MUST
  answer, errors included, with `Access-Control-Allow-Origin`, that origin
  (then with `Vary: Origin`) or `*`, and with `Access-Control-Expose-Headers`
  naming the headers of this text that a page reads: `Date`, `ETag`,
  `Content-Range`, `Accept-Ranges`, `Repr-Digest`, `Retry-After`,
  `WWW-Authenticate`, `Accept-Signature`, `Upload-Offset`, `Upload-Length`,
  `Lantern-Chunk-Size`,
  `Allow`, `Deprecation`, `Sunset` and `Link`. [L-2.5-2]
- To a preflight of such a request (`OPTIONS` with
  `Access-Control-Request-Method`), whatever its route, a server MUST
  answer `204` without asking for a token, with `Access-Control-Allow-Origin`
  as above, `Access-Control-Allow-Methods` naming the method asked (or
  `GET, HEAD, POST, PUT, PATCH, DELETE`), and `Access-Control-Allow-Headers`
  naming one by one each header asked that this text gives a client:
  `Authorization`, `Content-Type`, `Content-Digest`, `Signature`,
  `Signature-Input`, `Accept-Schema`, `Lantern-Platform`, the headers of a
  save (§ 9.2, § 9.4), `Upload-Offset`, `If-Match`, `If-None-Match`,
  `If-Range`, `Range` and `Last-Event-ID`. [L-2.5-3] The Fetch standard's
  `*` does not cover `Authorization`, which is named. A server SHOULD give
  `Access-Control-Max-Age`, of 600 seconds or more, so that a page does
  not ask before each request. [L-2.5-4]
- Credentials go in `Authorization` alone (§ 5.1). A server MUST NOT send
  `Access-Control-Allow-Credentials`, set a cookie on a route of this
  text, or take a token or any credential from a cookie. [L-2.5-5] A page
  thus sends a server nothing its browser keeps for it, and a page of
  another origin borrows nothing of the user's.
- To an origin it does not allow, a server sends none of these headers:
  the browser keeps its answer from the page. It answers the request
  itself as it would without `Origin`, and an `OPTIONS` that is not a
  preflight of an origin it allows with `405`.
- A server on a private network MAY answer a preflight that carries
  `Access-Control-Request-Private-Network: true` with
  `Access-Control-Allow-Private-Network: true`, for an origin it allows,
  as some browsers ask before a public page reads a private address.

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
- Each schema's `$id` is its stable address,
  `https://lantern.boreale.dev/schemas/v1/<name>.json` (`apps.json`,
  `common.json`…), where the site serves it: the address of a schema of
  `/v1/` never changes, and each release of this text (§ 3.6) carries the
  same files.
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

### 3.6 Releases

Each version of this text is released on the repository, by a tag
`spec-v<version>` (`spec-v0.7`): its release holds SPEC.md, the schemas,
their examples, the test vectors, `openapi.yaml` and the conformance suite,
each as an asset of its own and all in one zip, with their SHA-256 sums in
`SHA256SUMS`. GitHub attests that each asset was built from that tag by the
repository's release workflow (a build provenance attestation, SLSA). To
check an asset:

```sh
gh attestation verify lantern-0.7.zip --repo JigSawFr/lantern
sha256sum --check --ignore-missing SHA256SUMS
```

An implementation names the version it follows, and the suite of that
release checks it (§ 17).

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
  only addresses of its own networks. [L-4.1-2] It SHOULD answer the same
  address 10 times a second at most, and stay silent beyond. [L-4.1-3]
- A server SHOULD also advertise itself with DNS-SD (RFC 6763) over
  multicast DNS (RFC 6762) as `_lantern._tcp`, with the TXT keys
  `uid=<uid>`, `path=<base>` and `v=1` (the versions, comma-separated).
  [L-4.1-4] The reference server does, with the standard library alone; a
  client that cannot read multicast DNS uses the datagram.
- A datagram with `"peers": true` also asks the consoles that share files
  (§ 19.5); a server answers it as any other.
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
              "pairing": 1, "signatures": 1, "admin": 0, "events": 1,
              "peers": 1, "sync": 0, "encrypted_saves": 1, "deltas": 1},
 "auth": {"bearer_only": true, "skew": 300},
 "peers": {"key": "<base64 of 32 bytes>", "grant_lifetime": 600},
 "limits": {"page_size": 500, "save_body": 8388608,
            "save_size": 1073741824, "saves_kept_per_title": 10,
            "heartbeat": 15, "event_streams": 2, "wait": 60}}
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
  `cheats`, `cheats.write`, `requests`, `admin`, `sync.read`, `sync.write`.
  `library` covers every read of the catalogue: apps, titles and homebrew.
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
- `limits`: `page_size`, the most items on a page (§ 6.2), 1 to 1000; with `saves`,
  `save_body`, the largest save a single request takes (§ 9.2),
  `save_size`, the largest save at all (§ 9.3), and
  `saves_kept_per_title`, how many backups the server keeps per title,
  platform and account before it drops the oldest (§ 9.1); with `events`,
  `heartbeat`, `event_streams` and `wait` (§ 18.4); with `sync`,
  `sync_items` (§ 20.5).
- `peers`, with the family `peers`: the public key of the server's grants
  and their lifetime (§ 19.3). `static`, in a static library's handshake
  only (§ 21.2).
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
no name per distribution) and `web` (a client in a web browser, which
installs nothing: Annex A.7). A later version adds names to this list; a
vendor's own begins with `x-<vendor>-`.

- Every app (§ 6.1), title (§ 7), homebrew (§ 8), save (§ 9) and cheat set
  (§ 10) carries its `platform`.
- A client says its own platform with the header
  `Lantern-Platform: <name>` on every call, as § 2 asks (`L-2-7`).
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
  `title_id` or a homebrew `id` known on several platforms MUST give `400`
  too, until the client names the platform. [L-4.3-8]
- `?platform=<name>` on a listing (or on a route that needs a platform)
  MUST override the header. [L-4.3-5]
- Responses that depend on the platform SHOULD carry
  `Vary: Lantern-Platform` (§ 14). [L-4.3-6]
- A platform's profile (Annex A) says what the core leaves open. On a
  platform with no profile yet (Annex A.8), a server MAY serve apps and
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
  shown in groups of 4 joined by `-`. [L-5.2-5] A server MUST read a code
  the user types, on its page or through § 5.7, ignoring case, spaces and
  dashes: `kq4m 7txd` is `KQ4M-7TXD`. [L-5.2-14]
- `interval` is 1 to 60 seconds.
- A code MUST expire within 10 minutes (`expires`, in seconds, at most
  600). [L-5.2-6] The poll address MUST be unguessable (at least 128 bits)
  and give the token once. [L-5.2-7]
- The server MUST limit pairing requests per address and attempts at a
  code: beyond them it answers `429` `slow_down` with `Retry-After`.
  [L-5.2-8] It SHOULD answer `429` `slow_down` to polls more often than
  `interval`. [L-5.2-9] It MUST count `interval` from the last poll it
  answered with `202` or `200`, never from one it refused with `429`, and
  give in `Retry-After` the seconds left until it answers again: a client
  that waits as long as `Retry-After` says, then `interval` between its
  polls, always gets its token. [L-5.2-15]

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
- **Keys of small order.** A server MUST refuse at pairing, with `400`, a
  device key that does not decode canonically or is one of the 8 points of
  small order. [L-5.4-12] It checks every signature of a request as § 8.4
  says (`L-8.4-4`): a key or an R of small order, or S at L or above,
  never verifies.
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
  query and the server's `spki=<its key's whole SHA-256, lower-case hex>`
  (§ 5.3), always when no CA vouches for its certificate.
- `user`: the account the devices join; `scopes`: what they may do, a
  subset of that account's; `expires`: when it stops, 30 days ahead at
  most; `devices`: how many devices may redeem it, 1 to 100; `used`: how
  many did; `rating_cap` (§ 5.6) and `note`, optional.
- A device redeems it by pairing (§ 5.2) with `"invitation": "<code>"`,
  which a server MUST read ignoring case, spaces and dashes, as a pairing
  code (§ 5.2). [L-5.5-4] The pairing is approved at once, for the invitation's account, with the
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
| `DELETE <base>/v1/admin/users/{name}?confirm=<name>` | Deletes the account → `204`: its devices, invitations and waiting pairings, its save backups, requests and sync data. |
| `GET <base>/v1/admin/devices?user=` | The devices, one token each: `{"id":"d_…", "user":"lea", "device":"Lea's Switch", "scopes":[…], "created":"…", "bound":true, "key":"<short fingerprint>", "rating_cap":{…}, "invitation":"i_…", "expires":"…"}`. |
| `DELETE <base>/v1/admin/devices/{id}` | Revokes the device's token → `204`. |
| `GET <base>/v1/admin/pairings` | The pairings waiting for approval: `{"id":"pr_…", "code":"KQ4M-7TXD", "device":"Lea's Switch", "scopes":[…], "key":"<short fingerprint>", "created":"…", "expires":"…"}`. |
| `POST <base>/v1/admin/pairings/{id}` | `{"schema":1, "decision":"approve", "user":"lea", "scopes":["library"], "rating_cap":{"age":12}}` → `204`; `"decision":"refuse"` → `204`, and the device's poll gets `410`. |
| `GET <base>/v1/admin/invitations` | The invitations that can still be redeemed (§ 5.5). |
| `POST <base>/v1/admin/invitations` | `{"schema":1, "user":"sam", "scopes":["library"], "expires":"2026-11-06T18:00:00Z", "devices":2, "rating_cap":{"age":12}, "note":"…"}` → `201` the invitation, with its `code` and `link`. |
| `DELETE <base>/v1/admin/invitations/{id}` | Revokes it → `204`: its code gives `410`. |
| `GET <base>/v1/admin/requests?status=&user=&platform=` | Every account's requests (§ 11), newest first, each with its `user`. |
| `POST <base>/v1/admin/requests/{id}` | `{"schema":1, "decision":"decline", "reason":"…"}` or `{"schema":1, "decision":"done"}` → `200` the request (§ 11). |

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

**Deleting an account.** `confirm` repeats the account's name, so that a
slip of the finger deletes nothing; an admin app asks its user to type it.

- A server MUST refuse a deletion whose `confirm` is not the account's
  name, with `400`, and the deletion of the caller's own account, with
  `409` `conflict`. [L-5.7-6] It MAY refuse, with `409` `conflict`, to
  delete an account its own configuration defines (a file of accounts it
  only reads), and says so in `detail`.
- A deletion MUST take effect at once and whole: the account's tokens give
  `401` from their next request, its invitations `410`, its pairings
  waiting are refused, and its save backups, requests and sync data
  (§ 20) are erased; the name then gives `404` on this family's routes.
  [L-5.7-7] An account later made with the same name inherits nothing of
  it.
- A deletion cannot be undone: the protocol keeps no account in a bin.

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
- `size`: bytes, an integer of I-JSON's range (§ 2.3: 8 PiB at most). `installed_size`, optional: the bytes
  the app takes once installed, when the server knows them (an `nsz`'s,
  decompressed), which a client compares with its free space (§ 6.3).
- `format`: a lower-case word from the profile's list of package formats.
- `sha256`: of the file as served, lower-case hex. A server MUST give it,
  having hashed the file before it lists it. [L-6.1-1]
- `atlas`, optional: the game's id in [Atlas](https://atlas.boreale.dev/),
  the open data on games of Boréale: its Wikidata item, `Q` and digits
  (`Q900001`), the key of Atlas's `links.json`, which ties a game's ids on
  every platform together (a Switch title id, a Steam app id…). A client
  MAY read Atlas's data with it (how well known a game is,
  similar games); Atlas's files of one platform are keyed by that
  platform's own ids, which `links.json` gives. It is a hint about the
  game, never its identity: a client MUST NOT install or match anything by
  `atlas` alone. [L-6.1-2] Atlas is an external address (§ 7.1).
- `mirrors`, optional: other addresses of the same file, which a client may
  read it from (§ 19.2).
- `chunks`, optional: where the file's chunk index is, for an update that
  downloads only what changed (§ 22).

### 6.2 Listing

`GET <base>/v1/apps?platform=&type=&title_id=&q=&sort=&page_size=&cursor=` →

```json
{"schema": 1, "items": [App, …], "total": 4123, "next": "c_…"}
```

- `platform` overrides `Lantern-Platform` (§ 4.3); `type` and `title_id`
  MUST filter, and `q` keep the apps whose `name` holds it, compared as
  § 2.3 says. [L-6.2-1] `q` is 256 bytes at most.
- `sort`: `name` (the default), by `name` compared as § 2.3 says;
  `added`, newest first; or `release`, newest first by the release of the
  app's title, those without one last. Ties MUST be broken by `id`,
  compared as bytes, smallest first, so the order is stable. [L-6.2-2]
- `cursor` is opaque; `next` is `null` on the last page. Reading with a
  cursor while the library changes MUST neither skip nor repeat an app.
  [L-6.2-3]
- A cursor MUST give `410` when it expired (the client then reads the list
  from its start), and `400` when the server never gave it, or gave it for
  another listing (or `410`, when the server cannot tell it from an expired
  one). [L-6.2-4]
- `page_size` is at most `limits.page_size`; a larger one MUST be lowered
  to it. [L-6.2-5] One that is not a positive integer, or a `q` above 256
  bytes, MUST give `400`. [L-6.2-6] Without `page_size`, the server
  chooses, within `limits.page_size`.
- `total`, optional, is how many items the whole listing holds for this
  caller and these filters, when the server counts them.

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

`installed` is always sent, and may be empty (a console with nothing yet);
`want` holds one or more of `base`, `update` and `dlc`. A server MUST
answer `400` to a `want` empty or with another value, and ignore an
installed `app_id` it does not know; an `app_id` listed twice counts by its
highest `version_code`. [L-6.3-2]

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
An app whose file changed is another app (its `id` changes, § 6.1): the
old id is in `removed`, the new app in `added`.
With `wait`, a request waits for what changes, and its document carries
the events of § 18 (§ 18.3).

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
- MUST honour `If-Range` with its `ETag` (RFC 9110 § 13.1.5): the range
  when the tag matches, the whole file (`200`) otherwise, so that a client
  resuming a file that changed starts again (Annex B.4). [L-6.6-6]
- A request of several ranges MAY get the whole file (`200`); a server MUST
  NOT answer `multipart/byteranges`, which no client of this text reads.
  [L-6.6-7] A suffix range (`bytes=-500`) is a range like another.
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
every id asked for in one of the two lists, an id asked twice once, and
answer `400` to more than 100 ids or to none. [L-7.2-1]

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
ignored, compared as § 2.3 says. A server MUST NOT serve a manifest that breaks these rules, or
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

A package MAY carry `mirrors`, as an app (§ 19.2), and `chunks` (§ 22).

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
- A verifier of an Ed25519 signature (of a homebrew here, of a request in
  § 5.4) MUST decode the public key and the signature's R first, and
  refuse the signature when either does not decode, is not encoded
  canonically (a y of p or more, or x = 0 with its sign bit set), or is one
  of the 8 points of small order ([8]P is the identity), and when S is L or
  more; only then does it check the equation. [L-8.4-4] Without that, a key
  and an R of small order with S = 0 pass the cofactorless equation for
  about one message in 8, and anyone can forge. Test vectors:
  `vectors/ed25519-refused.json`.
- On the first install of an `id`, the client pins its `public_key` (or
  that it had none). A later version signed by another key, or unsigned
  after a signed one, MUST be refused unless the user explicitly accepts the
  change, after the client showed both keys' short fingerprints (the
  SHA-256 of the 32 bytes, in the form of § 5.3). [L-8.4-3]
- A server MUST NOT serve a signature that L-8.4-4 refuses. [L-8.4-5]

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
which MUST hold the account's own backups, newest first per title (the
order of the titles is the server's), where a save is: [L-9.1-1]

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
  `other`, as the profile maps the platform's own kinds. A backup sent
  without one has none, and a reader reads it as `other`.
- `game_version_code`: the game's `version_code` (§ 6.1) when it was
  saved, so that a client SHOULD warn before restoring a save on an older
  game. [L-9.1-2]
- `profile`: the name the user gave the profile the save belongs to, as
  the device shows it. Never a hardware or account identifier.
- `device`: the name of the paired device that sent it (§ 5.2).
- `encryption`, only for a backup encrypted on the device: its scheme and
  key id (§ 9.4).
- The archive is a zip whose content the profile gives (Annex A); an
  encrypted backup's bytes are that zip, encrypted (§ 9.4).
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
3. `HEAD <upload>` MUST answer `204` with `Upload-Offset`,
   `Upload-Length` and `Lantern-Chunk-Size` (the upload's `chunk_size`):
   where to resume after an interruption, and in what chunks, for a client
   that kept only the upload's address. [L-9.3-3] A server keeps only whole
   chunks, or says in `Upload-Offset` how much of a cut one it kept.
4. The chunk that reaches `size` ends the upload: the server MUST check the
   whole archive's SHA-256, then answer `201` with the save entry, or `422`
   `digest_mismatch` and discard it. [L-9.3-4]

`DELETE <upload>` abandons an upload (`204`). An upload not finished by
`expires` is gone (`404` or `410`). Only the account that opened an upload
sees it.

### 9.4 End-to-end encryption (feature `encrypted_saves`)

A client MAY encrypt a backup before it sends it, with a key that only its
user's devices hold: the server then keeps bytes it cannot read. A server
that offers this family keeps such backups as they come, with the metadata
that stays in clear.

**The save key.** 32 random bytes, made once, from its system's secure
random source, by the first device of the user that encrypts, and carried
by the user to their other devices (below). It never goes to a server. Two
values come from it by HKDF-SHA-256 (RFC 5869), with an empty salt:

- the **key id**, the first 8 bytes of HKDF(info `lantern-save-e2e-1 key
  id`), written as 16 lower-case hex digits: which key a backup needs,
  stored and shown in clear;
- the **wrapping key**, 32 bytes of HKDF(info `lantern-save-e2e-1 wrap`).

**A backup, scheme `lantern-save-e2e-1`.** For each backup, the client
makes a random 32-byte **file key**, wraps it with the wrapping key, and
encrypts the archive (the zip of § 9.1) with it in chunks, with
XChaCha20-Poly1305 (draft-irtf-cfrg-xchacha-03: HChaCha20, then RFC 8439's
ChaCha20-Poly1305), as age's STREAM does with ChaCha20-Poly1305:

| Bytes | What |
|---|---|
| 0–7 | `LTNE2E01`, in ASCII |
| 8–15 | the key id's 8 bytes |
| 16–39 | the wrap's nonce: 24 random bytes |
| 40–87 | the file key sealed by the wrapping key with that nonce, bytes 0–15 as additional data: 32 bytes, then the 16-byte tag |
| 88– | the chunks |

Bytes 0–87 are the **header**. The archive is cut into chunks of 65,536
bytes, the last one shorter (an empty archive is one empty chunk). Chunk
*i*, from 0, is sealed by the file key with the 24-byte nonce made of 16
zero bytes, *i* on 7 bytes big-endian, and one byte, `01` for the last
chunk and `00` for the others, with the header as additional data; it is
written as its bytes, then its 16-byte tag. The encrypted backup is
88 + *n* + 16 × (number of chunks) bytes long for an archive of *n* bytes.
Test vectors: `vectors/encrypted-saves.json`.

- A reader MUST refuse a backup whose key id is not its key's, whose header
  or any chunk does not open, whose last chunk is not marked last, or that
  goes on after it, and restore nothing of it. [L-9.4-1] A chunk cut, moved,
  dropped or added thus never goes unnoticed.
- A client MUST NOT send the save key, a file key, the wrapping key or the
  recovery phrase to any server or peer: of the key, only its id leaves the
  device. [L-9.4-2]
- A client MUST make a new file key and a new wrap nonce, from a secure
  random source, for each backup. [L-9.4-3] One that resumes an upload
  (§ 9.3) keeps the header it made and encrypts again to the same bytes,
  without keeping the encrypted file.

**Sending it.** As any backup (§ 9.2, § 9.3), with its `encryption`,
`{"scheme": "lantern-save-e2e-1", "key_id": "0a1b2c3d4e5f6071"}`, in the
upload's document (§ 9.3), or in the header
`Lantern-Save-Encryption: lantern-save-e2e-1; key_id=0a1b2c3d4e5f6071` of a
request of § 9.2. `size`, `sha256`, `Content-Digest` and `Repr-Digest` are
those of the encrypted bytes, as the server keeps them.

- A server that offers this family MUST keep an encrypted backup's bytes as
  sent, list it with its `encryption`, and not require of it what it
  checks of an archive in clear, such as being a zip. [L-9.4-4] It MAY
  check that the bytes begin with `LTNE2E01` and the metadata's key id,
  and answer `400` otherwise.
- A server that does not offer it MUST answer `400` to a backup sent with
  an `encryption`, rather than keep it as an archive. [L-9.4-5]
- The title, `kind`, `slot`, `game_version_code`, `profile`, `note`,
  `device`, the times and the sizes stay in clear: the server needs them to
  list and keep backups. A client SHOULD leave `profile` and `note` out of
  an encrypted backup unless its user wants them shown. [L-9.4-6]

**Carrying the key.** The user moves the key from one device to another in
one of two forms of the same 35 bytes: the key's 32 bytes, then the first
3 bytes of SHA-256(`lantern-save-key` ‖ the key), written in the pairing
alphabet (§ 5.2), 5 bits a symbol, the most significant first: 56 symbols,
shown in 14 groups of 4.

- A **recovery phrase**, which the user writes down and types on the other
  device: `7KQ2-MZ4P-…`. Symbols rather than words: nothing to translate
  into the languages a console shows, no list of 2048 words to ship in a
  homebrew, the alphabet the user already types at pairing, without `0`,
  `O`, `1` or `I`, and a 24-bit check that catches a mistyped symbol. A
  reader ignores case, spaces and dashes.
- A **QR code**: `LANTERN-SAVE-KEY-1:` then the 56 symbols, which fit the
  QR code's alphanumeric mode, for a device with a camera to scan.

- A client MUST refuse a phrase or a QR code whose check does not match,
  and say so before anything else. [L-9.4-7]
- A client MUST show the phrase or the QR code only when its user asks, on
  its own screen. [L-9.4-8] It SHOULD ask the user to write the phrase down
  when it makes the key. [L-9.4-9] It keeps the key where its system
  protects keys, as a device key (§ 5.4).

**What is lost.** The server can no longer show what a backup holds, check
that it is a zip, nor keep one copy of two backups of the same save: the
same archive gives other bytes each time. Nobody can give a backup back to
a user who lost both their key and its phrase. The server still sees which
title, when, how large and from which device; it may delete a backup,
withhold one, or give an older one back: the key protects what a backup
holds, not whether it is there.

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

A user asks their server for a game it does not have; its admin adds it,
or declines, and says why.

- `GET <base>/v1/requests` → `{"schema":1, "requests":[{"id", "platform",
  "title_id", "name", "status", "created", "updated", "reason"}…]}`: the
  account's own, of the platform named (§ 4.3), newest first. `status`:
  `open`, `done` or `declined`; `updated`, when the status last changed;
  `reason`, on a declined request only, the admin's words for its
  requester (512 bytes at most).
- `POST <base>/v1/requests` `{"schema":1, "platform":"switch",
  "title_id":"…"}` → `201` with the new request (`{"schema":1, "id":…}`,
  as listed), or `200` with the open request for the same title.
  `platform` defaults to the client's (§ 4.3). A server MUST answer so.
  [L-11-1]
- `DELETE <base>/v1/requests/{id}`: the account withdraws its own request,
  whatever its status. A server MUST answer `204`, and `404` for another
  account's request or an unknown one. [L-11-2]
- Every device of the account reads the same requests; the event `request`
  (§ 18.2) tells them when one is made, changes status or is withdrawn.

**States.** A request goes only as this table says:

| From | To | How | Event `request` (§ 18.2) |
|---|---|---|---|
| (none) | `open` | The account asks for a title it has no open request for (`POST`). | `"status": "open"` |
| `open` | `done` | The title arrives in the library (the server sees it), or an admin says it is done. | `"status": "done"` |
| `open` | `declined` | An admin declines it, with a `reason` or without. | `"status": "declined"` |
| any | (none) | The account withdraws it (`DELETE`). | `"deleted": true` |

- `done` and `declined` are final: a server MUST NOT change a request's
  status but as the table says, and an account that asks again for the
  same title makes a new request. [L-11-3]
- With the scope `admin` (§ 5.7), `GET <base>/v1/admin/requests` lists
  every account's requests, newest first, each with its `user`, a page as
  in § 6.2, filtered by `status`, `user` and `platform`; `POST
  <base>/v1/admin/requests/{id}` decides an open one: `{"schema":1,
  "decision":"decline", "reason":"Only the games this household owns."}`
  (`reason` optional, with `decline` only) or `{"schema":1,
  "decision":"done"}`. A server MUST answer `200` with the request as it
  then is, `409` `conflict` when it is no longer open, `404` when it does
  not know it, and `400` to another decision or a `reason` with `done`.
  [L-11-4]
- A server MUST give a declined request's `reason` to its requester, in
  their listing, as the admin wrote it. [L-11-5] It is for people, in the
  admin's language: the server does not translate it.
- A server MUST send the event `request` at each change of the table, to
  the account's streams and to those of the scope `admin`. [L-11-6]

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
| 400 | `bad_request`, `key_required` | A malformed query or body, a parameter given twice, a body that is not I-JSON (§ 2.3, § 2.4); a cursor or `since` token the server never gave; a platform missing where one is needed; a pairing without a device key, on a server that issues only bound tokens (§ 5.4) |
| 401 | `unauthorized`, `signature_required`, `signature_invalid`, `signature_expired`, `signature_replayed` | No token where one is needed, or an unknown, revoked or expired one (with `WWW-Authenticate: Bearer`); a bound token without a signature (§ 5.4); a signature that does not verify or is not of the form § 5.4 gives; a signature's `created` outside the server's window; a signature's `nonce` seen before |
| 403 | `forbidden`, `account_frozen` | A scope missing; a frozen account; a peer's grant missing or not valid (§ 19.4); another device's `installed` (§ 20.4) |
| 404 | `not_found` | |
| 405 | `bad_request` | A method the route does not take (with `Allow`) |
| 409 | `conflict` | An upload's offset that is not the server's (with `Upload-Offset`); a cheat set or an account that exists already (§ 10, § 5.7); an account that cannot be deleted (§ 5.7); a sync write of another generation (§ 20.4); a decision on a request no longer open (§ 11) |
| 410 | `gone` | An expired cursor, `since` token, event id, sync revision, pairing, invitation or file id |
| 412 | `precondition_failed` | A sync write whose `If-Match` is not the collection's (§ 20.4) |
| 413 | `too_large` | A save or a chunk above the server's limit; a sync collection full (§ 20.5) |
| 416 | `bad_request` | A range outside the file (with `Content-Range: bytes */<size>`) |
| 422 | `unsupported_schema`, `digest_mismatch` | A request document of a schema the server cannot read; a body whose SHA-256 is not the one announced |
| 429 | `slow_down` | Too many requests, pairing attempts, polls, event streams or downloads from a peer (with `Retry-After`) |
| 500 | `internal` | A failure of the server itself; the client may try again later |
| 503 | `unavailable` | Scanning, maintenance (with `Retry-After`) |

- An unknown route MUST give `404` `not_found`. [L-12-3]
- The answer to a `HEAD` has no body, an error's included: its status and
  headers say it.
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
| A string field | 4 KiB (`name` and a request's `reason` 512 bytes, `note` 120 bytes, `profile` 64 bytes), in UTF-8; but a cheat set's `text` (§ 10), 1 MiB, the set's own limit |
| A listing's `q` | 256 bytes |
| A page | 1000 items |
| Titles read at once | 100 |
| A manifest | 4096 files, each path 1024 bytes |
| A homebrew's `packages` | 16 |
| `tags` of a title or a homebrew | 32, each 64 bytes |
| A port's `requires_data` | 256 files, each `accept` list 32 |
| A cheat set | 1 MiB |
| A discovery datagram | 1200 bytes |
| `Signature-Input`, `Signature` | 1 KiB each |
| An event's `data` (§ 18) | 4 KiB |
| A file's `mirrors` (§ 19.2) | 8 |
| A grant (§ 19.3) | 1 KiB |
| A sync write (§ 20.4) | 1000 items; a collection `limits.sync_items`, 100,000 at most |
| A chunk index (§ 22.1) | 8 MiB; 100,000 chunks, each 4 times its chunker's `size` at most (16 MiB) |

A server MUST refuse a request document beyond these limits, or beyond
its own lower ones, with `400` or `413`, never fail on it. [L-13-3]

## 14. Caching

Every `GET` returning JSON SHOULD carry an `ETag` and honour
`If-None-Match` with `304`. [L-14-1] A server that sends an `ETag` MUST
answer an `If-None-Match` that holds it (compared weakly, RFC 9110
§ 13.1.2), or `*`, with `304`, without a body, and with the `ETag`, `Vary`
and `Cache-Control` the `200` would carry; [L-14-3] and its `ETag` MUST
change when the document it would send that caller changes: another page,
another platform, language, encoding or rating cap. [L-14-4] A listing's
pages are documents like the others, each with its tag. Responses to authenticated calls
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
  pinned at pairing when no CA vouches for it (§ 5.3). Save backups may be
  encrypted on the device, by an open construction whose key the server
  never sees (§ 9.4).
- Nothing about what a console holds leaves it for sync without its
  user's consent, and the user deletes what the server keeps (§ 20).
- A file taken from a mirror or a peer is checked as one from the server;
  a peer serves only files, by their hash, to the holders of a grant
  (§ 19).
- Discovery is a hint, never a proof (§ 4.1).
- A server cannot change a client's settings or add headers to its later
  requests.
- A client checks a download's SHA-256 before installing it (§ 6.6), and a
  homebrew's signature when it has one (§ 8.4); one put together from
  chunks, each chunk and then the whole (§ 22).
- A browser client keeps its key where no script reads it, and a server
  takes no credential from a cookie (§ 2.5, Annex A.7).
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
- Forged signatures: a key or an R of small order, or a signature not
  encoded canonically, is refused before the verification equation, by
  every verifier, and a device key of small order at pairing (§ 8.4,
  § 5.4): with them, the equation alone takes a forgery for about one
  message in 8, for requests and homebrew alike.
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

**A hostile mirror or peer** (a mirror that serves other bytes, a console
on the LAN that lies, a peer that answers slowly or never).

- Protected: every file from a mirror or a peer is checked by its size and
  SHA-256 against the server's document before it is kept (§ 19.1); no
  token, signature or cookie goes to them (§ 19.1); a client stops at the
  size and falls back to its server.
- Not protected: on plain HTTP, whoever watches the network sees which
  file goes where; a peer or a mirror may refuse to serve, or serve slowly.

**Someone on the LAN, against a peer** (a guest's laptop, a smart TV).

- Protected: a peer serves nothing without a grant of a server it paired
  with, for that very file, valid a few minutes (§ 19.3, § 19.4); it
  serves only apps and homebrew packages it holds whole, by their hash,
  never a save, a key, a token or a path (§ 19.4); it is off unless its
  user turns it on, answers its own networks only, and limits its
  downloads and requests (§ 19.4).
- Not protected: a grant seen on a plain HTTP network may be replayed, for
  that same file, until it expires; a peer's discovery reply tells the
  network its name and the uids of its servers.

**A flood of event streams, or a curious stream** (§ 18).

- Protected: each token holds a few streams at most, beyond which a server
  answers `429` (§ 18.4); a stream carries only what its caller could read,
  by scope, account, platform and rating cap (§ 18.2); a revoked token's
  stream ends at its next heartbeat (§ 18.1); events name what changed,
  never the documents, which are read with the token's rights.
- Not protected: a stream tells its caller when something it may see
  changed, and so when the server's owner is at work on the library.

**A curious server, for what it keeps of the user** (§ 9.4, § 20).

- Protected: nothing of what a console holds leaves it for sync without
  its user's consent, given by name for `installed` (§ 20.1); the user
  deletes what the server keeps, at once, and a console asleep cannot put
  it back (§ 20.3, § 20.5); a backup encrypted on the device is bytes the
  server cannot read, by a key it never sees (§ 9.4).
- Not protected: the metadata of an encrypted backup (its title, times,
  sizes and device), and what a server keeps while sync is on; a server
  may delete a backup, withhold one or give back an older one; a user who
  loses both their save key and its phrase loses their encrypted backups.

**A static library** (§ 21): what a web host or a USB key holds.

- Protected: the same as against a malicious server: manifests, roots,
  hashes and authors' signatures are checked whatever the source (§ 8,
  § 6.6).
- Not protected: a static library is public to whoever reaches its files,
  has no token, no rating cap and no pairing; on a local storage nothing
  says who wrote it.

**A hostile chunk index or chunk source** (§ 22: a server or a static
library whose index lies, a mirror or a peer that serves other bytes for a
range, an index made to have a client write more than the file).

- Protected: the index is checked by the size and SHA-256 its app or
  package gives, and must name that very file (§ 22.3); each chunk is
  checked by its SHA-256 before it is kept, and the file put together by
  the document's `sha256` before anything of it is installed (§ 22.3,
  § 6.6); a chunk is named by its hash alone, so a chunk found elsewhere
  (in the seed of another game, say) is the same bytes, and the file's
  digest fixes their order and place: no chunk stands for another; the
  chunks add up to the file's size, each 16 MiB at most, 100,000 at most in
  an index of 8 MiB at most (§ 13), so a client never writes more than the
  file's size whatever an index says: nothing inflates as an archive does;
  a client can always read the whole file instead.
- Not protected: the ranges a client asks for tell its server, or a
  mirror, which chunks it lacks, and so roughly which version it had; a
  hostile source wastes a client's time and bandwidth until it falls back.

**A hostile web page** (a site the user opens in the browser where a
Lantern client runs, a page of another origin).

- Protected: a server answers the pages of the origins its owner allows
  alone (§ 2.5), and takes no credential from a cookie: a page of another
  origin borrows nothing of the user's; a browser client's key cannot be
  read out of its origin's storage, and its token is worth nothing without
  it (Annex A.7); a browser client reaches only the servers its browser
  trusts, and never asks its user to accept a certificate warning
  (Annex A.7).
- Not protected: a script that runs in a page of an allowed origin (a
  cross-site scripting flaw of the client) uses the key while it runs; a
  server that allows every origin lets any page its user opens read what
  it gives anonymously, from the user's own network (a library at home):
  `*` is for what is public anyway.

**A stolen admin token.**

- Protected: it is bound to its device's key like any (§ 5.4); a deletion
  asks for the account's name and refuses the caller's own (§ 5.7).
- Not protected: whoever holds an admin's device and key can delete other
  accounts and their data: the confirmation guards against a slip, not an
  attacker. Keep the scope `admin` to few devices.

Out of scope: rights to games. Lantern serves a user's own games and
enforces nothing (§ 15).

## 17. Conformance

A conformance suite (`conformance/`) runs against a server's URL, with a
token or without, and checks every requirement of this text it can see
from outside; each check names the ids it covers. The rules it cannot see
(a client's, or a server's inside) are listed by id on the site's
[traceability page](https://lantern.boreale.dev/requirements/). With a
token, it writes only what it then deletes: save backups, a cheat set, a
request, sync items, the devices it pairs and the invitations it makes,
and, with `--admin-writes`, an account of its own, which it then deletes
(§ 5.7). With `--static`, it checks a static library (§ 21) instead of a
server, at an address or in a folder; with `--peer`, a peer (§ 19.4), its
slots of downloads included; with `--fetch-mirrors`, the bytes of every
mirror the library names (§ 19.2), read without a token or any credential
of the server; with `--origin`, the answers to a page of that origin, its
preflights included (§ 2.5), of a server or of a static library over
HTTP. Its rate limits of pairing and invitations come last: they
leave the suite's address limited for a while. A
reference server (`server/`) serves a folder of packages and homebrew,
exports it as a static library, and passes the suite; `server/peer.py` is a
reference peer.

**Levels.** An implementation is conformant at a level:

| Level | What |
|---|---|
| `Lantern Core` | Transport, versions and the handshake (§ 2–4); tokens, pairing and signed requests when it issues tokens (§ 5.1–5.4); the library, what is missing, changes and sections when offered, and files (§ 6); errors, limits and caching (§ 12–14) |
| `+titles` | Titles (§ 7) |
| `+homebrew` | Homebrew, packages, manifests, signatures, ports and requirements (§ 8) |
| `+saves` | Save backups (§ 9) |
| `+cheats` | Cheats, and writing them when offered (§ 10) |
| `+requests` | Requests (§ 11) |
| `+admin` | Administration, invitations, rating caps, deleting accounts (§ 5.5–5.7), and deciding requests when requests are offered (§ 11) |
| `+events` | Events: the stream, long polling and their limits (§ 18) |
| `+peers` | Grants and mirrors (§ 19.2, § 19.3); with `--peer`, the peer's profile (§ 19.4) |
| `+sync` | Sync: collections, the merge rule, deletion (§ 20) |
| `+encrypted_saves` | End-to-end encrypted backups kept as sent (§ 9.4) |
| `+deltas` | Differential updates: chunk indexes, their route and the chunks they name (§ 22) |
| `Lantern Static` | A static library: its layout, documents and files (§ 21), without the routes a server has |

The suite prints the levels a server reaches: a level is reached when its
family is offered to the caller, none of its checks fails, and none was
left out for want of a token or a scope (run it with a token that holds
every scope, and anonymously on a public server). Every level of a server
needs `Lantern Core`; `Lantern Static` stands alone, for a static library
read with `--static`.

**The name.** Only an implementation that passes the suite at a level may
call itself "Lantern compatible" and show the badge, with that level and
the version of the text: "Lantern compatible 0.7 · Core +titles". The
badges and the registry of implementations are
[on the site](https://lantern.boreale.dev/conformance/); an implementation joins the
registry by a pull request with its report.

**Test vectors** (`vectors/`), for the libraries of clients and servers:
signed requests (§ 5.4), homebrew signatures (§ 8.4), SPKI fingerprints
(§ 5.3), paths (§ 8.2), `version_code` per profile (Annex A),
requirements (§ 8.7), rating caps (§ 5.6), encrypted backups and recovery
phrases (§ 9.4), grants (§ 19.3), sync's merge rule (§ 20.4), canonical
JSON (§ 2.3), the static layout (§ 21.1) and chunks and their indexes
(§ 22), each case with what a reader decides.

## 18. Events (feature `events`)

What changed, pushed by the server as it happens, so that a client in the
background (a console's homebrew while its user plays, a home automation
integration such as boreale-ha) learns it without reading the library
again and again. Two ways carry the same events: a stream (18.1), and long
polling (18.3) for a client that cannot keep a connection open. Annex B.10
says how a console and a home automation integration use them.

### 18.1 The stream

`GET <base>/v1/events`, with `Accept: text/event-stream`, answers `200`
with `Content-Type: text/event-stream` and `Cache-Control: no-store`, and
keeps the response open: Server-Sent Events, as the WHATWG HTML standard
defines them.

```text
retry: 5000

id: s_9f2c01aa_1042
event: ready
data: {"schema":1}

: heartbeat

id: s_9f2c01aa_1043
event: request
data: {"schema":1,"id":"r_7Qm2","platform":"switch","title_id":"0100ABCD00010000","status":"done"}
```

- Each event's `id` is a token of `GET <base>/v1/changes` (§ 6.4): the
  stream and `changes?since=` share their tokens. A server MUST give every
  event an `id` that `changes?since=` takes, and that resumes just after
  that event. [L-18.1-1]
- A stream MUST begin with a `retry` field, the milliseconds a client waits
  before it connects again, then an event `ready` whose `id` is the token
  it starts from: the one the client gave, or the current one. [L-18.1-2]
  A client that connected without a token learns from it where it stands.
- A client resumes with `Last-Event-ID: <token>`, or `?since=<token>` when
  it cannot set the header (the query wins). The server MUST then send,
  after `ready`, every event after that token that the caller may see, in
  order, then the new ones as they come. [L-18.1-3] It MUST send those
  events before the stream's first heartbeat, so that a client knows, at
  that heartbeat, that it has caught up. [L-18.1-10] A token too old for the
  server MUST give `410` `gone`, and one it never gave `400` (or `410`, as
  for `since`, § 6.4), before the stream begins. [L-18.1-4] The client then
  reads again what it shows (the library, its requests) and connects
  without a token.
- `data` is one line of JSON, a document with its `schema` (§ 3.2). A reader
  MUST ignore an event whose `event` it does not know, and one whose
  document is of a newer `schema`. [L-18.1-5]
- A server MUST write a comment line (`:` and anything) or an event at
  least every `limits.heartbeat` seconds, so that the client, and the
  proxies between them, see the stream alive. [L-18.1-6] A client that
  hears nothing for twice that long connects again.
- A server MUST NOT apply a `Content-Encoding` to a stream: each event goes
  out as soon as it is written. [L-18.1-7]
- The request is authenticated, and signed when its token is bound
  (§ 5.4), once, when the stream opens. A server MUST end the stream of a
  token revoked, or of an account frozen or deleted, at the latest at its
  next heartbeat (§ 5.7). [L-18.1-8] A server MAY end any stream when it
  wants, after an hour, say: the client connects again with the last `id`
  it read.
- A client MUST wait at least `retry` before it connects again, and back
  off as Annex B.2 says while connecting fails. [L-18.1-9]

### 18.2 Events

| `event` | Who gets it | `data` |
|---|---|---|
| `ready` | Every stream | `{"schema":1}`: the stream begins (18.1). |
| `library` | Scope `library` | `{"schema":1, "families":["apps","titles","homebrew","cheats"], "platforms":["switch"]}`: something of those families changed on those platforms. The client reads their changes (§ 6.4, § 7.3) or their listings again. |
| `request` | Scope `requests`: the account's own requests; scope `admin`: every account's, with its `user` | `{"schema":1, "id", "platform", "title_id", "status"}` (§ 11), at each change of § 11's table; `"deleted": true` instead of `status` when it was withdrawn. |
| `pairing` | Scope `admin` | A pairing waiting for approval, as § 5.7 lists it: `{"schema":1, "id", "code", "device", "key", "expires"}`. |
| `save` | Scope `saves`: the account's own backups | A backup kept: `{"schema":1, "platform", "title_id", "save_id", "created", "device"}` (§ 9). |
| `sync` | Scope `sync.read`: the account's own | `{"schema":1, "collection":"wishes", "rev":42}`: a collection changed (§ 20). |
| `shutdown` | Every stream | `{"schema":1, "retry":30}`: the server is stopping; the client connects again after `retry` seconds at least. |

- A server MUST send a caller only the events of what it could read with
  its token: of its scopes and its account, of its platform when it named
  one (`Lantern-Platform` or `?platform=`, § 4.3), and within its rating
  cap (§ 5.6). [L-18.2-1] A `library` event names only the families and
  platforms of which the caller sees a change; a change it cannot see gives
  it no event.
- A server SHOULD send `shutdown` to every stream before it stops on
  purpose. [L-18.2-2]
- An event says what changed, never the documents: the client reads them
  from their routes, under their own rules, and an event's `data` stays
  small (§ 13). A later version may add events.

### 18.3 Long polling

`GET <base>/v1/changes?since=<token>&wait=<seconds>`: the same events, for
a client that cannot keep a stream open (a console that sleeps, a proxy
that cuts long responses).

- With `wait`, a server MUST answer as soon as an event the caller may see
  comes after `since`, or once `wait` seconds have passed, the first of the
  two; a `wait` above `limits.wait` is lowered to it. [L-18.3-1]
- Its document MUST be that of § 6.4, with `events`: every event after `since`
  that the stream would send this caller, `{"id", "event", "data"}` each,
  in order (`ready` and `shutdown` excepted), `[]` when the wait ended with
  none; its `since` resumes after the last of them. [L-18.3-2]
- `wait` without `since`, or that is not an integer from 0, MUST give
  `400`. [L-18.3-3]
- The client asks again at once with the new `since`; it waits (Annex B.2)
  only after an error.

### 18.4 Limits

- A server that offers `events` MUST give, in its handshake's `limits`:
  `heartbeat`, the seconds between two heartbeats at most, 5 to 60;
  `event_streams`, how many streams a token may hold at once (an anonymous
  caller: an address), 1 at least; and `wait`, the longest wait of a long
  poll, 30 to 300 seconds. [L-18.4-1]
- Beyond `event_streams`, a server MUST answer `429` `slow_down`, with a
  `Retry-After` of `heartbeat` seconds at most: by then it has seen whether
  an older stream of the token still listens. [L-18.4-2]
- A client SHOULD hold one stream per server, and none while it has
  nothing to show of what events tell. [L-18.4-3]

## 19. Mirrors and peers (feature `peers`)

A file is its SHA-256 (§ 6.6, Annex B.5): whoever serves its bytes serves
the file, and a client checks them the same way wherever they come from.
A client may thus take a file of its library from somewhere nearer than its
server: a **mirror** the server names, or a **peer**, a paired console on
the same network that holds it already. Only files go that way, by their
hash: apps and homebrew packages, never a save backup, a document, or
anything named by a path.

### 19.1 What a client checks, whatever the source

- A client MUST check the size and SHA-256 of what a mirror or a peer
  served against its server's document (the app's, or the package's)
  before it keeps or installs any of it, treating mirrors and peers as
  untrusted: nothing they say (a size, a header, a redirect, a
  document) decides anything. [L-19.1-1]
- A client MUST NOT send a mirror or a peer its token, its signatures, a
  cookie or any credential of its server (§ 2); a peer gets a grant, and
  nothing else (§ 19.3). [L-19.1-2]
- A client SHOULD stop reading from a source once it gave more bytes than
  the size, and take the file from its server when what a source gave
  fails its check. [L-19.1-3]

### 19.2 Mirrors

An app (§ 6.1) or a homebrew package (§ 8.2) MAY carry `mirrors`, at most
8 other addresses of the same bytes: `[{"url":
"https://mirror.example.org/frostline.nsz"}]`.

- A mirror's `url` is absolute, `https`, or `http` for an address of a
  private network: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`,
  `fc00::/7` or `fe80::/10`, or of loopback, for testing (§ 2). A client
  MUST NOT read a mirror over plain HTTP at another address. [L-19.2-1]
- A server MUST name as a mirror only an address that serves the file's
  exact bytes, and put none of its tokens in it. [L-19.2-2]
- A client reads a mirror as a file (§ 6.6), with `Range` to resume. A
  mirror is a hint: a client may pass it by, and takes the file from its
  server when the mirror fails.

### 19.3 Grants

A peer serves a file only to a client its server allows to read it. The
server says so with a **grant**: a short statement, signed by a key of the
server's own, that a peer checks without asking anyone.

`GET <base>/v1/grants/sha256/{hex}`, with the scope `library` →

```json
{"schema": 1, "sha256": "3a7bd3e2…", "size": 734003200,
 "grant": "eyJleHAiOjE3OTMzNDYwMDAsInB1cnBvc2UiOi…Iq9k",
 "expires": "2026-10-30T09:40:00Z"}
```

- The server MUST answer `200` with a grant only for a file it would serve
  the caller (of its scopes and platform, within its rating cap: § 5.6),
  and `404` otherwise, as for a file it does not have. [L-19.3-1]
- A grant is `<payload>.<signature>`, each in base64url without padding.
  The payload is the UTF-8 bytes of the JSON object
  `{"exp":<Unix seconds>,"purpose":"lantern-grant-1","sha256":"<hex>","size":<bytes>,"uid":"<server's uid>"}`,
  with these keys in this order and no space, `uid` that of the server's
  handshake (§ 4.2); the signature is the Ed25519 signature (RFC 8032) of
  those bytes by the server's grant key, whose public key the handshake
  gives in `peers.key`. Test vectors: `vectors/grants.json`.
- A grant's `exp` MUST be at most `peers.grant_lifetime` seconds ahead,
  and `peers.grant_lifetime` at most 900. [L-19.3-2] A grant names one
  file of one server: whoever holds it may read that file from a peer, as
  its holder could from its server.
- The grant key MUST serve grants alone and stay on the server, its public
  key, `peers.key`, the same for every caller. [L-19.3-3] A server
  changes it only when it leaks: a peer then refuses its grants until it
  reads the handshake again.

### 19.4 Peers

A paired console MAY serve the files of its server that it holds to the
other devices of its network: it is then a **peer**. It is off until its
user turns it on.

A peer has one route, under a base path of its own (the `base` of its
discovery reply): `GET <peer base>/v1/blobs/sha256/{hex}`, with
`Lantern-Grant: <grant>` → the file whose SHA-256 is `<hex>`, served as
§ 6.6 says: `Range`, a strong `ETag`, `Repr-Digest`, `Content-Length`,
`Accept-Ranges`; `HEAD` alike.

A peer MUST:

- serve a file only with a grant that verifies with the `peers.key` of the
  server whose `uid` it names, a server it paired with and whose handshake
  it read over the pinned connection (§ 5.3), whose `exp` is not past by its
  clock and whose `sha256` is the path's, and answer `403` `forbidden`
  otherwise; [L-19.4-1]
- serve only files it holds whole, whose size and SHA-256 it checked against
  its server's document, and only apps and homebrew packages: never a save
  backup, a key, a token, a document or anything named by a path; a file it
  does not hold gives `404` `not_found`; [L-19.4-2]
- serve only while its user allows it, and only to addresses of its own
  networks; [L-19.4-3]
- serve at most `slots` downloads at once (its discovery reply, 1 to 8),
  and a few requests a second per address, answering `429` `slow_down`
  with `Retry-After` beyond; [L-19.4-4]
- answer errors as § 12 says, as `application/problem+json`, without
  `WWW-Authenticate`: a peer takes no token. [L-19.4-5]

A peer speaks plain HTTP on a private network (§ 19.2's addresses), or
HTTPS with a certificate of its own that nobody pins: what it serves is
checked by its hash, and nothing secret goes to it but a grant, worth one
file for a few minutes. A client MUST NOT send a grant over plain HTTP to
an address outside a private network. [L-19.4-6]

### 19.5 Finding peers

- A client that looks for peers adds `"peers": true` to its discovery
  datagram (§ 4.1). A peer answers only such a datagram, unicast, with
  `{"schema":1, "lantern":"peer", "uid":"<the peer's own uid>",
  "name":"Lea's Switch", "port":47116, "base":"/lantern", "tls":false,
  "slots":2, "servers":["6f1c2a8e-…"]}`: `servers` are the uids of the
  servers whose grants it takes, and `tls` whether it speaks HTTPS. Its
  reply MUST be of this form, within § 4.1's limits, and only from a
  peer that is on. [L-19.5-1] A client older than this version ignores a
  reply whose `lantern` is not `server`.
- A peer MAY also advertise itself with DNS-SD as `_lantern-peer._tcp`,
  with the TXT keys `servers=<uid>,…`, `path=<base>`, `v=1` and `tls=0` or
  `1`.
- A client asks the peers whose `servers` hold its server's `uid`; it MAY
  ask a peer `HEAD` first, to see whether it holds the file. A reply is a
  hint, as discovery is (§ 4.1).
- A client SHOULD look for peers at most once a minute, and read a file
  from at most 2 peers at once. [L-19.5-2]

## 20. Sync (feature `sync`)

A user's wishes, and what each of their consoles has installed, kept by
their server so that every console of theirs sees them, with the scopes
`sync.read` and `sync.write`. Requests (§ 11) are the account's already:
every device of the account reads the same ones, and the event `request`
(§ 18.2) tells them of a change.

### 20.1 Consent

- A client MUST ask its user before it turns sync on, saying which
  collections it sends and to which server, and reads or writes nothing of
  `<base>/v1/sync` before they agree. [L-20.1-1] The answer is kept per
  console profile and per server: a console of several users asks each
  one, and syncs each profile with the account its user chose (a profile
  that wants sync of its own pairs with its own account, § 5.2).
- What a console has installed MUST NOT leave it without a consent given
  for it by name: agreeing to sync wishes does not cover it. [L-20.1-2]
- A client MUST let its user turn sync off; it then stops sending at once,
  and offers to delete what the server keeps (20.5). [L-20.1-3]

### 20.2 Collections

| Collection | An item per | `key` | `value` |
|---|---|---|---|
| `wishes` | Game wished for | `<platform>/<title_id>` | `{"platform", "title_id", "name"?, "note"?}` |
| `installed` | Device of the account | The device's id, `d_…` (§ 5.7), which `GET <base>/v1/sync` gives the device | `{"device":"Lea's Switch", "platform":"switch", "apps":[{"app_id", "version_code"}…], "homebrew":[{"id", "build"}…]}` |

An item is `{"key", "value", "updated", "rev"}`, or a deletion, `{"key",
"deleted": true, "updated", "rev"}`:

- `updated`: when the item last changed, in UTC, to the millisecond
  (`2026-10-30T09:12:03.250Z`), as the device that changed it saw it,
  corrected by its offset to the server's `Date` (Annex B.9);
- `rev`: the collection's revision when the server took the change, an
  integer that grows with each change of the collection.

A later version may add collections: a reader skips one it does not know.

### 20.3 Reading

`GET <base>/v1/sync` (scope `sync.read`) → `{"schema":1,
"generation":"g_4Rz1", "device":"d_3f9a1c07b2e455d0",
"collections":{"wishes":{"rev":42, "items":12}, "installed":{"rev":7,
"items":2}}}`: what the account keeps; `device`, the caller's own key in
`installed`.

`GET <base>/v1/sync/{collection}?since=<rev>&page_size=&cursor=` →
`{"schema":1, "collection":"wishes", "generation":"g_4Rz1", "rev":42,
"items":[Item…], "next":null}`, a page as in § 6.2: with `since`, the items
changed after that revision, deletions included; without it, every item
but deletions. `rev` is the collection's when its first page was read.

- A server MUST give, after `since`, every item whose `rev` is above it,
  deletions included, or answer `410` `gone` when it no longer keeps the
  deletions that far back; the client then reads the collection whole.
  [L-20.3-1]
- `generation` changes only when the account's sync data is deleted
  (20.5). A client that reads another `generation` than the one it kept
  MUST NOT write its own items back: it drops its copy of the sync state,
  turns sync off and asks its user again (20.1). [L-20.3-2] So a console
  asleep while its user deleted their data cannot bring it back.

### 20.4 Writing and conflicts

`PATCH <base>/v1/sync/{collection}` (scope `sync.write`), `{"schema":1,
"generation":"g_4Rz1", "items":[{"key", "value", "updated"} or {"key",
"deleted": true, "updated"}…]}` → `200` `{"schema":1, "collection",
"generation", "rev", "items":[…]}`: each item sent, as the server keeps it
then, with its `rev`.

The merge rule, item by item, the same on every server:

1. Of the item the server has and the one sent, the server keeps the one
   of the later `updated`.
2. On the same `updated`, a deletion wins; between two values, the one
   whose canonical JSON (§ 2.3) is the greater string of bytes; when they
   are the same, the server keeps the one it has.
3. An item it keeps takes the collection's next `rev`; an item it does not
   keep is answered as the server has it.

So two consoles that change two items never lose each other's change, and
two that change the same item end with the same result, whatever the order
in which their changes arrive. Test vectors: `vectors/sync-merge.json`.

- A server MUST merge by these rules, item by item, and answer each item
  sent as it then keeps it. [L-20.4-1]
- A server MUST take an `updated` more than `auth.skew` seconds ahead of its
  clock as its own time: a console whose clock runs ahead cannot win every
  conflict to come. [L-20.4-2]
- `If-Match: "<generation>-<rev>"`, the collection's as a read gave them,
  makes a write all or nothing: when the collection changed since, a
  server MUST change nothing and answer `412` `precondition_failed`.
  [L-20.4-3] A client sends it when it wrote its
  items from the whole collection, and lets the rule merge otherwise.
- A server MUST refuse a write of another `generation` than its own with
  `409` `conflict`: the data was deleted since. [L-20.4-4]
- In `installed`, a device MUST be able to write its own item only: a server
  answers `403` `forbidden` to a write of another key. [L-20.4-5]
- A server MUST answer `400` to an item whose `key` or `value` is not of its
  collection's form (a `wishes` key is a platform and a title id of § 4.3 and
  § 6.1), or whose `updated` is not such a time. [L-20.4-6]

### 20.5 Deletion and retention

- `DELETE <base>/v1/sync/{collection}`, and `DELETE <base>/v1/sync` for
  every collection (scope `sync.write`) → `204`. A server MUST erase those
  items, deletions included, at once, and give the account a new
  `generation`. [L-20.5-1] Its other devices learn it at their next read
  (20.3), and from the event `sync`.
- A server MUST keep a deletion at least 30 days, so that a device that
  syncs once a month learns of it. [L-20.5-2]
- A server MUST erase the sync data of an account it deletes (§ 5.7).
  [L-20.5-3]
- A server SHOULD give `limits.sync_items`, how many items a collection
  holds at most, and answer `413` `too_large` to a write beyond. [L-20.5-4]

## 21. Static libraries

A library served as files, which change only when they are written again:
on a web host such as GitHub Pages, a NAS's web server, or a USB key or an
SD card read with no server at all. A static library is read only, and
public to whoever reaches its files.

### 21.1 Layout

A static library is a folder, its **root**: an address
(`https://lea.example.org/library/`) or a folder on a storage the device
reads. Each read route is a file below it:

| Route | File |
|---|---|
| The handshake (§ 4.2) | `lantern.json` |
| `GET <base>/v1/apps?platform=<p>` | `v1/apps/<p>/pages/<n>.json`: page *n*, from 1 |
| `GET <base>/v1/titles/{title_id}` | `v1/titles/<p>/<title_id>.json` |
| Every title of a platform | `v1/titles/<p>/pages/<n>.json`: § 7.2's document, with `next` |
| `GET <base>/v1/homebrew?platform=<p>` | `v1/homebrew/<p>/pages/<n>.json` |
| `GET <base>/v1/homebrew/{id}` | `v1/homebrew/<p>/<id>.json` |
| `GET <base>/v1/cheats?platform=<p>&title_id=<t>` | `v1/cheats/<p>/<t>.json` |
| `GET <base>/v1/cheats/{id}` | `v1/cheats/<id>.txt` |
| A file (§ 6.6) | `v1/blobs/sha256/<hex>`: the file whose SHA-256 is `<hex>` |
| A file's chunk index (§ 22.1) | `v1/chunks/sha256/<hex>.json`: the index of the file whose SHA-256 is `<hex>` |

`<p>` is a platform of the handshake's `platforms`. A title without cheat
sets has no file of them. Test vectors: `vectors/static-layout.json`.

- A listing is sorted as a server sorts it (by name: § 6.2, § 8.5) and cut
  into pages of `static.page_size` items: the cursor of page *n* + 1 is
  `"<n+1>"`, and `next` is `null` on the last page. A platform with nothing
  of a family has an empty first page. The same library gives the same
  pages.
- A static library MUST hold these files only where the table puts them,
  each valid against its schema as a server's document is (§ 3.2), its
  pages chained as above, and every file its documents point at, of their
  size and SHA-256. [L-21.1-1]
- Every `file` of a document, every `url` of an image that is not
  `external`, and every `url` of `chunks` (§ 22.1), MUST be a path
  relative to the root, such as
  `v1/blobs/sha256/3a7b…`: without a scheme, a leading `/`, a `..` part, a
  `\`, or a query. [L-21.1-2]
- Its texts are in one language, the handshake's `language` (§ 2.2).

### 21.2 Its handshake

`lantern.json` is a handshake (§ 4.2) with `static`: `{"generated":
"2026-10-30T18:00:00Z", "page_size": 100}`, when its files were written and
the size of its pages. Its `base` is `.`: the root.

- A static library's handshake MUST say `account` `{"state":"anonymous",
  "scopes":["library","cheats"]}` (without `cheats` when it has none), and
  give 0 in `features` to every family a static library cannot offer:
  `changes`, `sections`, `saves`, `encrypted_saves`, `requests`,
  `pairing`, `signatures`, `admin`, `events`, `peers` and `sync`.
  [L-21.2-1]
- `cheats`, when above 0, is read only (§ 10). `deltas` may be above 0: a
  static library holds the chunk indexes of its files (§ 22). `limits`
  gives `page_size` alone.

### 21.3 Reading one

- A client MUST read a static library's files as JSON whatever their
  `Content-Type` (a USB key has none, and a web host may say another), and
  checks every file it takes by its size and SHA-256 (§ 6.6), as from a
  server. [L-21.3-1] A web host may compress what it serves: the client
  checks the bytes once decoded.
- What a static library cannot answer, a client computes from its pages:
  what is missing, by § 6.3's rules over the whole listing of its platform;
  filters and search (§ 6.2, § 8.5); the updates of homebrew (§ 8.5), by
  comparing `build`. A client MUST compute what is missing by § 6.3's rules,
  as a server would. [L-21.3-2]
- A static library has no pairing, no token and no rating cap: whoever
  reads its files reads all of them, and one at a public address is public.
  It has no changes and no events: a client reads `lantern.json` again,
  and its pages again when `static.generated` changed (their `ETag`, where
  HTTP gives one, spares those that did not).
- Over HTTP, § 2 holds: HTTPS but on loopback. A static library's files
  are not a server's routes (§ 2.4): a client may follow a web host's
  redirect between them over HTTPS, as it sends them no credential. On a local storage, nothing
  says who wrote the files but the user who plugged it in; the checks of
  § 6.6 and § 8 hold as for any server.
- A client given an address MUST look for a library there in this order:
  first the origin's `/.well-known/lantern`, where a server's handshake
  (one without `static`) is the server of that origin (§ 4.2); then
  `<address>/lantern.json`, where a handshake with `static` is a static
  library whose root is the address. It passes over an error, a document
  it cannot read (not JSON, or of a newer `schema`, § 3.2) and a document
  of the other kind: a handshake with `static` at `/.well-known/lantern`
  never makes the origin's root a static library. A folder on a storage
  has no origin: its `lantern.json` alone. [L-21.3-3]
- Over HTTP, a static library's files SHOULD carry
  `Access-Control-Allow-Origin: *`, so that a page of any origin reads
  them (GitHub Pages sends it). [L-21.3-4] A browser reads them with
  requests that need no preflight (Annex A.7), which a web host does not
  answer.

## 22. Differential updates (feature `deltas`)

A newer version of a package holds much of the version a device has. With
this family, a client takes those bytes from what it holds and downloads
only the rest. A file is cut into **chunks** by a rule that depends on its
bytes alone (§ 22.2), so that two versions of a file share the chunks that
did not change, and its **index** lists them, each by its size and SHA-256
(§ 22.1). Nothing is computed per request: the index is a document written
once, which a static library holds as a file; a chunk is a range of the
file (§ 6.6), which its server, a mirror or a peer serves as it serves the
file (§ 19). Each chunk is checked by its SHA-256, and the file put
together by its app's or package's `sha256`, before anything of it is
installed; a client that cannot use an index reads the whole file, as
without this family. Save backups are not concerned.

### 22.1 Chunk indexes

An app (§ 6.1) and a homebrew package (§ 8.2) MAY carry `chunks`, where
the index of its file is:

```json
"chunks": {"url": "<base>/v1/chunks/sha256/3a7bd3e2…", "size": 1033, "sha256": "5f0e9c1d…"}
```

`url` is the index's address (in a static library, its path, § 21.1);
`size` and `sha256` are those of the index's bytes. The index, in
canonical JSON (§ 2.3):

```json
{"chunker":{"alg":"lantern-cdc-1","size":65536},"chunks":[[48083,"ece35ba2…"],[39083,"775fb5ff…"],[136252,"c236d967…"]],"schema":1,"sha256":"3a7bd3e2…","size":223418}
```

- `sha256` and `size`: those of the whole file, as its app or package
  gives them.
- `chunker`: how the file was cut: `alg`, `lantern-cdc-1` (§ 22.2), and its
  `size`, a power of two from 65,536 (64 KiB) to 4,194,304 (4 MiB). A later
  version may add chunkers.
- `chunks`: each chunk of the file, in its order, as `[size, sha256]`: its
  size in bytes and the SHA-256 of its bytes, lower-case hex. A chunk's
  offset is the sizes before it added up; the sizes add up to the file's.
  An empty file has none.

A server that gives `chunks` MUST serve at its `url` an index of that
file, of this form and within § 13's limits, cut by its `chunker` exactly
as § 22.2 says and written in canonical JSON (§ 2.3): its bytes are those
whose `size` and SHA-256 `chunks` gives. [L-22.1-1] A file thus has the
same index wherever it is cut with the same `size`. Test vectors:
`vectors/chunks.json`.

`GET <base>/v1/chunks/sha256/{hex}`, with the scope `library`, → the index
of the file whose SHA-256 is `{hex}`. A server MUST answer it for every
file it gives `chunks` for that the caller may read (of its scopes and
platform, within its rating cap: § 5.6), and `404` otherwise, as for a
file it does not have. [L-22.1-2] A client that holds a file may thus ask
for its index by its SHA-256 alone.

A server MAY leave `chunks` out of a file (a small one gains nothing).
`features.deltas` is the `schema` of the indexes it writes (§ 4.2).

### 22.2 The chunker, `lantern-cdc-1`

A content-defined chunker, of the gear hash's kind (as FastCDC), with one
parameter, its `size` S = 2^b, b from 16 to 22:

- a chunk is at least `min` = S / 4 bytes and at most `max` = 4 × S, but
  the file's last, which may be shorter; the mask M is the 64-bit integer
  whose top b bits are set, (2^b − 1) × 2^(64 − b);
- the gear table G gives, for each byte value i from 0 to 255, the first 8
  bytes, read as a big-endian integer, of the SHA-256 of the 13 ASCII
  bytes `lantern-cdc-1` followed by the byte i;
- the first chunk begins at the file's start, each next one where the last
  ended. When `min` bytes or fewer are left, they are the last chunk.
  Otherwise h is 0, and for each byte B from the chunk's start + `min` on,
  h becomes (2 × h + G[B]) modulo 2^64; the chunk ends just after the
  first byte after which h AND M is 0, or after its `max`-th byte, or at
  the file's end, the first of the three.

A chunk's end depends on its start and the bytes after it alone: a change
in a file moves the ends near it, and further on the chunks end where they
ended in the older version. Its first `min` bytes are not hashed, which
keeps chunks from being tiny and the chunker quick.

### 22.3 Updating with an index

A client that holds bytes of an older version (the package it downloaded
and kept, the files an archive installed, a file of another version: its
**seeds**) puts a newer file together:

1. It reads the index at `chunks.url`, and checks it.
2. It cuts each seed with the index's `chunker` (§ 22.2), and takes from it
   each chunk of the index it finds there, of the same size and SHA-256.
3. It reads the other chunks as ranges of the file (§ 6.6), from its
   server, a mirror or a peer (§ 19), joining neighbours into one range as
   it likes.
4. It checks the file put together, then installs it as any download.

- Before it uses an index, a client MUST check that its bytes are of the
  size and SHA-256 that `chunks` gives; read it as absent when its
  `schema` is above the one it knows (§ 3.2) or its chunker is one it does
  not know; and refuse it when its `sha256` or `size` is not its file's, or
  its chunks are of another form than § 22.1's: each of 1 byte to the
  chunker's `max`, its SHA-256 in lower case, 100,000 at most, their sizes
  adding up to the file's. [L-22.3-1]
- A client MUST check each chunk's SHA-256, wherever it comes from, before
  it keeps it, and the whole file's size and SHA-256 against its app's or
  package's before it installs anything of it (§ 6.6), and refuse what does
  not match. [L-22.3-2]
- A client MUST NOT write more than the file's size, nor read more of a
  source than the range it asked for. [L-22.3-3]
- A client SHOULD read the whole file (§ 6.6) when it cannot use an index,
  or when a chunk or a source fails, as it would without this family.
  [L-22.3-4]

A mirror or a peer is read for a range as for a file: without a
credential of the server, a peer with a grant (§ 19). A partial file keeps
the chunks it checked: a client resumes with them after a lost connection
or a sleep (Annex B.4).

What a change costs: the chunks it touches, about 1.25 × S each. A
package that its format compresses whole, as one stream, differs
everywhere from one version to the next, and gains nothing; one that
compresses by blocks or by file, as `nsz` and `zip` do, keeps the parts
that did not change the same bytes, which its chunks find.

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
the platform**: what is marked "(to check)" is not settled. The
browser's, `web`, gives it nothing to install (Annex A.7). The other
platforms are open: no profile yet (Annex A.8).

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

### A.7 Web (`web`)

A client in a web browser: a page, or an app installed from one, that
reads a library in the browser. It installs nothing: what it downloads, it
hands to its user, to copy to a console's card, say. Its rules follow from
what a browser allows and forbids; a server's side of them is § 2.5.

- **Ids, types, formats, cheats, saves, homebrew**: none in this version.
  A server MUST NOT list an app, a title, a homebrew, a cheat set or a save
  of platform `web`, nor `web` among its handshake's `platforms`: a
  browser has nothing to install. [L-A.7-1] A browser client shows the
  library of another platform, which it names with `?platform=`.
- **Headers.** The browser writes `User-Agent` itself (§ 2, `L-2-5`), and
  `Lantern-Platform` would need a preflight before every read (§ 2.5): a
  browser client names the platform it shows with `?platform=` instead
  (§ 4.3, `L-4.3-5`).
- **Transport.** A browser client MUST be served over HTTPS (or plain HTTP
  from loopback, for testing), and read servers, mirrors and peers over
  HTTPS only, but a server on loopback. [L-A.7-2] A page over HTTPS cannot
  read plain HTTP (mixed content): a mirror or a peer over plain HTTP
  (§ 19) is passed by, and the file taken from the server.
- **No pinning.** A page cannot see the key of the server it reaches, so
  it can neither pin it (§ 5.3) nor show its fingerprint at pairing. A
  browser client MUST reach only a server whose certificate its browser
  accepts by its CA store, never asking its user to accept a certificate
  the browser warns about. [L-A.7-3] A server at home is then
  read by a browser with a certificate of a public CA, for a domain of its
  owner's, or of a CA its user installed on that device; one with a
  self-signed certificate is not for browser clients.
- **Device keys.** A browser client MUST pair with a device key (§ 5.4),
  made by WebCrypto (Ed25519) as not extractable, and keep it, and its
  token, in its own origin's IndexedDB alone: never in a cookie,
  `localStorage`, a URL, or anywhere a script reads a key's bytes.
  [L-A.7-4] It sends its token in `Authorization` alone, signed (§ 5.4).
- **Events.** `EventSource` sends no `Authorization`: a browser client
  reads the stream (§ 18.1) with `fetch`, or polls long (§ 18.3).
- **Static libraries.** A web host such as GitHub Pages answers no
  preflight. A browser client MUST read a static library with requests a
  browser sends without one: `GET` or `HEAD`, with no header but those the
  browser sets itself, `Accept`, `Accept-Language` and a single `Range`.
  [L-A.7-5] The host sends `Access-Control-Allow-Origin: *` (§ 21.3).
- **Downloads.** A browser client MUST check what it downloads (its size
  and SHA-256, § 6.6; each chunk, § 22.3) before it hands it to its user,
  and hand over nothing that fails. [L-A.7-6]

### A.8 Open platforms

Open: no profile yet. `ios`, `windows` and `macos`, and Atlas's store names
(`steam`, `gog`, `xbox`), have none; § 4.3 says what a server and a client
do on them.

## Annex B — Client guidelines

Not normative: advice from what consoles and phones meet in use. A client
that follows it is kinder to its users and to the servers it reads.

### B.1 Timeouts

- Connect: 10 seconds, 3 on the LAN; the TLS handshake within the same
  time.
- A JSON request: 30 seconds without a byte, 60 in all.
- A file: no limit in all, but 60 seconds without a byte, then resume
  (B.4).
- Polling a pairing: as `interval` says, until `expires`; after a `429`,
  wait as long as its `Retry-After` says, then `interval` again (§ 5.2).

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
- A file put together from chunks (§ 22.3) resumes by the chunks already
  checked: keep, beside the partial file, which of the index's chunks it
  holds.

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

### B.10 Events in the background

- **A console's homebrew.** While its user plays, a homebrew in the
  background keeps one stream (§ 18.1) to its server, and shows a small
  notice when a request it made is done or a backup arrived from another
  console. When the console sleeps the stream dies: on waking, the
  homebrew asks `changes?since=<the last id>&wait=0` once, which gives
  what happened while it slept, then opens its stream again with
  `Last-Event-ID`. A homebrew that cannot keep a socket in the background
  long-polls with a `wait` of a minute or so instead.
- **A home automation integration** (boreale-ha, for Home Assistant). It
  pairs as a device, by a QR code shown in its configuration, with the
  scopes of what it shows: `library` for a sensor of new games, `requests`
  for the state of a household's requests, `admin` to raise a notification
  when a console waits for approval (the event `pairing`, with its code
  and its fingerprint, which the admin compares before approving). It
  keeps one stream, turns each event into an event of its own, marks the
  server unavailable on `shutdown` and comes back after its `retry`.
- Both keep the last `id` they read, so that nothing is missed across a
  restart, and read the library again only after a `410`.

### B.11 Sharing on the LAN

- Turn sharing on only when the user asks, say what it does ("other
  consoles of this network may download the games this console holds,
  once your server allows them"), and show how many downloads it served.
- Before reading a file from a peer, ask the server for a grant; ask
  peers `HEAD` first, take the file from one, keep reading the file from
  the server when the peer is slower or fails, and check it whole before
  keeping it.
- A save backup never goes through a peer, encrypted or not.

### B.12 Sync and save keys

- Ask for consent once per profile, in plain words: "Keep your wishes on
  Living room shelf, so that your other consoles see them?" and,
  separately, "Also share what this console has installed?".
- Read `GET <base>/v1/sync/{collection}?since=` at start and on each event
  `sync`; write each change as it happens, with its `updated`.
- When a console makes a save key, show its phrase once, ask the user to
  write it down, and offer to show it again later; never put it in a
  screenshot the system takes by itself, where the system lets a homebrew
  say so.

### B.13 Differential updates

- Keep the package of each app and homebrew installed, where the device
  has room, or the last one downloaded: it is the seed of the next update
  (§ 22.3). A console that shares files on the LAN (§ 19.4) holds them
  anyway.
- Cut a seed once per chunker `size` and keep its chunks' list, by the
  seed's SHA-256, rather than cut it again at each update.
- Ask for the chunks to read in a few ranges: join neighbours, and those a
  few kilobytes apart, which costs less than another request.
- Show what an update downloads, and what it saves ("12 MB of 1.4 GB"),
  and check free space against the file's `size`: the file is put
  together beside the old one before it replaces it.

### B.14 Browser clients

- Keep the key and the token in IndexedDB, under the server's `uid`; a
  user who clears the site's data pairs again.
- Read the event stream with `fetch` and a stream reader, or long-poll:
  `EventSource` cannot carry `Authorization` nor a signature.
- Hand a download to the user only once checked (Annex A.7): hash it as it
  arrives (WebCrypto has no streaming SHA-256: a small library does it),
  then offer it to save.
- A page served by the server itself (its own origin) needs no CORS at
  all; one served elsewhere needs the server's owner to allow its origin
  (§ 2.5): say so, with that origin, when a preflight fails.

## Annex C — The road to 1.0

Not normative: what this text needs before its version 1.0, when `/v1/`
and `schema` 1 stop changing shape, and where each criterion stands at this
draft, 0.7.

| | Criterion | Where it stands at 0.7 |
|---|---|---|
| 1 | **Two independent servers and two independent clients** reach `Lantern Core` with the conformance suite, each written from this text by people who did not write the other ones, and each pair of them works together: pairing, listing, downloading, what is missing. | Open. One server passes the suite, the reference server of this repository; the libraries of lantern-sdk are written by this text's authors and do not count. The registry on the site lists who passes. |
| 2 | **A core with no open question**: every section from § 2 to § 14, and § 17, without a part marked "to check", and no issue labelled as a question on them left open. | Met. 0.6 settled what the core left open, and 0.7 what browsers ask of it (§ 2.5) and the canonical form of numbers (§ 2.3); their Changes list each point. None of those sections is marked "to check", and the list below holds no question on them. It stays met while no issue labelled as a question on them is open. |
| 3 | **Profiles reviewed for two platforms at least**, by people who know them and are not this text's authors: the Switch's and one other, their ids, formats, paths and roots tried on real devices. | Open. The Switch's profile is complete, not yet reviewed from outside; the drafts (A.2 to A.6) keep their "(to check)". |
| 4 | **An outside review** of what holds keys: signed requests (§ 5.4), encrypted backups (§ 9.4), grants and peers (§ 19), by someone who did not write them. | Open. |
| 5 | **A released, attested text**: each version a release of its files, with their sums and a build provenance attestation (§ 3.6). | Met from 0.6: the release workflow is in place; its tags, `spec-v0.6` and `spec-v0.7`, are the maintainer's to make. |

Then, at 1.0:

- The families beyond the core (§ 7 to § 11, § 18 to § 22) may stay at
  `schema` 1 and still grow after 1.0, by additions only (§ 3.5).
- The drafts' rule (§ 3.5) ends: a change of shape raises a document's
  `schema`, and the older one stays served while clients read it.

**Open questions.** What is still to decide, which the 1.0 gate reads:
criterion 2 holds while the first list is empty.

- On the core (§ 2 to § 14, § 17): none.
- Elsewhere: every "(to check)" of the drafts' profiles (Annex A.2 to
  A.6), which only someone who knows the platform can settle.

Browser clients (§ 2.5, Annex A.7) and updates by their differences (§ 22),
on the list until 0.6, are settled by 0.7.

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
  - A security fix to Ed25519 verification (§ 8.4, § 5.4): a verifier
    refuses a key or an R of small order and encodings that are not
    canonical, before the equation, which alone accepted a forgery (a key
    and an R of small order, S = 0) for about one message in 8; a server
    refuses a device key of small order at pairing. The reference server and
    the suite's reference client did accept such forgeries until 0.4;
    `vectors/ed25519-refused.json` holds the cases.
  - A server refuses a document beyond the limits without failing (§ 13).
  - A threat model (§ 16); conformance levels, the name and the badge
    (§ 17); test vectors (`vectors/`); client guidelines (Annex B).
- 0.5 (2026-10-30): what happens while nobody asks, files shared on the
  LAN, sync, encrypted backups and static libraries; still `/v1/` and
  `schema` 1, as a draft. Every 0.4 route and field stays, with the
  additions below; four optional families are new, each declared in
  `features`: `events`, `peers`, `sync` and `encrypted_saves`.
  - Events (§ 18): Server-Sent Events at `<base>/v1/events`, whose ids are
    `changes` tokens, so that `Last-Event-ID` resumes where
    `changes?since=` would; events `library`, `request`, `pairing`, `save`,
    `sync` and `shutdown`, each only to the callers that could read what it
    is about; heartbeats, `retry`, a limit of streams per token; long
    polling with `changes?wait=`, whose document gains `events`. The
    handshake's `limits` add `heartbeat`, `event_streams` and `wait`.
  - Mirrors and peers (§ 19): `mirrors` on apps and packages; grants,
    signed by a key of the server's own (`peers` in the handshake), with
    which a paired console shares the files it holds, by their SHA-256, at
    `/v1/blobs/sha256/{hex}`; peers found by discovery (`"peers": true`, a
    reply `lantern` `peer`) or DNS-SD. A client checks what a mirror or a
    peer gives as what its server gives; plain HTTP is allowed for them on
    a private network only (§ 2).
  - Sync (§ 20): wishes and what each console has installed, kept per
    account with the scopes `sync.read` and `sync.write`, only with the
    user's consent; an item merge rule by time, with `If-Match` for a write
    all or nothing (new code `412` `precondition_failed`), and deletion,
    which a console asleep cannot undo (`generation`).
  - Encrypted backups (§ 9.4): `lantern-save-e2e-1`, XChaCha20-Poly1305 in
    chunks of 64 KiB with a file key wrapped by a key derived from the
    user's save key (HKDF-SHA-256); the key carried as a recovery phrase in
    the pairing alphabet, or a QR code; `encryption` on a backup.
  - Static libraries (§ 21): the read routes as files (handshake,
    pages of fixed cursors, titles, homebrew, cheats, files by their
    SHA-256), a handshake with `static`, and what a client computes
    itself; the reference server exports one, and the suite checks one
    (`--static`).
  - Deleting an account (§ 5.7): `DELETE <base>/v1/admin/users/{name}`,
    confirmed by the name, which revokes its devices and erases its data;
    the suite now deletes the account it makes.
  - Discovery (§ 4.1): the reference server advertises itself with DNS-SD,
    with the standard library alone.
  - The schemas check the ids of every profile, the draft ones included,
    in every document that carries them, and a cheat set's `build_id` per
    profile.
  - A threat model for each addition (§ 16), conformance levels `+events`,
    `+peers`, `+sync`, `+encrypted_saves` and `Lantern Static` (§ 17),
    client guidelines B.10 to B.12, and the road to 1.0 (Annex C).
- 0.6 (2026-10-30): the draft that readies the text for 1.0; still `/v1/`
  and `schema` 1, as a draft. Every 0.5 route and field stays, with the
  additions below; four points narrow what a document or a request may be,
  each marked **(narrower)**: no server or client of this text wrote them,
  and the schemas, which keep `schema` 1 (§ 3.5), now refuse them.
  - A core with no open question (Annex C, criterion 2). What § 2 to § 14
    and § 17 left open is settled:
    - JSON is I-JSON (§ 2.3, `L-2.3-1`): no member name twice, no unpaired
      surrogate, no byte order mark; integers between −(2^53 − 1) and
      2^53 − 1, so `size` is no longer "a 64-bit integer" **(narrower)**; a
      request document that is not I-JSON gives `400`.
    - Times are RFC 3339 in UTC with `Z`, no offset **(narrower)**, a
      fraction of 1 to 9 digits read by every reader; dates `YYYY-MM-DD`
      (§ 2.3, `L-2.3-2`, `L-2.3-3`).
    - Hex digests are lower-case everywhere, and a path's SHA-256 of
      another form gives `404` (§ 2.3, `L-2.3-4`).
    - Names are compared and searched by Unicode's canonical caseless
      match, written in NFC; ids, codes and listed values exactly
      (§ 2.3, `L-2.3-5`, `L-2.3-6`): `q` "searches names" (§ 6.2), which
      said neither how nor in what, keeps the apps whose `name` holds it,
      and a manifest's paths "the same when case is ignored" (§ 8.2) are
      compared that way.
    - Nothing is an empty page (`items` `[]`, `next` `null`), never an
      error; an empty file has its SHA-256 and gives `416` to any range
      (§ 2.3, `L-2.3-7`).
    - Routes and queries (§ 2.4): paths exactly as written, a trailing `/`
      another path, no redirect from a server and none followed by a
      client (`L-2.4-1`, `L-2.4-2`); a parameter given twice gives `400`
      **(narrower)** (`L-2.4-3`); an empty value is absent, so that the
      templates this text writes (`?platform=&type=`) work as they are
      (`L-2.4-4`); a parameter a route does not know is ignored
      (`L-2.4-5`); `HEAD` on every `GET` route but a pairing's poll and
      the event stream (`L-2.4-6`); a request document sent as anything but
      `application/json` gives `400` (`L-2.4-7`).
    - Listings (§ 6.2): the order of `name`, `added` and `release` (the
      title's release, newest first, those without one last), ties by `id`
      as bytes; `q` of 256 bytes at most; a `page_size` that is not a
      positive integer gives `400` (`L-6.2-6`); `total` optional, exact when
      given; `limits.page_size` 1 to 1000 (§ 4.2).
    - What is missing (§ 6.3, `L-6.3-2`): `installed` may be empty, `want`
      is one or more of `base`, `update` and `dlc`, anything else `400`
      **(narrower)**; an unknown `app_id` is ignored, one listed twice
      counts by its highest version.
    - Changes (§ 6.4): an app whose file changed is removed, then added
      under its new id.
    - Files (§ 6.6): `If-Range` honoured (`L-6.6-6`), as Annex B.4 relied
      on; several ranges may get the whole file, never
      `multipart/byteranges` (`L-6.6-7`).
    - Titles at once (§ 7.2): an id asked twice is answered once; no id
      gives `400`. Saves (§ 9.1): newest first per title, the order of the
      titles the server's; a backup without `kind` is read as `other`.
    - Platforms (§ 4.3): an id known on several platforms gives `400`
      without a platform, now with its id (`L-4.3-8`); a client's
      `Lantern-Platform` is the SHOULD of § 2 (`L-2-7`), as § 4.3 now says.
    - Pairing and invitations: a code typed is read ignoring case, spaces
      and dashes, on the server's page and in an invitation (`L-5.2-14`,
      `L-5.5-4`); `interval` is 1 to 60 seconds. Discovery: "a few times a
      second" is 10 replies a second to an address at most (`L-4.1-3`).
    - Caching (§ 14): a server that sends an `ETag` answers
      `If-None-Match` with it, weakly compared, or `*`, by `304` with the
      same `ETag`, `Vary` and `Cache-Control` (`L-14-3`), and its tag
      changes with the document a caller would get (`L-14-4`).
    - Errors (§ 12): a parameter twice, a body not I-JSON; the answer to a
      `HEAD` has no body.
    - The schemas' `$id` are their stable addresses,
      `https://lantern.boreale.dev/schemas/v1/<name>.json` (§ 3.2), and
      the times, dates, integers and pairing `interval` above are checked
      by them.
  - Requests (§ 11): their states and transitions as a table, `done` and
    `declined` final (`L-11-3`); an admin declines a request, with a
    `reason` its requester reads, or marks it done, at
    `POST <base>/v1/admin/requests/{id}`, and lists every account's at
    `GET <base>/v1/admin/requests` (`L-11-4`, `L-11-5`); a request gains
    `updated` and `reason`; the event `request` at each transition, to the
    account and to the scope `admin`, with the request's `user` (`L-11-6`,
    § 18.2).
  - Events (§ 18.1): the events after a resumed token come before the
    stream's first heartbeat, which tells a client it caught up
    (`L-18.1-10`).
  - Mirrors (§ 19.2): plain HTTP on loopback too, for testing, as § 2
    allows.
  - Releases (§ 3.6): each version of the text released by a tag
    `spec-v<version>`, its files, a zip, their SHA-256 sums and build
    provenance attestations, checked with `gh attestation verify`.
  - Editorial, no change to any schema: Atlas's data a client may read
    (§ 6.1) no longer names prices; Lantern carries no notion of price or
    promotion.
  - Conformance (§ 17): the suite reads every mirror with
    `--fetch-mirrors`, fills a peer's slots of downloads, and checks what
    0.6 settles; the road to 1.0 says where each criterion stands, and
    lists the questions still open (Annex C).
- 0.7 (2026-10-30): differential updates, browser clients, and what the
  suite still could not check; still `/v1/` and `schema` 1, as a draft.
  Every 0.6 route and field stays, with the additions below; one optional
  family is new, declared in `features`: `deltas`. Four points narrow what
  a server or a document may be, each marked **(narrower)**, as 0.6 did;
  one widens what a client may do, marked **(wider)**.
  - Differential updates (§ 22, feature `deltas`): a file cut into chunks
    by `lantern-cdc-1`, a content-defined chunker spelled out to the byte
    (a gear table of SHA-256, a mask, a least and a largest chunk), so that
    two versions share the chunks that did not change; an index per file,
    in canonical JSON, each chunk by its size and SHA-256, named by
    `chunks` on an app or a package (its `url`, `size` and SHA-256) and
    served at `<base>/v1/chunks/sha256/{hex}`, or as a file of a static
    library (§ 21.1); a client takes the chunks it holds from its seeds and
    reads the others as ranges of the file, from its server, a mirror or a
    peer, checks each chunk, then the whole file, before installing it, and
    reads the whole file when anything fails (`L-22.1-1`, `L-22.1-2`,
    `L-22.3-1` to `L-22.3-4`). No patch format and no work per request:
    the index is written once, a chunk is a range. Limits (§ 13): an index
    of 8 MiB, 100,000 chunks, 16 MiB a chunk. A threat model for it
    (§ 16), the level `+deltas` (§ 17), vectors (`vectors/chunks.json`)
    and client guidelines (Annex B.13).
  - Browsers (§ 2.5): the CORS answers a server gives the origins its
    owner allows, errors and preflights included, the request headers it
    names and the response headers it exposes (`L-2.5-1` to `L-2.5-5`); no
    credential in a cookie, never `Access-Control-Allow-Credentials`. The
    `web` profile (Annex A.7): a browser client installs nothing and is
    served over HTTPS, reaches only servers its browser trusts, since it
    cannot pin a key, keeps a non-extractable WebCrypto key in IndexedDB,
    reads a static library with simple requests, and checks what it hands
    its user (`L-A.7-2` to `L-A.7-6`). A server serves nothing of platform
    `web` and does not list it **(narrower)** (`L-A.7-1`): until 0.6, `web`
    was an open platform, of which a server could serve apps. A browser
    client is not held to `User-Agent`, which its browser writes, nor to
    `Lantern-Platform` (`L-2-5`, `L-2-7`) **(wider)**. Open platforms
    become Annex A.8. Client guidelines B.14. Annex C's two open questions
    beyond the profiles are settled.
  - Canonical JSON (§ 2.3): RFC 8785's, numbers as ECMAScript writes them,
    members sorted by UTF-16 code units, where sync's merge rule said
    "keys sorted" without saying how, and nothing of numbers **(narrower)**;
    on the same `updated` and the same canonical JSON, the server keeps its
    own item (§ 20.4). Vectors: `vectors/canonical-json.json`, and numbers
    in `vectors/sync-merge.json`.
  - Pairing (§ 5.2): a server counts `interval` from the last poll it
    answered, never from one it refused with `429`, and its `Retry-After`
    is the time left, so that a client polling a little fast is not shut
    out for good **(narrower)** (`L-5.2-15`).
  - Static libraries (§ 21.3): a client looks for a server's handshake at
    the origin's `/.well-known/lantern` first, then for `lantern.json` at
    the address, passing over what it cannot read, and never takes a
    static handshake at `/.well-known/lantern` for a library's root
    (`L-21.3-3`); over HTTP, files carry `Access-Control-Allow-Origin: *`
    (`L-21.3-4`); the chunk indexes of the files (§ 21.1).
  - Resumable uploads (§ 9.3): `HEAD` on an upload also gives
    `Lantern-Chunk-Size`, its `chunk_size`, so that a client resuming
    after a restart, which kept only the upload's address, sends chunks
    the server takes **(narrower)** (`L-9.3-3`).
  - Limits (§ 13): a cheat set's `text`, written through § 10, is the one
    string beyond 4 KiB: 1 MiB, the set's own limit, as § 10 said.
  - Conformance (§ 17): `--origin` checks a server's or a static library's
    answers to a page of that origin; the suite asks for `zstd` only when
    its Python reads it, and checks the reference server's images on its
    own origin (§ 7.1).
