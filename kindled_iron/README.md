# Kindled Iron stickman renderer

Scene JSON in, 1080x1920 MP4 out. Linux, CPU, no AI agent at render time.

```
python -m kindled_iron.render kindled_iron/scenes/genesis-1.json --out storage/kindled_iron/genesis-1.mp4
python -m kindled_iron.render <scene> --reuse-audio --frames-only 1,5,10 --safe-box   # stills + safe-box overlay
python -m kindled_iron.voice_samples        # same lines in 6 calm voices (storage/kindled_iron/voices)
```

## Writing rules (every script)
- The hook (first line) is explained in the next 1-2 lines.
- Words a 6-year-old understands. No theology jargon.
- Leave out side details. Summarize; never read verses.
- Only the Bible's 66 books; no claims the chapter itself doesn't support.
- **Length:** target a 61-68 s video (script ~145-155 words). Shorter is fine only when the story is
  complete and makes sense. Never pad with filler or a long end card. `render.py` logs
  `Length: X s (target 61-68)` and warns under 61 s (never fails). A script under ~120 words gets ONE
  automatic rewrite pass (Gemini, needs `GEMINI_API_KEY`) asking for a fuller version
  (`script_check.py`); `"exact_narration": true` (owner's own text) skips it.

## TikTok safe area (1080x1920, owner's template)
All important art and captions stay inside **x 120-960, y 160-1440**, and out of the right button column
**x 780-960 for y 840-1440**. Top 160 px and bottom 480 px are decoration only. In practice:
drawings in the upper zone (y 180-660, full width), figures stand on y 1170 in x 120-780, captions sit
under the feet (centred at x 450, y ~1255-1360). Every render checks this every 0.2 s and logs
`LAYOUT WARNING` lines (also `checks.json`): outside the box, in the button column, a character over
key text, a walking character passing through another. After the video it logs `EMPTY-SCREEN WARNING`
for any stretch over 1 s with under 2.5 % ink in the art area. Warnings never fail the render.
Moving to a new panel fades the earlier panels' words/rays, so the walking guide never crosses text;
a walking character is always drawn in front, and characters not yet drawn take no space.

Pipeline: `kokoro_tts.py` (Kokoro voices each beat; needs `espeak-ng`) ->
`whisper_transcribe.py` (faster-whisper word timings, aligned to the script words) ->
`render.py` resolves every event to an absolute time -> `runtime/page.html` + `runtime/runtime.js`
build the board, rigs and one paused GSAP timeline -> headless Chrome (Playwright) seeks it
frame by frame -> FFmpeg encodes with the narration. Captions are drawn in the page, so they
are burned into every frame; an `.srt` is written next to the MP4.

Needs: `ffmpeg`, `espeak-ng`, Chrome/Chromium (`CHROME_PATH` or auto-detect), and
`pip install kokoro soundfile faster-whisper playwright` (+ `python -m spacy download en_core_web_sm`).
Everything visual is local: GSAP and the Caveat font are in `vendor/`.

Look: off-white board `#F4F1EA`, charcoal ink `#222222`, burnt orange `#CC5500` accents, flat light
hand-coloured fills (blue water, green grass/hills, green+brown tree, cream/gray sheep, fish with a gray
belly, orange sun), no ruled lines, no hand / pencil / cursor. Captions stay ink + orange. Constants in
`render.py` (`PALETTE`, `SAFE`, `CAPTION`).

## Scene JSON (what Gemini will write)

The world is a strip of 1080x1920 **panels** side by side. Each beat names its `panel`;
every `x` in that beat is panel-local (0-1080). Feet stand on `ground` (default y 1170).
Keep to the safe area above.

```json
{
  "id": "genesis-1",
  "exact_narration": false,
  "voice": {"name": "am_michael", "speed": 1.0, "lang": "a"},
  "beat_gap": 0.3, "end_hold": 1.6, "ground": 1170, "camera_y": 960,
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
`plant` (flower), `fish`, `birds` (n), `animal`, `globe` (r), `check` (k), `arrow` (dx, dy, bend),
`figure` (tiny person icon), `cross` (orange X over `target`), `frame` (empty page, w, h), `dot` (r).
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

Voices: British voices (`bf_*`, `bm_*`) need `"lang": "b"` in the scene's `voice`.
