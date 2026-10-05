# Kindled Iron stickman renderer

Scene JSON in, 1080x1920 MP4 out. Linux, CPU, no AI agent at render time.

```
python -m kindled_iron.render kindled_iron/scenes/genesis-1.json --out storage/kindled_iron/genesis-1.mp4
python -m kindled_iron.render <scene> --reuse-audio --frames-only 1,5,10 --safe-box   # stills + safe-box overlay
python -m kindled_iron.render <scene> --tts kokoro --debug-copy   # + <name>_safebox.mp4 with the safe box drawn on
python -m kindled_iron.voice_samples        # same lines in 6 calm Kokoro voices (storage/kindled_iron/voices)
```

Outputs next to the MP4: `.srt`, `_meta.json` (duration, words, voice used, fallback flag, insets),
`_sources.json` (every footage clip: source page, file URL, licence), and with `--debug-copy`
`_safebox.mp4`. The work dir keeps `checks.json`, `timings.json`, `stills/`.

## Hook + retention rules
- First 2 seconds: the question/hook is fully on screen at frame 0 (`"instant": true` draws), with
  motion from frame 1 (camera pull-back, wiggle). No slow fade-in.
- Something new or moving at least every 1.5-2 s: `PACING WARNING` if no event for over 2 s
  (ambient motion keeps running anyway: sun turning, waves, drifting clouds, birds, swimming fish,
  swaying trees/plants, twinkling stars, blinking characters).
- A small `DAY n` counter with progress dots (`{"do": "counter", "day": 3}`, `day: 0` hides it).

## Pacing (pacing.py): pauses between sentences, every voice
- The script is split into sentences. Silence after each: `pause_sentence` (0.35 s) normally,
  `pause_beat` (0.7 s) after the hook, a question, a 1-2 word punch line ("Wrong."), a "Day N" line,
  and before the last line. Per channel in `voice_profiles.json` (`pause_sentence`, `pause_beat`,
  `max_pause`). A manual tag sets one exactly: `The very first words are: [pause 0.5] In the beginning, God.`
  Tags are never spoken or captioned.
- Kokoro / Chatterbox voice one sentence at a time and join with the pauses. ElevenLabs gets the whole
  script in ONE request (consistent tone) with `<break time="0.7s" />` tags on models that support
  them (`use_break_tags`; tags add ~400 characters a video).
