"""Kindled Iron director: script.txt + the owner's narration.mp3 -> a finished private preview. No voice is ever
generated and nothing is published.

    python -m kindled_iron.director.direct --id epicurean-paradox --private <kindled-iron-voice checkout> --out <dir>

1. align   the MP3 is transcribed (faster-whisper small.en) and aligned to the script's words, like the renderer
2. plan    Gemini writes a shot plan per line (meaning only: drawings, clip-box media, verse, pop, gesture, freeze)
3. check   plan.validate + media.resolve (stock footage by meaning, the owner's memes) + compile (zones -> coordinates)
4. render  preflight: 8 stills + the every-frame audit; then the full MP4 (music, pencil, record scratch, chimes)
5. gates   gates.run on both renders; any failure goes back to Gemini as the plan's fix_errors (max 2 fix rounds)
6. review  Gemini vision judges the 8 stills against their lines; one automatic fix round; final verdict
7. output  <out>/: <id>.mp4, <id>-8-frames.jpg, scene.json, plan.json, media.json, gates.json, review.json,
           gemini_calls.json, and fail_report.md when it could not make a video that passes every gate
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from kindled_iron.director import compile as compiler, gates, gemini, media, plan as planmod, review as reviewmod

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_FIX = 2
PLAN_TRIES = 3          # invalid plans retried inside one round (cheap: no render)


def log(msg: str) -> None:
    print(f"[director] {msg}", flush=True)


def split_beats(text: str) -> list[str]:
    paragraphs = [re.sub(r"\s+", " ", x).strip() for x in re.split(r"\n\s*\n", text) if x.strip()]
    if len(paragraphs) > 1:
        return paragraphs
    sentences = re.split(r"(?<=[.!?])\s+", paragraphs[0])
    beats, chunk = [], []
    for sentence in sentences:
        chunk.append(sentence)
        if len(" ".join(chunk).split()) >= 25:
            beats.append(" ".join(chunk))
            chunk = []
    if chunk:
        beats.append(" ".join(chunk))
    return beats


def align(mp3: Path, lines: list[str], work: Path) -> tuple[list[list[dict]], float]:
    """Per-line word timings of the recording (the renderer's own alignment) and how much of the script was heard."""
    from kindled_iron import whisper_transcribe as wt
    from kindled_iron.render import words_of
    wav = work / "director_voice.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(mp3), "-ac", "1", "-ar", "44100", str(wav)], check=True)
    dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                         str(wav)]).decode().strip())
    heard = wt.transcribe(wav, "small.en")
    per = [words_of(t) for t in lines]
    flat = [w for ws in per for w in ws]
    aligned = wt.align(flat, heard, (0.0, dur))
    a, b = [wt.norm(w) for w in flat], [wt.norm(h["word"]) for h in heard]
    matched = sum(bl.size for bl in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_matching_blocks())
    out, k = [], 0
    for ws in per:
        out.append(aligned[k:k + len(ws)])
        k += len(ws)
    return out, matched / max(1, len(a))


def run_render(scene_file: Path, out: Path, work: Path, preflight: bool) -> str | None:
    cmd = [sys.executable, "-m", "kindled_iron.render", str(scene_file), "--out", str(out), "--work", str(work),
           "--whisper-model", "small.en"] + (["--frames-only", "auto", "--audit"] if preflight else [])
    log(("preflight" if preflight else "full render") + ": " + " ".join(cmd[2:]))
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    (work.parent / ("preflight.log" if preflight else "render.log")).write_text(p.stdout + p.stderr, encoding="utf-8")
    for line in (p.stdout + p.stderr).splitlines():
        if "LAYOUT WARNING" in line or "AUDIT FAIL" in line or line.startswith("FAIL") or "MEDIA FAILED" in line:
            log("  " + line.strip())
    if p.returncode:
        tail = [l for l in (p.stdout + p.stderr).splitlines() if l.strip()]
        fail = next((l for l in reversed(tail) if "FAIL" in l or "Error" in l), tail[-1] if tail else "render failed")
        return fail.strip()[:600]
    return None


def ntfy(title: str, body: str) -> None:
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        log("NTFY_TOPIC not set: no phone alert")
        return
    try:
        req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"), method="POST",
                                     headers={"Title": title.encode("utf-8").decode("latin-1", "ignore")})
        urllib.request.urlopen(req, timeout=20).read()
    except Exception as e:  # noqa: BLE001 - an alert never fails the run
        log(f"ntfy failed: {e}")


def _measure(specs: list[dict]) -> dict:
    from kindled_iron.director.catalog import measure_specs
    return measure_specs(specs)[0]


