"""Render one Kindled Iron scene JSON to a 1080x1920 MP4. No AI agent at render time.

    python -m kindled_iron.render kindled_iron/scenes/genesis-1.json --out storage/kindled_iron/genesis-1.mp4

Steps: the voice provider (ElevenLabs / Chatterbox / Kokoro, see tts.py) voices the beats ->
faster-whisper word timings on that audio -> every event's
"at" (a word of its beat, or seconds) becomes an absolute time -> page.html +
runtime.js build the board, stickmen and one GSAP timeline -> headless Chrome
(Playwright) seeks the timeline frame by frame and screenshots it -> FFmpeg
encodes the frames with the narration. Captions are part of the page, so they
are burned into every frame.

Options: --frames-only T1,T2,...  write PNG stills at those seconds (quick check)
         --safe-box               overlay the TikTok safe box (use with --frames-only)
         --reuse-audio            keep work/narration.wav + timings from the last run
         --chrome PATH            Chrome/Chromium binary (else CHROME_PATH / auto-detect)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENDOR = HERE / "vendor"
UPSTREAM = VENDOR / "stickman-animation-agent" / "components" / "characters"

WIDTH, HEIGHT, FPS = 1080, 1920, 30
PANEL_W = 1080
PALETTE = {
    "board": "#F4F1EA", "ink": "#222222", "inkSoft": "#55524C", "accent": "#CC5500",
    # flat, light "hand-coloured" fills (captions stay ink + accent)
    "water": "#A9CCE6", "waterLine": "#3D7DB0", "green": "#AED39A", "greenLine": "#4E8A3A", "leaf": "#93C47D",
    "trunk": "#9A6A43", "wool": "#F3EBD7", "woolGray": "#9C9C98", "fishBody": "#EBCF7E", "fishBelly": "#BDBDBA",
    "cloud": "#FFFFFF", "cloudShade": "#D7E7F3", "page": "#FBF6E8", "moon": "#F3E4A2", "starFill": "#F6D66A",
    "shadow": "#DCD5C8", "leafDark": "#5C9A4C", "marker": "#F7D3AE",
    "skin": "#E9C9A0", "robe": "#8A6A4F", "robeDark": "#6C503A", "controller": "#C9CED6",
}
# The host (guide) is drawn after the channel owner: brown skin, shoulder-length twisted locs with a
# middle part, small mustache + chin goatee, slightly hand-drawn head. A scene can turn it off ("look": false).
# Outfit: black short-sleeve button-up (light-blue collar, buttons, pocket, sleeve trim), black pants with a
# beige accent, dark shoes with beige soles, no scarf, bare arms.
HOST_LOOK = {"head": "hand", "hair": "locs", "beard": "goatee", "outfit": "buttonup",
             "colors": {"skin": "#8D5B3E", "hair": "#231915", "shirt": "#2A2C33", "pants": "#25262C", "shoe": "#2E2925"}}
HUD = {"x": 300, "y": 248, "scale": 1.25}   # DAY counter badge (top-left of the safe box: x 148-452, y 188-313)
NO_POP = {"darkness", "line", "frame", "waves", "hill", "rays", "strike", "cross", "inset", "sparkle"}
# TikTok safe area (owner's template). Important art + captions stay inside the box and out of the
# right-hand button column; the top 160 px and bottom 480 px are decoration only.
SAFE = {"x0": 120, "x1": 960, "y0": 160, "y1": 1440, "column": {"x0": 780, "x1": 960, "y0": 840, "y1": 1440}}
CAPTION = {"x": 450, "y": 1255, "w": 600, "size": 100}   # text box x 150-750 (outline stays < 780), shrinks to fit
TARGET_LEN = (61.0, 68.0)
MIN_WORDS = 120
EXPRESSIONS = ["neutral", "happy", "surprised", "thinking", "speaking", "focused"]
HAIRS = ["long-straight", "short-tufts"]


def log(msg: str) -> None:
    print(f"[kindled_iron] {msg}", flush=True)


# --------------------------------------------------------------- vendored SVG parts
def _svg_inner(path: Path) -> str:
    s = path.read_text(encoding="utf-8")
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    m = re.search(r"<svg[^>]*>(.*)</svg>", s, flags=re.S)
    s = (m.group(1) if m else s).strip()
    # Kindled Iron colours instead of upstream's ink / parchment
    s = s.replace("#1A1A1A", PALETTE["ink"]).replace("#E5DDD0", PALETTE["board"])
    return re.sub(r'stroke-width="([\d.]+)"', lambda m_: f'stroke-width="{float(m_.group(1)) * 1.6:g}"', s)


def vendor_parts() -> dict:
    # the head's paper-coloured fill only appears once the head is drawn
    head = _svg_inner(UPSTREAM / "tier1" / "heads" / "front.svg").replace(
        f'fill="{PALETTE["board"]}"', f'fill="{PALETTE["board"]}" data-fill="1" fill-opacity="0"')
    exprs = {n: _svg_inner(UPSTREAM / "tier1" / "expressions" / f"{n}.svg") for n in EXPRESSIONS
             if (UPSTREAM / "tier1" / "expressions" / f"{n}.svg").exists()}
    # faint guide strands (opacity < 1) would show through the face; keep the outer strands only
    hair = {n: re.sub(r'<path[^>]*opacity="0?\.\d+"[^>]*/>', "", _svg_inner(UPSTREAM / "tier1" / "hair" / f"{n}.svg"))
            for n in HAIRS}
    return {"head": head, "expressions": exprs, "hair": hair}


# --------------------------------------------------------------- timing
def words_of(text: str) -> list[str]:
    from kindled_iron.pacing import words_of as _w
    return _w(text)                      # [pause x] tags are never spoken or captioned


def resolve_at(at, beat_words: list[dict], beat_start: float, beat_end: float, used: dict,
               beat_pauses: list | None = None) -> float:
    """`at` = seconds after the beat starts, "end", a word of this beat ("God", "God#2" = second
    "God", "God+0.3" = 0.3 s after it starts), or "pause" / "pause#2" = inside the 1st / 2nd pause
    of this beat (after its 1st / 2nd sentence), so a drawing lands in the silence."""
    if at is None:
        return beat_start
    if isinstance(at, (int, float)):
        return beat_start + float(at)
    s = str(at).strip()
    em = re.fullmatch(r"end([+-][\d.]+)?", s)
    if em:                                   # "end" / "end+0.2": after the beat's last word
        return beat_end + float(em.group(1) or 0)
    pm = re.fullmatch(r"pause(?:#(\d+))?([+-][\d.]+)?", s)
    if pm:
        n = int(pm.group(1) or 1)
        if not beat_pauses or len(beat_pauses) < n:
            raise ValueError(f"this beat has no pause #{n}")
        return beat_pauses[n - 1][0] + 0.06 + float(pm.group(2) or 0)
    m = re.fullmatch(r"(.+?)(?:#(\d+))?([+-][\d.]+)?", s)
    word, nth, off = m.group(1), int(m.group(2) or 1), float(m.group(3) or 0)
    key = re.sub(r"[^a-z0-9]", "", word.lower())
    hits = [w for w in beat_words if re.sub(r"[^a-z0-9]", "", w["word"].lower().replace("’", "'")) == key]
    if len(hits) < nth:
        raise ValueError(f"word {word!r} (#{nth}) is not in this beat's narration")
    return hits[nth - 1]["start"] + off


def caption_chunks(words: list[dict], max_words: int = 3, max_chars: int = 13, min_words: int = 1) -> list[dict]:
    """Chunks of min_words..max_words words; a chunk ends at punctuation or a pause only once it has
    min_words (a pause over 0.8 s always ends it)."""
    chunks, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        text = " ".join(x["word"] for x in cur)
        nxt = words[i + 1] if i + 1 < len(words) else None
        punct = re.search(r"[.,;:!?]$", w["word"])
        pause = nxt["start"] - w["end"] if nxt is not None else 0.0
        gap = nxt is not None and pause > 0.35
        too_long = nxt is not None and len(text) + 1 + len(nxt["word"]) > max_chars
        enough = len(cur) >= min_words or pause > 0.8
        if len(cur) >= max_words or ((punct or gap) and enough) or too_long or nxt is None:
            chunks.append(cur)
            cur = []
    out = []
    for k, ch in enumerate(chunks):
        end = ch[-1]["end"] + 0.25
        if k + 1 < len(chunks):
            end = min(max(ch[-1]["end"], chunks[k + 1][0]["start"]), chunks[k + 1][0]["start"])
        out.append({"start": ch[0]["start"], "end": round(end, 3),
                    "words": [{"text": w["word"].upper(), "start": w["start"], "end": w["end"]} for w in ch]})
    return out


def srt(chunks: list[dict]) -> str:
    def ts(t: float) -> str:
        ms = int(round(t * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "\n".join(f"{i}\n{ts(c['start'])} --> {ts(c['end'])}\n{' '.join(w['text'] for w in c['words'])}\n"
                     for i, c in enumerate(chunks, 1))


# --------------------------------------------------------------- scene -> page data
def build_data(scene: dict, spans: list[tuple[float, float]], beat_words: list[list[dict]], duration: float,
               insets: dict | None = None, pauses: list | None = None) -> dict:
    insets = insets or {}
    pauses = pauses or []                     # [(start, end, beat)] silences between sentences
    ground = scene.get("ground", 1170)
    cast = {cid: {**c, "x": c["x"] + PANEL_W * c.get("panel", 0)} for cid, c in scene["cast"].items()}
    if "guide" in cast and cast["guide"].get("look", True) is not False:
        g = cast["guide"]
        cast["guide"] = {**HOST_LOOK, **g, "colors": {**HOST_LOOK["colors"], **(g.get("colors") or {})}}
    objects, events, captions = [], [], []
    ids = set()
    cam_y = scene.get("camera_y", 960)
    for b, beat in enumerate(scene["beats"]):
        start, end = spans[b]
        off = PANEL_W * beat.get("panel", 0)
        words = beat_words[b]
        used: dict = {}
        if beat.get("captions", True):
            captions += caption_chunks(words, **(scene.get("captions_chunk") or {}))
        cam = beat.get("camera_start")
        prev_panel = scene["beats"][b - 1].get("panel", 0) if b else None
        trans = beat.get("transition")
        if b and trans is None and beat.get("panel", 0) != prev_panel and cam is False \
                and not any(ev.get("do") == "walk" and ev.get("camera") for ev in beat.get("events", [])):
            trans = "slide"                      # a new panel with no walk: slide over by default
        # a scripture card stays at least 1 s after its quote: the scene change waits for it
        t_change = max([start] + [o["quote_end"] + 1.0 + 0.3 for o in objects if o["type"] == "scripture"
                                  and o["quote_end"] + 1.0 + 0.3 > start])
        if b and trans:
            events += transition_events(trans, t_change, off, cam if isinstance(cam, dict) else {}, cam_y, beat.get("whoosh"))
        elif cam is not False:
            cam = cam or {}
            events.append({"t": max(0.0, start - 0.25) if b else 0.0, "do": "camera",
                           "x": off + cam.get("x", 540), "y": cam.get("y", cam_y), "zoom": cam.get("zoom", 1.0),
                           "dur": cam.get("dur", 0.9 if b else 0.01)})
        for ev in beat.get("events", []):
            e = dict(ev)
            if isinstance(e.get("scripture"), dict):
                card_n = sum(1 for o in objects if o["type"] == "scripture")
                o, ev_draw = scripture_card(e, words, off, card_n, beat.get("id", b))
                objects.append(o)
                events.append(ev_draw)
                ids.add(o["id"])
                continue
            if "do" not in e and isinstance(e.get("reaction"), str):     # {"reaction": "<emotion>"}
                e["do"], e["who"], e["emotion"] = "reaction", e.get("who", "guide"), e.pop("reaction")
            if "do" not in e:                     # shorthand {"guide": "parachute", ...}
                who = next((k for k in scene["cast"] if isinstance(e.get(k), str)), None)
                if who:
                    e["do"], e["who"] = e.pop(who), who
            try:
                e["t"] = round(resolve_at(e.pop("at", None), words, start, end, used,
                                          [p for p in pauses if p[2] == b]), 3)
            except ValueError as err:
                raise SystemExit(f"beat {beat.get('id', b)}: {err}")
            kind = e.get("do")
            if b and trans and e["t"] < t_change and kind in ("place", "draw", "fade", "counter"):
                e["t"] = round(t_change, 3)            # nothing of the new scene happens before it is on screen
            if kind == "draw":
                if e["id"] in ids:
                    raise SystemExit(f"duplicate object id {e['id']!r}")
                if e.get("type") == "inset":
                    if "frames" not in e and e["id"] not in insets:
                        continue                      # no clip found: the inset is simply left out
                    e.update(insets.get(e["id"], {}))
                    # a real clip lands in the nearest pause (within 1.5 s before / 0.5 s after)
                    near = [p for p in pauses if p[1] - p[0] >= 0.3 and e["t"] - 1.5 <= p[0] <= e["t"] + 0.5] \
                        if scene.get("inset_snap", True) else []
                    if near:
                        p0 = min(near, key=lambda p: abs(p[0] - e["t"]))
                        e["t"] = round(p0[0] + 0.05, 3)
                ids.add(e["id"])
                obj = {k: v for k, v in e.items() if k not in ("t", "do", "dur", "pop", "sparkle", "hold", "instant")}
                obj["x"] = obj.get("x", 540) + off
                obj["y"] = obj.get("y", 900)
                objects.append(obj)
                pop = e.get("pop", obj["type"] not in NO_POP)
                events.append({"t": e["t"], "do": "draw", "id": e["id"], "dur": e.get("dur"), "pop": pop, "hold": e.get("hold"),
                               "instant": e.get("instant"),
                               **{k: e[k] for k in ("hit", "why", "main", "sound", "sound_dur", "hit_sound") if k in e}})
                if e.get("sparkle"):                  # a burst of little stars as it lands
                    sid = e["id"] + "_spk"
                    objects.append({"id": sid, "type": "sparkle", "x": obj["x"], "y": obj["y"], "r": e.get("sparkle_r", 120),
                                    "n": 6})
                    events.append({"t": round(e["t"] + 0.25, 3), "do": "draw", "id": sid, "dur": 0.3, "pop": False})
                continue
            if kind in ("walk", "drift"):
                e["to"] = e["to"] + off
                if e.get("camera"):
                    e["camX"] = e.get("camX", 540) + off
                    e.setdefault("camY", cam_y)
            if kind == "place" and "x" in e:
                e["x"] = e["x"] + off
            if kind == "camera":
                e["x"] = e.get("x", 540) + off
                e.setdefault("y", cam_y)
                e.setdefault("zoom", 1.0)
            if "tx" in e:
                e["tx"] += off
            events.append(e)
    events.sort(key=lambda e: e["t"])
    # Moving to a new panel: everything on earlier panels fades out as the guide sets off, so he
    # never walks over key text and no half-cut drawing edge slides across the screen.
    panel_of = {o["id"]: int(o["x"] // PANEL_W) for o in objects}
    faded: set[str] = set()
    for e in [e for e in events if (e["do"] == "walk" and e.get("camera")) or e.get("transition")]:
        new_panel = int((e.get("camX") if e["do"] == "walk" else e["x"]) // PANEL_W)
        old = [o["id"] for o in objects if panel_of[o["id"]] < new_panel and o["id"] not in faded]
        if old:
            faded.update(old)
            events.append({"t": max(0.0, e["t"] - 0.15), "do": "fade", "ids": old, "opacity": 0, "dur": 0.25})
    events.sort(key=lambda e: e["t"])
    hold_cards(events, objects)
    respond(events, objects)
    interaction_check(scene, events, objects, spans)
    events.sort(key=lambda e: e["t"])
    return {"width": WIDTH, "height": HEIGHT, "fps": FPS, "duration": duration, "ground": ground,
            "palette": PALETTE, "cast": cast, "objects": objects, "events": events, "captions": captions,
            "camera": {"x": 540, "y": cam_y, "zoom": 1.0}, "vendor": vendor_parts(), "safe": SAFE, "debugSafe": False,
            "captionSize": (scene.get("captions_box") or {}).get("size", CAPTION["size"]), "hud": HUD, "paper": None, "inboxReactions": [],
            "fillMin": scene.get("fill_min", 0.45), "captionBox": scene.get("captions_box") or {}}


def _norm_words(text: str) -> list[str]:
    from kindled_iron.scripture import words as w
    return w(text)


def wrap(text: str, size: int, width: int) -> list[str]:
    per = max(8, int(width / (0.43 * size)))         # Caveat bold: ~0.43 em a character
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > per:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return lines + ([cur] if cur else [])


def scripture_card(e: dict, words: list[dict], off: int, n: int, beat_id) -> tuple[dict, dict]:
    """A scripture card is written on exactly while the quote is spoken: its words are found in this
    beat's narration; the reference appears when the quote ends."""
    from kindled_iron.scripture import canonical

    card = e["scripture"]
    want = _norm_words(card["text"])
    said = [(_norm_words(w["word"]) or [""])[0] for w in words]
    hit = next((i for i in range(len(said) - len(want) + 1) if said[i:i + len(want)] == want), None)
    if hit is None:
        raise SystemExit(f"FAIL: beat {beat_id}: the scripture card text {card['text']!r} is not spoken in this beat")
    t0, t1 = words[hit]["start"], words[hit + len(want) - 1]["end"]
    size = int(e.get("size", 76))
    w = int(e.get("w", 800))
    lines = wrap(card["text"].strip().strip('"“”'), size, w - 130)
    if len(lines) > 3:
        size = int(size * 0.85)
        lines = wrap(card["text"].strip().strip('"“”'), size, w - 130)
    o = {"id": e.get("id", f"card{n + 1}"), "type": "scripture", "x": off + e.get("x", 540), "y": e.get("y", 430),
         "w": w, "size": size, "lines": lines, "ref": canonical(card["ref"]), "text": card["text"],
         "quote_end": round(t1, 3), "_t0": round(t0, 3), "_t1": round(t1 + 1.0, 3), "allow_overlap": e.get("allow_overlap", False), "over": e.get("over", [])}
    return o, {"t": round(t0, 3), "do": "draw", "id": o["id"], "dur": round(max(0.4, t1 - t0), 3), "pop": False}


