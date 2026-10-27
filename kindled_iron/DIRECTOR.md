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
 1b story   story.py (no AI call): the spoken sentences on the narration's clock and what each one does (points at a
            visual, asks, gives examples, quotes); story.json. diagram.py: where the narration introduces a library
            diagram and walks through what it shows, that diagram is shown WHOLE for those sentences (below)
 2 plan     the AI (Gemini -> GitHub Models -> Hugging Face -> Groq -> OpenRouter -> Cloudflare, see "AI providers") writes a SHOT
            PLAN per line: 2 drawings (a library doodle picked by tag, or a built-in diagram, + labels), clip-box
            media (stock search words or a meme from your library), a typed verse card, an optional meme
            pop-up, the guide's expression and gesture, and ONE record-scratch freeze. Meaning only, no
            coordinates. The prompt carries both golden scenes in full (Where Did God Come From?, Love of Money
            v3), their per-line summary, the drawing catalog, the media library (memes + stills), the guide actions and the rules below.
 3 check    plan.py rejects anything off-script or off-catalog; media.py finds the footage; compile.py turns the
            plan into a scene: every coordinate comes from the fixed zones and each drawing's measured size
 4 render   the existing renderer: first 8 stills + the every-frame audit, then the full MP4
 5 gates    plain mistakes are repaired in code first (no AI call); any failed gate goes back to the planner as
            "fix_errors"; at most 3 plan calls per video, else fail_report.md
 6 review   one vision call looks at the 8 stills with their lines; one automatic fix round if the plan budget
            allows; review.json. Accepted (status ok: true, state done) ONLY when every gate passed and the review
            of the final video said pass: a failed or missing review, or a video revised after its review and not
            reviewed again (1 vision call per video), is a FAIL with fail_report.md