def attempt(lines, words, cat, lib, meta, work: Path, feedback: list[str], rounds: list[dict]) -> dict | None:
    """One round: plan (+ re-plans for invalid plans), media, compile, preflight, full render, gates.
    Returns the result dict when every gate passed, else None (rounds[-1] holds the errors)."""
    rec: dict = {"feedback_in": feedback, "errors": []}
    rounds.append(rec)
    line_keys = [[planmod.key(w["word"]) for w in ws] for ws in words]
    spoken = [[w["word"] for w in ws] for ws in words]
    fb = list(feedback)
    for k in range(PLAN_TRIES):
        p = gemini.call_json("plan", planmod.prompt(lines, lib, cat, fb, spoken))
        errs = planmod.validate(p, lines, line_keys, lib, cat)
        if not errs:
            per_line, records, errs = media.resolve(p, lib, log)
        if not errs:
            try:
                scene, frames = compiler.compile_scene(p, lines, words, cat, per_line, meta, measure=_measure)
            except compiler.CompileError as e:
                errs = [f"layout: {e}"]
        if not errs:
            break
        log(f"plan try {k + 1}: {len(errs)} problem(s): " + "; ".join(errs[:6]))
        rec["errors"].append({"stage": "plan", "try": k + 1, "errors": errs})
        fb = list(feedback) + errs
    else:
        return None
    rec["plan"] = p
    scene_file = work / "scene.json"
    scene_file.write_text(json.dumps(scene, indent=1, ensure_ascii=False), encoding="utf-8")
    mp4 = work / f"{meta['id']}.mp4"
    pre_work, full_work = work / "pre", work / "full"
    for d in (pre_work, full_work):
        shutil.rmtree(d, ignore_errors=True)
    err = run_render(scene_file, mp4, pre_work, preflight=True)
    g = gates.run(pre_work, scene, p, lines, cat, meta["align"], False, err)
    rec["preflight_gates"] = g
    if not g["_passed"]:
        rec["errors"].append({"stage": "preflight", "errors": gates.errors(g) + _coverage_lines(g, words)})
        log("preflight gates failed: " + "; ".join(rec["errors"][-1]["errors"][:8]))
        return None
    err = run_render(scene_file, mp4, full_work, preflight=False)
    g = gates.run(full_work, scene, p, lines, cat, meta["align"], True, err, mp4.with_name(mp4.stem + "_meta.json"))
    rec["final_gates"] = g
    if not g["_passed"]:
        rec["errors"].append({"stage": "final", "errors": gates.errors(g)})
        log("final gates failed: " + "; ".join(rec["errors"][-1]["errors"][:8]))
        return None
    return {"plan": p, "scene": scene, "frames": frames, "media": records, "gates": g, "mp4": mp4, "work": full_work}


def _coverage_lines(g: dict, words: list[list[dict]]) -> list[str]:
    """Turn low-coverage times into per-line advice the planner can act on."""
    c = g.get("coverage") or {}
    if c.get("ok", True):
        return []
    hits: dict[int, int] = {}
    for t, _ in (c.get("detail") or {}).get("low_samples", []):
        n = next((i for i, ws in enumerate(words) if ws and ws[0]["start"] - 0.3 <= t <= ws[-1]["end"] + 0.6), None)
        if n is not None:
            hits[n] = hits.get(n, 0) + 1
    return [f"line {n + 1}: the frame looks empty: make its first drawing a WIDE diagram (flow, timeline, scales, venn, "
            "crossout, bars) and its second a TALL or square object (person, puppet, question, germ, bolt, heart)"
            for n in sorted(hits)]


