"""Gates: the director FAILS instead of shipping a weak video. Every failure is phrased for the planner.

Run on the work dir of a render (preflight = 8 stills + the every-frame audit; final = the full MP4):
  render      the renderer itself succeeded (its every-frame audit fails it on overlaps, captions on the guide...)
  layout      zero layout warnings (safe box, button column, text under the guide, overlaps)
  coverage    >= 60% of the usable frame (safe box minus the right button column) covered at every sample, and no
              single empty rectangle larger than 20% of it
  doodles     every drawing >= 250 px on its long side
  empty       no empty card / blank frame / empty verse page
  per_line    every line shows something new: a drawing of what it says, its own box media or verse card, or the
              whole diagram (drawings are the house style, not a quota)
  box_media   no media, no frame: every clip-box segment holds real loaded media (or a verse card / drawn heart),
              none failed to load; the box may be absent (no filler footage to fill a slot)
  diagram     a whole diagram is inside the safe area, uniformly scaled (its own aspect), its caption band inside
              the safe area and clear of it, and shown only while the narration is about it
  verses      every scripture reference / quote in the script is a typed verse card
  alignment   the script matches the recording (>= 85% of the script words heard)
  music       (final) the music bed is in the mix
  sfx         (final) sound effects are in the mix (pencil strokes, the record scratch)
"""
from __future__ import annotations

import json
from pathlib import Path

from kindled_iron.director.plan import director_types, quoted_spans, scripture_refs

MIN_COVER, MIN_DOODLE, MIN_ALIGN = 0.60, 250, 0.85
MAX_EMPTY = 0.20          # no single empty rectangle larger than 20% of the usable frame


def largest_empty(empty: list[list[bool]]) -> int:
    """Cells in the largest all-empty axis-aligned rectangle of a grid (histogram method)."""
    best, h = 0, [0] * (len(empty[0]) if empty else 0)
    for row in empty:
        h = [h[j] + 1 if row[j] else 0 for j in range(len(row))]
        stack: list[int] = []
        for j in range(len(h) + 1):
            cur = h[j] if j < len(h) else 0
            while stack and h[stack[-1]] >= cur:
                top = stack.pop()
                width = j if not stack else j - stack[-1] - 1
                best = max(best, h[top] * width)
            stack.append(j)
    return best


COMP_EMPTY = 0.30        # PROPOSED (report-only): no single empty region over 30 % of the usable frame ...
COMP_HOLD = 1.0          # ... and every third of the frame holds something; failing for >= 1 s = an unfinished frame


def composition(rects: list, safe: dict, empty_frac: float) -> tuple[bool, list[str]]:
    """PROPOSED replacement for the 60 % coverage floor (report-only until the owner approves it): a frame is a
    finished composition when every horizontal third of the usable frame (top / middle / bottom) holds a visible
    element (a drawing, the guide, a caption, the media box) and no single empty region is over COMP_EMPTY of it.
    Negative space between elements is allowed (drawing-led frames are rarely 60 % ink); a whole empty part is not."""
    y0, y1 = safe["y0"], safe["y1"]
    thirds = [(y0 + k * (y1 - y0) / 3, y0 + (k + 1) * (y1 - y0) / 3) for k in range(3)]
    names = ("top", "middle", "bottom")
    missing = [names[k] for k, (a, b) in enumerate(thirds)
               if not any(r[1] < b and r[3] > a and r[0] < safe["x1"] and r[2] > safe["x0"] for r in rects)]
    why = [f"nothing in the {m} third" for m in missing] + ([f"an empty region of {empty_frac:.0%}"] if empty_frac > COMP_EMPTY else [])
    return not why, why


