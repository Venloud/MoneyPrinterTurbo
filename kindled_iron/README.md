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

## Channel format (every video)
Every video answers ONE question people really ask:
1. The question on screen and spoken in the first 2 seconds.
2. A straight answer by 10 seconds.
3. Then the reasons, each one backed by a scripture card.
4. A last line that closes the loop (comes back to the question).
God is NEVER drawn as a person or figure: the word GOD in burnt orange and/or warm light only.
The guide is the HOST: large (35-45 % of the safe-box height), front-facing, lower part of the frame,
talking to the viewer, pointing at what matters, reacting (eyebrows only inside a reaction).

## Scripture cards (scripture.py, WEB text in data/web_bible.json.gz)
In the narration a reference is written in brackets: `"From everlasting to everlasting, you are God." [Psalm 90:2]`.
The bracket is WRITTEN on screen, never spoken and never captioned (it is stripped from the TTS text).
The beat gets a card event: `{"scripture": {"ref": "Psalm 90:2", "text": "From everlasting to everlasting, you are God."}}`
(optional `x`, `y`, `w`, `size`). The quote is found in the spoken words and written on exactly while it is
spoken; the reference (burnt orange, small open-Bible icon) appears when it ends, with a soft chime; the card
stays at least 1 s after the quote (a scene change waits for it).
Translation: World English Bible (public domain, eBible.org). Every card's text must be the WEB verse or a
contiguous part of it, word for word (case/punctuation ignored); any mismatch, a book outside the 66, or a
[Ref] without a card FAILS the render. Check one by hand: `python -m kindled_iron.scripture "John 1:3"`.
The video shows no translation label; the post description carries "Scripture: World English Bible"
(added automatically to `<name>_meta.json` -> `post`, and to the phone alert).

## Hook + retention rules
- First 2 seconds: the question/hook is fully on screen at frame 0 (`"instant": true` draws), with
  motion from frame 1 (camera pull-back, wiggle). No slow fade-in.
- Something new or moving at least every 1.5-2 s: `PACING WARNING` if no event for over 2 s
  (ambient motion keeps running anyway: sun turning, waves, drifting clouds, birds, swimming fish,
  swaying trees/plants, twinkling stars, blinking characters).
- A small `DAY n` counter with progress dots (`{"do": "counter", "day": 3}`, `day: 0` hides it).

## Pacing (pacing.py)
Kindled Iron uses `"pacing": "tight"` (voice_profiles.json):
- No pause padding. ElevenLabs reads the whole script in ONE request (speed 1.0-1.05, no break tags) and
  its natural read is kept.
- On the final audio every silence longer than `trim_over` (0.45 s) is cut to `keep_gap` (0.40 s); natural
  shorter pauses stay; the lead-in is cut to 0.05 s.
- No added pauses: `max_beats` is 0 (a `[beat]` tag fails the render).
- Target **about 175 words a minute** (`wpm_target` 165-185, a WARNING above 185), ElevenLabs speed 0.90, never
  below 0.87 (`min_speed`); 61-64 s (`length_target`), shorter is fine, never pad.
  Log: `pacing: tight - N silences trimmed ..., longest silence X s` and `Length: X s ...; pace N words/min`.
- A visual change at least every 1.5 s (scene `"max_visual_gap": 1.5`, `PACING WARNING` otherwise);
  captions 2-3 words at a time, bold, big (scene `captions_box` {x, y, w, size}, `captions_chunk`
  {max_words, max_chars}), inside the safe box and clear of the button column.
Other channels can still use the older sentence pauses (`pause_sentence`, `pause_beat`, `max_pause`,
`[pause 0.8]` tags).
- Captions and every animation follow the final audio. A beat starts inside the pause before it, so
  its walk / first drawing lands in the silence; footage insets snap into the nearest pause; and
  `"at": "pause"` / `"pause#2"` puts any event in the 1st / 2nd pause of its beat (the DAY counter ticks
  in the pause before each "Day N" line).

## Voice text (scene "tts_text")
The voice reads the scene's `tts_text` in ONE ElevenLabs request: the script's exact words (checked; only
punctuation may differ), with short fragments joined by commas so it does not sound chopped and real stops only
where a stop is wanted. Captions and on-screen text keep the script's own punctuation. The returned read is never
cut, re-spaced or stretched. Delivery: calm, soft, conversational (speed 0.97, stability 0.5, similarity 0.8,
style 0.18; if it sounds pushed or bright, lower style first). No recording is used anywhere.

