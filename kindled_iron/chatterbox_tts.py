"""Chatterbox TTS (Resemble AI, MIT) cloning from a private reference clip. Same interface as kokoro_tts.

Chatterbox pins its own torch/transformers, so it runs in its OWN Python (a separate venv):
KI_CHATTERBOX_PYTHON=/path/to/venv/bin/python. That interpreter runs this file as a worker.

The reference clip is NOT in this repo (public fork). The workflow downloads the chosen clip from
the owner's private repo into KI_VOICE_REF_DIR at run time; synthesize() deletes it after use.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _python() -> str | None:
    p = os.environ.get("KI_CHATTERBOX_PYTHON", "").strip()
    return p if p and Path(p).exists() else None


def _ref_path(profile: dict) -> Path | None:
    name = (profile.get("chatterbox") or {}).get("reference_clip")
    d = os.environ.get("KI_VOICE_REF_DIR", "").strip()
    if not name or not d:
        return None
    p = Path(d) / name
    return p if p.exists() else None


def available(profile: dict, chars: int = 0) -> tuple[bool, str, dict]:
    if not _python():
        return False, "Chatterbox not installed (KI_CHATTERBOX_PYTHON unset)", {}
    if not _ref_path(profile):
        return False, "no reference clip at run time (KI_VOICE_REF_DIR)", {}
    return True, "reference clip loaded", {}


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?:])\s+", text.strip())
    out, cur = [], ""
    for p in parts:                       # Chatterbox degrades on long inputs: <= ~220 chars a chunk
        if cur and len(cur) + len(p) > 220:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        out.append(cur)
    return out


def synthesize(segments: list[tuple[str, float]], out_wav: Path, profile: dict, ref: Path | None = None,
               keep_ref: bool = False) -> dict:
    """One sentence at a time (long ones split), joined with each sentence's pause."""
    ref = ref or _ref_path(profile)
    cfg = profile.get("chatterbox") or {}
    job = {"segments": [[sentences(t), p] for t, p in segments], "out": str(out_wav), "ref": str(ref),
           "settings": {k: cfg[k] for k in ("exaggeration", "cfg_weight", "temperature") if k in cfg}}
    try:
        subprocess.run([_python() or sys.executable, __file__, "--worker", json.dumps(job)], check=True)
    finally:
        if not keep_ref and ref and Path(ref).exists():
            Path(ref).unlink()            # the clip only lives for this run
    return {"model": "chatterbox", "reference_clip": cfg.get("reference_clip"), "chars": sum(len(t) for t, _ in segments)}


def _worker(job: dict) -> None:            # runs inside the Chatterbox venv
    import torch
    import torchaudio
    from chatterbox.tts import ChatterboxTTS

    torch.manual_seed(7)
    model = ChatterboxTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
    sr = model.sr
    pieces = [torch.zeros(1, int(0.15 * sr))]
    for chunks, pause in job["segments"]:
        for j, s in enumerate(chunks):
            pieces.append(model.generate(s, audio_prompt_path=job["ref"], **job["settings"]))
            if j < len(chunks) - 1:
                pieces.append(torch.zeros(1, int(0.12 * sr)))
        pieces.append(torch.zeros(1, int(pause * sr)))
    torchaudio.save(job["out"], torch.cat(pieces, dim=1), sr)
    print(f"[chatterbox] wrote {job['out']}", flush=True)


if __name__ == "__main__" and len(sys.argv) > 2 and sys.argv[1] == "--worker":
    _worker(json.loads(sys.argv[2]))
