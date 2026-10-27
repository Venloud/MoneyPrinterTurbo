"""The media box: ONE hand-drawn framed box that holds the real clips, and the Bible verses typed into it.

Opt-in per scene ("mediabox" in the scene JSON); scenes without it render exactly as before.

    "mediabox": {"x": 540, "y": 455, "w": 820, "h": 500, "verse_size": 62},
    "clips": {"cash": {"pexels": "5466769", "start": 1.0, "group": "cash"}, ...},
    "clip_limits": {"cash": 3},
    events in a beat:
      {"at": "selling-0.2", "box": "clip", "clip": "car_lot", "start": 4.0}   start = second inside the source clip
      {"box": "verse", "scripture": {"ref": "Hebrews 13:5", "text": "..."}, "split_after": "have"}
      {"at": "Your-0.2", "box": "off"}                                          the box leaves (end of video)
      {"at": "heart-0.2", "box": "heart"}                                       a drawn heart on the box page
      {"at": "Your-0.1", "box": "split", "left": "cash", "right": "bible"}      two shots side by side in the box
      {"at": "work", "box_bullet": "WORK"} ... {"at": "The", "box_bullets_clear": true}   cumulative check bullets
    clip options: "crop": [x, y, w, h] (fractions) for this use; "range_start": second to start at.
    clips may say "distinct": true: every use gets a range of the source that no other use has shown (else FAIL);
    other clips continue where the last use stopped and wrap round when the source runs out.

Rules (all checked here, the render stops on any of them):
- a clip segment runs until the next request; a long line loops its clip;
- the same clip never twice in a row; a clip "group" (e.g. cash) at most clip_limits[group] times;
- a verse REPLACES the clip: each word of the quote is typed letter by letter and fully on screen by 70 % of its
  spoken duration; an orange caret follows the typing; the reference appears right after the quote and the card
  holds 1 s after it (a request that would cut it short waits); "split_after": the quote goes on a second page
  after that word;
- pinned clips are required: a pin that can't be fetched fails the render (never a silent gap);
- no media, no frame: the box is drawn only while a segment holds something ("off" removes it, and the video may
  start with no box at all); each clip / picture gets a frame of ITS OWN shape (fitted inside the box area: the
  whole picture, minimal padding or cropping), never a stretched or empty frame;
- {"box": "diagram", "file": ..., "rect": [x, y, w, h]}: a whole diagram (director/diagram.py), the image scaled
  uniformly to exactly that rectangle, no frame around it.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from kindled_iron import insets as insets_mod

HERE = Path(__file__).resolve().parent
TYPE_SHARE = 0.70          # a word is fully typed by 70 % of its spoken duration
HOLD = 1.0                 # the card stays 1 s after the reference appears
LEAD = 0.25                # the page appears this long before the first letter


def _norm(text: str) -> list[str]:
    from kindled_iron.scripture import words
    return words(text)


def verse_segment(ev: dict, words: list[dict], box: dict, beat_id) -> dict:
    """Typing schedule for one verse: pages -> lines -> per-letter times."""
    from kindled_iron.scripture import canonical

    card = ev["scripture"]
    tokens = card["text"].split()
    want = _norm(card["text"])
    said = [(_norm(w["word"]) or [""])[0] for w in words]
    hit = next((i for i in range(len(said) - len(want) + 1) if said[i:i + len(want)] == want), None)
    if hit is None and not ev.get("paced"):
        raise SystemExit(f"FAIL: beat {beat_id}: the verse {card['text']!r} is not spoken word for word in this beat")
    if hit is None:
        # "paced": the line names the reference but does not quote it (a paraphrase): the WEB text types across the
        # spoken words from the first word after "from" (a word of the beat) to the beat's last word.
        k0 = next((i for i, w in enumerate(said) if ev.get("from") and w == (_norm(ev["from"]) or [""])[0]), 0)
        span = words[k0:] or words
        t0, t1 = span[0]["start"], max(span[0]["start"] + 1.0, span[-1]["end"] - 0.25)
        n_tok = max(1, len(tokens))
        tok_word = [{"start": round(t0 + (t1 - t0) * i / n_tok, 3), "end": round(t0 + (t1 - t0) * (i + 1) / n_tok, 3)}
                    for i in range(n_tok)]
        hit, want = 0, [None]
        quote_word = {"end": t1}
    else:
        tok_word, k = [], hit
        for tok in tokens:
            n = len(_norm(tok))
            tok_word.append(words[k] if n else words[min(k, hit + len(want) - 1)])
            k += n
        quote_word = words[hit + len(want) - 1]
    def times_of(tok: str, w: dict) -> list[float]:
        ts, te = w["start"], w["start"] + TYPE_SHARE * max(0.05, w["end"] - w["start"])
        return [round(ts + (te - ts) * j / len(tok), 3) for j in range(len(tok))]
    split = ev.get("split_after")
    cut = len(tokens)
    if split:
        idx = [i for i, tok in enumerate(tokens) if _norm(tok) and _norm(tok)[-1] == _norm(split)[0]]
        if not idx:
            raise SystemExit(f"FAIL: beat {beat_id}: split_after {split!r} is not in the verse")
        cut = idx[0] + 1
    groups = [list(range(0, cut))] + ([list(range(cut, len(tokens)))] if cut < len(tokens) else [])
    size = int(box.get("verse_size", 62))
    pages = []
    for g, ids in enumerate(groups):
        toks = [tokens[i] for i in ids]
        if g == 0:
            toks[0] = "\u201C" + toks[0]
        if g == len(groups) - 1:
            toks[-1] = toks[-1] + "\u201D"
        text, times = "", []
        for j, tok in enumerate(toks):
            tt = times_of(tok, tok_word[ids[j]])
            text += tok
            times += tt
            if j < len(toks) - 1:
                text += " "
                times.append(tt[-1])
        # lines are wrapped in the page with the real font (runtime); every letter keeps its own time
        pages.append({"t": round(min(times), 3), "text": text, "times": times})
    quote_end = quote_word["end"]
    first = pages[0]["t"]
    return {"kind": "verse", "ref": canonical(card["ref"]), "text": card["text"], "pages": pages,
            "first_letter": first, "ref_t": round(quote_end + 0.05, 3), "hold_until": round(quote_end + 0.05 + HOLD, 3),
            "verse_size": size}


def plan(scene: dict, spans: list, beat_words: list, pauses: list, duration: float, resolve_at, log) -> list[dict]:
    """Box requests in time order -> segments [{kind, t0, t1, ...}] (no clip frames yet)."""
    box = scene["mediabox"]
    reqs = []
    for b, beat in enumerate(scene["beats"]):
        start, end = spans[b]
        for ev in beat.get("events", []):
            if "box" not in ev:
                continue
            if ev["box"] == "verse":
                seg = verse_segment(ev, beat_words[b], box, beat.get("id", b))
                reqs.append((seg["first_letter"] - LEAD, seg))
                continue
            t = resolve_at(ev.get("at"), beat_words[b], start, end, {}, [p for p in pauses if p[2] == b])
            if ev["box"] == "clip":
                if ev["clip"] not in scene.get("clips", {}):
                    raise SystemExit(f"FAIL: beat {beat.get('id', b)}: clip {ev['clip']!r} is not in the scene's clips")
                reqs.append((max(0.0, t), {"kind": "clip", "clip": ev["clip"], "start": ev.get("range_start", ev.get("start")),
                                           "crop": ev.get("crop"), "cue": ev.get("at"), "beat": beat.get("id", b)}))
            elif ev["box"] == "split":
                for side in ("left", "right"):
                    if ev[side] not in scene.get("clips", {}):
                        raise SystemExit(f"FAIL: beat {beat.get('id', b)}: clip {ev[side]!r} is not in the scene's clips")
                reqs.append((t, {"kind": "split", "left": ev["left"], "right": ev["right"], "cue": ev.get("at"), "beat": beat.get("id", b)}))
            elif ev["box"] == "media":         # a private file (owner upload): image, gif, mp4, mov, webp
                reqs.append((max(0.0, t), {"kind": "media", "file": ev["file"], "fallback": ev.get("fallback"), "fit": ev.get("fit"),
                                           "start": ev.get("start"), "crop": ev.get("crop"), "cue": ev.get("at"), "beat": beat.get("id", b)}))
            elif ev["box"] == "diagram":       # a whole diagram, no frame (director/diagram.py placed it)
                reqs.append((max(0.0, t), {"kind": "diagram", "file": ev["file"], "rect": ev["rect"],
                                           "views": ev.get("views") or [], "cue": ev.get("at"), "beat": beat.get("id", b)}))
            elif ev["box"] == "heart":
                reqs.append((t, {"kind": "heart", "cue": ev.get("at"), "beat": beat.get("id", b)}))
            elif ev["box"] == "off":
                reqs.append((t, {"kind": "off"}))
    reqs.sort(key=lambda r: r[0])
    segs, hold = [], 0.0
    for t, seg in reqs:
        if t < hold - 1e-3:
            log(f"media box: {seg['kind']} {seg.get('clip', seg.get('ref', ''))} waits {hold - t:.2f} s for the verse card to hold 1 s")
            t = hold
        if segs:
            segs[-1]["t1"] = round(t, 3)
        seg = {**seg, "t0": round(max(0.0, t), 3)}
        segs.append(seg)
        hold = seg.get("hold_until", 0.0)
    if segs:
        segs[-1]["t1"] = round(max(duration, segs[-1].get("hold_until", 0.0)), 3)
    segs = [s for s in segs if s["kind"] != "off" and s["t1"] - s["t0"] > 0.05]
    # rules: never the same footage twice in a row; clip groups (cash) capped
    prev: set = set()
    counts: dict[str, int] = {}
    clips = scene["clips"]
    for s in segs:
        keys = [s["clip"]] if s["kind"] == "clip" else [s["left"], s["right"]] if s["kind"] == "split" else []
        pins = {clips[k].get("pexels") or k for k in keys} | ({"file:" + s["file"]} if s["kind"] in ("media", "diagram") else set())
        if pins & prev:
            raise SystemExit(f"FAIL: footage {sorted(pins & prev)} twice in a row at {s['t0']:.1f} s")
        prev = pins
        for k in keys:
            g = clips[k].get("group")
            if g:
                counts[g] = counts.get(g, 0) + 1
    uses: dict[str, int] = {}
    for s in segs:
        keys = [s["clip"]] if s["kind"] == "clip" else [s["left"], s["right"]] if s["kind"] == "split" else []
        for key in [clips[k].get("pexels") or k for k in keys] + (["file:" + s["file"]] if s["kind"] == "media" else []):
            uses[key] = uses.get(key, 0) + 1
    lim = scene.get("max_media_uses")
    over = {k: v for k, v in uses.items() if lim is not None and v > lim}
    if over:
        raise SystemExit(f"FAIL: used more than {lim} times: {over}")
    for g, n in counts.items():
        lim = (scene.get("clip_limits") or {}).get(g)
        if lim is not None and n > lim:
            raise SystemExit(f"FAIL: clip group {g!r} used {n} times (max {lim})")
    for s in segs:
        if s["kind"] == "verse" and s["t1"] < s["hold_until"] - 1e-3:
            raise SystemExit(f"FAIL: verse {s['ref']} leaves before it held 1 s")
    for b, beat in enumerate(scene["beats"]):          # marker swipes on a verse card that is on screen
        start, end = spans[b]
        for ev in beat.get("events", []):
            if "box_highlight" in ev:
                t = resolve_at(ev.get("at"), beat_words[b], start, end, {}, [p for p in pauses if p[2] == b])
                on = next((s for s in segs if s["kind"] == "verse" and s["t0"] <= t < s["t1"]), None)
                if not on:
                    raise SystemExit(f"FAIL: beat {beat.get('id', b)}: highlight {ev['box_highlight']!r} at {t:.2f} s but no verse card is on")
                if ev["box_highlight"].lower() not in on["text"].lower():
                    raise SystemExit(f"FAIL: highlight {ev['box_highlight']!r} is not in {on['ref']}")
                on.setdefault("highlights", []).append({"t": round(t, 3), "text": ev["box_highlight"]})
    log("media box: " + ", ".join(f"{s['t0']:.1f}-{s['t1']:.1f} {label(s)}" for s in segs))
    return segs


def label(s: dict) -> str:
    return {"clip": lambda: s["clip"], "verse": lambda: s["ref"], "heart": lambda: "drawn heart",
            "media": lambda: s.get("used_file") or s["file"], "diagram": lambda: "diagram " + s["file"],
            "split": lambda: f"split {s['left']} | {s['right']}"}[s["kind"]]()


def bullets(scene: dict, spans: list, beat_words: list, pauses: list, resolve_at, segs: list[dict]) -> dict | None:
    """Cumulative check bullets inside the box: each pops on its spoken word; all clear at the clear cue."""
    items, clear = [], None
    for b, beat in enumerate(scene["beats"]):
        start, end = spans[b]
        for ev in beat.get("events", []):
            if "box_bullet" in ev or ev.get("box_bullets_clear"):
                t = resolve_at(ev.get("at"), beat_words[b], start, end, {}, [p for p in pauses if p[2] == b])
                if ev.get("box_bullets_clear"):
                    clear = round(t, 3)
                else:
                    items.append({"t": round(t, 3), "text": ev["box_bullet"]})
    if not items:
        return None
    if clear is None or clear <= items[-1]["t"]:
        raise SystemExit("FAIL: box bullets need a clear cue after the last bullet")
    if any(sg["kind"] == "verse" and sg["t0"] < clear and items[0]["t"] < sg["t1"] for sg in segs):
        raise SystemExit("FAIL: box bullets overlap a verse")
    return {"items": items, "clear": clear}


def _placeholder(key: str, dur: float, w: int, h: int, out_dir: Path) -> list[str]:
    """LOCAL TESTS ONLY (KI_BOX_PLACEHOLDER=1, no Pexels key): a labelled test pattern instead of the clip."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("f_*.jpg"):
        old.unlink()
    font = (HERE / "vendor" / "fonts" / "Caveat.ttf").as_posix()
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:r=30:d={dur:.2f}",
                    "-vf", f"eq=saturation=0.4,drawtext=fontfile='{font}':text='{key}':fontsize=90:x=40:y=40:fontcolor=white:box=1:boxcolor=black@0.5",
                    "-q:v", "5", str(out_dir / "f_%04d.jpg")], check=True)
    return [p.as_uri() for p in sorted(out_dir.glob("f_*.jpg"))]


