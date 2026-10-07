"""Original theme candidates from ElevenLabs Music (a safety net next to the owner's own track).

    python -m kindled_iron.music_gen --out DIR [--only theme_1]

Writes DIR/theme_1.mp3 .. theme_3.mp3 (about 90 s, loopable) and DIR/themes.json (prompt, credits used).
A theme that already exists in DIR is never generated again (the workflow keeps them in the private repo's
"music-themes" release). Needs ELEVENLABS_API_KEY with Music access; respects the monthly budget floor.
The prompts ask for an ORIGINAL piece and never name or describe an existing song or artist.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from kindled_iron import elevenlabs_tts as el
from kindled_iron import tts

BASE = ("An original, calm, ethereal and hopeful piece, slow (about 66-72 BPM), for quiet background under a spoken "
        "voice. Soft felt piano, warm sustained strings, airy pads, gentle reverb. No lyrics and no words. No drums "
        "(at most a very light, soft pulse). Peaceful and reverent, never dramatic or loud. Seamlessly loopable: the "
        "ending flows back into the opening. ")
THEMES = {
    "theme_1": BASE + "One solo, wordless, breathy 'ahh' voice floats softly above the piano from early on.",
    "theme_2": BASE + "A soft, distant wordless choir sings a breathy 'ahh' pad behind the piano and strings.",
    "theme_3": BASE + "Instrumental in the first half; wordless breathy 'ahh' voices arrive gently only in the "
                      "second half and fade back toward the loop point.",
}
LENGTH_MS = 90_000


def _used() -> int | None:
    try:
        return int(el._get("/user/subscription").get("character_count", 0))
    except Exception:  # noqa: BLE001
        return None


def compose(prompt: str, out: Path) -> None:
    last = None
    for model in ("music_v1",):
        body = json.dumps({"prompt": prompt, "music_length_ms": LENGTH_MS, "model_id": model}).encode()
        req = urllib.request.Request(f"{el.API}/music?output_format=mp3_44100_128", data=body, method="POST",
                                     headers={"xi-api-key": el._key() or "", "Content-Type": "application/json",
                                              "Accept": "audio/mpeg"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                out.write_bytes(r.read())
            return
        except urllib.error.HTTPError as e:
            try:
                d = json.loads(e.read().decode()).get("detail", {})
                d = (d.get("status", "") + " " + str(d.get("message", ""))[:200]) if isinstance(d, dict) else str(d)[:200]
            except Exception:  # noqa: BLE001
                d = ""
            last = f"HTTP {e.code} {d}".strip()
    raise RuntimeError(f"ElevenLabs Music: {last}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    info_f = out / "themes.json"
    info = json.loads(info_f.read_text()) if info_f.exists() else {}
    if not el._key():
        raise SystemExit("no ELEVENLABS_API_KEY: themes not generated")
    prof = tts.load_profile("kindled_iron")
    q = el.quota(prof["elevenlabs"]) or {}
    if "remaining" in q:
        print(f"[music_gen] ElevenLabs quota before: {q['remaining']}/{q['budget']} left")
    total = 0
    for name, prompt in THEMES.items():
        if a.only and name not in a.only.split(","):
            continue
        f = out / f"{name}.mp3"
        if f.exists() and f.stat().st_size > 50_000:
            print(f"[music_gen] {name}: already made (0 credits)")
            continue
        q = el.quota(prof["elevenlabs"]) or {}
        if q.get("remaining_fraction", 1.0) < float(prof["elevenlabs"].get("min_remaining_fraction", 0.1)):
            print(f"[music_gen] {name}: skipped, monthly budget under the floor")
            continue
        before = _used()
        try:
            compose(prompt, f)
        except Exception as e:  # noqa: BLE001
            print(f"[music_gen] {name}: FAILED ({e})")
            info[name] = {"prompt": prompt, "error": str(e)}
            continue
        after = None
        for _ in range(6):
            after = _used()
            if after is None or after != before:
                break
            time.sleep(3)
        credits = (after - before) if before is not None and after is not None else None
        total += credits or 0
        info[name] = {"prompt": prompt, "length_ms": LENGTH_MS, "credits": credits, "file": f.name}
        print(f"[music_gen] {name}: {f.stat().st_size // 1024} KB, credits {credits}")
    info_f.write_text(json.dumps(info, indent=1))
    print(f"[music_gen] credits this run: {total}")


if __name__ == "__main__":
    main()
