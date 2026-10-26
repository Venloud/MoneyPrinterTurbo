"""Gemini (free tier) client for the director: JSON text calls and image (vision) calls, with a call log.

The model is discovered from the key's own model list (never a guessed name that returns 404). Temporary
server errors are retried with backoff; auth, quota and invalid-model errors are not. Every call is recorded in
CALLS (kind, model, seconds, prompt/response sizes) so each preview can report the Gemini calls it used.
Offline tests set KI_GEMINI_MOCK to a directory of canned responses (plan_<n>.json, review_<n>.json).
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
CALLS: list[dict] = []
_MODEL: dict[str, str] = {}
TIMEOUTS = (420, 600, 600, 600)     # seconds per try: a full shot plan can take minutes on the free tier


def _key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY missing (GitHub secret)")
    return key


def pick_model(requested: str) -> str:
    if "m" in _MODEL:
        return _MODEL["m"]
    req = urllib.request.Request(f"{API}/models?pageSize=200", headers={"x-goog-api-key": _key()})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Gemini listModels HTTP {e.code}: {e.read(600).decode('utf-8', 'replace')}") from None
    names = [m["name"].split("/", 1)[1] for m in data.get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    flash = [n for n in names if "flash" in n and not any(x in n for x in ("image", "tts", "live", "exp", "audio"))]
    for cand in [requested] + flash:
        if cand in names:
            _MODEL["m"] = cand
            return cand
    raise RuntimeError("no Gemini Flash model on this key; models: " + ", ".join(names[:20]))


def _mock(kind: str):
    d = os.getenv("KI_GEMINI_MOCK")
    if not d:
        return None
    n = sum(1 for c in CALLS if c["kind"] == kind)
    f = Path(d) / f"{kind}_{n}.json"
    if not f.exists():
        f = Path(d) / f"{kind}.json"
    CALLS.append({"kind": kind, "model": "mock", "seconds": 0.0, "file": f.name})
    return json.loads(f.read_text(encoding="utf-8"))


def call_json(kind: str, prompt: str, images: list[Path] | None = None, model: str | None = None,
              temperature: float = 0.3) -> dict:
    """One generateContent call that must return a JSON object. kind = 'plan' | 'review' (for the call log)."""
    mocked = _mock(kind)
    if mocked is not None:
        return mocked
    name = pick_model(model or os.getenv("KI_DIRECTOR_MODEL", "gemini-3.8-flash"))
    parts: list[dict] = [{"text": prompt}]
    for img in images or []:
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(Path(img).read_bytes()).decode()}})
    body = json.dumps({"contents": [{"parts": parts}],
                       "generationConfig": {"responseMimeType": "application/json", "temperature": temperature}}).encode()
    req = urllib.request.Request(f"{API}/models/{name}:generateContent", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": _key()})
    t0, data = time.time(), None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUTS[attempt]) as r:
                data = json.load(r)
            break
        except urllib.error.HTTPError as e:
            detail = e.read(1200).decode("utf-8", "replace")
            if e.code in (429, 500, 502, 503, 504) and attempt < 3 and not re.search(r"PerDay|per day|billing", detail):
                time.sleep((5, 20, 60)[attempt])
                continue
            CALLS.append({"kind": kind, "model": name, "seconds": round(time.time() - t0, 1), "error": f"HTTP {e.code}"})
            raise RuntimeError(f"Gemini {name} HTTP {e.code}: {detail[:600]}") from None
        except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as e:
            # a slow answer (a long plan under load) or a dropped connection: the same request again, longer wait
            print(f"[gemini] {kind} call {attempt + 1}: {type(e).__name__}: {e}; retrying", flush=True)
            if attempt < 3:
                time.sleep(10)
                continue
            CALLS.append({"kind": kind, "model": name, "seconds": round(time.time() - t0, 1), "error": type(e).__name__})
            raise RuntimeError(f"Gemini {name}: no answer after 4 tries ({type(e).__name__})") from None
    usage = (data or {}).get("usageMetadata", {})
    CALLS.append({"kind": kind, "model": name, "seconds": round(time.time() - t0, 1), "images": len(images or []),
                  "prompt_tokens": usage.get("promptTokenCount"), "output_tokens": usage.get("candidatesTokenCount")})
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"Gemini {name}: no text in the response ({json.dumps(data)[:300]})") from None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except ValueError:
        raise RuntimeError(f"Gemini {name}: response is not JSON: {text[:300]}") from None