FAILED: list[str] = []


def frame_size(aspect: float, max_w: int, max_h: int) -> tuple[int, int]:
    """The frame for media of this shape (width / height): as large as fits the box area, the media's own aspect
    (even sizes for the encoder). No media is ever stretched to the box's shape."""
    w, h = max_w, max_w / aspect
    if h > max_h:
        w, h = max_h * aspect, max_h
    return int(w) // 2 * 2, int(h) // 2 * 2


def media_frames(s: dict, seconds: float, w: int, h: int, work: Path, n: int, log):
    """Frames of a private owner file for the box. Stills: one frame; gif / video: the clip (loops when the line is
    longer). fit "contain" keeps the whole picture (paper around it); default "cover" for landscape pictures and
    "contain" for anything much narrower than the box. A file that fails falls back; no fallback = FAIL by name."""
    from kindled_iron import private_media as pm
    idx = {}
    for name in ("movie_reference", "reactions"):
        idx.update({f"{name}/{k}": v for k, v in pm._index(Path(os.environ.get("KI_PRIVATE_MEDIA", "/nonexistent")) / name).items()})
    for rel in [s["file"]] + ([s["fallback"]] if s.get("fallback") else []):
        f = pm.private_file(rel)
        if not f:
            FAILED.append(rel)
            log(f"MEDIA FAILED TO LOAD: {rel} (not in the private repo)")
            continue
        meta = idx.get(rel, {})
        sz = pm.image_size(f) or (w, h)
        crop = s.get("crop") or meta.get("crop")
        aspect = sz[0] * (crop[2] if crop else 1) / max(1, sz[1] * (crop[3] if crop else 1))
        w, h = frame_size(aspect, w, h)             # the frame takes the picture's own shape
        s["geom"] = {"w": w, "h": h}
        fit = "contain"
        still = f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
        start = float(s.get("start") if s.get("start") is not None else meta.get("start", 0.0))
        end = meta.get("end")
        dur = 0.04 if still else max(0.5, min(seconds + 0.1, 12.0, (float(end) - start) if end else 12.0))
        out_dir = work / "box" / f"media_{n}"
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("f_*.jpg"):
            old.unlink()
        vf = (f"crop=iw*{crop[2]}:ih*{crop[3]}:iw*{crop[0]}:ih*{crop[1]}," if crop else "")
        vf += (f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0xFBF6E8"
               if fit == "contain" else f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}")
        cmd = ["ffmpeg", "-y", "-v", "error"] + ([] if still else ["-ss", f"{start:.2f}"]) + ["-i", str(f)] + \
              (["-frames:v", "1"] if still else ["-t", f"{dur:.2f}", "-an", "-r", "30"]) + \
              ["-vf", vf if still else "fps=30," + vf, "-q:v", "3", str(out_dir / "f_%04d.jpg")]
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            FAILED.append(rel)
            log(f"MEDIA FAILED TO LOAD: {rel} ({(e.stderr or b'').decode(errors='ignore').strip()[-120:]})")
            continue
        frames = [p.as_uri() for p in sorted(out_dir.glob("f_*.jpg"))]
        if not frames:
            FAILED.append(rel)
            log(f"MEDIA FAILED TO LOAD: {rel} (no frames)")
            continue
        if rel != s["file"]:
            log(f"media box: {s['file']} failed, using the fallback {rel}")
        s["used_file"] = rel
        return frames, {"clip": rel, "source": "owner upload (private)", "id": rel, "page": "", "file_url": "",
                        "license": "owner upload", "start": 0.0 if still else start, "end": 0.04 if still else round(start + len(frames) / 30, 2),
                        "crop": crop, "fit": fit}
    raise SystemExit(f"FAIL: box media {s['file']} failed to load" + (f" (fallback {s['fallback']} too)" if s.get("fallback") else ""))


