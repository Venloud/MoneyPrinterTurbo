"""Script length rule for Kindled Iron, checked before anything is voiced.

Target: a 61-68 s video, i.e. a script of about 145-155 words. Shorter is fine only when
the story is complete; never pad. A scene under MIN_WORDS words gets ONE automatic rewrite
pass (Gemini, needs GEMINI_API_KEY) asking for a fuller version of the same story. The
rewrite returns the whole scene JSON (narration + events, since events are keyed to words)
and is used only if every event still finds its word. Owner-written scripts set
"exact_narration": true and are never rewritten.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

REWRITE_MODEL = os.environ.get("KI_REWRITE_MODEL", "gemini-2.5-flash")

WRITING_RULES = """Writing rules:
- The hook (first line) must be explained in the next 1-2 lines.
- Use words a 6-year-old understands. No theology jargon.
- Leave out side details. Summarize; never read verses.
- Only the Bible's 66 books. Make no claim the chapter itself does not support.
- Never pad: no filler lines, no long goodbye. Every line moves the story."""


def word_count(scene: dict) -> int:
    return sum(len(b["narration"].split()) for b in scene["beats"])


def _anchors_ok(scene: dict) -> bool:
    for beat in scene["beats"]:
        words = {re.sub(r"[^a-z0-9]", "", w.lower()) for w in beat["narration"].split()}
        for ev in beat.get("events", []):
            at = ev.get("at")
            if isinstance(at, str) and at != "end":
                w = re.sub(r"[^a-z0-9]", "", re.split(r"[#+-]", at)[0].lower())
                if w not in words:
                    return False
    return True


def rewrite_fuller(scene: dict, log) -> dict | None:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        log("WARNING: rewrite pass skipped (no GEMINI_API_KEY)")
        return None
    prompt = (f"This Kindled Iron scene JSON has a {word_count(scene)}-word script. Rewrite it as a FULLER "
              f"version of the same story, 145-155 words in total, so the video runs 61-68 seconds. "
              f"Add real story content, never filler.\n{WRITING_RULES}\n"
              "Keep the exact same JSON format, cast, panels and object types. Update the events so every word "
              "anchor (\"at\") is a word of its own beat's narration. Return ONLY the JSON.\n\n" + json.dumps(scene))
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"responseMimeType": "application/json", "temperature": 0.6}}).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{REWRITE_MODEL}:generateContent"
    req = urllib.request.Request(url, body, {"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            text = json.load(r)["candidates"][0]["content"]["parts"][0]["text"]
        new = json.loads(text)
    except Exception as e:  # noqa: BLE001 - any failure = render the original
        log(f"WARNING: rewrite pass failed ({type(e).__name__}: {str(e)[:120]}); rendering the original")
        return None
    if not isinstance(new, dict) or not new.get("beats") or not _anchors_ok(new):
        log("WARNING: rewrite pass returned an unusable scene; rendering the original")
        return None
    log(f"rewrite pass: {word_count(scene)} -> {word_count(new)} words")
    return new


def check(scene: dict, log, min_words: int) -> dict:
    n = word_count(scene)
    log(f"Script: {n} words (target ~145-155)")
    if n >= min_words:
        return scene
    if scene.get("exact_narration"):
        log(f"WARNING: script under {min_words} words, but exact_narration is set (owner's text): no rewrite")
        return scene
    return rewrite_fuller(scene, log) or scene
