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


# Model choice per voice profile: "model_id" may be an alias or a real id. v3 / v4 read [bracket] audio tags,
# "..." and "—" for pauses; they never get SSML <break>.
MODEL_ALIASES = {"v2": "eleven_multilingual_v2", "v3": "eleven_v3", "v4": "eleven_v4"}


def resolve_model(name: str) -> str:
    return MODEL_ALIASES.get(name, name)


def is_tagged_model(model: str) -> bool:
    return resolve_model(model).startswith(("eleven_v3", "eleven_v4"))


_MODELS: list | None = None


def list_models() -> list[dict]:
    """The models this key can use for text-to-speech, as the API lists them (cached per run)."""
    global _MODELS
    if _MODELS is None:
        try:
            req = urllib.request.Request(API + "/models", headers={"xi-api-key": _key() or "", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.load(r)
            _MODELS = [{"model_id": m.get("model_id"), "name": m.get("name"), "tts": m.get("can_do_text_to_speech")}
                       for m in data if isinstance(m, dict)]
        except Exception:  # noqa: BLE001 - the list is advisory; the TTS request itself decides
            _MODELS = []
    return _MODELS


def used_chars() -> int | None:
    try:
        return int(_get("/user/subscription").get("character_count", 0))
    except Exception:  # noqa: BLE001
        return None


def script_text(segments: list[tuple[str, float]], model: str) -> str:
    if model not in BREAK_MODELS or is_tagged_model(model):
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
    model = resolve_model(cfg.get("model_id", "eleven_multilingual_v2"))
    listed = [m["model_id"] for m in list_models() if m.get("tts")]
    if listed and model not in listed:
        raise RuntimeError(f"model {model} is not available for text-to-speech on this key (listed: {', '.join(listed)})")
    # break tags add characters (credits); use_break_tags: false sends plain text and lets
    # pacing.enforce() cut at the sentence edges and insert the silence instead
    text = script_text(segments, model if cfg.get("use_break_tags", True) else "")
    settings = dict(cfg.get("voice_settings", {}))
    if "speed" in settings:
        # ElevenLabs' own range is 0.7-1.2; the channel's floor (min_speed, 0.87 for Kindled Iron) wins
        settings["speed"] = min(1.2, max(0.7, float(profile.get("min_speed", 0.7)), float(settings["speed"])))
    if is_tagged_model(model):
        # v3 takes stability only as 0.0 (creative), 0.5 (natural) or 1.0 (robust); no SSML breaks ever
        settings["stability"] = min((0.0, 0.5, 1.0), key=lambda v: abs(v - float(settings.get("stability", 0.5))))
        text = text.replace("<break", "")
    body = {"text": text, "model_id": model, "voice_settings": settings}
    fmt = cfg.get("output_format", "mp3_44100_128")
    req = urllib.request.Request(f"{API}/text-to-speech/{cfg['voice_id']}?output_format={fmt}",
                                 data=json.dumps(body).encode(), method="POST",
                                 headers={"xi-api-key": _key() or "", "Content-Type": "application/json",
                                          "Accept": "audio/mpeg"})
    def call(b: dict) -> bytes:
        r_ = urllib.request.Request(req.full_url, data=json.dumps(b).encode(), method="POST", headers=dict(req.header_items()))
        with urllib.request.urlopen(r_, timeout=300) as r:
            return r.read()

    try:
        audio = call(body)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            d = json.loads(e.read().decode()).get("detail", {})
            detail = (d.get("status", "") + " " + str(d.get("message", ""))[:160]) if isinstance(d, dict) else str(d)[:160]
        except Exception:  # noqa: BLE001
            pass
        if e.code in (400, 422) and is_tagged_model(model):
            # a newer model may not take every setting: retry once with stability + similarity only
            body["voice_settings"] = {k: settings[k] for k in ("stability", "similarity_boost") if k in settings}
            try:
                audio = call(body)
            except urllib.error.HTTPError as e2:
                raise RuntimeError(f"ElevenLabs HTTP {e2.code} ({model}) {detail}".strip()) from None
        else:
            raise RuntimeError(f"ElevenLabs HTTP {e.code} ({model}) {detail}".strip()) from None
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(audio)
        mp3 = f.name
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3, "-ac", "1", "-ar", "44100", str(out_wav)], check=True)
    finally:
        os.unlink(mp3)
    return {"model": model, "voice_id": cfg["voice_id"], "chars": len(text), "break_tags": False if is_tagged_model(model)
            else model in BREAK_MODELS, "voice_settings_sent": body["voice_settings"]}