def coverage(page_file: Path, duration: float, safe: dict, skip: list[tuple[float, float]], chrome=None,
             step: float = 0.5, sizes: dict | None = None) -> list[tuple[float, float]]:
    """(t, covered fraction, largest empty rectangle as a fraction) every `step` s: union of the visible elements'
    boxes over the usable frame (the safe box minus the button column).
    sizes (optional) collects every object's largest measured side while fully drawn."""
    sizes = {} if sizes is None else sizes
    from playwright.sync_api import sync_playwright
    from kindled_iron import render
    x0, x1, y0, y1 = safe["x0"], safe["x1"], safe["y0"], safe["y1"]
    col = safe["column"]
    xs, ys = list(range(x0 + 6, x1, 12)), list(range(y0 + 6, y1, 12))
    in_col = lambda x, y: col["x0"] <= x <= col["x1"] and col["y0"] <= y <= col["y1"]
    grid = [(x, y) for x in xs for y in ys if not in_col(x, y)]
    out = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=render.find_chrome(chrome), args=["--allow-file-access-from-files"])
        page = b.new_page(viewport={"width": 1080, "height": 1920})
        page.goto(Path(page_file).resolve().as_uri())
        page.wait_for_function("window.kiSeek !== undefined", timeout=60000)
        page.wait_for_timeout(1500)
        t = 0.25                                  # the first quarter second is the cut-in (drawings appearing)
        while t <= duration:
            if not any(a <= t <= c for a, c in skip):
                page.evaluate(f"window.kiSeek({t:.3f})")
                rects = page.evaluate("""() => { var o = window.kiRects(), out = [];
                    if (o.box) out.push(o.box);          // the page; its hand-drawn frame is the mediabox object below
                    ['guide', 'cap'].forEach(function (k) { var v = o[k]; if (v) out.push(v.left !== undefined ? [v.left, v.top, v.right, v.bottom] : v); });
                    document.querySelectorAll('.ki-obj').forEach(function (el) {
                      if (el.getAttribute('visibility') === 'hidden' || parseFloat(getComputedStyle(el).opacity) < 0.3) return;
                      var q = el.getBoundingClientRect(); if (q.width > 4 && q.height > 4) out.push([q.left, q.top, q.right, q.bottom]); });
                    return out; }""")
                for oid, w, h in page.evaluate("""() => Array.from(document.querySelectorAll('.ki-obj')).filter(function (el) {
                      return el.getAttribute('visibility') !== 'hidden' && parseFloat(getComputedStyle(el).opacity) > 0.9; })
                      .map(function (el) { var q = el.getBoundingClientRect(); return [el.id.slice(4), q.width, q.height]; })"""):
                    sizes[oid] = max(sizes.get(oid, 0), w, h)
                cov = lambda x, y: any(r[0] <= x <= r[2] and r[1] <= y <= r[3] for r in rects)
                hit = sum(1 for (x, y) in grid if cov(x, y))
                empty = [[not in_col(x, y) and not cov(x, y) for x in xs] for y in ys]
                ef = largest_empty(empty) / len(grid)
                out.append((round(t, 2), round(hit / len(grid), 3), round(ef, 3), composition(rects, safe, ef)[1]))
            t = round(t + step, 3)
        b.close()
    return out


