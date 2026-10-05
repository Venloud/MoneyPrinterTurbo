"""Render one Kindled Iron scene JSON to a 1080x1920 MP4. No AI agent at render time.

    python -m kindled_iron.render kindled_iron/scenes/genesis-1.json --out storage/kindled_iron/genesis-1.mp4

Steps: Kokoro voices every beat -> faster-whisper word timings -> every event's
"at" (a word of its beat, or seconds) becomes an absolute time -> page.html +
runtime.js build the board, stickmen and one GSAP timeline -> headless Chrome
(Playwright) seeks the timeline frame by frame and screenshots it -> FFmpeg
encodes the frames with the narration. Captions are part of the page, so they
are burned into every frame.

Options: --frames-only T1,T2,...  write PNG stills at those seconds (quick check)
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
PALETTE = {"board": "#F4F1EA", "ink": "#222222", "inkSoft": "#55524C", "accent": "#CC5500"}
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
    head = _svg_inner(UPSTREAM / "tier1" / "heads" / "front.svg")
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


def caption_chunks(words: list[dict], max_words: int = 3, max_chars: int = 16) -> list[dict]:
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
def build_data(scene: dict, spans: list[tuple[float, float]], beat_words: list[list[dict]], duration: float) -> dict:
    ground = scene.get("ground", 1250)
    cast = {cid: {**c, "x": c["x"] + PANEL_W * c.get("panel", 0)} for cid, c in scene["cast"].items()}
    objects, events, captions = [], [], []
    ids = set()
    cam_y = scene.get("camera_y", 900)
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
                ids.add(e["id"])
                obj = {k: v for k, v in e.items() if k not in ("t", "do", "dur", "pop")}
                obj["x"] = obj.get("x", 540) + off
                obj["y"] = obj.get("y", 900)
                objects.append(obj)
                events.append({"t": e["t"], "do": "draw", "id": e["id"], "dur": e.get("dur"), "pop": e.get("pop")})
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
    return {"width": WIDTH, "height": HEIGHT, "fps": FPS, "duration": duration, "ground": ground,
            "palette": PALETTE, "cast": cast, "objects": objects, "events": events, "captions": captions,
            "camera": {"x": 540, "y": cam_y, "zoom": 1.0}, "vendor": vendor_parts()}


def write_page(data: dict, work: Path) -> Path:
    page = (HERE / "runtime" / "page.html").read_text(encoding="utf-8")
    rep = {
        "__W__": str(WIDTH), "__H__": str(HEIGHT), "__BOARD__": PALETTE["board"], "__INK__": PALETTE["ink"],
        "__ACCENT__": PALETTE["accent"], "__CAPTION_Y__": "1440", "__CAPTION_SIZE__": "118",
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
    a = ap.parse_args()

    scene_path = Path(a.scene)
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    sid = scene.get("id", scene_path.stem)
    out = Path(a.out or f"storage/kindled_iron/{sid}.mp4").resolve()
    work = Path(a.work or out.parent / f"{sid}_work").resolve()
    work.mkdir(parents=True, exist_ok=True)
    wav, timing_file = work / "narration.wav", work / "timings.json"
    texts = [b["narration"] for b in scene["beats"]]

    if a.reuse_audio and timing_file.exists() and json.loads(timing_file.read_text())["texts"] == texts:
        t = json.loads(timing_file.read_text())
        spans, beat_words = [tuple(s) for s in t["spans"]], t["words"]
        log("reusing narration + timings")
    else:
        from kindled_iron import kokoro_tts, whisper_transcribe as wt

        voice = scene.get("voice", {})
        spans = kokoro_tts.synthesize_beats(texts, wav, voice.get("name", "am_michael"), voice.get("speed", 1.0),
                                            voice.get("lang", "a"), gap=scene.get("beat_gap", 0.3))
        log(f"narration {spans[-1][1]:.2f} s, voice {voice.get('name', 'am_michael')}")
        heard = wt.transcribe(wav, a.whisper_model)
        log(f"whisper heard {len(heard)} words")
        beat_words = [wt.align(words_of(txt), heard, span) for txt, span in zip(texts, spans)]
        timing_file.write_text(json.dumps({"texts": texts, "spans": spans, "words": beat_words, "heard": heard}, indent=1))

    duration = round(spans[-1][1] + scene.get("end_hold", 1.8), 3)
    data = build_data(scene, spans, beat_words, duration)
    (work / "captions.srt").write_text(srt(data["captions"]), encoding="utf-8")
    page = write_page(data, work)
    log(f"{len(data['objects'])} objects, {len(data['events'])} events, {len(data['captions'])} caption chunks, {duration:.2f} s")

    if a.frames_only:
        stills = [float(x) for x in a.frames_only.split(",")]
        capture(page, None, None, duration, a.chrome, stills, work / "stills")
        log(f"stills in {work / 'stills'}")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    capture(page, out, wav, duration, a.chrome)
    shutil.copy(work / "captions.srt", out.with_suffix(".srt"))
    log(f"wrote {out}")


if __name__ == "__main__":
    sys.exit(main())