def hold_cards(events: list[dict], objects: list[dict]) -> None:
    """A card stays on screen at least 1 s after its quote ends: earlier fades are pushed back,
    an earlier scene change is a SCRIPTURE WARNING."""
    for o in [o for o in objects if o["type"] == "scripture"]:
        until = o["quote_end"] + 1.0
        for e in events:
            if e["do"] == "fade" and o["id"] in (e.get("ids") or [e.get("id")]) and e["t"] < until:
                e["t"] = round(until, 3)
            if (e.get("transition") or (e["do"] == "walk" and e.get("camera"))) and o["quote_end"] - 0.3 < e["t"] < until:
                log(f"SCRIPTURE WARNING: {o['ref']} leaves the screen {until - e['t']:.1f} s too early (scene change)")
    events.sort(key=lambda e: e["t"])


def transition_events(trans, t0: float, off: int, cam: dict, cam_y: float, whoosh=None) -> list[dict]:
    """Scene change: cut, slide, zoom or wipe to the next panel (the guide re-enters with an action)."""
    kind = trans if isinstance(trans, str) else trans.get("type", "slide")
    x, y, z = off + cam.get("x", 540), cam.get("y", cam_y), cam.get("zoom", 1.0)
    base = {"do": "camera", "x": x, "y": y, "transition": kind, "whoosh": whoosh}
    if kind == "cut":
        return [{**base, "t": max(0.0, t0 - 0.05), "zoom": z, "dur": 0.01}]
    if kind == "zoom":                      # punch into the old scene, cut, pull back out of the new one
        return [{"t": max(0.0, t0 - 0.35), "do": "camera_zoom_out_of", "zoom": 1.35, "dur": 0.3},
                {**base, "t": max(0.0, t0 - 0.05), "zoom": 1.35, "dur": 0.01},
                {"t": t0, "do": "camera", "x": x, "y": y, "zoom": z, "dur": 0.45, "ease": "power2.out"}]
    if kind == "wipe":
        return [{"t": max(0.0, t0 - 0.35), "do": "wipe", "dur": 0.7},
                {**base, "t": max(0.0, t0 - 0.02), "zoom": z, "dur": 0.01}]
    return [{**base, "t": max(0.0, t0 - 0.3), "zoom": z, "dur": 0.55, "ease": "power2.inOut"}]      # slide