def run(work: Path, scene: dict, plan: dict, lines: list[str], cat: dict, align_ratio: float, final: bool,
        render_error: str | None, meta_path: Path | None = None, chrome=None) -> dict:
    res: dict[str, dict] = {}

    def gate(name: str, ok: bool, detail, fix: str = "") -> None:
        res[name] = {"ok": bool(ok), "detail": detail, **({"fix": fix} if not ok and fix else {})}

    gate("render", render_error is None, render_error or "ok", "the renderer failed: " + (render_error or ""))
    checks = json.loads((work / "checks.json").read_text()) if (work / "checks.json").exists() else []
    checks = [c for c in checks if not c["issue"].startswith("SPARSE")]
    gate("layout", not checks, checks[:20], "layout warnings: " + "; ".join(f"{c['issue']} at {c['from']:.1f}s" for c in checks[:8]))
    audit = json.loads((work / "audit.json").read_text()) if (work / "audit.json").exists() else {"issues": []}
    gate("audit", not audit.get("issues"), audit.get("issues", [])[:20],
         "every-frame audit: " + "; ".join(f"{i['issue']} at {i['from']:.1f}s" for i in audit.get("issues", [])[:8]))

    types = director_types(cat)
    small, empty, per_line = [], [], []
    for b, beat in enumerate(scene["beats"]):
        draws = [e for e in beat["events"] if e.get("do") == "draw"]
        new_draw = [e for e in draws if e.get("type") in types or e.get("doodle") in types]
        small += []                                   # sizes are measured on the page (coverage pass)
        for e in draws:
            if e.get("type") in ("frame", "popup") and not e.get("text"):
                empty.append(f"line {b + 1}: empty {e['type']} card")
        dg = (scene.get("director") or {}).get("diagram")
        covered = dg and any(s_["line"] == b + 1 for s_ in dg.get("sentences", []))
        own_box = any(e.get("box") in ("clip", "media", "verse", "split", "heart", "diagram") for e in beat["events"])
        if not new_draw and not covered and not own_box:
            per_line.append(f"line {b + 1}: nothing new on screen")
    gate("doodles", not small, small, "drawings too small: " + "; ".join(small))
    segs = json.loads((work / "box_segments.json").read_text()) if (work / "box_segments.json").exists() else []
    for s in segs:
        if s["kind"] == "verse" and any(not p.get("text", "").strip() for p in s.get("pages", [])):
            empty.append(f"verse {s.get('ref')}: an empty page")
    gate("empty", not empty, empty, "; ".join(empty))
    gate("per_line", not per_line, per_line, "; ".join(per_line) + ": show each line's idea (a drawing of what it says, "
         "or media that truly shows it)")
    failed = json.loads((work / "media_failures.json").read_text()) if (work / "media_failures.json").exists() else []
    hollow = [f"{s['kind']} at {s['t0']:.1f}s" for s in segs if s["kind"] in ("clip", "media", "split", "diagram")
              and not (s.get("geom") or {}).get("w")]
    gate("box_media", not failed and not hollow,
         f"{sum(1 for s in segs if s['kind'] in ('clip', 'media', 'split'))} clip/meme segment(s), "
         f"{sum(1 for s in segs if s['kind'] == 'diagram')} diagram(s)",
         "the clip box shows a frame without media: " + "; ".join([f"{f} failed to load" for f in failed] + hollow) +
         " (give a media item that exists, or leave the line without box media)")
    from kindled_iron.render import SAFE as _SAFE
    dg_problems = diagram_problems(scene, _SAFE)
    gate("diagram", not dg_problems, dg_problems or ((scene.get("director") or {}).get("diagram") or {}).get("readability")
         or "no diagram", "; ".join(dg_problems))
    want = [(i + 1, r) for i, t in enumerate(lines) for r in scripture_refs(t)] + \
        [(i + 1, q) for i, t in enumerate(lines) for q in quoted_spans(t) if not scripture_refs(t) and
         any((L.get("verse") or {}) for L in plan["lines"][i:i + 1])]
    have = {(s.get("ref") or "").lower() for s in segs if s["kind"] == "verse"}
    missing = []
    for n, r in want:
        if not any(r.lower().split(":")[0] in h for h in have):
            missing.append(f"line {n}: {r} is not on a typed verse card")
    gate("verses", not missing, missing or f"{len(have)} verse card(s)", "; ".join(missing))
    gate("alignment", align_ratio >= MIN_ALIGN, f"{align_ratio:.0%} of the script words heard in the recording",
         "the script does not match the recording")
    page = work / "index.html"
    if page.exists() and render_error is None:
        from kindled_iron.render import SAFE
        html = page.read_text(encoding="utf-8")
        data = json.loads(html.split("window.KI_DATA = ", 1)[1].split(";</script>", 1)[0])
        # the freeze empties the board on purpose (zoom), then the camera returns (0.45 s) and the board refills
        # (the pencil draw-on, 0.6 s): that beat is not measured
        fz = [(e["t"], e["t"] + e.get("dur", 1.0) + 0.45 + 1.0) for e in data["events"] if e.get("do") == "freeze"]
        seen: dict = {}
        cov = coverage(page, data["duration"], SAFE, fz, chrome, sizes=seen)
        tiny = [f"{oid} is {px:.0f} px" for oid, px in seen.items() if oid.split("_")[0][1:].isdigit() and px < MIN_DOODLE]
        gate("doodles", not small and not tiny, small + tiny, "drawings too small (under 250 px): " + "; ".join(small + tiny))
        low = [(t, c) for t, c, _, _ in cov if c < MIN_COVER]
        holes = [(t, e) for t, _, e, _ in cov if e > MAX_EMPTY]
        # PROPOSED replacement metric, reported beside the gate, never counted in _passed until approved
        bad = [(t, w) for t, _, _, w in cov if w]
        runs: list = []
        for t, w in bad:
            if runs and t - runs[-1][1] <= 0.51:
                runs[-1][1] = t
                runs[-1][2] |= set(w)
            else:
                runs.append([t, t, set(w)])
        unfinished = [(a, b, sorted(w)) for a, b, w in runs if b - a + 0.5 >= COMP_HOLD]
        res["_proposed_composition"] = {"ok": not unfinished, "report_only": True,
                                        "unfinished": [f"{a:.1f}-{b + 0.5:.1f}s: {', '.join(w)}" for a, b, w in unfinished[:20]],
                                        "rule": f"every third of the usable frame holds something and no empty region over "
                                                f"{COMP_EMPTY:.0%}, failing for >= {COMP_HOLD:.0f} s = unfinished"}
        gate("coverage", not low and not holes,
             {"min": min((c for _, c, _, _ in cov), default=0), "max_empty": max((e for _, _, e, _ in cov), default=0),
              "low_samples": low[:60], "empty_samples": holes[:60], "samples": len(cov)},
             (f"the frame is under {MIN_COVER:.0%} covered at " + ", ".join(f"{t:.1f}s ({c:.0%})" for t, c in low[:6]) + "; "
              if low else "") +
             (f"an empty region over {MAX_EMPTY:.0%} of the frame at " + ", ".join(f"{t:.1f}s ({e:.0%})" for t, e in holes[:6]) + "; "
              if holes else "") + "use bigger drawings (a wide or square illustration above the guide, a tall one beside him)")
    if final:
        meta = json.loads(meta_path.read_text()) if meta_path and meta_path.exists() else {}
        music = (meta.get("music") or {}).get("source", "none")
        gate("music", music != "none", music, "no music in the mix (private music/theme_1.mp3 missing?)")
        gate("sfx", (meta.get("sfx_cues") or 0) >= 2, meta.get("sfx_cues"), "no sound effects in the mix")
    res["_passed"] = all(v["ok"] for k, v in res.items() if not k.startswith("_"))
    return res


