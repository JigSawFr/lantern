// Lantern's site (site/README.md): the copy buttons of the home page and the
// demo. The page chrome's script (the home's aurora, the header's links on a
// phone, the cards' glow and the sections' reveal) is boreale-site's
// chrome.js; the header's two menus and the language chosen are its
// boreale.js and lang.js. One dark look, Boréale's, as PlayGuard's and
// PlayShelf's.
'use strict';

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
