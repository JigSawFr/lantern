#!/usr/bin/env python3
"""The website's layout on phones, a tablet and a desktop (site/README.md).

Serves a built site (tools/build_site.py <out-dir>) and opens each page in
headless Chromium (Playwright), failing when one:

- is wider than the screen (a long word, a header that does not fit): the
  page scrolls sideways;
- throws (site.js, lang.js);
- has a target under 24px a finger cannot hit (WCAG 2.2, 2.5.8).

Every page on a small phone (320), an iPhone (402x874), a phone in landscape
(874x402), a tablet (1024) and a desktop (1440); images not loaded (their
boxes are in the pages). With SITE_AXE set to axe-core's axe.min.js, also
what axe finds against WCAG 2.2 A and AA on an iPhone, on every page.

Usage: tools/site_layout.py <site-dir>   (needs Playwright for Python with
Chromium, PLAYWRIGHT_CHROMIUM=<path> for a browser of its own). Adapted from
Atlas's and boreale.dev's tools/site_layout.py.
"""
import asyncio
import functools
import http.server
import os
import sys
import threading

from playwright.async_api import async_playwright

SITE = sys.argv[1]
AXE = os.environ.get("SITE_AXE")
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
SCREENS = [("small phone", 320, 640, True), ("iPhone", 402, 874, True), ("phone in landscape", 874, 402, True),
           ("tablet", 1024, 768, False), ("desktop", 1440, 900, False)]

MEASURE = """(screen) => {
  const out = { width: document.documentElement.scrollWidth, wide: [], small: [] };
  if (out.width > screen + 1) {
    for (const e of document.querySelectorAll('body *')) {
      if (e.getBoundingClientRect().right <= screen + 1) continue;
      let a = e.parentElement, clipped = false;
      for (; a && a !== document.body; a = a.parentElement) {
        if (getComputedStyle(a).overflowX !== 'visible') { clipped = true; break; }
      }
      if (!clipped) out.wide.push(`${e.tagName.toLowerCase()} "${(e.textContent || '').trim().slice(0, 40)}"`);
      if (out.wide.length >= 3) break;
    }
  }
  for (const e of document.querySelectorAll('a[href], button')) {
    const r = e.getBoundingClientRect();
    if (r.width && r.height && (r.width < 24 || r.height < 24) && getComputedStyle(e).display !== 'inline')
      out.small.push(`${e.tagName.toLowerCase()} "${(e.textContent || '').trim().slice(0, 30)}"`);
  }
  return out;
}"""


def pages():
    found = []
    for root, dirs, files in os.walk(SITE):
        dirs[:] = [d for d in dirs if d != "assets"]
        for f in files:
            if f.endswith(".html"):
                path = os.path.relpath(os.path.join(root, f), SITE).replace(os.sep, "/")
                found.append(path.removesuffix("index.html"))
    return sorted(found)


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve():
    handler = functools.partial(Quiet, directory=SITE)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}/"


async def check(browser, base, screen, paths, failures):
    name, width, height, phone = screen
    # In English, so the first visit stays on the page asked for (assets/lang.js).
    context = await browser.new_context(viewport={"width": width, "height": height}, is_mobile=phone,
                                        has_touch=phone, locale="en-US", reduced_motion="reduce")
    await context.route("**/*.{png,webp,jpg,jpeg,gif}", lambda route: route.abort())
    page = await context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    for path in paths:
        errors.clear()
        await page.goto(base + path, wait_until="networkidle")
        m = await page.evaluate(MEASURE, width)
        where = f"{name} ({width}px) /{path}"
        if m["width"] > width + 1:
            failures.append(f"{where}: {m['width']}px wide: " + ", ".join(m["wide"]))
        if m["small"]:
            failures.append(f"{where}: targets under 24px: {', '.join(m['small'])}")
        failures.extend(f"{where}: {e}" for e in errors)
    await context.close()


async def accessible(browser, base, paths, failures):
    name, width, height, phone = SCREENS[1]
    # axe is a script added to the page, which the site's CSP refuses.
    context = await browser.new_context(viewport={"width": width, "height": height}, is_mobile=phone,
                                        has_touch=phone, locale="en-US", bypass_csp=True, reduced_motion="reduce")
    source = open(AXE, encoding="utf-8").read()
    page = await context.new_page()
    for path in paths:
        await page.goto(base + path, wait_until="networkidle")
        await page.add_script_tag(content=source)
        found = await page.evaluate("""(tags) => axe.run(document, {
            runOnly: { type: 'tag', values: tags }, resultTypes: ['violations'] })
          .then((r) => r.violations.map((v) => ({ id: v.id, help: v.help,
            where: v.nodes.slice(0, 3).map((n) => n.target.join(' ')) })))""", AXE_TAGS)
        failures.extend(f"axe /{path}: {v['id']} ({v['help']}): {', '.join(v['where'])}" for v in found)
    await context.close()


async def main():
    paths = pages()
    base = serve()
    failures = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM") or None)
        for screen in SCREENS:
            await check(browser, base, screen, paths, failures)
        if AXE:
            await accessible(browser, base, paths, failures)
        await browser.close()
    for f in failures:
        print(f"::error::{f}" if os.environ.get("GITHUB_ACTIONS") else f)
    print(f"site layout: {len(paths)} pages on {len(SCREENS)} screens" + (", with axe" if AXE else "")
          + f", {len(failures)} problem(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
