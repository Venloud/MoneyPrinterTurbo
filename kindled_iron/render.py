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
}
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
    return text.split()


def resolve_at(at, beat_words: list[dict], beat_start: float, beat_end: float, used: dict) -> float:
    """`at` = seconds after the beat starts, "end", or a word of this beat
    ("God", "God#2" = second "God", "God+0.3" = 0.3 s after it starts)."""
    if at is None:
        return beat_start
    if isinstance(at, (int, float)):
        return beat_start + float(at)
    s = str(at).strip()
    if s == "end":
        return beat_end
    m = re.fullmatch(r"(.+?)(?:#(\d+))?([+-][\d.]+)?", s)
    word, nth, off = m.group(1), int(m.group(2) or 1), float(m.group(3) or 0)
    key = re.sub(r"[^a-z0-9]", "", word.lower())
    hits = [w for w in beat_words if re.sub(r"[^a-z0-9]", "", w["word"].lower().replace("’", "'")) == key]
    if len(hits) < nth:
        raise ValueError(f"word {word!r} (#{nth}) is not in this beat's narration")
    return hits[nth - 1]["start"] + off


def caption_chunks(words: list[dict], max_words: int = 3, max_chars: int = 13) -> list[dict]:
    chunks, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        text = " ".join(x["word"] for x in cur)
        nxt = words[i + 1] if i + 1 < len(words) else None
        punct = re.search(r"[.,;:!?]$", w["word"])
        gap = nxt is not None and nxt["start"] - w["end"] > 0.35
        too_long = nxt is not None and len(text) + 1 + len(nxt["word"]) > max_chars
        if len(cur) >= max_words or punct or gap or too_long or nxt is None:
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
               insets: dict | None = None) -> dict:
    insets = insets or {}
    ground = scene.get("ground", 1170)
    cast = {cid: {**c, "x": c["x"] + PANEL_W * c.get("panel", 0)} for cid, c in scene["cast"].items()}
    objects, events, captions = [], [], []
    ids = set()
    cam_y = scene.get("camera_y", 960)
    for b, beat in enumerate(scene["beats"]):
        start, end = spans[b]
        off = PANEL_W * beat.get("panel", 0)
        words = beat_words[b]
        used: dict = {}
        if beat.get("captions", True):
            captions += caption_chunks(words)
        cam = beat.get("camera_start")
        if cam is not False:
            cam = cam or {}
            events.append({"t": max(0.0, start - 0.25) if b else 0.0, "do": "camera",
                           "x": off + cam.get("x", 540), "y": cam.get("y", cam_y), "zoom": cam.get("zoom", 1.0),
                           "dur": cam.get("dur", 0.9 if b else 0.01)})
        for ev in beat.get("events", []):
            e = dict(ev)
            try:
                e["t"] = round(resolve_at(e.pop("at", None), words, start, end, used), 3)
            except ValueError as err:
                raise SystemExit(f"beat {beat.get('id', b)}: {err}")
            kind = e.get("do")
            if kind == "draw":
                if e["id"] in ids:
                    raise SystemExit(f"duplicate object id {e['id']!r}")
                if e.get("type") == "inset":
                    if e["id"] not in insets:
                        continue                      # no clip found: the inset is simply left out
                    e.update(insets[e["id"]])
                ids.add(e["id"])
                obj = {k: v for k, v in e.items() if k not in ("t", "do", "dur", "pop", "sparkle", "hold", "instant")}
                obj["x"] = obj.get("x", 540) + off
                obj["y"] = obj.get("y", 900)
                objects.append(obj)
                pop = e.get("pop", obj["type"] not in NO_POP)
                events.append({"t": e["t"], "do": "draw", "id": e["id"], "dur": e.get("dur"), "pop": pop, "hold": e.get("hold"),
                               "instant": e.get("instant")})
                if e.get("sparkle"):                  # a burst of little stars as it lands
                    sid = e["id"] + "_spk"
                    objects.append({"id": sid, "type": "sparkle", "x": obj["x"], "y": obj["y"], "r": e.get("sparkle_r", 120),
                                    "n": 6})
                    events.append({"t": round(e["t"] + 0.25, 3), "do": "draw", "id": sid, "dur": 0.3, "pop": False})
                continue
            if kind == "walk":
                e["to"] = e["to"] + off
                if e.get("camera"):
                    e["camX"] = e.get("camX", 540) + off
                    e.setdefault("camY", cam_y)
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
    for e in [e for e in events if e["do"] == "walk" and e.get("camera")]:
        new_panel = int(e["camX"] // PANEL_W)
        old = [o["id"] for o in objects if panel_of[o["id"]] < new_panel and o["id"] not in faded]
        if old:
            faded.update(old)
            events.append({"t": max(0.0, e["t"] - 0.15), "do": "fade", "ids": old, "opacity": 0, "dur": 0.25})
    events.sort(key=lambda e: e["t"])
    return {"width": WIDTH, "height": HEIGHT, "fps": FPS, "duration": duration, "ground": ground,
            "palette": PALETTE, "cast": cast, "objects": objects, "events": events, "captions": captions,
            "camera": {"x": 540, "y": cam_y, "zoom": 1.0}, "vendor": vendor_parts(), "safe": SAFE, "debugSafe": False,
            "captionSize": CAPTION["size"], "hud": HUD, "paper": None, "inboxReactions": []}


def write_page(data: dict, work: Path) -> Path:
    page = (HERE / "runtime" / "page.html").read_text(encoding="utf-8")
    rep = {
        "__W__": str(WIDTH), "__H__": str(HEIGHT), "__BOARD__": PALETTE["board"], "__INK__": PALETTE["ink"],
        "__ACCENT__": PALETTE["accent"], "__CAPTION_X__": str(CAPTION["x"]), "__CAPTION_Y__": str(CAPTION["y"]), "__CAPTION_W__": str(CAPTION["w"]),
        "__CAPTION_SIZE__": str(CAPTION["size"]),
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
    out = [{"issue": m, "from": a, "to": b} for m, rs in ranges.items() for a, b in rs]
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


VISUAL_EVENTS = {"move", "wiggle", "draw", "walk", "point", "reach", "wave", "cheer", "react", "shrug", "present", "look", "shake",
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
        if stills is not None:
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
    a = ap.parse_args()

    scene_path = Path(a.scene)
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    sid = scene.get("id", scene_path.stem)
    from kindled_iron import script_check

    scene = script_check.check(scene, log, MIN_WORDS)
    out = Path(a.out or f"storage/kindled_iron/{sid}.mp4").resolve()
    work = Path(a.work or out.parent / f"{sid}_work").resolve()
    work.mkdir(parents=True, exist_ok=True)
    wav, timing_file = work / "narration.wav", work / "timings.json"
    texts = [b["narration"] for b in scene["beats"]]

    if a.reuse_audio and timing_file.exists() and json.loads(timing_file.read_text())["texts"] == texts:
        t = json.loads(timing_file.read_text())
        spans, beat_words, voice_meta = [tuple(s) for s in t["spans"]], t["words"], t.get("voice", {})
        log("reusing narration + timings")
    else:
        from kindled_iron import tts, whisper_transcribe as wt

        profile = tts.load_profile(scene.get("voice_profile", "kindled_iron"))
        if scene.get("voice", {}).get("kokoro"):          # per-scene Kokoro override (voice, speed, lang)
            profile["kokoro"] = {**profile.get("kokoro", {}), **scene["voice"]["kokoro"]}
        provider = a.tts or profile.get("tts_provider", "kokoro")
        voice_meta = tts.voice(texts, wav, profile, provider, log)
        audio_len = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                                   "-of", "csv=p=0", str(wav)]).decode().strip())
        # Word timings always come from the audio that was actually used.
        heard = wt.transcribe(wav, a.whisper_model)
        log(f"narration {audio_len:.2f} s, whisper heard {len(heard)} of {sum(len(words_of(x)) for x in texts)} words")
        flat = [w for txt in texts for w in words_of(txt)]
        aligned = wt.align(flat, heard, (0.0, audio_len))
        beat_words, k = [], 0
        for txt in texts:
            n = len(words_of(txt))
            beat_words.append(aligned[k:k + n])
            k += n
        spans = [(bw[0]["start"], bw[-1]["end"]) for bw in beat_words]
        timing_file.write_text(json.dumps({"texts": texts, "spans": spans, "words": beat_words, "heard": heard,
                                           "voice": voice_meta}, indent=1))

    from kindled_iron import effects, insets as insets_mod

    clips = insets_mod.fetch(scene, work, log)          # network step, BEFORE the render
    duration = round(spans[-1][1] + scene.get("end_hold", 1.8), 3)
    lo, hi = TARGET_LEN
    log(f"Length: {duration:.1f} s (target {lo:.0f}-{hi:.0f})")
    if duration < lo:
        log(f"WARNING: under {lo:.0f} s. Fine only if the story is complete; never pad it.")
    elif duration > hi:
        log(f"WARNING: over {hi:.0f} s")
    data = build_data(scene, spans, beat_words, duration, clips)
    data["inboxReactions"] = effects.apply_reaction_rules(data["events"], scene, spans, beat_words, work, log)
    data["events"] = [e for e in data["events"] if not e.get("_drop")]
    data["paper"] = effects.paper_texture(work, PALETTE["board"])
    data["debugSafe"] = a.safe_box
    pacing_check(data["events"], duration)
    (work / "captions.srt").write_text(srt(data["captions"]), encoding="utf-8")
    page = write_page(data, work)
    log(f"{len(data['objects'])} objects, {len(data['events'])} events, {len(data['captions'])} caption chunks, {duration:.2f} s")

    if a.frames_only:
        stills = [float(x) for x in a.frames_only.split(",")]
        capture(page, None, None, duration, a.chrome, stills, work / "stills")
        log(f"stills in {work / 'stills'}")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    cues = effects.plan_sfx(data["events"], data["objects"])
    effects.mix(wav, cues, work / "mix.wav", duration)
    log(f"sound effects: {len(cues)} cues (Kenney CC0), under the voice")
    capture(page, out, work / "mix.wav", duration, a.chrome)
    shutil.copy(work / "captions.srt", out.with_suffix(".srt"))
    shutil.copy(work / "sources.json", out.with_name(out.stem + "_sources.json"))
    empty = empty_check(out)
    words = sum(len(words_of(x)) for x in texts)
    meta = {"scene": sid, "duration": duration, "words": words, "voice": voice_meta,
            "insets": json.loads((work / "sources.json").read_text()), "sfx_cues": len(cues), "empty_stretches": empty}
    out.with_name(out.stem + "_meta.json").write_text(json.dumps(meta, indent=1))
    if a.debug_copy:
        dbg = out.with_name(out.stem + "_safebox.mp4")
        safe_overlay(out, dbg)
        log(f"debug copy with the safe box: {dbg}")
    log(f"wrote {out} ({duration:.1f} s, {words} words, voice {voice_meta.get('provider_used', '?')}"
        f"{' = fallback voice' if voice_meta.get('fallback') else ''})")


if __name__ == "__main__":
    sys.exit(main())
