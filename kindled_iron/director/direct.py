"""Kindled Iron script/MP3 director. Never generates speech or publishes.

Produces a *draft* scene compatible with the existing renderer.
Requires a supplied MP3. Gemini is only used to write scene events.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path

from kindled_iron.whisper_transcribe import transcribe

ROOT = Path(__file__).resolve().parents[1]
ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_ACTIONS = {
    "draw", "walk", "point", "place", "express", "look", "look_viewer",
    "present", "shrug", "react", "pulse", "wiggle", "fade", "camera",
    "freeze", "face", "size", "move", "light_burst", "shake",
    "reach", "touch", "enter", "exit", "wave", "cheer", "drift",
}
ALLOWED_OBJECTS = {"word", "book", "arrow", "frame", "line", "circle",
                   "check", "cross", "coinhand", "heartdollar", "lockdollar"}
SAFE_FIELDS = {"id", "title", "voice_profile", "voice_file", "voice_as_is",
               "exact_narration", "max_silence", "end_hold", "ground", "camera_y",
               "fill_min", "max_visual_gap", "cast", "captions_box",
               "captions_chunk", "preview", "post", "beats", "mediabox", "clips"}


def norm(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold().replace("’", "'"))


def split_beats(text: str) -> list[str]:
    paragraphs = [re.sub(r"\s+", " ", x).strip() for x in re.split(r"\n\s*\n", text) if x.strip()]
    if len(paragraphs) > 1:
        return paragraphs
    sentences = re.split(r"(?<=[.!?])\s+", paragraphs[0])
    beats, chunk = [], []
    for sentence in sentences:
        chunk.append(sentence)
        if len(" ".join(chunk).split()) >= 25:
            beats.append(" ".join(chunk))
            chunk = []
    if chunk:
        beats.append(" ".join(chunk))
    return beats


def _available_flash_models(key: str) -> list[str]:
    """Query models enabled for THIS API key, never guess a model that returns 404."""
    import urllib.error
    url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=100"
    req = urllib.request.Request(url, headers={"x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.load(response)
    except urllib.error.HTTPError as e:
        detail = e.read(900).decode("utf-8", "replace")
        raise RuntimeError(f"Gemini listModels HTTP {e.code}: {detail}") from None
    return [m["name"].split("/", 1)[1] for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
            and "flash" in m.get("name", "").lower()
            and not any(x in m.get("name", "").lower() for x in ("image", "preview", "tts", "live", "exp"))]


def request_gemini(prompt: str, model: str) -> dict:
    import urllib.error
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY missing, cannot direct scene")
    if not re.fullmatch(r"[a-zA-Z0-9._-]+", model):
        raise ValueError("invalid Gemini model ID")
    available = _available_flash_models(key)
    if not available:
        raise RuntimeError("No Gemini Flash text models available to this API key")
    preferred = [model, "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]
    selected = next((name for name in preferred if name in available), None)
    if selected is None:
        raise RuntimeError("Requested model unavailable. Flash models on key: "
                           + ", ".join(available[:15]) + ". Update KI_DIRECTOR_MODEL explicitly.")
    print(f"Gemini director model: {selected} (requested: {model})", flush=True)
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.25}
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + selected + ":generateContent",
        data=body, method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            data = json.load(response)
    except urllib.error.HTTPError as e:
        detail = e.read(1400).decode("utf-8", "replace")
        raise RuntimeError(f"Gemini generateContent HTTP {e.code} ({selected}): {detail}") from None
    try:
        return json.loads(data["candidates"][0]["content"]["parts"][0]["text"])
    except (KeyError, IndexError, ValueError) as exc:
        raise RuntimeError(f"Gemini returned invalid JSON response ({type(exc).__name__})") from None


def validate(scene: dict, beats: list[str]) -> list[str]:
    errors = []
    if not isinstance(scene, dict) or not isinstance(scene.get("beats"), list):
        return ["invalid scene object"]
    if len(scene["beats"]) != len(beats):
        errors.append("beat count mismatch")
        return errors
    for i, (beat, narration) in enumerate(zip(scene["beats"], beats)):
        if norm(beat.get("narration", "")) != norm(narration):
            errors.append(f"beat {i}: altered narration")
        if not isinstance(beat.get("events"), list) or not beat["events"]:
            errors.append(f"beat {i}: missing visual events")
            continue
        spoken = norm(narration)
        ids = set()
        for ev in beat["events"]:
            action = ev.get("do")
            if action not in ALLOWED_ACTIONS:
                errors.append(f"beat {i}: unknown or forbidden action {action!r}")
            if action == "draw":
                if ev.get("type") not in ALLOWED_OBJECTS:
                    errors.append(f"beat {i}: unsupported object {ev.get('type')!r}")
                if not ev.get("id"):
                    errors.append(f"beat {i}: missing drawing id")
                if ev.get("id") in ids:
                    errors.append(f"beat {i}: duplicate drawing id")
                ids.add(ev.get("id"))
            anchor = ev.get("at")
            if not isinstance(anchor, (int, float, str)):
                errors.append(f"beat {i}: invalid event anchor")
            elif isinstance(anchor, str) and not re.fullmatch(r"(end|pause)([+-][0-9.]+)?", anchor):
                word = re.split(r"[#+-]", anchor)[0]
                if norm(word) and norm(word)[0] not in spoken:
                    errors.append(f"beat {i}: anchor not spoken {anchor!r}")
            if "file" in ev or "url" in ev or "scripture" in ev or "box" in ev:
                errors.append(f"beat {i}: unsupported external media/event (requires verified catalog)")
    return errors


def guide_prompt(beats: list[str], recognized: list[dict], examples: list, feedback: str) -> str:
    # Full examples are grounded in the original scenes but truncated to essential
    # beat structure to limit model context and cost.
    few = [{"narration": b.get("narration"), "events": b.get("events", [])[:11]}
           for s in examples for b in s.get("beats", [])[:3]]
    return json.dumps({
        "task": "Direct a Kindled Iron animated hand-drawn educational short. Return only JSON scene with beats.",
        "rules": [
            "Do not change a single narration word; keep the exact beat order and count.",
            "Original guide only. One scene beat for every supplied paragraph.",
            "Drawings first, supported shapes only. No people depicting God, no occult symbolism.",
            "Give each beat meaningful doodles, walk/point/express events and occasional camera zooms.",
            "Choose positions conservatively. Avoid overlapping captions or host.",
            "Use only allowed actions and objects, no external clips or memes until independently verified.",
            "Each event has an at anchor: seconds inside its narration beat or exact spoken word.",
            "Each drawing needs a unique id, position x/y, size/duration appropriate to its type.",
            "Use hard cuts by default; meaningful camera zooms only.",
            "Never invent Bible quotes. Revelation 21:4 is a paraphrase, use label only.",
            "Return format: {beats:[{id,panel:0,narration,events,camera_start:false,interaction:false}]}."
        ],
        "allowed_actions": sorted(ALLOWED_ACTIONS),
        "allowed_objects": sorted(ALLOWED_OBJECTS),
        "beats": beats,
        "audio_words_sample": recognized[:100],
        "few_shot": few,
        "fix_errors": feedback,
    }, ensure_ascii=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", type=Path, required=True)
    ap.add_argument("--audio", type=Path, required=True)
    ap.add_argument("--id", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--private-audio-path", required=True)
    ap.add_argument("--model", default=os.getenv("KI_DIRECTOR_MODEL", "gemini-2.5-flash"))
    args = ap.parse_args()
    if not ID.fullmatch(args.id):
        ap.error("id must use lowercase words separated by hyphens")
    if not args.audio.is_file() or not args.script.is_file():
        ap.error("script and owner MP3 are required; TTS fallback forbidden")
    if args.audio.suffix.lower() != ".mp3":
        ap.error("audio must be an owner-supplied MP3")
    text = args.script.read_text(encoding="utf-8").strip()
    beats = split_beats(text)
    if not beats:
        ap.error("empty script")
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        wav = Path(temp) / "spoken.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(args.audio),
                        "-ac", "1", "-ar", "44100", str(wav)], check=True)
        words = transcribe(wav, "small.en")
    # Fail closed if the supplied transcript is clearly not the recording.
    from difflib import SequenceMatcher
    agreement = SequenceMatcher(a=norm(text), b=norm(" ".join(w["word"] for w in words)),
                                autojunk=False).ratio()
    if agreement < 0.70:
        raise SystemExit(f"FAIL: script/audio agreement {agreement:.0%} below 70%")
    examples = [json.loads((ROOT / "scenes" / name).read_text(encoding="utf-8"))
                for name in ("where-did-god-come-from.json", "love-of-money-v3.json")]
    errors = []
    for attempt in range(3):
        proposed = request_gemini(guide_prompt(beats, words, examples, "; ".join(errors)), args.model)
        errors = validate(proposed, beats)
        if not errors:
            break
    if errors:
        raise SystemExit("FAIL: AI director scene validation: " + "; ".join(errors[:20]))
    scene = {
        "id": args.id, "title": args.id.replace("-", " ").title(),
        "voice_profile": "kindled_iron",
        "voice_file": {
            "path": args.private_audio_path,
            "sha256": hashlib.sha256(args.audio.read_bytes()).hexdigest(),
            "provider": "elevenlabs", "voice": "owner",
        },
        "voice_as_is": True, "exact_narration": True, "end_hold": 0.7,
        "cast": {"guide": {"panel": 0, "x": 680, "scale": 2.1,
                           "facing": -1, "accent": True}},
        "captions_box": {"x": 540, "y": 735, "w": 780, "size": 92,
                         "min_scale": 0.65},
        "captions_chunk": {"max_words": 3, "min_words": 1, "max_chars": 18},
        "preview": {"folder": args.id, "public_artifacts": False, "stage": "full"},
        "post": {"title": args.id.replace("-", " ").title()},
        "beats": proposed["beats"],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(scene, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Director: {len(beats)} beats, recording matches {agreement:.1%}, "
          "3-attempt maximum, owner MP3 required, no TTS, private preview scene")


if __name__ == "__main__":
    main()