GUIDE_TOUCHES = {"point", "reach", "touch", "pet", "ride", "peek", "climb", "shield_eyes", "look"}
RESPONSE = {"tree": "wiggle", "plant": "wiggle", "cloud": "wiggle", "waves": "splash", "fish": "splash",
            "animal": "wiggle", "sun": "pulse", "light": "pulse", "moon": "pulse", "star": "pulse", "stars": "pulse",
            "hill": "dirt", "globe": "wiggle", "book": "pulse", "scripture": None, "frame": None, "inset": None}


def respond(events: list[dict], objects: list[dict]) -> None:
    """The drawing a character touches answers back: the tree shakes, water splashes, the sun pulses."""
    by_id = {o["id"]: o for o in objects}
    for e in list(events):
        if e.get("do") not in GUIDE_TOUCHES or e.get("respond") is False:
            continue
        o = by_id.get(e.get("toward") or e.get("on"))
        if not o:
            continue
        kind = RESPONSE.get(o["type"], "pulse")
        if kind is None:
            continue
        t = round(e["t"] + 0.25, 3)
        if kind in ("splash", "dirt"):
            sid = f"{o['id']}_{kind}_{int(t * 100)}"
            objects.append({"id": sid, "type": "splash", "x": o["x"], "y": o["y"] - (30 if kind == "splash" else 0),
                            "r": 90, "n": 9, "dirt": kind == "dirt"})
            events.append({"t": t, "do": "draw", "id": sid, "dur": 0.3, "pop": False, "hold": 0.7})
        else:
            events.append({"t": t, "do": kind, "id": o["id"]})


