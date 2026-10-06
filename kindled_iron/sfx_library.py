"""Build the fixed sound library ONCE (then it is committed and reused; renders never search).

    python -m kindled_iron.sfx_library            # fill vendor/sfx/lib + vendor/sfx/lib/sources.json
    python -m kindled_iron.sfx_library --list     # show what each role would use, download nothing

Source order per role: Kenney (CC0, already vendored) -> Freesound, CC0 ONLY (API with FREESOUND_API_KEY,
else the public search page with the CC0 filter; every sound page is re-checked for the CC0 licence) ->
ElevenLabs Sound Effects (only with --allow-elevenlabs + ELEVENLABS_API_KEY; generated once, cached,
characters logged). No CC BY, no CC BY-NC, no Shutterstock. Each long recording is cut into several
variants (different stretches of it), so every role has at least 4 to rotate.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
LIB = HERE / "vendor" / "sfx" / "lib"
KENNEY = HERE / "vendor" / "sfx"
SR = 44100
UA = "KindledIronBot/1.0 (sound library build; contact via GitHub Venloud)"
CC0 = "creativecommons.org/publicdomain/zero"

# role -> searches (best first), how many sources, variant length range (s), number of variants, loop?
ROLES = {
    # drawn things: pencil / pen on paper
    "pencil_long": {"q": ["pencil drawing on paper", "pencil sketching", "pencil line"], "src": 2, "seg": (0.5, 1.8), "n": 6},
    "scribble": {"q": ["pencil scribble", "pencil scribbling"], "src": 2, "seg": (0.15, 0.6), "n": 6},
    "marker": {"q": ["marker on paper", "felt tip pen drawing", "marker pen"], "src": 2, "seg": (0.4, 1.6), "n": 5},
    "handwriting": {"q": ["pencil writing on paper", "writing with pencil", "pen writing paper"], "src": 2, "seg": (0.6, 2.0), "n": 5},
    "scratch": {"q": ["pencil scratch", "pen scratch paper", "pencil strike"], "src": 2, "seg": (0.08, 0.35), "n": 6},
    "eraser": {"q": ["eraser rubbing paper", "eraser", "rubber eraser"], "src": 2, "seg": (0.4, 1.5), "n": 4},
    # big things arriving
    "rumble": {"q": ["earth rumble", "ground rumble", "rocks crumble"], "src": 2, "seg": (1.2, 3.0), "n": 4},
    "whoosh_fall": {"q": ["falling whoosh", "whoosh down", "fall whoosh"], "src": 2, "seg": (0.4, 1.4), "n": 4},
    "boom": {"q": ["deep boom", "cinematic boom", "sub boom"], "src": 2, "seg": (1.0, 3.0), "n": 4},
    "riser": {"q": ["riser swell", "reverse swell", "swell rise"], "src": 2, "seg": (0.9, 2.5), "n": 4},
    "burst": {"q": ["magic shimmer", "shimmer", "chime sparkle"], "src": 2, "seg": (0.5, 2.0), "n": 4},
    "water_rush": {"q": ["water rush", "wave wash", "water whoosh"], "src": 2, "seg": (1.0, 3.0), "n": 4},
    "whoosh_slow": {"q": ["slow whoosh", "soft whoosh", "air whoosh"], "src": 2, "seg": (0.8, 2.5), "n": 4},
    # low ambience + a soft music bed (loops)
    "amb_hum": {"q": ["low drone ambience", "dark ambient drone", "room tone"], "src": 1, "loop": 30},
    "amb_wind": {"q": ["soft wind ambience", "gentle wind"], "src": 1, "loop": 30},
    "amb_waves": {"q": ["calm sea waves", "gentle ocean waves"], "src": 1, "loop": 30},
    "amb_birds": {"q": ["birds morning ambience", "birdsong forest"], "src": 1, "loop": 30},
    "amb_crickets": {"q": ["crickets night ambience", "night crickets"], "src": 1, "loop": 30},
    "music": {"q": ["ambient pad calm", "warm ambient pad", "calm ambient music"], "src": 1, "loop": 75},
}
# Kenney CC0 roles (vendored: vendor/sfx/*.ogg + the Impact Sounds pack)
KENNEY_ROLES = {
    "pop": ["pop.ogg", "pop2.ogg", "pop3.ogg", "tick.ogg"],
    "thud": ["impactSoft_heavy_000.ogg", "impactSoft_heavy_001.ogg", "impactSoft_heavy_002.ogg", "impactSoft_heavy_003.ogg"],
}
KENNEY_IMPACT_ZIP = "https://kenney.nl/media/pages/assets/impact-sounds/87b4ddecda-1677589768/kenney_impact-sounds.zip"
# Never use these words in a pick (wrong feel for a calm kids' channel, or not what the role means)
BAD = re.compile(r"explos|gun|scream|horror|scary|glitch|laser|alarm|siren|voice|speech|talk|music loop|beat|drum|"
                 r"rain|thunder|car|traffic|crowd|kids|child|toilet|fart|creepy|monster", re.I)
BAD_MUSIC_OK = {"music"}


def log(msg: str) -> None:
    print(f"[sfx_library] {msg}", flush=True)


def _get(url: str, headers: dict | None = None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    for k in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if k == 2:
                raise
            log(f"retry {url}: {e}")
            time.sleep(3 * (k + 1))
    return b""


# --------------------------------------------------------------- Freesound (CC0 only)
def freesound_search(query: str) -> list[dict]:
    key = os.environ.get("FREESOUND_API_KEY")
    if key:
        q = urllib.parse.urlencode({"query": query, "filter": 'license:"Creative Commons 0"', "page_size": 30,
                                    "fields": "id,name,username,license,duration,previews,num_downloads,avg_rating,url"})
        data = json.loads(_get(f"https://freesound.org/apiv2/search/text/?{q}&token={key}"))
        return [{"id": r["id"], "title": r["name"], "author": r["username"], "duration": r["duration"],
                 "downloads": r["num_downloads"], "url": r["url"], "license_url": r["license"],
                 "mp3": r["previews"]["preview-hq-mp3"]} for r in data.get("results", []) if CC0 in r.get("license", "")]
    page = _get("https://freesound.org/search/?" + urllib.parse.urlencode(
        {"q": query, "f": 'license:"Creative Commons 0"'})).decode("utf-8", "replace")
    out = []
    for m in re.finditer(r'data-sound-id="(\d+)"\s+data-username="([^"]*)".*?data-mp3="([^"]+)".*?data-title="([^"]*)"\s+'
                         r'data-duration="([\d.]+)".*?data-num-downloads="(\d+)"', page, re.S):
        sid, user, mp3, title, dur, dl = m.groups()
        out.append({"id": int(sid), "title": html.unescape(title), "author": html.unescape(user), "duration": float(dur),
                    "downloads": int(dl), "mp3": mp3.replace("-lq.mp3", "-hq.mp3"),
                    "url": f"https://freesound.org/people/{urllib.parse.quote(html.unescape(user))}/sounds/{sid}/"})
    time.sleep(1.0)
    return out


def verify_cc0(snd: dict) -> bool:
    if snd.get("license_url"):
        return CC0 in snd["license_url"]
    page = _get(snd["url"]).decode("utf-8", "replace")
    time.sleep(1.0)
    snd["license_url"] = "https://creativecommons.org/publicdomain/zero/1.0/" if CC0 in page else ""
    return bool(snd["license_url"])


# --------------------------------------------------------------- audio helpers
def decode(src) -> np.ndarray:
    raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(src), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"])
    return np.frombuffer(raw, np.float32).copy()


def encode(x: np.ndarray, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                    "-c:a", "libvorbis", "-q:a", "5", str(out)], input=x.astype(np.float32).tobytes(), check=True)


def segments(x: np.ndarray, lo: float, hi: float) -> list[tuple[int, int]]:
    """Active stretches (energy above a threshold) cut to lo..hi seconds."""
    hop = int(0.02 * SR)
    rms = np.sqrt(np.convolve(x ** 2, np.ones(hop) / hop, mode="same")[::hop] + 1e-12)
    if not len(rms):
        return []
    thr = max(np.percentile(rms, 95) * 0.22, 1e-4)
    act = rms > thr
    runs, i = [], 0
    while i < len(act):
        if act[i]:
            j = i
            while j < len(act) and (act[j] or (j + 4 < len(act) and act[j:j + 4].any())):
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    out = []
    for a, b in runs:
        L = (b - a) * hop / SR
        if L < lo:
            continue
        if L <= hi:
            out.append((a * hop, b * hop))
            continue
        n = int(hi * SR)
        k = a * hop
        while k + n <= b * hop and len(out) < 40:     # several windows from one long stroke
            out.append((k, k + n))
            k += int(n * 1.3)
    return out


def tidy(seg: np.ndarray, fade: float = 0.015) -> np.ndarray:
    n = max(1, int(fade * SR))
    seg = seg - float(np.mean(seg))
    seg[:n] *= np.linspace(0, 1, n)
    seg[-n:] *= np.linspace(1, 0, n)
    rms = float(np.sqrt(np.mean(seg ** 2))) or 1e-6
    seg = seg * (0.1 / rms)                      # same loudness for every variant (-20 dBFS RMS)
    peak = float(np.max(np.abs(seg))) or 1.0
    return seg / peak * 0.95 if peak > 0.95 else seg


def make_loop(x: np.ndarray, length: float) -> np.ndarray:
    n = min(len(x), int(length * SR))
    a = max(0, (len(x) - n) // 2)
    return tidy(x[a:a + n].copy(), fade=1.0)


# --------------------------------------------------------------- build
def kenney(sources: list) -> None:
    impact = HERE / "vendor" / "sfx" / "kenney_impact"
    if not impact.exists():
        import io
        import zipfile
        z = zipfile.ZipFile(io.BytesIO(_get(KENNEY_IMPACT_ZIP)))
        impact.mkdir(parents=True)
        for name in z.namelist():
            base = name.rsplit("/", 1)[-1]
            if base in KENNEY_ROLES["thud"]:
                (impact / base).write_bytes(z.read(name))
    for role, files in KENNEY_ROLES.items():
        for k, f in enumerate(files):
            src = (KENNEY / f) if (KENNEY / f).exists() else impact / f
            out = LIB / f"{role}_{k}.ogg"
            encode(tidy(decode(src)), out)
            sources.append({"file": out.name, "role": role, "source": "kenney", "title": f,
                            "pack": "Kenney Interface/Impact Sounds", "url": "https://kenney.nl/assets",
                            "license": "CC0 1.0", "license_url": "https://creativecommons.org/publicdomain/zero/1.0/"})


def build(roles: list[str], list_only: bool, pins: dict) -> None:
    LIB.mkdir(parents=True, exist_ok=True)
    src_file = LIB / "sources.json"
    sources = [s for s in (json.loads(src_file.read_text()) if src_file.exists() else []) if s["role"] not in roles]
    if not list_only and "pop" in roles:
        kenney(sources)
    cache = LIB.parent / ".download"
    cache.mkdir(exist_ok=True)
    for role in [r for r in roles if r in ROLES]:
        spec, picked = ROLES[role], []
        need_len = spec.get("loop") or spec["seg"][0] * 3
        cands = []
        for q in spec["q"]:
            for s in freesound_search(q):
                s["query"] = q
                if BAD.search(s["title"]) and role not in BAD_MUSIC_OK:
                    continue
                if s["duration"] < need_len or s["duration"] > (600 if spec.get("loop") else 240):
                    continue
                cands.append(s)
        cands = [c for k, c in enumerate(cands) if c["id"] not in {d["id"] for d in cands[:k]}]
        if pins.get(role):
            cands = [c for c in cands if c["id"] in pins[role]] + [c for c in cands if c["id"] not in pins[role]]
        else:
            cands.sort(key=lambda c: -c["downloads"])
        log(f"{role}: " + "; ".join(f"{c['id']} '{c['title']}' {c['duration']:.0f}s {c['downloads']}dl" for c in cands[:6]))
        if list_only:
            continue
        variants = []
        for c in cands:
            if len(picked) >= spec["src"]:
                break
            if not verify_cc0(c):
                log(f"  skip {c['id']}: sound page does not say CC0")
                continue
            f = cache / f"{c['id']}.mp3"
            if not f.exists():
                f.write_bytes(_get(c["mp3"]))
            x = decode(f)
            if spec.get("loop"):
                variants.append((c, None, make_loop(x, spec["loop"])))
                picked.append(c)
                continue
            segs = segments(x, *spec["seg"])
            if not segs:
                log(f"  skip {c['id']}: no usable stretch")
                continue
            picked.append(c)
            per = max(2, -(-spec["n"] // spec["src"]))
            step = max(1, len(segs) // per)
            for a, b in segs[::step][:per]:
                variants.append((c, (a / SR, b / SR), tidy(x[a:b].copy())))
        for old in LIB.glob(f"{role}_*.ogg"):
            old.unlink()
        for k, (c, span, audio) in enumerate(variants[: spec.get("n", 1)]):
            out = LIB / f"{role}_{k}.ogg"
            encode(audio, out)
            sources.append({"file": out.name, "role": role, "source": "freesound", "id": c["id"], "title": c["title"],
                            "author": c["author"], "url": c["url"], "license": "CC0 1.0", "license_url": c["license_url"],
                            "query": c["query"], "segment": [round(span[0], 2), round(span[1], 2)] if span else "loop"})
        n = len(variants[: spec.get("n", 1)])
        log(f"  {role}: {n} file(s) from {', '.join(str(c['id']) for c in picked) or 'nothing'}"
            + ("" if n >= (1 if spec.get("loop") else 4) else "  WARNING: under 4 variants"))
    sources.sort(key=lambda s: s["file"])
    if not list_only:
        src_file.write_text(json.dumps(sources, indent=1))
        log(f"{len(sources)} files listed in {src_file}")


def elevenlabs_sfx(prompt: str, seconds: float, out: Path) -> int:
    """Fallback ONLY when a role found nothing CC0 (explicit --allow-elevenlabs). Returns characters billed."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise SystemExit("no ELEVENLABS_API_KEY")
    cache = LIB.parent / ".elevenlabs" / (hashlib.sha1(f"{prompt}|{seconds}".encode()).hexdigest() + ".mp3")
    if not cache.exists():
        req = urllib.request.Request("https://api.elevenlabs.io/v1/sound-generation", method="POST",
                                     data=json.dumps({"text": prompt, "duration_seconds": seconds}).encode(),
                                     headers={"xi-api-key": key, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(r.read())
            billed = int(r.headers.get("character-cost") or 0)
            log(f"ElevenLabs SFX '{prompt}': {billed} characters")
    encode(tidy(decode(cache)), out)
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--roles", default=",".join(["pop", "thud"] + list(ROLES)))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--pins", default=str(HERE / "vendor" / "sfx" / "lib_pins.json"),
                    help="role -> [freesound ids] chosen after listening (tried first)")
    a = ap.parse_args()
    pins = {k: v for k, v in (json.loads(Path(a.pins).read_text()) if Path(a.pins).exists() else {}).items() if not k.startswith("_")}
    build([r for r in a.roles.split(",") if r], a.list, pins)


if __name__ == "__main__":
    main()
