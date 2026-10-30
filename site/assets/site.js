// Lantern's site (site/README.md): the two menus of the header, as boreale.dev's
// site.js places them (its "site switcher" and languages blocks, copied as they are).


// Boréale's site switcher: the menu of the four sites opens under the name
// beside its button, wherever the header is. The same block in boreale.dev's,
// PlayGuard's, PlayShelf's and Aurore's site.js; boreale's is the reference.
// Without popovers (an old browser), the name still leads home.
(function () {
  const menu = document.getElementById("sites");
  const anchor = menu && menu.closest(".switcher");
  if (!anchor || !menu.showPopover) return;
  menu.addEventListener("beforetoggle", (event) => {
    if (event.newState !== "open") return;
    const box = anchor.getBoundingClientRect();
    const screen = document.documentElement.clientWidth;
    const width = Math.min(400, screen - 24); // site.css's width
    menu.style.top = `${box.bottom + window.scrollY + 6}px`;
    menu.style.left = `${Math.max(12, Math.min(box.left, screen - width - 12)) + window.scrollX}px`;
  });
})();

// The header's languages: their menu opens under its button, its right edge
// on the button's where the screen has room, the language in use in view.
(function () {
  const menu = document.getElementById("languages");
  const button = document.querySelector(".lang-button");
  if (!menu || !button || !menu.showPopover) return;
  menu.addEventListener("beforetoggle", (event) => {
    if (event.newState !== "open") return;
    const box = button.getBoundingClientRect();
    const screen = document.documentElement.clientWidth;
    menu.style.top = `${box.bottom + window.scrollY + 6}px`;
    const width = Math.min(460, screen - 24); // site.css's width
    menu.style.left = `${Math.max(12, Math.min(box.right - width, screen - width - 12)) + window.scrollX}px`;
    requestAnimationFrame(() => menu.querySelector("[aria-current]")?.scrollIntoView({ block: "nearest" }));
  });
})();
