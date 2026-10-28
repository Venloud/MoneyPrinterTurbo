"""Visual themes: the same renderer and director, different colours and paper.

A scene picks one with "theme": "<name>"; without it nothing changes (the Kindled Iron look). A theme only swaps
data the renderer already reads when it builds the page: the palette (every drawing, the guide, captions, the clip
box and the verse card take their colours from it by name), the guide's colours and the paper. No layout, timing,
editing or animation code depends on it.

    blueprint   deep-blue engineering paper with a fine grid; white technical line drawings (every fill becomes a
                flat blue panel, every line white); the guide as a white outline with his usual expressions;
                light-cyan highlights
"""
from __future__ import annotations

import json

BOARD = "#123A6B"
PANEL = "#17457C"          # fills read as flat panels a shade lighter than the paper, never as colour
WHITE = "#F4F8FF"

THEMES: dict[str, dict] = {
    "blueprint": {
        "palette": {
            "board": BOARD, "ink": WHITE, "inkSoft": "#BFD4EE", "accent": "#8FD8FF",
            "water": PANEL, "waterLine": "#DCEBFF", "green": PANEL, "greenLine": "#DCEBFF", "leaf": PANEL,
            "trunk": PANEL, "wool": PANEL, "woolGray": PANEL, "fishBody": PANEL, "fishBelly": PANEL,
            "cloud": PANEL, "cloudShade": PANEL, "page": PANEL, "moon": PANEL, "starFill": PANEL,
            "shadow": "#0D2D55", "leafDark": PANEL, "marker": "#2C5D97",
            "skin": PANEL, "robe": PANEL, "robeDark": PANEL, "controller": PANEL,
        },
        "host_colors": {"skin": PANEL, "hair": PANEL, "shirt": PANEL, "pants": PANEL, "shoe": PANEL},
        "grid": {"minor": 40, "major": 200},
    },
}


# Narrator characters a video may ask for (approved_audio/<id>/settings.json "character"); without one the guide is the
# theme's usual narrator. Same rig, joints and animations; only the drawing differs (runtime buildChar: spec.style).
#   teen   a stylized teenager: taller oval head with a jaw (about 0.43 of the body), big readable features, an
#          oversized hoodie and baggy cargo pants drawn as outlines only (approved 2026-10-27 for evaluation in
#          Computer Bugs only; it never replaces another video's approved character)
CHARACTERS: dict[str, dict] = {
    # height: the figure's height relative to the default narrator (measured on the page: 577 / 499 px); the
    # compiler scales it to fill the same guide box the layout is built around (proportions unchanged)
    "teen": {"style": "teen", "colors": {"hoodie": "#FF5F52", "pants": "#0B0D12"}, "height": 1.157},
}


def character(name: str | None) -> dict:
    """The cast spec for a narrator character ({} for the theme's own). An unknown name is an error."""
    if not name:
        return {}
    if name not in CHARACTERS:
        raise SystemExit(f"FAIL: unknown character {name!r} (known: {', '.join(sorted(CHARACTERS))})")
    return json.loads(json.dumps(CHARACTERS[name]))


def apply(name: str | None, palette: dict, host_look: dict) -> dict | None:
    """Swap the theme's values into the renderer's palette and guide look (in place, for this render process).
    -> the theme (None for the default look). An unknown name is an error, never a silent default."""
    if not name or name == "kindled":
        return None
    if name not in THEMES:
        raise SystemExit(f"FAIL: unknown theme {name!r} (known: {', '.join(sorted(THEMES))})")
    t = THEMES[name]
    palette.update(t["palette"])
    host_look["colors"] = {**host_look.get("colors", {}), **t["host_colors"]}
    return t
