"""Gemini (free tier) client for the director: JSON text calls and image (vision) calls, with a call log.

The model is discovered from the key's own model list (never a guessed name that returns 404). Temporary
server errors are retried with backoff; auth, quota and invalid-model errors are not. Every call is recorded in
CALLS (kind, model, seconds, prompt/response sizes) so each preview can report the Gemini calls it used.
One provider of llm.py (Gemini -> GitHub Models -> Cloudflare).
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://generativelanguage.googleapis.com/v1beta"
from kindled_iron.director.calls import CALLS     # shared call log of every provider
_MODEL: dict[str, str] = {}
TIMEOUTS = (420, 600)       # seconds per try: a full shot plan can take minutes on the free tier
WAITS = (10, 30, 60, 120)    # busy (503/429/5xx), slow or dropped: the same model again after these pauses


def _key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY missing (GitHub secret)")
    return key


def models(requested: str) -> list[str]:
    """The key's own Flash models: the requested one first, then the others newest first, lite models last
    (a busy or out-of-quota model falls through to the next one)."""
    if "chain" in _MODEL:
        return _MODEL["chain"]
    req = urllib.request.Request(f"{API}/models?pageSize=200", headers={"x-goog-api-key": _key()})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Gemini listModels HTTP {e.code}: {e.read(600).decode('utf-8', 'replace')}") from None
    names = [m["name"].split("/", 1)[1] for m in data.get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    flash = [n for n in names if "flash" in n and not any(x in n for x in ("image", "tts", "live", "exp", "audio", "preview"))]
    ver = lambda n: [int(x) for x in re.findall(r"\d+", n)[:2]] or [0]
    flash.sort(key=lambda n: ("lite" in n, [-v for v in ver(n)]))
    chain = ([requested] if requested in names else []) + [n for n in flash if n != requested]
    if not chain:
        raise RuntimeError("no Gemini Flash model on this key; models: " + ", ".join(names[:20]))
    _MODEL["chain"] = chain
    return _MODEL["chain"]


def pick_model(requested: str) -> str:
    return models(requested)[0]


def _try_model(kind: str, name: str, body: bytes, images) -> tuple:
    """-> (response dict, t0) or (reason string, t0). Busy / slow / dropped = the same model again after
    10, 30, 60, 120 s; a per-day quota = next model at once; any other HTTP error stops the whole call."""
    req = urllib.request.Request(f"{API}/models/{name}:generateContent", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": _key()})
    t0, why = time.time(), ""
    for attempt in range(len(WAITS) + 1):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUTS[min(attempt, len(TIMEOUTS) - 1)]) as r:
                return json.load(r), t0
        except urllib.error.HTTPError as e:
            detail = e.read(1200).decode("utf-8", "replace")
            why = f"HTTP {e.code}"
            if e.code == 429 and re.search(r"PerDay|per day", detail):
                why += " per-day quota"
                break
            if e.code not in (429, 500, 502, 503, 504):
                CALLS.append({"kind": kind, "provider": "gemini", "model": name, "seconds": round(time.time() - t0, 1), "error": why})
                raise RuntimeError(f"Gemini {name} HTTP {e.code}: {detail[:600]}") from None
        except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as e:
            why = type(e).__name__
        if attempt < len(WAITS):
            print(f"[gemini] {kind} {name} try {attempt + 1}: {why}; again in {WAITS[attempt]} s", flush=True)
            time.sleep(WAITS[attempt])
    CALLS.append({"kind": kind, "provider": "gemini", "model": name, "seconds": round(time.time() - t0, 1), "error": why})
    return why, t0


def generate(kind: str, prompt: str, images: list[Path] | None = None, model: str | None = None,
             temperature: float = 0.3) -> dict:
    """One generateContent call that must return a JSON object, falling through the key's Flash models.
    Raises llm.Unavailable when no model answers (quota=True when every failure was quota / busy / timeout)."""
    from kindled_iron.director.llm import Unavailable
    if not os.getenv("GEMINI_API_KEY"):
        raise Unavailable("GEMINI_API_KEY missing", quota=False)
    chain = models(model or os.getenv("KI_DIRECTOR_MODEL", "gemini-3.8-flash"))
    parts: list[dict] = [{"text": prompt}]
    for img in images or []:
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(Path(img).read_bytes()).decode()}})
    body = json.dumps({"contents": [{"parts": parts}],
                       "generationConfig": {"responseMimeType": "application/json", "temperature": temperature}}).encode()
    data, last = None, ""
    for name in chain:
        try:
            data, t0 = _try_model(kind, name, body, images)
        except RuntimeError as e:                      # a non-retryable HTTP error of this model
            data, last = None, str(e)[:200]
            continue
        if isinstance(data, dict):
            break
        last, data = data, None
        print(f"[gemini] {kind}: {name} gave up ({last}); next model", flush=True)
    if data is None:
        raise Unavailable(f"every Gemini model failed; last: {last}",
                          quota=bool(re.search(r"429|503|50[024]|quota|Timeout|URLError|Remote|Connection", last)))
    usage = (data or {}).get("usageMetadata", {})
    CALLS.append({"kind": kind, "provider": "gemini", "model": name, "seconds": round(time.time() - t0, 1),
                  "images": len(images or []), "prompt_tokens": usage.get("promptTokenCount"),
                  "output_tokens": usage.get("candidatesTokenCount")})
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise Unavailable(f"Gemini {name}: no text in the response ({json.dumps(data)[:200]})", quota=False) from None
    return parse_json(text, f"Gemini {name}")


def parse_json(text: str, who: str) -> dict:
    """The JSON object in a model's answer (code fences and stray prose around it are ignored)."""
    from kindled_iron.director.llm import Unavailable
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    try:
        out = json.loads(t)
    except ValueError:
        m = re.search(r"\{.*\}", t, re.S)
        try:
            out = json.loads(m.group(0)) if m else None
        except ValueError:
            out = None
    if not isinstance(out, dict):
        raise Unavailable(f"{who}: the answer is not a JSON object: {t[:200]}", quota=False)
    return out