def diagram_frame(s: dict, work: Path, n: int, log):
    """The whole diagram as ONE picture of exactly rect's size: a uniform scale of the original (the rect was made
    from its own aspect), never cropped, split or stretched. A diagram that fails to load fails the render."""
    from kindled_iron import private_media as pm
    f = pm.private_file(s["file"])
    if not f:
        FAILED.append(s["file"])
        raise SystemExit(f"FAIL: diagram {s['file']} is not in the private repo")
    sz = pm.image_size(f)
    x, y, w, h = s["rect"]
    if not sz or abs(sz[0] / sz[1] - w / h) > 0.01:
        raise SystemExit(f"FAIL: diagram {s['file']} would be stretched ({sz} into {w}x{h}): its rectangle must keep its shape")
    out_dir = work / "box" / f"diagram_{n}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "f_0001.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(f), "-vf", f"scale={w}:{h}:flags=lanczos", "-frames:v", "1",
                    str(out)], check=True, capture_output=True)
    log(f"media box: diagram {s['file']} {sz[0]}x{sz[1]} scaled uniformly to {w}x{h} at ({x}, {y})")
    return [out.as_uri()], {"clip": s["file"], "source": "owner upload (private)", "id": s["file"], "page": "", "file_url": "",
                            "license": "owner-supplied", "start": 0.0, "end": 0.04, "crop": None, "fit": "whole, uniform scale"}


