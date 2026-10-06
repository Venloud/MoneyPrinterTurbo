"""Pose / action sheet: every guide action on one image, for approving the body before a full render.

    python -m kindled_iron.action_sheet --out storage/kindled_iron/action_sheet.png

No voice, no network: each action plays on its own little stage and one frame from the middle of it
is captured, labelled and tiled.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from kindled_iron import effects
from kindled_iron.render import (CAPTION, HOST_LOOK, HUD, PALETTE, SAFE, VENDOR, capture, log, vendor_parts, write_page)

PW = 1080
T = 4.0           # seconds per cell
GUIDE = {"x": 540, "scale": 1.7, "facing": 1, "accent": True, "faceless": True, **HOST_LOOK}
FACES = [
    ("neutral", [], [], 0.6),
    ("happy", [], [{"t": 0.1, "do": "express", "who": "guide", "expression": "happy"}], 0.6),
    ("surprised", [], [{"t": 0.1, "do": "express", "who": "guide", "expression": "surprised"}], 0.6),
    ("confused (meme)", [], [{"t": 0.2, "do": "reaction", "who": "guide", "face": "confused_math", "dur": 1.4}], 0.8),
    ("mind-blown (meme)", [], [{"t": 0.2, "do": "reaction", "who": "guide", "face": "mind_blown", "dur": 1.4}], 0.8),
]


def cells():
    """(label, objects, events, sample offset). Positions are panel-local; times relative to the cell."""
    return [
        ("neutral, front", [], [], 0.6),
        ("happy", [], [{"t": 0.1, "do": "express", "who": "guide", "expression": "happy"}], 0.6),
        ("surprised", [], [{"t": 0.1, "do": "express", "who": "guide", "expression": "surprised"}], 0.6),
        ("curious", [], [{"t": 0.1, "do": "express", "who": "guide", "expression": "curious"}], 0.6),
        ("awe (looking up)", [], [{"t": 0.1, "do": "look", "who": "guide", "dir": "up", "expression": "awe", "hold": 3}], 0.8),
        ("walk", [], [{"t": 0.1, "do": "place", "who": "guide", "x": 330}, {"t": 0.2, "do": "walk", "who": "guide", "to": 760}], 1.0),
        ("wave", [], [{"t": 0.2, "do": "wave", "who": "guide"}], 0.9),
        ("point", [{"id": "s4", "type": "star", "x": 820, "y": 520, "r": 40}], [{"t": 0.2, "do": "point", "who": "guide", "toward": "s4"}], 0.9),
        ("light fills the scene, shield eyes", [{"id": "l5", "type": "sun", "x": 780, "y": 420}],
         [{"t": 0.1, "do": "light_burst", "x": 780, "y": 420, "dur": 1.0, "hold": 1.5}, {"t": 0.3, "do": "shield_eyes", "who": "guide"}], 1.3),
        ("in the dark (outline + scarf)", [{"id": "d6", "type": "darkness", "x": 540, "y": 820, "w": 900, "h": 760}],
         [{"t": 0.1, "do": "ghost", "who": "guide", "value": 1, "dur": 0.3}, {"t": 0.1, "do": "float", "who": "guide", "y": -120}], 1.2),
        ("float", [], [{"t": 0.1, "do": "float", "who": "guide", "y": -160}], 1.2),
        ("parachute", [{"id": "c8", "type": "cloud", "x": 260, "y": 360}], [{"t": 0.1, "do": "parachute", "who": "guide", "from": -700, "dur": 2.6}], 1.3),
        ("pop up from the ground", [{"id": "h9", "type": "line", "x": 540, "y": 1172, "w": 900}, {"id": "dirt9", "type": "splash", "x": 540, "y": 1165, "dirt": True, "r": 120}],
         [{"t": 0.1, "do": "pop_up", "who": "guide"}, {"t": 0.15, "do": "draw", "id": "dirt9", "dur": 0.3}], 0.38),
        ("climb", [{"id": "h10", "type": "hill", "x": 700, "y": 1172, "w": 760, "h": 330}],
         [{"t": 0.1, "do": "place", "who": "guide", "x": 330}, {"t": 0.2, "do": "climb", "who": "guide", "dx": 260, "dy": -230, "dur": 1.8, "endY": -230}], 1.1),
        ("sit under the tree", [{"id": "t11", "type": "tree", "x": 640, "y": 1026, "scale": 1.2}],
         [{"t": 0.2, "do": "sit", "who": "guide", "against": "t11", "facing": -1}], 1.0),
        ("lie down, look up", [{"id": "st12", "type": "stars", "x": 540, "y": 520, "w": 600, "h": 200, "n": 6}],
         [{"t": 0.2, "do": "lie_down", "who": "guide"}], 1.2),
        ("swim + snorkel", [{"id": "w13", "type": "waves", "x": 540, "y": 1040, "w": 900, "rows": 3, "scale": 1.3}],
         [{"t": 0.1, "do": "swim", "who": "guide", "in": "w13", "snorkel": True, "dur": 3.0, "dx": 120}], 1.4),
        ("ride a fish", [{"id": "w14", "type": "waves", "x": 540, "y": 1120, "w": 900, "rows": 2}, {"id": "f14", "type": "fish", "x": 520, "y": 1100, "scale": 2.2, "allow_overlap": True}],
         [{"t": 0.1, "do": "ride", "who": "guide", "on": "f14", "dx": -14}], 1.0),
        ("pet the sheep", [{"id": "a16", "type": "animal", "x": 760, "y": 1110, "scale": 1.1}],
         [{"t": 0.1, "do": "place", "who": "guide", "x": 480}, {"t": 0.2, "do": "pet", "who": "guide", "toward": "a16"}], 1.0),
        ("peek from behind the tree", [{"id": "t17", "type": "tree", "x": 540, "y": 960, "scale": 2.1}],
         [{"t": 0.2, "do": "peek", "who": "guide", "toward": "t17", "side": 1}], 1.0),
        ("jump", [], [{"t": 0.2, "do": "jump", "who": "guide", "height": 170}], 0.67),
        ("fall", [], [{"t": 0.2, "do": "fall", "who": "guide", "height": 520, "dur": 1.0}], 0.62),
        ("reaction: side-eye (brows only)", [], [{"t": 0.2, "do": "reaction", "who": "guide", "face": "side_eye", "dur": 1.4}], 0.8),
        ("presents the people", [], [{"t": 0.1, "do": "place", "who": "guide", "x": 760, "facing": -1},
                                     {"t": 0.1, "do": "enter", "who": "man", "dur": 0.5}, {"t": 0.15, "do": "enter", "who": "woman", "dur": 0.5},
                                     {"t": 0.6, "do": "present", "who": "guide"}], 1.4),
        ("ending: looks at the viewer", [], [{"t": 0.2, "do": "look_viewer", "who": "guide"}], 1.0),
    ]


def build(work: Path, faces: bool = False) -> tuple[dict, list[tuple[str, float]]]:
    objects, events, samples = [], [], []
    cs = FACES if faces else cells()
    people_panel = next((i for i, c in enumerate(cs) if c[0].startswith("presents")), 99)
    cast = {"guide": dict(GUIDE),
            "man": {"x": 260 + PW * people_panel, "scale": 1.5, "facing": 1, "hair": "short",
                    "colors": {"shirt": "#7FA36B", "pants": "#5E6B47", "skin": "#D9A877", "hair": "#3B2A1E"}},
            "woman": {"x": 480 + PW * people_panel, "scale": 1.5, "facing": -1, "hair": "long-straight", "dress": True,
                      "colors": {"shirt": "#C98BA3", "dress": "#C98BA3", "pants": "#8C5C70", "skin": "#E8C09A", "hair": "#5A3B2A"}}}
    for i, (label, objs, evs, peak) in enumerate(cs):
        t0, off = i * T, PW * i
        events.append({"t": t0, "do": "camera", "x": off + 540, "y": 880, "zoom": 1.0, "dur": 0.01})
        events.append({"t": t0, "do": "place", "who": "guide", "x": off + 540, "facing": 1})
        events.append({"t": t0, "do": "ghost", "who": "guide", "value": 0, "dur": 0.01})
        for o in objs:
            objects.append({**o, "x": o["x"] + off})
            if o["type"] != "splash":
                events.append({"t": t0, "do": "draw", "id": o["id"], "dur": 0.01, "instant": True})
        for e in evs:
            e = {**e, "t": t0 + e["t"]}
            for k in ("x", "to"):
                if k in e and e["do"] in ("place", "walk"):
                    e[k] += off
            events.append(e)
        samples.append((label, t0 + peak))
    events.sort(key=lambda e: e["t"])
    data = {"width": 1080, "height": 1920, "fps": 30, "duration": len(cs) * T, "ground": 1170, "palette": PALETTE,
            "cast": cast, "objects": objects, "events": events, "captions": [], "camera": {"x": 540, "y": 880, "zoom": 1.0},
            "vendor": vendor_parts(), "safe": SAFE, "debugSafe": False, "captionSize": CAPTION["size"], "hud": HUD,
            "paper": effects.paper_texture(work, PALETTE["board"]), "inboxReactions": []}
    return data, samples


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="storage/kindled_iron/action_sheet.png")
    ap.add_argument("--work", default="storage/kindled_iron/action_sheet_work")
    ap.add_argument("--chrome", default=None)
    ap.add_argument("--faces", action="store_true", help="pose sheet of the host's faces only (neutral, happy, surprised, confused, mind-blown)")
    a = ap.parse_args()
    work = Path(a.work).resolve()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    data, samples = build(work, a.faces)
    page = write_page(data, work)
    capture(page, None, None, data["duration"], a.chrome, [t for _, t in samples], work / "stills")
    font = (VENDOR / "fonts" / "Caveat.ttf").as_posix()
    cells_dir = work / "cells"
    cells_dir.mkdir()
    for i, (label, t) in enumerate(samples):
        src = work / "stills" / f"frame_{t:05.2f}.png"
        txt = label.replace(":", r"\:").replace(",", r"\,")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf",
                        ("crop=640:800:220:560,scale=360:450,pad=360:502:0:0:color=0xF4F1EA," if a.faces else
                         "crop=1080:1200:0:220,scale=360:400,pad=360:452:0:0:color=0xF4F1EA,") +
                        f"drawtext=fontfile='{font}':text='{txt}':fontsize=34:fontcolor=0x222222:x=(w-text_w)/2:y={460 if a.faces else 410},"
                        f"drawbox=x=0:y=0:w=iw:h=ih:color=0xCCCCCC:t=2",
                        str(cells_dir / f"cell_{i:02d}.png")], check=True)
    n = len(samples)
    cols = 5 if a.faces else 6
    rows = (n + cols - 1) // cols
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-framerate", "1", "-i", str(cells_dir / "cell_%02d.png"),
                    "-vf", f"tile={cols}x{rows}:color=0xF4F1EA", "-frames:v", "1", str(Path(a.out).resolve())], check=True)
    log(f"action sheet: {a.out} ({n} actions)")


if __name__ == "__main__":
    main()