## Clean voice (sound.py, every provider)
High-pass 85 Hz, de-plosive (the band under 160 Hz is compressed hard only above its own loud level), light
de-esser, a 1.5 dB dip at 3 kHz, gentle compression; voice at -17 LUFS, true peak target -2.5 dBTP. A clip's own
audio ("God did") is matched to 1 dB under the voice. The render FAILS if true peak > -2.0 dBTP or a low-frequency
burst (< 120 Hz) is more than 10 dB above the voice's average level.

## Music (voice_profiles.json: music_source = mine | generated | none)
- mine: the owner's track from the PRIVATE repo's `music/` (`music_file` = exact name, `music_start` = seconds),
  checked out at render time, never copied here; metadata `use_third_party_music: true`.
- generated: an original ElevenLabs Music theme (`music_gen.py`, 3 candidates `theme_1..3`, ~90 s, loopable,
  kept in the private release `music-themes`, made once); `music_generated` picks one.
- none.
Mix: about 22 dB under the voice (loudness), a further 3.5 dB under speech plus a 3.5 dB dip at 1-4 kHz while a
word is spoken, rising in the gaps and +2 dB on the last line (`music_lift`), 1 s fade in, 2 s fade out, looped
with a 2 s crossfade if the video outlasts it. Every render also writes `<name>_nomusic.mp4`.
Workflow input `music_source` switches it for one run. A render with any music goes only to the private release.

## Sound effects
Max 8, each about 20 dB under the voice, never starting on top of a word (moved into the nearest pause):
scripture chimes, a soft whoosh on the big scene changes, soft hits on the key lines. No pencil sounds.

## Publishing (publish.py, kindled_iron_publish.yml: the ONLY thing that posts)
1. Approve: the render's file name goes into the private repo's `approved/index.json`.
2. Run **Kindled Iron Publish** (input `render`, empty = latest approved; `check_only` = connections only).
   It refuses fallback-voice renders and renders that failed a check, checks every platform first, skips a
   platform whose check fails, and one failing platform never stops the others. One ntfy with the links.
- TikTok: refreshes the token first (saved back to secrets); direct post when the app has `video.publish` and
  TikTok accepts it, otherwise the TikTok inbox (draft). YouTube: resumable upload, public Short, not made for kids,
  AI-voice disclosure on. Instagram: Reel by resumable upload (no public URL); Threads: video fetched from a
  temporary public release of this repo, deleted at the end of the run. Facebook: Page Reel.
- `publish_config.json` -> `publish_mode` per platform: live | draft | off.
- Mondays the workflow refreshes the Instagram / Threads / TikTok tokens and alerts (ntfy) before any expires.

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
`PIXABAY_API_KEY`), Wikimedia Commons (no key; only files whose API metadata says public domain or CC0, so no
credit lines). Never CC BY / CC BY-SA. Default order Pexels -> Pixabay -> Commons; space / Earth shots put NASA
first. Max 8 a video; no clip found = the inset is silently left out.
Big clips: `w` 820 / `h` 470 at (540, 410) fills the upper half of the safe box; drawings go beside or on
top. `"inset_snap": false` on the scene keeps clips on their words (no snapping to pauses). Every render
logs each clip's source + licence and writes `insets_contact_sheet.jpg` (CI artifact `insets.jpg`).
NASA search results are mixed (press conferences...), so pin NASA clips after checking frames.

## Third-party clips and meme images (private_media.py)
Never stored in this public repo (git ignores `reactions/`, `movie_reference/`, `reactions_inbox/`). They live in
the PRIVATE repo `Venloud/kindled-iron-voice`: `reactions/` (meme images and reaction clips, named by emotion or
words: `confused.jpg`, `god_did.mp4`) and `movie_reference/` (film/TV clips named by scene: `burning_bush.mp4`),
each with an optional `index.json` (tags, words said, start/end seconds, play its audio). The test workflow
checks them out at render time with `VOICE_REPO_TOKEN`; any render that used them goes ONLY to the private
`test-renders` release (with its stills), never to a public artifact.
- Clip request: `{"at": "Moses-0.2", "id": "c_bush", "x": 540, "y": 410, "w": 820, "h": 470,
  "meme_clip": {"query": "burning bush", "folders": ["movie_reference"], "max_s": 2, "audio": false},
  "fallback": {<a normal stock inset or guide action>}}`. Order: private folders -> yt-dlp (only with
  `"yt": "<url or exact search>", "start": s`; YouTube often blocks runners) -> the pinned fallback. A missing
  clip never fails the render. A clip with `"audio": true` plays its own sound at voice level; the video runs on
  until it ends.
