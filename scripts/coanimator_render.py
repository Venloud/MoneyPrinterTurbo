#!/usr/bin/env python3
"""Kindled Iron CoAnimator bridge."""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
from pathlib import Path

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--project", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--resolution", default="720p")
    p.add_argument("--fps", default="30")
    p.add_argument("--quality", default="standard")
    p.add_argument("--workers", default="auto")
    args = p.parse_args()

    coa = shutil.which("coa")
    if not coa:
        raise SystemExit("CoAnimator CLI 'coa' was not found.")

    project = Path(args.project)
    if not project.exists():
        raise SystemExit(f"CoAnimator project not found: {project}")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [coa, "render", str(project), "--resolution", args.resolution,
           "--fps", str(args.fps), "--quality", args.quality,
           "--workers", args.workers, "--out", str(out)]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    if not out.is_file() or out.stat().st_size == 0:
        raise SystemExit(f"CoAnimator render did not produce a valid MP4: {out}")

    print(json.dumps({"renderer":"coanimator","project":str(project),
                      "output":str(out),"resolution":args.resolution,
                      "fps":args.fps,"quality":args.quality}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
