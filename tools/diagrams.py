"""The specification's diagrams, drawn as inline SVG by the site's build.

Each diagram is data (DIAGRAMS): who talks to whom, in what order, or what
leads to what. This module lays it out and draws it, in the site's colours
(classes of site/assets/site.css, no inline style: the CSP forbids it). The
text of a diagram is either protocol text, shown as written (routes, fields,
codes), or a catalog key ("@name" is the key `dg_name` of site/i18n/*.json),
so that every language reads the same drawing. Each figure also carries the
same steps as a list for screen readers: the drawing alone says nothing to
them.

SPEC.md stays the only normative text and holds no picture: the figures are
the site's, put under a section's heading (WHERE) when the page is built.
"""

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The section a figure goes under: the heading's number in SPEC.md (and in its translations).
WHERE = {
    "connect": "4",
    "features": "4.2",
    "signed": "5.4",
    "invitation": "5.5",
    "homebrew": "8.4",
    "requests": "11",
    "errors": "12",
    "deltas": "22",
    "saves": "9",
    "saves_e2e": "9.4",
    "events": "18",
    "peers": "19",
    "sync": "20",
    "static": "21.1",
    "threats": "16",
}

SEQUENCE, GRAPH, COLUMNS = "sequence", "graph", "columns"

DIAGRAMS = {
    # ---- From a device finding a server to its signed calls (§ 4.1, 4.2, 5.2, 5.3, 5.4).
    "connect": {
        "kind": SEQUENCE,
        "actors": ["@device", "@server", "@phone"],
        "steps": [
            ("msg", 0, 1, 'UDP 47115  {"lantern":"discover"}'),
            ("msg", 1, 0, '{"lantern":"server", uid, port, base}', True),
            ("note", 0, 1, "@connect_hint"),
            ("msg", 0, 1, "GET /.well-known/lantern"),
            ("msg", 1, 0, "handshake: uid, versions,\nplatforms, features, limits", True),
            ("sep", "@connect_pairing"),
            ("msg", 0, 1, "POST /v1/pairing\n{device, scopes, key}"),
            ("msg", 1, 0, "code KQ4M-7TXD, verify_complete,\npoll, interval", True),
            ("note", 0, 0, "@connect_show"),
            ("msg", 2, 1, "@connect_approve"),
            ("msg", 0, 1, "GET <poll>  (every interval)"),
            ("msg", 1, 0, "202 …  then  200 {token: et_…}\nor 410 gone · 429 slow_down", True),
            ("note", 0, 0, "@connect_pin"),
            ("sep", "@connect_calls"),
            ("msg", 0, 1, "Authorization: Bearer et_…\n+ request signature"),
            ("msg", 1, 0, "200  ·  401  ·  403", True),
        ],
    },
    # ---- Which feature opens which routes, for whom (§ 4.2).
    "features": {
        "kind": COLUMNS,
        "per_row": 4,
        "cols": [
            ("library", [("library", "6"), ("titles", "7"), ("homebrew", "8"), ("changes", "6.4"),
                         ("sections", "6.5"), ("deltas", "22")]),
            ("saves", [("saves", "9"), ("encrypted_saves", "9.4")]),
            ("cheats · cheats.write", [("cheats", "10")]),
            ("requests", [("requests", "11")]),
            ("sync.read · sync.write", [("sync", "20")]),
            ("admin", [("admin", "5.7")]),
            ("@feat_any", [("pairing", "5.2"), ("signatures", "5.4"), ("events", "18"), ("peers", "19")]),
        ],
    },
    # ---- Backing up and restoring a save (§ 9.1 to 9.3).
    "saves": {
        "kind": SEQUENCE,
        "actors": ["@device", "@server"],
        "steps": [
            ("sep", "@saves_backup"),
            ("msg", 0, 1, "POST /v1/saves/{title_id}\nContent-Digest: sha-256=:…:"),
            ("msg", 1, 0, "201 save entry (save_id, sha256)", True),
            ("note", 0, 1, "@saves_big"),
            ("msg", 0, 1, "POST /v1/saves/{title_id}/uploads\n{size, sha256, kind}"),
            ("msg", 1, 0, "201 {upload, chunk_size, offset}", True),
            ("msg", 0, 1, "PATCH <upload>  Upload-Offset: n"),
            ("msg", 1, 0, "204  Upload-Offset: n + chunk", True),
            ("msg", 0, 1, "HEAD <upload>  (after a cut)"),
            ("msg", 1, 0, "204  Upload-Offset, Upload-Length", True),
            ("msg", 1, 0, "last chunk: 201 save entry\nor 422 digest_mismatch", True),
            ("sep", "@saves_restore"),
            ("msg", 0, 1, "GET /v1/saves?platform=&title_id="),
            ("msg", 1, 0, "{saves: [Save…]}  newest first", True),
            ("note", 0, 0, "@saves_warn"),
            ("msg", 0, 1, "GET /v1/saves/{title_id}/{save_id}"),
            ("msg", 1, 0, "@saves_archive", True),
            ("note", 0, 0, "@saves_check"),
        ],
    },
    # ---- The key of an encrypted backup never leaves the user's devices (§ 9.4).
    "saves_e2e": {
        "kind": GRAPH,
        "cols": 3, "rows": 3,
        "nodes": {
            "archive": (0, 0, "@e2e_archive", "dev"),
            "encrypt": (1, 0, "@e2e_encrypt", "dev"),
            "server": (2, 0, "@e2e_server", "srv"),
            "phrase": (0, 1, "@e2e_phrase", "dev"),
            "key": (1, 1, "@e2e_key", "key"),
            "server2": (2, 2, "@e2e_server2", "srv"),
            "decrypt": (1, 2, "@e2e_decrypt", "dev"),
            "restored": (0, 2, "@e2e_restored", "dev"),
        },
        "edges": [
            ("archive", "encrypt", "zip"),
            ("encrypt", "server", "LTNE2E01 + chunks"),
            ("key", "encrypt", "@e2e_wraps"),
            ("key", "server", "@e2e_never", "bad"),
            ("key", "phrase", "@e2e_carry"),
            ("server2", "decrypt", "GET …/{save_id}"),
            ("key", "decrypt", "@e2e_unwraps"),
            ("decrypt", "restored", "zip"),
        ],
    },
    # ---- A signed request, and its refusals (§ 5.4).
    "signed": {
        "kind": SEQUENCE,
        "actors": ["@client", "@server"],
        "steps": [
            ("note", 0, 0, "@sg_key"),
            ("msg", 0, 1, "GET /v1/apps?page_size=50\nAuthorization: Bearer et_…\nSignature-Input: lantern=(…);created, nonce, keyid, alg\nSignature: lantern=:…:"),
            ("note", 1, 1, "@sg_check"),
            ("msg", 1, 0, "200", True),
            ("msg", 1, 0, "401 signature_required | signature_invalid\n| signature_expired | signature_replayed", True),
            ("note", 0, 0, "@sg_clock"),
            ("msg", 0, 1, "@sg_again"),
            ("msg", 1, 0, "200", True),
        ],
    },
    # ---- An invitation: a device pairs without anyone signing in (§ 5.5).
    "invitation": {
        "kind": SEQUENCE,
        "actors": ["@admin", "@server", "@device"],
        "steps": [
            ("msg", 0, 1, "@inv_create"),
            ("msg", 1, 0, "{code, link, devices, expires}", True),
            ("msg", 0, 2, "@inv_hand"),
            ("msg", 2, 1, 'POST /v1/pairing\n{device, scopes, key, "invitation": code}'),
            ("note", 1, 1, "@inv_limits"),
            ("msg", 1, 2, "@inv_poll", True),
        ],
    },
    # ---- An author's signature, and the key a client pins (§ 8.4).
    "homebrew": {
        "kind": SEQUENCE,
        "actors": ["@author", "@server", "@client"],
        "steps": [
            ("msg", 0, 1, "package + signature\n{alg: ed25519, public_key, value}"),
            ("note", 1, 1, "@hb_serves"),
            ("msg", 1, 2, "entry + package + signature", True),
            ("note", 2, 2, "@hb_check"),
            ("note", 2, 2, "@hb_pin"),
            ("note", 2, 2, "@hb_change"),
        ],
    },
    # ---- The life of a request (§ 11).
    "requests": {
        "kind": GRAPH,
        "cols": 3, "rows": 2,
        "nodes": {
            "ask": (0, 0, "@rq_ask", "dev"),
            "open": (1, 0, "open", "srv"),
            "done": (2, 0, "done", "dev"),
            "declined": (2, 1, "declined", "bad"),
            "withdrawn": (1, 1, "@rq_withdrawn", "dev"),
        },
        "edges": [
            ("ask", "open", "POST /v1/requests"),
            ("open", "done", "@rq_done"),
            ("open", "declined", "@rq_declined"),
            ("open", "withdrawn", "DELETE"),
        ],
    },
    # ---- Which status, which code, for which cause (§ 12).
    "errors": {
        "kind": COLUMNS,
        "per_row": 4, "cw": 220, "tall": True,
        "cols": [
            ("@er_who", [("401 unauthorized", "5.1"), ("401 signature_*", "5.4"), ("403 account_frozen", "4.2"),
                         ("429 slow_down", "5.2")]),
            ("@er_req", [("400 bad_request", "2.4"), ("413 too_large", "9.3"), ("422 digest_mismatch", "9.2"),
                         ("422 unsupported_schema", "3.2")]),
            ("@er_state", [("404 not_found", "12"), ("409 conflict", "9.3"), ("410 gone", "6.4"),
                           ("412 precondition_failed", "20.4")]),
            ("@er_server", [("500 internal", "12"), ("503 unavailable", "12")]),
        ],
    },
    # ---- Updating a file from an older version, chunk by chunk (§ 22).
    "deltas": {
        "kind": GRAPH,
        "cols": 3, "rows": 3, "pad": 90,
        "nodes": {
            "seed": (0, 0, "@dl_seed", "dev"),
            "cut": (1, 0, "@dl_cut", "dev"),
            "missing": (2, 0, "@dl_missing", "srv"),
            "index": (1, 1, "@dl_index\nGET /v1/chunks/sha256/{hex}", "srv"),
            "assemble": (2, 1, "@dl_assemble", "dev"),
            "verify": (2, 2, "@dl_verify", "key"),
            "install": (1, 2, "@dl_install", "dev"),
        },
        "edges": [
            ("seed", "cut", ""),
            ("index", "cut", ""),
            ("cut", "missing", "@dl_other"),
            ("cut", "assemble", "@dl_found"),
            ("missing", "assemble", "@dl_each"),
            ("assemble", "verify", ""),
            ("verify", "install", ""),
        ],
    },
    # ---- A stream of events, and its resumption (§ 18).
    "events": {
        "kind": SEQUENCE,
        "actors": ["@client", "@server"],
        "steps": [
            ("msg", 0, 1, "GET /v1/events\nAccept: text/event-stream"),
            ("msg", 1, 0, "200  retry: 5000\nevent: ready  id: s_…", True),
            ("msg", 1, 0, "event: library | request | save | sync\nid: s_…", True),
            ("msg", 1, 0, ": heartbeat  (every limits.heartbeat)", True),
            ("note", 0, 1, "@ev_cut"),
            ("msg", 0, 1, "GET /v1/events\nLast-Event-ID: <last id>"),
            ("msg", 1, 0, "@ev_missed", True),
            ("msg", 1, 0, "or 410 gone (@ev_old)", True),
            ("note", 0, 0, "@ev_reread"),
            ("sep", "@ev_poll"),
            ("msg", 0, 1, "GET /v1/changes?since=<token>&wait=30"),
            ("msg", 1, 0, "@ev_answer", True),
        ],
    },
    # ---- A file from a peer, on the strength of a grant (§ 19).
    "peers": {
        "kind": SEQUENCE,
        "actors": ["@client", "@server", "@peer"],
        "steps": [
            ("msg", 0, 2, 'UDP 47115  {"peers": true}'),
            ("msg", 2, 0, '{"lantern":"peer", port, servers: [uid…]}', True),
            ("msg", 0, 1, "GET /v1/grants/sha256/{hex}"),
            ("msg", 1, 0, "{grant, expires}  (@peer_signed)", True),
            ("msg", 0, 2, "GET /v1/blobs/sha256/{hex}\nLantern-Grant: <grant>"),
            ("note", 2, 2, "@peer_check"),
            ("msg", 2, 0, "@peer_file", True),
            ("note", 0, 0, "@peer_verify"),
        ],
    },
    # ---- The life of a console's sync (§ 20).
    "sync": {
        "kind": GRAPH,
        "cols": 3, "rows": 2,
        "nodes": {
            "off": (0, 0, "@sync_off", "dev"),
            "asking": (1, 0, "@sync_asking", "dev"),
            "synced": (2, 0, "@sync_synced", "srv"),
            "reset": (0, 1, "@sync_reset", "bad"),
            "deleted": (2, 1, "@sync_deleted", "dev"),
        },
        "edges": [
            ("off", "asking", "@sync_turn_on"),
            ("asking", "synced", "@sync_agrees"),
            ("synced", "deleted", "DELETE /v1/sync"),
            ("deleted", "reset", "@sync_other"),
            ("reset", "off", "@sync_drop"),
        ],
    },
    # ---- The files of a static library (§ 21.1).
    "static": {
        "kind": GRAPH,
        "cols": 3, "rows": 6,
        "nodes": {
            "root": (0, 2, "@static_root", "dev"),
            "hand": (1, 0, "lantern.json\n@static_hand", "srv"),
            "v1": (1, 2, "v1/", "dev"),
            "apps": (2, 1, "apps/<p>/pages/<n>.json", "dev"),
            "titles": (2, 2, "titles/<p>/<title_id>.json\ntitles/<p>/pages/<n>.json", "dev"),
            "homebrew": (2, 3, "homebrew/<p>/pages/<n>.json\nhomebrew/<p>/<id>.json", "dev"),
            "cheats": (2, 4, "cheats/<p>/<t>.json\ncheats/<id>.txt", "dev"),
            "blobs": (2, 5, "blobs/sha256/<hex>\nchunks/sha256/<hex>.json", "key"),
        },
        "edges": [
            ("root", "hand", ""),
            ("root", "v1", ""),
            ("v1", "apps", ""),
            ("v1", "titles", ""),
            ("v1", "homebrew", ""),
            ("v1", "cheats", ""),
            ("v1", "blobs", ""),
        ],
        "wide": 1,
    },
    # ---- Who Lantern protects against what (§ 16): each threat, and the rules that answer it.
    "threats": {
        "kind": COLUMNS,
        "per_row": 3, "cw": 250, "tall": True,
        "cols": [
            ("@thr_network", [("@d_tls", "2"), ("@d_pin", "5.3"), ("@d_sign", "5.4"), ("@d_hash", "6.6")]),
            ("@thr_server", [("@d_paths", "8.2"), ("@d_author", "8.4"), ("@d_bounds", "13")]),
            ("@thr_thief", [("@d_bound", "5.4")]),
            ("@thr_source", [("@d_check", "19.1"), ("@d_nocred", "19.1")]),
            ("@thr_curious", [("@d_e2e", "9.4"), ("@d_consent", "20.1")]),
        ],
    },
    # ---- The home page: one protocol between apps and libraries.
    "overview": {
        "kind": GRAPH,
        "cols": 3, "rows": 1,
        "nodes": {
            "clients": (0, 0, "@ov_clients", "dev"),
            "lantern": (1, 0, "@ov_lantern", "key"),
            "servers": (2, 0, "@ov_servers", "srv"),
        },
        "edges": [
            ("clients", "lantern", "@ov_find"),
            ("lantern", "servers", "@ov_families"),
        ],
    },
}