def diagram_problems(scene: dict, safe: dict) -> list[str]:
    """Static checks of a whole-diagram presentation (the per-frame audit checks the rendered frames)."""
    dg = (scene.get("director") or {}).get("diagram")
    if not dg:
        return []
    out = []
    x, y, w, h = dg["fit"]["rect"]
    col = safe["column"]
    if x < safe["x0"] or y < safe["y0"] or x + w > safe["x1"] or y + h > safe["y1"]:
        out.append(f"the diagram {dg['file']} leaves the safe area ({x}, {y}, {w}x{h})")
    if y + h > col["y0"] and x + w > col["x0"]:
        out.append(f"the diagram {dg['file']} reaches into the right button column")
    size = dg.get("size") or (dg["fit"].get("size"))
    if size and abs(w / h - size[0] / size[1]) > 0.01:
        out.append(f"the diagram {dg['file']} is not scaled uniformly ({size} shown as {w}x{h})")
    cw = next(iter(scene.get("caption_windows") or []), None)
    if cw:
        cx0, cx1 = cw["x"] - cw["w"] / 2, cw["x"] + cw["w"] / 2
        if cx0 < safe["x0"] or cx1 > col["x0"] or cw["y"] + 100 > safe["y1"]:
            out.append("the caption band beside the diagram leaves the safe area")
        if cw["y"] < y + h and cx0 < x + w and x < cx1:
            out.append("the caption band overlaps the diagram")
    if dg["t1"] - dg["t0"] > 30.5:
        out.append(f"the diagram stays {dg['t1'] - dg['t0']:.0f} s (max 30 s)")
    return out


def errors(res: dict) -> list[str]:
    return [v.get("fix") or f"{k} failed: {v['detail']}" for k, v in res.items() if not k.startswith("_") and not v["ok"]]
