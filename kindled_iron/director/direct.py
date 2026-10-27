"""Kindled Iron director: script.txt + the owner's narration.mp3 -> a finished private preview. No voice is ever
generated and nothing is published.

    python -m kindled_iron.director.direct --id <video-id> --private <kindled-iron-voice checkout> --out <dir>

1. align   the MP3 is transcribed (faster-whisper small.en) and aligned to the script's words, like the renderer
2. plan    the AI (llm.py: Gemini -> GitHub Models -> Cloudflare) writes a shot plan per line (meaning only: drawings, clip-box media, verse, pop, gesture, freeze)
3. check   plan.validate + media.resolve (stock footage by meaning, the owner's memes) + compile (zones -> coordinates)
4. render  preflight: 8 stills + the every-frame audit; then the full MP4 (music, pencil, record scratch, chimes)
5. gates   gates.run on both renders; any failure goes back to the planner as fix_errors (at most 3 plan calls a video;
           plain mistakes are repaired in code first)
6. review  one vision call judges the 8 stills against their lines; one automatic fix round if the budget allows
   quota   every provider out of quota -> status waiting_quota, checkpoint.json kept, exit 75; the scheduled run
           after the 07:00 UTC reset resumes it
7. output  <out>/: <id>.mp4, <id>-8-frames.jpg, scene.json, plan.json, media.json, gates.json, review.json,
           ai_calls.json, rounds.json, checkpoint.json, status.json, and fail_report.md when it failed
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

from datetime import datetime, timedelta, timezone

from kindled_iron.director import compile as compiler, diagram as diagmod, gates, llm, media, plan as planmod, review as reviewmod
from kindled_iron.director import bundle
from kindled_iron.director import story as storymod
from kindled_iron.director.calls import CALLS

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ROUNDS: list[dict] = []   # every attempt's plan + errors (kept for the fail report, also after a crash)
PLAN_CALLS = 3            # AI plan calls per video (code repairs come first; every re-plan counts)
VISION_CALLS = 1          # AI vision calls per video
WAIT_EXIT = 75            # exit code: waiting for AI quota (EX_TEMPFAIL), not a failure
ATTEMPTS = [0]            # each attempt renders in its own folder: a later attempt never touches an earlier render


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


def attempt(p: dict, lines, words, cat, lib, meta, work: Path, rec: dict) -> dict | None:
    """One plan, all the way: code repairs, checks, media, compile, preflight render + gates, full render + gates.
    Returns the result when every gate passed, else None with the errors in rec["errors"] (no AI call here)."""
    line_keys = [[planmod.key(w["word"]) for w in ws] for ws in words]
    rec["plan"] = p
    notes = planmod.repair(p, lines, line_keys, cat, lib)
    if notes:
        log("plan repaired in code: " + "; ".join(notes))
        rec["repairs"] = notes
    dg = meta.get("diagram")
    if dg:                                         # the diagram is the visual there: no box media / meme card asked for
        cleared = diagmod.clear_plan(p, words, dg)
        if cleared:
            log("diagram on screen: " + "; ".join(cleared))
            rec.setdefault("repairs", []).extend(cleared)
    covered = {i for i, ws in enumerate(words) if dg and ws and ws[-1]["end"] <= dg["t1"] + 1.0}   # the diagram shows them
    errs = planmod.validate(p, lines, line_keys, lib, cat, covered)
    if not errs:
        per_line, records, errs = media.resolve(p, lib, log, lines)
        if dg and not errs:
            records.append({"kind": "diagram", "file": dg["file"], "path": dg.get("path"), "source": "owner library (private)",
                            "shown": [dg["t0"], dg["t1"]], "rect": dg["fit"]["rect"], "scale": dg["fit"]["scale"],
                            "why": dg["why"], "supports": dg["sentences"], "views": dg["views"],
                            "readability": dg.get("readability")})
    if not errs:
        try:
            scene, frames = compiler.compile_scene(p, lines, words, cat, per_line, meta, measure=_measure, diagram=dg)
        except compiler.CompileError as e:
            errs = [f"layout: {e}"]
    if errs:
        log(f"plan: {len(errs)} problem(s): " + "; ".join(errs[:6]))
        rec["errors"].append({"stage": "plan", "errors": errs})
        return None
    ATTEMPTS[0] += 1
    sub = work / f"attempt{ATTEMPTS[0]}"          # its own folder: the reviewed render of an earlier attempt stays
    shutil.rmtree(sub, ignore_errors=True)        # intact whatever this one does
    sub.mkdir(parents=True)
    rec["attempt"] = ATTEMPTS[0]
    scene_file = sub / "scene.json"
    scene_file.write_text(json.dumps(scene, indent=1, ensure_ascii=False), encoding="utf-8")
    mp4 = sub / f"{meta['id']}.mp4"
    pre_work, full_work = sub / "pre", sub / "full"
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
    try:
        bundle.verify_mp4(mp4, _expected_seconds(scene, words), decode=False)
    except bundle.BundleError as e:                # the renderer said ok but the file is not a complete video
        rec["errors"].append({"stage": "final", "errors": [f"the rendered video is incomplete: {e}"]})
        log(f"final render incomplete: {e}")
        return None
    return {"plan": p, "scene": scene, "frames": frames, "media": records, "gates": g, "mp4": mp4, "work": full_work,
            "attempt": ATTEMPTS[0]}


def _expected_seconds(scene: dict, words: list[list[dict]]) -> float | None:
    """How long the finished video must be: the narration's last word plus the scene's end hold."""
    try:
        return round(words[-1][-1]["end"] + float(scene.get("end_hold", 0)), 2)
    except (IndexError, KeyError, TypeError):
        return None


def _coverage_lines(g: dict, words: list[list[dict]]) -> list[str]:
    """Turn low-coverage times into per-line advice the planner can act on."""
    c = g.get("coverage") or {}
    if c.get("ok", True):
        return []
    hits: dict[int, int] = {}
    d = c.get("detail") or {}
    for t, _ in d.get("low_samples", []) + d.get("empty_samples", []):
        n = next((i for i, ws in enumerate(words) if ws and ws[0]["start"] - 0.3 <= t <= ws[-1]["end"] + 0.6), None)
        if n is not None:
            hits[n] = hits.get(n, 0) + 1
    return [f"line {n + 1}: the frame looks unfinished: show this line's main idea as a drawing (it is laid out large), "
            "or box media that truly shows it; never a decorative drawing" for n in sorted(hits)]


def fail_report(out: Path, vid: str, rounds: list[dict], why: str) -> str:
    lines = [f"# Director failed: {vid}", "", why, "", "Each attempt below is one AI plan (at most 3 per video) and the checks it failed. The errors of an "
             "attempt are what the planner received as fix_errors in the next one.", ""]
    for n, r in enumerate(rounds):
        lines.append(f"## Attempt {n + 1}" + (f" (plan by {r['provider']})" if r.get("provider") else ""))
        for e in r["errors"]:
            lines.append(f"- {e['stage']}:")
            lines += [f"  - {x}" for x in e["errors"][:30]]
        if not r["errors"]:
            lines.append("- no errors recorded")
        lines.append("")
    text = "\n".join(lines)
    (out / "fail_report.md").write_text(text, encoding="utf-8")
    return text


def _video_summary(man: dict | None) -> dict:
    return {k: man.get(k) for k in ("video", "sha256", "duration", "bytes", "run", "director_commit", "review",
                                    "accepted", "saved_at")} if man else {}


def accepted(gate_ok: dict, review: dict | None) -> tuple[bool, str]:
    """A preview is accepted only when every gate passed AND a genuine vision review of THIS final video said
    "pass". A failed or missing review, or a video revised after its review (not re-reviewed), is never ok."""
    if not gate_ok or not all(gate_ok.values()):
        return False, "not every gate passed: " + ", ".join(k for k, v in (gate_ok or {}).items() if not v)
    verdict = (review or {}).get("verdict")
    if verdict == "pass":
        return True, ""
    if verdict == "fixed_not_rereviewed":
        return False, ("the video was revised after its vision review and the revision was not reviewed again (the "
                       "budget is 1 vision call a video): it is not accepted")
    if verdict in (None, "", "pending"):
        return False, "no vision review of the final video"
    return False, f"the vision review failed: {(review or {}).get('summary', '')[:600]}"


def load_checkpoint(private: Path, vid: str, sha: str) -> dict:
    """The state of a video that waits for AI quota (previews/<id>/checkpoint.json): kept only while its status
    says waiting_quota and the recording is the same, so a finished or failed video always starts fresh."""
    d = private / "previews" / vid
    try:
        st = json.loads((d / "status.json").read_text())
        ck = json.loads((d / "checkpoint.json").read_text())
    except (OSError, ValueError):
        return {}
    if st.get("state") != "waiting_quota" or ck.get("sha256") != sha:
        return {}
    return ck


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
    work = (a.work or (REPO / "storage" / "director" / a.id)).resolve()     # the renderer and Chrome need absolute paths
    a.out = a.out.resolve()
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    a.out.mkdir(parents=True, exist_ok=True)
    ev = a.out                                    # the run's evidence sits beside the video, as always
    t0 = time.time()
    lines = split_beats(script.read_text(encoding="utf-8").strip())
    sha = hashlib.sha256(mp3.read_bytes()).hexdigest()
    ck = load_checkpoint(a.private, a.id, sha)
    if ck:
        log(f"resuming after a quota wait (since {ck.get('waiting_since')}): {ck['plan_calls']} plan call(s), "
            f"{ck['vision_calls']} vision call(s) already used")
        words, ratio = ck["words"], ck["align"]
        ROUNDS.extend(ck.get("rounds", []))
    else:
        words, ratio = align(mp3, lines, work)
        ck = {"sha256": sha, "words": words, "align": ratio, "plan_calls": 0, "vision_calls": 0, "feedback": [],
              "rounds": [], "passed_plan": None}
    log(f"{len(lines)} lines, {sum(len(w) for w in words)} words; recording matches {ratio:.0%} of the script")
    meta = {"id": a.id, "audio_path": f"approved_audio/{a.id}/narration.mp3", "sha256": sha, "align": ratio}
    cat = planmod.catalog()
    lib = media.library(a.private)
    diagrams = [m for m in lib if m.get("role") == "diagram"]
    lib = [m for m in lib if m.get("role") != "diagram"]          # diagrams are presented whole, never as a box meme
    log(f"catalog: {sum(1 for o in cat['objects'].values() if o.get('director'))} drawings; media library: {len(lib)} files, "
        f"{len(diagrams)} diagram(s)")
    # 1. story understanding (no AI call): the spoken sentences and what each one does
    story = storymod.analyze(lines, words)
    (ev / "story.json").write_text(json.dumps({"sentences": [{**storymod.evidence(s_), "intent": s_["intent"]}
                                                                for s_ in story["sentences"]]}, indent=1, ensure_ascii=False),
                                      encoding="utf-8")
    # 2. a whole diagram, where the narration introduces one from the library and explains what it shows
    from kindled_iron.render import SAFE
    dg = diagmod.select(story["sentences"], diagrams)
    if dg:
        item = next(m for m in diagrams if m["file"] == dg["file"])
        dg["fit"] = diagmod.fit(dg["size"], SAFE)
        dg["readability"] = diagmod.readability(item, dg["fit"]["scale"])
        meta["diagram"] = dg
        log(f"diagram: {dg['file']} {dg['t0']:.1f}-{dg['t1']:.1f}s at {dg['fit']['rect']} (scale {dg['fit']['scale']}); "
            f"{dg['why']}" + (f"; LIMITATION: {dg['readability']['note']}" if dg["readability"].get("ok") is False else ""))
    rounds: list[dict] = ROUNDS
    previous = bundle.read_manifest(a.private / "previews" / a.id)     # the video saved by an earlier run, if any
    status = {"id": a.id, "lines": len(lines), "alignment": round(ratio, 3), "video_saved": False,
              "video": {"kept": "previous", **_video_summary(previous)} if previous else None}
    if dg:
        status["diagram"] = {"file": dg["file"], "shown": [dg["t0"], dg["t1"]], "readability": dg["readability"]}
        if dg["readability"].get("ok") is False:
            status["limitations"] = [dg["readability"]["note"]]
    spoken = [[w["word"] for w in ws] for ws in words]

    def calls_summary() -> dict:
        by: dict = {}
        for c in CALLS:
            k = f"{c.get('provider')}:{c.get('kind')}"
            by.setdefault(k, {"answered": 0, "failed": 0, "models": []})
            by[k]["failed" if c.get("error") else "answered"] += 1
            if c.get("model") not in by[k]["models"]:
                by[k]["models"].append(c.get("model"))
        return {"plan_calls": ck["plan_calls"], "vision_calls": ck["vision_calls"], "limits": {"plan": PLAN_CALLS,
                "vision": VISION_CALLS}, "by_provider": by}

    def write_common() -> None:
        (ev / "ai_calls.json").write_text(json.dumps(CALLS, indent=1), encoding="utf-8")
        (ev / "rounds.json").write_text(json.dumps(rounds, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        ck["rounds"] = rounds
        (a.out / "checkpoint.json").write_text(json.dumps(ck, ensure_ascii=False, default=str), encoding="utf-8")
        status.update({"minutes": round((time.time() - t0) / 60, 1), "ai": calls_summary()})
        (a.out / "status.json").write_text(json.dumps(status, indent=1, default=str), encoding="utf-8")

    def finish(ok: bool, rev: dict | None, why: str = "") -> None:
        status.update({"ok": ok, "state": "done" if ok else "failed"})
        write_common()
        if not ok:
            text = fail_report(ev, a.id, rounds, why)
            ntfy(f"Kindled Iron director FAILED: {a.id}", why + "\n" + text[:1500])
            sys.exit(f"FAIL: {why} (see fail_report.md)")
        (ev / "fail_report.md").unlink(missing_ok=True)
        ntfy(f"Kindled Iron preview accepted: {a.id}",
             f"Gates passed and the vision review passed. {rev.get('summary', '')}\nPrivate: previews/{a.id}/")

    def wait(stage: str, e: Exception) -> None:
        """Every AI provider is out of quota: keep the checkpoint and stop cleanly; the scheduled retry after the
        07:00 UTC reset resumes it. Alert only when it is still stuck after 24 h."""
        now = datetime.now(timezone.utc)
        ck.setdefault("waiting_since", now.isoformat(timespec="seconds"))
        since = datetime.fromisoformat(ck["waiting_since"])
        status.update({"ok": False, "state": "waiting_quota", "stage": stage, "waiting_since": ck["waiting_since"],
                       "why": str(e)[:1500]})
        if now - since >= timedelta(hours=24) and not ck.get("notified"):
            ck["notified"] = True
            ntfy(f"Kindled Iron director waiting for AI quota: {a.id}",
                 f"Still no AI provider with quota after 24 h (stage: {stage}).\n{str(e)[:800]}")
        write_common()
        log(f"WAITING FOR QUOTA ({stage}): every AI provider is out; the checkpoint is kept and the scheduled run "
            f"after the 07:00 UTC reset resumes it. {str(e)[:400]}")
        sys.exit(WAIT_EXIT)

    if ratio < gates.MIN_ALIGN:
        rounds.append({"errors": [{"stage": "alignment", "errors": [f"only {ratio:.0%} of script.txt is heard in narration.mp3"]}]})
        finish(False, None, f"script.txt does not match narration.mp3 ({ratio:.0%} of the words heard)")

    def plan_call(feedback: list[str]) -> dict:
        ctx = diagmod.planner_note(dg) if dg else None
        full = planmod.prompt(lines, lib, cat, feedback, spoken, context=ctx)
        compact = planmod.prompt(lines, lib, cat, feedback, spoken, compact=True, context=ctx)
        n_before = len(CALLS)
        p = llm.call_json("plan", full, compact=compact)
        ck["plan_calls"] += 1
        answered = [c for c in CALLS[n_before:] if not c.get("error")]
        rounds.append({"feedback_in": feedback, "errors": [], "provider": answered[-1]["provider"] if answered else "?"})
        return p

    result = None
    if ck.get("passed_plan"):                      # it had passed every gate and waited only for the review
        log("re-rendering the plan that already passed every gate (no plan call)")
        rounds.append({"feedback_in": [], "errors": [], "provider": "checkpoint"})
        result = attempt(ck["passed_plan"], lines, words, cat, lib, meta, work, rounds[-1])
    while not result and ck["plan_calls"] < PLAN_CALLS:
        log(f"plan call {ck['plan_calls'] + 1}/{PLAN_CALLS}")
        try:
            p = plan_call(ck["feedback"])
        except llm.QuotaWait as e:
            wait("plan", e)
        result = attempt(p, lines, words, cat, lib, meta, work, rounds[-1])
        if not result:
            ck["feedback"] = [x for e in rounds[-1]["errors"] for x in e["errors"]][-40:]
    if not result:
        finish(False, None, f"no plan passed every gate within the budget of {PLAN_CALLS} plan calls")
    ck["passed_plan"] = result["plan"]

    def save(res: dict, rev: dict) -> bool:
        """Replace the saved video bundle with this render, or keep the previous one (a render that is not a
        complete, valid video never replaces it). Its review, gates and status always describe this video."""
        miss = planmod.misses(res["plan"], cat)                 # concepts the doodle library did not have
        acts = res["scene"].get("director", {}).get("actions", [])      # guide actions asked for, performed or not
        used = [d.get("type") for L in res["plan"]["lines"] for d in L.get("drawings", [])]
        notes = []
        tf = res["work"] / "preview_times.json"
        times = json.loads(tf.read_text()) if tf.is_file() else None
        if times is None:
            notes.append("preview_times.json missing: the 8 review stills could not be placed")
        sheet = res["work"] / "frames-8.jpg"
        try:
            subprocess.run([sys.executable, str(ROOT / "tools" / "frame_sheet.py"), str(res["mp4"]), "--work", str(res["work"]),
                            "--out", str(sheet)], check=True, capture_output=True)
        except (subprocess.CalledProcessError, OSError) as e:
            notes.append(f"frame sheet failed: {str(e)[:200]}")
        gate_ok = {k: v["ok"] for k, v in res["gates"].items() if not k.startswith("_")}
        ok, why = accepted(gate_ok, rev)
        rev = dict(rev, ai=calls_summary(), calls=CALLS)
        manifest = {"id": a.id, "run": os.environ.get("GITHUB_RUN_ID"), "director_commit": bundle.git_commit(REPO),
                    "narration_sha256": sha, "plan_attempt": res.get("attempt"), "review": rev.get("verdict"),
                    "accepted": ok, "not_accepted_because": None if ok else why, "gates": gate_ok, "notes": notes,
                    "proposed_composition": (res["gates"].get("_proposed_composition") or {}).get("ok")}
        data = {"review.json": rev, "gates.json": res["gates"], "scene.json": res["scene"], "plan.json": res["plan"],
                "media.json": res["media"], "doodle_misses.json": miss, "guide_actions.json": acts}
        try:
            man = bundle.write(a.out, a.id, res["mp4"], data, {f"{a.id}-8-frames.jpg": sheet,
                               f"{a.id}-box_contact.jpg": res["work"] / "box_contact.jpg"}, manifest,
                               _expected_seconds(res["scene"], words))
        except bundle.BundleError as e:
            log(f"NOT SAVED: {e}; the previous video stays")
            status.update({"video_saved": False, "save_error": str(e)})
            return False
        status.update({"video_saved": True, "video": {"kept": "new", **_video_summary(man)}, "gates": gate_ok,
                       "preview_times": times, "doodle_misses": len(miss), "save_notes": notes,
                       "guide_actions": {"performed": sum(1 for x in acts if x.get("performed")),
                                         "not_performed": [f"line {x['line']}: {x['action']} ({x['status']})"
                                                           for x in acts if not x.get("performed")]},
                       "drawings": {"library": sum(1 for t in used if cat["objects"].get(t, {}).get("doodle")),
                                    "built_in": sum(1 for t in used if not cat["objects"].get(t, {}).get("doodle"))}})
        log(f"saved {a.id}.mp4 ({man['duration']:.1f} s, sha {man['sha256'][:12]}), review {rev.get('verdict')}, "
            f"accepted {ok}")
        return True

    tf = result["work"] / "preview_times.json"
    if not tf.is_file():                           # no stills to review: saved, recorded, never accepted
        final = {"verdict": "not_reviewed", "summary": "preview_times.json is missing: the vision review could not run"}
        status["verdict"] = final["verdict"]
        saved = save(result, final)
        finish(False, final, final["summary"] + ("" if saved else "; the video was not saved either"))
    times = json.loads(tf.read_text())
    n_before = len(CALLS)
    try:
        rev = reviewmod.review(result["mp4"], times, [f["line"] for f in result["frames"]], result["work"])
        ck["vision_calls"] += 1
    except llm.QuotaWait as e:
        save(result, {"verdict": "pending", "summary": "waiting for AI quota for the vision review"})
        wait("review", e)
    rev["provider"] = next((c["provider"] for c in reversed(CALLS[n_before:]) if not c.get("error")), "?")
    log(f"vision review ({rev['provider']}): {rev['verdict']} ({rev.get('summary', '')})")
    final = {"verdict": rev["verdict"], "summary": rev.get("summary", ""), "rounds": [rev]}
    if rev["verdict"] != "pass" and ck["plan_calls"] < PLAN_CALLS:
        fb = reviewmod.fixes(rev, [f"line {int(f['beat'][1:])}" for f in result["frames"]])
        log("review fix round: " + "; ".join(fb[:6]))
        try:
            p = plan_call(fb)
            better = attempt(p, lines, words, cat, lib, meta, work, rounds[-1])
        except llm.QuotaWait as e:
            log(f"no AI quota for the review fix round ({str(e)[:200]}): keeping the reviewed video")
            better = None
        if better:                                 # the newest complete render is saved, but it was not reviewed
            result = better                        # (the vision budget is 1 call a video): never accepted
            final = {"verdict": "fixed_not_rereviewed", "summary": "revised after a failed vision review; the revision "
                     "passed every gate but was not reviewed (1 vision call a video)", "previous_review": rev}
            log("the review fix passed every gate; the vision budget (1 call) leaves it not re-reviewed")
        else:
            log("the review fix round did not pass the gates: keeping the reviewed video (its own render is untouched)")
    elif rev["verdict"] != "pass":
        log("vision review failed and the plan budget is spent: keeping the video with the failed verdict")
    status["verdict"] = final["verdict"]
    saved = save(result, final)                    # the video and ITS review are saved together, or not at all
    ok, why = accepted(status.get("gates") or {}, final) if saved else (False, "the video could not be saved: "
                                                                         + str(status.get("save_error")))
    finish(ok, final, why)
    log(f"done: {a.out}")


def _clean_work() -> None:
    """The temporary render folders go when the run ends (the preview folder keeps the saved video)."""
    if "--keep-work" in sys.argv:
        return
    w = sys.argv[sys.argv.index("--work") + 1] if "--work" in sys.argv else None
    vid = sys.argv[sys.argv.index("--id") + 1] if "--id" in sys.argv else None
    d = Path(w) if w else (REPO / "storage" / "director" / vid if vid and ID.fullmatch(vid) else None)
    if d and d.is_dir():
        for sub in d.glob("attempt*"):
            shutil.rmtree(sub, ignore_errors=True)


if __name__ == "__main__":
    import atexit
    atexit.register(_clean_work)
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:                       # any crash still leaves a fail report, status and a phone alert
        import traceback
        tb = traceback.format_exc()
        print(tb, flush=True)
        out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else None
        vid = sys.argv[sys.argv.index("--id") + 1] if "--id" in sys.argv else "?"
        why = f"crashed: {type(e).__name__}: {e}"
        if out:
            ev = out
            ev.mkdir(parents=True, exist_ok=True)
            (ev / "ai_calls.json").write_text(json.dumps(CALLS, indent=1), encoding="utf-8")
            (ev / "rounds.json").write_text(json.dumps(ROUNDS, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
            st = {}
            try:                                   # keep what the run already knew (which video is current...)
                st = json.loads((out / "status.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            st.update({"id": vid, "ok": False, "state": "failed", "error": why})
            man = bundle.read_manifest(out)        # a bundle this run saved stays described; never accepted now
            if man:
                st["video"] = {"kept": "new", **_video_summary(man), "accepted": False}
            (out / "status.json").write_text(json.dumps(st, indent=1, default=str), encoding="utf-8")
            (ev / "fail_report.md").write_text(f"# Director failed: {vid}\n\n{why}\n\n```\n{tb[-3000:]}\n```\n", encoding="utf-8")
        ntfy(f"Kindled Iron director FAILED: {vid}", why)
        sys.exit(f"FAIL: {why}")
