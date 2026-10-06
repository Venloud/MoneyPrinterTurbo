"""Music candidates under the same voice, so the owner can pick one by ear.

    python -m kindled_iron.music_samples --work storage/kindled_iron/work --out storage/kindled_iron/music_samples

Takes the first --seconds (10) of the render's narration (work/narration.wav + timings.json) and mixes each
music track in vendor/sfx/lib/music_*.ogg under it exactly as the real render does (same level, same
ducking, voice at -14 LUFS, no effects). Writes music_<name>.mp3 per track. The pick goes in
voice_profiles.json -> <channel>.music_track.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from kindled_iron import sound


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=float, default=10.0)
    a = ap.parse_args()
    work, out = Path(a.work), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    t = json.loads((work / "timings.json").read_text())
    words = [w for bw in t["words"] for w in bw if w["start"] < a.seconds]
    clip = out / "_voice.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(work / "narration.wav"), "-t", f"{a.seconds:.2f}", str(clip)], check=True)
    tracks = sorted(p.stem.split("_", 1)[1] for p in sound.LIB.glob("music_*.ogg"))
    for name in tracks:
        mixed, novoice = out / f"_{name}.wav", out / f"_{name}_nv.wav"
        sound.mix(clip, [], {"beats": []}, [], words, a.seconds, mixed, novoice, {"track": name, "lift_at": None}, print)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mixed), "-t", f"{a.seconds:.2f}", "-b:a", "192k",
                        str(out / f"music_{name}.mp3")], check=True)
        mixed.unlink()
        novoice.unlink()
        print(f"music sample: {out / f'music_{name}.mp3'}")
    clip.unlink()


if __name__ == "__main__":
    main()
