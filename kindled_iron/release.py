"""Kindled Iron release path: generate -> owner approval -> buffer -> publish. Three manual workflows call this.

Private repo (kindled-iron-voice) layout, one permanent folder per video, no attempt folders:
    approved_audio/<id>/narration.mp3, script.txt (settings.json)   the owner's input (workflow 1)
    previews/<id>/                                                   the saved preview + its evidence (workflow 1)
    buffer/<id>.json                                                 the owner's approval of ONE exact video (workflow 2)
    approved/posted.json                                             every platform post, never posted twice (workflow 3)

    python -m kindled_iron.release check-input --private DIR --id ID     workflow 1: MP3 + script valid?
    python -m kindled_iron.release save-preview --from OUT --to PREVIEW  workflow 1: keep the last valid preview
    python -m kindled_iron.release list --private DIR                    workflow 2: what can be approved
    python -m kindled_iron.release approve --private DIR --id ID --actor LOGIN --confirm ID [--platforms a,b]
    python -m kindled_iron.release select --private DIR --id ID --ledger posted.json [--platforms a,b]
    python -m kindled_iron.release finish --private DIR --id ID --ledger posted.json --results publish_results.json

Nothing here posts, approves on its own, or weakens a gate: a video enters the buffer only through `approve`
(run by an allowed owner who types the video id again), and only a buffered video whose file still has the approved
sha256 can be selected for publishing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from kindled_iron.director import bundle

ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MIN_SECONDS, MAX_SECONDS = 5.0, 180.0           # a Short's narration; anything else is the wrong file
APPROVERS = [a.strip().lower() for a in os.environ.get("KI_APPROVERS", "Venloud").split(",") if a.strip()]
LATEST_RUN = ("status.json", "fail_report.md", "rounds.json", "ai_calls.json", "story.json", "checkpoint.json")


class Refused(Exception):
    """A release step that must not go ahead; the message says why."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(path: Path) -> str:
    return bundle.sha256(path)


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Refused(f"{path.name} is missing or not valid JSON ({type(e).__name__})")


# ------------------------------------------------------------------ workflow 1: the input and the saved preview
def check_input(private: Path, vid: str) -> dict:
    """approved_audio/<id>/: narration.mp3 is a real MP3 of a Short's length and script.txt has the words."""
    if not vid or not ID.fullmatch(vid):
        raise Refused(f"video id {vid!r} must be lowercase words joined by '-' (e.g. why-bugs-are-called-bugs)")
    src = Path(private) / "approved_audio" / vid
    mp3, script = src / "narration.mp3", src / "script.txt"
    if not mp3.is_file():
        raise Refused(f"no MP3: upload narration.mp3 to approved_audio/{vid}/ in the private repo first")
    if mp3.stat().st_size < 10_000:
        raise Refused(f"approved_audio/{vid}/narration.mp3 is only {mp3.stat().st_size} bytes: not a recording")
    try:
        probe = json.loads(subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=format_name,duration:stream=codec_type,codec_name",
             "-of", "json", str(mp3)], stderr=subprocess.STDOUT))
    except (subprocess.CalledProcessError, ValueError):
        raise Refused(f"approved_audio/{vid}/narration.mp3 is not a readable audio file")
    except FileNotFoundError:
        raise Refused("ffprobe is not installed: the MP3 cannot be checked")
    audio = [s for s in probe.get("streams") or [] if s.get("codec_type") == "audio"]
    if not audio or audio[0].get("codec_name") != "mp3":
        raise Refused(f"approved_audio/{vid}/narration.mp3 holds no MP3 audio "
                      f"({', '.join(s.get('codec_name', '?') for s in audio) or 'no audio stream'})")
    dur = float((probe.get("format") or {}).get("duration") or 0)
    if not MIN_SECONDS <= dur <= MAX_SECONDS:
        raise Refused(f"approved_audio/{vid}/narration.mp3 lasts {dur:.1f} s (expected {MIN_SECONDS:.0f}-{MAX_SECONDS:.0f} s)")
    if not script.is_file() or not script.read_text(encoding="utf-8").strip():
        raise Refused(f"approved_audio/{vid}/script.txt is missing or empty (the director aligns the words to the MP3)")
    st = src / "settings.json"
    if st.exists():
        _load(st)
    return {"id": vid, "mp3_sha256": _sha(mp3), "seconds": round(dur, 2),
            "words": len(script.read_text(encoding="utf-8").split())}


