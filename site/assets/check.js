// Checks a document against the schemas the site publishes (schemas/v1/), in the browser: nothing leaves it.
// The validator reads the subset of JSON Schema 2020-12 that Lantern's schemas use (the keywords below),
// each $ref resolved from the schemas' own $id; tests/test_check.py runs it, under Node, against every
// example of examples/v1/ and every refused one (examples/v1/invalid/), so that it agrees with the Python
// jsonschema that tools/check_schemas.py uses. The page's texts are its catalog's (data-* attributes).
'use strict';

(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.LanternCheck = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  const BASE = 'https://lantern.boreale.dev/schemas/v1/';
  const UUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/;
  const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
  const DATETIME = /^(\d{4})-(\d{2})-(\d{2})[Tt]([01]\d|2[0-3]):([0-5]\d):([0-5]\d|60)(\.\d+)?([Zz]|[+-]([01]\d|2[0-3]):[0-5]\d)$/;

  const kind = (v) => v === null ? 'null' : Array.isArray(v) ? 'array' : typeof v === 'object' ? 'object' : typeof v;
  const isType = (v, t) => {
    switch (t) {
      case 'integer': return typeof v === 'number' && Number.isInteger(v);
      case 'number': return typeof v === 'number' && Number.isFinite(v);
      default: return kind(v) === t;
    }
  };
  const same = (a, b) => {
    if (kind(a) !== kind(b)) return false;
    if (kind(a) === 'array') return a.length === b.length && a.every((x, i) => same(x, b[i]));
    if (kind(a) === 'object') {
      const ka = Object.keys(a), kb = Object.keys(b);
      return ka.length === kb.length && ka.every((k) => k in b && same(a[k], b[k]));
    }
    return a === b;
  };
  const validDate = (m) => {
    const y = +m[1], mo = +m[2], d = +m[3];
    return mo >= 1 && mo <= 12 && d >= 1 && d <= new Date(Date.UTC(y, mo, 0)).getUTCDate();
  };
  const formats = {
    uuid: (s) => UUID.test(s),
    date: (s) => { const m = DATE.exec(s); return !!m && validDate(m); },
    'date-time': (s) => { const m = DATETIME.exec(s); return !!m && validDate(m); },
  };
  const pointer = (doc, fragment) => {
    let node = doc;
    for (const raw of fragment.split('/').slice(1)) {
      const key = decodeURIComponent(raw).replace(/~1/g, '/').replace(/~0/g, '~');
      if (node === null || typeof node !== 'object' || !(key in node)) return undefined;
      node = node[key];
    }
    return node;
  };
  const codePoints = (s) => { let n = 0; for (const _ of s) n++; return n; };   // eslint-disable-line no-unused-vars

  // `schemas`: {file name without .json: parsed schema}; the $id of each is BASE + name + '.json'.
  function validator(schemas) {
    const byId = {};
    for (const s of Object.values(schemas)) byId[s.$id] = s;
    const resolve = (ref, base) => {
      const url = new URL(ref, base);
      const fragment = decodeURIComponent(url.hash.slice(1));
      url.hash = '';
      const doc = byId[url.href];
      if (!doc) throw new Error('unknown schema ' + url.href);
      const target = fragment ? pointer(doc, fragment) : doc;
      if (target === undefined) throw new Error('unknown part ' + ref);
      return [target, doc.$id];
    };

    function check(schema, value, path, base, out) {
      if (schema === true) return;
      if (schema === false) { out.push([path, 'nothing is allowed here']); return; }
      const fail = (message) => out.push([path, message]);
      const valid = (sub, v = value) => { const tmp = []; check(sub, v, path, base, tmp); return tmp.length === 0; };

      if (schema.$ref) {
        const [target, where] = resolve(schema.$ref, base);
        check(target, value, path, where, out);
      }
      if ('type' in schema) {
        const types = Array.isArray(schema.type) ? schema.type : [schema.type];
        if (!types.some((t) => isType(value, t))) { fail('expected ' + types.join(' or ') + ', found ' + kind(value)); return; }
      }
      if ('const' in schema && !same(schema.const, value)) fail('must be ' + JSON.stringify(schema.const));
      if (schema.enum && !schema.enum.some((e) => same(e, value))) fail('must be one of ' + schema.enum.map((e) => JSON.stringify(e)).join(', '));

      if (typeof value === 'number') {
        if ('minimum' in schema && value < schema.minimum) fail('at least ' + schema.minimum);
        if ('maximum' in schema && value > schema.maximum) fail('at most ' + schema.maximum);
        if ('exclusiveMinimum' in schema && value <= schema.exclusiveMinimum) fail('more than ' + schema.exclusiveMinimum);
        if ('exclusiveMaximum' in schema && value >= schema.exclusiveMaximum) fail('less than ' + schema.exclusiveMaximum);
      }
      if (typeof value === 'string') {
        const length = codePoints(value);
        if ('minLength' in schema && length < schema.minLength) fail('at least ' + schema.minLength + ' characters');
        if ('maxLength' in schema && length > schema.maxLength) fail('at most ' + schema.maxLength + ' characters');
        if (schema.pattern && !new RegExp(schema.pattern, 'u').test(value)) fail('does not match ' + schema.pattern);
        if (schema.format && formats[schema.format] && !formats[schema.format](value)) fail('not a ' + schema.format);
      }
      if (Array.isArray(value)) {
        if ('minItems' in schema && value.length < schema.minItems) fail('at least ' + schema.minItems + ' items');
        if ('maxItems' in schema && value.length > schema.maxItems) fail('at most ' + schema.maxItems + ' items');
        if (schema.uniqueItems && value.some((a, i) => value.some((b, j) => j > i && same(a, b)))) fail('items must be different');
        const prefix = schema.prefixItems || [];
        value.forEach((item, i) => {
          const sub = i < prefix.length ? prefix[i] : schema.items;
          if (sub !== undefined) check(sub, item, path + '[' + i + ']', base, out);
        });
      }
      if (kind(value) === 'object') {
        for (const key of schema.required || []) if (!(key in value)) fail('"' + key + '" is required');
        const props = schema.properties || {};
        for (const [key, item] of Object.entries(value)) {
          const at = path + '.' + key;
          if (key in props) check(props[key], item, at, base, out);
          else if (schema.additionalProperties === false) out.push([at, 'not allowed here']);
          else if (typeof schema.additionalProperties === 'object') check(schema.additionalProperties, item, at, base, out);
          if (schema.propertyNames && !valid(schema.propertyNames, key)) out.push([at, 'this name is not allowed']);
        }
      }
      for (const sub of schema.allOf || []) check(sub, value, path, base, out);
      if (schema.anyOf && !schema.anyOf.some((s) => valid(s))) fail('matches none of the alternatives');
      if (schema.oneOf) {
        const n = schema.oneOf.filter((s) => valid(s)).length;
        if (n !== 1) fail(n === 0 ? 'matches none of the alternatives' : 'matches several alternatives');
      }
      if (schema.not && valid(schema.not)) fail('is not allowed');
      if (schema.if) {
        if (valid(schema.if)) { if (schema.then) check(schema.then, value, path, base, out); }
        else if (schema.else) check(schema.else, value, path, base, out);
      }
    }

    return {
      /** The problems of `value` against the schema `name` ([[path, message]…], empty when it matches). */
      validate(name, value) {
        const out = [];
        check(schemas[name], value, '$', schemas[name].$id, out);
        return out;
      },
    };
  }

  // The names of the schemas a schema refers to ("common" for "common.json#/$defs/name").
  const referred = (node, found = new Set()) => {
    if (Array.isArray(node)) node.forEach((n) => referred(n, found));
    else if (node && typeof node === 'object') {
      for (const [k, v] of Object.entries(node)) {
        if (k === '$ref' && typeof v === 'string') {
          const m = /^([A-Za-z0-9-]+)\.json/.exec(v.replace(BASE, ''));
          if (m) found.add(m[1]);
        } else referred(v, found);
      }
    }
    return found;
  };

  return { validator, referred, BASE };
});

