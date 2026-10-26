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
 2 plan     the AI (Gemini -> GitHub Models -> Hugging Face -> Groq -> OpenRouter -> Cloudflare, see "AI providers") writes a SHOT
            PLAN per line: 2 drawings (a library doodle picked by tag, or a built-in diagram, + labels), clip-box
            media (stock search words or a meme from your library), a typed verse card, an optional meme
            pop-up, the guide's expression and gesture, and ONE record-scratch freeze. Meaning only, no
            coordinates. The prompt carries both golden scenes in full (Where Did God Come From?, Love of Money
            v3), their per-line summary, the drawing catalog, the meme library and the rules below.
 3 check    plan.py rejects anything off-script or off-catalog; media.py finds the footage; compile.py turns the
            plan into a scene: every coordinate comes from the fixed zones and each drawing's measured size
 4 render   the existing renderer: first 8 stills + the every-frame audit, then the full MP4
 5 gates    plain mistakes are repaired in code first (no AI call); any failed gate goes back to the planner as
            "fix_errors"; at most 3 plan calls per video, else fail_report.md
 6 review   one vision call looks at the 8 stills with their lines; one automatic fix round if the plan budget
            allows (the fixed video is then not re-reviewed: 1 vision call per video); review.json
```

Files: `kindled_iron/director/` (`direct.py` runs it all, `plan.py`, `compile.py`, `media.py`, `gates.py`,
`review.py`, `gemini.py`, `catalog.py` + `catalog.json`). The renderer (`render.py`, `runtime/runtime.js`,
`mediabox.py`) draws exactly what the scene says, as for the hand-made videos.

### The fixed layout (catalog.json "zones")

| Zone | Where (1080x1920) | What goes there |
|---|---|---|
| Clip box | top, 820 x 380 (y 180-560) | stock footage, your memes, the typed verse card |
| Caption band | under the box | one line, 1-3 words, the spoken word orange (hidden while a verse is typed) |
| Drawing area | everything from under the caption to the bottom of the safe box (y 702-1432, 38% of the frame) | the band above the guide's head (650 x 318) + the side beside him (285 wide, up to full height) |
| Guide lane | bottom: 4 spots (230, 340, 560, 650), ground 1570 | the guide walks; a meme pop-up sits beside him on its word |

Each line gets up to three drawings, arranged by the compiler for the most frame: the band whole or in two halves,
the side beside the guide (lower part or full height), or the band over his own side. A drawing that cannot fit
readably is dropped with a note; a thin strip diagram is swapped for the library illustration of the same idea.
On a meme pop-up line the side drawing makes way for the card and comes back the moment it is gone.
Zones never overlap, so text never lands on text or on the guide; a new drawing that covers an old one of the
other slot clears it first. The compiler keeps the guide's arms clear: he points only where his hand cannot reach a
drawing, shrugs only where there is room, and a drawing is cleared before he walks through it.

### The doodle library (kindled_iron/doodles/)

150 finished illustrations in the channel style (ink lines, flat palette fills, orange/blue highlights), each with
tags and named label slots: money, phone, house, car, Bible, cross, heart, brain, clock, scales, bar chart, line
graph, venn, triangle diagram, earthquake, storm, hospital, child, family, crowd, crown, chain, broken chain, lock,
key, door, road fork, mountain, sun, stars, fire, water, tree, globe, question mark, lightbulb, gift, trophy,
hammer, shield, sword, chair, prison bars, mirror, mask, ladder, bridge, seed, cup, bread and more. The planner
picks one by tag/meaning and fills its label slots from the script; it composes from the built-in diagrams only
when nothing fits, and those concepts are logged in `doodle_misses.json` (also counted in status.json) so the
library can grow. They draw on stroke by stroke like every drawing (the runtime's `doodle` primitive).

To add or change a doodle: edit `kindled_iron/doodles/build.py` (one `doodle(name, tags, doc, parts, labels)`
call), then `python -m kindled_iron.doodles.build`, review `python -m kindled_iron.doodles.sheet --out /tmp/sheets`,
and regenerate the catalog (`python -m kindled_iron.director.catalog`). Faith rules apply: no occult imagery, no
eyes as symbols, God is never drawn as a figure.

### AI providers, budget and quota waits

One interface (`kindled_iron/director/llm.py`) for the shot plan and the vision review. The providers and their
models are in `kindled_iron/director/providers.json` (free tiers only), tried in this order:

| # | Provider | Secret (repo settings -> Secrets -> Actions) | Notes |
|---|---|---|---|
| 1 | Gemini Flash | `GEMINI_API_KEY` | the key's own Flash models, strongest first |
| 2 | GitHub Models | none: the workflow's own token (`permissions: models: read`) | small requests (8k tokens): gets the compact prompt |
| 3 | Hugging Face | `HF_TOKEN` | free inference credits; chat + vision models |
| 4 | Groq | `GROQ_API_KEY` | chat + vision models |
| 5 | OpenRouter | `OPENROUTER_API_KEY` | only models ending in `:free` are ever called |
| 6 | Cloudflare Workers AI | `KINDLED_CF_ACCOUNT_ID` + `KINDLED_CF_API_TOKEN` | Kindled's own account only; Night Files' Cloudflare secrets are never read |
| 7 | Claude | `CLAUDE_CODE_OAUTH_TOKEN` | OFF unless `"allow_claude_fallback": true` in providers.json; at most 1 plan call per video, never the review |

To add a key: create the secret with exactly that name in the MoneyPrinterTurbo repository settings; nothing else
changes (a provider whose secret is missing is skipped). To change a model: edit providers.json (`chat` / `vision`).
Pay-per-use keys are never used, and a test fails if the director code references them or Night Files'
Cloudflare secrets.

How a call goes: a provider that answers 429 / quota / 5xx / a timeout is marked exhausted for the rest of the run
and the next one is asked; the vision review only asks providers with a vision model; every answer goes through
the same plan checks, whoever sent it. Each call is logged with its provider and model (`ai_calls.json`,
`review.json` -> `ai` and `calls`, `status.json`).

Budget per video: at most 3 plan calls and 1 vision call; plain mistakes are repaired in code first. When every
provider is exhausted the video is not failed: status.json says `waiting_quota`, `checkpoint.json` keeps the
alignment, the calls used, the last errors and any plan that already passed, and the run exits 75 (a notice, not a
red run). The workflow's daily schedule (07:17 UTC, after the Gemini reset) resumes only waiting videos; `NTFY_TOPIC`
gets an alert only if one is still stuck after 24 h. (GitHub runs schedules from the default branch's copy of the
workflow, so the automatic retry starts once this is merged to main.)

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
| coverage | at least 60 % of the usable frame (safe box minus the button column) is covered at every half second (from 0.25 s, skipping the freeze zoom and its redraw), and no single empty rectangle is larger than 20 % of it |
| doodles | every drawing is at least 250 px on its long side (measured on the page) |
| empty | no empty card, no empty verse page, the clip box never empties |
| per_line | every line brings a new drawing and new clip-box content (or its verse card) |
| box_media | at least one real clip or meme in the clip box |
| verses | every reference / quote in the script is on a typed verse card |
| alignment | at least 85 % of the script's words are heard in the MP3 |
| music, sfx | (full render) theme_1 is in the mix; sound effects are in the mix |

## Reading fail_report.md

It lists each attempt (one AI plan, at most 3) and the exact checks it failed; those lines are what the planner received as
fix_errors in the next round. Typical causes and what to do:

- `script.txt does not match narration.mp3`: the script is not the recording's text. Fix script.txt.
- `no stock video matches 'x'`: the planner's footage idea found nothing that really shows it; it is retried
  with another query automatically. If it keeps failing, add a fitting meme/clip to movie_reference/.
- `cannot be drawn 250 px or larger here`: the line's two drawings were both tall; the planner is told to make
  the first one wide.
- `the frame looks empty` (coverage): a line's drawings are small for their slots; retried automatically.
- A renderer `AUDIT FAIL` that repeats every round is a compiler bug (a zone rule), not the plan: report it.

## Outputs (previews/<id>/)

`<id>.mp4` (private preview), `<id>-8-frames.jpg`, `scene.json` (what was rendered), `plan.json` (the AI's plan),
`media.json` (every clip/meme pick, its source, page and why it matched), `gates.json`, `review.json` (vision
verdict per still + the AI calls by provider), `ai_calls.json` (every AI call: provider, model, tokens, seconds),
`doodle_misses.json`, `rounds.json`, `checkpoint.json`, `status.json` (state: done | failed | waiting_quota), and
`fail_report.md` only when it failed.

## Secrets (MoneyPrinterTurbo repo settings, names only)

`GEMINI_API_KEY` (free tier), `VOICE_REPO_TOKEN`, `PEXELS_API_KEY`, `PIXABAY_API_KEY` (optional), `FREESOUND_API_KEY`
(for the record scratch, optional), `NTFY_TOPIC` (optional phone alerts), and the optional AI fallback keys in the
provider table above.

## Local offline test (no keys)

```
KI_LLM_MOCK=test/kindled_iron/mock_epicurean KI_BOX_PLACEHOLDER=1 KI_MUSIC_SOURCE=generated \
  python -m kindled_iron.director.direct --id epicurean-paradox --private ../kindled-iron-voice --out /tmp/out
for t in 'test_director*.py' 'test_llm*.py' 'test_direct_budget*.py'; do python -m unittest discover -s test/kindled_iron -p "$t"; done
```