def fail_report(out: Path, vid: str, rounds: list[dict], why: str) -> str:
    lines = [f"# Director failed: {vid}", "", why, "", "Each round below lists the checks that failed. The errors of a round are what "
             "Gemini received as fix_errors in the next round.", ""]
    for n, r in enumerate(rounds):
        lines.append(f"## Round {n + 1}")
        for e in r["errors"]:
            lines.append(f"- {e['stage']}" + (f" (plan try {e['try']})" if "try" in e else "") + ":")
            lines += [f"  - {x}" for x in e["errors"][:30]]
        if not r["errors"]:
            lines.append("- no errors recorded")
        lines.append("")
    text = "\n".join(lines)
    (out / "fail_report.md").write_text(text, encoding="utf-8")
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id", required=True)
    ap.add_argument("--private", type=Path, default=Path(os.environ.get("KI_PRIVATE_MEDIA", ".")))
    ap.add_argument("--out", type=Path, required=True, help="the preview folder (kindled-iron-voice/previews/<id>)")
    ap.add_argument("--work", type=Path, default=None)
    a = ap.parse_args()
    if not ID.fullmatch(a.id):
        ap.error("id must be lowercase words separated by hyphens")
    src = a.private / "approved_audio" / a.id
    script, mp3 = src / "script.txt", src / "narration.mp3"
    if not script.is_file() or not mp3.is_file():
        sys.exit(f"FAIL: {src} needs script.txt and narration.mp3 (the owner's recording; no voice is generated)")
    os.environ.setdefault("KI_PRIVATE_MEDIA", str(a.private))
    work = a.work or (REPO / "storage" / "director" / a.id)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    a.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    lines = split_beats(script.read_text(encoding="utf-8").strip())
    words, ratio = align(mp3, lines, work)
    log(f"{len(lines)} lines, {sum(len(w) for w in words)} words; recording matches {ratio:.0%} of the script")
    meta = {"id": a.id, "audio_path": f"approved_audio/{a.id}/narration.mp3",
            "sha256": hashlib.sha256(mp3.read_bytes()).hexdigest(), "align": ratio}
    cat = planmod.catalog()
    lib = media.library(a.private)
    log(f"catalog: {sum(1 for o in cat['objects'].values() if o.get('director'))} drawings; meme library: {len(lib)} files")
    rounds: list[dict] = []
    status = {"id": a.id, "lines": len(lines), "alignment": round(ratio, 3)}

    def finish(ok: bool, result: dict | None, rev: dict | None, why: str = "") -> None:
        (a.out / "gemini_calls.json").write_text(json.dumps(gemini.CALLS, indent=1), encoding="utf-8")
        (a.out / "rounds.json").write_text(json.dumps(rounds, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        status.update({"ok": ok, "minutes": round((time.time() - t0) / 60, 1), "gemini_calls": len(gemini.CALLS)})
        (a.out / "status.json").write_text(json.dumps(status, indent=1), encoding="utf-8")
        if not ok:
            text = fail_report(a.out, a.id, rounds, why)
            ntfy(f"Kindled Iron director FAILED: {a.id}", why + "\n" + text[:1500])
            sys.exit(f"FAIL: {why} (see fail_report.md)")
        (a.out / "fail_report.md").unlink(missing_ok=True)
        ntfy(f"Kindled Iron preview ready: {a.id}",
             f"Gates passed. Vision review: {rev.get('verdict')}. {rev.get('summary', '')}\nPrivate: previews/{a.id}/")

    if ratio < gates.MIN_ALIGN:
        rounds.append({"errors": [{"stage": "alignment", "errors": [f"only {ratio:.0%} of script.txt is heard in narration.mp3"]}]})
        finish(False, None, None, f"script.txt does not match narration.mp3 ({ratio:.0%} of the words heard)")
    feedback: list[str] = []
    result = None
    for n in range(1 + MAX_FIX):
        log(f"round {n + 1}/{1 + MAX_FIX}")
        result = attempt(lines, words, cat, lib, meta, work, feedback, rounds)
        if result:
            break
        feedback = [e for x in rounds[-1]["errors"] for e in x["errors"]][-40:]
    if not result:
        finish(False, None, None, f"no plan passed every gate after {1 + MAX_FIX} rounds")

    def save(res: dict, rev: dict) -> None:
        shutil.copy(res["mp4"], a.out / f"{a.id}.mp4")
        (a.out / "scene.json").write_text(json.dumps(res["scene"], indent=1, ensure_ascii=False), encoding="utf-8")
        (a.out / "plan.json").write_text(json.dumps(res["plan"], indent=1, ensure_ascii=False), encoding="utf-8")
        (a.out / "media.json").write_text(json.dumps(res["media"], indent=1, ensure_ascii=False), encoding="utf-8")
        (a.out / "gates.json").write_text(json.dumps(res["gates"], indent=1, ensure_ascii=False), encoding="utf-8")
        times = json.loads((res["work"] / "preview_times.json").read_text())
        subprocess.run([sys.executable, str(ROOT / "tools" / "frame_sheet.py"), str(res["mp4"]), "--work", str(res["work"]),
                        "--out", str(a.out / f"{a.id}-8-frames.jpg")], check=True)
        for f in ("box_contact.jpg",):
            if (res["work"] / f).exists():
                shutil.copy(res["work"] / f, a.out / f"{a.id}-{f}")
        (a.out / "review.json").write_text(json.dumps(rev, indent=1, ensure_ascii=False), encoding="utf-8")
        status["preview_times"] = times

    def do_review(res: dict) -> dict:
        times = json.loads((res["work"] / "preview_times.json").read_text())
        return reviewmod.review(res["mp4"], times, [f["line"] for f in res["frames"]], res["work"])

    rev = do_review(result)
    log(f"vision review: {rev['verdict']} ({rev.get('summary', '')})")
    reviews = [rev]
    if rev["verdict"] != "pass":
        fb = reviewmod.fixes(rev, [f"line {int(f['beat'][1:])}" for f in result["frames"]])
        log("review fix round: " + "; ".join(fb[:6]))
        better = attempt(lines, words, cat, lib, meta, work, fb, rounds)
        if better:
            rev2 = do_review(better)
            reviews.append(rev2)
            result, rev = better, rev2
            log(f"vision review after the fix: {rev['verdict']}")
        else:
            log("the review fix round did not pass the gates: keeping the first video")
    final = {"verdict": rev["verdict"], "summary": rev.get("summary", ""), "rounds": reviews}
    status.update({"verdict": rev["verdict"], "gates": {k: v["ok"] for k, v in result["gates"].items() if not k.startswith("_")}})
    save(result, final)
    finish(True, result, final)
    log(f"done: {a.out}")


if __name__ == "__main__":
    main()
