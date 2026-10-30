# Lantern's website

`https://lantern.boreale.dev/`: the protocol's page and its specification, in the fifteen languages of Boréale's sites (English at the root, each other one in its folder: `/fr/`, `/fr-ca/`, `/de/` ... `/zh-hant/`), and the error types the specification's `type` addresses lead to (`/errors/<name>/`, in English). Every link inside it is relative, so it works at another address too.

```sh
python3 tools/build_site.py build         # the pages (SITE_OFFLINE=1: without boreale.dev's versions)
python3 tools/check_site.py build         # links, anchors, catalogs, CSP, referrers, UTM tags, error types
python3 -m http.server -d build           # then http://localhost:8000/
SITE_AXE=axe.min.js python3 tools/site_layout.py build   # phones to desktop, with axe (Playwright)
```

- `template.html` is every page's frame, `home.html` the protocol's page. Each `{{key}}` is a text of `i18n/<language>.json` (`en.json` the reference; the menu of Boréale's sites, the privacy texts and the footer's notice are boreale.dev's catalogs' word for word).
- **The specification** (`spec/`) is `SPEC.md`, rendered at each build by `build_site.py` (`blocks()`, the Markdown SPEC.md is written in, with the standard library only): each heading an anchor as GitHub makes it (`#42-handshake`), each `§ 4.2` a link to its section, its contents beside it. It stays in English in every language; the page around it is translated and says so.
- **The error types** (`errors/`): § 10's table, read from SPEC.md, one row and one page per `code`, at the address its `type` gives (`https://lantern.boreale.dev/errors/account-frozen`). `check_site.py` fails when one of SPEC.md's error addresses has no page.
- The look is Boréale's (`branding/README.md` in JigSawFr/boreale): the night, the aurora once at the top, Sora, Figtree and JetBrains Mono served with the site (`assets/fonts/`, SIL Open Font License; the language menu's flags CC BY 4.0). `assets/mark.svg` is Lantern's mark (the frame in the aurora's colours, a lantern in snow, its flame lit), also the favicon and `assets/marks/lantern.svg`; `social-preview.html` is the source of `assets/social-preview.png`, taken with Chromium at 1280 × 640.
- **The header**: the name opens the menu of Boréale's sites (`switcher()`, `SITES` in `build_site.py`: boreale.dev's list, then Atlas and Lantern), each with its latest release from `https://boreale.dev/versions.json` (`versions_of()` reads `{"schema": 1, "projects": {...}}` and the flat shape of before; another schema shows no versions). The languages' menu leads to the same page in another language, and the choice is kept (`assets/lang.js`, `lantern-lang`).
- **Links out** (`links_out()`): every page says `<meta name="referrer" content="no-referrer">`; a link to another site has `rel="noreferrer"`, one to boreale.dev, its subdomains or github.com/JigSawFr keeps the origin (`referrerpolicy="strict-origin"`). A link to another of our sites carries `utm_source=lantern` and `utm_medium=nav`, `footer` or `link` (`utm()`), one to this site or anyone else none.
- **The audience**, counted by Umami Cloud: `assets/umami.js` is its tracker, served with the site (a copy of <https://cloud.umami.is/script.js>, Boréale's sites share it), which sends each page seen to `gateway.umami.is`, without cookie, and only from `lantern.boreale.dev` (`data-domains`), not from a preview or a local copy. Its site in Umami is Boréale's (`UMAMI_WEBSITE`), shared with the other projects' sites. The home page's privacy section says what it counts, and links to boreale.dev's privacy and legal notice.
- The Content-Security-Policy allows nothing but the site itself: no inline script or style, no font or script from elsewhere; the one address a page may send to is Umami's (`connect-src`).
- No e-mail address anywhere: contact goes through the repository's issues (`check_site.py` checks it).

`.github/workflows/site.yml` builds and checks it for each pull request touching it, and publishes main's on GitHub Pages (*Settings › Pages › Source: GitHub Actions*; the custom domain is written in `build/CNAME` too).