def interaction_check(scene: dict, events: list[dict], objects: list[dict], spans) -> None:
    """Every scene: the guide touches, points at or reacts to at least one drawing."""
    ids = {o["id"] for o in objects}
    for b, beat in enumerate(scene["beats"]):
        a, z = spans[b][0], spans[b + 1][0] if b + 1 < len(spans) else spans[b][1] + 5
        hit = any(e.get("who") == "guide" and e.get("do") in GUIDE_TOUCHES | {"present"} and
                  (e.get("toward") in ids or e.get("on") in ids or e.get("do") in ("present", "shield_eyes")) and a <= e["t"] < z
                  for e in events)
        if not hit and beat.get("interaction", True):
            log(f"INTERACTION WARNING beat {beat.get('id', b)}: the guide doesn't touch, point at or react to any drawing")


def write_page(data: dict, work: Path) -> Path:
    page = (HERE / "runtime" / "page.html").read_text(encoding="utf-8")
    cap = {**CAPTION, **(data.get("captionBox") or {})}
    rep = {
        "__W__": str(WIDTH), "__H__": str(HEIGHT), "__BOARD__": PALETTE["board"], "__INK__": PALETTE["ink"],
        "__ACCENT__": PALETTE["accent"], "__CAPTION_X__": str(cap["x"]), "__CAPTION_Y__": str(cap["y"]), "__CAPTION_W__": str(cap["w"]),
        "__CAPTION_SIZE__": str(cap["size"]),
        "__FONT__": (VENDOR / "fonts" / "Caveat.ttf").as_uri(),
        "__GSAP__": (VENDOR / "gsap" / "gsap.min.js").as_uri(),
        "__RUNTIME__": (HERE / "runtime" / "runtime.js").as_uri(),
        "__DATA__": json.dumps(data),
    }
    for k, v in rep.items():
        page = page.replace(k, v)
    out = work / "index.html"
    out.write_text(page, encoding="utf-8")
    return out


