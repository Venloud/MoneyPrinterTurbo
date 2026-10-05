"""ONE-TIME: generate Chatterbox reference clips from the owner's ElevenLabs voice.

    python -m kindled_iron.voice_bootstrap --out /tmp/voice_refs

Makes 5 reference clips (25-30 s, different deliveries) + 1 reserve clip (~3 min) as WAV.
The workflow uploads them to the owner's PRIVATE repo and deletes them; nothing here is ever
committed, released or uploaded as an artifact of this (public) repo. Voice settings are sent
per request only; the voice itself is never edited.
"""
from __future__ import annotations

import argparse
import copy
import subprocess
from pathlib import Path

from kindled_iron import elevenlabs_tts, tts

# Original texts written for these clips (no Scripture quotations), ~75 words each (~28 s).
CLIPS = [
    ("kindled_iron_ref_1.wav", "warm storyteller", {"stability": 0.5, "style": 0.25, "speed": 0.95},
     "Long ago, in a quiet village by the hills, there lived an old shepherd who knew every sheep by name. "
     "Each morning he walked the same dusty path, humming the same simple song. One day a little lamb wandered "
     "off toward the river, and the shepherd left everything behind to find it. He searched until the sun went down, "
     "and when he finally heard a tiny cry in the reeds, he laughed out loud."),
    ("kindled_iron_ref_2.wav", "calm teacher", {"stability": 0.65, "style": 0.1, "speed": 0.95},
     "Here is something interesting. A seed looks small and plain, but inside it is everything a tree needs to start. "
     "Put it in the soil, give it water and light, and slowly it pushes a tiny root down and a green shoot up. "
     "Nobody can see it happening at first. But give it time, and one day there is shade where there was only dirt. "
     "Small beginnings can grow into very big things."),
    ("kindled_iron_ref_3.wav", "bright and excited", {"stability": 0.35, "style": 0.55, "speed": 1.05},
     "Okay, are you ready for this? Picture the biggest ocean wave you have ever seen. Now picture it ten times taller! "
     "That is how sailors felt when the storm hit. The boat tipped, the rain came sideways, and everyone grabbed a rope. "
     "And then, just like that, the wind stopped. The water went flat like glass. Can you imagine that moment? "
     "Total silence, and every single person staring at the sky."),
    ("kindled_iron_ref_4.wav", "slow and reflective", {"stability": 0.75, "style": 0.05, "speed": 0.88},
     "Sometimes the best moments are the quiet ones. The kettle on the stove, the window open, the birds outside just "
     "starting to wake up. You sit for a while and you do not need to say anything at all. You just notice how much "
     "you have been given. The light on the table. The people you love. Another morning. It is easy to rush past "
     "that. Today, try to slow down and see it."),
    ("kindled_iron_ref_5.wav", "friendly and conversational", {"stability": 0.45, "style": 0.3, "speed": 1.0},
     "So here is a question my friend asked me the other day. If you could visit any place in history, just for one "
     "afternoon, where would you go? I thought about it for a long time. Maybe a busy market thousands of years ago, "
     "with all the noise and the smells and the people bargaining over bread. Honestly, I think I would just walk "
     "around and listen. What about you? Where would you go?"),
]
RESERVE = ("kindled_iron_reserve.wav", "reserve (mixed, ~3 min)", {"stability": 0.55, "style": 0.2, "speed": 0.95},
           " ".join(c[3] for c in CLIPS) + " " + " ".join(c[3] for c in CLIPS[:2]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--profile", default="kindled_iron")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    profile = tts.load_profile(a.profile)
    need = sum(len(c[3]) for c in CLIPS) + len(RESERVE[3])
    ok, why, q = elevenlabs_tts.available(profile, need)
    print(f"[bootstrap] ElevenLabs: {why}; this run needs about {need} characters")
    if not ok:
        raise SystemExit(f"[bootstrap] stopped: {why}")
    for name, label, settings, text in CLIPS + [RESERVE]:
        p = copy.deepcopy(profile)
        p["elevenlabs"]["voice_settings"].update(settings)
        wav = out / name
        elevenlabs_tts.synthesize([text], wav, p)
        dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                             "-of", "csv=p=0", str(wav)]).decode().strip())
        print(f"[bootstrap] {name}: {label}, {dur:.1f} s, {len(text)} characters")
    print(f"[bootstrap] done: {len(CLIPS) + 1} clips in {out} (upload them privately, then delete)")


if __name__ == "__main__":
    main()
