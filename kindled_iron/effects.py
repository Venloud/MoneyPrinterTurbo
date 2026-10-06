"""Small polish layers: reaction rules and the paper texture (sound design lives in sound.py)."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
INBOX = HERE / "reactions_inbox"
SR = 44100

BUILTIN_FACES = {"shocked", "mind_blown", "side_eye", "crying_laughing", "thinking", "wait_what"}
MAX_REACTIONS, MIN_GAP = 2, 15.0


# --------------------------------------------------------------- reactions
def _inbox() -> list[dict]:
    f = INBOX / "reactions.json"
    if not f.exists():
        return []
    items = json.loads(f.read_text(encoding="utf-8")).get("reactions", [])
    return [r for r in items if r.get("approved") and (INBOX / r.get("file", "")).exists()]


def apply_reaction_rules(events: list[dict], scene: dict, spans, beat_words, work: Path, log) -> list[dict]:
    """Hard limits: max 2 a video, never two within 15 s, never on a serious/holy beat or on the word
    'God', each under 1.5 s. Extras are dropped with a WARNING. Resolves inbox images."""
    serious = [spans[i] for i, b in enumerate(scene["beats"]) if b.get("serious")]
    god_times = [w["start"] for bw in beat_words for w in bw if re.sub(r"[^a-z]", "", w["word"].lower()) == "god"]
    inbox, inbox_used = _inbox(), []
    kept, last = [], None
    for e in sorted(events, key=lambda x: x["t"]):
        if e["do"] != "reaction":
            continue
        why = None
        if len(kept) >= MAX_REACTIONS:
            why = f"more than {MAX_REACTIONS} reactions"
        elif last is not None and e["t"] - last < MIN_GAP:
            why = f"within {MIN_GAP:.0f} s of the previous one"
        elif any(a - 0.3 <= e["t"] <= b + 0.3 for a, b in serious):
            why = "on a serious/holy beat"
        elif any(abs(e["t"] - g) < 0.8 for g in god_times):
            why = "on the word 'God'"
        if why:
            log(f"WARNING: reaction at {e['t']:.1f} s dropped ({why})")
            e["_drop"] = True
            continue
        e["dur"] = min(1.5, float(e.get("dur", 1.2)))
        want = e.get("face") or e.get("emotion")
        pick = next((r for r in inbox if r["emotion"] == want), None) if e.get("use_inbox") else None
        if pick:
            key = f"inbox_{len(inbox_used)}"
            shutil.copy(INBOX / pick["file"], work / f"{key}{Path(pick['file']).suffix}")
            inbox_used.append({"key": key, "href": (work / f"{key}{Path(pick['file']).suffix}").as_uri()})
            e["face"] = key
        elif want in BUILTIN_FACES:
            e["face"] = want
        else:
            log(f"WARNING: reaction face {want!r} unknown; dropped")
            e["_drop"] = True
            continue
        kept.append(e)
        last = e["t"]
    desc = ", ".join("%s at %.1f s" % (x["face"], x["t"]) for x in kept) or "none"
    log(f"reactions: {len(kept)} ({desc})")
    return inbox_used


# --------------------------------------------------------------- paper
def paper_texture(work: Path, board: str) -> str:
    out = work / "paper.png"
    if not out.exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"color=c=0x{board.lstrip('#')}:s=1080x1920,noise=alls=9:allf=u,gblur=sigma=0.7",
                        "-frames:v", "1", str(out)], check=True)
    return out.as_uri()
