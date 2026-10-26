"""One interface for the director's AI calls (the shot plan and the vision review), whatever provider answers.

The providers and their models live in providers.json (free tiers only), tried in its order:
  gemini -> github (GitHub Models, the workflow token) -> huggingface -> groq -> openrouter (':free' models only)
  -> cloudflare (the Kindled account: KINDLED_CF_*) -> claude (off unless allow_claude_fallback; max 1 plan call)
A provider whose secret is missing is skipped. One that answers 429 / quota / 5xx / a timeout is marked exhausted
for the rest of the run and the next one is asked. The vision review only asks providers with a vision model.
Every answer goes through the same plan checks afterwards, whoever sent it.

call_json() returns the first JSON answer. When every usable provider is exhausted it raises QuotaWait: the
video waits for the daily reset instead of failing. Every call (also the failed ones) is logged in calls.CALLS
with its provider and model. Offline tests set KI_LLM_MOCK (or KI_GEMINI_MOCK) to a directory of canned answers
(plan_<n>.json / plan.json, review_<n>.json / review.json).
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

from kindled_iron.director.calls import CALLS

CONFIG = Path(__file__).resolve().parent / "providers.json"
EXHAUSTED: dict[str, str] = {}          # provider -> why, for the rest of this run
SYSTEM = "You answer with one JSON object only."


class Unavailable(Exception):
    """This provider gave no answer. quota=True: out of quota / busy / timed out (worth waiting for)."""

    def __init__(self, msg: str, quota: bool = True):
        super().__init__(msg)
        self.quota = quota


class QuotaWait(Exception):
    """No provider can answer until a quota resets."""


def config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def _log(msg: str) -> None:
    print(f"[llm] {msg}", flush=True)


def _http(method: str, url: str, headers: dict, body: dict | None = None, timeout: float = 420):
    """-> (status, headers, parsed JSON or text); status 0 = no answer (timeout, dropped). Tests replace this."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, st, hd = r.read(), r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        raw, st, hd = e.read(), e.code, dict(e.headers or {})
    except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as e:
        return 0, {}, f"{type(e).__name__}: {e}"
    try:
        return st, hd, json.loads(raw)
    except ValueError:
        return st, hd, raw.decode("utf-8", "replace")


def _busy(status: int, body) -> bool:
    return status in (0, 408, 429, 500, 502, 503, 504, 529) or bool(re.search(r"quota|rate.?limit|exhaust|3036", str(body)[:500], re.I))


