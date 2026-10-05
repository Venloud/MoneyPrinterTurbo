"""ElevenLabs TTS (the owner's cloned voice). Same interface as kokoro_tts / chatterbox_tts.

The key comes ONLY from the ELEVENLABS_API_KEY environment variable (a GitHub secret). It is never
printed, written to disk or put in an error message. A missing key is a normal state: available()
returns (False, reason) and the caller falls back. Voice settings are sent per request; the voice
in the account is never edited or deleted (this module only calls the TTS and subscription GETs).
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.elevenlabs.io/v1"
# Models that honour <break time="0.7s" /> (max 3 s). Others get sentence cuts + silence afterwards.
BREAK_MODELS = {"eleven_multilingual_v2", "eleven_turbo_v2", "eleven_turbo_v2_5", "eleven_flash_v2",
                "eleven_flash_v2_5", "eleven_monolingual_v1", "eleven_english_sts_v2"}


def _key() -> str | None:
    k = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    return k or None


def _get(path: str) -> dict:
    req = urllib.request.Request(API + path, headers={"xi-api-key": _key() or "", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def quota(cfg: dict) -> dict | None:
    """Remaining characters this month, capped by our own monthly_char_budget.
    None if the subscription can't be read (key without the User: read permission)."""
    try:
        sub = _get("/user/subscription")
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"error": type(e).__name__}
    used = int(sub.get("character_count", 0))
    limit = int(sub.get("character_limit", 0))
    budget = min(limit, int(cfg.get("monthly_char_budget", limit))) if limit else int(cfg.get("monthly_char_budget", 0))
    remaining = max(0, budget - used)
    return {"used": used, "plan_limit": limit, "budget": budget, "remaining": remaining,
            "remaining_fraction": (remaining / budget) if budget else 0.0,
            "resets_unix": sub.get("next_character_count_reset_unix")}


def available(profile: dict, chars: int = 0) -> tuple[bool, str, dict]:
    cfg = profile.get("elevenlabs") or {}
    if not _key():
        return False, "no ELEVENLABS_API_KEY (normal: using the next voice)", {}
    if not cfg.get("voice_id"):
        return False, "no ElevenLabs voice_id in the profile", {}
    q = quota(cfg) or {}
    if "error" in q:
        # Can't verify the quota: carry on (ElevenLabs still enforces the plan limit) but say so.
        return True, f"quota unreadable ({q['error']}; give the key 'User: read' permission)", q
    floor = float(cfg.get("min_remaining_fraction", 0.10))
    if q["remaining_fraction"] < floor:
        return False, f"only {q['remaining_fraction']:.0%} of the monthly budget left (< {floor:.0%})", q
    if chars > q["remaining"]:
        return False, f"script needs {chars} characters, {q['remaining']} left", q
    return True, f"{q['remaining']}/{q['budget']} characters left this month", q


def script_text(segments: list[tuple[str, float]], model: str) -> str:
    if model not in BREAK_MODELS:
        return " ".join(t for t, _ in segments)
    out = []
    for t, p in segments:
        out.append(t)
        if p >= 0.05:
            out.append(f'<break time="{min(3.0, p):g}s" />')
    return " ".join(out)


def synthesize(segments: list[tuple[str, float]], out_wav: Path, profile: dict) -> dict:
    """ONE request for the whole script (consistent tone). Pauses: <break> tags when the model
    supports them; either way pacing.enforce() fixes every gap on the final audio afterwards."""
    cfg = profile["elevenlabs"]
    model = cfg.get("model_id", "eleven_multilingual_v2")
    # break tags add characters (credits); use_break_tags: false sends plain text and lets
    # pacing.enforce() cut at the sentence edges and insert the silence instead
    text = script_text(segments, model if cfg.get("use_break_tags", True) else "")
    settings = dict(cfg.get("voice_settings", {}))
    if "speed" in settings:
        settings["speed"] = max(0.92, float(settings["speed"]))
    body = {"text": text, "model_id": model, "voice_settings": settings}
    fmt = cfg.get("output_format", "mp3_44100_128")
    req = urllib.request.Request(f"{API}/text-to-speech/{cfg['voice_id']}?output_format={fmt}",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"xi-api-key": _key() or "", "Content-Type": "application/json",
                                          "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            audio = r.read()
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read().decode()).get("detail", {})
            detail = detail.get("status", "") if isinstance(detail, dict) else str(detail)[:80]
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"ElevenLabs HTTP {e.code} {detail}".strip()) from None
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio)
        mp3 = f.name
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-ac", "1", "-ar", "44100", str(out_wav)], check=True)
    finally:
        os.unlink(mp3)
    return {"model": model, "voice_id": cfg["voice_id"], "chars": len(text), "break_tags": model in BREAK_MODELS}
