"""Voice the same scene narration with every option so the owner can pick a default.

    python -m kindled_iron.voice_compare kindled_iron/scenes/genesis-1.json --out /tmp/voice_compare

Writes elevenlabs.mp3, chatterbox_ref_1..5.mp3 (one per reference clip in KI_VOICE_REF_DIR) and
kokoro.mp3. ElevenLabs audio goes through the normal cache, so the test render reuses it for free.
Reference clips are kept until the end of this run, then deleted.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
from pathlib import Path

from kindled_iron import chatterbox_tts, tts


def _mp3(wav: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-b:a", "160k", str(wav.with_suffix(".mp3"))], check=True)
    wav.unlink()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("scene")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    scene = json.loads(Path(a.scene).read_text(encoding="utf-8"))
    beats = [b["narration"] for b in scene["beats"]]
    profile = tts.load_profile(scene.get("voice_profile", "kindled_iron"))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(f"[compare] {m}", flush=True)  # noqa: E731

    meta = tts.voice(beats, out / "elevenlabs.wav", profile, "elevenlabs", log)
    if meta["provider_used"] == "elevenlabs":
        _mp3(out / "elevenlabs.wav")
    else:
        (out / "elevenlabs.wav").unlink()
        log("ElevenLabs not available, no elevenlabs.mp3")

    ref_dir = Path(os.environ.get("KI_VOICE_REF_DIR", ""))
    refs = sorted(ref_dir.glob("kindled_iron_ref_*.wav")) if ref_dir.is_dir() else []
    for ref in refs:
        p = copy.deepcopy(profile)
        p["chatterbox"]["reference_clip"] = ref.name
        wav = out / f"chatterbox_{ref.stem.replace('kindled_iron_', '')}.wav"
        try:
            chatterbox_tts.synthesize(beats, wav, p, ref=ref, keep_ref=True)
            _mp3(wav)
            log(f"chatterbox with {ref.name}: ok")
        except Exception as e:  # noqa: BLE001
            log(f"chatterbox with {ref.name} failed: {str(e)[:120]}")
    for ref in refs:
        ref.unlink()
    tts.voice(beats, out / "kokoro.wav", profile, "kokoro", log)
    _mp3(out / "kokoro.wav")
    log("files: " + ", ".join(sorted(f.name for f in out.glob("*.mp3"))))


if __name__ == "__main__":
    main()
