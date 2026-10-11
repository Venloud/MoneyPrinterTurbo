# Kindled Iron: production

How a finished script becomes a posted video. No AI writes or changes anything at run time: you write the
script, the blocks decide the drawings, the renderer and the checks are plain code.

## The flow

```
your script (kindled_iron/queue/NNN-<id>.json)
  -> build_scene.py   blocks + slots -> scene JSON; checks anchors, WEB verses, caption, length (no credits spent)
  -> credit_guard.py  enough ElevenLabs credits? else skip the day + alert (script stays queued)
  -> render.py        ElevenLabs voice (default model) -> word timings (Whisper) -> drawings (Chrome) -> mix
  -> checks           1080x1920, audio, 55-95 s, decodes, no fallback voice, verses OK, true peak, low-end bursts
  -> private copy     release "test-renders" in the private repo (mp4, no-music mp4, meta, post text)
  -> publish.py       TikTok, YouTube Shorts, Instagram Reels, Threads, Facebook Reels
  -> ledger           approved/posted.json in the private repo: every post id/url; a scene is never posted twice
  -> queue/done/      the script moves there; ntfy tells you what posted and what failed
```

## Workflows (Actions tab)

| Workflow | File | What it does | When |
|---|---|---|---|
| Kindled Iron Daily | `kindled_iron_daily.yml` | the whole flow above for the next queued script; `dry_run` = render + checks only | manual; schedule written but OFF until you say go |
| Kindled Iron Test Render | `kindled_iron_test.yml` | renders one scene, uploads privately, never posts; `my_voice`, `tts_model`, `music_source` inputs | manual |
| Kindled Iron Publish | `kindled_iron_publish.yml` | posts one APPROVED render (private `approved/index.json`); `only` = some platforms; `check_only`. Daily 13:17 UTC: refresh tokens + check every platform, ntfy only if something needs you | manual + daily check |
| Platform Connection Check | `platform_connection_check.yml` | the same token refresh + check, on demand | manual |
| Meta Token Refresh | `meta_token_refresh.yml` | turns a short Facebook user token into a never-expiring Page token | when Facebook says the token is dead |
| TikTok OAuth Connect | `tiktok_oauth_connect.yml` | connects TikTok (refresh token) | only if TikTok rejects the refresh token |
| TikTok Connection Check | `tiktok_connection_check.yml` | TikTok only | manual |
| Voice Bootstrap / Compare / Samples | `kindled_iron_voice_*.yml`, `kindled_iron_voices.yml` | voice setup tools | rarely |

A platform that fails its check is skipped; the others still post. A post that went out is in the ledger, so a
re-run only tries the platforms that are missing.

## Secrets (names only; Settings -> Secrets and variables -> Actions)

- Voice/render: `ELEVENLABS_API_KEY` (needs User: read for the credit guard), `VOICE_REPO_TOKEN` (private repo
  read + write: media, renders, ledger), `PEXELS_API_KEY`, `PIXABAY_API_KEY`, `FREESOUND_API_KEY`, `GIPHY_API_KEY`
- TikTok: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REFRESH_TOKEN`, `TIKTOK_ACCESS_TOKEN`, `TIKTOK_OPEN_ID`
- YouTube: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`, `YOUTUBE_REFRESH_TOKEN` (new one: `kindled_iron/tools/connect_youtube.py`)
- Instagram / Threads: `INSTAGRAM_ACCESS_TOKEN`, `THREADS_ACCESS_TOKEN`
- Facebook: `FACEBOOK_PAGE_ID`, `FACEBOOK_PAGE_ACCESS_TOKEN`, `META_APP_ID`, `META_APP_SECRET` (+ `META_SHORT_USER_TOKEN` only while running Meta Token Refresh)
- Upkeep: `GH_SECRETS_WRITE_TOKEN` (saves refreshed tokens), variable `TOKEN_MIRROR_REPOS` (optional)
- Alerts: `NTFY_TOPIC` (below)

### NTFY_TOPIC

One secret, the topic name only: letters, digits, `-` or `_`, 1-64 characters, no `https://ntfy.sh/` in front
(e.g. `kindled-iron-7f3k9q2m`). Pick something long and random: anyone who knows the topic can read it.
Install the ntfy app, subscribe to that topic, then add the secret. Every alert (posted, failed platform,
queue empty/low, credits low, script error, token problems, render failure) goes there.

## Voice

- ElevenLabs voice `jRFiEvaIrFDZO8HLTCKI`, default model **eleven_v4** (`voice_profiles.json` -> `kindled_iron.elevenlabs.model_id`;
  aliases `v2 | v3 | v4`; the test workflow's `tts_model` overrides it for one run).
- v3/v4 read the script with `[tags]` (e.g. `[curious]`, `[light laugh]`) plus `...` and `—` for pauses, never `<break>`.
  Tags are stripped from captions, on-screen text, timings and the word check. Whisper checks no tag was read aloud.
- Settings: stability 0.5, similarity 0.8, style 0.18, speed 0.97, speaker boost. The voice chain cleans it to
  -17 LUFS, true peak under -2.0 dBTP (fails otherwise), no low-frequency bursts over +10 dB.
- Voice audio is cached by text + settings: a re-render of the same text costs 0 credits.
- Measured: eleven_v4 billed 126 credits for a 1,149-character script (v3: 460). The guard still counts characters x 1.3.

## Music

- Default: generated **theme_1** (private repo `music/theme_1.mp3`; theme_2 / theme_3 are there too).
  `voice_profiles.json`: `music_source` mine | generated | none, `music_generated` picks the theme.
- -22 dB under the voice, a further -3.5 dB under speech, -3.5 dB at 1-4 kHz under speech, +2 dB lift on the last
  line, 1 s fade in, 2 s fade out, loops with a 2 s crossfade. Every render also writes a no-music copy.
- Never put copyrighted tracks in a posted video. The Love Story files in `music/` are the owner's and are not used by default.

## Effects and visuals

- Max 8 sound effects at -20 dB relative to the voice, moved into pauses (never on a spoken word), no pencil sounds.
- Drawings come only from the blocks (`kindled_iron/blocks/`); stock clips from Pexels / Pixabay / NASA / Commons;
  third-party clips (private `reactions/`, `movie_reference/`) only when a scene asks for them.
- Faith rules: no occult imagery; God is never drawn as a figure (the word GOD in the accent color, or light).
- Scripture: World English Bible only; every card is checked word for word before any credit is spent.

## Add a script

1. Copy `kindled_iron/blocks/example_script.json` to `kindled_iron/queue/NNN-<id>.json` (NNN = order, e.g. `004-`).
2. Write each line's `say` (what the voice reads, with optional `[tags]`), pick a `block`, fill its `slots`
   (each block file lists them in `slots`; `_help` says what it draws).
3. Check it on your PC or in Codespaces: `python -m kindled_iron.build_scene kindled_iron/queue/NNN-<id>.json --out /tmp/x.json`
   (an error names the line and the problem).
4. Commit it. Want to see it before it posts? Run Kindled Iron Daily with `dry_run` ticked.

Batch rules and the block list: `kindled_iron/BATCH.md`.