FONT = 12.5
LINE = 15


def tw(text: str, mono: bool = True) -> float:
    return max((len(line) for line in text.split("\n")), default=0) * (7.4 if mono else 6.9)


def esc(text: str) -> str:
    return html.escape(text, quote=True)


KEY = re.compile(r"@([a-z0-9_]+)")


def words(item: str, catalog: dict) -> tuple:
    """(text, is protocol text) of an item: each "@name" in it is the catalog's `dg_name`, the rest as written;
    an item with none is protocol text (set in the monospace)."""
    if "@" not in item:
        return item, True
    return KEY.sub(lambda m: catalog["dg_" + m.group(1)], item), False


def text_el(x: float, y: float, text: str, cls: str = "", anchor: str = "middle") -> str:
    """A text of one or several lines, `y` the first line's baseline."""
    spans = "".join(f'<tspan x="{x:.0f}" dy="{0 if i == 0 else LINE}">{esc(line)}</tspan>'
                    for i, line in enumerate(text.split("\n")))
    return f'<text class="{cls}" x="{x:.0f}" y="{y:.0f}" text-anchor="{anchor}">{spans}</text>'


def lines_of(text: str) -> int:
    return text.count("\n") + 1


def figure(name: str, svg: str, steps: list, catalog: dict, src: str | None = None, stepper: bool = False) -> str:
    """The figure: its drawing, its caption and its steps. `src` is where the standalone SVG of the figure is
    served, relative to the site's root (the build writes it, standalone()): with it, the figure offers to
    download it as SVG, or as PNG drawn from it (site/assets/spec.js sets the links, so that without script
    there are none)."""
    caption = esc(catalog[f"dg_{name}_caption"])
    items = "".join(f"<li>{esc(s)}</li>" for s in steps)
    tools = ""
    if src:
        tools = (f'<p class="dg-tools" hidden data-src="{esc(src)}">'
                 f'<a data-kind="svg" title="{esc(catalog["dg_download_svg"])}">SVG</a>'
                 f'<button type="button" data-kind="png" title="{esc(catalog["dg_download_png"])}">PNG</button></p>')
    if stepper:
        tools += (f'<p class="dg-stepper" hidden data-steps="{len(steps)}">'
                  f'<button type="button" data-do="prev">{esc(catalog["dg_step_prev"])}</button>'
                  f'<button type="button" data-do="next">{esc(catalog["dg_step_next"])}</button>'
                  f'<button type="button" data-do="all">{esc(catalog["dg_step_all"])}</button>'
                  f'<span class="dg-count" aria-hidden="true"></span><span class="sr" role="status" aria-live="polite"></span></p>')
    return (f'<figure class="diagram" id="diagram-{name.replace("_", "-")}">'
            f'<div class="dg-scroll" tabindex="0" role="region" aria-label="{caption}">{svg}</div>'
            f'<figcaption>{caption}</figcaption>{tools}'
            f'<ol class="sr">{items}</ol></figure>')


