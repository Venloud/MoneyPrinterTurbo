"""Credit guard for the daily run: is there enough ElevenLabs credit for this scene (default voice + model)?

    python -m kindled_iron.credit_guard kindled_iron/scenes/<id>.json

Prints one line and writes ok=true|false and why=... to $GITHUB_OUTPUT. Exit code is always 0 (the workflow
decides). Needed = characters the voice request sends (the tagged text for v3 / v4) x credit_margin; ok only if
that fits AND at least min_credits_left (daily_config.json) stay afterwards AND the profile's monthly floor holds.
An unreadable balance (key without User: read) = not ok: the daily run never spends credits blind.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from kindled_iron import elevenlabs_tts as el
from kindled_iron import tts

HERE = Path(__file__).resolve().parent


def main() -> None:
    scene = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    cfg = json.loads((HERE / "daily_config.json").read_text())
    prof = tts.load_profile(scene.get("voice_profile", "kindled_iron"))
    model = el.resolve_model(prof["elevenlabs"].get("model_id", "eleven_multilingual_v2"))
    text = scene.get("tts_text_tagged") if el.is_tagged_model(model) and scene.get("tts_text_tagged") else scene.get("tts_text", "")
    need = int(len(text) * float(cfg.get("credit_margin", 1.3)))
    reserve = int(cfg.get("min_credits_left", 3000))
    ok, why, q = el.available(prof, need)
    if ok and "error" in q:
        ok, why = False, f"ElevenLabs balance unreadable ({q['error']}): not spending credits blind"
    elif ok and q.get("remaining", 0) - need < reserve:
        ok, why = False, f"{q['remaining']} credits left; this video needs ~{need} and {reserve} must stay in reserve"
    line = f"credit guard: {'OK' if ok else 'SKIP'} - model {model}, needs ~{need} credits; {why}"
    print(line)
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a") as f:
            f.write(f"ok={'true' if ok else 'false'}\nwhy={line}\n")


if __name__ == "__main__":
    main()