def _source(spec: dict, key: str, got: dict, log):
    if key in got:
        return got[key]
    pin = spec.get("pexels") or spec.get("pixabay")   # a pinned Pexels / Pixabay ID, or "query": the first Pexels hit
    search = insets_mod._pixabay if spec.get("pixabay") and not spec.get("pexels") else insets_mod._pexels
    try:
        cands = search(spec.get("query", ""), pin)
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"FAIL: required clip {key} (Pexels {pin}) could not be fetched: {type(e).__name__}: {e}")
    if not cands:
        raise SystemExit(f"FAIL: required clip {key} (Pexels {pin or spec.get('query')}): no file (is PEXELS_API_KEY set?)")
    c = cands[0]
    if not pin:
        log(f"media box: clip {key} = Pexels {c['id']} (search {spec.get('query')!r})")
    f = insets_mod._download(c["file_url"])
    length = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                            "-of", "csv=p=0", str(f)]).decode().strip() or 0)
    got[key] = (c, f, length)
    return got[key]


def fetch(scene: dict, segs: list[dict], work: Path, log) -> list[dict]:
    """Frames for every clip / split segment (pinned Pexels clips; required, a missing one fails by ID).
    Ranges: every use of a source continues after the previous use; "distinct" sources never show a range twice."""
    box, clips = scene["mediabox"], scene["clips"]
    W, H = int(box["w"]), int(box["h"])
    BX, BY = box.get("x", 540), box.get("y", 455)
    placeholder = os.environ.get("KI_BOX_PLACEHOLDER") == "1"
    sources, got, cursor, used = [], {}, {}, {}
    def clip_aspect(key: str, crop=None) -> float:
        c, f, length = _source(clips[key], key, got, log)
        from kindled_iron.private_media import image_size
        sz = image_size(f) or (16, 9)
        crop = crop or clips[key].get("crop")
        return sz[0] * (crop[2] if crop else 1) / max(1, sz[1] * (crop[3] if crop else 1))

    def take(key: str, seconds: float, w: int, h: int, n: int, crop=None, start=None, side=""):
        spec = clips[key]
        crop = crop or spec.get("crop")
        want = round(min(12.0, seconds + 0.1), 2)
        if placeholder:
            out_dir = work / "box" / f"{key}_{n}{side}"
            return _placeholder(key, max(1.0, want), w, h, out_dir), {}
        c, f, length = _source(spec, key, got, log)
        pin = spec.get("pexels") or spec.get("pixabay") or c["id"]
        st = float(start) if start is not None else cursor.get(pin, float(spec.get("start", 0.3)))
        dur = min(want, length - 0.1)
        if st + dur > length - 0.05:
            if spec.get("distinct"):
                raise SystemExit(f"FAIL: clip {key} (Pexels {pin}, {length:.1f} s) has no unused range left for {dur:.1f} s "
                                 f"at {st:.1f} s")
            st = 0.3                                # reuse allowed: wrap round
        dur = max(1.0, min(dur, length - st - 0.05))
        rng = (round(st, 2), round(st + dur, 2))
        if spec.get("distinct"):
            for a0, a1 in used.get(pin, []):
                if rng[0] < a1 - 0.05 and a0 < rng[1] - 0.05:
                    raise SystemExit(f"FAIL: clip {key} (Pexels {pin}) range {rng} overlaps an earlier use {a0}-{a1}")
        used.setdefault(pin, []).append(rng)
        cursor[pin] = st + dur + 0.2
        key_h = hashlib.sha1(json.dumps([key, rng, crop, w, h]).encode()).hexdigest()[:12]
        frames = insets_mod._frames(f, st, dur, w, h, 30, work / "box" / f"{key}_{key_h}", crop)
        if len(frames) < 20:
            raise SystemExit(f"FAIL: required clip {key} (Pexels {pin}) gave only {len(frames)} frames")
        return frames, {"clip": key, "source": c.get("source", "pexels"), "id": c["id"], "page": c["page"], "file_url": c["file_url"],
                        "license": insets_mod.LICENSES[c.get("source", "pexels")], "start": rng[0], "end": rng[1], "crop": crop}
    for n, s in enumerate(segs):
        seconds = s["t1"] - s["t0"]
        s["geom"] = {"x": BX, "y": BY, "w": W, "h": H}
        if s["kind"] == "clip":
            asp = 16 / 9 if placeholder else clip_aspect(s["clip"], s.get("crop"))
            fw, fh = frame_size(asp, W, H)
            s["geom"].update(w=fw, h=fh)
            frames, rec = take(s["clip"], seconds, fw, fh, n, s.get("crop"), s.get("start"))
            s.update({"frames": frames, "fps": 30})
            recs = [rec]
        elif s["kind"] == "media":
            frames, rec = media_frames(s, seconds, W, H, work, n, log)
            s["geom"] = {"x": BX, "y": BY, **s["geom"]}
            s.update({"frames": frames, "fps": 30})
            recs = [rec]
        elif s["kind"] == "diagram":
            frames, rec = diagram_frame(s, work, n, log)
            x, y, w, h = s["rect"]
            s["geom"] = {"x": x + w / 2, "y": y + h / 2, "w": w, "h": h, "bare": True}
            s.update({"frames": frames, "fps": 30})
            recs = [rec]
        elif s["kind"] == "split":
            half = W // 2 - 6
            fl, rl = take(s["left"], seconds, half, H, n, side="L")
            fr, rr = take(s["right"], seconds, half, H, n, side="R")
            s.update({"frames_l": fl, "frames_r": fr, "fps": 30})
            recs = [dict(rl, side="left") if rl else {}, dict(rr, side="right") if rr else {}]
        else:
            continue
        for rec in recs:
            if rec:
                rec.update({"segment": n, "shown": [s["t0"], s["t1"]], "cue": s.get("cue"), "beat": s.get("beat"),
                            "loops": seconds > rec["end"] - rec["start"] + 0.05})
                sources.append(rec)
                log(f"box {s['kind']} {rec['clip']}: Pexels {rec['id']} {rec['start']:.1f}-{rec['end']:.1f} s"
                    f"{' crop ' + str(rec['crop']) if rec.get('crop') else ''} for {s['t0']:.1f}-{s['t1']:.1f} (beat {s.get('beat')}, cue {s.get('cue')})")
    (work / "sources.json").write_text(json.dumps(sources, indent=1))
    (work / "media_failures.json").write_text(json.dumps(FAILED, indent=1))
    contact(segs, work, log)
    return segs


