// The figures (tools/diagrams.py, site/README.md): the buttons that download one as SVG or PNG or show it as
// the list of its steps, and the ones that walk through a sequence step by step. Every text it shows is the figure's own markup (the page's
// catalog); the buttons are hidden until here, so without script there are none and the figure is whole.
'use strict';

(function () {
  const siteRoot = document.body.dataset.root || '';

  // ---- Download: the SVG the build wrote for the figure (diagrams.standalone), or a PNG drawn from that
  // file at twice its size.
  for (const tools of document.querySelectorAll('.dg-tools')) {
    const url = siteRoot + tools.dataset.src;
    const name = tools.dataset.src.split('/').pop();
    const link = tools.querySelector('[data-kind="svg"]');
    link.href = url;
    link.download = name;
    tools.querySelector('[data-kind="png"]').addEventListener('click', async () => {
      try {
        const text = await (await fetch(url, { credentials: 'omit' })).text();
        const image = new Image();
        image.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(text);
        await image.decode();
        const canvas = document.createElement('canvas');
        canvas.width = image.naturalWidth * 2;
        canvas.height = image.naturalHeight * 2;
        canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
        const a = document.createElement('a');
        a.href = canvas.toDataURL('image/png');
        a.download = name.replace(/\.svg$/, '.png');
        a.click();
      } catch (e) { /* the SVG link stays */ }
    });
    // The drawing or the list of its steps (the same ones a screen reader is given).
    const view = tools.querySelector('[data-kind="view"]');
    const figure = tools.closest('figure');
    view.addEventListener('click', () => {
      const list = figure.classList.toggle('dg-list');
      view.textContent = list ? view.dataset.drawing : view.dataset.list;
      view.setAttribute('aria-pressed', String(list));
    });
    tools.hidden = false;
  }

  // ---- Stepper: "next" lights one step of a sequence and dims those after it; "all" shows it whole again.
  // The step is also said, from the list every figure carries, in a status that screen readers announce.
  for (const bar of document.querySelectorAll('.dg-stepper')) {
    const figure = bar.closest('figure');
    const steps = [...figure.querySelectorAll('.dg-step')];
    const words = [...figure.querySelectorAll('ol.sr li')].map((li) => li.textContent);
    const count = bar.querySelector('.dg-count');
    const say = bar.querySelector('[role="status"]');
    let now = -1;   // -1: the figure whole
    const show = () => {
      steps.forEach((step, i) => {
        step.classList.toggle('dg-later', now >= 0 && i > now);
        step.classList.toggle('dg-now', i === now);
      });
      count.textContent = now < 0 ? '' : `${now + 1} / ${steps.length}`;
      say.textContent = now < 0 ? '' : words[now] || '';
      const current = steps[now];
      // The lit step stays in view, in the figure's own scroller and in the page (below the sticky contents bar).
      if (current && current.scrollIntoView) {
        current.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
      }
    };
    const go = (what) => {
      if (what === 'next') now = Math.min(now + 1, steps.length - 1);
      else if (what === 'prev') now = now <= 0 ? -1 : now - 1;
      else now = -1;
      show();
    };
    bar.addEventListener('click', (event) => {
      const button = event.target.closest('button');
      if (!button) return;
      go(button.dataset.do);
    });
    // Keys, once the focus is in the figure: N and P walk the steps, Escape shows the figure whole again; on the
    // stepper's own buttons the arrows do too. The drawing keeps its arrows: it scrolls with them.
    const keys = { n: 'next', p: 'prev', Escape: 'all' };
    figure.addEventListener('keydown', (event) => {
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      let what = keys[event.key];
      if (!what && bar.contains(event.target)) what = { ArrowRight: 'next', ArrowLeft: 'prev' }[event.key];
      if (!what || (event.key !== 'Escape' && event.shiftKey)) return;
      if (event.target.closest && event.target.closest('input, textarea, select')) return;
      if (what === 'all' && now < 0) return;
      event.preventDefault();
      go(what);
    });
    const shortcut = { next: 'n', prev: 'p', all: 'Escape' };
    for (const button of bar.querySelectorAll('button')) {
      if (shortcut[button.dataset.do]) button.setAttribute('aria-keyshortcuts', shortcut[button.dataset.do]);
    }
    bar.hidden = false;
  }
})();
