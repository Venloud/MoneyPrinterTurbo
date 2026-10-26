"""The doodle library: reusable hand-drawn illustrations in the channel style, built ONCE into library.json.

    python -m kindled_iron.doodles.build          # writes kindled_iron/doodles/library.json (then regenerate catalog)

Each doodle is drawn around (0, 0) at about 360 x 340 px (bigger than any slot, so it is never blown up), from
ink strokes (round caps, 7-9 px) with flat palette fills (the runtime colours them in after the ink, slightly
off-register), orange (accent) and blue (water / waterLine) highlights. The runtime's `doodle` primitive draws
any of them with the same stroke-by-stroke pencil reveal as the built-in drawings.

Per doodle: tags (what it can stand for: the director picks by tag / meaning) and named label slots
({slot: [x, y, size, colour, width]}): the director fills them with short words from the script (labels only, never sentences).
Faith rules: no occult imagery, no eyes as symbols, God is never drawn as a figure.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parent / "library.json"
LIB: dict[str, dict] = {}


def P(d: str, w: float = 7, c: str | None = None, fill: str | None = None, fo: float | None = None) -> list:
    st = {"w": w}
    if c:
        st["c"] = c
    if fill:
        st["fill"] = fill
        st["fo"] = 1 if fo is None else fo
    return [d, st]


def n(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def rect(x, y, w, h, r=0) -> str:
    if not r:
        return f"M{n(x)},{n(y)} L{n(x + w)},{n(y)} L{n(x + w)},{n(y + h)} L{n(x)},{n(y + h)} Z"
    return (f"M{n(x + r)},{n(y)} L{n(x + w - r)},{n(y)} Q{n(x + w)},{n(y)} {n(x + w)},{n(y + r)} L{n(x + w)},{n(y + h - r)} "
            f"Q{n(x + w)},{n(y + h)} {n(x + w - r)},{n(y + h)} L{n(x + r)},{n(y + h)} Q{n(x)},{n(y + h)} {n(x)},{n(y + h - r)} "
            f"L{n(x)},{n(y + r)} Q{n(x)},{n(y)} {n(x + r)},{n(y)} Z")


def circ(cx, cy, r, wob=0.0, seed=1) -> str:
    """A circle; wob > 0 makes it slightly uneven (hand-drawn)."""
    if not wob:
        return f"M{n(cx - r)},{n(cy)} a{n(r)},{n(r)} 0 1,0 {n(2 * r)},0 a{n(r)},{n(r)} 0 1,0 {n(-2 * r)},0"
    pts = []
    for i in range(17):
        a = i / 16 * 2 * math.pi + 0.3
        rr = r * (1 + (0 if i == 16 else math.sin(seed * 7.1 + i * 2.3) * wob))
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    return poly(pts, close=True)


def ell(cx, cy, rx, ry) -> str:
    return f"M{n(cx - rx)},{n(cy)} a{n(rx)},{n(ry)} 0 1,0 {n(2 * rx)},0 a{n(rx)},{n(ry)} 0 1,0 {n(-2 * rx)},0"


def poly(pts, close=False) -> str:
    return "M" + " L".join(f"{n(x)},{n(y)}" for x, y in pts) + (" Z" if close else "")


def line(*xy) -> str:
    return poly(list(zip(xy[::2], xy[1::2])))


def star(cx, cy, r1, r2, k=5, rot=-90) -> str:
    pts = []
    for i in range(2 * k):
        a = math.radians(rot + i * 180 / k)
        r = r1 if i % 2 == 0 else r2
        pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
    return poly(pts, close=True)


def doodle(name: str, tags: list[str], doc: str, parts: list, labels: dict | None = None) -> None:
    assert name not in LIB, name
    assert len(parts) >= 3, f"{name}: a doodle needs at least 3 strokes"
    LIB[name] = {"tags": tags, "doc": doc, "parts": parts, "slots": labels or {"label": [0, 205, 34]}}


# ======================================================================= money / possessions
doodle("money", ["money", "cash", "dollar", "wealth", "rich", "pay", "price", "greed", "bills"],
       "a stack of dollar bills with a $ on top",
       [P(rect(-150, 10, 300, 90, 12), fill="green", fo=0.9), P(rect(-140, -30, 300, 90, 12), fill="green", fo=0.95),
        P(rect(-130, -70, 300, 90, 12), fill="green"), P(ell(20, -25, 32, 32), c="greenLine", w=6),
        P("M30,-45 C10,-52 0,-38 14,-30 C30,-22 30,-6 10,-8 M20,-58 L20,8", w=6, c="greenLine")])
doodle("coin_pile", ["coins", "money", "change", "savings", "pennies", "small amount"],
       "a pile of gold coins",
       [P(ell(-60, 60, 80, 26), fill="starFill"), P(ell(50, 40, 80, 26), fill="starFill"), P(ell(-10, 0, 80, 26), fill="starFill"),
        P(ell(0, -60, 80, 26), fill="starFill"), P("M-80,-60 L-80,-40 C-80,-25 80,-25 80,-40 L80,-60", w=7),
        P("M-15,-70 L15,-50", c="accent", w=5)])
doodle("money_bag", ["money bag", "riches", "greed", "treasure", "bank", "wealth", "fortune"],
       "a bulging money bag tied with a rope, $ on it",
       [P("M-40,-120 C-20,-100 20,-100 40,-120 L20,-80 C130,-40 150,120 0,130 C-150,120 -130,-40 -20,-80 Z", fill="trunk", fo=0.55),
        P("M-30,-85 C-10,-75 10,-75 30,-85", c="accent", w=9), P("M15,-10 C-20,-25 -35,10 0,20 C35,30 25,70 -15,55 M0,-30 L0,75", w=8, c="accent")],
       {"label": [0, 185, 34], "on": [0, 100, 28]})
doodle("credit_card", ["credit card", "debt", "card", "buy", "spend", "payment", "loan"],
       "a credit card with a chip",
       [P(rect(-170, -105, 340, 210, 22), fill="water", fo=0.9), P(rect(-125, -45, 60, 45, 6), fill="starFill"),
        P(line(-170, -70, 170, -70), w=14), P(line(-120, 50, -40, 50, -20, 50), w=6), P(line(10, 50, 110, 50), w=6)],
       {"label": [0, 165, 34], "on": [60, 0, 26]})
doodle("piggy_bank", ["piggy bank", "savings", "save", "budget", "money"],
       "a piggy bank with a coin going in",
       [P("M-120,20 C-120,-80 100,-90 120,0 C130,60 80,95 30,95 L-60,95 C-110,90 -125,60 -120,20 Z", fill="marker"),
        P("M-60,95 L-60,125 M60,95 L60,125", w=9), P(ell(130, 10, 18, 22), fill="marker"), P(line(-20, -65, 30, -65), w=8),
        P(ell(5, -115, 26, 26), fill="starFill"), P(circ(70, -15, 5), w=6)])
doodle("diamond", ["diamond", "jewel", "valuable", "precious", "treasure", "worth"],
       "a cut diamond",
       [P("M-120,-40 L-70,-110 L70,-110 L120,-40 L0,120 Z", fill="water", fo=0.85), P(line(-120, -40, 120, -40), w=6),
        P("M-70,-110 L-35,-40 L0,120 L35,-40 L70,-110 M-35,-40 L0,-110 L35,-40", w=5, c="waterLine")])
doodle("gold_bars", ["gold", "gold bars", "wealth", "treasure", "riches", "vault"],
       "three stacked gold bars",
       [P("M-160,60 L-130,0 L-10,0 L20,60 Z", fill="starFill"), P("M-20,60 L10,0 L130,0 L160,60 Z", fill="starFill"),
        P("M-90,0 L-60,-60 L60,-60 L90,0 Z", fill="starFill"), P(line(-160, 60, 160, 60), w=8),
        P("M-40,-40 L-10,-20 M40,-45 L60,-30", c="accent", w=5)])
doodle("receipt", ["receipt", "bill", "cost", "invoice", "list", "pay"],
       "a long paper receipt",
       [P("M-90,-150 L90,-150 L90,140 L70,125 L50,140 L30,125 L10,140 L-10,125 L-30,140 L-50,125 L-70,140 L-90,125 Z", fill="page"),
        P(line(-60, -100, 40, -100), w=6), P(line(-60, -60, 60, -60), w=6), P(line(-60, -20, 20, -20), w=6),
        P(line(-60, 40, 60, 40), w=9, c="accent")], {"label": [0, 190, 34], "on": [0, 85, 28]})
# ======================================================================= tech / home objects
doodle("phone", ["phone", "smartphone", "social media", "screen", "scroll", "text message", "call", "notifications"],
       "a smartphone with app squares on the screen",
       [P(rect(-85, -165, 170, 330, 26), fill="inkSoft", fo=0.25), P(rect(-68, -135, 136, 250, 8), fill="water", fo=0.8),
        P(rect(-50, -115, 40, 40, 8), c="accent", w=5, fill="marker"), P(rect(10, -115, 40, 40, 8), w=5, fill="green"),
        P(rect(-50, -55, 40, 40, 8), w=5, fill="starFill"), P(circ(0, 140, 10), w=6)], {"label": [0, 215, 34], "screen": [0, 40, 24]})
doodle("laptop", ["laptop", "computer", "work", "internet", "online", "screen", "study"],
       "an open laptop",
       [P(rect(-140, -130, 280, 175, 12), fill="inkSoft", fo=0.2), P(rect(-120, -112, 240, 140, 6), fill="water", fo=0.8),
        P("M-175,60 L175,60 L150,95 L-150,95 Z", fill="controller"), P(line(-35, 78, 35, 78), w=6)],
       {"label": [0, 150, 34], "screen": [0, -42, 26]})
doodle("tv", ["tv", "television", "news", "media", "screen", "show", "entertainment"],
       "an old TV with antennas",
       [P(rect(-160, -90, 320, 210, 24), fill="trunk", fo=0.45), P(rect(-135, -68, 210, 165, 14), fill="water", fo=0.85),
        P("M-60,-90 L-110,-160 M40,-90 L90,-165", w=7), P(circ(115, -30, 13), w=6), P(circ(115, 25, 13), w=6)],
       {"label": [0, 175, 34], "screen": [-30, 15, 26]})
doodle("lightbulb", ["lightbulb", "idea", "realize", "understand", "insight", "think", "invention", "aha"],
       "a glowing lightbulb with rays",
       [P("M-55,40 C-110,-10 -100,-130 0,-130 C100,-130 110,-10 55,40 L50,80 L-50,80 Z", fill="starFill"),
        P(rect(-45, 80, 90, 45, 10), fill="controller"), P(line(-45, 102, 45, 102), w=5),
        P("M-25,40 L-15,-30 L0,0 L15,-30 L25,40", c="accent", w=6), P("M-150,-60 L-120,-55 M150,-60 L120,-55 M0,-175 L0,-150 M-105,-150 L-85,-125 M105,-150 L85,-125", c="accent", w=7)])
doodle("clock_wall", ["clock", "time", "hour", "late", "waiting", "deadline", "minutes", "how long"],
       "a round wall clock",
       [P(circ(0, 0, 140, 0.02, 3), w=9, fill="page"), P(circ(0, 0, 8), w=8), P(line(0, 0, 0, -95), w=9),
        P(line(0, 0, 65, 35), w=8, c="accent"), P("M0,-120 L0,-105 M120,0 L105,0 M0,120 L0,105 M-120,0 L-105,0", w=7)])
doodle("hourglass", ["hourglass", "time", "running out", "patience", "waiting", "eternity", "life short"],
       "an hourglass with sand running down",
       [P(line(-110, -150, 110, -150), w=12), P(line(-110, 150, 110, 150), w=12),
        P("M-85,-150 C-85,-40 -15,-30 -15,0 C-15,30 -85,40 -85,150 M85,-150 C85,-40 15,-30 15,0 C15,30 85,40 85,150", w=8),
        P("M-60,-110 L60,-110 C40,-60 10,-40 0,-15 C-10,-40 -40,-60 -60,-110 Z", w=4, c="trunk", fill="starFill"),
        P("M0,-15 L0,110 M-65,140 C-40,90 40,90 65,140 Z", w=4, c="trunk", fill="starFill")])
doodle("calendar", ["calendar", "day", "date", "week", "schedule", "plan", "sabbath", "rest day"],
       "a calendar page with one day circled",
       [P(rect(-150, -130, 300, 260, 14), fill="page"), P(rect(-150, -130, 300, 60, 14), fill="accent", fo=0.85),
        P("M-90,-150 L-90,-110 M90,-150 L90,-110", w=10),
        P("M-110,-30 L110,-30 M-110,20 L110,20 M-110,70 L110,70 M-55,-55 L-55,110 M0,-55 L0,110 M55,-55 L55,110", w=4, c="inkSoft"),
        P(circ(28, 45, 32), w=7, c="accent")], {"label": [0, 190, 34], "top": [0, -100, 30]})
doodle("car", ["car", "drive", "travel", "commute", "road trip", "vehicle", "accident"],
       "a little car side view",
       [P("M-170,40 L-170,-5 C-160,-25 -120,-30 -100,-30 L-60,-85 L60,-85 L105,-30 C150,-28 170,-15 170,10 L170,40 Z", fill="accent", fo=0.75),
        P("M-48,-72 L-75,-32 L-5,-32 L-5,-72 Z M10,-72 L10,-32 L85,-32 L52,-72 Z", w=5, fill="water", fo=0.9),
        P(circ(-95, 45, 36), w=8, fill="inkSoft", fo=0.8), P(circ(95, 45, 36), w=8, fill="inkSoft", fo=0.8), P(circ(-95, 45, 10), w=5)])
doodle("house_big", ["house", "home", "family home", "mortgage", "rent", "household"],
       "a house with a roof, door, windows and chimney",
       [P("M-160,-20 L0,-150 L160,-20", w=10, c="accent"), P(rect(-130, -35, 260, 170, 4), fill="page"),
        P(rect(85, -130, 30, 60), fill="trunk", fo=0.8), P(rect(-25, 50, 50, 85, 4), fill="trunk", fo=0.7),
        P(rect(-105, 0, 60, 50), w=6, c="waterLine", fill="water"), P(rect(45, 0, 60, 50), w=6, c="waterLine", fill="water")])
doodle("door", ["door", "opportunity", "open door", "way in", "choice", "enter", "closed"],
       "a door, slightly open, light coming out",
       [P(rect(-95, -165, 190, 330, 6), fill="trunk", fo=0.6), P("M-95,-165 L40,-140 L40,190 L-95,165", w=8, fill="page"),
        P(circ(20, 20, 9), w=6), P("M60,-120 L150,-150 M60,0 L160,0 M60,120 L150,150", c="starFill", w=8)],
       {"label": [0, 235, 34]})
doodle("key", ["key", "answer", "unlock", "secret", "solution", "access", "freedom"],
       "an old key",
       [P(circ(-105, 0, 60, 0.03, 2), w=9, fill="starFill"), P(circ(-105, 0, 22), w=7),
        P("M-45,0 L160,0 M110,0 L110,45 M145,0 L145,35", w=12), P("M70,-10 L150,-10", c="accent", w=4)])
doodle("lock", ["lock", "locked", "trapped", "security", "closed", "can't", "protect"],
       "a padlock",
       [P("M-70,-20 L-70,-80 C-70,-170 70,-170 70,-80 L70,-20", w=14), P(rect(-115, -25, 230, 175, 22), fill="starFill"),
        P(circ(0, 45, 18), w=7, fill="ink"), P(line(0, 55, 0, 100), w=10)])
doodle("chain", ["chain", "chains", "slavery", "bondage", "addiction", "trapped", "sin", "bound"],
       "a heavy chain of links",
       [P(ell(-120, 0, 55, 32), w=12, c="inkSoft"), P(ell(-40, 0, 55, 32), w=12), P(ell(40, 0, 55, 32), w=12, c="inkSoft"),
        P(ell(120, 0, 55, 32), w=12), P("M-150,-12 L-100,-12 M10,-12 L60,-12", c="cloud", w=4)])
doodle("broken_chain", ["broken chain", "freedom", "free", "set free", "breaking free", "deliverance", "redeemed"],
       "a chain snapped in the middle with a spark",
       [P(ell(-140, 20, 50, 30), w=12), P("M-95,10 C-60,-10 -40,5 -30,25 C-40,45 -70,50 -95,35", w=12, c="inkSoft"),
        P("M95,-10 C60,-30 40,-15 30,5 C40,25 70,30 95,15", w=12, c="inkSoft"), P(ell(140, 0, 50, 30), w=12),
        P("M0,-20 L-10,-70 M15,-15 L40,-60 M-15,0 L-55,-30", c="accent", w=7)])
doodle("ladder", ["ladder", "climb", "success", "progress", "step by step", "career", "rise"],
       "a ladder leaning up",
       [P("M-80,170 L-20,-170 M80,170 L120,-170", w=10, c="trunk"),
        P("M-70,120 L85,120 M-58,60 L92,60 M-46,0 L100,0 M-34,-60 L106,-60 M-22,-120 L113,-120", w=8),
        P("M-110,175 L130,175", w=6, c="inkSoft")])
doodle("bridge", ["bridge", "connection", "gap", "cross over", "reconcile", "link", "path"],
       "an arched bridge over water",
       [P("M-180,20 C-90,-90 90,-90 180,20", w=10, c="trunk"), P("M-180,-20 L180,-20", w=8),
        P("M-120,-20 L-120,-35 M-60,-20 L-60,-60 M0,-20 L0,-68 M60,-20 L60,-60 M120,-20 L120,-35", w=6),
        P("M-180,80 C-140,65 -100,95 -60,80 C-20,65 20,95 60,80 C100,65 140,95 180,80", w=6, c="waterLine")])
doodle("road_fork", ["fork in the road", "choice", "decision", "two paths", "choose", "free will", "crossroads", "options"],
       "a road splitting into two paths",
       [P("M-60,170 L-25,40 L-160,-140 L-95,-140 L0,-25 L95,-140 L160,-140 L25,40 L60,170 Z", w=8, fill="page"),
        P("M0,160 L0,120 M0,90 L0,55 M-55,-70 L-75,-95 M55,-70 L75,-95", w=7, c="starFill"),
        P("M-180,175 L-70,175 M70,175 L180,175", w=6, c="greenLine")],
       {"left": [-128, -175, 24], "right": [128, -175, 24], "label": [0, 215, 34]})
doodle("mountain", ["mountain", "obstacle", "challenge", "goal", "summit", "hard", "faith moves mountains"],
       "a mountain with a snowy peak and a flag",
       [P("M-180,140 L-40,-110 L40,10 L80,-40 L180,140 Z", fill="woolGray", fo=0.6),
        P("M-75,-50 L-40,-110 L-5,-50 L-25,-60 L-40,-45 L-55,-60 Z", w=6, fill="cloud"), P("M-40,-110 L-40,-170", w=6),
        P("M-40,-170 L10,-155 L-40,-140", c="accent", w=6, fill="accent", fo=0.9)])
doodle("wooden_cross", ["cross", "jesus", "faith", "christ", "salvation", "church", "christian", "gospel", "crucifixion", "sacrifice"],
       "a simple wooden cross with light behind it",
       [P("M-150,-40 L-170,-60 M150,-40 L170,-60 M-110,-150 L-130,-175 M110,-150 L130,-175 M0,-190 L0,-215", c="starFill", w=8),
        P(rect(-24, -170, 48, 330, 4), fill="trunk", fo=0.85), P(rect(-110, -100, 220, 46, 4), fill="trunk", fo=0.85),
        P("M-60,160 L60,160", w=6, c="inkSoft")], {"label": [0, 205, 34]})
doodle("bible", ["bible", "scripture", "word of god", "book", "verse", "gospel", "god's word", "holy book"],
       "a closed Bible with a cross on the cover",
       [P(rect(-115, -150, 230, 300, 12), fill="trunk", fo=0.8), P(rect(-95, -150, 210, 300, 10), w=4, c="robeDark"),
        P("M0,-95 L0,25 M-40,-55 L40,-55", c="starFill", w=10), P("M115,-140 L130,-130 L130,155 L-100,160", w=5, c="inkSoft")],
       {"label": [0, 205, 34], "on": [0, 95, 24]})
doodle("church", ["church", "worship", "congregation", "faith", "sunday", "believers"],
       "a small church with a steeple and a cross",
       [P("M-110,-10 L0,-90 L110,-10", w=9, c="accent"), P(rect(-95, -15, 190, 150, 4), fill="page"),
        P("M-30,-75 L0,-130 L30,-75", w=7, fill="page"), P("M0,-130 L0,-185 M-20,-165 L20,-165", w=7),
        P("M-25,135 L-25,70 C-25,40 25,40 25,70 L25,135", w=6, fill="trunk", fo=0.7), P(circ(-55, 30, 16), w=5, c="waterLine", fill="water")])
doodle("praying_hands", ["prayer", "pray", "praying", "ask god", "worship", "faith", "thank"],
       "two hands pressed together in prayer",
       [P("M-8,-150 C-40,-120 -80,-30 -80,40 L-60,120 L-5,120 L-5,-130 Z", fill="skin"),
        P("M8,-150 C40,-120 80,-30 80,40 L60,120 L5,120 L5,-130 Z", fill="skin"),
        P("M-60,120 L-75,165 L75,165 L60,120", w=7, fill="water", fo=0.8), P("M-55,-20 L-25,-10 M55,-20 L25,-10", w=5, c="inkSoft")])
doodle("dove", ["dove", "peace", "holy spirit", "hope", "spirit", "gentle"],
       "a white dove flying with an olive branch",
       [P("M-150,10 C-100,-20 -40,-10 0,10 C40,-10 120,-40 160,-20 C120,20 60,60 0,50 C-60,60 -120,40 -150,10 Z", fill="cloud"),
        P("M-30,0 C-40,-80 0,-140 60,-150 C40,-90 30,-40 20,5", w=7, fill="cloud"),
        P("M160,-20 L190,-15 L160,-5", w=6, c="accent"), P("M175,-10 C190,20 200,40 210,60 M190,25 L215,20 M200,45 L180,55", w=5, c="greenLine"),
        P(circ(140, -18, 4), w=6)])
doodle("crown", ["crown", "king", "kingdom", "royal", "power", "rule", "authority", "reign", "glory"],
       "a royal crown with jewels",
       [P("M-150,80 L-170,-90 L-80,-10 L0,-130 L80,-10 L170,-90 L150,80 Z", fill="starFill"),
        P(rect(-155, 80, 310, 45, 8), fill="starFill"), P(circ(0, 100, 14), c="accent", w=6, fill="accent"),
        P(circ(-90, 100, 11), c="waterLine", w=6, fill="water"), P(circ(90, 100, 11), c="waterLine", w=6, fill="water")])
doodle("throne", ["throne", "king", "reign", "authority", "seat", "power", "sovereign"],
       "an empty royal throne",
       [P("M-80,-160 L80,-160 L80,30 L-80,30 Z", fill="accent", fo=0.6), P(rect(-120, 20, 240, 50, 10), fill="trunk", fo=0.8),
        P("M-110,70 L-110,160 M110,70 L110,160", w=12, c="trunk"), P("M-80,-160 L-60,-195 L-30,-165 L0,-200 L30,-165 L60,-195 L80,-160", c="starFill", w=8)])
doodle("trophy", ["trophy", "win", "winner", "success", "victory", "prize", "achievement", "reward"],
       "a winner's cup",
       [P("M-90,-140 L90,-140 C90,-30 50,20 0,25 C-50,20 -90,-30 -90,-140 Z", fill="starFill"),
        P("M-90,-110 C-150,-110 -150,-30 -70,-25 M90,-110 C150,-110 150,-30 70,-25", w=8),
        P("M0,25 L0,80 M-60,80 L60,80 L70,130 L-70,130 Z", w=8, fill="trunk", fo=0.7), P("M-40,-110 L-35,-60", c="cloud", w=6)],
       {"label": [0, 185, 34], "on": [0, 106, 22]})
doodle("medal", ["medal", "award", "first place", "honor", "achievement", "prize"],
       "a medal on a ribbon",
       [P("M-60,-170 L-10,-40 M60,-170 L10,-40", w=26, c="waterLine"), P(circ(0, 40, 85, 0.02, 4), w=8, fill="starFill"),
        P(star(0, 40, 45, 20), w=6, c="accent")], {"label": [0, 175, 34], "on": [0, 40, 30]})
doodle("gift", ["gift", "present", "grace", "free gift", "give", "generosity", "blessing"],
       "a wrapped gift box with a bow",
       [P(rect(-130, -40, 260, 180, 6), fill="accent", fo=0.75), P(rect(-150, -85, 300, 55, 6), fill="accent", fo=0.9),
        P("M-18,-85 L-18,140 M18,-85 L18,140", w=8, c="starFill"),
        P("M0,-85 C-60,-160 -120,-110 -50,-85 M0,-85 C60,-160 120,-110 50,-85", w=8)])
doodle("cup", ["cup", "drink", "coffee", "tea", "morning", "communion"],
       "a steaming mug",
       [P("M-100,-60 L100,-60 L85,120 C80,140 -80,140 -85,120 Z", fill="water", fo=0.85),
        P("M100,-20 C170,-20 170,70 90,75", w=10), P("M-50,-90 C-70,-120 -30,-140 -50,-170 M0,-90 C-20,-120 20,-140 0,-170 M50,-90 C30,-120 70,-140 50,-170", w=6, c="inkSoft"),
        P(ell(0, -60, 100, 16), w=6)])
doodle("bread", ["bread", "food", "daily bread", "provision", "hunger", "meal", "loaf"],
       "a loaf of bread with slashes on top",
       [P("M-170,40 C-170,-70 170,-70 170,40 C170,80 -170,80 -170,40 Z", fill="trunk", fo=0.6),
        P("M-90,-30 L-60,10 M-20,-45 L10,0 M50,-40 L80,5", w=7, c="robeDark"), P(ell(0, 95, 160, 15), w=4, c="shadow", fill="shadow", fo=0.7)])
doodle("chair_big", ["chair", "sit", "rest", "waiting", "empty chair", "alone"],
       "a wooden chair",
       [P("M-80,-170 L-80,50 M80,-170 L80,50", w=10, c="trunk"), P("M-80,-140 L80,-140 M-80,-90 L80,-90", w=8, c="trunk"),
        P(rect(-100, 30, 200, 35, 6), fill="trunk", fo=0.8), P("M-90,65 L-100,170 M90,65 L100,170 M-55,65 L-50,140 M55,65 L50,140", w=9, c="trunk")])
doodle("mirror", ["mirror", "reflection", "self", "identity", "look at yourself", "vanity", "honest"],
       "an oval hand mirror with a shine",
       [P(ell(0, -50, 100, 130), w=12, c="trunk"), P(ell(0, -50, 82, 112), w=5, fill="water", fo=0.7),
        P("M-40,-120 L-10,-150 M-50,-80 L10,-140", w=7, c="cloud"), P("M0,80 L0,175", w=22, c="trunk")])
doodle("mask", ["mask", "pretend", "hide", "fake", "hypocrite", "identity", "theater", "two faces"],
       "a theater mask held on a stick",
       [P("M-120,-90 C-120,-140 120,-140 120,-90 C120,20 60,80 0,80 C-60,80 -120,20 -120,-90 Z", fill="page"),
        P("M-80,-55 C-60,-75 -30,-75 -20,-50 C-35,-40 -65,-40 -80,-55 Z M80,-55 C60,-75 30,-75 20,-50 C35,-40 65,-40 80,-55 Z", w=6, fill="ink"),
        P("M-50,20 C-20,45 20,45 50,20", w=7, c="accent"), P("M95,40 L150,175", w=10, c="trunk")])
doodle("shield", ["shield", "protection", "safe", "defend", "faith", "armor", "guard", "security"],
       "a knight's shield with a cross",
       [P("M0,-160 L130,-115 C130,20 80,110 0,160 C-80,110 -130,20 -130,-115 Z", fill="water", fo=0.85),
        P("M0,-160 L0,160 M-128,-30 L128,-30", w=9, c="starFill"), P("M0,-135 L105,-98", w=5, c="cloud")])
doodle("sword", ["sword", "fight", "battle", "war", "word of god", "conflict", "weapon"],
       "a sword pointing up",
       [P("M0,-185 L22,-150 L22,80 L-22,80 L-22,-150 Z", fill="controller"), P(rect(-85, 80, 170, 26, 10), fill="trunk", fo=0.85),
        P(rect(-14, 106, 28, 70, 6), fill="robeDark"), P(circ(0, 186, 14), w=6, fill="starFill"), P(line(0, -150, 0, 60), w=4, c="inkSoft")],
       {"label": [0, 240, 34]})
doodle("hammer_big", ["hammer", "build", "work", "fix", "break", "carpenter", "judgment", "smash"],
       "a hammer",
       [P(rect(-25, -60, 50, 230, 12), fill="trunk", fo=0.85), P("M-120,-140 L90,-140 L120,-110 L120,-60 L-120,-60 C-150,-80 -150,-120 -120,-140 Z", fill="controller"),
        P(line(-110, -95, 100, -95), w=5, c="inkSoft"), P(line(-10, 0, -10, 150), w=4, c="robeDark")])
doodle("scales_big", ["justice", "fair", "balance", "judge", "weigh", "unfair", "law", "compare"],
       "balance scales of justice",
       [P("M0,-170 L0,150 M-80,150 L80,150", w=10, c="trunk"), P(line(-150, -120, 150, -120), w=8),
        P("M-150,-120 L-200,-20 M-150,-120 L-100,-20 M150,-120 L100,-20 M150,-120 L200,-20", w=4, c="inkSoft"),
        P("M-210,-20 Q-150,40 -90,-20 Z", fill="starFill"), P("M90,-20 Q150,40 210,-20 Z", fill="starFill"),
        P(circ(0, -170, 12), w=6, fill="accent")], {"left": [-150, 45, 26], "right": [150, 45, 26], "label": [0, 205, 34]})
doodle("gavel", ["gavel", "judge", "court", "verdict", "law", "judgment", "trial", "guilty"],
       "a judge's gavel striking its block",
       [P("M-160,-110 L-70,-160 L-30,-90 L-120,-40 Z", fill="trunk", fo=0.85), P("M-75,-100 L120,30", w=18, c="trunk"),
        P(rect(-150, 90, 220, 50, 10), fill="trunk", fo=0.7), P("M80,70 L110,40 M40,60 L45,25 M120,95 L160,90", c="accent", w=6)])
doodle("prison_bars", ["prison", "jail", "bars", "trapped", "captive", "locked up", "guilty", "sin"],
       "a barred prison window",
       [P(rect(-150, -150, 300, 300, 10), fill="woolGray", fo=0.45), P("M-90,-150 L-90,150 M-30,-150 L-30,150 M30,-150 L30,150 M90,-150 L90,150", w=11),
        P(line(-150, -40, 150, -40), w=9), P(rect(-150, -150, 300, 300, 10), w=8)])
# ======================================================================= nature / world
doodle("sun_big", ["sun", "day", "light", "warm", "morning", "summer", "joy", "creation"],
       "a smiling-free plain sun with rays",
       [P(circ(0, 0, 85, 0.03, 5), fill="starFill", c="accent", w=9),
        P(" ".join(f"M{n(math.cos(a) * 115)},{n(math.sin(a) * 115)} L{n(math.cos(a) * 165)},{n(math.sin(a) * 165)}" for a in [i * math.pi / 6 for i in range(12)]), c="accent", w=9),
        P("M-40,-30 C-30,-50 -10,-55 5,-55", w=6, c="cloud")])
doodle("moon_stars", ["night", "moon", "stars", "dark", "sleep", "evening"],
       "a crescent moon with stars",
       [P("M40,-150 C-90,-140 -120,50 20,120 C-60,40 -50,-90 40,-150 Z", fill="moon"),
        P(star(110, -70, 30, 13), w=6, fill="starFill"), P(star(90, 70, 22, 10), w=6, fill="starFill"), P(star(-120, -110, 18, 8), w=5, fill="starFill")])
doodle("starry_sky", ["stars", "universe", "sky", "heaven", "space", "galaxy", "countless", "promise"],
       "a sky full of stars",
       [P(star(-90, -60, 45, 19), w=7, fill="starFill"), P(star(70, -90, 35, 15), w=7, fill="starFill"), P(star(20, 60, 55, 23), w=7, fill="starFill"),
        P(star(-130, 90, 25, 11), w=6, fill="starFill"), P(star(140, 40, 22, 10), w=6, fill="starFill"), P(circ(-20, -130, 5) + " " + circ(150, -150, 5) + " " + circ(-160, 0, 5), w=6)])
doodle("planet_earth", ["earth", "world", "planet", "globe", "everyone", "nations", "creation"],
       "the planet Earth with continents",
       [P(circ(0, 0, 150, 0.02, 6), fill="water", c="waterLine", w=9),
        P("M-90,-90 C-40,-120 0,-90 -20,-50 C-40,-20 -90,-10 -110,-40 C-120,-60 -110,-80 -90,-90 Z", w=6, c="greenLine", fill="green"),
        P("M30,-20 C80,-40 120,0 100,50 C80,100 30,110 20,70 C10,40 -10,10 30,-20 Z", w=6, c="greenLine", fill="green"),
        P("M-80,70 C-60,60 -40,80 -55,100", w=6, c="greenLine")])
doodle("tree_big", ["tree", "life", "growth", "roots", "nature", "family tree", "garden", "eden"],
       "a big leafy tree",
       [P("M-22,170 L-16,20 L16,20 L22,170 Z", fill="trunk", fo=0.95), P("M-15,60 L-60,10 M15,40 L60,0", w=8, c="trunk"),
        P("M-20,30 C-150,40 -170,-90 -80,-120 C-80,-200 70,-210 80,-130 C170,-130 170,10 80,30 C50,50 10,45 -20,30 Z", fill="leaf", fo=0.95),
        P("M-80,-60 q15,-16 30,0 M20,-130 q15,-16 30,0 M50,-40 q15,-16 30,0", w=5, c="leafDark")])
doodle("seed_sprout", ["seed", "plant", "sprout", "grow", "small start", "faith like a mustard seed", "new life", "begin"],
       "a sprout growing from a seed in the soil",
       [P("M-170,80 C-90,60 90,60 170,80 L170,140 L-170,140 Z", fill="trunk", fo=0.55), P(ell(0, 95, 28, 18), w=6, fill="starFill"),
        P("M0,80 C0,20 -5,-40 0,-120", w=8, c="greenLine"), P("M0,-40 C-60,-50 -95,-90 -90,-130 C-40,-120 -10,-90 0,-40 Z", w=6, c="greenLine", fill="green"),
        P("M0,-80 C60,-90 95,-130 90,-170 C40,-160 10,-130 0,-80 Z", w=6, c="greenLine", fill="green")])
doodle("flower", ["flower", "beauty", "spring", "bloom", "grow", "gift", "life"],
       "a flower with petals and leaves",
       [P(" ".join(circ(math.cos(a) * 55, -60 + math.sin(a) * 55, 42) for a in [i * 2 * math.pi / 6 for i in range(6)]), w=6, c="accent", fill="marker"),
        P(circ(0, -60, 32), w=6, fill="starFill"), P("M0,-25 C0,40 -5,100 0,160", w=8, c="greenLine"),
        P("M0,80 C-60,60 -90,90 -100,120 C-50,125 -20,110 0,80 Z", w=6, c="greenLine", fill="green")])
doodle("fire", ["fire", "flame", "burn", "passion", "destruction", "trial", "anger", "hell", "heat"],
       "a campfire flame on logs",
       [P("M0,-170 C60,-100 120,-60 110,20 C100,90 50,110 0,110 C-50,110 -100,90 -110,20 C-120,-50 -40,-60 -30,-120 C-10,-90 -5,-60 0,-170 Z", c="accent", w=8, fill="accent", fo=0.6),
        P("M0,-40 C30,-10 55,20 45,55 C35,90 -35,90 -45,55 C-55,20 -20,0 0,-40 Z", c="accent", w=6, fill="starFill"),
        P("M-150,150 L130,100 M-130,100 L150,150", w=18, c="trunk")])
doodle("water_waves", ["water", "sea", "ocean", "flood", "waves", "baptism", "storm at sea", "drown"],
       "ocean waves",
       [P("M-180,-40 C-150,-90 -110,-90 -90,-40 C-70,-90 -30,-90 -10,-40 C10,-90 50,-90 70,-40 C90,-90 130,-90 160,-40 L180,-40 L180,140 L-180,140 Z", c="waterLine", w=8, fill="water"),
        P("M-170,30 C-140,0 -110,0 -90,30 C-70,0 -40,0 -20,30 C0,0 30,0 50,30 C70,0 100,0 130,30 C150,0 170,10 180,20", c="waterLine", w=6),
        P("M-140,-70 C-130,-80 -120,-80 -110,-70 M0,-75 C10,-85 20,-85 30,-75", c="cloud", w=5)])
doodle("water_drop", ["drop", "water", "tear", "thirst", "rain", "clean", "living water"],
       "a big water drop",
       [P("M0,-170 C60,-70 120,0 120,60 C120,130 65,170 0,170 C-65,170 -120,130 -120,60 C-120,0 -60,-70 0,-170 Z", c="waterLine", w=9, fill="water"),
        P("M-55,50 C-60,90 -35,120 -5,125", c="cloud", w=9), P("M30,-60 C45,-35 55,-15 60,10", c="cloud", w=6)])
doodle("rain_cloud", ["rain", "storm", "sad", "cloud", "gloomy", "trouble", "weather", "tears"],
       "a grey cloud with rain",
       [P("M-140,10 C-190,10 -190,-80 -120,-80 C-120,-150 -20,-160 0,-100 C30,-160 140,-150 130,-80 C190,-80 190,10 140,10 Z", fill="woolGray", fo=0.6),
        P("M-110,50 L-125,95 M-50,50 L-65,95 M10,50 L-5,95 M70,50 L55,95 M130,50 L115,95", c="waterLine", w=8),
        P("M-80,120 L-95,160 M-20,120 L-35,160 M40,120 L25,160 M100,120 L85,160", c="waterLine", w=8)])
doodle("storm", ["storm", "lightning", "thunder", "disaster", "chaos", "trouble", "danger", "power"],
       "a dark storm cloud with a lightning bolt",
       [P("M-140,-10 C-190,-10 -190,-100 -120,-100 C-120,-170 -20,-180 0,-120 C30,-180 140,-170 130,-100 C190,-100 190,-10 140,-10 Z", fill="inkSoft", fo=0.55),
        P("M10,-10 L-50,90 L5,90 L-30,180 L60,60 L5,60 L40,-10 Z", c="accent", w=7, fill="starFill"),
        P("M-120,30 L-135,70 M110,30 L95,70", c="waterLine", w=7)])
doodle("earthquake", ["earthquake", "crack", "disaster", "natural disaster", "shaking", "broken ground", "suffering", "destruction"],
       "cracked ground split open with falling rocks",
       [P("M-180,0 L-40,-10 L-10,20 L30,-15 L180,-5 L180,120 L-180,120 Z", fill="trunk", fo=0.5),
        P("M-40,-10 L-10,20 L-25,60 L10,95 L-5,120 M30,-15 L-10,20", w=9), P("M-140,-40 L-120,-30 M90,-50 L110,-35 M-60,-70 L-45,-55", w=7, c="inkSoft"),
        P(poly([(-120, -100), (-95, -120), (-75, -95), (-100, -75)], True) + " " + poly([(80, -110), (110, -125), (125, -95), (95, -80)], True), w=6, fill="woolGray")])
doodle("volcano", ["volcano", "eruption", "disaster", "anger", "explosion", "danger"],
       "a volcano erupting",
       [P("M-180,140 L-50,-60 L50,-60 L180,140 Z", fill="trunk", fo=0.6), P("M-50,-60 C-20,-40 20,-40 50,-60", w=6),
        P("M-30,-60 C-60,-110 -20,-150 0,-180 C20,-150 60,-110 30,-60", c="accent", w=8, fill="accent", fo=0.7),
        P("M-20,-50 C-40,0 -60,40 -70,80 M20,-50 C30,0 50,30 55,70", c="accent", w=9)])
doodle("desert", ["desert", "wilderness", "dry", "lonely", "wandering", "drought", "trial"],
       "a desert with dunes, a cactus and the sun",
       [P("M-180,80 C-100,20 -40,30 0,70 C60,20 130,10 180,60 L180,140 L-180,140 Z", fill="starFill", fo=0.7),
        P("M60,60 L60,-60 M60,-10 C30,-10 25,-30 25,-55 M60,-30 C90,-30 95,-50 95,-80", c="greenLine", w=14),
        P(circ(-110, -90, 40), c="accent", w=7, fill="starFill")])
doodle("garden", ["garden", "eden", "paradise", "creation", "plants", "growth", "beginning"],
       "a garden: flowers, grass and a tree",
       [P("M-180,90 C-90,70 90,70 180,90 L180,150 L-180,150 Z", fill="green"),
        P("M100,90 L100,-20 M100,-20 C20,-30 20,-130 100,-140 C180,-130 180,-30 100,-20 Z", w=7, c="greenLine", fill="leaf"),
        P("M-120,90 L-120,10 M-60,90 L-60,30", w=6, c="greenLine"), P(circ(-120, 0, 22) + " " + circ(-60, 20, 18), w=6, c="accent", fill="marker"),
        P("M-170,100 L-160,80 M-20,100 L-10,80 M30,100 L40,80", w=5, c="greenLine")])
doodle("rock", ["rock", "foundation", "firm", "solid", "strong", "stand", "unshakable"],
       "a big solid rock",
       [P("M-170,110 C-170,0 -110,-110 -10,-120 C100,-130 170,-30 170,110 Z", fill="woolGray", fo=0.7),
        P("M-90,-40 L-50,-10 M30,-80 L60,-40 L40,0 M90,20 L120,40", w=6, c="inkSoft"), P("M-190,115 L190,115", w=7)])
doodle("sand_castle", ["sand", "castle", "weak foundation", "temporary", "falls apart", "pride"],
       "a crumbling sand castle",
       [P("M-160,110 L-140,-20 L-100,-20 L-100,-60 L-60,-60 L-60,-20 L60,-20 L60,-80 L100,-80 L100,-20 L140,-20 L160,110 Z", fill="starFill", fo=0.7),
        P("M-60,-60 L-60,-90 L-40,-90 M100,-80 L100,-120 L120,-110", w=6), P(rect(-25, 30, 50, 80, 25), w=6, fill="trunk", fo=0.6),
        P("M120,60 L150,80 M140,20 L170,35", c="inkSoft", w=6)])
doodle("animal_lamb", ["lamb", "sheep", "innocent", "sacrifice", "flock", "gentle", "jesus lamb of god"],
       "a little woolly lamb",
       [P(circ(-10, 0, 110, 0.12, 7), fill="wool", c="inkSoft"), P(ell(110, -50, 50, 40), fill="wool", c="inkSoft"),
        P("M-60,100 L-60,160 M-10,105 L-10,165 M40,100 L40,160 M80,95 L85,150", w=10), P(circ(125, -55, 5), w=7),
        P("M95,-85 C80,-110 70,-90 85,-80", w=6)])
doodle("lion", ["lion", "strength", "courage", "king", "bold", "fearless", "pride"],
       "a lion's head with a big mane",
       [P(circ(0, 0, 150, 0.14, 8), fill="accent", fo=0.6, c="accent"), P(circ(0, 0, 95), fill="starFill"),
        P(circ(-35, -20, 8) + " " + circ(35, -20, 8), w=7), P("M-20,25 L20,25 L0,45 Z M0,45 L0,60 M-30,70 C-15,80 15,80 30,70", w=6)])
doodle("snake", ["snake", "serpent", "temptation", "lie", "deceive", "danger", "sin"],
       "a coiled snake with a forked tongue",
       [P("M-160,120 C-160,40 -40,60 -40,10 C-40,-40 -160,-40 -120,-100 C-90,-140 20,-150 60,-110", w=26, c="greenLine"),
        P("M-160,120 C-160,40 -40,60 -40,10 C-40,-40 -160,-40 -120,-100 C-90,-140 20,-150 60,-110", w=14, c="green"),
        P(ell(85, -110, 38, 26), fill="green", c="greenLine"), P("M120,-108 L160,-110 L175,-125 M160,-110 L175,-95", c="accent", w=5),
        P(circ(90, -120, 5), w=6)])
# ======================================================================= people / body
doodle("child", ["child", "kid", "children", "innocent", "boy", "girl", "young", "son", "daughter"],
       "a small child waving",
       [P(circ(0, -95, 50), fill="skin"), P("M-50,-110 C-40,-160 40,-160 50,-110", w=8, c="robeDark"),
        P("M-55,-30 L55,-30 L70,90 L-70,90 Z", fill="accent", fo=0.7), P("M55,-20 L110,-90 M-55,-20 L-95,40", w=9),
        P("M-30,90 L-30,165 M30,90 L30,165", w=10)], {"label": [0, 210, 34]})
doodle("family", ["family", "parents", "children", "home", "marriage", "together", "household", "love"],
       "a family: two parents and a child holding hands",
       [P(circ(-110, -110, 40) + " " + circ(110, -110, 40), fill="skin"), P(circ(0, -20, 30), fill="skin"),
        P("M-150,-60 L-70,-60 L-60,90 L-160,90 Z", fill="waterLine", fo=0.55), P("M70,-60 L150,-60 L165,90 L55,90 Z", fill="accent", fo=0.6),
        P("M-30,20 L30,20 L38,100 L-38,100 Z", fill="green", fo=0.8), P("M-65,0 L-30,40 M65,0 L30,40 M-130,90 L-130,160 M-90,90 L-90,160 M90,90 L90,160 M130,90 L130,160 M-15,100 L-15,150 M15,100 L15,150", w=8)])
doodle("crowd", ["crowd", "people", "everyone", "many", "society", "nations", "humanity", "world"],
       "a crowd of people",
       [P(" ".join(circ(x, -70 + (i % 2) * 20, 30) for i, x in enumerate(range(-140, 160, 70))), fill="skin", w=6),
        P(" ".join(rect(x - 30, -35 + (i % 2) * 20, 60, 140, 20) for i, x in enumerate(range(-140, 160, 70))), fill="waterLine", fo=0.45, w=6),
        P(" ".join(circ(x, -10, 26) for x in range(-105, 140, 70)), fill="skin", w=6),
        P(" ".join(rect(x - 28, 20, 56, 120, 18) for x in range(-105, 140, 70)), fill="accent", fo=0.5, w=6)])
doodle("thinker", ["think", "thinking", "wonder", "question", "philosopher", "doubt", "consider", "reason"],
       "a person sitting, chin on hand, thinking, with a thought bubble",
       [P(circ(-20, -60, 45), fill="skin"), P("M-70,-10 L40,-10 L50,110 L-80,110 Z", fill="waterLine", fo=0.5),
        P("M30,10 L35,-35 L5,-25", w=9), P(circ(90, -150, 40) + " " + circ(55, -95, 12) + " " + circ(40, -70, 7), w=6, fill="cloud"),
        P("M-80,110 L-90,170 M40,110 L60,170", w=10)], {"label": [0, 215, 34], "thought": [90, -150, 22]})
doodle("brain", ["brain", "mind", "think", "intelligence", "knowledge", "smart", "logic", "reason", "memory"],
       "a brain",
       [P("M-150,10 C-170,-80 -100,-140 -30,-130 C0,-160 80,-150 100,-110 C160,-110 180,-30 150,20 C170,80 100,130 40,110 C0,140 -80,130 -100,90 C-150,90 -175,50 -150,10 Z", fill="marker", c="accent"),
        P("M0,-125 C-20,-60 20,-20 0,40 C-10,70 10,100 20,115", w=6, c="accent"),
        P("M-110,-60 C-80,-50 -70,-20 -90,10 M-60,40 C-40,30 -30,60 -50,80 M60,-80 C90,-70 100,-40 80,-10 M70,40 C100,40 110,70 90,90", w=6, c="accent")])
doodle("heart_big", ["heart", "love", "care", "compassion", "feelings", "kindness", "god's love"],
       "a big heart",
       [P("M0,140 C-230,0 -150,-190 0,-80 C150,-190 230,0 0,140 Z", c="accent", w=10, fill="accent", fo=0.5),
        P("M-90,-70 C-70,-95 -40,-100 -20,-85", c="cloud", w=9), P("M60,-60 C80,-40 85,-10 75,15", c="cloud", w=7)],
       {"label": [0, 195, 34], "on": [0, 0, 30]})
doodle("broken_heart", ["broken heart", "hurt", "grief", "pain", "loss", "heartbreak", "sorrow", "betrayal"],
       "a heart broken in two",
       [P("M-10,140 C-230,0 -160,-190 -10,-80 L-30,-30 L5,10 L-25,60 Z", c="accent", w=9, fill="accent", fo=0.5),
        P("M20,140 C240,0 170,-190 20,-80 L0,-30 L35,10 L5,60 Z", c="accent", w=9, fill="accent", fo=0.5),
        P("M-10,-80 L-30,-30 L5,10 L-25,60 L-10,140 M20,-80 L0,-30 L35,10 L5,60 L20,140", w=7)])
doodle("tears", ["cry", "tears", "sad", "grief", "mourning", "sorrow", "weep", "pain"],
       "a sad face shedding tears",
       [P(circ(0, 0, 140, 0.03, 9), fill="skin"), P("M-75,-40 C-60,-25 -40,-25 -25,-40 M25,-40 C40,-25 60,-25 75,-40", w=8),
        P("M-60,85 C-30,55 30,55 60,85", w=8), P("M-55,-5 C-65,20 -75,40 -55,50 C-35,40 -45,20 -55,-5 Z M55,-5 C45,20 35,40 55,50 C75,40 65,20 55,-5 Z", c="waterLine", w=5, fill="water")])
doodle("smile_face", ["happy", "joy", "smile", "glad", "good news", "content", "hope"],
       "a big smiling face",
       [P(circ(0, 0, 140, 0.03, 10), fill="starFill"), P(circ(-50, -35, 12) + " " + circ(50, -35, 12), w=8, fill="ink"),
        P("M-80,30 C-40,100 40,100 80,30", w=10), P("M-110,10 C-100,20 -90,20 -85,15 M110,10 C100,20 90,20 85,15", c="accent", w=7)])
doodle("angry_face", ["angry", "anger", "mad", "rage", "frustrated", "wrath"],
       "an angry red face with steam",
       [P(circ(0, 0, 140, 0.03, 11), fill="accent", fo=0.45), P("M-85,-60 L-25,-35 M85,-60 L25,-35", w=10), P(circ(-50, -15, 10) + " " + circ(50, -15, 10), w=8, fill="ink"),
        P("M-60,75 C-30,50 30,50 60,75", w=9), P("M-140,-140 C-160,-170 -130,-190 -150,-215 M140,-140 C120,-170 150,-190 130,-215", w=7, c="inkSoft")])
doodle("hand_open", ["hand", "help", "give", "offer", "receive", "open hand", "generous", "stop"],
       "an open hand, palm out",
       [P("M-80,170 L-80,20 C-100,0 -130,-40 -110,-60 C-90,-70 -70,-40 -60,-20 L-60,-130 C-60,-160 -25,-160 -25,-130 L-25,-150 C-25,-180 10,-180 10,-150 L10,-140 C10,-170 45,-170 45,-140 L45,-120 C45,-145 80,-145 80,-120 L80,40 C80,100 40,130 40,170 Z", fill="skin"),
        P("M-25,-130 L-25,-40 M10,-140 L10,-40 M45,-120 L45,-40", w=5, c="inkSoft"), P("M-40,40 C-10,60 30,60 60,40", w=5, c="inkSoft")])
doodle("handshake", ["handshake", "agreement", "deal", "covenant", "promise", "partnership", "peace", "trust"],
       "two hands shaking",
       [P("M-180,-30 L-80,-40 L-20,-10 L40,-50 L180,-40 L180,60 L80,70 L20,100 C0,110 -20,100 -40,80 L-180,70 Z", fill="skin"),
        P("M-180,-30 L-110,-30 L-110,70 L-180,70 Z", fill="waterLine", fo=0.6), P("M180,-40 L110,-40 L110,60 L180,60 Z", fill="accent", fo=0.6),
        P("M-20,-10 C-10,20 20,20 40,0 M0,40 L40,40 M10,70 L45,65", w=6, c="inkSoft")])
doodle("footprints", ["footprints", "walk", "journey", "follow", "path", "steps", "follow jesus"],
       "a trail of footprints",
       [P(ell(-110, 110, 28, 45), fill="trunk", fo=0.5), P(ell(-30, 30, 28, 45), fill="trunk", fo=0.5), P(ell(50, -50, 28, 45), fill="trunk", fo=0.5),
        P(ell(130, -130, 28, 45), fill="trunk", fo=0.5), P(" ".join(circ(x, y, 8) for x, y in [(-120, 50), (-100, 48), (-40, -30), (-20, -32), (40, -110), (60, -112)]), w=5)])
doodle("person_tired", ["tired", "weary", "burden", "heavy", "exhausted", "stress", "struggle", "carry"],
       "a bent-over person carrying a heavy sack",
       [P(circ(-60, -40, 35), fill="skin"), P("M-40,-10 C0,0 30,20 40,70 L-20,90 C-30,50 -50,20 -40,-10 Z", fill="waterLine", fo=0.5),
        P(circ(40, -60, 85, 0.1, 12), fill="trunk", fo=0.6), P("M20,85 L10,170 M-10,85 L-40,170", w=10),
        P("M-30,10 L20,-20", w=8)])
doodle("runner", ["run", "race", "hurry", "busy", "chase", "escape", "fast", "rush"],
       "a person running",
       [P(circ(40, -130, 35), fill="skin"), P("M30,-95 L-10,20", w=12, c="waterLine"),
        P("M20,-60 L80,-30 L110,-70 M20,-60 L-40,-50 L-70,-10", w=10), P("M-10,20 L50,70 L30,150 M-10,20 L-70,80 L-130,60", w=11),
        P("M-150,-60 L-100,-60 M-160,-20 L-110,-20 M-140,20 L-100,20", c="inkSoft", w=6)])
doodle("doctor", ["doctor", "hospital", "medicine", "healing", "nurse", "sick", "health"],
       "a doctor with a stethoscope",
       [P(circ(0, -110, 48), fill="skin"), P("M-80,-50 L80,-50 L95,150 L-95,150 Z", fill="cloud"),
        P("M-40,-50 C-60,30 -10,60 20,30 M20,30 L20,10", w=6, c="inkSoft"), P(circ(20, 5, 12), w=6, fill="controller"),
        P("M45,-10 L75,-10 M60,-25 L60,5", c="accent", w=8)])
doodle("hospital", ["hospital", "sick", "illness", "disease", "healing", "doctor", "emergency", "suffering"],
       "a hospital building with a red cross",
       [P(rect(-150, -60, 300, 200, 6), fill="page"), P(rect(-60, -140, 120, 90, 6), fill="page"),
        P("M-15,-125 L15,-125 L15,-110 L30,-110 L30,-80 L15,-80 L15,-65 L-15,-65 L-15,-80 L-30,-80 L-30,-110 L-15,-110 Z", c="accent", w=5, fill="accent"),
        P(" ".join(rect(x, -30, 45, 40) for x in (-125, -55, 15, 85)), w=5, c="waterLine", fill="water"), P(rect(-30, 70, 60, 70), w=6, fill="water")])
doodle("bed_sick", ["sick", "illness", "bed", "patient", "disease", "weak", "rest", "recover"],
       "a person lying sick in bed",
       [P("M-170,40 L170,40 L170,90 L-170,90 Z", fill="trunk", fo=0.6), P("M-170,-40 L-170,140 M170,10 L170,140", w=10, c="trunk"),
        P("M-120,40 C-120,0 150,0 160,40", w=7, fill="water", fo=0.8), P(circ(-110, -5, 30), fill="skin"),
        P("M-90,-70 L-80,-55 M-70,-80 L-65,-60", c="waterLine", w=5)])
doodle("germ_big", ["germ", "virus", "disease", "sickness", "infection", "pandemic", "illness"],
       "a spiky germ",
       [P(circ(0, 0, 105, 0.08, 13), fill="green", c="greenLine", w=9),
        P(" ".join(f"M{n(math.cos(a) * 105)},{n(math.sin(a) * 105)} L{n(math.cos(a) * 150)},{n(math.sin(a) * 150)}" for a in [i * math.pi / 5 for i in range(10)]), c="greenLine", w=8),
        P(" ".join(circ(math.cos(a) * 158, math.sin(a) * 158, 10) for a in [i * math.pi / 5 for i in range(10)]), c="greenLine", w=6, fill="green"),
        P(circ(-35, -25, 18) + " " + circ(30, 30, 24) + " " + circ(40, -40, 10), c="greenLine", w=6)])
doodle("pill", ["medicine", "pill", "cure", "treatment", "heal", "quick fix", "drug"],
       "a capsule pill",
       [P("M-120,60 L60,-120 C100,-160 160,-100 120,-60 L-60,120 C-100,160 -160,100 -120,60 Z", w=9),
        P("M-120,60 L-30,-30 L60,60 L-60,120 C-100,160 -160,100 -120,60 Z", w=5, fill="cloud"),
        P("M-30,-30 L60,-120 C100,-160 160,-100 120,-60 L60,60 Z", w=5, c="accent", fill="accent", fo=0.75)])
doodle("grave", ["death", "grave", "die", "dead", "mortality", "loss", "funeral", "tomb"],
       "a gravestone with grass",
       [P("M-100,120 L-100,-60 C-100,-170 100,-170 100,-60 L100,120 Z", fill="woolGray", fo=0.6),
        P("M-170,120 L170,120", w=8, c="greenLine"), P("M-150,120 L-140,95 M-120,120 L-115,100 M120,120 L130,98 M145,120 L155,100", w=5, c="greenLine"),
        P(line(-50, -40, 50, -40), w=6, c="inkSoft")], {"label": [0, 175, 34], "on": [0, 20, 26]})
doodle("empty_tomb", ["empty tomb", "resurrection", "risen", "easter", "victory over death", "alive"],
       "a cave tomb with the stone rolled away and light inside",
       [P("M-170,130 C-170,-80 -80,-150 0,-150 C80,-150 170,-80 170,130 Z", fill="woolGray", fo=0.6),
        P("M-60,130 L-60,10 C-60,-50 60,-50 60,10 L60,130 Z", w=7, fill="starFill"), P(circ(125, 75, 55, 0.05, 14), w=8, fill="woolGray", fo=0.85),
        P("M-30,0 L-50,-30 M0,-15 L0,-45 M30,0 L50,-30", c="accent", w=6)])
doodle("baby", ["baby", "newborn", "birth", "new life", "infant", "beginning", "jesus born"],
       "a baby wrapped in a blanket",
       [P(circ(0, -70, 50), fill="skin"), P("M-80,-40 C-110,60 -60,140 0,140 C60,140 110,60 80,-40 C40,-10 -40,-10 -80,-40 Z", fill="water", fo=0.85),
        P(circ(-18, -75, 5) + " " + circ(18, -75, 5), w=6), P("M-12,-50 C-5,-44 5,-44 12,-50", w=5),
        P("M-60,20 C-20,40 20,40 60,20 M-50,70 C-15,85 15,85 50,70", w=5, c="waterLine")])
doodle("elder", ["old", "elderly", "grandparent", "age", "wisdom", "years", "ancestor"],
       "an old person with a cane",
       [P(circ(-10, -110, 42), fill="skin"), P("M-40,-140 C-20,-160 20,-160 30,-140", w=8, c="woolGray"),
        P("M-60,-65 L40,-65 L55,110 L-75,110 Z", fill="robe", fo=0.6), P("M50,-20 L100,-10 L100,170 M100,-10 C120,-25 125,-5 110,0", w=8, c="trunk"),
        P("M-40,110 L-45,170 M25,110 L30,170", w=10)])
doodle("soldier", ["soldier", "army", "war", "fight", "battle", "duty", "enemy"],
       "a soldier with a helmet and shield",
       [P(circ(0, -100, 42), fill="skin"), P("M-55,-110 C-55,-170 55,-170 55,-110 Z", w=7, fill="greenLine", fo=0.8),
        P("M-65,-50 L65,-50 L75,110 L-75,110 Z", fill="green", fo=0.8), P("M60,-20 L120,-20 L130,60 L80,90 L50,60 Z", w=7, fill="woolGray"),
        P("M-45,110 L-45,170 M45,110 L45,170", w=10)])
doodle("king_person", ["king", "ruler", "leader", "power", "authority", "president", "boss"],
       "a king with a crown and a cape",
       [P(circ(0, -100, 42), fill="skin"), P("M-40,-145 L-45,-185 L-20,-160 L0,-190 L20,-160 L45,-185 L40,-145 Z", w=6, fill="starFill"),
        P("M-80,-55 L80,-55 L110,150 L-110,150 Z", c="accent", fill="accent", fo=0.6), P("M-40,-55 L40,-55 L30,150 L-30,150 Z", w=5, fill="cloud")])
doodle("puppet_strings", ["puppet", "control", "controlled", "no choice", "robot", "manipulate", "forced", "free will"],
       "a puppet hanging on strings from a cross bar",
       [P("M-110,-170 L110,-170 M0,-200 L0,-140", w=10, c="trunk"),
        P("M-100,-170 L-60,-20 M100,-170 L60,-20 M0,-170 L0,-110 M-40,-170 L-30,90 M40,-170 L30,90", w=3, c="inkSoft"),
        P(circ(0, -80, 30), fill="trunk", fo=0.5), P("M-35,-45 L35,-45 L40,50 L-40,50 Z", fill="accent", fo=0.6),
        P("M-35,-35 L-60,-20 M35,-35 L60,-20 M-25,50 L-30,90 M25,50 L30,90", w=9)])
doodle("robot", ["robot", "machine", "ai", "programmed", "no free will", "automatic", "technology"],
       "a boxy robot",
       [P(rect(-70, -170, 140, 110, 16), fill="controller"), P(rect(-95, -45, 190, 170, 14), fill="controller"),
        P(circ(-30, -115, 14) + " " + circ(30, -115, 14), c="waterLine", w=6, fill="water"), P("M0,-170 L0,-205", w=7),
        P(circ(0, -212, 10), c="accent", w=6, fill="accent"), P("M-95,-10 L-150,60 M95,-10 L150,60 M-50,125 L-50,175 M50,125 L50,175", w=12)])
# ======================================================================= symbols / diagrams
doodle("question_big", ["question", "why", "mystery", "unknown", "doubt", "wonder", "how"],
       "a big question mark",
       [P("M-80,-80 C-80,-170 90,-180 90,-80 C90,-20 0,-10 0,50 L0,70", c="accent", w=24),
        P(circ(0, 140, 18), c="accent", w=10, fill="accent"), P("M-75,-80 C-70,-140 40,-160 65,-110", c="cloud", w=5)])
doodle("exclamation", ["important", "warning", "alert", "danger", "attention", "surprise"],
       "a warning triangle with an exclamation mark",
       [P("M0,-170 L170,130 L-170,130 Z", c="accent", w=10, fill="starFill"), P("M0,-80 L0,40", w=18),
        P(circ(0, 85, 12), w=8, fill="ink")])
doodle("check_big", ["yes", "correct", "true", "right", "done", "approved", "good", "agree"],
       "a big green check mark in a box",
       [P(rect(-140, -140, 280, 280, 24), fill="page"), P("M-90,0 L-25,70 L100,-90", c="greenLine", w=26),
        P("M-120,-120 L-60,-120", c="inkSoft", w=5)])
doodle("x_mark", ["no", "wrong", "false", "never", "reject", "mistake", "not", "impossible"],
       "a big red X in a box",
       [P(rect(-140, -140, 280, 280, 24), fill="page"), P("M-90,-90 L90,90 M90,-90 L-90,90", c="accent", w=26),
        P("M100,120 L130,120", c="inkSoft", w=5)])
doodle("arrow_up", ["up", "rise", "increase", "grow", "more", "better", "improve", "go up"],
       "a bold arrow pointing up",
       [P("M0,-170 L130,-30 L50,-30 L50,160 L-50,160 L-50,-30 L-130,-30 Z", c="greenLine", w=9, fill="green"),
        P("M-30,-10 L-30,130", c="cloud", w=7), P("M-130,170 L130,170", c="inkSoft", w=5)])
doodle("arrow_down", ["down", "fall", "decrease", "less", "worse", "decline", "drop", "lose"],
       "a bold arrow pointing down",
       [P("M0,170 L130,30 L50,30 L50,-160 L-50,-160 L-50,30 L-130,30 Z", c="accent", w=9, fill="accent", fo=0.55),
        P("M-30,-140 L-30,10", c="cloud", w=7), P("M-130,-175 L130,-175", c="inkSoft", w=5)])
doodle("cycle", ["cycle", "repeat", "again", "loop", "pattern", "habit", "forever", "endless"],
       "two arrows chasing each other in a circle",
       [P("M-120,-20 C-110,-120 60,-160 120,-60", c="waterLine", w=14), P("M120,-60 L140,-120 M120,-60 L60,-70", c="waterLine", w=14),
        P("M120,20 C110,120 -60,160 -120,60", c="accent", w=14), P("M-120,60 L-140,120 M-120,60 L-60,70", c="accent", w=14)],
       {"label": [0, 205, 34], "center": [0, 0, 30]})
doodle("target", ["goal", "target", "aim", "purpose", "focus", "mission", "bullseye"],
       "a target with an arrow in the bullseye",
       [P(circ(-20, 20, 140), fill="cloud"), P(circ(-20, 20, 95), c="accent", w=8, fill="accent", fo=0.5), P(circ(-20, 20, 45), fill="cloud"),
        P(circ(-20, 20, 14), c="accent", w=8, fill="accent"), P("M-20,20 L160,-160 M130,-170 L170,-170 L170,-130", w=9, c="trunk")])
doodle("puzzle", ["puzzle", "problem", "solve", "missing piece", "fit", "understand", "pieces"],
       "two puzzle pieces fitting together",
       [P("M-160,-110 L-20,-110 L-20,-60 C10,-80 10,-20 -20,-40 L-20,30 L-160,30 Z", fill="water", c="waterLine"),
        P("M0,-110 L140,-110 L140,30 L0,30 L0,-20 C30,0 30,-60 0,-40 Z", fill="accent", fo=0.55, c="accent"),
        P("M-160,60 L-20,60 L-20,150 L-160,150 Z", w=7, fill="green")], {"label": [0, 205, 34]})
doodle("bar_chart", ["graph", "chart", "statistics", "data", "numbers", "bar chart", "growth", "compare", "results"],
       "a bar chart on axes with three bars",
       [P("M-160,-160 L-160,130 L170,130", w=9), P(rect(-120, 30, 70, 100, 4), c="waterLine", fill="water"),
        P(rect(-25, -40, 70, 170, 4), c="accent", fill="accent", fo=0.6), P(rect(70, -120, 70, 250, 4), c="greenLine", fill="green"),
        P("M-170,-150 L-160,-165 L-150,-150", w=6)], {"a": [-85, 165, 24], "b": [10, 165, 24], "c": [105, 165, 24], "label": [0, -195, 30]})
doodle("line_graph", ["graph", "trend", "over time", "line graph", "rise and fall", "history", "progress"],
       "a line graph going up and down on axes",
       [P("M-160,-150 L-160,130 L170,130", w=9), P("M-150,80 L-90,20 L-40,60 L20,-40 L70,0 L150,-120", c="accent", w=10),
        P(" ".join(circ(x, y, 9) for x, y in [(-90, 20), (-40, 60), (20, -40), (70, 0), (150, -120)]), c="accent", w=6, fill="page"),
        P("M-120,130 L-120,140 M-40,130 L-40,140 M40,130 L40,140 M120,130 L120,140", w=5)],
       {"label": [0, 185, 30], "top": [100, -150, 24]})
doodle("pie_chart", ["pie chart", "share", "percent", "portion", "part of", "majority", "statistics"],
       "a pie chart with a slice pulled out",
       [P("M0,0 L0,-140 A140,140 0 1,0 121,70 Z", fill="water", c="waterLine"),
        P("M20,-10 L141,-80 A140,140 0 0,1 141,60 Z", c="accent", fill="accent", fo=0.6),
        P("M12,-12 L20,-150 A140,140 0 0,1 135,-90 Z", fill="green", c="greenLine")], {"label": [0, 190, 34], "slice": [95, -10, 22]})
doodle("triangle_diagram", ["triangle", "three things", "trilemma", "paradox", "three ideas", "trinity of ideas", "all powerful all good all knowing"],
       "a triangle diagram with a label at each corner",
       [P("M0,-150 L160,120 L-160,120 Z", w=9, fill="page"), P(circ(0, -150, 14) + " " + circ(160, 120, 14) + " " + circ(-160, 120, 14), c="accent", w=7, fill="accent"),
        P(circ(0, 40, 30), c="waterLine", w=6, fill="water")],
       {"top": [0, -195, 26], "left": [-140, 165, 26], "right": [140, 165, 26], "center": [0, 40, 24]})
doodle("venn_big", ["venn", "overlap", "both", "common ground", "compare", "in between"],
       "two overlapping circles",
       [P(circ(-70, 0, 120, 0.02, 15), c="accent", w=8, fill="accent", fo=0.22), P(circ(70, 0, 120, 0.02, 16), c="waterLine", w=8, fill="water", fo=0.5),
        P("M0,-95 C30,-50 30,50 0,95", w=4, c="inkSoft")], {"left": [-110, 0, 22], "right": [110, 0, 22], "label": [0, 165, 30]})
doodle("flow_arrows", ["steps", "process", "then", "cause and effect", "sequence", "leads to", "because"],
       "three boxes joined by arrows",
       [P(rect(-175, -50, 100, 100, 12), fill="page"), P(rect(-50, -50, 100, 100, 12), fill="page"), P(rect(75, -50, 100, 100, 12), c="accent", fill="marker"),
        P("M-75,0 L-55,0 M-65,-10 L-55,0 L-65,10 M50,0 L70,0 M60,-10 L70,0 L60,10", w=6, c="accent")],
       {"a": [-125, 0, 20], "b": [0, 0, 20], "c": [125, 0, 20], "label": [0, 110, 30]})
doodle("signpost_big", ["direction", "which way", "choice", "options", "guidance", "decision"],
       "a signpost with two arrows",
       [P("M0,170 L0,-170", w=12, c="trunk"), P("M0,-140 L130,-140 L165,-110 L130,-80 L0,-80 Z", c="waterLine", w=7, fill="water"),
        P("M0,-50 L-130,-50 L-165,-20 L-130,10 L0,10 Z", c="accent", w=7, fill="marker"), P("M-60,170 L60,170", w=7, c="inkSoft")],
       {"right": [75, -110, 22], "left": [-75, -20, 22], "label": [0, 210, 30]})
doodle("speech_bubble", ["said", "speak", "words", "say", "message", "talk", "promise", "voice"],
       "a speech bubble",
       [P("M-160,-110 C-160,-160 160,-160 160,-110 L160,40 C160,80 120,80 100,80 L-40,80 L-100,150 L-90,80 C-140,80 -160,70 -160,40 Z", fill="page"),
        P("M-110,-70 L110,-70 M-110,-20 L60,-20", w=6, c="inkSoft"), P("M140,-130 C150,-110 150,-90 145,-75", c="cloud", w=6)],
       {"label": [0, 195, 30], "on": [0, -20, 26]})
doodle("thought_cloud", ["think", "imagine", "dream", "idea", "believe", "wonder", "thought"],
       "a thought cloud",
       [P("M-120,20 C-180,20 -180,-80 -110,-80 C-110,-150 -10,-160 10,-100 C40,-160 150,-150 140,-80 C200,-80 200,20 140,20 C120,60 -100,60 -120,20 Z", fill="cloud"),
        P(circ(-110, 90, 22) + " " + circ(-150, 140, 13), fill="cloud", w=6), P("M-80,-60 C-70,-80 -50,-90 -30,-88", c="cloudShade", w=7)],
       {"label": [0, 200, 30], "on": [0, -40, 26]})
doodle("lock_heart", ["love locked", "commitment", "faithful", "marriage", "loyal", "covenant"],
       "a heart-shaped padlock",
       [P("M-55,-40 L-55,-100 C-55,-170 55,-170 55,-100 L55,-40", w=12, c="inkSoft"),
        P("M0,150 C-200,30 -140,-120 0,-30 C140,-120 200,30 0,150 Z", c="accent", w=9, fill="accent", fo=0.5), P(circ(0, 40, 14), w=6, fill="ink")])
doodle("anchor", ["anchor", "hope", "steady", "secure", "stable", "hold on"],
       "a ship's anchor",
       [P(circ(0, -140, 28), w=10), P("M0,-110 L0,150 M-70,-60 L70,-60", w=12),
        P("M-140,40 C-130,120 -60,150 0,150 C60,150 130,120 140,40 M-160,60 L-140,40 L-115,60 M160,60 L140,40 L115,60", w=12),
        P("M-15,-90 L-15,120", c="cloud", w=4)])
doodle("compass", ["compass", "direction", "guidance", "lost", "find the way", "north", "purpose"],
       "a compass",
       [P(circ(0, 0, 140, 0.02, 17), w=10, fill="page"), P("M0,-110 L30,0 L0,110 L-30,0 Z", w=5),
        P("M0,-110 L30,0 L-30,0 Z", c="accent", w=5, fill="accent"), P("M0,-140 L0,-125 M140,0 L125,0 M0,140 L0,125 M-140,0 L-125,0", w=8)],
       {"label": [0, 190, 30], "top": [0, -170, 24]})
doodle("map", ["map", "plan", "journey", "route", "where", "find", "travel"],
       "a folded treasure map with a dotted path and an X",
       [P("M-170,-110 L-60,-140 L60,-110 L170,-140 L170,110 L60,140 L-60,110 L-170,140 Z", fill="page"),
        P("M-60,-140 L-60,110 M60,-110 L60,140", w=5, c="inkSoft"), P("M-130,80 C-90,20 -40,60 0,0 C40,-50 80,-10 110,-70", c="waterLine", w=6),
        P("M95,-90 L130,-55 M130,-90 L95,-55", c="accent", w=9)])
doodle("book_open", ["book", "read", "learn", "study", "story", "knowledge", "law", "history"],
       "an open book with lines of text",
       [P("M0,-90 C-60,-130 -130,-120 -170,-100 L-170,110 C-130,90 -60,90 0,120 Z", fill="page"),
        P("M0,-90 C60,-130 130,-120 170,-100 L170,110 C130,90 60,90 0,120 Z", fill="page"),
        P("M-140,-60 L-30,-60 M-140,-20 L-30,-20 M-140,20 L-50,20 M30,-60 L140,-60 M30,-20 L140,-20 M30,20 L110,20", w=5, c="inkSoft")],
       {"label": [0, 175, 30], "left": [-85, 60, 22], "right": [85, 60, 22]})
doodle("scroll", ["scroll", "law", "old testament", "ancient", "record", "command", "prophecy"],
       "an unrolled ancient scroll",
       [P(rect(-120, -120, 240, 240, 6), fill="page"), P(rect(-150, -150, 300, 40, 20), fill="trunk", fo=0.6),
        P(rect(-150, 110, 300, 40, 20), fill="trunk", fo=0.6), P("M-80,-70 L80,-70 M-80,-30 L80,-30 M-80,10 L60,10 M-80,50 L80,50", w=5, c="inkSoft")],
       {"label": [0, 200, 30], "on": [0, -10, 24]})
doodle("tablets", ["commandments", "law", "rules", "ten commandments", "moses", "covenant"],
       "two stone tablets",
       [P("M-160,150 L-160,-60 C-160,-150 -10,-150 -10,-60 L-10,150 Z", fill="woolGray", fo=0.55),
        P("M10,150 L10,-60 C10,-150 160,-150 160,-60 L160,150 Z", fill="woolGray", fo=0.55),
        P("M-130,-40 L-40,-40 M-130,10 L-40,10 M-130,60 L-40,60 M-130,110 L-40,110 M40,-40 L130,-40 M40,10 L130,10 M40,60 L130,60 M40,110 L130,110", w=5, c="inkSoft")])
doodle("envelope", ["letter", "message", "mail", "invitation", "news", "send"],
       "a sealed envelope",
       [P(rect(-160, -100, 320, 200, 10), fill="page"), P("M-160,-100 L0,20 L160,-100", w=7),
        P("M-160,100 L-40,0 M160,100 L40,0", w=5, c="inkSoft"), P(circ(0, 20, 24), c="accent", w=6, fill="accent")])
doodle("magnifier", ["search", "look closer", "investigate", "find", "examine", "evidence", "truth", "detail"],
       "a magnifying glass",
       [P(circ(-40, -40, 105, 0.02, 18), w=14, fill="water", fo=0.45), P("M35,35 L150,150", w=26, c="trunk"),
        P("M-100,-80 C-90,-110 -60,-130 -30,-130", c="cloud", w=9)])
doodle("battery", ["energy", "battery", "tired", "empty", "recharge", "power", "strength", "rest"],
       "a battery running low",
       [P(rect(-150, -75, 270, 150, 18), fill="page"), P(rect(120, -30, 30, 60, 6), fill="inkSoft"),
        P(rect(-130, -55, 70, 110, 8), c="accent", w=5, fill="accent", fo=0.75), P("M-20,-40 L-50,10 L-10,10 L-40,60", c="inkSoft", w=5)])
doodle("megaphone", ["announce", "shout", "tell everyone", "share", "preach", "loud", "spread the word"],
       "a megaphone with sound lines",
       [P("M-150,-30 L-30,-30 L110,-110 L110,110 L-30,30 L-150,30 Z", c="accent", w=8, fill="accent", fo=0.55),
        P(rect(-100, 30, 40, 60, 8), w=7, fill="inkSoft", fo=0.6), P("M140,-60 C165,-20 165,20 140,60 M170,-90 C205,-30 205,30 170,90", w=7)])
doodle("bell", ["bell", "call", "alarm", "wake up", "announce", "church bell"],
       "a ringing bell",
       [P("M-110,90 C-100,20 -90,-100 0,-110 C90,-100 100,20 110,90 Z", fill="starFill"), P(rect(-130, 90, 260, 25, 12), fill="starFill"),
        P(circ(0, 130, 20), w=7, fill="trunk"), P("M-150,-60 L-130,-40 M150,-60 L130,-40 M-160,10 L-135,15 M160,10 L135,15", c="accent", w=7),
        P("M0,-110 L0,-140", w=8)])
doodle("candle", ["candle", "light", "hope", "darkness", "remember", "prayer", "shine"],
       "a lit candle",
       [P(rect(-45, -40, 90, 200, 10), fill="cloud"), P("M0,-40 L0,-65", w=6),
        P("M0,-160 C30,-120 35,-90 0,-65 C-35,-90 -30,-120 0,-160 Z", c="accent", w=6, fill="starFill"),
        P("M-80,165 L80,165", w=8, c="trunk"), P("M-25,-20 L-25,80", c="cloudShade", w=6)])
doodle("lamp", ["lamp", "light", "guide", "lamp unto my feet", "truth", "darkness", "shine"],
       "an oil lamp with a flame",
       [P("M-150,40 C-150,-20 130,-30 150,20 L190,-10 L170,40 C150,90 -120,100 -150,40 Z", fill="trunk", fo=0.6),
        P("M150,10 C175,-30 180,-60 160,-95 C140,-60 140,-30 150,10 Z", c="accent", w=6, fill="starFill"),
        P("M-150,40 C-190,30 -200,0 -170,-10", w=8), P(ell(0, 100, 120, 18), w=5, c="shadow", fill="shadow", fo=0.6)])
doodle("stairs", ["steps", "stairs", "progress", "level", "climb", "stages", "step by step"],
       "a staircase going up",
       [P("M-170,150 L-170,90 L-100,90 L-100,30 L-30,30 L-30,-30 L40,-30 L40,-90 L110,-90 L110,-150 L170,-150 L170,150 Z", fill="page"),
        P("M-170,150 L170,150", w=8), P("M120,-170 L160,-170 L140,-195", c="accent", w=6)])
doodle("wall", ["wall", "barrier", "blocked", "separation", "divide", "obstacle", "can't"],
       "a brick wall",
       [P(rect(-170, -130, 340, 260, 4), fill="accent", fo=0.45), P("M-170,-65 L170,-65 M-170,0 L170,0 M-170,65 L170,65", w=6),
        P("M-90,-130 L-90,-65 M10,-130 L10,-65 M110,-130 L110,-65 M-40,-65 L-40,0 M60,-65 L60,0 M-90,0 L-90,65 M10,0 L10,65 M110,0 L110,65 M-40,65 L-40,130 M60,65 L60,130", w=6)])
doodle("boat", ["boat", "ship", "storm at sea", "ark", "journey", "fishermen", "sail"],
       "a sailboat on waves",
       [P("M-160,30 L160,30 L120,100 L-120,100 Z", fill="trunk", fo=0.75), P("M0,30 L0,-170", w=8),
        P("M10,-160 L140,10 L10,10 Z", w=7, fill="cloud"), P("M-10,-130 L-110,10 L-10,10 Z", w=7, c="accent", fill="marker"),
        P("M-180,120 C-140,105 -100,135 -60,120 C-20,105 20,135 60,120 C100,105 140,135 180,120", c="waterLine", w=6)])
doodle("airplane", ["plane", "fly", "travel", "trip", "far away", "vacation"],
       "a plane flying",
       [P("M-170,10 C-160,-20 120,-30 160,-10 C180,0 170,20 150,25 L-150,40 Z", fill="cloud"),
        P("M-20,10 L-90,110 L-50,110 L50,20 Z M-30,-15 L-80,-90 L-50,-90 L20,-20 Z", w=7, fill="water"),
        P("M-150,20 L-170,-50 L-130,-50 L-110,15", w=7, fill="accent", fo=0.6), P(" ".join(circ(x, 0, 7) for x in (40, 70, 100)), w=5, c="waterLine")])
doodle("rocket", ["rocket", "launch", "fast", "future", "space", "ambition", "take off"],
       "a rocket taking off",
       [P("M0,-170 C60,-120 70,-20 50,80 L-50,80 C-70,-20 -60,-120 0,-170 Z", fill="cloud"), P(circ(0, -60, 26), c="waterLine", w=7, fill="water"),
        P("M-50,20 L-100,100 L-50,80 M50,20 L100,100 L50,80", w=8, fill="accent", fo=0.7),
        P("M-30,90 C-30,140 0,170 0,170 C0,170 30,140 30,90 Z", c="accent", w=6, fill="starFill")])
doodle("magnet", ["attract", "magnet", "pull", "temptation", "drawn to", "attraction"],
       "a horseshoe magnet pulling",
       [P("M-110,-130 L-110,20 C-110,140 110,140 110,20 L110,-130 L50,-130 L50,20 C50,70 -50,70 -50,20 L-50,-130 Z", c="accent", w=8, fill="accent", fo=0.6),
        P(rect(-110, -150, 60, 40, 4) + " " + rect(50, -150, 60, 40, 4), w=7, fill="controller"),
        P("M-150,-190 L-130,-170 M150,-190 L130,-170 M0,-200 L0,-175", w=6, c="inkSoft")])
doodle("scale_weight", ["heavy", "weight", "burden", "pressure", "ton", "load"],
       "a heavy iron weight",
       [P("M-120,140 L-90,-60 L90,-60 L120,140 Z", fill="inkSoft", fo=0.55), P("M-40,-60 C-40,-150 40,-150 40,-60", w=14),
        P(rect(-70, 20, 140, 50, 6), w=5, c="inkSoft"), P("M-80,110 L80,110", w=5, c="cloud")], {"label": [0, 195, 30], "on": [0, 45, 30]})
doodle("seesaw", ["unbalanced", "balance", "tip", "outweigh", "trade off", "more than"],
       "a seesaw tipped to one side",
       [P("M-60,140 L0,40 L60,140 Z", fill="trunk", fo=0.7), P("M-180,-10 L180,90", w=12),
        P(rect(-170, -80, 80, 60, 8), c="accent", fill="marker"), P(rect(100, 15, 60, 50, 8), c="waterLine", fill="water")],
       {"left": [-130, -110, 22], "right": [130, -10, 22], "label": [0, 195, 30]})
doodle("umbrella", ["umbrella", "protection", "covered", "shelter", "storm", "safe"],
       "an umbrella sheltering from rain",
       [P("M-160,0 C-150,-130 150,-130 160,0 C130,-25 100,-25 80,0 C50,-25 20,-25 0,0 C-20,-25 -50,-25 -80,0 C-100,-25 -130,-25 -160,0 Z", c="waterLine", fill="water"),
        P("M0,-110 L0,130 C0,165 -45,165 -45,130", w=9), P("M-170,-160 L-180,-130 M-110,-175 L-120,-145 M110,-175 L100,-145 M170,-160 L160,-130", c="waterLine", w=7)])
doodle("tent", ["tent", "camp", "shelter", "temporary", "wilderness", "tabernacle"],
       "a camping tent",
       [P("M-180,130 L0,-140 L180,130 Z", fill="accent", fo=0.5), P("M0,-140 L0,130 M0,-140 L-60,130", w=6),
        P("M0,-140 L20,-175 M-180,130 L180,130", w=7), P("M-60,130 L0,0 L0,130", w=5, fill="trunk", fo=0.6)])
doodle("treasure_chest", ["treasure", "riches", "heaven treasure", "valuable", "hidden", "reward"],
       "an open treasure chest with gold",
       [P(rect(-150, -10, 300, 140, 8), fill="trunk", fo=0.8), P("M-150,-10 C-150,-110 150,-110 150,-10", w=8, fill="trunk", fo=0.6),
        P("M-120,-20 C-80,-80 80,-80 120,-20", c="accent", w=6, fill="starFill"),
        P("M-150,40 L150,40 M-20,20 L20,20 L20,70 L-20,70 Z", w=7, c="starFill"), P(star(60, -55, 18, 8), w=5, fill="starFill")])
doodle("fishing", ["fish", "fishermen", "catch", "follow me", "net", "provision"],
       "a fish on a hook",
       [P("M-120,20 C-60,-60 60,-60 110,20 C60,90 -60,90 -120,20 Z", c="waterLine", fill="fishBody"),
        P("M110,20 L170,-30 L170,70 Z", c="waterLine", w=7, fill="fishBody"), P(circ(-70, 5, 9), w=7),
        P("M-120,-160 L-120,-30 C-120,0 -150,0 -150,-20", w=6, c="inkSoft"), P("M-40,-25 C-30,10 -30,40 -40,65", c="waterLine", w=5)])
doodle("sheep_flock", ["flock", "sheep", "shepherd", "lost sheep", "follow", "crowd", "church"],
       "three sheep in a flock",
       [P(circ(-100, 20, 60, 0.12, 19) + " " + circ(100, 20, 60, 0.12, 20), fill="wool", c="inkSoft"), P(circ(0, -10, 75, 0.12, 21), fill="wool", c="inkSoft"),
        P(ell(-150, 0, 20, 16) + " " + ell(150, 0, 20, 16) + " " + ell(70, -40, 24, 20), fill="inkSoft", fo=0.6),
        P("M-120,75 L-120,110 M-80,75 L-80,110 M-30,60 L-30,100 M30,60 L30,100 M80,75 L80,110 M120,75 L120,110", w=8)])
doodle("shepherd_staff", ["shepherd", "staff", "guide", "lead", "pastor", "lord is my shepherd"],
       "a shepherd's crook",
       [P("M0,170 L0,-90 C0,-170 110,-170 110,-90 C110,-50 80,-40 60,-60", w=16, c="trunk"),
        P("M-5,-80 L-5,160", c="robeDark", w=4), P("M-60,175 L60,175", w=6, c="inkSoft")])
doodle("money_vs_heart", ["money or love", "priorities", "what matters", "compare", "choose", "treasure"],
       "a heart and a dollar sign on two sides of a line",
       [P("M-80,90 C-200,10 -150,-110 -80,-40 C-10,-110 40,10 -80,90 Z", c="accent", w=8, fill="accent", fo=0.5),
        P("M0,-150 L0,150", w=6, c="inkSoft"), P("M120,-70 C70,-90 50,-40 100,-20 C150,0 150,60 90,50 M110,-100 L110,80", c="greenLine", w=12)],
       {"left": [-80, 140, 24], "right": [110, 140, 24], "label": [0, 200, 30]})
doodle("time_money", ["time is money", "busy", "work", "wages", "hours", "career"],
       "a clock and coins",
       [P(circ(-40, -30, 110, 0.02, 22), w=9, fill="page"), P("M-40,-30 L-40,-100 M-40,-30 L10,0", w=8, c="accent"),
        P(ell(100, 110, 70, 22) + " " + ell(100, 80, 70, 22), fill="starFill"), P(ell(100, 50, 70, 22), fill="starFill")])
doodle("ballot", ["vote", "choose", "decision", "election", "democracy", "voice"],
       "a ballot going into a box",
       [P(rect(-140, -20, 280, 170, 10), fill="water", fo=0.8), P(line(-60, -20, 60, -20), w=12),
        P(rect(-60, -150, 120, 140, 6), fill="page"), P("M-30,-90 L-5,-60 L35,-120", c="greenLine", w=10)])
doodle("idol", ["idol", "false god", "worship things", "golden calf", "priorities", "money god"],
       "a golden statue on a pedestal, crossed out",
       [P(rect(-90, 80, 180, 70, 6), fill="woolGray", fo=0.6), P("M-60,80 L-70,-20 C-80,-120 80,-120 70,-20 L60,80 Z", fill="starFill"),
        P(circ(0, -130, 35), fill="starFill"), P("M-150,-180 L150,150", c="accent", w=12)])
doodle("houses_city", ["city", "town", "society", "neighborhood", "people", "community", "world"],
       "a little city skyline",
       [P(rect(-170, -40, 80, 180, 4), fill="water", fo=0.7), P(rect(-80, -130, 90, 270, 4), fill="page"),
        P(rect(20, -70, 70, 210, 4), fill="accent", fo=0.45), P(rect(100, -10, 70, 150, 4), fill="green", fo=0.8),
        P(" ".join(rect(x, y, 20, 24) for x in (-60, -25) for y in (-100, -50, 0, 50)), w=4, c="waterLine")])
doodle("scale_tipping_coin", ["corruption", "bribe", "unfair", "injustice", "rigged"],
       "a balance with a coin outweighing a heart",
       [P("M0,-150 L0,150 M-80,150 L80,150", w=10, c="trunk"), P("M-160,-60 L160,-140", w=8),
        P("M-210,40 Q-160,100 -110,40 Z M110,-40 Q160,20 210,-40 Z", fill="starFill"),
        P(ell(-160, 15, 40, 14), fill="starFill", c="trunk"), P("M160,-55 C130,-75 125,-110 145,-110 C155,-110 160,-100 160,-95 C160,-100 165,-110 175,-110 C195,-110 190,-75 160,-55 Z", c="accent", w=6, fill="accent", fo=0.5)])
doodle("snowflake", ["cold", "winter", "frozen", "pure", "unique", "white"],
       "a snowflake",
       [P(" ".join(f"M0,0 L{n(math.cos(a) * 150)},{n(math.sin(a) * 150)}" for a in [i * math.pi / 3 for i in range(6)]), c="waterLine", w=10),
        P(" ".join(f"M{n(math.cos(a) * 90)},{n(math.sin(a) * 90)} L{n(math.cos(a + 0.45) * 125)},{n(math.sin(a + 0.45) * 125)} M{n(math.cos(a) * 90)},{n(math.sin(a) * 90)} L{n(math.cos(a - 0.45) * 125)},{n(math.sin(a - 0.45) * 125)}" for a in [i * math.pi / 3 for i in range(6)]), c="waterLine", w=7),
        P(circ(0, 0, 22), c="waterLine", w=7, fill="water")])
doodle("rainbow", ["rainbow", "promise", "covenant", "hope", "after the storm", "god's promise"],
       "a rainbow between two clouds",
       [P("M-170,90 C-170,-140 170,-140 170,90", c="accent", w=22), P("M-140,90 C-140,-100 140,-100 140,90", c="starFill", w=22),
        P("M-110,90 C-110,-65 110,-65 110,90", c="green", w=22), P("M-80,90 C-80,-30 80,-30 80,90", c="water", w=22),
        P(circ(-160, 100, 40) + " " + circ(160, 100, 40), fill="cloud", w=6)])


# the width (px, at the doodle's own scale) a label may use in each slot: it wraps / shrinks to fit
SLOT_WIDTH = {"label": 340, "on": 200, "screen": 150, "thought": 70, "center": 120, "top": 200, "slice": 90,
              "left": 130, "right": 130, "a": 92, "b": 92, "c": 92}
WIDTH_OF = {("flow_arrows", "a"): 92, ("flow_arrows", "b"): 92, ("flow_arrows", "c"): 92, ("bar_chart", "a"): 80,
            ("bar_chart", "b"): 80, ("bar_chart", "c"): 80, ("triangle_diagram", "left"): 150,
            ("triangle_diagram", "right"): 150, ("triangle_diagram", "center"): 64, ("venn_big", "left"): 115,
            ("venn_big", "right"): 115, ("scales_big", "left"): 125, ("scales_big", "right"): 125,
            ("seesaw", "left"): 110, ("seesaw", "right"): 110, ("money_vs_heart", "left"): 150,
            ("money_vs_heart", "right"): 150, ("calendar", "top"): 260, ("compass", "top"): 160, ("line_graph", "top"): 140,
            ("cycle", "center"): 150, ("book_open", "left"): 120, ("book_open", "right"): 120,
            ("signpost_big", "left"): 115, ("signpost_big", "right"): 115, ("road_fork", "left"): 130,
            ("road_fork", "right"): 130}


def main() -> None:
    for name, d in LIB.items():
        for slot, q in d["slots"].items():
            while len(q) < 4:
                q.append(None)
            q[3:5] = [q[3], WIDTH_OF.get((name, slot), SLOT_WIDTH.get(slot, 200))]
    OUT.write_text(json.dumps(LIB, separators=(",", ":")), encoding="utf-8")
    print(f"doodle library: {len(LIB)} illustrations -> {OUT}")


if __name__ == "__main__":
    main()
