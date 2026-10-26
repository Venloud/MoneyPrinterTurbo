"""Shot plan -> render-ready scene JSON. All coordinates come from here (zones in catalog.json + measured sizes).

Layout (fixed, never overlapping): the clip box at the top, the caption band under it, the drawing area in the
middle, the guide lane at the bottom. Drawings sit only in the drawing area, so the guide (below it) never walks
through them; meme pop-ups sit in the guide lane next to the guide while he stands at an outer spot.

Timing comes from the real narration: `words` are the recording's word timings aligned to the script (the same
alignment the renderer makes), so walks, freezes and pop-ups are scheduled around each other here, and every
event is anchored to a spoken word ("word#n+0.3") so the renderer resolves it on its own alignment.
"""
from __future__ import annotations

import math
import re

from kindled_iron import scripture
from kindled_iron.director.plan import director_types, key, quoted_spans

WALK_SPEED = 280                # px/s, the guide's natural pace at this size
WALK_EVERY = (2, 3)             # lines between walks, alternating
FACE_OF = {"happy": "crying_laughing", "curious": "thinking", "thinking": "thinking", "surprised": "surprised",
           "shocked": "shocked", "awe": "mind_blown", "mind_blown": "mind_blown", "focused": "thinking",
           "puzzled": "puzzled", "confused_math": "confused_math", "side_eye": "side_eye", "wait_what": "wait_what",
           "crying_laughing": "crying_laughing"}
POP_CARD = {"w": 380, "dur": 1.2}
FREEZE = {"dur": 1.0, "zoom": 1.45, "after": 0.45}   # the camera needs ~0.35 s to come back after the freeze
SHOULDER_Y = 1110


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


def _split_word(text: str, limit: int = 110) -> str | None:
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


def _fit(obj: dict, slot: tuple[float, float, float, float]) -> tuple[float, float, float]:
    """Scale + position (x, y) so the measured drawing fills its slot (never under 250 px on its long side)."""
    x0, y0, x1, y1 = slot
    w, h = obj["size"]
    cx, cy = obj.get("center", [0, 0])
    s = min((x1 - x0) * 0.92 / w, (y1 - y0) * 0.92 / h, 2.4)      # 8 % room for the pop-in and the strokes
    if max(w, h) * s < 250:
        raise CompileError(f"a {obj.get('_name')} drawing would be under 250 px in its slot")
    return round(s, 3), round((x0 + x1) / 2 - cx * s, 1), round((y0 + y1) / 2 - cy * s, 1)


def _tip_ok(spot: float, target: tuple[float, float], reach: float) -> bool:
    """Pointing: the hand ends ~reach px from the shoulder toward the target; it must stay in the usable frame."""
    dx, dy = target[0] - spot, target[1] - SHOULDER_Y
    d = math.hypot(dx, dy) or 1
    tx = spot + reach * dx / d
    return 125 <= tx <= 775


def _lane_slot(spot: float, G: dict) -> tuple[float, float, float, float] | None:
    """The guide lane beside the guide, on the side with more room (never under the button column)."""
    half = G["reach_side"] + 12          # clear of a pointing / shrugging arm, not just the body
    right = (spot + half, 1005, 775, 1430)
    left = (125, 1005, spot - half, 1430)
    best = max((right, left), key=lambda r: r[2] - r[0])
    return best if best[2] - best[0] >= 280 else None


def _pop_slot(spot: float, G: dict) -> tuple[float, float, float, float]:
    """A meme card beside the guide: he keeps his arms down while it is up, so only his body needs room."""
    half = G["half_width"] + 30
    right, left = (spot + half, 1005, 775, 1430), (125, 1005, spot - half, 1430)
    return max((right, left), key=lambda r: r[2] - r[0])


def _walks_into(walk: tuple, side) -> bool:
    """Does a walk head toward the side where the lane drawing is?"""
    if side is None:
        return False
    return (walk[1] - walk[0]) * side > 0


