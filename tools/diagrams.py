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
import re

# The section a figure goes under: the heading's number in SPEC.md (and in its translations).
WHERE = {
    "connect": "4",
    "features": "4.2",
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
            ("msg", 1, 0, "202 …  then  200 {token: et_…}", True),
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


def figure(name: str, svg: str, steps: list, catalog: dict) -> str:
    caption = esc(catalog[f"dg_{name}_caption"])
    items = "".join(f"<li>{esc(s)}</li>" for s in steps)
    return (f'<figure class="diagram" id="diagram-{name.replace("_", "-")}">'
            f'<div class="dg-scroll" tabindex="0" role="region" aria-label="{caption}">{svg}</div>'
            f'<figcaption>{caption}</figcaption>'
            f'<ol class="sr">{items}</ol></figure>')


def svg_open(w: float, h: float, name: str, catalog: dict) -> str:
    return (f'<svg class="dg" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" width="{w:.0f}" '
            f'height="{h:.0f}" role="img" aria-label="{esc(catalog[f"dg_{name}_caption"])}">'
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
    for step, (text, mono) in zip(spec["steps"], texts):
        k = lines_of(text)
        cls = "mono" if mono else ""
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
    width = cols * cw - gap + 24
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
    return svg_open(width, y, name, catalog) + "".join(body) + "</svg>", alt


def render(name: str, catalog: dict, sections: dict | None = None) -> str:
    spec = DIAGRAMS[name]
    if spec["kind"] == SEQUENCE:
        svg, alt = sequence(name, spec, catalog)
    elif spec["kind"] == GRAPH:
        svg, alt = graph(name, spec, catalog)
    else:
        svg, alt = columns(name, spec, catalog, sections or {})
    return figure(name, svg, alt, catalog)


def keys() -> set:
    """Every catalog key the diagrams use."""
    found = set()
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
