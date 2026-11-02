// The home page's rail: a column of dots at the right edge of a wide screen, one for each section (its link is
// the section's own title, so there is nothing to translate but the rail's name, the script's data-label), the
// one being read lit. Without script there is no rail; on a phone or a narrow window it is not shown.
'use strict';

(function () {
  const sections = [...document.querySelectorAll('main > section[id]')]
    .map((section) => ({ section, title: section.querySelector('h2') }))
    .filter((s) => s.title);
  if (sections.length < 3) return;
  const nav = document.createElement('nav');
  nav.className = 'rail';
  nav.setAttribute('aria-label', document.currentScript ? document.currentScript.dataset.label : '');
  const list = document.createElement('ul');
  const dots = new Map();
  for (const { section, title } of sections) {
    const li = document.createElement('li');
    const a = document.createElement('a');
    a.href = '#' + section.id;
    a.title = title.textContent.trim();
    const label = document.createElement('span');
    label.className = 'sr';
    label.textContent = a.title;
    a.append(label);
    li.append(a);
    list.append(li);
    dots.set(section, a);
  }
  nav.append(list);
  document.body.append(nav);

  // The section read is the last whose top is above the middle of the screen.
  const reading = () => {
    let now = sections[0].section;
    for (const { section } of sections) if (section.getBoundingClientRect().top <= innerHeight * 0.45) now = section;
    for (const [section, a] of dots) {
      if (section === now) a.setAttribute('aria-current', 'location'); else a.removeAttribute('aria-current');
    }
  };
  let queued = false;
  addEventListener('scroll', () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; reading(); });
  }, { passive: true });
  addEventListener('resize', reading);
  reading();
})();
