#!/usr/bin/env python3
"""Checks Lantern's JSON Schemas (schemas/v1/) against their examples.

Every schema must be a valid 2020-12 schema; every examples/v1/<name>.json
must match schemas/v1/<name>.json; every examples/v1/invalid/<name>.<why>.json
must not, so that the schemas keep refusing what SPEC.md forbids. Every
schema's $id is its stable address, https://lantern.boreale.dev/schemas/v1/
and its file's name (SPEC.md § 3.2). The schemas refer to each other by
their $id, resolved from the files here, offline.

Usage: tools/check_schemas.py [repo-root]   (needs jsonschema and referencing)
"""
import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

root = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
schemas = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((root / "schemas/v1").glob("*.json"))}
registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas.values())
errors = []


def validator(name):
    return Draft202012Validator(schemas[name], registry=registry, format_checker=FormatChecker())


ID_BASE = "https://lantern.boreale.dev/schemas/v1/"    # the schemas' stable addresses (SPEC.md § 3.2)
for name, schema in schemas.items():
    if schema.get("$id") != f"{ID_BASE}{name}.json":
        errors.append(f"schemas/v1/{name}.json: $id {schema.get('$id')!r}, not {ID_BASE}{name}.json")
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as e:  # noqa: BLE001 - reported, not raised
        errors.append(f"schemas/v1/{name}.json: not a valid schema: {e}")

examples = root / "examples/v1"
for path in sorted(examples.glob("*.json")):
    if path.stem not in schemas:
        errors.append(f"{path.relative_to(root)}: no schema of that name")
        continue
    for e in validator(path.stem).iter_errors(json.loads(path.read_text(encoding="utf-8"))):
        errors.append(f"{path.relative_to(root)}: {e.json_path}: {e.message}")
for name in schemas:
    if name != "common" and not (examples / f"{name}.json").exists():
        errors.append(f"schemas/v1/{name}.json: no example in examples/v1/")
for path in sorted((examples / "invalid").glob("*.json")):
    name = path.name.split(".")[0]
    if name not in schemas:
        errors.append(f"{path.relative_to(root)}: no schema of that name")
    elif validator(name).is_valid(json.loads(path.read_text(encoding="utf-8"))):
        errors.append(f"{path.relative_to(root)}: accepted, but should be refused")

for e in errors:
    print(e)
print(f"check_schemas: {len(schemas)} schemas, {len(list(examples.glob('*.json')))} examples, "
      f"{len(list((examples / 'invalid').glob('*.json')))} refused ones, {len(errors)} problem(s)")
sys.exit(1 if errors else 0)
