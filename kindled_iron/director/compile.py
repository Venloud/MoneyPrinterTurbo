"""Shot plan -> render-ready scene JSON. All coordinates come from here (zones in catalog.json + measured sizes).

Layout (fixed, never overlapping): the clip box at the top, the caption band under it, the drawing area in the
middle, the guide lane at the bottom. Drawings sit only in the drawing area, so the guide (below it) never walks
through them; meme pop-ups sit in the guide lane next to the guide while he stands at an outer spot.

Timing comes from the real narration: `words` are the recording's word timings aligned to the script (the same
alignment the renderer makes), so walks, freezes and pop-ups are scheduled around each other here, and every
event is anchored to a spoken word ("word#n+0.3") so the renderer resolves it on its own alignment.
"""
from __future__ import annotations

import itertools
import math
import re

from kindled_iron import scripture
from kindled_iron.director import actions
from kindled_iron.director.plan import director_types, key, quoted_spans

WALK_SPEED = 280                # px/s, the guide's natural pace at this size
WALK_EVERY = (2, 3)             # lines between walks, alternating
FACE_OF = {"happy": "crying_laughing", "curious": "thinking", "thinking": "thinking", "surprised": "surprised",
           "shocked": "shocked", "awe": "mind_blown", "mind_blown": "mind_blown", "focused": "thinking",
           "puzzled": "puzzled", "confused_math": "confused_math", "side_eye": "side_eye", "wait_what": "wait_what",
           "crying_laughing": "crying_laughing"}
POP_CARD = {"w": 380, "dur": 1.2}
POP_CLEAR, POP_BACK = 0.12, 0.02          # a drawing beside the card goes just as it appears, comes back as it goes
POP_GOD_GAP, POP_MIN_GAP = 0.45, 3.05      # effects.py drops a reaction within 0.4 s of "God" or 3 s of the last
SCRATCH = "sfx/record_scratch.mp3"        # the owner's record scratch (private repo); the sound library has none
FREEZE = {"dur": 1.0, "zoom": 1.45, "after": 0.45}   # the camera needs ~0.35 s to come back after the freeze
SHOULDER_Y = 1110               # set from the measured guide (his top + 122) in compile_scene
FILL = 0.97                     # a drawing fills its slot to this share (the measured size includes its strokes)
MIN_LABEL_SCALE = 0.72          # a labeled drawing smaller than this makes its labels too small to read on a phone


class CompileError(Exception):
    pass


def _occ(words: list[dict], w: str, after: float = -1.0) -> tuple[int, dict]:
    """(nth, word) of the first occurrence of w (renderer matching) starting at or after `after` seconds."""
    k = key(w)
    n = 0
    for x in words:
        if key(x["word"]) == k:
            n += 1
            if x["start"] >= after - 1e-6:
                return n, x
    raise CompileError(f"word {w!r} is not in the line")


def _anchor(words: list[dict], w: str, off: float = 0.0, after: float = -1.0) -> tuple[str, float]:
    n, x = _occ(words, w, after)
    return f"{key(w)}#{n}{off:+.2f}", round(x["start"] + off, 3)


def _at_time(words: list[dict], t: float) -> str:
    """An anchor for an absolute time: the last word starting before t, plus the offset."""
    best = words[0]
    for x in words:
        if x["start"] <= t:
            best = x
    n = sum(1 for x in words[: words.index(best) + 1] if key(x["word"]) == key(best["word"]))
    return f"{key(best['word'])}#{n}{t - best['start']:+.2f}"


def _verse_text(v: dict, line: str) -> tuple[str, bool]:
    """(card text, spoken) for a verse request: the quoted words when the line quotes the WEB, else the WEB text."""
    if v.get("quoted"):
        for q in quoted_spans(line):
            q = q.strip().rstrip(",")
            ok, _ = scripture.check(v["ref"], q)
            if ok:
                return q, True
    return scripture.verse_text(v["ref"]).strip().strip("“”\"").strip(), False