# --------------------------------------------------------------- capture
def find_chrome(explicit: str | None) -> str | None:
    cands = [explicit, os.environ.get("CHROME_PATH"), shutil.which("google-chrome"), shutil.which("google-chrome-stable"),
             shutil.which("chromium"), shutil.which("chromium-browser"), "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"]
    for c in cands:
        if c and Path(c).exists():
            return c
    return None  # let Playwright use its own downloaded Chromium


def layout_check(page, duration: float, work: Path) -> list[dict]:
    """Sample the timeline every 0.2 s: safe box, right button column, a character over key
    text, a walking character passing through another. Warnings only (logged + checks.json)."""
    ranges: dict[str, list] = {}
    t = 0.0
    while t <= duration:
        for msg in page.evaluate(f"window.kiSeek({t:.3f}) && window.kiCheck({t:.3f})"):
            r = ranges.setdefault(msg, [])
            if r and t - r[-1][1] <= 0.25:
                r[-1][1] = t
            else:
                r.append([t, t])
        t = round(t + 0.2, 3)
    out = [{"issue": m, "from": a, "to": b} for m, rs in ranges.items() for a, b in rs
           if not m.startswith("SPARSE") or b - a >= 1.5]          # sparse only counts over 1.5 s
    out.sort(key=lambda x: x["from"])
    (work / "checks.json").write_text(json.dumps(out, indent=1))
    for x in out:
        log(f"LAYOUT WARNING {x['from']:.1f}-{x['to']:.1f} s: {x['issue']}")
    log(f"layout check: {len(out)} warning(s)" if out else "layout check: OK (safe box, text, walks, overlaps)")
    backwards = [x for x in out if x["issue"].startswith("WALK-FACING")]
    if backwards:
        raise SystemExit("FAIL: a character walks backwards: " + "; ".join(
            f"{x['issue']} at {x['from']:.1f}-{x['to']:.1f} s" for x in backwards))
    return out


VISUAL_EVENTS = {"freeze", "lean_on", "place", "sit", "lie_down", "swim", "float", "parachute", "pop_up", "climb", "jump", "fall", "ride",
                 "peek", "pet", "shield_eyes", "stand", "look_viewer", "ghost", "wipe", "touch", "size", "drift",
                 "rise", "drop", "light_burst", "paper", "express", "fade",
                 "move", "wiggle", "draw", "walk", "point", "reach", "wave", "cheer", "react", "shrug", "present", "look", "shake",
                 "camera", "pulse", "enter", "reaction", "counter", "inset", "sparkle", "kneel"}


def pacing_check(events: list[dict], duration: float, max_gap: float = 2.0) -> list[tuple[float, float]]:
    """Something new or moving at least every ~2 s (ambient motion not counted)."""
    times = sorted({round(e["t"], 2) for e in events if e["do"] in VISUAL_EVENTS} | {0.0, duration})
    gaps = [(a, b) for a, b in zip(times, times[1:]) if b - a > max_gap]
    for a, b in gaps:
        log(f"PACING WARNING {a:.1f}-{b:.1f} s: nothing new for {b - a:.1f} s")
    if not gaps:
        log(f"pacing check: OK (something new at least every {max_gap:.0f} s)")
    return gaps