// ---- The page (site/check.html): a document, the kind it claims to be, and what is wrong with it.
(function () {
  if (typeof document === 'undefined') return;
  const form = document.getElementById('check-form');
  if (!form) return;
  const T = form.dataset;
  const doc = document.getElementById('check-doc');
  const kindSelect = document.getElementById('check-kind');
  const result = document.getElementById('check-result');
  const root = document.body.dataset.root || '';
  const fill = (text, values) => text.replace(/\{(\w+)\}/g, (_, k) => values[k]);
  const cache = {};

  async function load(name) {
    if (cache[name]) return;
    const response = await fetch(root + 'schemas/v1/' + name + '.json', { credentials: 'omit' });
    if (!response.ok) throw new Error(name + ': ' + response.status);
    cache[name] = await response.json();
    await Promise.all([...window.LanternCheck.referred(cache[name])].map(load));
  }
  const say = (cls, ...nodes) => {
    result.className = 'check-result ' + cls;
    result.replaceChildren(...nodes);
  };
  const text = (tag, s, cls) => { const e = document.createElement(tag); e.textContent = s; if (cls) e.className = cls; return e; };

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    let value;
    try { value = JSON.parse(doc.value); } catch (e) { say('bad', text('p', fill(T.notJson, { error: e.message }))); return; }
    const name = kindSelect.value;
    try {
      await load(name);
      const problems = window.LanternCheck.validator(cache).validate(name, value);
      const newer = value && typeof value === 'object' && typeof value.schema === 'number' && value.schema > 1;
      const nodes = [];
      if (newer) nodes.push(text('p', T.newer, 'note'));
      if (!problems.length) {
        say('ok', text('p', fill(T.ok, { name })), ...nodes);
      } else {
        const list = document.createElement('ul');
        for (const [path, message] of problems.slice(0, 50)) {
          const li = document.createElement('li');
          li.append(text('code', path), ' ', message);
          list.append(li);
        }
        say('bad', text('p', fill(T.bad, { n: problems.length })), list, ...nodes);
      }
    } catch (e) { say('bad', text('p', fill(T.failed, { error: e.message }))); }
  });

  const sample = document.getElementById('check-sample');
  if (sample) {
    sample.hidden = false;
    sample.addEventListener('click', async () => {
      try {
        const response = await fetch(root + 'demo/lantern.json', { credentials: 'omit' });
        doc.value = JSON.stringify(await response.json(), null, 2);
        kindSelect.value = 'handshake';
        result.replaceChildren();
        result.className = 'check-result';
      } catch (e) { say('bad', text('p', fill(T.failed, { error: e.message }))); }
    });
  }
  form.hidden = false;
})();