- Emotion request: `{"at": "who", "reaction": "confused", "card": {"x", "y", "w", "h", "rotate"}}`: the guide acts
  the face AND a meme image pops in beside him: private `reactions/` first, then
  github.com/cheesits456/ReactionPics (hand-picked file names per emotion, downloaded at render time, never copied
  here). GIPHY is not used in videos: its API terms require a visible "Powered By GIPHY" mark plus creator credit.
- One switch: `voice_profiles.json` -> `use_third_party_clips` (workflow input `third_party_clips` wins): off =
  every request uses its fallback / the drawn face only.
- Add a clip from your PC: `python kindled_iron/tools/fetch_clip.py "<url or search>" --start 12.5 --dur 2
  --name burning_bush --folder movie_reference` (needs yt-dlp, ffmpeg and a token for the private repo).

## Reactions (use sparingly)
`{"do": "reaction", "who": "guide", "face": "shocked", "dur": 1.2}`: faces `confused_math` (floating math
symbols), `puzzled`, `surprised`, `shocked`, `mind_blown`, `side_eye`, `crying_laughing`, `thinking`, `wait_what`.
Images in `reactions_inbox/` are preferred when present. Eyebrows exist ONLY inside a reaction (never angled
down = never angry). Hard limits (extra ones are dropped with a WARNING): max 3 a video, 3 s apart, under
1.5 s, never on a scripture card or on GOD (`"allow_god": true` only lifts the word-timing rule for a question
like "who made God?", where GOD is not drawn). Record-scratch meme: `{"do": "freeze", "zoom": 1.45}` (gray
freeze-frame + "*record scratch*" + zoom).
Guide moves: walk in, `lean_on` a card, `size`, `drift`, point, react; change side, size and pose every scene.
Pop-culture drawings are our own generic shapes: `voxel` world, `blockfolk` villager, `cursor`, `clock`,
`controller`, `popup` ("CHEAT ON"); no game textures, logos, characters or UI.

## The host
The guide is drawn after the channel owner (`render.HOST_LOOK`): brown skin, shoulder-length twisted locs with a
middle part, small mustache + chin goatee, a slightly hand-drawn head; bare arms and hands in the same skin tone.
Outfit: black short-sleeve button-up (light-blue collar, buttons, chest pocket, sleeve trim, light shading),
black pants with a beige belt and side stripe, dark shoes with beige soles, no scarf. A scene can
switch it off with `"look": false` on the guide. Pose sheet of the faces:
`python -m kindled_iron.action_sheet --faces --out faces.png`. He stands low: his feet may sit a little below
the safe box (scene `ground` 1490); the space above is padding for text.

## Captions vs titles
Captions never overlap a title (popup, scripture card, a big word of 80 px or more, or `"title": true`) and
never sit on the guide's head: they move to the nearest free spot, then shrink (to 64 %). When the same words
are already written big on screen, the caption hides. The layout check logs `CAPTION OVERLAP` and
`... over the guide's head` otherwise. The record-scratch freeze stays in colour; `"focus": {"x", "y"}` sets
what the punch-in frames.

## Faces
Everyone (guide, man, woman) has the same simple face: two dot eyes and a small mouth, friendly and
calm by default. `express` / `look` expressions: `neutral`, `happy`, `surprised`, `curious`, `awe`
(older names map: thinking/focused -> curious, speaking/sad -> neutral). The guide always wears the
orange scarf; people are told apart by hair, clothes and height.

