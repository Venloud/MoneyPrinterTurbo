"""The director's AI provider chain with mocked HTTP (0 real calls)."""
import json
import os
import re
import time
import unittest
from pathlib import Path

from kindled_iron.director import gemini, llm
from kindled_iron.director.calls import CALLS

ROOT = Path(__file__).resolve().parents[2]
SECRETS = {"GEMINI_API_KEY": "g", "GITHUB_TOKEN": "gh", "HF_TOKEN": "hf", "GROQ_API_KEY": "gq",
           "OPENROUTER_API_KEY": "or", "KINDLED_CF_ACCOUNT_ID": "acct", "KINDLED_CF_API_TOKEN": "cf",
           "CLAUDE_CODE_OAUTH_TOKEN": "cl"}
HOSTS = {"github": "models.github.ai", "huggingface": "router.huggingface.co", "groq": "api.groq.com",
         "openrouter": "openrouter.ai", "cloudflare": "api.cloudflare.com", "claude": "api.anthropic.com"}


class FakeHTTP:
    """status per provider (200 = answers); records which providers were asked."""

    def __init__(self, status=None):
        self.status, self.asked = status or {}, []

    def __call__(self, method, url, headers, body=None, timeout=300):
        name = next(n for n, h in HOSTS.items() if h in url)
        if name == "claude" and url.endswith("/models"):
            return 200, {}, {"data": [{"id": "claude-x-sonnet"}, {"id": "claude-x-haiku"}]}
        self.asked.append((name, body))
        st = self.status.get(name, 200)
        if st != 200:
            return st, {}, {"error": {"message": "Rate limit exceeded: quota"}}
        if name == "claude":
            return 200, {}, {"content": [{"type": "text", "text": json.dumps({"by": name})}], "usage": {}}
        return 200, {}, {"choices": [{"message": {"content": json.dumps({"by": name})}}], "usage": {}}


class Providers(unittest.TestCase):
    def setUp(self):
        self.env = dict(os.environ)
        for k in ("KI_LLM_MOCK", "KI_GEMINI_MOCK"):
            os.environ.pop(k, None)
        os.environ.update(SECRETS)
        self.real = (gemini.models, gemini._try_model, llm._http, llm.config, time.sleep)
        self.cfg = json.loads(llm.CONFIG.read_text())
        llm.config = lambda: self.cfg
        gemini.models = lambda requested: ["gemini-a", "gemini-b"]
        gemini._try_model = lambda kind, name, body, images: ("HTTP 429 per-day quota", time.time())   # Gemini out
        time.sleep = lambda s: None
        llm.EXHAUSTED.clear()
        CALLS.clear()

    def tearDown(self):
        gemini.models, gemini._try_model, llm._http, llm.config, time.sleep = self.real
        llm.EXHAUSTED.clear()
        os.environ.clear()
        os.environ.update(self.env)

    def test_gemini_429_then_github_answers(self):
        http = FakeHTTP()
        llm._http = http
        self.assertEqual(llm.call_json("plan", "FULL " * 10, compact="SHORT"), {"by": "github"})
        self.assertEqual(CALLS[-1]["provider"], "github")
        self.assertEqual(CALLS[-1]["model"], self.cfg["providers"][1]["chat"])     # the model comes from config
        self.assertIn("gemini", llm.EXHAUSTED)                                      # skipped for the rest of the run

    def test_three_fail_then_the_fourth_answers(self):
        llm._http = FakeHTTP({"github": 429, "huggingface": 503})
        self.assertEqual(llm.call_json("plan", "FULL", compact="SHORT"), {"by": "groq"})
        self.assertEqual(set(llm.EXHAUSTED), {"gemini", "github", "huggingface"})
        http = FakeHTTP()                                     # later calls in the run skip the exhausted ones
        llm._http = http
        llm.call_json("plan", "FULL")
        self.assertEqual([n for n, _ in http.asked], ["groq"])

    def test_missing_secret_is_skipped(self):
        for k in ("GITHUB_TOKEN", "HF_TOKEN"):
            os.environ.pop(k)
        http = FakeHTTP()
        llm._http = http
        self.assertEqual(llm.call_json("plan", "FULL"), {"by": "groq"})
        self.assertNotIn("github", [n for n, _ in http.asked])

    def test_vision_only_asks_vision_providers(self):
        for p in self.cfg["providers"]:
            if p["name"] == "github":
                p["vision"] = None                            # pretend GitHub Models had no vision model
        http = FakeHTTP()
        llm._http = http
        img = Path(__file__).resolve().parents[2] / "kindled_iron" / "director" / "catalog.json"   # any bytes
        self.assertEqual(llm.call_json("review", "Q", images=[img]), {"by": "huggingface"})
        self.assertEqual([n for n, _ in http.asked], ["huggingface"])
        user = http.asked[0][1]["messages"][1]["content"]
        self.assertTrue(any(part.get("type") == "image_url" for part in user))
        self.assertEqual(http.asked[0][1]["model"], self.cfg["providers"][2]["vision"])

    def test_openrouter_only_free_models(self):
        llm._http = FakeHTTP({p: 429 for p in ("github", "huggingface", "groq")})
        for p in self.cfg["providers"]:
            if p["name"] == "openrouter":
                p["chat"] = "some/paid-model"
        self.assertEqual(llm.call_json("plan", "FULL"), {"by": "cloudflare"})

    def test_all_out_is_waiting_quota(self):
        llm._http = FakeHTTP({p: 429 for p in HOSTS})
        with self.assertRaises(llm.QuotaWait) as e:
            llm.call_json("plan", "FULL", compact="SHORT")
        for p in ("gemini", "github", "huggingface", "groq", "openrouter", "cloudflare"):
            self.assertIn(p, str(e.exception))
        self.assertIn("allow_claude_fallback is false", str(e.exception))

    def test_claude_only_when_allowed_and_once(self):
        llm._http = FakeHTTP({p: 429 for p in HOSTS if p != "claude"})
        with self.assertRaises(llm.QuotaWait):
            llm.call_json("plan", "FULL")                    # off by default
        llm.EXHAUSTED.clear()
        self.cfg["allow_claude_fallback"] = True
        http = FakeHTTP({p: 429 for p in HOSTS if p != "claude"})
        llm._http = http
        self.assertEqual(llm.call_json("plan", "FULL"), {"by": "claude"})
        llm.EXHAUSTED.clear()
        with self.assertRaises(llm.QuotaWait):                # max 1 plan call per video
            llm.call_json("plan", "FULL")

    def test_forbidden_secrets_never_referenced(self):
        banned = re.compile(r"\b(CLOUDFLARE_ACCOUNT_ID|CLOUDFLARE_API_TOKEN|OPENAI_API_KEY|MOONSHOT_API_KEY|WAVESPEED_API_KEY)\b")
        files = list((ROOT / "kindled_iron" / "director").glob("*.py")) + \
            list((ROOT / "kindled_iron" / "director").glob("*.json")) + \
            [ROOT / ".github" / "workflows" / "kindled_iron_director_preview.yml"]
        hits = [f"{f.name}: {m.group(1)}" for f in files for m in banned.finditer(f.read_text(encoding="utf-8"))]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