def _split_word(text: str, limit: int = 95) -> str | None:
    """Long verses go on two pages: split after the punctuation nearest the middle."""
    if len(text) <= limit:
        return None
    toks, mid, best, pos = text.split(), len(text) / 2, None, 0
    for i, t in enumerate(toks[:-1]):
        pos += len(t) + 1
        if re.search(r"[,;:.]$", t) and (best is None or abs(pos - mid) < abs(best[1] - mid)):
            best = (i, pos)
    if best is None:
        best = (len(toks) // 2, mid)
    w = re.sub(r"[^\w']", "", toks[best[0]])
    return w or None


def _fit(obj: dict, slot: tuple[float, float, float, float], strict: bool = True):
    """Scale + position (x, y) so the measured drawing fills its slot (its long side never under 254 px, a margin
    over the 250 px gate). strict=False returns None instead of raising."""
    x0, y0, x1, y1 = slot
    w, h = obj["size"]
    cx, cy = obj.get("center", [0, 0])
    s = min((x1 - x0) * FILL / w, (y1 - y0) * FILL / h, 2.4)      # room for the strokes' width
    if max(w, h) * s < 254:
        if not strict:
            return None
        raise CompileError(f"a {obj.get('_name')} drawing would be under 250 px in its slot")
    return round(s, 3), round((x0 + x1) / 2 - cx * s, 1), round((y0 + y1) / 2 - cy * s, 1)


def _draw_fields(d: dict, types: dict) -> dict:
    """The renderer fields of a planned drawing: a library doodle (kindled_iron/doodles) becomes the runtime's
    `doodle` primitive with its strokes and the labels in its slots; a built-in drawing passes its fields."""
    if types.get(d["type"], {}).get("doodle"):
        from kindled_iron.director.catalog import doodle_spec
        return doodle_spec(d["type"], d.get("fields") or {})
    return {"type": d["type"], **(d.get("fields") or {})}


def _tip_ok(spot: float, target: tuple[float, float], reach: float) -> bool:
    """Pointing: the hand ends ~reach px sideways toward the target (also when the target is nearly above him:
    the renderer still points sideways); it must stay in the usable frame, left of the button column."""
    side = 1 if target[0] >= spot else -1
    return 125 <= _arm_tip(spot, target, reach)[0] <= 775 and 125 <= spot + side * reach <= 775


from kindled_iron.director.catalog import ZONES as _Z

_LY = (_Z["lane"]["y0"], _Z["lane"]["y1"])
LANES = {"left": (125, _LY[0], 410, _LY[1]), "right": (490, _LY[0], 775, _LY[1])}   # clear of his swinging arms at 340 / 560


def _lane_slot(spot: float, G: dict, full: bool = False) -> tuple[float, float, float, float] | None:
    """The drawing slot beside the guide, on the far side from him. The two side slots are fixed, so a walk
    between the two spots on one side never passes through the drawing on the other side. full=True: the whole
    height from under the (middle) caption down to the safe box's bottom (a tall drawing beside him)."""
    slot = LANES["left"] if spot >= 540 else LANES["right"]
    body = (spot - G["half_width"] - 20, spot + G["half_width"] + 20)
    if not (body[1] < slot[0] or body[0] > slot[2]):
        return None
    return (slot[0], _Z["caption"]["y"] + _Z["caption"]["h"] + 15, slot[2], slot[3]) if full else slot


def _near_top(lane: tuple) -> tuple[float, float, float, float]:
    """The band above the guide's head on his own side (next to a full-height side drawing)."""
    d = _Z["draw"]
    return (lane[2] + 12, d["y0"], 775, d["y1"]) if lane[0] < 300 else (125, d["y0"], lane[0] - 12, d["y1"])


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _LANE_CARD(spot: float, G: dict) -> tuple[float, float, float, float]:
    """Where a meme card beside the guide at this spot goes (its box, for the timeline check)."""
    ls = _pop_slot(spot, G)
    cx = (ls[0] + ls[2]) / 2
    return (cx - _Z["pop"]["w"] / 2, ls[1], cx + _Z["pop"]["w"] / 2, ls[3])


def _pop_slot(spot: float, G: dict) -> tuple[float, float, float, float]:
    """A meme card beside the guide: he keeps his arms down while it is up, so only his body needs room."""
    half = G["half_width"] + 30
    right, left = (spot + half, _LY[0], 775, _LY[1]), (125, _LY[0], spot - half, _LY[1])
    return max((right, left), key=lambda r: r[2] - r[0])


def _arm_tip(spot: float, target: tuple[float, float], reach: float) -> tuple[float, float]:
    """Measured: a pointing arm reaches ~reach px sideways whatever the target's height (the elbow bends out),
    unless the target is straight above him."""
    dx = target[0] - spot
    if abs(dx) < 40:
        return spot, SHOULDER_Y - reach
    return spot + reach * (1 if dx > 0 else -1), SHOULDER_Y


def _inside(pt: tuple[float, float], rect, pad: float = 18) -> bool:
    """The audit compares the guide's whole bounding box: an arm stretched over a lane drawing's columns touches
    it whatever the arm's height, so only x counts."""
    return rect[0] - pad <= pt[0] <= rect[2] + pad


def _path_hits(walk: tuple, rects: list, G: dict) -> bool:
    """Does the guide's body sweep over any of these drawings while he walks?"""
    a, b = sorted(walk[:2])
    lo, hi = a - G["half_width"] - 10, b + G["half_width"] + 10
    return any(r[0] <= hi and r[2] >= lo for r in rects)


def _walks_into(walk: tuple, side) -> bool:
    """Does a walk head toward the side where the lane drawing is?"""
    if side is None:
        return False
    return (walk[1] - walk[0]) * side > 0


def _spans(tl: dict) -> dict:
    """id -> (rect, t_on, [(shown_from, shown_to)]) from the draw and fade times (a fade takes 0.1 s)."""
    out = {}
    for did, (rect, t_on) in tl["draw"].items():
        ev = sorted((t, op) for t, ids, op in tl["fade"] if did in ids and t >= t_on - 1e-6)
        sp, on, start = [], True, t_on
        for t, op in ev:
            if on and op == 0:
                sp.append((start, t + 0.1))
                on = False
            elif not on and op == 1:
                on, start = True, t
        if on:
            sp.append((start, 1e9))
        out[did] = (rect, t_on, sp)
    return out


def _found(tl: dict, eps: float = 0.06) -> list[dict]:
    sp, out = _spans(tl), []
    for did, (rect, _, spans) in sp.items():
        for crect, c0, c1 in tl["cards"]:
            if _overlap(rect, crect):
                for s0, s1 in spans:
                    a, b = max(s0, c0), min(s1, c1)
                    if b - a > eps:
                        out.append({"kind": "card", "id": did, "a": a, "b": b, "c0": c0, "c1": c1})
    ids = sorted(sp)
    for x, did in enumerate(ids):
        for oid in ids[x + 1:]:
            if not _overlap(sp[did][0], sp[oid][0]):
                continue
            for s0, s1 in sp[did][2]:
                for o0, o1 in sp[oid][2]:
                    a, b = max(s0, o0), min(s1, o1)
                    if b - a > eps:
                        out.append({"kind": "overlap", "id": did, "other": oid, "a": a, "b": b,
                                    "first": did if s0 < o0 else oid if o0 < s0 else None,
                                    "later_from": max(s0, o0)})
    return out


def _say(c: dict) -> str:
    if c["kind"] == "card":
        return f"DRAWING {c['id']} UNDER MEME at {c['a']:.2f}-{c['b']:.2f}s"
    return f"{c['id']} overlaps {c['other']} at {c['a']:.2f}-{c['b']:.2f}s"


def conflicts(tl: dict, eps: float = 0.06) -> list[str]:
    """The compiled timeline checked the way the renderer's per-frame audit checks it, before any render: a drawing
    on screen under a meme card, or two drawings on screen over each other. tl = {"draw": {id: (rect, t_on)},
    "fade": [(t, ids, opacity)], "cards": [(rect, t0, t1)]}. Fades take 0.1 s; the overlap must last > eps."""
    return [_say(c) for c in _found(tl, eps)]


def _beat_at(words: list[list[dict]], t: float) -> int:
    b = 0
    for k, ws in enumerate(words):
        if ws and ws[0]["start"] - 0.6 <= t:
            b = k
    return b


def resolve_conflicts(tl: dict, beats: list[dict], words: list[list[dict]]) -> tuple[list[str], list[str]]:
    """Fix what the timeline check finds, in code (no AI call): a drawing under a meme card makes way for it (faded
    just before, back after it) or, when it would appear under it, appears after it; of two drawings over each
    other the one shown first is cleared just before the other appears. -> (notes, what is left: a reason to reject
    the plan before rendering)."""
    notes: list[str] = []

    def fade(t, did, op):
        b = _beat_at(words, t)
        beats[b]["events"].append({"at": _at_time(words[b], t), "do": "fade", "ids": [did], "opacity": op, "dur": 0.1})
        tl["fade"].append((t, [did], op))

    for _ in range(4 * len(tl["draw"]) + 4):         # every fix removes one conflict; bounded either way
        found = _found(tl)
        if not found:
            return notes, []
        c = found[0]
        sp = _spans(tl)
        if c["kind"] == "card":
            rect, t_on, spans = sp[c["id"]]
            if t_on >= c["c0"] - 0.25:                     # it would appear under the card: after it instead
                new_t = round(c["c1"] + 0.05, 3)
                for bt in beats:
                    for e in list(bt["events"]):
                        if e.get("do") == "draw" and e.get("id") == c["id"]:
                            bt["events"].remove(e)
                            b = _beat_at(words, new_t)
                            beats[b]["events"].append(dict(e, at=_at_time(words[b], new_t)))
                tl["draw"][c["id"]] = (rect, new_t)
                notes.append(f"{c['id']} now appears after the meme card ({new_t:.2f}s)")
            else:
                fade(round(c["c0"] - 0.2, 3), c["id"], 0)
                if any(s0 <= c["c1"] < s1 for s0, s1 in spans):
                    fade(round(c["c1"], 3), c["id"], 1)
                notes.append(f"{c['id']} makes way for the meme card at {c['c0']:.2f}s")
        else:
            if not c["first"]:
                break                                       # both appear at once: no order to fix it by
            t_out = round(max(0.0, c["later_from"] - 0.05), 3)
            back = [f for f in tl["fade"] if c["first"] in f[1] and f[2] == 1 and t_out - 0.4 <= f[0] <= c["later_from"] + 0.06]
            if back:                                        # it was coming back (after a meme card) just as the
                for f in back:                              # other appears: it stays cleared instead
                    tl["fade"].remove(f)
                    for b, bt in enumerate(beats):
                        for e in list(bt["events"]):
                            if e.get("do") == "fade" and e.get("opacity") == 1 and e.get("ids") == f[1] and \
                                    abs(_anchor_time(words[b], e["at"]) - f[0]) < 0.02:
                                bt["events"].remove(e)
                notes.append(f"{c['first']} stays cleared at {c['later_from']:.2f}s (the next drawing takes its place)")
            else:
                fade(t_out, c["first"], 0)
                notes.append(f"{c['first']} cleared at {c['later_from']:.2f}s (the next drawing covers its place)")
    return notes, conflicts(tl)


def _anchor_time(words: list[dict], at) -> float:
    """The absolute time of an anchor ("word#n+0.25") written by _at_time / _anchor within its line's words."""
    if isinstance(at, (int, float)):
        return float(at)
    m = re.match(r"(.+)#(\d+)([+-][\d.]+)$", str(at))
    if not m:
        return -1.0
    w, n, off = m.group(1), int(m.group(2)), float(m.group(3))
    hits = [x for x in words if key(x["word"]) == w]
    return hits[n - 1]["start"] + off if len(hits) >= n else -1.0


def compile_scene(plan: dict, lines: list[str], words: list[list[dict]], cat: dict, media: list[list[dict]],
                  meta: dict, measure=None, diagram: dict | None = None) -> tuple[dict, list[dict]]:
    """-> (scene, frames). frames = the 8 review stills: [{beat, at, line}].
    measure(specs) -> {id: {size, center}}: the drawings' real boxes with their own labels (Chrome); without it
    the catalog's sample sizes are used (offline tests).
    diagram (diagram.select + diagram.fit): a whole diagram shown from t0 to t1. While it is up nothing else is drawn
    where it or its caption band is (drawings move after it, or are left out when their line ends first), no clip,
    meme card or freeze happens, and the guide steps out when it covers him and comes back when it goes."""
    Z, G = cat["zones"], cat["guide"]
    global SHOULDER_Y
    SHOULDER_Y = G["top"] + 122                 # measured: shoulders 122 px under the top of his head
    scene_notes = []
    types = director_types(cat)
    real = {}
    if measure:
        specs = [{"id": f"l{i + 1}_{d['type']}{j}", **_draw_fields(d, types)}
                 for i, L in enumerate(plan["lines"]) for j, d in enumerate(L["drawings"][:3])]
        real = measure(specs)
    spots = Z["guide"]["spots"]
    outer = (spots[0], spots[-1])
    reach = G["reach_side"]
    shrug_ok = [s for s in spots if s - G["shrug_half_width"] >= 120 and s + G["shrug_half_width"] <= 778]
    dz = Z["draw"]
    dx0, dx1 = dz["x0"], min(dz["x1"], 775)
    slots1 = [(dx0, dz["y0"], dx1, dz["y1"])]
    mid = (dx0 + dx1) / 2
    slots2 = [(dx0, dz["y0"], mid - 5, dz["y1"]), (mid + 5, dz["y0"], dx1, dz["y1"])]
    n_lines = len(lines)
    P = plan["lines"]
    freeze = plan.get("freeze") or {}
    ov = (diagram["t0"], diagram["t1"]) if diagram else None
    OBST: list = []                              # the diagram and its caption band while it is up
    hide_guide = False
    if diagram:
        x_, y_, w_, h_ = diagram["fit"]["rect"]
        cp = diagram["fit"]["caption"]
        OBST = [(x_, y_, x_ + w_, y_ + h_), (cp["x"] - cp["w"] / 2, cp["y"] - 6, cp["x"] + cp["w"] / 2, cp["y"] + 112)]
        hide_guide = y_ + h_ > G["top"] - 10      # it reaches down over the guide: he steps out while it is up

    def under_diagram(rect, t: float, t_end: float | None = None) -> bool:
        """Would this drawing be on screen where the diagram (or its caption band) is while it is up?"""
        return bool(ov) and any(_overlap(rect, o) for o in OBST) and t < ov[1] + 0.05 and (t_end or 1e9) > ov[0] - 0.05
    BOX = (Z["box"]["x"] - Z["box"]["w"] / 2, Z["box"]["y"] - Z["box"]["h"] / 2,
           Z["box"]["x"] + Z["box"]["w"] / 2, Z["box"]["y"] + Z["box"]["h"] / 2)
    # a line with no clip-box media: the captions stay at the middle and the drawings get the whole space above them,
    # from the top of the safe area down to the caption (OPEN)
    OPEN = (dx0, 190, dx1, dz["y1"])
    has_box = [bool([b for b in media[i] if not b.get("skip")]) or bool(L.get("verse")) for i, L in enumerate(P)]
    box_at: list = []                            # when each line's own box media / verse card arrives
    for i, L in enumerate(P):
        ts = [_occ(words[i], b["word"])[1]["start"] - 0.15 for b in media[i] if not b.get("skip")]
        ts = [t for t in ts if not (ov and ov[0] - 0.2 <= t + 0.15 < ov[1])]
        if L.get("verse"):
            ts.append(_occ(words[i], L["verse"]["word"])[1]["start"] - 0.4)
        box_at.append(min(ts) if ts else None)
    LEAD = (dx0, 190, dx1, dz["y0"] - 15)        # a late-media line opens with a drawing where the box will be (above
                                                 # the band, never over it), until the media comes
    late = [b is not None and b - words[i][0]["start"] > 1.2 and not (ov and words[i][0]["start"] < ov[1])
            for i, b in enumerate(box_at)]
    open_line = [not has_box[i] and not (ov and words[i][-1]["end"] < ov[1] + 1.0)   # (not a line the diagram covers)
                 for i in range(len(P))]

    # ---------------- times we must keep clear of walks: pop cards, verse typing, the freeze
    pop_t, verse_t, freeze_t = {}, {}, None
    god = [w["start"] for ws in words for w in ws if key(w["word"]) == "god"]
    for i, L in enumerate(P):
        if L.get("pop"):
            # the renderer's reaction rules (effects.apply_reaction_rules), applied here so a card is never
            # dropped at render time: not within 0.4 s of the word God, 3 s after the previous card
            t = _occ(words[i], L["pop"]["word"])[1]["start"]
            near = [g for g in god if abs(t - g) < POP_GOD_GAP]
            if near:
                later = [w for w in words[i] if w["start"] >= max(near) + POP_GOD_GAP and key(w["word"]) != "god"
                         and all(abs(w["start"] - g) >= POP_GOD_GAP for g in god)]
                if later:
                    t = later[0]["start"]
                    scene_notes.append(f"line {i + 1}: pop-up moved off the word God to {later[0]['word']!r}")
                else:
                    t = None
            if t is not None and ov and ov[0] - 0.3 <= t <= ov[1] + 0.3:
                t = None                              # the diagram is up: no meme card over it
                scene_notes.append(f"line {i + 1}: pop-up left out (the diagram is on screen then)")
            if t is not None and pop_t and t - pop_t[max(pop_t)] < POP_MIN_GAP:
                t = None
            if t is None:
                P[i] = dict(L, pop=None)
                scene_notes.append(f"line {i + 1}: pop-up dropped (too close to the word God or the previous card)")
            else:
                pop_t[i] = t
        if L.get("verse"):
            v = L["verse"]
            verse_t[i] = (_occ(words[i], v["word"])[1]["start"] - 0.4, words[i][-1]["end"] + 1.4)
    if freeze.get("line"):
        fi = freeze["line"] - 1
        freeze_t = (fi, _occ(words[fi], freeze["word"])[1]["start"])
        if ov and ov[0] - 0.5 <= freeze_t[1] <= ov[1] + 0.2:
            scene_notes.append(f"line {fi + 1}: freeze left out (the diagram is on screen then)")
            freeze_t, freeze = None, {}

    # ---------------- guide route: a walk every 2-3 lines, outer spots for pop-ups
    cur = spots[3]
    route, walks, nxt, k = [], {}, WALK_EVERY[0], 0
    for i in range(n_lines):
        t0 = words[i][0]["start"]
        # a pop-up needs him on an outer spot: get there a line early, so a pop early in its line never fails
        need_outer = (i in pop_t or (i + 1) in pop_t) and cur not in outer
        due = i >= nxt and i < n_lines - 1
        if need_outer or due:
            if need_outer:
                dest = min(outer, key=lambda s: abs(s - cur))
            else:
                # mostly steps within one side (the lane drawing on the far side stays clear of him); every
                # third walk crosses to the other side
                right = [x for x in spots if x >= 540]
                left = [x for x in spots if x < 540]
                mine, other = (right, left) if cur >= 540 else (left, right)
                inner = min(mine, key=lambda x: abs(x - 540))
                if (k % 3 == 2 and cur == inner) or len(mine) < 2:
                    dest = min(other, key=lambda x: abs(x - cur))      # cross from the inner spot: a short walk
                else:
                    dest = next(x for x in mine if x != cur)
                if i in pop_t and dest not in outer:
                    dest = min(outer, key=lambda s: abs(s - cur))
            dur = max(1.0, abs(dest - cur) / WALK_SPEED) + 0.25      # the renderer's walks last at least 1 s
            ws = t0 + 0.1
            for j in sorted(pop_t):                   # never walk while any meme card is up (also the last line's)
                c0, c1 = pop_t[j] - 0.3, pop_t[j] + POP_CARD["dur"] + 0.3
                if ws < c1 and ws + dur > c0 and j != i:
                    ws = c1 + 0.05
            if ov and ws < ov[1] + 0.3 and ws + dur > ov[0] - 0.3:
                ws = ov[1] + 0.35                    # never while the diagram is up (he may be stepped out)
            t_end = ws + dur
            blocked = (i in verse_t and t_end > verse_t[i][0]) or (i in pop_t and t_end > pop_t[i] - 0.2) or \
                (freeze_t and freeze_t[0] == i and t0 <= freeze_t[1] + FREEZE["dur"] + FREEZE["after"] and t_end >= freeze_t[1] - 0.2)
            if dest != cur and not blocked:
                walks[i] = (cur, dest, ws, t_end)
                cur = dest
                k += 1
                nxt = i + WALK_EVERY[k % 2]
            elif need_outer and i in pop_t:
                # no time to reach an outer spot: this line goes without its pop-up (the card would hit him)
                del pop_t[i]
                P[i] = dict(P[i], pop=None)
                scene_notes.append(f"line {i + 1}: pop-up dropped (the guide could not reach an outer spot in time)")
        route.append(cur)

    scene_clips: dict[str, dict] = {}
    beats, frames, used_media = [], [], []
    shown: dict[str, list[str]] = {"area": [], "lane": [], "top": []}
    slot_of: dict[str, tuple] = {}
    old_lane_side = None
    last_gesture_line = -2
    acted_log: list[dict] = []                  # the guide actions asked for and whether the rig performed them
    tl: dict = {"draw": {}, "fade": [], "cards": []}   # absolute times, for the pre-render collision check
    kept_before: set = set()                    # band drawings already kept over from their own line
    cleared_by_freeze = False                   # the previous line's freeze left the board empty
    for i, (L, text) in enumerate(zip(P, lines)):
        W = words[i]
        t_start, t_last = W[0]["start"], W[-1]["end"]
        spot = route[i]
        ev: list[dict] = []
        first = W[0]["word"]
        if i == 0:
            ev += [{"at": 0, "do": "place", "who": "guide", "x": spot, "facing": -1 if spot > 540 else 1},
                   {"at": 0, "do": "size", "who": "guide", "value": Z["guide"]["size"], "dur": 0}]
        if i in walks:
            ev.append({"at": _at_time(W, walks[i][2]), "do": "walk", "who": "guide", "to": walks[i][1]})
        if i == n_lines - 1:
            ev.append({"at": _anchor(W, first, 0.05)[0], "do": "look_viewer", "who": "guide"})
        ev.append({"at": _anchor(W, first, 0.08)[0], "do": "express", "who": "guide", "expression": L["expression"]})
        busy = []                                   # [(t0, t1)] where the guide keeps his arms down
        if i in pop_t:
            busy.append((pop_t[i] - 0.3, pop_t[i] + POP_CARD["dur"] + 0.3))
        if i in walks:
            busy.append((walks[i][2], walks[i][3]))
        fz = freeze_t if freeze_t and freeze_t[0] == i else None
        if fz:
            busy.append((fz[1] - 0.2, fz[1] + FREEZE["dur"] + FREEZE["after"]))
        if ov and hide_guide and t_start - 1 < ov[1] and t_last + 1 > ov[0]:
            busy.append((ov[0] - 0.2, ov[1] + 0.3))     # he is stepped out behind the diagram

        # ---------------- drawings: the first in the drawing area, the second in the guide lane on the side away
        # from the guide (when no pop-up uses that side), else both side by side in the drawing area. Each one
        # replaces what was in its own slot, so the frame never empties between lines.
        dr = L["drawings"][:3]
        lane = _lane_slot(spot, G)           # on a pop-up line the lane drawing waits until the card is gone
        objs = [dict(types[d["type"]], _name=d["type"], _labeled=bool(d.get("fields")),
                     **real.get(f"l{i + 1}_{d['type']}{j}", {})) for j, d in enumerate(dr)]
        full = _lane_slot(spot, G, full=True)
        near = _near_top(full) if full else None
        # every way to place the line's 1-3 drawings: the band (whole or two halves), the side beside him (lower
        # or full height), the band over his own side; the one that fills the most frame wins (each >= 254 px,
        # labels readable). Drawings no arrangement can hold readably are dropped (noted).
        sets = [[("area", slots1[0])], [("area", slots2[0]), ("area", slots2[1])]]
        if lane:
            sets += [[("area", slots1[0]), ("lane", lane)], [("area", slots2[0]), ("area", slots2[1]), ("lane", lane)]]
        if full:
            sets += [[("lane", full)], [("lane", full), ("area", near)]]
        if late[i]:                            # its media comes late: one drawing leads in the box's place until then
            sets += [[("top", LEAD)]] + [[("top", LEAD)] + st for st in list(sets) if len(st) < 3]   # (one drawing too)
        if open_line[i]:                       # no media: one big drawing, two side by side or two stacked (+ beside him)
            om, oh = (OPEN[0] + OPEN[2]) / 2, (OPEN[1] + OPEN[3]) / 2
            opens = [[("top", OPEN)], [("top", (OPEN[0], OPEN[1], om - 5, OPEN[3])), ("top", (om + 5, OPEN[1], OPEN[2], OPEN[3]))],
                     [("top", (OPEN[0], OPEN[1], OPEN[2], oh - 5)), ("top", (OPEN[0], oh + 5, OPEN[2], OPEN[3]))]]
            sets = [o_ + l_ for o_ in opens for l_ in ([[]] + ([[("lane", lane)]] if lane else [])) if len(o_) + len(l_) <= 3]
            if full:
                sets.append([("lane", full), ("top", (near[0], OPEN[1], near[2], OPEN[3]))])
        def search(cands):
            best, best_area, pick = None, -1.0, ()
            for st in cands:
                if len(st) > len(dr):
                    continue
                for perm in itertools.permutations(range(len(dr)), len(st)):
                    area = 0.0
                    for k, (_, sl) in zip(perm, st):
                        f = _fit(objs[k], sl, strict=False)
                        if f is None or (f[0] < MIN_LABEL_SCALE and objs[k].get("_labeled")):   # labels stay readable
                            area = -1.0
                            break
                        area += objs[k]["size"][0] * objs[k]["size"][1] * f[0] ** 2
                    if open_line[i] and area >= 0:   # the open middle: keep the planner's drawings over one giant one
                        area += 1e7 * len(st)
                    if area > best_area:
                        best, best_area, pick = st, area, perm
            return best, best_area, pick
        best, best_area, pick = None, -1.0, ()
        if i in pop_t:
            # a meme-card line: the side beside the guide is the card's while it is up (a side drawing would have to
            # clear for it and leave its part of the frame empty), so the band holds two drawings when it can hold
            # them readably; a third may still go beside him (it appears once the card is gone)
            need = min(2, len(dr))
            best, best_area, pick = search([st for st in sets if sum(z == "area" for z, _ in st) >= need])
            if best is None or best_area < 0 or sum(z == "area" for z, _ in best) < need:
                best, best_area, pick = None, -1.0, ()
        if best is None and dr:
            best, best_area, pick = search(sets)
        if not dr:                                     # the line's visual is its media / verse card / the diagram
            best, best_area, pick = [], 0.0, ()
        elif best is None or best_area < 0:
            raise CompileError(f"line {i + 1}: {' and '.join(o['_name'] for o in objs)} cannot be drawn 250 px or larger "
                               "here: pick library illustrations")
        order = sorted(zip(pick, best))                # keep the planner's order
        dropped = [dr[k]["type"] for k in range(len(dr)) if k not in pick]
        if dropped:
            scene_notes.append(f"line {i + 1}: {', '.join(dropped)} dropped (no room for it readably)")
        dr, objs, places = [dr[k] for k, _ in order], [objs[k] for k, _ in order], [p_ for _, p_ in order]
        ids, first_t, draw_pos = [], None, {}
        pop_redraw: list = []                          # lane drawings that make way for this line's meme card
        freeze_back: list = []                         # drawings shown before the freeze that come back after it
        after_freeze = cleared_by_freeze
        cleared_by_freeze = False
        new_in = {"area": None, "lane": None, "top": None}
        refilled = False                               # a drawing already refills the board after this line's freeze
        for j, d in enumerate(dr):
            did = f"l{i + 1}_{d['type']}{j}"
            obj = objs[j]
            zone, slot = places[j]
            s, x, y = _fit(obj, slot)
            a, t = _anchor(W, d["word"], 0.0)
            through = i in walks and _path_hits(walks[i], [slot], G)          # does his walk cross this slot?
            if i in walks and zone == "lane" and ((through and t < walks[i][3] + 0.1) or t > walks[i][3] + 1.5):
                t = walks[i][3] + 0.15 if through else max(t_start, walks[i][2])   # the lane never stays empty
                a = _at_time(W, t)
            if i in pop_t and zone == "lane" and t < pop_t[i] + POP_CARD["dur"] + 0.2:
                if t < pop_t[i] - 1.4:                 # shown on its word, cleared just before the card, back after it
                    pop_redraw.append((did, t))
                else:
                    t = pop_t[i] + POP_CARD["dur"] + POP_BACK
                    a = _at_time(W, t)
            k0 = 1 if zone == "lane" else j              # a lane drawing waits until the guide stands on his spot
            if i == 0 and t - t_start > 0.1 * k0 and not (zone == "lane" and i in pop_t):   # first frame full (the hook)
                t = round(0.1 * k0, 3)
                a = t
            first_top = next(k for k in range(len(places)) if places[k][0] == "top") if any(z == "top" for z, _ in places) else -1
            if zone == "top" and j == first_top and t - t_start > 0.1 and (
                    late[i] or (open_line[i] and (i == 0 or not open_line[i - 1]))):
                # the media left (or comes late): the line's main drawing takes the middle at once, already in the
                # pause before the line once the previous box / verse card is gone
                gone = max([c1 for r_, c0_, c1 in tl["cards"] if r_ == BOX and c0_ < t_start] + [0.0]) + 0.05
                t = round(max(t_start - 0.35, gone, words[i - 1][-1]["end"] + 0.05 if i else 0.0), 3) if i else round(t_start + 0.1, 3)
                t = min(t, round(t_start + 0.1, 3)) if gone <= t_start + 0.1 else t
                a = _at_time(W, t)
            if after_freeze and t - t_start > 0.1 + 0.35 * j:   # the freeze cleared the board: refill at once
                t = round(t_start + 0.1 + 0.35 * j, 3)
                a = _at_time(W, t)
            if fz and zone == "lane" and t > fz[1] + FREEZE["dur"] + FREEZE["after"] + 1.5:
                t = fz[1] + FREEZE["dur"] + FREEZE["after"] + 0.3      # refill the lane right after the freeze
                a = _at_time(W, t)
            tb = fz[1] + FREEZE["dur"] + FREEZE["after"] + 0.35 + 0.35 * j if fz else 0
            if fz and t <= fz[1] - 0.8 and t >= t_start - 0.01:
                if tb < t_last - 0.3:                  # shown on its word, cleared for the freeze zoom (below), back
                    freeze_back.append((did, tb))       # once the camera is, while its line still runs
            elif fz and t <= fz[1] + FREEZE["dur"] + FREEZE["after"]:
                t = fz[1] + FREEZE["dur"] + FREEZE["after"] + 0.35 + 0.35 * j   # after it, the camera fully back
                a = _at_time(W, t)
            elif fz and not refilled and t > fz[1] + FREEZE["dur"] + FREEZE["after"] + 0.35 and t > fz[1] - 0.8:
                # the freeze cleared the board: the line's next drawing comes as soon as the camera is back, not
                # seconds later on its word (the frame would stand empty)
                t = fz[1] + FREEZE["dur"] + FREEZE["after"] + 0.35
                a = _at_time(W, t)
            if fz and t > fz[1]:
                refilled = True
            if ov and t_start < ov[1] < t_last and t > ov[1] + 0.1 + 0.35 * j:
                t = round(ov[1] + 0.1 + 0.35 * j, 3)          # the board refills as soon as the diagram goes
                a = _at_time(W, t)
            if under_diagram(slot, t):
                if ov[1] + 0.1 + 0.35 * j < t_last - 0.3:   # the rest of its line, once the diagram is gone
                    t = round(ov[1] + 0.1 + 0.35 * j, 3)
                    a = _at_time(W, t)
                else:                                        # its line is over before the diagram goes
                    scene_notes.append(f"line {i + 1}: {d['type']} left out (the diagram is on screen for this line)")
                    continue
            if zone != "lane":                         # the middle is the box's (and its caption's) while one is up:
                for r_, c0_, c1_ in tl["cards"]:        # never drawn before the caption has gone back to the top
                    if r_ == BOX and c0_ - 0.05 < t < c1_ + 0.05:
                        t = round(c1_ + 0.05, 3)
                        a = _at_time(W, t)
            if j and first_t is not None and abs(t - first_t) < 0.3 and i:
                t = first_t + 0.35
                a = _at_time(W, t)
            # drawn stroke by stroke (no pop-in overshoot, no idle sway): it never grows past its slot
            ev.append({"at": a, "do": "draw", "id": did, "x": x, "y": y, "scale": s, "dur": 0.6,
                       "pop": False, "still": True, "main": True, **({"instant": True} if i == 0 and j == 0 and zone == "area" else {}),
                       **_draw_fields(d, types)})
            ids.append(did)
            draw_pos[did] = ((slot[0] + slot[2]) / 2, (slot[1] + slot[3]) / 2, key(d["word"]), t, zone)
            fw, fh = obj["size"][0] * s, obj["size"][1] * s
            slot_of[did] = (x + obj.get("center", [0, 0])[0] * s - fw / 2, y + obj.get("center", [0, 0])[1] * s - fh / 2,
                            x + obj.get("center", [0, 0])[0] * s + fw / 2, y + obj.get("center", [0, 0])[1] * s + fh / 2)
            tl["draw"][did] = (slot_of[did], t)
            first_t = t if first_t is None else min(first_t, t)
            if new_in[zone] is None or t < new_in[zone]:
                new_in[zone] = t
        # clear each slot just before its new drawing; the lane also clears before a walk toward it, a pop-up
        # on that side, or when it gets no new drawing this line
        fades: dict[float, list[str]] = {}
        kept_area = []                                 # an old band drawing no new drawing covers stays one line
        new_area = [d for d in ids if draw_pos[d][4] == "area"]
        for od in shown["area"]:
            if new_area and od not in kept_before and not any(_overlap(slot_of[od], slot_of[nd]) for nd in ids):
                kept_area.append(od)
        kept_before = set(kept_area)
        for zone in ("area", "lane", "top"):
            old = [d for d in shown[zone] if d not in kept_area]
            if not old:
                continue
            t_new = new_in[zone]
            if zone == "lane":
                if i in walks and _path_hits(walks[i], [slot_of[d] for d in old], G):
                    t_new = walks[i][2] - 0.05 if t_new is None else min(t_new, walks[i][2] - 0.05)
                if i in pop_t:
                    t_new = pop_t[i] - POP_CLEAR + 0.05 if t_new is None else min(t_new, pop_t[i] - POP_CLEAR + 0.05)
                if t_new is None:
                    t_new = new_in["area"] if new_in["area"] is not None else t_start
            if zone == "top" and t_new is None:      # the middle: cleared with the line's first new drawing
                t_new = min([x for x in new_in.values() if x is not None], default=t_start)
            if zone == "top" and not open_line[i]:   # ... and before the captions come back to the middle
                t_new = min(t_new, (words[i - 1][-1]["end"] - 0.03) if i else t_start)
            if t_new is None:
                continue
            if zone == "area":                         # each old band drawing goes just before the new one on it
                for od in old:
                    hits = [draw_pos[nd][3] for nd in ids if draw_pos[nd][4] == "area" and _overlap(slot_of[od], slot_of[nd])]
                    fades.setdefault(round(max(t_start - 0.55, (min(hits) if hits else t_new) - 0.05), 3), []).append(od)
                continue
            hand = zone == "top" and not open_line[i]          # the layout handover: exactly before the caption returns
            fades.setdefault(round(t_new - 0.05 if hand else max(t_start - 0.55, t_new - 0.05), 3), []).extend(old)
        # a new drawing whose slot covers an old drawing of the OTHER zone (a full-height side drawing after a
        # band, or the reverse) clears that one just before it appears
        for zone in ("area", "lane", "top"):
            for od in shown[zone]:
                hits = [draw_pos[nd][3] for nd in ids if draw_pos[nd][4] != zone and _overlap(slot_of[od], slot_of[nd])]
                if hits:
                    fades.setdefault(round(max(t_start - 0.55, min(hits) - 0.05), 3), []).append(od)
        for did_, _ in pop_redraw:
            fades.setdefault(round(pop_t[i] - POP_CLEAR, 3), []).append(did_)
            ev.append({"at": _at_time(W, pop_t[i] + POP_CARD["dur"]), "do": "fade", "ids": [did_], "opacity": 1,
                       "dur": 0.1})                    # the card is hidden at its end time (it shrinks just before)
            tl["fade"].append((pop_t[i] + POP_CARD["dur"], [did_], 1))
        # a drawing whose place is free before its word (empty when the line starts, or its old drawing cleared early
        # for another one) is drawn as soon as it is free, staggered, instead of leaving part of the frame empty; an
        # empty place may be filled in the pause before the line (at most 0.5 s ahead, never before the previous
        # line's last word). Beside the guide: never into his walk, a meme card or the freeze.
        probe = {"draw": tl["draw"], "fade": tl["fade"] + [(ft, fids, 0) for ft, fids in fades.items()], "cards": []}
        sp_now = _spans(probe)
        lead = max(t_start - 0.5, words[i - 1][-1]["end"] + 0.05) if i else t_start
        pulled = 0                                     # the stagger counts only the drawings moved earlier here
        for j, did in enumerate(ids):
            if draw_pos[did][4] == "lane":
                if i in walks and _path_hits(walks[i], [slot_of[did]], G):
                    continue
                if i in pop_t and _overlap(slot_of[did], _LANE_CARD(spot, G)):
                    continue
            ends = [max(b for _, b in spans) for o, (r, _, spans) in sp_now.items()
                    if o not in ids and _overlap(r, slot_of[did]) and max(b for _, b in spans) > t_start]
            if any(e > 1e8 for e in ends):
                continue                               # its place stays taken until its own word
            # as the old one fades (the same 0.05 s overlap as every replacement): a drawing counts from its start
            tn = round(max([lead + 0.1 + 0.35 * pulled] + [e - 0.05 for e in ends]), 3)
            if draw_pos[did][4] != "lane":             # not while a clip box (and its caption handover) is up
                for r_, c0_, c1_ in tl["cards"]:
                    if r_ == BOX and c0_ - 0.05 < tn < c1_ + 0.05:
                        tn = round(c1_ + 0.05, 3)
            if fz and fz[1] - 0.8 < tn < fz[1] + FREEZE["dur"] + FREEZE["after"] + 0.35:
                continue
            if i in pop_t and pop_t[i] - 0.3 < tn < pop_t[i] + POP_CARD["dur"] and _overlap(slot_of[did], _LANE_CARD(spot, G)):
                continue
            if under_diagram(slot_of[did], tn):
                continue
            if draw_pos[did][3] > tn + 0.01:
                pulled += 1
                for e in ev:
                    if e.get("do") == "draw" and e.get("id") == did:
                        e["at"] = _at_time(W, tn)
                draw_pos[did] = draw_pos[did][:3] + (tn,) + draw_pos[did][4:]
                tl["draw"][did] = (slot_of[did], tn)
        # an old side drawing cleared early (a new band drawing covers it): the new side drawing takes its place at
        # once instead of waiting for its word, so the side never stands empty
        old_lane = set(shown["lane"])
        cleared = [ft for ft, fids in fades.items() if old_lane & set(fids) and ft >= t_start]
        if cleared:
            tf = min(cleared)
            for nd in [d for d in ids if draw_pos[d][4] == "lane" and draw_pos[d][3] > tf + 0.3]:
                tn = round(tf + 0.05, 3)
                if i in walks and _path_hits(walks[i], [slot_of[nd]], G) or under_diagram(slot_of[nd], tn):
                    continue
                if fz and fz[1] - 0.8 < tn < fz[1] + FREEZE["dur"] + FREEZE["after"] + 0.35:
                    continue                           # never into the freeze zoom
                if i in pop_t and pop_t[i] - 1.4 < tn < pop_t[i] + POP_CARD["dur"] + POP_BACK:
                    tn = round(pop_t[i] + POP_CARD["dur"] + POP_BACK, 3)   # it would sit under (or flash just before)
                    if tn >= draw_pos[nd][3] - 0.3:                     # the card: right after it instead
                        continue
                for e in ev:
                    if e.get("do") == "draw" and e.get("id") == nd:
                        e["at"] = _at_time(W, tn)
                draw_pos[nd] = draw_pos[nd][:3] + (tn,) + draw_pos[nd][4:]
                tl["draw"][nd] = (slot_of[nd], tn)
                if i in pop_t and tn < pop_t[i]:      # now shown before the card: it makes way for it like the others
                    fades.setdefault(round(pop_t[i] - POP_CLEAR, 3), []).append(nd)
                    ev.append({"at": _at_time(W, pop_t[i] + POP_CARD["dur"]), "do": "fade", "ids": [nd], "opacity": 1,
                               "dur": 0.1})
                    tl["fade"].append((pop_t[i] + POP_CARD["dur"], [nd], 1))
                for zone in ("area", "lane", "top"):          # what it now covers earlier is cleared earlier too
                    for od in shown[zone]:
                        if od != nd and _overlap(slot_of[od], slot_of[nd]):
                            fades.setdefault(round(max(t_start - 0.55, tn - 0.05), 3), []).append(od)
        if late[i]:                                    # the lead drawing gives way to the media for good
            for did_ in [d for d in ids if draw_pos[d][4] == "top" and draw_pos[d][3] < box_at[i] - 0.3]:
                fades.setdefault(round(box_at[i] - 0.2, 3), []).append(did_)
        faded_now = {d for fids in fades.values() for d in fids}
        for ft, fids in sorted(fades.items()):
            fids = sorted(set(fids))
            ev.append({"at": _at_time(W, ft) if ft >= t_start else _anchor(W, first, ft - t_start)[0], "do": "fade",
                       "ids": fids, "opacity": 0, "dur": 0.1})
            tl["fade"].append((ft, fids, 0))
        prev_old = shown["area"] + shown["lane"] + shown["top"]
        prev_lane = list(shown["lane"])
        for zone in ("area", "lane", "top"):
            mine = [d for d in ids if draw_pos[d][4] == zone]
            if mine or zone in ("lane", "top"):
                shown[zone] = mine + ([d for d in kept_area if d not in faded_now] if zone == "area" else [])
        old_lane_side = None if not shown["lane"] else (1 if draw_pos[shown["lane"][0]][0] > spot else -1)
        old_lane_spot = spot

        # ---------------- gesture (point at the drawing being named, or shrug / look / wave)
        g = L.get("gesture") or {"do": "none"}
        want = g.get("do", "none")
        if want == "none" and i - last_gesture_line >= 2 and dr:
            want, g = "point", {"do": "point", "word": dr[0]["word"]}
        if want != "none":
            target = next((d for d, p in draw_pos.items() if p[2] == key(g.get("word", ""))), ids[0] if ids else None)
            tg = draw_pos.get(target) if target else None
            waits = want in ("point", "shrug", "wave", "present", "look") or actions.ACTIONS.get(want, {}).get("points")
            t_g = max(_occ(W, g.get("word", first))[1]["start"], (tg[3] + 0.35) if tg and waits else 0)
            if any(a <= t_g <= b for a, b in busy):
                t_g = max(b for a, b in busy if a <= t_g <= b) + 0.1
            if t_g < t_last - 0.3:
                at = _at_time(W, t_g)
                lanes = [slot_of[d] for d in set(prev_lane + shown["lane"] + [d for d in ids if draw_pos[d][4] == "lane"])]
                tip = _arm_tip(spot, tg[:2], reach) if tg else None
                room = spot in shrug_ok and not any(
                    r[0] - 18 <= x <= r[2] + 18 for r in lanes for x in (spot - G["shrug_half_width"], spot + G["shrug_half_width"]))
                can_point = bool(tg) and tg[4] != "lane" and _tip_ok(spot, tg[:2], reach) and not any(_inside(tip, r) for r in lanes)
                acted = actions.rig(want, {"expression": L["expression"], "room": room, "target": target if tg else None,
                                           "can_point": can_point}) if want in actions.ACTED - {"point", "shrug", "wave", "present", "look"} else None
                if acted and (t_g + actions.span(acted) > t_last + 0.4 or
                              any(a < t_g + actions.span(acted) and b > t_g for a, b in busy)):
                    acted = None                      # the acted moment would run into a walk, a meme card or the next line
                if want not in ("point", "shrug", "wave", "present", "look"):
                    acted_log.append({"line": i + 1, "action": want, "status": actions.ACTIONS[want]["status"],
                                      "performed": bool(acted), **({} if acted else {"instead": "look up"})})
                if acted:
                    for dt, e in acted:
                        ev.append({"at": _at_time(W, t_g + dt), **e})
                elif want == "point" and tg and tg[4] == "lane":
                    ev.append({"at": at, "do": "look", "who": "guide", "dir": "down", "expression": L["expression"], "hold": 0.7})
                elif want == "point" and tg and _tip_ok(spot, tg[:2], reach) and not any(_inside(tip, r) for r in lanes):
                    ev.append({"at": at, "do": "point", "who": "guide", "toward": target, "hold": 0.6, "respond": False})
                elif want == "shrug" and room:
                    ev.append({"at": at, "do": "shrug", "who": "guide"})
                elif want == "wave" and spot + 150 <= 775:
                    ev.append({"at": at, "do": "wave", "who": "guide"})
                else:
                    ev.append({"at": at, "do": "look", "who": "guide", "dir": "up", "expression": L["expression"], "hold": 0.7})
                last_gesture_line = i
        if fz:
            # the freeze zooms the whole board: drawings on screen would be pushed off the safe box
            on_screen = prev_old + [d for d, p in draw_pos.items() if p[3] < fz[1]]
            if on_screen:
                tl["fade"].append((_anchor(W, freeze["word"], -0.12)[1], sorted(set(on_screen)), 0))
                ev.append({"at": _anchor(W, freeze["word"], -0.12)[0], "do": "fade", "ids": sorted(set(on_screen)),
                           "opacity": 0, "dur": 0.1})
            for did_, tb in freeze_back:
                ev.append({"at": _at_time(W, tb), "do": "fade", "ids": [did_], "opacity": 1, "dur": 0.1})
                tl["fade"].append((tb, [did_], 1))
            cleared_by_freeze = not freeze_back and not any(p[3] > fz[1] for p in draw_pos.values())
            ev.append({"at": _anchor(W, freeze["word"])[0], "do": "freeze", "who": "guide", "dur": FREEZE["dur"],
                       "zoom": FREEZE["zoom"], "focus": {"x": spot, "y": 1150}, "grey": True,
                       "sound": "record_scratch", "sound_file": SCRATCH})

        # ---------------- the clip box
        if L.get("verse"):
            v = L["verse"]
            txt, spoken = _verse_text(v, text)
            box_ev = {"box": "verse", "scripture": {"ref": scripture.canonical(v["ref"]), "text": txt}}
            sp = _split_word(txt)
            if sp:
                box_ev["split_after"] = sp
            if not spoken:
                box_ev.update({"paced": True, "from": key(v["word"])})
            ev.append(box_ev)
        box_on = _anchor(W, L["verse"]["word"], -0.4)[1] if L.get("verse") else None
        for b in media[i]:
            if b.get("skip"):
                continue
            a, ta = _anchor(W, b["word"], -0.15)
            if ov and ov[0] - 0.2 <= ta < ov[1]:
                scene_notes.append(f"line {i + 1}: box media on {b['word']!r} left out (the diagram shows this part)")
                continue
            box_on = ta if box_on is None else min(box_on, ta)
            if b["kind"] == "meme":
                ev.append({"at": a, "box": "media", "file": b.get("path") or "movie_reference/" + b["file"]})
            else:
                ck = f"s_{b['source']}_{b['id']}"
                scene_clips.setdefault(ck, {b["source"]: b["id"], "label": b.get("title", "")[:80]})
                ev.append({"at": a, "box": "clip", "clip": ck})
            used_media.append(b)
        if box_on is not None:
            # the frame is there only while its media is: it leaves at the end of its line, unless the next line's
            # own media follows at once (no flicker); a verse card still holds its 1 s (mediabox.plan waits for it)
            nxt = [_occ(words[i + 1], x["word"])[1]["start"] - 0.15 for x in (media[i + 1] if i + 1 < n_lines else [])
                   if not x.get("skip")]
            if i + 1 < n_lines and P[i + 1].get("verse"):
                nxt.append(_occ(words[i + 1], P[i + 1]["verse"]["word"])[1]["start"] - 0.4)
            t_off = round(t_last + (0.01 if i + 1 < n_lines and open_line[i + 1] else 0.15), 3)
            if not nxt or min(nxt) - t_off > 0.8:
                ev.append({"at": _at_time(W, t_off), "box": "off"})
                tl["cards"].append((BOX, box_on, max(t_off, t_last + 1.1) if i in verse_t else t_off))   # (the card holds 1.05 s)
            else:
                tl["cards"].append((BOX, box_on, min(nxt)))

        # ---------------- the pop-up meme beside the guide
        if L.get("pop"):
            p = L["pop"]
            ls = _pop_slot(spot, G)
            if ls[2] - ls[0] < Z["pop"]["w"] + 10:
                raise CompileError(f"line {i + 1}: no room for the pop-up beside the guide")
            cx = (ls[0] + ls[2]) / 2
            tl["cards"].append(((cx - Z["pop"]["w"] / 2, ls[1], cx + Z["pop"]["w"] / 2, ls[3]),
                                pop_t[i], pop_t[i] + POP_CARD["dur"]))
            ev.append({"at": _at_time(W, pop_t[i]), "reaction": FACE_OF.get(L["expression"], "surprised"),
                       "face": FACE_OF.get(L["expression"], "surprised"), "file": p.get("path") or "movie_reference/" + p["file"],
                       "dur": POP_CARD["dur"], "card": {"x": cx, "y": Z["pop"]["y"], "w": Z["pop"]["w"], "rotate": 0}})
        beat = {"id": f"l{i + 1}", "panel": 0, "narration": text, "events": ev,
                "camera_start": {"x": 540, "y": 960, "zoom": 1.0, "dur": 0.01} if i == 0 else False}
        if i == n_lines - 1:
            beat["interaction"] = False
        beats.append(beat)
        if ids:
            # a still once the line's last drawing is complete (draw 0.6 s + margin for the renderer's own timing)
            frames.append({"beat": beat["id"], "t": max(draw_pos[d][3] for d in ids) + 1.5, "line": text})

    # captions: at the middle of the frame (the default anchor) with or without a clip box; only a diagram moves them
    # to their band under it while it is up (no top-of-frame windows, no handovers between box and no-box lines)
    cap_wins: list = []
    dg_info = None
    if diagram:
        b0, b1 = _beat_at(words, ov[0]), _beat_at(words, ov[1])
        at0 = 0 if ov[0] <= words[0][0]["start"] + 0.05 and b0 == 0 else _at_time(words[b0], ov[0])
        beats[b0]["events"].append({"at": at0, "box": "diagram", "file": diagram["path"] or "movie_reference/" + diagram["file"],
                                    "rect": diagram["fit"]["rect"],
                                    "views": [dict(v, rect_n=[v["rect"][0] / diagram["size"][0], v["rect"][1] / diagram["size"][1],
                                                              v["rect"][2] / diagram["size"][0], v["rect"][3] / diagram["size"][1]])
                                              if v.get("rect") else v for v in diagram.get("views") or []]})
        beats[b1]["events"].append({"at": _at_time(words[b1], ov[1]), "box": "off"})
        if hide_guide:              # the diagram covers him: he steps out (a cut, no effect) and is back when it goes
            first = next((e for e in beats[b0]["events"] if e.get("do") == "place" and e.get("at") == 0), None)
            if at0 == 0 and first:
                first["hidden"] = True                # the video opens on the diagram: he starts out of view
            else:
                beats[b0]["events"].append({"at": at0, "do": "exit", "who": "guide", "dur": 0})
            beats[b1]["events"].append({"at": _at_time(words[b1], ov[1]), "do": "appear", "who": "guide"})
        for o in OBST:
            tl["cards"].append((o, ov[0], ov[1]))
        frames.append({"beat": beats[b0]["id"], "t": min(ov[0] + 2.0, ov[1] - 0.2), "line": lines[b0]})
        frames.sort(key=lambda f: f["t"])
        dg_info = {k: diagram[k] for k in ("file", "size", "t0", "t1", "why", "sentences", "views", "fit", "readability") if k in diagram}
        dg_info["guide_hidden"] = hide_guide
    fixed, left = resolve_conflicts(tl, beats, words)
    scene_notes += [f"timeline: {n}" for n in fixed]
    if left:
        raise CompileError("drawings would collide on screen (rejected before rendering): " + "; ".join(left[:4]))
    scene_conflicts = fixed
    # ---------------- the 8 review stills: spread over the lines
    picks = frames if len(frames) <= 8 else [frames[round(k * (len(frames) - 1) / 7)] for k in range(8)]
    while len(picks) < 8 and frames:
        extra = dict(frames[len(picks) % len(frames)])
        extra["t"] += 1.2
        picks.append(extra)
    pv = []
    for f in picks:
        i = int(f["beat"][1:]) - 1
        pv.append({"beat": f["beat"], "at": _at_time(words[i], min(f["t"], words[i][-1]["end"] + 0.4)), "line": f["line"]})
    Zc = Z["caption"]
    scene = {
        "id": meta["id"], "title": meta.get("title") or meta["id"].replace("-", " ").title(),
        "voice_profile": "kindled_iron", **({"theme": meta["theme"]} if meta.get("theme") else {}),
        "voice_file": {"path": meta["audio_path"], "sha256": meta["sha256"], "provider": "owner", "voice": "owner"},
        "voice_as_is": True, "exact_narration": True, "end_hold": 1.4, "ground": Z["guide"]["ground"], "camera_y": 960,
        "fill_min": 0.3, "max_visual_gap": 2.5, "walk_speed": WALK_SPEED, "pencil": True,
        "captions_box": {"x": Zc["x"] + Zc["w"] / 2, "y": Zc["y"], "w": Zc["w"], "size": Zc["size"], "min_scale": 0.6},
        "captions_chunk": {"max_words": 3, "min_words": 1, "max_chars": 16},
        "caption_windows": sorted(([{"t0": ov[0], "t1": ov[1], **diagram["fit"]["caption"]}] if diagram else []) + cap_wins,
                                  key=lambda w: w["t0"]),
        "audit": {"max_words": 3, "one_line": True}, "caption_color": "ink", "caption_on": "accent",
        "require_memes": sum(1 for L in P if L.get("pop")), "max_media_uses": 2,
        "cast": {"guide": {"panel": 0, "x": route[0], "scale": 2.1, "facing": -1 if route[0] > 540 else 1, "accent": True}},
        "mediabox": {"x": Z["box"]["x"], "y": Z["box"]["y"], "w": Z["box"]["w"], "h": Z["box"]["h"], "verse_size": round(60 * Z["box"]["h"] / 420), "pad_x": 48},
        "clips": scene_clips,
        "preview": {"folder": meta["id"], "public_artifacts": False, "stage": "full",
                    "frames": [{"beat": f["beat"], "at": f["at"]} for f in pv]},
        "post": {"title": meta.get("title") or meta["id"].replace("-", " ").title()},
        "director": {"plan_lines": n_lines, "route": route, "walks": {str(k + 1): v[:2] for k, v in walks.items()}, "notes": scene_notes, "timeline_fixes": scene_conflicts, "diagram": dg_info,
                     "actions": acted_log + list(plan.get("unsupported_actions") or [])},
        "beats": beats,
    }
    return scene, pv