def empty_check(mp4: Path) -> list[tuple[float, float]]:
    """Near-empty screen for more than 1 s inside the safe art area (captions excluded).
    Near-empty = under 2.5 % ink (a lone stickman is ~1.7 %)."""
    w, h = SAFE["x1"] - SAFE["x0"], CAPTION["y"] - 20 - SAFE["y0"]
    vf = f"crop={w}:{h}:{SAFE['x0']}:{SAFE['y0']},negate,blackdetect=d=1.0:pix_th=0.12:pic_th=0.975"
    res = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(mp4), "-vf", vf, "-an", "-f", "null", "-"],
                         capture_output=True, text=True)
    spans = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", res.stderr)]
    for a, b in spans:
        log(f"EMPTY-SCREEN WARNING {a:.1f}-{b:.1f} s: almost nothing drawn for {b - a:.1f} s")
    if not spans:
        log("empty-screen check: OK (no stretch over 1 s)")
    return spans


def safe_overlay(src: Path, dst: Path) -> None:
    """Second copy of the final video with the safe box drawn on (the final file stays clean)."""
    s, c = SAFE, SAFE["column"]
    vf = ",".join([
        f"drawbox=x=0:y=0:w=iw:h={s['y0']}:color=black@0.18:t=fill",
        f"drawbox=x=0:y={s['y1']}:w=iw:h=ih-{s['y1']}:color=black@0.18:t=fill",
        f"drawbox=x={c['x0']}:y={c['y0']}:w={c['x1'] - c['x0']}:h={c['y1'] - c['y0']}:color=red@0.22:t=fill",
        f"drawbox=x={s['x0']}:y={s['y0']}:w={s['x1'] - s['x0']}:h={s['y1'] - s['y0']}:color=0x00AA00@0.9:t=4"])
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", vf, "-c:v", "libx264", "-crf", "21",
                    "-preset", "veryfast", "-c:a", "copy", str(dst)], check=True)


def capture(page_file: Path, out_mp4: Path | None, audio: Path | None, duration: float, chrome: str | None,
            stills: list[float] | None = None, still_dir: Path | None = None) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        exe = find_chrome(chrome)
        log(f"Chrome: {exe or 'playwright default'}")
        browser = pw.chromium.launch(executable_path=exe, args=["--allow-file-access-from-files", "--font-render-hinting=none",
                                                                "--disable-gpu", "--hide-scrollbars"])
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type in ("error", "warning") and errors.append(m.text))
        page.goto(page_file.as_uri())
        try:
            page.wait_for_function("window.KI_READY === true", timeout=60000)
        except Exception:
            raise SystemExit("page never became ready: " + "; ".join(errors or ["no error reported"]))
        for e in errors:
            log(f"page: {e}")
        layout_check(page, duration, page_file.parent)
        # GSAP can't reliably undo instant "set" steps when scrubbed backwards: start again from a fresh
        # page so the capture only ever plays forwards
        page.goto(page_file.as_uri())
        page.wait_for_function("window.KI_READY === true", timeout=60000)
        if stills is not None:
            stills = sorted(stills)
            still_dir.mkdir(parents=True, exist_ok=True)
            for t in stills:
                page.evaluate(f"window.kiSeek({t})")
                page.screenshot(path=str(still_dir / f"frame_{t:05.2f}.png"))
            browser.close()
            return
        frames = int(round(duration * FPS))
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
               "-i", str(audio), "-map", "0:v", "-map", "1:a", "-af", "apad", "-t", f"{frames / FPS:.3f}",
               "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", "-r", str(FPS),
               "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out_mp4)]
        enc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for i in range(frames):
            page.evaluate(f"window.kiSeek({i / FPS:.5f})")
            enc.stdin.write(page.screenshot(type="jpeg", quality=93))
            if i % (FPS * 5) == 0:
                log(f"frame {i}/{frames}")
        enc.stdin.close()
        if enc.wait() != 0:
            raise SystemExit("ffmpeg encode failed")
        browser.close()


def post_text(scene: dict) -> dict:
    """Title / caption / description for the TikTok draft (the description carries the Bible credit)."""
    p = dict(scene.get("post") or {})
    p.setdefault("title", scene.get("title", scene.get("id", "")))
    if any(isinstance(ev.get("scripture"), dict) for b in scene["beats"] for ev in b.get("events", [])):
        credit = "Scripture: World English Bible"
        if credit not in p.get("description", ""):
            p["description"] = (p.get("description", "") + "\n" + credit).strip()
    return p


