"""Voice the narration with the chosen provider, falling back chosen -> chatterbox -> kokoro.

Every provider has the same interface: available(profile, chars) -> (ok, reason, info) and
synthesize(beats, out_wav, profile) -> meta. Audio is cached by
hash(provider + script + voice + model + settings), so a re-render of the same script costs
no ElevenLabs credits. Cache dir: KI_TTS_CACHE (default ~/.cache/kindled_iron/tts).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from kindled_iron import chatterbox_tts, elevenlabs_tts, kokoro_tts

HERE = Path(__file__).resolve().parent
PROVIDERS = {"elevenlabs": elevenlabs_tts, "chatterbox": chatterbox_tts, "kokoro": kokoro_tts}


def load_profile(name: str = "kindled_iron") -> dict:
    return json.loads((HERE / "voice_profiles.json").read_text(encoding="utf-8"))[name]


def _cache_dir() -> Path:
    d = Path(os.environ.get("KI_TTS_CACHE", Path.home() / ".cache" / "kindled_iron" / "tts"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_key(provider: str, beats: list[str], profile: dict) -> str:
    cfg = profile.get(provider) or {}
    blob = json.dumps({"provider": provider, "beats": beats, "cfg": cfg, "gap": profile.get("beat_gap"),
                       "eq": profile.get("eq")}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def _eq(wav: Path, eq: str | None) -> None:
    if not eq:
        return
    tmp = wav.with_suffix(".eq.wav")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-af", eq, str(tmp)], check=True)
    tmp.replace(wav)


def voice(beats: list[str], out_wav: Path, profile: dict, provider: str, log) -> dict:
    order = [provider] + [p for p in ("chatterbox", "kokoro") if p != provider]
    chars = sum(len(b) for b in beats)
    reasons: list[str] = []
    for p in order:
        key = cache_key(p, beats, profile)
        cached = _cache_dir() / f"{key}.wav"
        if cached.exists():
            shutil.copy(cached, out_wav)
            meta = {"provider_used": p, "cached": True, "cache_key": key, "chars_billed": 0}
            log(f"voice: {p} (cached audio, 0 credits)")
            break
        mod = PROVIDERS[p]
        ok, why, info = mod.available(profile, chars)
        if p == "elevenlabs" and info and "remaining" in info:
            log(f"ElevenLabs quota: {info['remaining']}/{info['budget']} characters left this month "
                f"({info['remaining_fraction']:.0%})")
        if not ok:
            reasons.append(f"{p}: {why}")
            log(f"voice: {p} skipped ({why})")
            continue
        if why and p == "elevenlabs" and "unreadable" in why:
            log(f"WARNING: ElevenLabs {why}")
        try:
            meta = mod.synthesize(beats, out_wav, profile)
        except Exception as e:  # noqa: BLE001 - never let one provider stop the render
            reasons.append(f"{p}: {str(e)[:120]}")
            log(f"WARNING: voice {p} failed ({str(e)[:120]})")
            continue
        _eq(out_wav, profile.get("eq"))
        shutil.copy(out_wav, cached)
        meta.update({"provider_used": p, "cached": False, "cache_key": key,
                     "chars_billed": meta.get("chars", 0) if p == "elevenlabs" else 0})
        log(f"voice: {p} ({meta.get('model')}, {meta.get('chars', 0)} characters)")
        break
    else:
        raise SystemExit("no voice provider worked: " + "; ".join(reasons))
    meta["provider_requested"] = provider
    meta["fallback"] = meta["provider_used"] != provider
    if meta["fallback"]:
        meta["voice_label"] = "fallback voice"
        meta["fallback_reasons"] = reasons
        if provider != "kokoro":
            log(f"WARNING: fallback voice: wanted {provider}, used {meta['provider_used']} ({'; '.join(reasons)})")
    return meta