def save_preview(new: Path, preview: Path) -> str:
    """Copy one run's output (OUT/<id>/) into previews/<id>/. The latest-run files always go in. A new video
    replaces the saved one only when it is complete and consistent AND it was accepted, or the saved one was not
    accepted either: a failed attempt never destroys the last accepted preview. -> what happened."""
    new, preview = Path(new), Path(preview)
    vid = preview.name
    preview.mkdir(parents=True, exist_ok=True)
    for name in LATEST_RUN:
        if (new / name).is_file():
            shutil.copyfile(new / name, preview / name)
        elif name == "fail_report.md" and (preview / name).exists():
            (preview / name).unlink()                       # a run that did not fail leaves no old fail report
    man = bundle.read_manifest(new)
    if not man:
        return "kept the previous video (this run saved no complete video)"
    ok, why = bundle.consistent(new, vid)
    if not ok:
        return f"kept the previous video (the new bundle is inconsistent: {why})"
    old = bundle.read_manifest(preview)
    if old and old.get("accepted") and not man.get("accepted"):
        return (f"kept the previous ACCEPTED video (sha {str(old.get('sha256'))[:12]}); the new one was not accepted: "
                f"{man.get('not_accepted_because')}")
    stage = preview / ".incoming"                         # the new bundle beside the old one, then swapped in
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    try:
        for name in man["files"] + [bundle.MANIFEST]:
            shutil.copyfile(new / name, stage / name)
        for name in (old or {}).get("files", []):
            if name not in man["files"] and (preview / name).is_file():
                (preview / name).unlink()
        for name in man["files"]:
            os.replace(stage / name, preview / name)
        os.replace(stage / bundle.MANIFEST, preview / bundle.MANIFEST)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return f"saved the new video (sha {man['sha256'][:12]}, accepted {man.get('accepted')})"


# ------------------------------------------------------------------ workflow 2: the owner's approval
def _ledger(path: Path | None) -> dict:
    if not path or not Path(path).exists():
        return {}
    return _load(Path(path))


def _render_meta(preview: Path, vid: str) -> dict | None:
    f = preview / f"{vid}-meta.json"
    return _load(f) if f.is_file() else None


def readiness(private: Path, vid: str) -> list[str]:
    """Every reason this preview cannot be approved ([] = it can): it exists, its file is the one its manifest
    describes, every gate passed and a real vision review passed it (accepted), the narration is still the approved
    one, and the render's own voice / scripture / audio checks pass the publisher's gate."""
    from kindled_iron import publish
    preview = Path(private) / "previews" / vid
    man = bundle.read_manifest(preview)
    if not man:
        return [f"previews/{vid}/ has no finished video (video.json): run workflow 1 first or fix its failure"]
    ok, why = bundle.consistent(preview, vid)
    if not ok:
        return [f"previews/{vid}/{vid}.mp4 is not the video its manifest describes ({why})"]
    problems = []
    if not man.get("accepted"):
        problems.append(f"not accepted by the checks: {man.get('not_accepted_because') or 'no reason recorded'}")
    mp3 = Path(private) / "approved_audio" / vid / "narration.mp3"
    if man.get("narration_sha256") and mp3.is_file() and _sha(mp3) != man["narration_sha256"]:
        problems.append("the narration MP3 changed after this video was rendered: render it again")
    meta = _render_meta(preview, vid)
    if meta is None:
        problems.append(f"{vid}-meta.json (voice, scripture and audio checks) is missing")
    else:
        try:
            publish.gate(meta)
        except SystemExit as e:
            problems.append(str(e))
    return problems


def candidates(private: Path, ledger: Path | None = None) -> list[dict]:
    out = []
    posted = _ledger(ledger)
    for d in sorted((Path(private) / "previews").glob("*/")):
        man = bundle.read_manifest(d)
        if not man:
            continue
        vid = d.name
        b = Path(private) / "buffer" / f"{vid}.json"
        out.append({"id": vid, "sha256": man.get("sha256"), "seconds": man.get("duration"),
                    "saved_at": man.get("saved_at"), "problems": readiness(private, vid),
                    "buffer": _load(b).get("state") if b.is_file() else None,
                    "posted_to": sorted(k for k in posted.get(vid, {}) if k != "renders")})
    return out