def compile_scene(plan: dict, lines: list[str], words: list[list[dict]], cat: dict, media: list[list[dict]],
                  meta: dict, measure=None) -> tuple[dict, list[dict]]:
    """-> (scene, frames). frames = the 8 review stills: [{beat, at, line}].
    measure(specs) -> {id: {size, center}}: the drawings' real boxes with their own labels (Chrome); without it
    the catalog's sample sizes are used (offline tests)."""
    Z, G = cat["zones"], cat["guide"]
    types = director_types(cat)
    real = {}
    if measure:
        specs = [{"id": f"l{i + 1}_{d['type']}{j}", "type": d["type"], **(d.get("fields") or {})}
                 for i, L in enumerate(plan["lines"]) for j, d in enumerate(L["drawings"][:2])]
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

    # ---------------- times we must keep clear of walks: pop cards, verse typing, the freeze
    pop_t, verse_t, freeze_t = {}, {}, None
    for i, L in enumerate(P):
        if L.get("pop"):
            pop_t[i] = _occ(words[i], L["pop"]["word"])[1]["start"]
        if L.get("verse"):
            v = L["verse"]
            verse_t[i] = (_occ(words[i], v["word"])[1]["start"] - 0.4, words[i][-1]["end"] + 1.4)
    if freeze.get("line"):
        fi = freeze["line"] - 1
        freeze_t = (fi, _occ(words[fi], freeze["word"])[1]["start"])

    # ---------------- guide route: a walk every 2-3 lines, outer spots for pop-ups
    cur = spots[3]
    route, walks, nxt, k = [], {}, WALK_EVERY[0], 0
    for i in range(n_lines):
        t0 = words[i][0]["start"]
        need_outer = i in pop_t and cur not in outer
        due = i >= nxt and i < n_lines - 1
        if need_outer or due:
            if need_outer:
                dest = min(outer, key=lambda s: abs(s - cur))
            else:
                idx = spots.index(cur)
                step = (1, 2)[k % 2] * (1 if (k // 2) % 2 == 0 else -1)
                j = idx + step
                if not 0 <= j < len(spots):
                    j = idx - step
                dest = spots[max(0, min(len(spots) - 1, j))]
                if i in pop_t and dest not in outer:
                    dest = min(outer, key=lambda s: abs(s - cur))
            dur = abs(dest - cur) / WALK_SPEED + 0.25
            t_end = t0 + 0.1 + dur
            blocked = (i in verse_t and t_end > verse_t[i][0]) or (i in pop_t and t_end > pop_t[i] - 0.2) or \
                (freeze_t and freeze_t[0] == i and t0 <= freeze_t[1] + FREEZE["dur"] + FREEZE["after"] and t_end >= freeze_t[1] - 0.2)
            if dest != cur and not blocked:
                walks[i] = (cur, dest, t0 + 0.1, t_end)
                cur = dest
                k += 1
                nxt = i + WALK_EVERY[k % 2]
            elif need_outer:
                raise CompileError(f"line {i + 1}: the guide cannot reach an outer spot before the pop-up")
        route.append(cur)

    scene_clips: dict[str, dict] = {}
    beats, frames, used_media = [], [], []
    shown: dict[str, list[str]] = {"area": [], "lane": []}
    old_lane_side = None
    last_gesture_line = -2
    for i, (L, text) in enumerate(zip(P, lines)):
        W = words[i]
        t_start, t_last = W[0]["start"], W[-1]["end"]
        spot = route[i]
        ev: list[dict] = []
        first = W[0]["word"]
        if i == 0:
            ev += [{"at": 0, "do": "place", "who": "guide", "x": spot, "facing": -1 if spot > 540 else 1},
                   {"at": 0, "do": "size", "who": "guide", "value": Z["guide"]["size"], "dur": 0.01}]
        if i in walks:
            ev.append({"at": _anchor(W, first, 0.1)[0], "do": "walk", "who": "guide", "to": walks[i][1]})
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

        # ---------------- drawings: the first in the drawing area, the second in the guide lane on the side away
        # from the guide (when no pop-up uses that side), else both side by side in the drawing area. Each one
        # replaces what was in its own slot, so the frame never empties between lines.
        dr = L["drawings"][:2]
        lane = _lane_slot(spot, G) if i not in pop_t else None
        if len(dr) == 2 and lane:
            places = [("area", slots1[0]), ("lane", lane)]
        elif len(dr) == 2:
            places = [("area", slots2[0]), ("area", slots2[1])]
        else:
            places = [("area", slots1[0])]
        ids, first_t, draw_pos = [], None, {}
        new_in = {"area": None, "lane": None}
        for j, d in enumerate(dr):
            did = f"l{i + 1}_{d['type']}{j}"
            obj = dict(types[d["type"]], _name=d["type"], **real.get(did, {}))
            zone, slot = places[j]
            s, x, y = _fit(obj, slot)
            a, t = _anchor(W, d["word"], 0.0)
            if fz and fz[1] - 0.1 <= t <= fz[1] + FREEZE["dur"] + FREEZE["after"]:
                t = fz[1] + FREEZE["dur"] + FREEZE["after"] + 0.05
                a = _at_time(W, t)
            if i in walks and zone == "lane" and t < walks[i][3] + 0.1:
                t = walks[i][3] + 0.15                # the lane drawing waits until the guide has arrived
                a = _at_time(W, t)
            if i == 0 and t - t_start > 0.6 + 0.8 * j:
                t = round(t_start + 0.05 + 0.8 * j, 3)
                a = round(0.05 + 0.8 * j, 3)
            if j and first_t is not None and t < first_t + 0.5:
                t = first_t + 0.6
                a = _at_time(W, t)
            # drawn stroke by stroke (no pop-in overshoot, no idle sway): it never grows past its slot
            ev.append({"at": a, "do": "draw", "id": did, "type": d["type"], "x": x, "y": y, "scale": s, "dur": 0.6,
                       "pop": False, "still": True, "main": True, **(d.get("fields") or {})})
            ids.append(did)
            draw_pos[did] = ((slot[0] + slot[2]) / 2, (slot[1] + slot[3]) / 2, key(d["word"]), t, zone)
            first_t = t if first_t is None else min(first_t, t)
            if new_in[zone] is None or t < new_in[zone]:
                new_in[zone] = t
        # clear each slot just before its new drawing; the lane also clears before a walk toward it, a pop-up
        # on that side, or when it gets no new drawing this line
        fades: dict[float, list[str]] = {}
        for zone in ("area", "lane"):
            old = shown[zone]
            if not old:
                continue
            t_new = new_in[zone]
            if zone == "lane":
                if i in walks and _walks_into(walks[i], old_lane_side):
                    t_new = walks[i][2] - 0.05 if t_new is None else min(t_new, walks[i][2] - 0.05)
                if i in pop_t:
                    t_new = pop_t[i] - 0.4 if t_new is None else min(t_new, pop_t[i] - 0.4)
                if t_new is None:
                    t_new = new_in["area"] if new_in["area"] is not None else t_start
            if t_new is None:
                continue
            fades.setdefault(round(max(t_start - 0.4, t_new - 0.15), 3), []).extend(old)
        for ft, fids in sorted(fades.items()):
            ev.append({"at": _at_time(W, ft) if ft >= t_start else _anchor(W, first, ft - t_start)[0], "do": "fade",
                       "ids": fids, "opacity": 0, "dur": 0.15})
        prev_old = shown["area"] + shown["lane"]
        for zone in ("area", "lane"):
            mine = [d for d in ids if draw_pos[d][4] == zone]
            if mine or zone == "lane":
                shown[zone] = mine
        old_lane_side = None if not shown["lane"] else (1 if draw_pos[shown["lane"][0]][0] > spot else -1)
        old_lane_spot = spot

        # ---------------- gesture (point at the drawing being named, or shrug / look / wave)
        g = L.get("gesture") or {"do": "none"}
        want = g.get("do", "none")
        if want == "none" and i - last_gesture_line >= 2:
            want, g = "point", {"do": "point", "word": dr[0]["word"]}
        if want != "none":
            target = next((d for d, p in draw_pos.items() if p[2] == key(g.get("word", ""))), ids[0] if ids else None)
            tg = draw_pos.get(target) if target else None
            t_g = max(_occ(W, g.get("word", first))[1]["start"], (tg[3] + 0.35) if tg else 0)
            if any(a <= t_g <= b for a, b in busy):
                t_g = max(b for a, b in busy if a <= t_g <= b) + 0.1
            if t_g < t_last - 0.3:
                at = _at_time(W, t_g)
                if want == "point" and tg and _tip_ok(spot, tg[:2], reach):
                    ev.append({"at": at, "do": "point", "who": "guide", "toward": target, "hold": 0.6, "respond": False})
                elif want == "shrug" and spot in shrug_ok:
                    ev.append({"at": at, "do": "shrug", "who": "guide"})
                elif want == "wave" and spot + 150 <= 775:
                    ev.append({"at": at, "do": "wave", "who": "guide"})
                else:
                    ev.append({"at": at, "do": "look", "who": "guide", "dir": "up", "expression": L["expression"], "hold": 0.7})
                last_gesture_line = i
        if fz:
            # the freeze zooms the whole board: drawings on screen would be pushed off the safe box
            on_screen = (prev_old if first_t is None or first_t > fz[1] else []) + \
                [d for d, p in draw_pos.items() if p[3] < fz[1]]
            if on_screen:
                ev.append({"at": _anchor(W, freeze["word"], -0.12)[0], "do": "fade", "ids": sorted(set(on_screen)),
                           "opacity": 0, "dur": 0.1})
            ev.append({"at": _anchor(W, freeze["word"])[0], "do": "freeze", "who": "guide", "dur": FREEZE["dur"],
                       "zoom": FREEZE["zoom"], "focus": {"x": spot, "y": 1150}, "sound": "record_scratch"})

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
        for b in media[i]:
            if b.get("skip"):
                continue
            a = 0 if (i == 0 and not used_media) else _anchor(W, b["word"], -0.15)[0]
            if b["kind"] == "meme":
                ev.append({"at": a, "box": "media", "file": "movie_reference/" + b["file"]})
            else:
                ck = f"s_{b['source']}_{b['id']}"
                scene_clips.setdefault(ck, {b["source"]: b["id"], "label": b.get("title", "")[:80]})
                ev.append({"at": a, "box": "clip", "clip": ck})
            used_media.append(b)

        # ---------------- the pop-up meme beside the guide
        if L.get("pop"):
            p = L["pop"]
            ls = _pop_slot(spot, G)
            if ls[2] - ls[0] < Z["pop"]["w"] + 10:
                raise CompileError(f"line {i + 1}: no room for the pop-up beside the guide")
            cx = (ls[0] + ls[2]) / 2
            ev.append({"at": _anchor(W, p["word"])[0], "reaction": FACE_OF.get(L["expression"], "surprised"),
                       "face": FACE_OF.get(L["expression"], "surprised"), "file": "movie_reference/" + p["file"],
                       "dur": POP_CARD["dur"], "card": {"x": cx, "y": Z["pop"]["y"], "w": Z["pop"]["w"], "rotate": 0}})
        beat = {"id": f"l{i + 1}", "panel": 0, "narration": text, "events": ev,
                "camera_start": {"x": 540, "y": 960, "zoom": 1.0, "dur": 0.01} if i == 0 else False}
        if i == n_lines - 1:
            beat["interaction"] = False
        beats.append(beat)
        if ids:
            frames.append({"beat": beat["id"], "t": draw_pos[ids[-1]][3] + 0.9, "line": text})

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
        "voice_profile": "kindled_iron",
        "voice_file": {"path": meta["audio_path"], "sha256": meta["sha256"], "provider": "owner", "voice": "owner"},
        "voice_as_is": True, "exact_narration": True, "end_hold": 1.4, "ground": Z["guide"]["ground"], "camera_y": 960,
        "fill_min": 0.3, "max_visual_gap": 2.5, "walk_speed": WALK_SPEED, "pencil": True,
        "captions_box": {"x": Zc["x"] + Zc["w"] / 2, "y": Zc["y"], "w": Zc["w"], "size": Zc["size"], "min_scale": 0.6},
        "captions_chunk": {"max_words": 3, "min_words": 1, "max_chars": 16},
        "audit": {"max_words": 3, "one_line": True}, "caption_color": "ink", "caption_on": "accent",
        "require_memes": sum(1 for L in P if L.get("pop")), "max_media_uses": 2,
        "cast": {"guide": {"panel": 0, "x": route[0], "scale": 2.1, "facing": -1 if route[0] > 540 else 1, "accent": True}},
        "mediabox": {"x": Z["box"]["x"], "y": Z["box"]["y"], "w": Z["box"]["w"], "h": Z["box"]["h"], "verse_size": 56, "pad_x": 46},
        "clips": scene_clips,
        "preview": {"folder": meta["id"], "public_artifacts": False, "stage": "full",
                    "frames": [{"beat": f["beat"], "at": f["at"]} for f in pv]},
        "post": {"title": meta.get("title") or meta["id"].replace("-", " ").title()},
        "director": {"plan_lines": n_lines, "route": route, "walks": {str(k + 1): v[:2] for k, v in walks.items()}},
        "beats": beats,
    }
    return scene, pv
