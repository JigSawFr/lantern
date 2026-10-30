# Contributing

Lantern is an open protocol: its text, its schemas, its conformance suite
and its reference server live here, and every change to the protocol
starts here. Client and server libraries live in
[lantern-sdk](https://github.com/JigSawFr/lantern-sdk).

## Questions and problems

Open an issue. A question about the text is as useful as a bug report: if
SPEC.md can be read two ways, it is a bug of SPEC.md.

A security flaw is not an issue: see [SECURITY.md](SECURITY.md).

## Proposing a change to the protocol

Open an issue with the **Proposal** template before any pull request. It
asks for:

- the problem, seen by a client or a server, with a real case;
- the change: routes, fields, codes, and the sections of SPEC.md it
  touches;
- its effect on `schema` (§ 3): an addition keeps a document's `schema`, a
  change of meaning raises it, and the older schema stays served while
  clients read it;
- how the conformance suite will check it, and what a client or server
  that ignores it does.

Once the proposal is agreed, the pull request changes SPEC.md, the schemas
and examples, `openapi.yaml`, the suite and the reference server together,
so that the suite never lags behind the text.

## Pull requests

- Titles and commits in [Conventional Commits](https://www.conventionalcommits.org/),
  with a scope: `docs(spec): …`, `feat(schemas): …`, `fix(server): …`.
- Fill in the pull request template; say the change's protocol impact.
- Run the checks before pushing:

  ```sh
  pip install -r tools/requirements.txt
  python3 tools/check_schemas.py
  python3 -m unittest discover -s tests
  python3 tools/build_site.py build && python3 tools/check_site.py build
  reuse lint
  ```

- Examples and tests use made-up games and names, and only reserved
  addresses (`example.org`, `192.0.2.0/24`): never a real person, game,
  server or e-mail address.
- Every file says its licence ([REUSE](https://reuse.software/)): the text
  of SPEC.md is CC BY 4.0, everything else MIT.

Pull requests are merged as one squashed commit.

## Code of conduct

Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).
