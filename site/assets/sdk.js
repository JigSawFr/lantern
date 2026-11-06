// The SDK page: the language chosen in an example's tabs is kept (in this browser only) and followed by the other
// examples and by the tables, whose column of that language is tinted. Without script the tabs and tables work as they are.
'use strict';

(function () {
  const KEY = 'lantern-sdk-language';
  const main = document.querySelector('main');
  if (!main) return;
  let stored = '';
  try { stored = localStorage.getItem(KEY) || ''; } catch (e) { stored = ''; }

  function pick(language, remember) {
    main.dataset.pick = language;
    for (const group of main.querySelectorAll('.tabs')) {
      const radio = group.querySelector('input[data-lang="' + CSS.escape(language) + '"]');
      if (radio) radio.checked = true;
    }
    if (remember) { try { localStorage.setItem(KEY, language); } catch (e) { /* kept for this visit only */ } }
  }

  for (const radio of main.querySelectorAll('.tabs input[data-lang]')) {
    radio.addEventListener('change', () => { if (radio.checked) pick(radio.dataset.lang, true); });
  }
  if (stored && main.querySelector('.tabs input[data-lang="' + CSS.escape(stored) + '"]')) pick(stored, false);
})();