# --------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene")
    ap.add_argument("--out", default=None)
    ap.add_argument("--work", default=None)
    ap.add_argument("--frames-only", default=None)
    ap.add_argument("--reuse-audio", action="store_true")
    ap.add_argument("--chrome", default=None)
    ap.add_argument("--whisper-model", default="base.en")
    ap.add_argument("--tts", choices=["elevenlabs", "chatterbox", "kokoro"], default=None,
                    help="voice provider (default: the voice profile's tts_provider)")
    ap.add_argument("--safe-box", action="store_true", help="overlay the TikTok safe box (debug stills)")
    ap.add_argument("--debug-copy", action="store_true", help="also write <name>_safebox.mp4 with the safe box drawn on")
    ap.add_argument("--recording", default=None, help="the owner's own reading (private file): his delivery in his cloned "
                    "voice via ElevenLabs speech-to-speech, fallback text-to-speech matched to it; no pause edits")
    ap.add_argument("--music", default=None, help="music track name (vendor/sfx/lib/music_<name>.ogg); default: channel music_track")
    a = ap.parse_args()

    scene_path = Path(a.scene)
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    sid = scene.get("id", scene_path.stem)
    from kindled_iron import script_check

    scene = script_check.check(scene, log, MIN_WORDS)
    from kindled_iron import scripture

    verse_results = scripture.check_scene(scene, log)      # fails the render on any misquote
    out = Path(a.out or f"storage/kindled_iron/{sid}.mp4").resolve()
    work = Path(a.work or out.parent / f"{sid}_work").resolve()
    work.mkdir(parents=True, exist_ok=True)
    wav, timing_file = work / "narration.wav", work / "timings.json"
    texts = [b["narration"] for b in scene["beats"]]
    end_hold = float(scene.get("end_hold", 1.4))

    if a.reuse_audio and timing_file.exists() and json.loads(timing_file.read_text())["texts"] == texts \
            and "pauses" in json.loads(timing_file.read_text()):
        t = json.loads(timing_file.read_text())
        spans, beat_words, voice_meta = [tuple(s) for s in t["spans"]], t["words"], t.get("voice", {})
        pauses = [tuple(p) for p in t["pauses"]]
        log("reusing narration + timings")
    else:
        import soundfile as sf

        from kindled_iron import pacing, tts, whisper_transcribe as wt

        profile = tts.load_profile(scene.get("voice_profile", "kindled_iron"))
        if scene.get("voice", {}).get("kokoro"):          # per-scene Kokoro override (voice, speed, lang)
            profile["kokoro"] = {**profile.get("kokoro", {}), **scene["voice"]["kokoro"]}
        profile["_end_hold"] = end_hold
        provider = a.tts or profile.get("tts_provider", "kokoro")
        segs = pacing.plan(texts, profile)
        raw = work / "narration_raw.wav"
        if a.recording:
            from kindled_iron import recording_voice

            voice_meta = recording_voice.voice(Path(a.recording), [w for txt in texts for w in words_of(txt)], raw,
                                               profile, work, log)
        else:
            voice_meta = tts.voice(pacing.provider_text(segs), raw, profile, provider, log)
        audio_len = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                                   "-of", "csv=p=0", str(raw)]).decode().strip())
        # Word timings always come from the audio that was actually used.
        heard = wt.transcribe(raw, a.whisper_model)
        flat = [w for txt in texts for w in words_of(txt)]
        log(f"voice audio {audio_len:.2f} s, whisper heard {len(heard)} of {len(flat)} words")
        aligned = wt.align(flat, heard, (0.0, audio_len))
        # Pauses: every sentence gap is set to its target on the final audio; timings shift with it.
        audio, sr = sf.read(raw, dtype="float32")
        if a.recording:      # his delivery stays exactly as read: no trimming, no pause insertion
            pace_stats = {"mode": "recording", "longest_silence": round(max(
                [aligned[i + 1]["start"] - aligned[i]["end"] for i in range(len(aligned) - 1)] or [0]), 2)}
            log(f"pacing: the recording's own pauses (longest {pace_stats['longest_silence']:.2f} s), no edits")
        else:
            audio, aligned, pace_stats = pacing.enforce(audio, sr, aligned, segs, profile, log)
        sf.write(wav, audio, sr)
        beat_words, k = [], 0
        for txt in texts:
            n = len(words_of(txt))
            beat_words.append(aligned[k:k + n])
            k += n
        pauses, k = [], 0
        for i, sg in enumerate(segs[:-1]):
            k += sg.n_words
            pauses.append((aligned[k - 1]["end"], aligned[k]["start"], sg.beat))
        # a beat starts in the pause before it, so its first drawing / walk lands in the silence
        spans = [((beat_words[b - 1][-1]["end"] + 0.1) if b else 0.0, bw[-1]["end"]) for b, bw in enumerate(beat_words)]
        voice_meta["pacing"] = {**pace_stats, "segments": [{"text": sg.text, "pause": sg.pause, "why": sg.why} for sg in segs]}
        timing_file.write_text(json.dumps({"texts": texts, "spans": spans, "words": beat_words, "heard": heard,
                                           "pauses": pauses, "voice": voice_meta}, indent=1))

    from kindled_iron import effects, insets as insets_mod, private_media
    from kindled_iron import tts as tts_mod

    chan = tts_mod.load_profile(scene.get("voice_profile", "kindled_iron"))
    third_party = private_media.enabled(chan)
    log(f"third-party clips/images: {'on' if third_party else 'off'}"
        f"{'' if not third_party else ' (private folders ' + ('found' if private_media.root() else 'NOT available') + ')'}")
    memes = private_media.resolve_scene(scene, chan, work, log)       # meme clips or their pinned fallbacks
    clips = insets_mod.fetch(scene, work, log)          # network step, BEFORE the render
    duration = round(spans[-1][1] + end_hold, 3)
    lo, hi = chan.get("length_target", TARGET_LEN)
    w_lo, w_hi = chan.get("wpm_target", [165, 185])
    n_words = sum(len(words_of(x)) for x in texts)
    wpm = n_words / duration * 60
    voice_meta["wpm"] = round(wpm, 1)
    log(f"Length: {duration:.1f} s (target {lo:.0f}-{hi:.0f}); pace {wpm:.0f} words/min over {n_words} words "
        f"(target {w_lo}-{w_hi})")
    if not w_lo <= wpm <= w_hi:
        log(f"WARNING: pace {wpm:.0f} wpm is outside {w_lo}-{w_hi}")
    if duration < lo:
        log(f"WARNING: under {lo:.0f} s. Fine only if the story is complete; never pad it.")
    elif duration > hi:
        log(f"WARNING: over {hi:.0f} s")
    data = build_data(scene, spans, beat_words, duration, clips, pauses)
    data["inboxReactions"], meme_images = effects.apply_reaction_rules(data["events"], scene, spans, beat_words, work, log,
                                                                       data, third_party)
    data["events"].sort(key=lambda e: e["t"])
    # a meme clip with its own audio may play after the last word: the video runs until it ends
    by_id = {o["id"]: o for o in data["objects"]}
    overlays = [(e["t"], by_id[e["id"]]["audio_file"], by_id[e["id"]]["clip_dur"]) for e in data["events"]
                if e["do"] == "draw" and by_id.get(e["id"], {}).get("audio_file")]
    for t0, _, d in overlays:
        if t0 + d + 0.8 > duration:
            duration = round(t0 + d + 0.8, 3)
            data["duration"] = duration
            log(f"meme clip audio runs to {t0 + d:.1f} s: video length {duration:.1f} s")
    data["events"] = [e for e in data["events"] if not e.get("_drop")]
    data["paper"] = effects.paper_texture(work, PALETTE["board"])
    data["debugSafe"] = a.safe_box
    pacing_check(data["events"], duration, float(scene.get("max_visual_gap", 2.0)))
    (work / "captions.srt").write_text(srt(data["captions"]), encoding="utf-8")
    page = write_page(data, work)
    log(f"{len(data['objects'])} objects, {len(data['events'])} events, {len(data['captions'])} caption chunks, {duration:.2f} s")

    if a.frames_only:
        stills = [float(x) for x in a.frames_only.split(",")]
        capture(page, None, None, duration, a.chrome, stills, work / "stills")
        log(f"stills in {work / 'stills'}")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    from kindled_iron import sound

    cues = sound.plan(data["events"], data["objects"], scene, spans)
    music = {"track": a.music or scene.get("music_track") or chan.get("music_track"), "lift_at": None}
    for b, beat in enumerate(scene["beats"]):
        if beat.get("music_lift") is not None:      # a small lift at the ending, from this word on
            music["lift_at"] = resolve_at(beat["music_lift"], beat_words[b], spans[b][0], spans[b][1], {})
    flat_words = [w for bw in beat_words for w in bw]
    mixed = sound.mix(wav, cues, scene, spans, flat_words, duration, work / "mix.wav", work / "mix_novoice.wav", music, log,
                      overlays=[(t0, Path(f)) for t0, f, _ in overlays])
    snd = sound.report(cues, mixed["beds"], duration)
    snd["lufs"] = mixed["lufs"]
    (work / "sounds.json").write_text(json.dumps(snd, indent=1))
    log(f"sounds: {snd['cues']} cues, longest stretch without a new sound {snd['longest_gap']:.1f} s "
        f"(at {snd['longest_gap_at']:.1f} s), final {mixed['lufs']:.1f} LUFS")
    capture(page, out, work / "mix.wav", duration, a.chrome)
    novoice = out.with_name(out.stem + "_novoice.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(out), "-i", str(work / "mix_novoice.wav"), "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", str(novoice)], check=True)
    log(f"voice-muted copy: {novoice}")
    shutil.copy(work / "sounds.json", out.with_name(out.stem + "_sounds.json"))
    if (work / "insets_contact_sheet.jpg").exists():
        shutil.copy(work / "insets_contact_sheet.jpg", out.with_name(out.stem + "_insets.jpg"))
    shutil.copy(work / "captions.srt", out.with_suffix(".srt"))
    shutil.copy(work / "sources.json", out.with_name(out.stem + "_sources.json"))
    empty = empty_check(out)
    words = sum(len(words_of(x)) for x in texts)
    meta = {"scene": sid, "duration": duration, "words": words, "voice": voice_meta,
            "insets": json.loads((work / "sources.json").read_text()), "sfx_cues": len(cues),
            "longest_sound_gap": snd["longest_gap"], "lufs": mixed["lufs"], "empty_stretches": empty,
            "verse_check": verse_results, "third_party": {"enabled": third_party, "clips": memes, "images": meme_images},
            "post": post_text(scene),
            "audio": {k: mixed.get(k) for k in ("lufs", "voice_lufs", "true_peak", "lf_burst")}}
    out.with_name(out.stem + "_meta.json").write_text(json.dumps(meta, indent=1))
    p = meta["post"]             # caption file the publisher reads
    out.with_name(out.stem + ".post.txt").write_text(
        f"title: {p.get('title', '')}\ncaption: {p.get('caption', '')}\nthreads: {p.get('threads', '')}\n"
        f"description: {p.get('description', '')}\n", encoding="utf-8")
    if a.debug_copy:
        dbg = out.with_name(out.stem + "_safebox.mp4")
        safe_overlay(out, dbg)
        log(f"debug copy with the safe box: {dbg}")
    log(f"wrote {out} ({duration:.1f} s, {words} words, voice {voice_meta.get('provider_used', '?')}"
        f"{' = fallback voice' if voice_meta.get('fallback') else ''})")


if __name__ == "__main__":
    sys.exit(main())
