// Runs site/assets/check.js (the page's validator) over every example of examples/v1/ and every refused one
// (examples/v1/invalid/): prints {"valid": [files it refuses], "invalid": [files it accepts]}, both lists empty
// when it agrees with tools/check_schemas.py. Run by tests/test_check.py.
'use strict';
const fs = require('fs');
const path = require('path');
const root = path.resolve(__dirname, '..');
const { validator } = require(path.join(root, 'site/assets/check.js'));
const schemas = {};
for (const f of fs.readdirSync(path.join(root, 'schemas/v1'))) {
  if (f.endsWith('.json')) schemas[f.slice(0, -5)] = JSON.parse(fs.readFileSync(path.join(root, 'schemas/v1', f), 'utf8'));
}
const v = validator(schemas);
const out = { valid: [], invalid: [], checked: 0 };
for (const f of fs.readdirSync(path.join(root, 'examples/v1')).sort()) {
  if (!f.endsWith('.json')) continue;
  out.checked++;
  const problems = v.validate(f.slice(0, -5), JSON.parse(fs.readFileSync(path.join(root, 'examples/v1', f), 'utf8')));
  if (problems.length) out.valid.push(f + ': ' + problems.slice(0, 2).map((p) => p.join(' ')).join('; '));
}
for (const f of fs.readdirSync(path.join(root, 'examples/v1/invalid')).sort()) {
  if (!f.endsWith('.json')) continue;
  out.checked++;
  const problems = v.validate(f.split('.')[0], JSON.parse(fs.readFileSync(path.join(root, 'examples/v1/invalid', f), 'utf8')));
  if (!problems.length) out.invalid.push(f);
}
console.log(JSON.stringify(out));
