"""One interface for the director's AI calls (the shot plan and the vision review), whatever provider answers.

Providers, in order (each one is skipped when it is not configured, out of quota or busy):
  1. Gemini Flash models (GEMINI_API_KEY, free tier; the key's own Flash models, see gemini.py)
  2. GitHub Models (GITHUB_TOKEN inside Actions with `permissions: models: read`; the best chat model of the
     catalog, one that also reads images for the review). Free requests are small (8k tokens in), so they get
     the compact prompt.
  3. Cloudflare Workers AI (CLOUDFLARE_ACCOUNT_ID / CLOUDFLARE_API_TOKEN), last resort. The account's daily free
     neurons are shared with Night Files: a call is made only when Cloudflare's own analytics say there is room
     (cf_budget below), and never more than KI_CF_DAILY_NEURONS a day for this bot.

call_json() returns the first JSON answer. When no provider answers because every one is out of quota, busy or
over its budget, it raises QuotaWait: the video waits for the daily reset instead of failing. Every call (also
the failed ones) is logged in calls.CALLS with its provider. Offline tests set KI_LLM_MOCK (or the older
KI_GEMINI_MOCK) to a directory of canned answers (plan_<n>.json / plan.json, review_<n>.json / review.json).
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from kindled_iron.director.calls import CALLS


class Unavailable(Exception):
    """This provider gave no answer. quota=True: out of quota / busy / over budget (worth waiting for)."""

    def __init__(self, msg: str, quota: bool = True):
        super().__init__(msg)
        self.quota = quota


class QuotaWait(Exception):
    """No provider can answer until a quota resets."""


def _log(msg: str) -> None:
    print(f"[llm] {msg}", flush=True)


def _http(method: str, url: str, headers: dict, body: dict | None = None, timeout: float = 300):
    """-> (status, headers, parsed JSON or text). Never raises on an HTTP error status (tests replace this)."""
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


# ------------------------------------------------------------------ 1. Gemini
class Gemini:
    name, compact = "gemini", False

    def ready(self) -> bool:
        return bool(os.getenv("GEMINI_API_KEY"))

    def call(self, kind, prompt, images, sheet, temperature):
        from kindled_iron.director import gemini
        return gemini.generate(kind, prompt, images=images, temperature=temperature)


# ------------------------------------------------------------------ 2. GitHub Models
GH_API = "https://models.github.ai"
# the strongest families first; within the catalog the first match wins (no guessed names: only listed models)
GH_PREFER = [r"gpt-5(?!.*(nano|mini))", r"gpt-4\.1(?!.*(nano|mini))", r"gpt-4o(?!.*mini)", r"gpt-5-mini", r"gpt-4\.1-mini",
             r"gpt-4o-mini", r"llama-4", r"llama-3\.3-70b", r"deepseek-v3", r"mistral-(medium|large)"]


class GitHubModels:
    name, compact = "github", True
    _cat: list | None = None

    def ready(self) -> bool:
        return bool(os.getenv("KI_MODELS_TOKEN") or os.getenv("GITHUB_MODELS_TOKEN"))

    def _hdr(self) -> dict:
        tok = os.getenv("KI_MODELS_TOKEN") or os.getenv("GITHUB_MODELS_TOKEN")
        return {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"}

    def pick(self, vision: bool) -> dict:
        if GitHubModels._cat is None:
            st, _, cat = _http("GET", f"{GH_API}/catalog/models", self._hdr(), timeout=30)
            if st != 200 or not isinstance(cat, list):
                raise Unavailable(f"GitHub Models catalog HTTP {st}: {str(cat)[:200]}", quota=st in (0, 429, 503))
            GitHubModels._cat = cat
        ok = [m for m in GitHubModels._cat if "text" in (m.get("supported_output_modalities") or ["text"])
              and (not vision or "image" in (m.get("supported_input_modalities") or []))
              and not re.search(r"embed|whisper|tts|image-gen|dall", m.get("id", ""), re.I)]
        for pat in GH_PREFER:
            for m in ok:
                if re.search(pat, m.get("id", ""), re.I):
                    return m
        if not ok:
            raise Unavailable("GitHub Models: no " + ("vision " if vision else "") + "chat model in the catalog", quota=False)
        return ok[0]

    def call(self, kind, prompt, images, sheet, temperature):
        m = self.pick(vision=bool(images))
        mid = m["id"]
        limit = int(((m.get("limits") or {}).get("max_input_tokens")) or 8000)
        limit = min(limit, int(os.getenv("KI_GH_MAX_INPUT_TOKENS", "8000")))     # the free tier's per-request cap
        if len(prompt) / 3.6 + 85 * len(images or []) > limit:
            raise Unavailable(f"GitHub Models {mid}: prompt ~{len(prompt) / 3.6:.0f} tokens is over its {limit}-token "
                              "request limit", quota=False)
        content: list = [{"type": "text", "text": prompt}]
        for img in images or []:
            content.append({"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(Path(img).read_bytes()).decode(), "detail": "low"}})
        reasoning = bool(re.search(r"gpt-5|/o\d", mid))
        body = {"model": mid, "messages": [
            {"role": "system", "content": "You answer with one JSON object only."},
            {"role": "user", "content": content}], "response_format": {"type": "json_object"}}
        body["max_completion_tokens" if reasoning else "max_tokens"] = 4000
        if not reasoning:
            body["temperature"] = temperature
        t0 = time.time()
        st, hd, out = _http("POST", f"{GH_API}/inference/chat/completions", self._hdr(), body)
        rec = {"kind": kind, "provider": "github", "model": mid, "seconds": round(time.time() - t0, 1),
               "images": len(images or [])}
        if st != 200:
            rec["error"] = f"HTTP {st}"
            CALLS.append(rec)
            raise Unavailable(f"GitHub Models {mid} HTTP {st}: {str(out)[:300]}", quota=st in (0, 429, 500, 502, 503, 504))
        usage = out.get("usage") or {}
        rec.update(prompt_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"))
        CALLS.append(rec)
        from kindled_iron.director.gemini import parse_json
        try:
            text = out["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise Unavailable(f"GitHub Models {mid}: no answer text", quota=False) from None
        return parse_json(text, f"GitHub Models {mid}")


# ------------------------------------------------------------------ 3. Cloudflare Workers AI (shared budget)
CF_API = "https://api.cloudflare.com/client/v4"
CF_TEXT = os.getenv("KI_CF_TEXT_MODEL", "@cf/meta/llama-3.3-70b-instruct-fp8-fast")
CF_VISION = os.getenv("KI_CF_VISION_MODEL", "@cf/meta/llama-3.2-11b-vision-instruct")
CF_DAILY = 10000.0                       # the account's free neurons per UTC day (Night Files uses most of them)
CF_RESERVE = 20 * 172.8                  # always leave Night Files room for at least 20 FLUX images
# neurons per million tokens, as Cloudflare prices these models (input, output)
CF_PRICE = {"llama-3.3-70b": (26668, 204805), "llama-3.2-11b-vision": (4410, 61493)}


def cf_used_today() -> tuple[float, float]:
    """(account total, this bot's models) neurons used today, from Cloudflare's own analytics (the same count
    Night Files reads). Raises Unavailable when the analytics cannot be read: then the budget is unknown."""
    acct, token = os.getenv("CLOUDFLARE_ACCOUNT_ID"), os.getenv("CLOUDFLARE_API_TOKEN")
    now = datetime.now(timezone.utc)
    query = """query($acct: String!, $since: Time!, $until: Time!) { viewer { accounts(filter: {accountTag: $acct}) {
      aiInferenceAdaptiveGroups(limit: 200, filter: {datetime_geq: $since, datetime_leq: $until}) {
        sum { totalNeurons } dimensions { modelId } } } } }"""
    st, _, data = _http("POST", f"{CF_API}/graphql", {"Authorization": f"Bearer {token}"},
                        {"query": query, "variables": {"acct": acct, "since": now.strftime("%Y-%m-%dT00:00:00Z"),
                                                       "until": now.strftime("%Y-%m-%dT%H:%M:%SZ")}}, timeout=30)
    try:
        rows = data["data"]["viewer"]["accounts"][0]["aiInferenceAdaptiveGroups"]
    except (KeyError, IndexError, TypeError):
        raise Unavailable(f"Cloudflare analytics unreadable (HTTP {st}: {str(data)[:160]}): the shared budget is "
                          "unknown, so Cloudflare is not used") from None
    total = sum(float(r["sum"].get("totalNeurons") or 0) for r in rows)
    mine = sum(float(r["sum"].get("totalNeurons") or 0) for r in rows
               if r["dimensions"]["modelId"] in (CF_TEXT, CF_VISION))
    return total, mine


class Cloudflare:
    name, compact = "cloudflare", True

    def ready(self) -> bool:
        return bool(os.getenv("CLOUDFLARE_ACCOUNT_ID") and os.getenv("CLOUDFLARE_API_TOKEN"))

    def call(self, kind, prompt, images, sheet, temperature):
        vision = bool(images)
        model = CF_VISION if vision else CF_TEXT
        price = CF_PRICE["llama-3.2-11b-vision" if vision else "llama-3.3-70b"]
        est = len(prompt) / 3.6 * price[0] / 1e6 + 4000 * price[1] / 1e6 + (600 if vision else 0)
        total, mine = cf_used_today()
        cap = float(os.getenv("KI_CF_DAILY_NEURONS", "1500"))
        if mine + est > cap or total + est > CF_DAILY - CF_RESERVE:
            raise Unavailable(f"Cloudflare budget: today {total:.0f}/{CF_DAILY:.0f} neurons (this bot {mine:.0f}/{cap:.0f}), "
                              f"a call needs ~{est:.0f}: left for Night Files")
        acct, token = os.getenv("CLOUDFLARE_ACCOUNT_ID"), os.getenv("CLOUDFLARE_API_TOKEN")
        body: dict = {"messages": [{"role": "system", "content": "You answer with one JSON object only."},
                                   {"role": "user", "content": prompt}], "max_tokens": 4000, "temperature": temperature}
        if vision:
            img = Path(sheet or images[0]).read_bytes()          # one image: the stills as one sheet
            body["image"] = list(img)
        else:
            body["response_format"] = {"type": "json_object"}
        url, hdr = f"{CF_API}/accounts/{acct}/ai/run/{model}", {"Authorization": f"Bearer {token}"}
        t0 = time.time()
        st, hd, out = _http("POST", url, hdr, body)
        if st != 200 and "agree" in str(out).lower():            # Meta's license: accepted once per account
            _http("POST", url, hdr, {"prompt": "agree"}, timeout=60)
            st, hd, out = _http("POST", url, hdr, body)
        if st != 200 and not vision and "response_format" in str(out):
            body.pop("response_format", None)
            st, hd, out = _http("POST", url, hdr, body)
        rec = {"kind": kind, "provider": "cloudflare", "model": model, "seconds": round(time.time() - t0, 1),
               "images": 1 if vision else 0, "neurons": hd.get("cf-ai-neurons") or hd.get("Cf-Ai-Neurons"),
               "budget_before": f"{total:.0f}/{CF_DAILY:.0f}"}
        if st != 200:
            rec["error"] = f"HTTP {st}"
            CALLS.append(rec)
            raise Unavailable(f"Cloudflare {model} HTTP {st}: {str(out)[:300]}",
                              quota=st in (0, 429, 500, 502, 503, 504) or "3036" in str(out))
        CALLS.append(rec)
        res = (out or {}).get("result") or {}
        ans = res.get("response")
        if isinstance(ans, dict):
            return ans
        from kindled_iron.director.gemini import parse_json
        return parse_json(str(ans or ""), f"Cloudflare {model}")


PROVIDERS = [Gemini(), GitHubModels(), Cloudflare()]


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
    """The first JSON answer of Gemini -> GitHub Models -> Cloudflare. compact: the shorter prompt for the
    small-request providers. Raises QuotaWait when every provider is out of quota / busy / over budget, and
    RuntimeError when one failed for another reason and nobody answered."""
    mocked = _mock(kind)
    if mocked is not None:
        return mocked
    why, all_quota = [], True
    for p in PROVIDERS:
        if not p.ready():
            why.append(f"{p.name}: not configured")
            continue
        try:
            out = p.call(kind, compact if (p.compact and compact) else prompt, images, sheet, temperature)
            if why:
                _log(f"{kind} answered by {p.name} after: " + "; ".join(why))
            return out
        except Unavailable as e:
            why.append(f"{p.name}: {e}")
            all_quota = all_quota and e.quota
            _log(f"{kind}: {p.name} unavailable ({str(e)[:240]}); next provider")
    if all_quota:
        raise QuotaWait("; ".join(why))
    raise RuntimeError(f"no AI provider answered the {kind} call: " + "; ".join(why))