```

Files: `kindled_iron/director/` (`direct.py` runs it all, `plan.py`, `compile.py`, `media.py`, `gates.py`,
`review.py`, `gemini.py`, `catalog.py` + `catalog.json`). The renderer (`render.py`, `runtime/runtime.js`,
`mediabox.py`) draws exactly what the scene says, as for the hand-made videos.

### The fixed layout (catalog.json "zones")

| Zone | Where (1080x1920) | What goes there |
|---|---|---|
| Clip box | top, up to 820 x 380 (y 180-560) | stock footage, your memes, the typed verse card; only while it holds media, its frame shaped like that media; a line without media draws here instead |
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

### No media, no frame

The clip box exists only while it shows something real: a clip, a library picture, a verse card. Each item shows
during its own line and the box goes when the line ends (unless the next line's own media follows at once). Its
frame takes the media's shape (a 16:9 clip 674 x 380, a square picture 380 x 380, a tall one 212 x 380), so
nothing is stretched or padded into an unrelated frame. A line with no fitting media has no box at all. A video
may start without it.

Drawings are the house style, not a quota: a line gets the 0-3 illustrations that show what it says (one strong
idea -> one drawing, shown large), never a decorative one. The layout follows what is on screen:
- the captions sit at the middle of the frame (their default anchor, about the centre line) with or without a clip
  box; everything is arranged around them: the clip box at the top, the drawings between the box and the caption,
  the guide below (owner, 2026-10-27: captions were too close to the top). The runtime still shifts or shrinks a
  caption that would cover a face or a drawing, and a diagram brings its own caption band;
- with no box, the drawings get the whole space above the caption (one big drawing, two side by side or two
  stacked, plus one beside the guide);
- a line whose media comes late in the sentence (over 1.2 s in) opens with its first drawing where the box will be;
  that drawing gives way just before the media arrives;
- at a layout change the line's main drawing takes the middle at once (already in the pause before the line, once
  the previous clip or verse card is gone), and the hand-over is ordered so nothing is ever under a caption: the
  clip leaves, then the caption moves up; the middle drawings clear, then the caption comes back down.

### Diagrams, charts, maps, flowcharts (director/story.py + director/diagram.py)

A library item with `"type": "diagram"` (or flowchart, chart, map, infographic) is a complete composition. It is
never a box meme and never split into drawings. It is shown when the narration does two things in a row of
sentences: points at a visual ("this graph", "the map", "look at...") or names the diagram's subject, and then keeps
talking about what the diagram contains (its subject, topics, aliases, description and region text) for at least 3
sentences (short asides like "Sounds crazy, right?" may sit between). It goes when the narration moves on, at most
30 s, and before any verse / quote. No video id and no script phrase is ever a trigger (a test checks the code).

While it is up:
- the WHOLE image, uniformly scaled: `scale = min(available_width / width, available_height / height)` into the
  safe area (beside the button column for a tall diagram, across the top for a wide one), never cropped, split,
  stretched or rearranged, no frame around it (`mediabox.py` refuses a rectangle that would change its shape);
- captions sit in their own band under it (inside the safe area);
- nothing else is drawn where it is: the planner's drawings for those words appear after it (or are left out when
  their line ends first), no clip, meme card, freeze or walk;
- when it reaches down over the guide, he steps out (a cut) and comes back the moment it goes; the normal layout
  returns with him.

Region focus (a view move over the intact image, never a cut file) is available only for library items with
`"region_rendering": true` and `regions` (`{"id": {"rect": [x, y, w, h], "text": ..., "keywords": [...]}}` in image
pixels), and only after the whole diagram has been on screen 2 s and a sentence names one region's keywords; the
focus lands on that spoken word. Items with `"region_rendering": false` (the Epicurean Paradox flowchart) always
show whole; their regions stay as metadata for later.

Readability: `"min_text_px"` (the smallest text's cap height in the original) gives the smallest text on screen;
under 18 px is reported as a limitation in status.json / media.json. The diagram is still shown whole (cropping or
splitting it needs the owner's approval).

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

## Adding memes, stills and clips

The library is `kindled-iron-voice/movie_reference/` and `kindled-iron-voice/reactions/` (jpg, png, webp, gif, mp4,
mov). Every top-level file there is offered to the planner; the file name's words are its tags
(`suspicious-fry-futurama.webp` -> suspicious, fry, futurama). Optional metadata in that folder's `index.json`:

```json
{"file": "confused_question_marks.png", "type": "meme", "tags": ["confusion", "question", "disbelief"],
 "description": "man smiling in confusion with question marks around his head", "tone": "comic confusion",
 "purpose": "react to a claim that makes no sense", "same_meme_as": ["movie_reference/confused-nick-young.jpeg"],
 "show": true, "source": "...", "license": "..."}