## Sound (sound.py, library built once by sfx_library.py)
Few effects, each one meaning something. Hard cap 8 a video (`max_effects`), never two within 1 s
(`min_spacing_s`), about 20 dB under the voice, never on top of a word, in this priority:
1. a big hit on the key moments only: events marked `"hit": true` (max 3), e.g. "nobody", "I AM", the last line
2. a soft chime when each scripture reference appears (dropped when a hit lands within 1 s)
3. a soft whoosh on big scene changes (beat `"whoosh": true`)
4. pencil sounds are off (`"pencil": false`)
No per-stroke sounds (no marker, scribble, eraser, scratch) and no ambience beds. `"sound": "<role>"` /
`"sound": false` on an event overrides.
Music: none for Kindled Iron (`music_track` "none"). Otherwise one track per channel (`music_track`, file `vendor/sfx/lib/music_<name>.ogg`;
`--music <name>` on render.py overrides), from frame 0, ducked under the voice, a +3 dB lift from the beat's
`"music_lift": "<word>"`. `python -m kindled_iron.music_samples` mixes every track under the same 10 s of voice.
Levels live in `sound_levels.json` (`sfx_levels` in dB relative to the voice, plus a master `sfx_gain_db`):
pencil -20, pops/chime -18, big sounds -14 (never peaking above the voice), music -24, all 4 dB lower while
someone speaks. The -14 LUFS target is set on the VOICE; effects and music are never boosted to reach it.
Each render writes `<name>_sounds.json`: every sound with its time, file and source.

Library: `vendor/sfx/lib/*.ogg` + `vendor/sfx/lib/sources.json` (licence per file). Source order:
Kenney CC0 -> Freesound CC0 only (API with FREESOUND_API_KEY, else the public CC0 search page; every
sound page re-checked for CC0) -> ElevenLabs Sound Effects (only with `--allow-elevenlabs`). No CC BY,
no Shutterstock. Picks are pinned in `vendor/sfx/lib_pins.json`; to swap one, change the id and run
`python -m kindled_iron.sfx_library --roles <role>`.

## Writing rules (every script)
- Write for adults: simple words, but no kid voice. Never repeat a point, never explain the obvious.
- The hook (first line) is answered fast; no theology jargon.
- Leave out side details. Summarize; never read verses.
- Only the Bible's 66 books; no claims the chapter itself doesn't support.
- **Length:** target a 61-68 s video (script ~170-190 words at 165-185 wpm). Shorter is fine only when the story is
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
Also `fade` (`ids`, `opacity`, `erase`), `pulse` / `wiggle` (`id`), `move` (`id`, `dx`, `dy`, `dur`),
`rise` (`id`: grows up out of the ground), `drop` (`id`: falls in from above and lands), `counter` (`day`),
`shake` (no `who` = camera shake), `paper` (`dark` 0..1: dark paper), `light_burst` (`x`, `y`, `dur`,
`hold`: the light fills the whole scene, paper brightens, rays spread from x,y; no spotlight).
Object `layer: "top"` stays visible on the dark paper; `still: true` = no ambient motion.

### Characters (`who` = a cast id)
`enter` (draws the character in), `exit`, `walk` (`to`, `speed`, `camera`, `camY`, `camZoom`, `face`;
turns first, never walks backwards), `point` / `reach` / `touch` (`toward`), `wave`, `cheer`, `react`,
`shrug`, `present`, `look` (`dir` up|down), `kneel`, `express` (`expression`), `face` (1 / -1),
`place` (`x`, `facing`, `hidden`), `size` (`value`: big + centred only for the hook and the last line),
`drift` (`to`: float across). Scene actions: `float`, `parachute` (`from`, `y`, `dur`), `pop_up`, `climb`
(`dx`, `dy`), `sit` (`against`: a tree id = back to the trunk), `lie_down`, `swim` (`in`: a waves id;
lower body under the water line, `snorkel`), `jump`, `fall`, `ride` (`on`: an animal/fish id; seated,
moves with it), `peek` (`toward`, `side`), `pet` (`toward`), `shield_eyes`, `look_viewer`, `stand`.
Shorthand: `{"guide": "parachute", "at": ...}`. Contact check: sit / lie / ride / swim must really touch
the ground, animal, trunk or water (LAYOUT WARNING otherwise).
Gestures hold for `hold` seconds, then return to rest. Cast options: `hair` (long-straight, short),
`dress`, `accent` (orange scarf), `colors`, `scale`, `facing`.

### Beats
`transition`: cut | slide | zoom | wipe (a new panel with no walk slides by default). `ambience`,
`music_from`, `serious`, `interaction: false` (no "guide touches a drawing" warning).

### Camera
`{"do": "camera", "x": 560, "y": 860, "zoom": 1.12, "dur": 1.0, "ease": "power2.inOut"}` (panel-local).

Upstream credit and what was vendored: `vendor/stickman-animation-agent/NOTICE.md`.

Kokoro British voices (`bf_*`, `bm_*`) need `"lang": "b"` in the profile's `kokoro` block.
