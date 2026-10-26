# Kindled Iron only: script + owner-provided MP3 preview

Status: scoped implementation specification, not a completed automatic visual planner.
Owner instruction, October 25, 2026: **Every Kindled Iron video receives a finished script AND the owner's already-produced MP3. No narration generation, voice substitution, or ElevenLabs TTS calls are permitted.** This applies only to Kindled Iron, not Bouriko, Night Files, or other channels.

## Current production target

- Video: **The Epicurean Paradox**.
- Owner-supplied narration: private repository `Venloud/kindled-iron-voice`, path `approved_audio/epicurean-paradox/narration.mp3`, committed `b1b6301`.
- Script: the approved final spoken transcript from the owner's conversation, text must match the recording. Do not rewrite the narration to fit an arbitrary time limit.
- Output: **private MP4 preview only**. Do not approve or publish to any platform.
- Visuals: automatic semantic selection when available, with priority to existing approved/reference assets, real relevant footage, and original Kindled Iron hand-drawn diagrams, host, and cream whiteboard aesthetic.
- Fail closed when a clip is semantically wrong or rights cannot be established; the Love of Money hammer/paintbrush mismatch is a known failure case.
- Quality: align actual MP3 with Whisper, inspect meaning at every visual cue, verify footage identities and sources, captions' safe zones, strict frame audit and final playback.

## Reuse existing implementation

The owning branch `claude/love-money-v3-alt` already implements owner-supplied audio through `kindled_iron/render.py::approved_voice_file()` via scene `voice_file.path`, `KI_PRIVATE_MEDIA` or `KI_VOICE_FILE`. When present, it skips all voice synthesis and records zero credits; a missing MP3 must fail rather than synthesize. The `kindled_iron_test.yml` private checkout already includes `approved_audio`. Existing scene authoring, `mediabox.py`, the runtime, music and private preview delivery must be reused, not replaced.

**Critical safeguard:** The current generic test workflow still exposes TTS controls and can fall back to synthesized narration for scenes without `voice_file`. A dedicated Kindled Iron script+MP3 entry point must enforce required MP3 before it invokes the renderer, and must not call TTS-related setup (including optional music generation). Do not label this requirement satisfied merely because the renderer has an optional `voice_file` field.

## Planned beginner experience

User supplies only the finished script and MP3. A dedicated preview action validates both, calculates the file SHA-256, aligns the spoken words, plans semantically related clips and animated graphics from approved assets, chooses actual media with traceable rights and verification, renders through the current Kindled Iron renderer, audits the output, and returns only a private MP4. Existing approved media should take priority; unrelated placeholders must never be used.

No automatic publishing or broad configuration change is authorized. Preserve work on other branches. Implement and test this path in incremental, verified steps before announcing that the single-action preview is working.
