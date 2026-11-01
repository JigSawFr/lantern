// The figures (tools/diagrams.py, site/README.md): the buttons that download one as SVG or PNG, and the
// ones that walk through a sequence step by step. Every text it shows is the figure's own markup (the page's
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
      if (current && current.scrollIntoView && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
        current.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'smooth' });
      }
    };
    bar.addEventListener('click', (event) => {
      const button = event.target.closest('button');
      if (!button) return;
      const what = button.dataset.do;
      if (what === 'next') now = Math.min(now + 1, steps.length - 1);
      else if (what === 'prev') now = now <= 0 ? -1 : now - 1;
      else now = -1;
      show();
    });
    bar.hidden = false;
  }
})();