```

`type: "still"` = a real-looking picture of a subject (used like stock footage); anything else is a meme.
`show: false` (guide-action references in `movie_reference/guide_actions/`) is never shown: the guide acts it out.
A missing or broken `index.json` only loses the extra tags; the files are still found by name.

Import a curated pack (a ZIP with `catalog.json`) without touching what is there:
`python kindled_iron/tools/import_media.py --zip pack.zip --private ../kindled-iron-voice [--meta extra.json] [--dry-run]`
(sha256 duplicates skipped, taken names get `_2`, nothing overwritten, index entries only appended, licences copied
as given, a report of what was imported / skipped / renamed / looks alike).

Rules the code enforces (plan.repair, no AI call):
- a meme or still is kept only when it fits its line: a shared word, or the same reaction family ("crazy" ~ "wait
  what", "earthquake" ~ "collapsed house"; the line's expression counts too). Dropped otherwise (logged).
- each meme once per video, look-alikes (`same_meme_as`) included; at most 4 memes per video (box + pop-ups).
- no line needs box media (the hook neither): a box item shows only during its own line (the real review of run
  40446183634 failed one chalkboard clip held over lines 1-4). Nothing is ever added just to fill the box.
- stock footage must show what the LINE says (media.py, every decision with its reason in media.json):
  the planner's query must share a subject word (or a reaction family) with the line, else it is left out; a result
  must share a subject word with the query, setting words alone ("classroom", "street", "looking"...) do not count;
  footage whose subject is writing or a chart (chalkboard, sign, screen, graph on a monitor...) is turned down unless
  the line itself names it. No fitting result = no frame on that line, not an error. The run-15 BACK TO SCHOOL clip
  came from the planner prompt's own example query ("chalkboard diagram classroom", now removed) and was accepted
  on the shared word "classroom"; both are fixed. Verification is by the provider's title / page words (recorded
  as `"verified"`); frames of stock clips are not inspected by a vision model (the budget is 1 vision call per
  video, used on the final video).
- a reaction meme is never put on a grave line (suffering, death, harm to children, grief): it would read as mockery,
  whatever words it shares with the line.
- pop-ups: at most 3 per video, at least 2 lines apart, never on a verse line or on the word "God", 380 px wide,
  1.2 s; no file twice in a row and no file more than twice per video.
- box items without a word are anchored on a spoken word of their line (the word their query or file names, else the
  line's first word); empty box items are dropped (a line may have no box); a box item `kind: "verse"` becomes the
  line's verse card; a line that names a reference gets one; `quoted: true` without a word-for-word quote of the WEB
  text becomes `quoted: false` (the card types the WEB text itself). The scripture checks themselves are unchanged.
- a drawing type that is not in the catalog (e.g. a media file name) becomes the closest verified catalog drawing
  (name, concept and labels against the catalog's names, tags and descriptions), or is dropped when the line keeps
  another one; otherwise the plan is rejected.

### The timeline check (before any render)

compile.py records every drawing's box and show/clear times and every meme card's window, and checks them the way
the renderer's per-frame audit does: no drawing under a meme card, no two drawings over each other. What it finds is
fixed in code (the drawing makes way for the card, appears after it, or the earlier drawing is cleared first; listed
in `scene.json` director.timeline_fixes); anything left rejects the plan before rendering. The per-frame audit
still runs on every render.

Layout rules that keep the frame filled (found replaying run 40434188836's three real plans):
- meme-card lines: the band holds two drawings when it can (the side beside the guide is the card's while it is
  up); a third may go beside him: it appears once the card is gone or makes way for it. A drawing beside the card
  clears just as the card appears (0.12 s before) and comes back as it goes (0.02 s after).
- the compiler applies the renderer's own card rules: no card within 0.4 s of the word God, none within 3 s of the
  previous card (moved to the next clear word or dropped, noted).
- a drawing whose place is free before its word is drawn as soon as it is free (staggered); an empty place may be
  filled in the pause before its line (at most 0.5 s ahead). Never into the guide's walk, a card or the freeze.
- drawings due well before the freeze show on their word, clear for the zoom and come back inside their line; after
  a freeze that cleared the board for good, the next line draws at its start. An old band drawing that no new
  drawing covers stays for one more line.

### Guide actions (director/actions.py)

The plan's `gesture` is an action the approved guide performs with his existing rig (never a stand-in figure):

| Action | Status | What he does |
|---|---|---|
| point, point_explain, shrug, present, look, wave | supported | as named |
| think | supported | looks up, thinking |
| realize | supported | "wait what" double take, then mind blown |
| confused | supported | shrug with a confused face (a puzzled head tilt where his arms have no room) |
| celebrate | supported | both arms up, hops (only where his arms have room) |
| choose_path | partial | turns to one side, the other, then points at the drawing; cannot walk a path |
| frustrated_at_screen | partial | shakes his head, then a side-eye; holds no screen |
| help_up, carry | unsupported | reported in `guide_actions.json`, the guide points instead |

An action that does not fit (a walk, a meme card or the next line in the way, no room for his arms) falls back to a
look up and is logged as not performed.

### The record-scratch freeze

The freeze plays `kindled-iron-voice/sfx/record_scratch.mp3` (the owner's recording, silence trimmed in code, at the
record_scratch level; the sound library has no record-scratch variants, so without this file the freeze is silent) and the whole frame goes grey while it holds
(`"grey": true` on the freeze event; scenes without it keep the colour freeze).

## Gates (the bot fails instead of shipping)

| Gate | Passes when |
|---|---|
| render | the renderer finished (its every-frame audit fails it on any overlap) |
| layout | zero layout warnings |
| audit | zero every-frame audit issues |
| coverage | at least 60 % of the usable frame (safe box minus the button column) is covered at every half second (from 0.25 s, skipping the freeze zoom and its redraw), and no single empty rectangle is larger than 20 % of it |
| (proposed) composition | REPORT-ONLY until the owner approves it (`gates.json` -> `_proposed_composition`, never counted in the result): every third of the usable frame (top / middle / bottom) holds something and no empty region is over 30 %; failing for 1 s or more = an unfinished frame. Negative space between drawings is allowed; a whole empty part of the frame is not. Drawing-led frames like the owner's reference measure 0.4-0.55 bounding-box coverage, so the 60 % floor fails them although they are finished compositions |
| doodles | every drawing is at least 250 px on its long side (measured on the page) |
| empty | no empty card, no empty verse page |
| per_line | every line brings a new drawing, unless the whole diagram is on screen for it |
| box_media | no frame without media: every clip-box segment holds media that loaded (none failed), shaped to it |
| diagram | a whole diagram is inside the safe area and clear of the button column, uniformly scaled, its caption band inside the safe area and not over it, at most 30 s (readability reported) |
| verses | every reference / quote in the script is on a typed verse card |
| alignment | at least 85 % of the script's words are heard in the MP3 |
| music, sfx | (full render) theme_1 is in the mix; sound effects are in the mix |

## Reading fail_report.md

It lists each attempt (one AI plan, at most 3) and the exact checks it failed; those lines are what the planner received as
fix_errors in the next round. Typical causes and what to do:

- `script.txt does not match narration.mp3`: the script is not the recording's text. Fix script.txt.
- No fitting footage is not a failure: the line goes without the box (media.json says why each result was turned
  down). To give such a line a picture, add a fitting still to movie_reference/ (with tags / description).
- `cannot be drawn 250 px or larger here`: the line's two drawings were both tall; the planner is told to make
  the first one wide.
- `the frame looks empty` (coverage): a line's drawings are small for their slots; retried automatically.
- A renderer `AUDIT FAIL` that repeats every round is a compiler bug (a zone rule), not the plan: report it.

## Outputs (previews/<id>/)

The same folder for every run. The video and its evidence are replaced together, only by a new render that is a
complete, valid video (ffprobe: 1080x1920 video + audio, the narration's duration; a full decode without errors):
the new files are staged in a hidden temporary folder (removed afterwards) and moved in place, `video.json` (the
manifest: the MP4's sha256, size, duration, run, director commit, narration sha, review verdict, accepted) last. A
failed or incomplete render never replaces the previous video; status.json says which video is current
(`video.kept`: new | previous) and why a new one was not saved (`save_error`). Each attempt renders in its own
temporary folder under storage/director/<id>/ (deleted at the end of the run), so a review fix round never touches
the reviewed render. A revision that passed the gates is saved as the newest video with verdict
`fixed_not_rereviewed` and the earlier review under `previous_review`: never accepted (1 vision call a video).

`<id>.mp4` (private preview), `video.json`, `<id>-8-frames.jpg`, `scene.json` (what was rendered), `plan.json` (the AI's plan),
`media.json` (every clip/meme pick, its source, page and why it matched), `gates.json`, `review.json` (vision
verdict per still + the AI calls by provider), `ai_calls.json` (every AI call: provider, model, tokens, seconds),
`doodle_misses.json`, `guide_actions.json` (each action asked for: performed or why not), `rounds.json`, `checkpoint.json`, `status.json` (state: done | failed | waiting_quota), and
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
