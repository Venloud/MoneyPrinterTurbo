"""Guide actions: what the planner may ask the guide to act out, mapped onto the existing rig (runtime.js events).

The guide-action reference images in the private library (movie_reference/guide_actions/, show: false) are never
shown on screen: the approved guide performs the action himself. Each action is one of:
  supported    the rig performs it fully
  partial      the rig performs the core of it; what it cannot do is said in 'cannot'
  unsupported  the rig cannot do it without faking it: the plan's request is reported (guide_actions.json) and
               the guide only looks at the drawing instead
An action with "points" waits until its drawing is on screen; the others land on their own word.
rig(name, ctx) -> [(seconds after the action word, event)], or None when it does not fit here (no room for the
arms, or nothing to point at): the compiler then uses the plain look-up.
"""
from __future__ import annotations

ACTIONS = {
    "point": {"status": "supported", "does": "points at the drawing being named"},
    "shrug": {"status": "supported", "does": "shrugs (a question)"},
    "present": {"status": "supported", "does": "opens both hands toward the board"},
    "look": {"status": "supported", "does": "looks up at the board"},
    "wave": {"status": "supported", "does": "waves"},
    "none": {"status": "supported", "does": "nothing new"},
    "think": {"status": "supported", "does": "looks up, thinking, head tilted"},
    "realize": {"status": "supported", "does": "a double take: 'wait what', then mind blown", "reference": "realize"},
    "confused": {"status": "supported", "does": "shrugs with a confused face (falls back to a puzzled head tilt)"},
    "celebrate": {"status": "supported", "does": "both arms up, hops (good news)"},
    "point_explain": {"status": "supported", "does": "points at the drawing while explaining it", "points": True},
    "choose_path": {"status": "partial", "does": "turns to one option, then the other, then points at the drawing",
                    "cannot": "walk down a path", "reference": "choose_path", "points": True},
    "frustrated_at_screen": {"status": "partial", "does": "shakes his head at the drawing, then a side-eye",
                             "cannot": "hold or type on a screen (no computer prop in his hands)",
                             "reference": "frustrated_at_screen"},
    "help_up": {"status": "unsupported", "cannot": "grab and lift a second figure (the rig has no two-character "
                "contact or pulling motion)", "reference": "help_up"},
    "carry": {"status": "unsupported", "cannot": "hold an object (his hands are drawn empty)"},
}
ACTED = {n for n, a in ACTIONS.items() if a["status"] != "unsupported"}
UNSUPPORTED = {n for n, a in ACTIONS.items() if a["status"] == "unsupported"}


def for_prompt() -> list[str]:
    """The planner's list: what each usable action looks like."""
    out = []
    for n, a in ACTIONS.items():
        if a["status"] == "unsupported" or n == "none":
            continue
        out.append(f"{n}: {a['does']}" + (f" (cannot {a['cannot']})" if a.get("cannot") else ""))
    return out


def rig(name: str, ctx: dict) -> list[tuple[float, dict]] | None:
    """ctx: expression (the line's), room (bool: both arms can go out without touching a drawing or leaving the
    safe box), target (drawing id or None), can_point (bool: the arm tip lands clear of everything)."""
    g, ex = {"who": "guide"}, ctx.get("expression")
    if name == "think":
        return [(0.0, {"do": "look", "dir": "up", "expression": "thinking", "hold": 1.2, **g})]
    if name == "realize":
        return [(0.0, {"do": "express", "expression": "wait_what", **g}),
                (0.45, {"do": "look", "dir": "up", "expression": "mind_blown", "hold": 1.0, **g})]
    if name == "confused":
        if ctx.get("room"):
            return [(0.0, {"do": "shrug", "hold": 1.2, **g}), (0.05, {"do": "express", "expression": "confused_math", **g})]
        return [(0.0, {"do": "look", "dir": "up", "expression": "puzzled", "hold": 1.2, **g})]
    if name == "celebrate":
        if not ctx.get("room"):
            return None
        return [(0.0, {"do": "cheer", "hold": 1.2, **g})]
    if name == "point_explain":
        if not (ctx.get("target") and ctx.get("can_point")):
            return None
        return [(0.0, {"do": "point", "toward": ctx["target"], "hold": 0.9, "respond": False, "expression": "speaking", **g})]
    if name == "choose_path":
        steps = [(0.0, {"do": "face", "facing": -1, **g}), (0.0, {"do": "express", "expression": "thinking", **g}),
                 (0.5, {"do": "face", "facing": 1, **g})]
        if ctx.get("target") and ctx.get("can_point"):
            return steps + [(1.0, {"do": "point", "toward": ctx["target"], "hold": 0.6, "respond": False, **g})]
        return steps + [(1.0, {"do": "look", "dir": "up", "expression": ex or "thinking", "hold": 0.6, **g})]
    if name == "frustrated_at_screen":
        return [(0.0, {"do": "shake", **g}), (0.9, {"do": "express", "expression": "side_eye", **g})]
    return None


def span(events: list[tuple[float, dict]]) -> float:
    """How long the acted moment lasts (start of the last step + its hold)."""
    return max(dt + (e.get("hold") or 0.9) for dt, e in events) if events else 0.0