def wanted_platforms(arg: str | None) -> list[str]:
    from kindled_iron import publish
    modes = publish.CONFIG["publish_mode"]
    configured = [p for p in publish.PLATFORMS if modes.get(p, "off") != "off"]
    if not arg:
        return configured
    asked = [p.strip() for p in arg.split(",") if p.strip()]
    bad = [p for p in asked if p not in configured]
    if bad:
        raise Refused(f"not a configured platform: {', '.join(bad)} (configured: {', '.join(configured)})")
    return asked


def post_text(private: Path, vid: str) -> dict:
    """The words that go out with the video: approved_audio/<id>/post.txt when the owner wrote one ('title:',
    'caption:', 'description:' lines, as the publisher reads them), else the title the director gave the scene.
    Recorded in the approval, so the owner approves the text together with the video."""
    from kindled_iron import publish
    f = Path(private) / "approved_audio" / vid / "post.txt"
    if f.is_file():
        return {k: v for k, v in publish.read_post(f).items()}
    scene = _load(Path(private) / "previews" / vid / "scene.json")
    p = dict(scene.get("post") or {})
    p.setdefault("title", scene.get("title") or vid.replace("-", " ").title())
    if any(isinstance(ev.get("scripture"), dict) for b in scene.get("beats", []) for ev in b.get("events", [])):
        p["description"] = (p.get("description", "") + "\nScripture: World English Bible").strip()
    tmp = Path(private) / "buffer" / f".{vid}.post.txt"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text("".join(f"{k}: {v}\n" for k, v in p.items()), encoding="utf-8")
    try:
        return publish.read_post(tmp)
    finally:
        tmp.unlink()


def approve(private: Path, vid: str, actor: str, confirm: str, platforms: str | None = None,
            ledger: Path | None = None, run: str | None = None, actor_id: str | None = None) -> dict:
    """The owner's explicit approval of ONE exact video -> buffer/<id>.json. Refused unless an allowed approver
    typed the same id again, the preview is ready (readiness() is empty) and it is not buffered or posted yet."""
    if not actor or actor.lower() not in APPROVERS:
        raise Refused(f"{actor!r} may not approve videos (allowed: {', '.join(APPROVERS)})")
    if (confirm or "").strip() != vid:
        raise Refused(f"approval not confirmed: type the exact video id {vid!r} in the confirm field")
    problems = readiness(private, vid)
    if problems:
        raise Refused("cannot approve " + vid + ": " + "; ".join(problems))
    preview = Path(private) / "previews" / vid
    man = bundle.read_manifest(preview)
    plats = wanted_platforms(platforms)
    done = set(_ledger(ledger).get(vid, {})) - {"renders"}
    if set(plats) <= done:
        raise Refused(f"{vid} is already posted to {', '.join(sorted(done))}: nothing left to approve")
    entry_f = Path(private) / "buffer" / f"{vid}.json"
    if entry_f.is_file():
        old = _load(entry_f)
        if old.get("state") == "approved":
            raise Refused(f"{vid} is already in the buffer (approved {old.get('approved_at')}, sha "
                          f"{str(old.get('sha256'))[:12]}): publish it or remove buffer/{vid}.json first")
    entry = {"id": vid, "state": "approved", "video": f"previews/{vid}/{vid}.mp4", "meta": f"previews/{vid}/{vid}-meta.json",
             "sha256": man["sha256"], "bytes": man.get("bytes"), "seconds": man.get("duration"),
             "narration_sha256": man.get("narration_sha256"), "platforms": plats, "post": post_text(private, vid),
             "approved_by": actor, "approved_by_id": actor_id, "approved_at": _now(), "approval_run": run,
             "accepted_checks": {"gates": man.get("gates"), "review": man.get("review")}}
    entry_f.parent.mkdir(parents=True, exist_ok=True)
    entry_f.write_text(json.dumps(entry, indent=1) + "\n", encoding="utf-8")
    return entry


# ------------------------------------------------------------------ workflow 3: publish one buffered video
def buffered(private: Path) -> list[dict]:
    d = Path(private) / "buffer"
    return [e for e in (_load(f) for f in sorted(d.glob("*.json"))) if e.get("state") == "approved"] if d.is_dir() else []


