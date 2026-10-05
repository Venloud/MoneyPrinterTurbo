# Kindled Iron stickman renderer

Scene JSON in, 1080x1920 MP4 out. Linux, CPU, no AI agent at render time.

```
python -m kindled_iron.render kindled_iron/scenes/genesis-1.json --out storage/kindled_iron/genesis-1.mp4
python -m kindled_iron.render <scene> --reuse-audio --frames-only 1,5,10   # quick PNG stills
```

Pipeline: `kokoro_tts.py` (Kokoro voices each beat; needs `espeak-ng`) ->
`whisper_transcribe.py` (faster-whisper word timings, aligned to the script words) ->
`render.py` resolves every event to an absolute time -> `runtime/page.html` + `runtime/runtime.js`
build the board, rigs and one paused GSAP timeline -> headless Chrome (Playwright) seeks it
frame by frame -> FFmpeg encodes with the narration. Captions are drawn in the page, so they
are burned into every frame; an `.srt` is written next to the MP4.

Needs: `ffmpeg`, `espeak-ng`, Chrome/Chromium (`CHROME_PATH` or auto-detect), and
`pip install kokoro soundfile faster-whisper playwright` (+ `python -m spacy download en_core_web_sm`).
Everything visual is local: GSAP and the Caveat font are in `vendor/`.

Look: off-white board `#F4F1EA`, charcoal ink `#222222`, burnt orange `#CC5500` accents,
no ruled lines, no hand / pencil / cursor. Constants in `render.py` (`PALETTE`).

## Scene JSON (what Gemini will write)

The world is a strip of 1080x1920 **panels** side by side. Each beat names its `panel`;
every `x` in that beat is panel-local (0-1080). Feet stand on `ground` (default y 1250).
Keep drawings between y 180 and 1350: captions sit at y ~1440-1560.

```json
{
  "id": "genesis-1",
  "voice": {"name": "am_michael", "speed": 1.05, "lang": "a"},
  "beat_gap": 0.28, "end_hold": 1.8, "ground": 1250, "camera_y": 900,
  "cast": {"guide": {"panel": 0, "x": 190, "scale": 1.5, "facing": 1, "accent": true}},
  "beats": [
    {"id": "hook", "panel": 0, "narration": "...", "captions": true, "camera_start": false,
     "events": [{"at": "Adam", "do": "point", "who": "guide", "toward": "adam"}]}
  ]
}
```

`at`: seconds after the beat starts (`1.2`), a word of the beat (`"God"`), the n-th copy
(`"God#2"`), with an offset (`"God+0.2"`, `"very-0.15"`), or `"end"`.

`camera_start`: omitted = cut/pan to the panel centre at the beat start; `false` = leave the
camera to the beat's own events (e.g. a walk with `"camera": true`).

### Drawing (`"do": "draw"`, needs a unique `id`)
`type` one of: `word` (text, size, color ink|accent, underline), `strike` / `circle` (target id),
`rays` (n, r1, r2, rx), `book`, `darkness` (w, h), `blob` (r), `waves` (w, rows), `line` (w),
`hill` (w, h), `cloud`, `light` (r), `voice`, `sun`, `moon`, `star`, `stars` (w, h, n), `tree`,
`plant` (flower), `fish`, `birds` (n), `animal`, `globe` (r), `check` (k), `arrow` (dx, dy, bend).
Common: `x`, `y`, `scale`, `rotate`, `dur`, `pop`. Strokes draw themselves; text wipes in.
Also `fade` (`ids`, `opacity`), `pulse` (`id`).

### Characters (`who` = a cast id)
`enter` (draws the stickman in), `exit`, `walk` (`to`, `speed`, `camera`, `camY`, `camZoom`, `face`),
`point` / `reach` (`toward` = object or character id; auto-turns), `wave`, `cheer`, `react`
(`expression`), `shrug`, `present`, `look` (`dir` up|down), `shake` (head), `kneel`, `express`
(`expression`: neutral, happy, surprised, thinking, speaking, focused), `face` (1 / -1).
Gestures hold for `hold` seconds, then return to rest. Cast options: `hair` (long-straight,
short-tufts), `dress`, `accent` (orange collar), `scale`, `facing`.

### Camera
`{"do": "camera", "x": 560, "y": 860, "zoom": 1.12, "dur": 1.0, "ease": "power2.inOut"}` (panel-local).

Upstream credit and what was vendored: `vendor/stickman-animation-agent/NOTICE.md`.
