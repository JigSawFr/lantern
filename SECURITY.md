# Security

Lantern is a protocol that moves files onto consoles, so a flaw in it, in
its reference server or in its conformance suite matters. Thank you for
reporting one.

## Reporting a flaw

Report it privately, through GitHub's private vulnerability reporting:
the **Security** tab of this repository, then **Report a vulnerability**.
Please don't open a public issue or pull request for it.

Say what you found, how to reproduce it (a request, a document, a server
or client behaviour), and what an attacker gains. A flaw in the text of
SPEC.md is as welcome as a flaw in the code.

## What happens next

- The report is acknowledged, then confirmed or answered with why it is
  not a flaw.
- A confirmed flaw is fixed in the specification (a new draft, or a
  `schema` change when a document's meaning changes), in the reference
  server and in the suite, so that the suite catches it in every other
  implementation.
- The advisory is published once the fix is out, crediting you if you wish.

## Scope

This repository: SPEC.md, `schemas/`, `openapi.yaml`, `conformance/` and
`server/`. The reference server is a reference, not a product: run it to
test, not to serve a library on the Internet. A flaw in the client and
server libraries belongs to
[lantern-sdk](https://github.com/JigSawFr/lantern-sdk/security).