def contact(segs: list[dict], work: Path, log) -> None:
    """box_contact.jpg: the middle frame of every clip / split segment, labelled, for checking what each shot shows."""
    from urllib.parse import urlparse
    font = (HERE / "vendor" / "fonts" / "Caveat.ttf").as_posix()
    tiles = []
    for n, s in enumerate(segs):
        fr = s.get("frames") or s.get("frames_l")
        if not fr:
            continue
        lab = f"{s['t0']:.1f}s {label(s)}".replace(":", r"\:").replace("'", "")
        out = work / f"_bc_{n}.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", urlparse(fr[len(fr) // 2]).path, "-vf",
                        f"scale=410:250,drawtext=fontfile='{font}':text='{lab}':fontsize=30:x=8:y=6:fontcolor=white:box=1:boxcolor=black@0.6",
                        str(out)], check=True)
        tiles.append(out)
    if not tiles:
        return
    while len(tiles) % 4:
        blank = work / f"_bc_blank{len(tiles)}.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=white:s=410x250", "-frames:v", "1", str(blank)], check=True)
        tiles.append(blank)
    args = []
    for t in tiles:
        args += ["-i", str(t)]
    rows = len(tiles) // 4
    layout = "|".join(f"{(i % 4) * 410}_{(i // 4) * 250}" for i in range(len(tiles)))
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args, "-filter_complex", f"xstack=inputs={len(tiles)}:layout={layout}",
                    "-frames:v", "1", "-q:v", "3", str(work / "box_contact.jpg")], check=True)
    for t in tiles:
        t.unlink()
    log(f"box contact sheet: {work / 'box_contact.jpg'} ({rows} rows)")


def page_data(scene: dict, segs: list[dict]) -> tuple[dict, dict]:
    """(object for the page, D.mediabox) ; the box is drawn on panel 0 at the scene's position."""
    box = scene["mediabox"]
    size = int(box.get("verse_size", 62))
    max_lines = int((box["h"] - 60) // (size * 1.12) - 1)
    obj = {"id": "box", "type": "mediabox", "x": box.get("x", 540), "y": box.get("y", 455), "w": box["w"], "h": box["h"],
           "verse_size": size, "pad_x": int(box.get("pad_x", 52)), "max_lines": max_lines, "allow_overlap": True}
    D = {"id": "box", "verse_size": size,
         "segments": [{k: v for k, v in s.items() if k in ("kind", "t0", "t1", "frames", "frames_l", "frames_r", "fps", "ref",
                                                          "ref_t", "pages", "clip", "left", "right", "highlights", "geom", "views")}
                      for s in segs]}
    return obj, D