def select(private: Path, vid: str, ledger: Path | None = None, platforms: str | None = None) -> dict:
    """The exact approved video to publish and the platforms it still needs. Refused when the buffer is empty,
    the video is not in it, its file is not the approved one any more, or every platform already has it."""
    waiting = buffered(private)
    if not waiting:
        raise Refused("the publishing buffer is empty: approve a video with workflow 2 first")
    entry = next((e for e in waiting if e["id"] == vid), None)
    if not entry:
        raise Refused(f"{vid!r} is not approved in the buffer (waiting: {', '.join(e['id'] for e in waiting)})")
    video = Path(private) / entry["video"]
    if not video.is_file():
        raise Refused(f"{entry['video']} is missing: the approved video is gone")
    got = _sha(video)
    if got != entry["sha256"]:
        raise Refused(f"{entry['video']} changed after approval (sha {got[:12]}, approved {entry['sha256'][:12]}): "
                      "approve the new video again")
    plats = entry["platforms"] if not platforms else [p for p in wanted_platforms(platforms) if p in entry["platforms"]]
    done = set(_ledger(ledger).get(vid, {})) - {"renders"}
    left = [p for p in plats if p not in done]
    if not left:
        raise Refused(f"{vid} is already posted to {', '.join(sorted(done & set(plats)))}: never posted twice")
    post = Path(private) / "buffer" / f"{vid}.post.txt"          # the approved text, as the publisher reads it
    post.write_text("".join(f"{k}: {v}\n" for k, v in (entry.get("post") or {}).items()), encoding="utf-8")
    return {**entry, "remaining": left, "already": sorted(done & set(plats)), "video_path": str(video),
            "meta_path": str(Path(private) / entry["meta"]), "post_path": str(post),
            "render_name": f"{vid}-{entry['sha256'][:12]}.mp4"}


def finish(private: Path, vid: str, ledger: Path | None, results: Path | None) -> dict:
    """After publishing: the buffer entry becomes 'published' once every approved platform has the post in the
    ledger; otherwise it stays approved (the next run posts only the missing platforms). -> summary."""
    entry_f = Path(private) / "buffer" / f"{vid}.json"
    entry = _load(entry_f)
    posted = _ledger(ledger).get(vid, {})
    res = json.loads(Path(results).read_text()) if results and Path(results).is_file() else []
    per = {p: ({"ok": True, "url": posted[p].get("url"), "mode": posted[p].get("mode"), "at": posted[p].get("at")}
               if p in posted else next(({"ok": False, "error": r.get("error")} for r in res if r.get("platform") == p),
                                        {"ok": False, "error": "not attempted"})) for p in entry["platforms"]}
    if all(v["ok"] for v in per.values()):
        entry.update({"state": "published", "published_at": _now()})
    entry["results"] = per
    entry_f.write_text(json.dumps(entry, indent=1) + "\n", encoding="utf-8")
    return {"id": vid, "state": entry["state"], "platforms": per}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check-input", "save-preview", "list", "approve", "select", "finish"])
    ap.add_argument("--private", type=Path)
    ap.add_argument("--id", default="")
    ap.add_argument("--from", dest="src", type=Path)
    ap.add_argument("--to", type=Path)
    ap.add_argument("--actor", default="")
    ap.add_argument("--actor-id", default=None)
    ap.add_argument("--confirm", default="")
    ap.add_argument("--platforms", default="")
    ap.add_argument("--ledger", type=Path)
    ap.add_argument("--results", type=Path)
    ap.add_argument("--run", default=os.environ.get("GITHUB_RUN_ID"))
    ap.add_argument("--out", type=Path, help="write the command's JSON result here")
    a = ap.parse_args()
    try:
        if a.cmd == "check-input":
            r = check_input(a.private, a.id)
        elif a.cmd == "save-preview":
            r = {"saved": save_preview(a.src, a.to)}
        elif a.cmd == "list":
            r = candidates(a.private, a.ledger)
        elif a.cmd == "approve":
            r = approve(a.private, a.id, a.actor, a.confirm, a.platforms or None, a.ledger, a.run, a.actor_id)
        elif a.cmd == "select":
            r = select(a.private, a.id, a.ledger, a.platforms or None)
        else:
            r = finish(a.private, a.id, a.ledger, a.results)
    except Refused as e:
        print(f"REFUSED: {e}", flush=True)
        sys.exit(2)
    text = json.dumps(r, indent=1, default=str)
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    if a.cmd == "finish" and r["state"] != "published":
        failed = [p for p, v in r["platforms"].items() if not v["ok"]]
        print(f"NOT every platform has the post yet: {', '.join(failed)} (run workflow 3 again: only these are tried)")
        sys.exit(1)


if __name__ == "__main__":
    main()
