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

BUILTIN_FACES = {"confused_math", "puzzled", "surprised", "shocked", "mind_blown", "side_eye", "crying_laughing", "thinking", "wait_what"}
# {"reaction": "<emotion>"} -> the guide's drawn face for that emotion (the meme image, if any, pops in beside him)
EMOTION_FACE = {"confused": "confused_math", "confused_math": "confused_math", "mind_blown": "mind_blown", "surprised": "surprised",
                "shocked": "shocked", "smart": "thinking", "thinking": "thinking", "celebration": "crying_laughing"}
MAX_REACTIONS, MIN_GAP = 3, 3.0


# --------------------------------------------------------------- reactions
def _inbox() -> list[dict]:
    f = INBOX / "reactions.json"
    if not f.exists():
        return []
    items = json.loads(f.read_text(encoding="utf-8")).get("reactions", [])
    return [r for r in items if r.get("approved") and (INBOX / r.get("file", "")).exists()]


def apply_reaction_rules(events: list[dict], scene: dict, spans, beat_words, work: Path, log, data: dict | None = None,
                         third_party: bool = False) -> tuple[list[dict], list[dict]]:
    """Hard limits: max 3 a video, 3 s apart, never on a serious/holy beat, a scripture card or the
    word 'God', each under 1.5 s. Extras are dropped with a WARNING. With third-party media on, an
    emotion request also pops a meme image beside the guide (private reactions/ -> ReactionPics).
    Returns (inbox faces, third-party images used)."""
    from kindled_iron import private_media

    cards = [(o["_t0"], o["_t1"]) for o in (data or {}).get("objects", []) if o.get("type") == "scripture" and "_t0" in o]
    meme_used = []
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
        elif not e.get("allow_god") and any(abs(e["t"] - g) < 0.4 for g in god_times):
            why = "on the word 'God'"
        elif any(a - 0.2 <= e["t"] <= b + 0.2 for a, b in cards):
            why = "on a scripture card"
        if why:
            log(f"WARNING: reaction at {e['t']:.1f} s dropped ({why})")
            e["_drop"] = True
            continue
        e["dur"] = min(1.5, float(e.get("dur", 1.2)))
        emotion = e.get("emotion")
        want = e.get("face") or EMOTION_FACE.get(emotion, emotion)
        if third_party and emotion and e.get("image", True) and data is not None:
            got = private_media.reaction_card(emotion, e["t"], e["dur"], e.get("card") or {}, work, len(meme_used) + 1)
            if got:
                obj, ev, rec = got
                data["objects"].append(obj)
                data["events"].append(ev)
                meme_used.append({**rec, "t": round(e["t"], 2)})
        # the owner's own approved images in reactions_inbox/ win over the drawn faces
        pick = next((r for r in inbox if r["emotion"] == want), None) if e.get("use_inbox", True) else None
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
    log(f"reactions: {len(kept)} ({desc})" + "".join(f"; meme image {m['origin']} at {m['t']:.1f} s" for m in meme_used))
    return inbox_used, meme_used


# --------------------------------------------------------------- paper
def paper_texture(work: Path, board: str) -> str:
    out = work / "paper.png"
    if not out.exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                        f"color=c=0x{board.lstrip('#')}:s=1080x1920,noise=alls=9:allf=u,gblur=sigma=0.7",
                        "-frames:v", "1", str(out)], check=True)
    return out.as_uri()