def _image_url(img: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(Path(img).read_bytes()).decode()


def _parse(text: str, who: str) -> dict:
    from kindled_iron.director.gemini import parse_json
    return parse_json(text, who)


# ------------------------------------------------------------------ provider kinds
class Provider:
    def __init__(self, cfg: dict):
        self.cfg, self.name = cfg, cfg["name"]

    def secret(self) -> str | None:
        return os.getenv(self.cfg["secret"])

    def ready(self) -> bool:
        return bool(self.secret()) and all(os.getenv(k) for k in [self.cfg.get("account_secret")] if k)

    def model(self, vision: bool) -> str | None:
        return self.cfg.get("vision") if vision else self.cfg.get("chat")

    def fits(self, prompt: str, images) -> bool:
        return len(prompt) / 3.6 + 85 * len(images or []) <= self.cfg.get("max_input_tokens", 8000)


class Gemini(Provider):
    def call(self, kind, prompt, images, model, temperature):
        from kindled_iron.director import gemini
        return gemini.generate(kind, prompt, images=images, model=model, temperature=temperature)


class OpenAICompatible(Provider):
    """GitHub Models, Hugging Face router, Groq, OpenRouter, Cloudflare Workers AI: the same chat-completions call."""

    def call(self, kind, prompt, images, model, temperature):
        c = self.cfg
        if c.get("free_only") and not model.endswith(":free"):
            raise Unavailable(f"{self.name}: model {model} is not a ':free' model", quota=False)
        url = c["url"].replace("{account}", os.getenv(c.get("account_secret") or "", "") or "")
        content: list = [{"type": "text", "text": prompt}]
        for img in images or []:
            iu = {"url": _image_url(img)}
            if c.get("image_detail"):
                iu["detail"] = c["image_detail"]
            content.append({"type": "image_url", "image_url": iu})
        body = {"model": model, "messages": [{"role": "system", "content": SYSTEM},
                                             {"role": "user", "content": content if images else prompt}],
                "temperature": temperature, "max_tokens": c.get("max_output_tokens", 4000),
                "response_format": {"type": "json_object"}}
        hdr = {"Authorization": f"Bearer {self.secret()}", **(c.get("headers") or {})}
        t0 = time.time()
        st, hd, out = _http("POST", url, hdr, body)
        if st == 400 and "response_format" in str(out):          # some models take no JSON mode: ask in words
            body.pop("response_format")
            st, hd, out = _http("POST", url, hdr, body)
        rec = {"kind": kind, "provider": self.name, "model": model, "seconds": round(time.time() - t0, 1),
               "images": len(images or [])}
        if st != 200:
            rec["error"] = f"HTTP {st}"
            CALLS.append(rec)
            raise Unavailable(f"{self.name} {model} HTTP {st}: {str(out)[:300]}", quota=_busy(st, out))
        usage = (out or {}).get("usage") or {}
        rec.update(prompt_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"))
        CALLS.append(rec)
        try:
            text = out["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise Unavailable(f"{self.name} {model}: no answer text ({str(out)[:200]})", quota=False) from None
        return _parse(text if isinstance(text, str) else json.dumps(text), f"{self.name} {model}")


class Claude(Provider):
    """Anthropic Messages API with the Claude Code OAuth token. Off unless the config allows it; plan calls only,
    at most claude_max_plan_calls per video."""

    def ready(self) -> bool:
        return super().ready() and bool(config().get("allow_claude_fallback"))

    def _hdr(self) -> dict:
        return {"Authorization": f"Bearer {self.secret()}", "anthropic-version": "2023-06-01",
                "anthropic-beta": "oauth-2025-04-20"}

    def model(self, vision: bool) -> str | None:
        want = self.cfg.get("vision") if vision else self.cfg.get("chat")
        if not want or not want.startswith("auto"):
            return want
        family = want.split("-", 1)[1] if "-" in want else ""
        st, _, out = _http("GET", self.cfg["models_url"], self._hdr(), timeout=30)
        ids = [m.get("id", "") for m in (out or {}).get("data", [])] if st == 200 and isinstance(out, dict) else []
        pick = next((i for i in ids if family in i), ids[0] if ids else None)
        if not pick:
            raise Unavailable(f"claude: model list HTTP {st}", quota=_busy(st, out))
        return pick

    def call(self, kind, prompt, images, model, temperature):
        used = sum(1 for c in CALLS if c.get("provider") == "claude" and c.get("kind") == "plan" and not c.get("error"))
        if kind != "plan" or used >= int(config().get("claude_max_plan_calls", 1)):
            raise Unavailable(f"claude: only {config().get('claude_max_plan_calls', 1)} plan call(s) per video", quota=True)
        body = {"model": model, "max_tokens": self.cfg.get("max_output_tokens", 8000), "temperature": temperature,
                "system": SYSTEM, "messages": [{"role": "user", "content": prompt}]}
        t0 = time.time()
        st, _, out = _http("POST", self.cfg["url"], self._hdr(), body)
        rec = {"kind": kind, "provider": "claude", "model": model, "seconds": round(time.time() - t0, 1), "images": 0}
        if st != 200:
            rec["error"] = f"HTTP {st}"
            CALLS.append(rec)
            raise Unavailable(f"claude HTTP {st}: {str(out)[:300]}", quota=_busy(st, out))
        usage = out.get("usage") or {}
        rec.update(prompt_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"))
        CALLS.append(rec)
        text = "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")
        return _parse(text, f"claude {model}")


KINDS = {"gemini": Gemini, "openai": OpenAICompatible, "claude": Claude}


def providers() -> list[Provider]:
    return [KINDS[c["kind"]](c) for c in config()["providers"]]


# ------------------------------------------------------------------ the interface
def _mock(kind: str):
    d = os.getenv("KI_LLM_MOCK") or os.getenv("KI_GEMINI_MOCK")
    if not d:
        return None
    n = sum(1 for c in CALLS if c["kind"] == kind and c.get("provider") == "mock")
    f = Path(d) / f"{kind}_{n}.json"
    if not f.exists():
        f = Path(d) / f"{kind}.json"
    CALLS.append({"kind": kind, "provider": "mock", "model": "mock", "seconds": 0.0, "file": f.name})
    return json.loads(f.read_text(encoding="utf-8"))


def call_json(kind: str, prompt: str, compact: str | None = None, images: list[Path] | None = None,
              sheet: Path | None = None, temperature: float = 0.3) -> dict:
    """The first JSON answer of the configured providers. compact: a shorter prompt for providers whose request
    limit the full one exceeds. images: the review stills (only vision providers are asked). Raises QuotaWait
    when every usable provider is exhausted, RuntimeError when they failed for other reasons."""
    mocked = _mock(kind)
    if mocked is not None:
        return mocked
    vision = bool(images)
    why, all_quota = [], True
    for p in providers():
        if p.name in EXHAUSTED:
            why.append(f"{p.name}: exhausted earlier this run ({EXHAUSTED[p.name][:80]})")
            continue
        if not p.ready():
            why.append(f"{p.name}: not configured" + (" (off: allow_claude_fallback is false)" if p.name == "claude" else ""))
            continue
        try:
            model = p.model(vision)
            if not model:
                why.append(f"{p.name}: no vision model")
                continue
            text = prompt if p.fits(prompt, images) else (compact or prompt)
            if not p.fits(text, images):
                why.append(f"{p.name}: the prompt is over its {p.cfg.get('max_input_tokens')}-token request limit")
                continue
            out = p.call(kind, text, images, model, temperature)
            if why:
                _log(f"{kind} answered by {p.name} ({model}) after: " + "; ".join(why))
            return out
        except Unavailable as e:
            why.append(f"{p.name}: {e}")
            all_quota = all_quota and e.quota
            if e.quota:
                EXHAUSTED[p.name] = str(e)
            _log(f"{kind}: {p.name} unavailable ({str(e)[:240]}); next provider")
    if all_quota:
        raise QuotaWait("; ".join(why))
    raise RuntimeError(f"no AI provider answered the {kind} call: " + "; ".join(why))