- Then, for every provider, the pauses are enforced on the final audio: each sentence gap is measured
  (word timings refined from the audio's own silences) and silence is inserted or trimmed to hit the
  target. Pauses are scaled (0.6x-1.8x, max `max_pause`) to aim at **140-150 words a minute**; the voice
  is never slowed below 0.92. Log: `pauses: ...` and `Length: X s ...; pace N words/min`.
- Captions and every animation follow the final audio. A beat starts inside the pause before it, so
  its walk / first drawing lands in the silence; footage insets snap into the nearest pause; and
  `"at": "pause"` / `"pause#2"` puts any event in the 1st / 2nd pause of its beat (the DAY counter ticks
  in the pause before each "Day N" line).

## Voice (tts.py)
Providers with one interface: `elevenlabs_tts.py` (owner's cloned voice), `chatterbox_tts.py`
(MIT, clones from a private reference clip), `kokoro_tts.py`. `--tts` picks one (default: the voice
profile's `tts_provider`); fallback is chosen -> chatterbox -> kokoro with a `WARNING` and
`"voice_label": "fallback voice"` in `_meta.json`. A missing `ELEVENLABS_API_KEY` is normal.
Settings live in `voice_profiles.json` (kindled_iron wired in; night_files / bouriko ready) and are
sent per request; the ElevenLabs voice is never edited. Before each ElevenLabs call the
remaining quota is read (`/v1/user/subscription`, needs the key's "User: read" permission), capped by
`monthly_char_budget` 40,000; under 10 % left it is skipped. Audio is cached by
hash(provider + script + voice + model + settings) in `KI_TTS_CACHE`, so re-renders cost 0 credits.
Word timings always come from whisper on the audio actually used.

### One-time private setup for the cloned voice (this repo is a public fork)
1. Create a **private** repo, `Venloud/kindled-iron-voice` (empty is fine). Another name: set the
   repo variable `KI_VOICE_REPO` in MoneyPrinterTurbo.
2. Create a fine-grained token: Resource owner Venloud, only that repo, permission
   **Contents: Read and write**. Save it in MoneyPrinterTurbo secrets as `VOICE_REPO_TOKEN`.
3. `ELEVENLABS_API_KEY` (already there). Give the key "Text to Speech" + "User: read" access.
4. Run **Kindled Iron Voice Bootstrap** once (type GENERATE): 5 reference clips (25-30 s) + a
   ~3-minute reserve, ~5,000 characters, stored only in the private repo's `voice-refs` release.
5. Run **Kindled Iron Voice Compare**: the Genesis narration in ElevenLabs, Chatterbox x 5 clips and
   Kokoro, in the private repo's `voice-compare` release. Pick a default; set `tts_provider` and
   `chatterbox.reference_clip` in `voice_profiles.json`.
6. **Kindled Iron Test Render** with `my_voice`: videos go to the private repo's `test-renders`
   release (never a public artifact). Chatterbox downloads its clip at run time and deletes it.

## Footage insets (insets.py, fetched before the render)
`{"do": "draw", "type": "inset", "query": "...", "sources": ["nasa", "pexels", "pixabay"],
"pin": {"nasa": "<nasa_id>"}, "start": 12.0, "clip_dur": 2.2, "crop": [x, y, w, h], "w": 340, "h": 230,
"rotate": -4}`: a 1.5-3 s real clip in a tilted hand-drawn frame that pops in and out on top of the
drawing. NASA (public domain), Pexels and Pixabay (no attribution needed; keys `PEXELS_API_KEY`,
`PIXABAY_API_KEY`). Never CC BY. Max 6 a video; no clip found = the inset is silently left out.
NASA search results are mixed (press conferences...), so pin NASA clips after checking frames.

## Reactions (use sparingly)
`{"do": "reaction", "who": "guide", "face": "side_eye", "dur": 1.2}`: faces `shocked`, `mind_blown`,
`side_eye`, `crying_laughing`, `thinking`, `wait_what`, drawn in our style and swapped onto the head
(head pops bigger) for under 1.5 s. Own images: `reactions_inbox/`. Hard limits (extra ones are
dropped with a WARNING): max 2 a video, 15 s apart, never on the word "God" or on a beat marked
`"serious": true`.

## Sound effects
Kenney CC0 sounds in `vendor/sfx` (licence file there): pops on drawings, scratch on strikes, ding on
the check mark and the DAY counter, whoosh on insets, boing on reactions, sparkle on sparkles. Mixed
at about -13 dB under the voice, at most one every 0.3 s.

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
for any stretch over 1 s with under 2.5 % ink in the art area. Also `object A overlaps B` (bounding
boxes; declare intended ones with `"over": ["B"]`; backdrops like darkness/frame/line/insets are
exempt). Warnings never fail the render, with one exception: a character walking the opposite way to
the one it faces **fails the render** (characters turn first, then walk). Captions shrink to fit the
box (then wrap). Moving to a new panel fades everything on earlier panels, so the walking guide never crosses text;
a walking character is always drawn in front, and characters not yet drawn take no space.

Pipeline: `tts.py` (ElevenLabs / Chatterbox / Kokoro) ->
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
  "voice_profile": "kindled_iron",
  "end_hold": 1.4, "ground": 1170, "camera_y": 960,
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
Also `sparkle` (n, r), `inset` (above). Common: `x`, `y`, `scale`, `rotate`, `dur`, `pop` (bounce, default
on for small things), `instant` (fully drawn at once), `sparkle` (burst as it lands), `marker` (word:
highlighter band), `over` (intended overlaps). Strokes draw themselves; text wipes in.
Also `fade` (`ids`, `opacity`), `pulse` / `wiggle` (`id`), `move` (`id`, `dx`, `dy`, `dur`),
`counter` (`day`), `shake` (no `who` = camera shake).

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

Kokoro British voices (`bf_*`, `bm_*`) need `"lang": "b"` in the profile's `kokoro` block.
