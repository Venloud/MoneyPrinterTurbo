"""The media box: ONE hand-drawn framed box that holds the real clips, and the Bible verses typed into it.

Opt-in per scene ("mediabox" in the scene JSON); scenes without it render exactly as before.

    "mediabox": {"x": 540, "y": 455, "w": 820, "h": 500, "verse_size": 62},
    "clips": {"cash": {"pexels": "5466769", "start": 1.0, "group": "cash"}, ...},
    "clip_limits": {"cash": 3},
    events in a beat:
      {"at": "selling-0.2", "box": "clip", "clip": "car_lot", "start": 4.0}   start = second inside the source clip
      {"box": "verse", "scripture": {"ref": "Hebrews 13:5", "text": "..."}, "split_after": "have"}
      {"at": "Your-0.2", "box": "off"}                                          the box leaves (end of video)

Rules (all checked here, the render stops on any of them):
- a clip segment runs until the next request; a long line loops its clip;
- the same clip never twice in a row; a clip "group" (e.g. cash) at most clip_limits[group] times;
- a verse REPLACES the clip: each word of the quote is typed letter by letter and fully on screen by 70 % of its
  spoken duration; an orange caret follows the typing; the reference appears right after the quote and the card
  holds 1 s after it (a request that would cut it short waits); "split_after": the quote goes on a second page
  after that word;
- pinned clips are required: a pin that can't be fetched fails the render (never a silent gap).
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
    if hit is None:
        raise SystemExit(f"FAIL: beat {beat_id}: the verse {card['text']!r} is not spoken word for word in this beat")
    # every card token -> the spoken word it belongs to
    tok_word, k = [], hit
    for tok in tokens:
        n = len(_norm(tok))
        tok_word.append(words[k] if n else words[min(k, hit + len(want) - 1)])
        k += n
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
    quote_end = words[hit + len(want) - 1]["end"]
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
                reqs.append((max(0.0, t), {"kind": "clip", "clip": ev["clip"], "start": ev.get("start")}))
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
    if not segs or segs[0]["t0"] > 0.0:
        raise SystemExit("FAIL: the media box must have something in it from t=0")
    # rules: never the same clip twice in a row; clip groups (cash) capped
    prev = None
    counts: dict[str, int] = {}
    clips = scene["clips"]
    for s in segs:
        if s["kind"] != "clip":
            prev = None
            continue
        pin = clips[s["clip"]].get("pexels") or s["clip"]
        if prev == pin:
            raise SystemExit(f"FAIL: clip {s['clip']} ({pin}) twice in a row at {s['t0']:.1f} s")
        prev = pin
        g = clips[s["clip"]].get("group")
        if g:
            counts[g] = counts.get(g, 0) + 1
    for g, n in counts.items():
        lim = (scene.get("clip_limits") or {}).get(g)
        if lim is not None and n > lim:
            raise SystemExit(f"FAIL: clip group {g!r} used {n} times (max {lim})")
    for s in segs:
        if s["kind"] == "verse" and s["t1"] < s["hold_until"] - 1e-3:
            raise SystemExit(f"FAIL: verse {s['ref']} leaves before it held 1 s")
    log("media box: " + ", ".join(f"{s['t0']:.1f}-{s['t1']:.1f} {s.get('clip') or s['ref']}" for s in segs))
    return segs


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


def fetch(scene: dict, segs: list[dict], work: Path, log) -> list[dict]:
    """Frames for every clip segment (pinned Pexels clips; required). Writes work/sources.json."""
    box, clips = scene["mediabox"], scene["clips"]
    w, h = int(box["w"]), int(box["h"])
    placeholder = os.environ.get("KI_BOX_PLACEHOLDER") == "1"
    sources, got = [], {}
    for n, s in enumerate(segs):
        if s["kind"] != "clip":
            continue
        spec = clips[s["clip"]]
        start = float(s.get("start") if s.get("start") is not None else spec.get("start", 0.5))
        want = round(min(12.0, s["t1"] - s["t0"] + 0.1), 2)
        key = hashlib.sha1(json.dumps([s["clip"], start, want, spec.get("crop"), w, h]).encode()).hexdigest()[:12]
        out_dir = work / "box" / f"{s['clip']}_{key}"
        if placeholder:
            frames = _placeholder(s["clip"], max(1.0, want), w, h, out_dir)
            s.update({"frames": frames, "fps": 30})
            continue
        if s["clip"] not in got:
            pin = spec["pexels"]
            try:
                cands = insets_mod._pexels("", pin)
            except Exception as e:  # noqa: BLE001
                raise SystemExit(f"FAIL: required clip {s['clip']} (Pexels {pin}) could not be fetched: {type(e).__name__}: {e}")
            if not cands:
                raise SystemExit(f"FAIL: required clip {s['clip']} (Pexels {pin}): no file (is PEXELS_API_KEY set?)")
            c = cands[0]
            f = insets_mod._download(c["file_url"])
            length = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                                    "-of", "csv=p=0", str(f)]).decode().strip() or 0)
            got[s["clip"]] = (c, f, length)
        c, f, length = got[s["clip"]]
        st = min(start, max(0.0, length - 1.6))
        dur = max(1.5, min(want, length - st - 0.05))
        frames = insets_mod._frames(f, st, dur, w, h, 30, out_dir, spec.get("crop"))
        if len(frames) < 20:
            raise SystemExit(f"FAIL: required clip {s['clip']} gave only {len(frames)} frames")
        s.update({"frames": frames, "fps": 30})
        sources.append({"segment": n, "clip": s["clip"], "source": "pexels", "id": c["id"], "page": c["page"],
                        "file_url": c["file_url"], "license": insets_mod.LICENSES["pexels"], "start": st,
                        "duration": round(len(frames) / 30, 2), "shown": [s["t0"], s["t1"]],
                        "loops": (s["t1"] - s["t0"]) > len(frames) / 30 + 0.05, "crop": spec.get("crop")})
        log(f"box clip {s['clip']}: Pexels {c['id']} {st:.1f}-{st + len(frames) / 30:.1f} s for {s['t0']:.1f}-{s['t1']:.1f}")
    (work / "sources.json").write_text(json.dumps(sources, indent=1))
    return segs


def page_data(scene: dict, segs: list[dict]) -> tuple[dict, dict]:
    """(object for the page, D.mediabox) ; the box is drawn on panel 0 at the scene's position."""
    box = scene["mediabox"]
    size = int(box.get("verse_size", 62))
    max_lines = int((box["h"] - 60) // (size * 1.12) - 1)
    obj = {"id": "box", "type": "mediabox", "x": box.get("x", 540), "y": box.get("y", 455), "w": box["w"], "h": box["h"],
           "verse_size": size, "pad_x": int(box.get("pad_x", 52)), "max_lines": max_lines, "allow_overlap": True}
    D = {"id": "box", "verse_size": size,
         "segments": [{k: v for k, v in s.items() if k in ("kind", "t0", "t1", "frames", "fps", "ref", "ref_t", "pages", "clip")}
                      for s in segs]}
    return obj, D
