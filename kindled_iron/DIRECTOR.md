# Kindled Iron director: script + MP3 -> private preview

You give it two files. It makes the whole video by itself and puts a private preview in
`Venloud/kindled-iron-voice/previews/<id>/`. It never generates a voice and never publishes.

## Add a video

1. In the private repo `kindled-iron-voice`, make a folder `approved_audio/<id>/` (`<id>` = lowercase words with
   hyphens, e.g. `why-did-god-rest`).
2. Put two files in it:
   - `script.txt`: the exact words of the recording. One paragraph = one "line" of the video (blank line between
     paragraphs). Write Bible references the normal way (`Revelation 21:4`); put direct quotes in quotation marks.
   - `narration.mp3`: your recording of exactly that script.
3. Commit and push.
4. GitHub -> MoneyPrinterTurbo -> Actions -> **Kindled Iron Director Preview** -> Run workflow
   (branch `feature/kindled-script-mp3-preview-20261026`; leave `video_id` empty to do every new folder, or type one id).
5. 40-90 minutes later: `kindled-iron-voice/previews/<id>/` has the MP4, the 8-frame sheet, and the reports
   (and your phone gets an ntfy alert if `NTFY_TOPIC` is set). The schedule is written in the workflow but OFF.

## How it works

```
script.txt + narration.mp3
 1 align    faster-whisper hears the MP3; every script word gets its time (the renderer's own alignment)
 2 plan     Gemini (free tier) writes a SHOT PLAN per line: 2 drawings (type + labels), clip-box media
            (stock search words or a meme from your library), a typed verse card, an optional meme pop-up,
            the guide's expression and gesture, and ONE record-scratch freeze. Meaning only, no coordinates.
            The prompt carries both golden scenes in full (Where Did God Come From?, Love of Money v3), their
            per-line summary, the drawing catalog, the meme library and the rules below.
 3 check    plan.py rejects anything off-script or off-catalog; media.py finds the footage; compile.py turns the
            plan into a scene: every coordinate comes from the fixed zones and each drawing's measured size
 4 render   the existing renderer: first 8 stills + the every-frame audit, then the full MP4
 5 gates    any failed gate goes back to Gemini as "fix_errors" (max 2 fix rounds), else fail_report.md
 6 review   Gemini vision looks at the 8 stills with their lines; one automatic fix round; review.json
```

Files: `kindled_iron/director/` (`direct.py` runs it all, `plan.py`, `compile.py`, `media.py`, `gates.py`,
`review.py`, `gemini.py`, `catalog.py` + `catalog.json`). The renderer (`render.py`, `runtime/runtime.js`,
`mediabox.py`) draws exactly what the scene says, as for the hand-made videos.

### The fixed layout (catalog.json "zones")

| Zone | Where (1080x1920) | What goes there |
|---|---|---|
| Clip box | top, 820 x 420 | stock footage, your memes, the typed verse card |
| Caption band | under the box | one line, 1-3 words, the spoken word orange (hidden while a verse is typed) |
| Drawing area | middle band, 650 x 192 | each line's first drawing: a WIDE diagram |
| Guide lane | bottom: 4 spots (230, 340, 560, 650) | the guide walks; each line's second drawing sits on the far side of the lane, a meme pop-up sits there on its word |

Zones never overlap, so text never lands on text or on the guide. The compiler also keeps the guide's arms clear:
he points only where his hand cannot reach a drawing in the lane, shrugs only where there is room, and a lane
drawing is cleared before he walks through it.

### The catalog

`catalog.json` is generated from the renderer (`python -m kindled_iron.director.catalog`, run in every workflow
run): every drawing primitive in `runtime.js` with its comment, its fields and its size measured in Chrome, every
event type with its fields, the media-box kinds, the guide's expressions and his measured reach. A unit test fails
when it is stale. To give the director a new kind of drawing, add a primitive to `OBJ` in `runtime.js` (with a
`// comment` saying what it shows; labels via `lbl()`), regenerate the catalog, commit both.

## Adding memes and clips

Put the file in `kindled-iron-voice/movie_reference/` (jpg, png, webp, gif, mp4, mov). The file name's words are
its tags (`suspicious-fry-futurama.webp` -> suspicious, fry, futurama). Optional extra tags in
`movie_reference/index.json`:

```json
{"file": "suspicious-fry-futurama.webp", "tags": ["suspicious", "doubt", "not sure"], "note": "doubting someone"}
```

Rules the code enforces: at most 3 pop-ups per video, at least 2 lines apart, never on a verse line or on the word
"God", 380 px wide, 1.2 s; no file twice in a row and no file more than twice per video.

## Gates (the bot fails instead of shipping)

| Gate | Passes when |
|---|---|
| render | the renderer finished (its every-frame audit fails it on any overlap) |
| layout | zero layout warnings |
| audit | zero every-frame audit issues |
| coverage | at least 60 % of the usable frame (safe box minus the button column) is covered at every half second (from 0.25 s, skipping the freeze zoom) |
| doodles | every drawing is at least 250 px on its long side (measured on the page) |
| empty | no empty card, no empty verse page, the clip box never empties |
| per_line | every line brings a new drawing and new clip-box content (or its verse card) |
| box_media | at least one real clip or meme in the clip box |
| verses | every reference / quote in the script is on a typed verse card |
| alignment | at least 85 % of the script's words are heard in the MP3 |
| music, sfx | (full render) theme_1 is in the mix; sound effects are in the mix |

## Reading fail_report.md

It lists each round and the exact checks that failed in that round; those lines are what Gemini received as
fix_errors in the next round. Typical causes and what to do:

- `script.txt does not match narration.mp3`: the script is not the recording's text. Fix script.txt.
- `no stock video matches 'x'`: the planner's footage idea found nothing that really shows it; it is retried
  with another query automatically. If it keeps failing, add a fitting meme/clip to movie_reference/.
- `cannot be drawn 250 px or larger here`: the line's two drawings were both tall; the planner is told to make
  the first one wide.
- `the frame looks empty` (coverage): a line's drawings are small for their slots; retried automatically.
- A renderer `AUDIT FAIL` that repeats every round is a compiler bug (a zone rule), not the plan: report it.

## Outputs (previews/<id>/)

`<id>.mp4` (private preview), `<id>-8-frames.jpg`, `scene.json` (what was rendered), `plan.json` (Gemini's plan),
`media.json` (every clip/meme pick, its source, page and why it matched), `gates.json`, `review.json` (vision
verdict per still), `gemini_calls.json` (every Gemini call, model, tokens, seconds), `rounds.json`, `status.json`,
and `fail_report.md` only when it failed.

## Secrets (MoneyPrinterTurbo repo settings, names only)

`GEMINI_API_KEY` (free tier), `VOICE_REPO_TOKEN`, `PEXELS_API_KEY`, `PIXABAY_API_KEY` (optional), `FREESOUND_API_KEY`
(for the record scratch, optional), `NTFY_TOPIC` (optional phone alerts).

## Local offline test (no keys)

```
KI_GEMINI_MOCK=test/kindled_iron/mock_epicurean KI_BOX_PLACEHOLDER=1 KI_MUSIC_SOURCE=generated \
  python -m kindled_iron.director.direct --id epicurean-paradox --private ../kindled-iron-voice --out /tmp/out
python -m unittest discover -s test/kindled_iron -p 'test_director*.py'
```
