// Lantern's site (site/README.md): the aurora of the home page, the
// header's links on a phone, and the home page's cards and sections. The
// header's two menus and the language chosen are boreale-site's (boreale.js,
// lang.js). One dark look, Boréale's, as PlayGuard's and PlayShelf's.
'use strict';

// The aurora behind the home page's header and hero (canvas#sky), the same
// as boreale.dev's, PlayGuard's and PlayShelf's: three soft curtains in the
// brand's colours under a few stars; they move only while the sky is in
// view, the page visible and the visitor has not asked for less motion.
// Without script, site.css's gradient stands in.
(function () {
  const canvas = document.getElementById('sky');
  if (!canvas || !canvas.getContext) return;
  const ctx = canvas.getContext('2d');
  // The curtains are drawn here at a quarter of the size, then laid on the
  // sky blurred and scaled up in one go: blurring each strip would be slow.
  const glow = document.createElement('canvas');
  const gtx = glow.getContext('2d');
  const still = window.matchMedia('(prefers-reduced-motion: reduce)');
  const curtains = [
    { rgb: [0, 255, 204], y: 0.34, amp: 0.08, freq: 1.2, speed: 0.00012, height: 0.42, alpha: 0.34 },
    { rgb: [51, 187, 255], y: 0.26, amp: 0.06, freq: 1.7, speed: -0.00009, height: 0.34, alpha: 0.26 },
    { rgb: [138, 92, 255], y: 0.18, amp: 0.05, freq: 0.9, speed: 0.00007, height: 0.3, alpha: 0.26 },
  ];
  let w = 0, h = 0, stars = [];

  function size() {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    w = canvas.clientWidth; h = canvas.clientHeight;
    canvas.width = Math.max(1, Math.round(w * ratio));
    canvas.height = Math.max(1, Math.round(h * ratio));
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    glow.width = Math.max(1, Math.round(w / 4));
    glow.height = Math.max(1, Math.round(h / 4));
    let seed = 7; // the same stars at each load
    const random = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    stars = Array.from({ length: Math.round((w * h) / 2600) }, () => ({
      x: random() * w, y: random() * h * 0.75, r: random() * 1.1 + 0.2, a: random() * 0.6 + 0.2,
    }));
  }

  function draw(t) {
    const gw = glow.width, gh = glow.height;
    gtx.globalCompositeOperation = 'source-over';
    gtx.clearRect(0, 0, gw, gh);
    gtx.globalCompositeOperation = 'lighter';
    const step = Math.max(2, gw / 120);
    for (const c of curtains) {
      const [r, g, b] = c.rgb;
      const phase = t * c.speed;
      for (let x = -step; x < gw + step; x += step) {
        const u = x / gw;
        const base = gh * (c.y + c.amp * Math.sin((u * c.freq + phase) * 2 * Math.PI) + 0.03 * Math.sin(u * 17 + phase * 20));
        const length = gh * c.height * (0.6 + 0.4 * Math.sin(u * 9 + phase * 11));
        const flicker = 0.65 + 0.35 * Math.sin(u * 31 + phase * 40);
        const fill = gtx.createLinearGradient(0, base - length, 0, base);
        fill.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0)`);
        fill.addColorStop(0.75, `rgba(${r}, ${g}, ${b}, ${c.alpha * flicker * 0.6})`);
        fill.addColorStop(1, `rgba(${r}, ${g}, ${b}, ${c.alpha * flicker})`);
        gtx.fillStyle = fill;
        gtx.fillRect(x, base - length, step + 1, length);
      }
    }

    ctx.fillStyle = '#0b1424';
    ctx.fillRect(0, 0, w, h);
    ctx.filter = 'blur(8px)'; // where the browser can; scaling up softens it anyway
    ctx.drawImage(glow, 0, 0, w, h);
    ctx.filter = 'none';
    for (const s of stars) {
      ctx.fillStyle = `rgba(232, 238, 247, ${s.a})`;
      ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, 2 * Math.PI); ctx.fill();
    }
  }

  // The curtains drift slowly: 30 frames a second is plenty, and half the
  // work on a 60 or 120Hz screen. Nothing is drawn while the sky is scrolled
  // out of view, the page hidden, or less motion asked.
  const FRAME = 1000 / 30;
  let frame = 0, last = 0, seen = true;
  function loop(t) {
    if (t - last >= FRAME - 1) { last = t; draw(t); }
    frame = requestAnimationFrame(loop);
  }
  function start() {
    cancelAnimationFrame(frame);
    if (still.matches || document.hidden || !seen) draw(last);
    else frame = requestAnimationFrame(loop);
  }

  size();
  start();
  let resizing = 0; // once per frame, however many resize events come
  window.addEventListener('resize', () => {
    cancelAnimationFrame(resizing);
    resizing = requestAnimationFrame(() => { size(); draw(last); });
  });
  document.addEventListener('visibilitychange', start);
  still.addEventListener('change', start);
  if ('IntersectionObserver' in window) {
    new IntersectionObserver((entries) => {
      seen = entries[entries.length - 1].isIntersecting;
      start();
    }).observe(canvas);
  }
})();

// The header's links on a phone, a row to scroll: its edge fades while
// there are more of them to scroll to.
(function () {
  const nav = document.querySelector('.nav');
  if (!nav) return;
  const fade = () => nav.classList.toggle('more', nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 2);
  nav.addEventListener('scroll', fade, { passive: true });
  addEventListener('resize', fade);
  fade();
})();

// The home page (site.css's "showcase"): the cards' edge lit where the
// pointer is, and the sections rising into view once (not with less motion
// asked, nor for a section already in view at load).
(function () {
  for (const card of document.querySelectorAll('.card')) {
    card.addEventListener('pointermove', (e) => {
      const box = card.getBoundingClientRect();
      card.style.setProperty('--mx', `${e.clientX - box.left}px`);
      card.style.setProperty('--my', `${e.clientY - box.top}px`);
    });
  }
  if (matchMedia('(prefers-reduced-motion: reduce)').matches || !('IntersectionObserver' in window)) return;
  const seen = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (e.isIntersecting) { e.target.classList.add('in'); seen.unobserve(e.target); }
    }
  }, { rootMargin: '0px 0px -12% 0px' });
  for (const part of document.querySelectorAll('.home main > .section, .home main > .band')) {
    if (part.getBoundingClientRect().top < innerHeight * 0.88) continue;
    part.classList.add('reveal');
    [...part.querySelectorAll('.card')].forEach((card, i) => card.style.setProperty('--i', i % 6));
    seen.observe(part);
  }
})();

// The copy buttons (the home page's request, the demo's address): a button
// with data-copy="<id>" copies that element's text (or a field's value). It
// is hidden in the markup, so that without script no dead button shows; its
// words (data-label, data-copied, data-failed) are the page's, in its
// language, and the outcome is said politely in a live region.
(function () {
  const buttons = document.querySelectorAll('button[data-copy]');
  if (!buttons.length) return;
  const live = document.createElement('p');
  live.className = 'sr'; live.setAttribute('role', 'status'); live.setAttribute('aria-live', 'polite');
  document.body.append(live);

  function copy(text, field) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise((ok, fail) => {
      // Without the clipboard API (an old browser, plain HTTP): select the text and ask the browser.
      const area = field || Object.assign(document.createElement('textarea'), { value: text });
      if (!field) {
        area.setAttribute('readonly', ''); area.style.cssText = 'position:fixed;left:-9999px;top:0;font-size:16px';
        document.body.append(area);
      }
      area.select();
      let done = false;
      try { done = document.execCommand('copy'); } catch (e) { done = false; }
      if (!field) area.remove();
      done ? ok() : fail(new Error('copy'));
    });
  }

  for (const button of buttons) {
    button.hidden = false;
    const text = button.querySelector('.copy-text');
    const was = text ? text.textContent : '';
    const target = document.getElementById(button.dataset.copy);
    if (button.dataset.label) button.setAttribute('aria-label', button.dataset.label);
    let timer = 0;
    const say = (words, done) => {
      live.textContent = '';
      setTimeout(() => { live.textContent = words; }, 30);   // a repeated message is read again
      if (done) button.setAttribute('data-done', ''); else button.removeAttribute('data-done');
      if (text) text.textContent = done ? words : was;
      clearTimeout(timer);
      timer = setTimeout(() => { button.removeAttribute('data-done'); if (text) text.textContent = was; }, 2500);
    };
    button.addEventListener('click', () => {
      if (!target) return;
      const field = 'value' in target ? target : null;
      const value = field ? field.value : target.textContent.trim();
      copy(value, field).then(() => say(button.dataset.copied, true), () => {
        live.textContent = button.dataset.failed;
        if (field) field.select();
      });
    });
  }
  // A read-only address is selected whole when it is clicked or reached.
  for (const field of document.querySelectorAll('input[readonly][data-select]')) {
    field.addEventListener('focus', () => field.select());
    field.addEventListener('click', () => field.select());
  }
})();