def svg_open(w: float, h: float, name: str, catalog: dict, links: bool = False) -> str:
    # A drawing is an image; one whose boxes are links is a group, or the links would sit inside an image.
    role = "group" if links else "img"
    return (f'<svg class="dg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" width="{w:.0f}" '
            f'height="{h:.0f}" role="{role}" aria-label="{esc(catalog[f"dg_{name}_caption"])}">'
            '<defs><marker id="dg-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            'orient="auto-start-reverse"><path class="dg-head" d="M0 0L10 5L0 10z"/></marker></defs>')


# ---- Sequence: actors in columns, the steps down.

def sequence(name: str, spec: dict, catalog: dict) -> tuple:
    actors = [words(a, catalog)[0] for a in spec["actors"]]
    n = len(actors)
    texts = []
    for step in spec["steps"]:
        if step[0] == "sep":
            texts.append(words(step[1], catalog))
        elif step[0] == "msg":
            texts.append(words(step[3], catalog))
        else:
            texts.append(words(step[3], catalog))
    gap = 190.0
    for step, (text, mono) in zip(spec["steps"], texts):
        if step[0] == "msg":
            gap = max(gap, (tw(text, mono) + 44) / max(1, abs(step[2] - step[1])))
        elif step[0] == "note" and step[2] > step[1]:
            gap = max(gap, (tw(text, mono) + 30) / (step[2] - step[1]) * 0.7)
    gap = min(gap, 380)
    margin = max(80.0, tw(max(actors, key=len), False) / 2 + 20)
    width = margin * 2 + gap * (n - 1)
    xs = [margin + i * gap for i in range(n)]
    out, alt = [], []
    y = 56.0
    body = []
    for n, (step, (text, mono)) in enumerate(zip(spec["steps"], texts)):
        k = lines_of(text)
        cls = "mono" if mono else ""
        opened = len(body)
        if step[0] == "sep":
            body.append(f'<line class="dg-sep" x1="12" y1="{y + 16:.0f}" x2="{width - 12:.0f}" y2="{y + 16:.0f}"/>')
            w = tw(text, mono) + 28
            body.append(f'<rect class="dg-sepbg" x="{width / 2 - w / 2:.0f}" y="{y + 4:.0f}" width="{w:.0f}" height="24" rx="12"/>')
            body.append(text_el(width / 2, y + 20, text, "dg-septext " + cls))
            alt.append(text)
            y += 36
        elif step[0] == "msg":
            a, b = xs[step[1]], xs[step[2]]
            dashed = len(step) > 4 and step[4]
            ay = y + k * LINE + 6
            direction = 1 if b > a else -1
            body.append(f'<line class="dg-msg{" dg-dash" if dashed else ""}" x1="{a + 3 * direction:.0f}" y1="{ay:.0f}" '
                        f'x2="{b - 3 * direction:.0f}" y2="{ay:.0f}" marker-end="url(#dg-arrow)"/>')
            body.append(text_el((a + b) / 2, y + 11, text, "dg-label " + cls))
            alt.append(f"{actors[step[1]]} → {actors[step[2]]}: " + text.replace("\n", " "))
            y += k * LINE + 20
        else:
            a, b = xs[step[1]], xs[step[2]]
            w = max(tw(text, mono) + 28, abs(b - a) + 56)
            cx = (a + b) / 2
            h = k * LINE + 12
            cx = min(max(cx, w / 2 + 4), width - w / 2 - 4)
            body.append(f'<rect class="dg-note" x="{cx - w / 2:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h}" rx="8"/>')
            body.append(text_el(cx, y + 18, text, "dg-notetext " + cls))
            alt.append(text.replace("\n", " "))
            y += h + 10
        # the step's drawing in a group of its own: the figure's stepper lights them one by one
        body[opened:] = [f'<g class="dg-step" data-step="{n}">', *body[opened:], "</g>"]
    height = y + 8
    head = [svg_open(width, height, name, catalog)]
    for x, label in zip(xs, actors):
        head.append(f'<line class="dg-life" x1="{x:.0f}" y1="38" x2="{x:.0f}" y2="{height - 6:.0f}"/>')
    for x, label in zip(xs, actors):
        w = tw(label, False) + 28
        head.append(f'<rect class="dg-actor" x="{x - w / 2:.0f}" y="6" width="{w:.0f}" height="30" rx="8"/>')
        head.append(text_el(x, 26, label, "dg-actortext"))
    return "".join(head + body) + "</svg>", alt


# ---- Graph: nodes on a grid, arrows between them.

def graph(name: str, spec: dict, catalog: dict) -> tuple:
    cols, rows = spec["cols"], spec["rows"]
    nodes = {}
    for key, (c, r, item, tone) in spec["nodes"].items():
        text, mono = words(item, catalog)
        nodes[key] = (c, r, text, mono, tone)
    longest = max(tw(text, mono) for _, _, text, mono, _ in nodes.values())
    nw = min(max(160.0, longest + 24), 250.0)
    labels = [words(e[2], catalog) for e in spec["edges"] if e[2]]
    gap = max([60.0] + [tw(t, m) + 24 for t, m in labels])
    gap = min(gap, 150.0)
    cw = nw + gap
    heights = {k: lines_of(v[2]) * LINE + 22 for k, v in nodes.items()}
    rh = max(heights.values()) + 46
    if any(e[2] and lines_of(words(e[2], catalog)[0]) > 1 for e in spec["edges"]):
        rh += 14
    width = cols * cw - gap + 24 + spec.get("pad", 0)
    height = rows * rh - 46 + 24 + 12

    def box(key):
        c, r, text, mono, tone = nodes[key]
        h = heights[key]
        x, y = 12 + c * cw, 12 + r * rh + (max(heights.values()) - h) / 2
        return x, y, nw, h

    out = [svg_open(width, height, name, catalog)]
    alt = []
    for key, (c, r, text, mono, tone) in nodes.items():
        x, y, w, h = box(key)
        out.append(f'<rect class="dg-node dg-{tone}" x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h}" rx="10"/>')
        out.append(text_el(x + w / 2, y + 20, text, "dg-nodetext " + ("mono" if mono else "")))
        alt.append(text.replace("\n", " "))
    for edge in spec["edges"]:
        a, b, label = edge[0], edge[1], edge[2]
        style = edge[3] if len(edge) > 3 else ""
        ax, ay, aw, ah = box(a)
        bx, by, bw, bh = box(b)
        cls = "dg-msg" + (" dg-dash" if style in ("bad", "back") else "") + (" dg-badline" if style == "bad" else "")
        acx, bcx = ax + aw / 2, bx + bw / 2
        acy, bcy = ay + ah / 2, by + bh / 2
        text, mono = words(label, catalog) if label else ("", False)
        if abs(acx - bcx) < 1:  # same column: vertical
            sy, ey = (ay + ah, by) if bcy > acy else (ay, by + bh)
            path = f"M{acx:.0f} {sy:.0f}V{ey:.0f}"
            lx, ly, anchor = acx + 8, (sy + ey) / 2 + 4, "start"
            if text and lx + tw(text, mono) > width - 4:  # no room on the right: the label goes on the left
                lx, anchor = acx - 8, "end"
        elif abs(acy - bcy) < 1:  # same row: horizontal
            sx, ex = (ax + aw, bx) if bcx > acx else (ax, bx + bw)
            path = f"M{sx:.0f} {acy:.0f}H{ex:.0f}"
            lx, ly, anchor = (sx + ex) / 2, acy - 8 - (lines_of(text) - 1) * LINE, "middle"
        else:  # elbow: out sideways, across, in sideways
            sx, ex = (ax + aw, bx) if bcx > acx else (ax, bx + bw)
            mx = (sx + ex) / 2
            path = f"M{sx:.0f} {acy:.0f}H{mx:.0f}V{bcy:.0f}H{ex:.0f}"
            lx, ly, anchor = mx + 8, (acy + bcy) / 2 + 4, "start"
        out.append(f'<path class="{cls}" d="{path}" fill="none" marker-end="url(#dg-arrow)"/>')
        if text:
            out.append(text_el(lx, ly, text, "dg-label dg-halo " + ("mono" if mono else ""), anchor))
        sa, sb = nodes[a][2].replace("\n", " "), nodes[b][2].replace("\n", " ")
        alt.append(f"{sa} → {sb}" + (f": {text.replace(chr(10), ' ')}" if text else ""))
    return "".join(out) + "</svg>", alt


# ---- Columns: groups of boxes, each linking to its section.

def columns(name: str, spec: dict, catalog: dict, sections: dict) -> tuple:
    per_row, cw = spec["per_row"], float(spec.get("cw", 196))
    tall = spec.get("tall", False)
    bh, step = (46.0, 52.0) if tall else (32.0, 38.0)
    groups = spec["cols"]
    rows = [groups[i:i + per_row] for i in range(0, len(groups), per_row)]
    width = per_row * cw + 12
    alt, body = [], []
    y = 8.0
    for row in rows:
        top = y
        tallest = max(len(items) for _, items in row)
        for c, (title, items) in enumerate(row):
            text, mono = words(title, catalog)
            text = text.replace("\n", " ")
            x = 6 + c * cw
            body.append(f'<rect class="dg-zone" x="{x:.0f}" y="{top:.0f}" width="{cw - 12:.0f}" '
                        f'height="{34 + tallest * step + 6:.0f}" rx="12"/>')
            body.append(text_el(x + (cw - 12) / 2, top + 22, text, "dg-zonetext " + ("mono" if mono else "")))
            parts = []
            for i, (item, ref) in enumerate(items):
                label, lmono = words(item, catalog)
                by = top + 34 + i * step
                anchor = sections.get(ref)
                box = f'<rect class="dg-node dg-dev" x="{x + 8:.0f}" y="{by:.0f}" width="{cw - 28:.0f}" height="{bh:.0f}" rx="8"/>'
                if tall:
                    box += (text_el(x + 18, by + 20, label, "dg-nodetext " + ("mono" if lmono else ""), "start")
                            + text_el(x + 18, by + 36, f"§ {ref}", "dg-ref", "start"))
                else:
                    box += (text_el(x + 18, by + 21, label, "dg-nodetext " + ("mono" if lmono else ""), "start")
                            + text_el(x + cw - 28, by + 21, f"§ {ref}", "dg-ref", "end"))
                body.append(f'<a href="#{anchor}">{box}</a>' if anchor else box)
                parts.append(f"{label} (§ {ref})")
            alt.append(f"{text}: " + ", ".join(parts))
        y = top + 34 + tallest * step + 6 + 12
    return svg_open(width, y, name, catalog, links=True) + "".join(body) + "</svg>", alt


def draw(name: str, catalog: dict, sections: dict | None = None) -> tuple:
    """(the SVG, the steps) of a figure."""
    spec = DIAGRAMS[name]
    if spec["kind"] == SEQUENCE:
        return sequence(name, spec, catalog)
    if spec["kind"] == GRAPH:
        return graph(name, spec, catalog)
    return columns(name, spec, catalog, sections or {})


def render(name: str, catalog: dict, sections: dict | None = None, src: str | None = None, stepper: bool = False) -> str:
    """The figure; `stepper` adds the buttons that walk through a sequence's steps (site/assets/figures.js)."""
    svg, alt = draw(name, catalog, sections)
    return figure(name, svg, alt, catalog, src, stepper and DIAGRAMS[name]["kind"] == SEQUENCE)


# The figures' colours and fonts outside the site, where there is no site.css (a README, a slide, a PNG):
# the brand's (library/boreale-site/assets/boreale.css), and the system's fonts, since a file loaded as an
# image loads no font.
STANDALONE_CSS = (
    "svg{font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:12.5px}"
    ".mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:12px}"
    ".dg-bg{fill:#0e1a33}text{fill:#e8eef7}.dg-head{fill:#a9b6cc}"
    ".dg-life{stroke:#22324f;stroke-width:1.5;stroke-dasharray:3 5}"
    ".dg-actor{fill:#0b1424;stroke:#00ffcc;stroke-width:1.5}.dg-actortext{font-weight:600}"
    ".dg-msg{stroke:#a9b6cc;stroke-width:1.5;fill:none}.dg-dash{stroke-dasharray:5 4}.dg-badline{stroke:#ff6b81}"
    ".dg-halo{paint-order:stroke;stroke:#0e1a33;stroke-width:4px;stroke-linejoin:round}"
    ".dg-note{fill:#0b1424;stroke:#6f7e9c;stroke-width:1}text.dg-notetext{fill:#a9b6cc}"
    ".dg-sep{stroke:#22324f;stroke-width:1;stroke-dasharray:2 4}.dg-sepbg{fill:#0b1424;stroke:#33bbff;stroke-width:1}"
    "text.dg-septext{fill:#33bbff;font-weight:600}"
    ".dg-node{fill:#0b1424;stroke:#22324f;stroke-width:1.5}.dg-dev{stroke:#00ffcc}.dg-srv{stroke:#33bbff}"
    ".dg-key{stroke:#8a5cff}.dg-bad{stroke:#ff6b81}.dg-zone{fill:none;stroke:#22324f;stroke-width:1.5}"
    "text.dg-zonetext{fill:#00ffcc;font-weight:600}text.dg-ref{fill:#6f7e9c;font-size:11px}"
)


def standalone(name: str, catalog: dict) -> str:
    """The figure as a file of its own: its SVG with its style, a title and the night behind it. Without the
    links of its boxes (they lead to a page of the site)."""
    svg, _ = draw(name, catalog)
    caption = esc(catalog[f"dg_{name}_caption"])
    width, height = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg).groups()
    svg = svg.replace("<defs>", f"<title>{caption}</title><style>{STANDALONE_CSS}</style><defs>", 1)
    svg = svg.replace("</defs>", f'</defs><rect class="dg-bg" width="{width}" height="{height}" rx="12"/>', 1)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + svg + "\n"


