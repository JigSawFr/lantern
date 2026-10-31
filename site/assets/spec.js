// The specification's page (site/README.md): its contents (folded on a phone, the section being read
// lit beside the text), the search over spec/search.json, and the button that copies a requirement's link.
// Every text it says is the page's catalog's (data-* attributes of .spec-layout and .spec-search). Without
// script the contents are open, every id is a link, and the search field stays hidden.
'use strict';

(function () {
  const layout = document.querySelector('.spec-layout');
  if (!layout) return;
  const side = layout.querySelector('.spec-side');
  const live = document.getElementById('spec-live');
  const article = layout.querySelector('article');
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const wide = matchMedia('(min-width: 1024px)');
  const fill = (text, values) => (text || '').replace(/\{(\w+)\}/g, (_, k) => values[k]);

  // ---- The contents: one sticky bar on a phone, a column beside the text on a large screen.
  const box = layout.querySelector('.toc-box');
  const summary = box && box.querySelector('summary');
  const now = box && box.querySelector('.toc-now');
  const list = box && box.querySelector('.toc-list');
  const toc = box && box.closest('.toc');
  const links = new Map();
  if (box) {
    for (const a of box.querySelectorAll('a[href^="#"]')) links.set(a.getAttribute('href').slice(1), a);
    const place = () => {
      if (wide.matches) { box.open = true; summary.tabIndex = -1; }
      else { summary.removeAttribute('tabindex'); }
    };
    // folded when the page opens on a phone; beside the text, always open
    box.open = wide.matches;
    place();
    wide.addEventListener('change', () => { if (!wide.matches) box.open = false; place(); });
    box.addEventListener('toggle', () => { if (wide.matches && !box.open) box.open = true; else if (box.open) reveal(); });
    // a section chosen in the list folds it; so do Esc and a touch outside
    list.addEventListener('click', (e) => { if (!wide.matches && e.target.closest('a')) box.open = false; });
    box.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !wide.matches && box.open) { box.open = false; summary.focus(); }
    });
    document.addEventListener('pointerdown', (e) => {
      if (!wide.matches && box.open && !toc.contains(e.target)) box.open = false;
    });
  }

  // The scroller of the contents: the list on a phone, the whole column beside the text.
  function reveal() {
    const current = box && box.querySelector('a[aria-current]');
    if (!current) return;
    const scroller = getComputedStyle(list).overflowY === 'visible' ? toc : list;
    const a = current.getBoundingClientRect();
    const b = scroller.getBoundingClientRect();
    if (!b.height) return;
    if (a.top < b.top + 40 || a.bottom > b.bottom - 16) {
      scroller.scrollTo({ top: scroller.scrollTop + (a.top - b.top) - b.height / 2 + a.height / 2, behavior: reduce.matches ? 'auto' : 'smooth' });
    }
  }

  // ---- The section being read: the last heading above the top third of the screen. The observer wakes
  // the check when a heading crosses that band; a jump to an anchor, or the address, wakes it too.
  const headings = [...article.querySelectorAll('h2[id], h3[id]')].filter((h) => links.has(h.id));
  let active = null;
  function update() {
    const line = innerHeight * 0.3;
    let found = headings[0];
    for (const h of headings) {
      if (h.getBoundingClientRect().top <= line) found = h; else break;
    }
    if (!found || found === active) return;
    if (active) links.get(active.id).removeAttribute('aria-current');
    active = found;
    const link = links.get(found.id);
    link.setAttribute('aria-current', 'true');
    if (now) now.textContent = link.textContent;
    reveal();
  }
  let queued = 0;
  const later = () => { cancelAnimationFrame(queued); queued = requestAnimationFrame(update); };
  if (headings.length) {
    if ('IntersectionObserver' in window) {
      const seen = new IntersectionObserver(later, { rootMargin: '0px 0px -70% 0px' });
      headings.forEach((h) => seen.observe(h));
    } else {
      addEventListener('scroll', later, { passive: true });
    }
    addEventListener('hashchange', later);
    addEventListener('scrollend', later);
    addEventListener('load', later);
    update();
  }

  // ---- Requirement ids: a button beside each, which copies its link.
  const svg = (paths, cls) => {
    const el = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    el.setAttribute('viewBox', '0 0 24 24'); el.setAttribute('aria-hidden', 'true'); el.setAttribute('class', cls);
    for (const d of paths) {
      const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      p.setAttribute('d', d); el.appendChild(p);
    }
    return el;
  };
  const say = (text) => { if (live) { live.textContent = ''; setTimeout(() => { live.textContent = text; }, 30); } };
  function copy(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise((ok, fail) => {
      const field = document.createElement('textarea');
      field.value = text; field.setAttribute('readonly', ''); field.className = 'sr';
      document.body.appendChild(field); field.select();
      let done = false;
      try { done = document.execCommand('copy'); } catch (e) { done = false; }
      field.remove();
      done ? ok() : fail(new Error('copy'));
    });
  }
  const d = layout.dataset;
  if (d.copy) {
    for (const pill of article.querySelectorAll('a.req[id]')) {
      const wrap = document.createElement('span');
      wrap.className = 'req-wrap';
      pill.replaceWith(wrap);
      wrap.appendChild(pill);
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'req-copy'; button.lang = d.ui || '';
      button.setAttribute('aria-label', fill(d.copy, { id: pill.id }));
      button.title = fill(d.copy, { id: pill.id });
      button.append(svg(['M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7', 'M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7'], 'copy'), svg(['M5 12.5l4.5 4.5L19 7.5'], 'done'));
      wrap.appendChild(button);
    }
    article.addEventListener('click', (e) => {
      const button = e.target.closest('.req-copy');
      if (!button) return;
      const id = button.parentNode.querySelector('a.req').id;
      const url = location.href.split('#')[0] + '#' + id;
      copy(url).then(() => {
        button.dataset.done = '';
        setTimeout(() => button.removeAttribute('data-done'), 1600);
        say(fill(d.copied, { id }));
      }, () => say(fill(d.copyFailed, { id })));
    });
  }

  // ---- Scrolling tables and code: an edge fades while there is more to scroll to.
  function edges(el) {
    el.classList.toggle('more-left', el.scrollLeft > 2);
    el.classList.toggle('more-right', el.scrollLeft + el.clientWidth < el.scrollWidth - 2);
  }
  const scrollers = [...article.querySelectorAll('.table, pre')];
  for (const el of scrollers) {
    el.addEventListener('scroll', () => edges(el), { passive: true });
    edges(el);
  }
  if ('ResizeObserver' in window) {
    const watch = new ResizeObserver((entries) => entries.forEach((e) => edges(e.target)));
    scrollers.forEach((el) => watch.observe(el));
  } else {
    addEventListener('resize', () => scrollers.forEach(edges));
  }

  // ---- The search.
  const form = layout.querySelector('.spec-search');
  if (!form) return;
  const input = form.querySelector('input');
  const results = form.querySelector('.spec-results');
  const status = form.querySelector('#spec-q-status');
  const fd = form.dataset;
  form.hidden = false;
  form.addEventListener('submit', (e) => e.preventDefault());
  let index = null, loading = null, timer = 0, announce = 0;

  function load() {
    if (index || loading) return loading;
    loading = fetch(form.dataset.index, { credentials: 'omit' })
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((data) => {
        if (data.schema !== 1) throw new Error('schema');   // a newer index is not read
        const sections = new Map(data.sections.map((s) => [s.id, s]));
        const norm = (t) => t.toLowerCase().replace(/_/g, '-');
        index = {
          sections: data.sections.map((s) => ({ kind: 'section', id: s.id, name: s.t, ctx: s.p, key: norm(`${s.t} ${s.p}`), bare: norm(s.t.replace(/^(?:annexe? )?[a-z0-9][\w.]*\.? (?:— )?/i, '')), number: s.n.toLowerCase() })),
          reqs: data.requirements.map((r) => {
            const s = sections.get(r.s);
            return { kind: 'req', id: r.id, to: r.id, name: r.id, ctx: r.t, where: s ? s.t : '', key: norm(r.id), text: norm(r.t) };
          }),
          terms: data.terms.flatMap((t) => t.s.map((s) => {
            const sec = sections.get(s);
            return { kind: t.k, id: s, to: s, name: t.t, ctx: sec ? sec.t : '', key: norm(t.t) };
          })),
        };
      })
      .catch(() => { loading = null; throw new Error('index'); });
    return loading;
  }

  // Ranked: an id or a number as typed, a title, a route or an error, then the words of a requirement.
  function find(raw) {
    const q = raw.toLowerCase().replace(/^§\s*/, '').replace(/_/g, '-').trim();
    if (!q) return [];
    const words = q.split(/\s+/);
    const all = (text) => words.every((w) => text.includes(w));
    const out = [];
    for (const s of index.sections) {
      let score = 0;
      if (s.number && (s.number === q || s.number.startsWith(q + '.'))) score = 100;
      else if (s.bare.startsWith(q)) score = 80;
      else if (all(s.key)) score = 60;
      if (score) out.push({ score, item: s });
    }
    for (const r of index.reqs) {
      let score = 0;
      if (r.key === q) score = 110;
      else if (r.key.startsWith(q)) score = 95;
      else if (r.key.includes(q)) score = 70;
      else if (words.length > 1 || q.length > 2) if (all(r.text)) score = 30;
      if (score) out.push({ score, item: r });
    }
    for (const t of index.terms) {
      const bare = t.key.replace(/^[a-z]+ (?=<?\/|<)/, '').replace(/^<base>/, '');
      let score = 0;
      if (t.key === q || bare === q) score = 105;
      else if (bare.startsWith(q) || t.key.startsWith(q)) score = 85;
      else if (all(t.key)) score = 65;
      if (score) out.push({ score, item: t });
    }
    return out.sort((a, b) => b.score - a.score);
  }

  function row(item) {
    const li = document.createElement('li');
    const a = document.createElement('a');
    a.href = '#' + (item.to || item.id);
    const kind = document.createElement('span');
    kind.className = 'kind'; kind.lang = document.documentElement.lang;
    kind.textContent = { section: fd.kindSection, req: fd.kindReq, route: fd.kindRoute, error: fd.kindError }[item.kind];
    const name = document.createElement('span');
    name.className = 'name'; name.textContent = item.name;
    a.append(kind, name);
    if (item.ctx) {
      const c = document.createElement('span');
      c.className = 'ctx'; c.textContent = item.kind === 'req' && item.where ? `${item.where}: ${item.ctx}` : item.ctx;
      a.appendChild(c);
    }
    li.appendChild(a);
    return li;
  }

  function show() {
    const q = input.value.trim();
    const began = q && !side.classList.contains('searching');
    side.classList.toggle('searching', !!q);
    if (!q) { results.hidden = true; results.textContent = ''; status.textContent = ''; return; }
    load().then(() => {
      if (input.value.trim() !== q) return;
      const found = find(q);
      results.textContent = '';
      for (const f of found.slice(0, 40)) results.appendChild(row(f.item));
      if (!found.length) {
        const li = document.createElement('li');
        li.textContent = fd.searchNone;
        results.appendChild(li);
      }
      results.hidden = false;
      if (began) {   // the field is where the page is not: bring it, and its results, into view
        const top = form.getBoundingClientRect().top;
        if (top > innerHeight * 0.4 || top < 0) form.scrollIntoView({ block: 'start', behavior: reduce.matches ? 'auto' : 'smooth' });
      }
      clearTimeout(announce);
      announce = setTimeout(() => { status.textContent = found.length ? fill(fd.searchCount, { n: found.length }) : fd.searchNone; }, 400);
    }, () => {
      results.textContent = '';
      const li = document.createElement('li');
      li.textContent = fd.searchError;
      results.appendChild(li);
      results.hidden = false;
    });
  }

  function clear() {
    input.value = '';
    show();
  }

  input.addEventListener('focus', () => { load().catch(() => {}); });
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(show, 80); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { if (input.value) { e.preventDefault(); clear(); } else input.blur(); }
    else if (e.key === 'ArrowDown') {
      const first = results.querySelector('a');
      if (first) { e.preventDefault(); first.focus(); }
    } else if (e.key === 'Enter') {
      const first = results.querySelector('a');
      if (first) { e.preventDefault(); first.click(); }
    }
  });
  results.addEventListener('keydown', (e) => {
    const links = [...results.querySelectorAll('a')];
    const at = links.indexOf(document.activeElement);
    if (e.key === 'ArrowDown' && at < links.length - 1) { e.preventDefault(); links[at + 1].focus(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); (at > 0 ? links[at - 1] : input).focus(); }
    else if (e.key === 'Escape') { e.preventDefault(); input.focus(); clear(); }
  });
  // Choosing a result: the page goes to it, the field is emptied and the contents come back.
  results.addEventListener('click', (e) => { if (e.target.closest('a')) setTimeout(clear, 0); });
  document.addEventListener('keydown', (e) => {
    if (e.key !== '/' || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    if (t.closest && t.closest('input, textarea, select, [contenteditable]')) return;
    e.preventDefault();
    input.focus(); input.select();
  });
})();