def export(directory: Path, check: bool = False) -> list:
    """Writes, or with `check` only compares, the English figures as files in `directory` (figures/ of the
    repository, which the README shows); the names of those out of date."""
    catalog = json.loads((ROOT / "site" / "i18n" / "en-US.json").read_text(encoding="utf-8"))
    stale = []
    for name in DIAGRAMS:
        target = directory / f"{name}.svg"
        text = standalone(name, catalog)
        if not target.exists() or target.read_text(encoding="utf-8") != text:
            stale.append(target.name)
            if not check:
                directory.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
    return stale


def keys() -> set:
    """Every catalog key the diagrams use."""
    found = {"dg_download_svg", "dg_download_png", "dg_step_prev", "dg_step_next", "dg_step_all"}
    for name, spec in DIAGRAMS.items():
        found |= {f"dg_{name}_caption"}
        items = list(spec.get("actors", []))
        items += [s[1] if s[0] == "sep" else s[3] for s in spec.get("steps", [])]
        items += [n[2] for n in spec.get("nodes", {}).values()]
        items += [e[2] for e in spec.get("edges", [])]
        if spec["kind"] == COLUMNS:
            for title, group in spec["cols"]:
                items += [title] + [label for label, _ in group]
        for item in items:
            found |= {"dg_" + k for k in KEY.findall(item)}
    return found


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3) or sys.argv[1] not in ("write", "check"):
        sys.exit("usage: python3 tools/diagrams.py write|check [directory]   (default: figures/)")
    where = Path(sys.argv[2]) if len(sys.argv) == 3 else ROOT / "figures"
    out_of_date = export(where, check=sys.argv[1] == "check")
    if sys.argv[1] == "check":
        if out_of_date:
            sys.exit(f"diagrams: {', '.join(out_of_date)} out of date: python3 tools/diagrams.py write")
        print(f"diagrams: {len(DIAGRAMS)} figures in {where.name}/, up to date")
    else:
        print(f"diagrams: {len(out_of_date)} of {len(DIAGRAMS)} figures written in {where.name}/")
