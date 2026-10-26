"""Contact sheets of the doodle library, drawn by the real renderer (for reviewing the library, not used in videos).

    python -m kindled_iron.doodles.sheet --out <dir>     # sheet_1.png, sheet_2.png, ... (20 doodles per sheet)
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from kindled_iron.doodles.build import OUT as LIBRARY

COLS, ROWS, CELL_W, CELL_H, SCALE = 4, 5, 270, 384, 0.55


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--chrome", default=None)
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    from kindled_iron import render
    lib = json.loads(LIBRARY.read_text())
    names = list(lib)
    a.out.mkdir(parents=True, exist_ok=True)
    per = COLS * ROWS
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=render.find_chrome(a.chrome), args=["--allow-file-access-from-files"])
        for k in range(0, len(names), per):
            chunk = names[k:k + per]
            events = []
            for j, nm in enumerate(chunk):
                d = lib[nm]
                cx, cy = (j % COLS) * CELL_W + CELL_W / 2, 30 + (j // COLS) * CELL_H + CELL_H / 2 - 20
                events.append({"at": 0.1, "do": "draw", "id": f"d{j}", "type": "doodle", "x": cx, "y": cy, "scale": SCALE,
                               "instant": True, "pop": False, "still": True, "parts": d["parts"], "slots": d["slots"],
                               "labels": {s: s.upper() for s in d["slots"]}})
            scene = {"id": "sheet", "cast": {}, "ground": 1570, "camera_y": 960, "exact_narration": True,
                     "beats": [{"id": "b1", "narration": "sheet", "interaction": False, "events": events}]}
            data = render.build_data(scene, [(0.0, 4.0)], [[{"word": "sheet", "start": 0.0, "end": 0.5}]], 4.0)
            data["paper"] = None
            with tempfile.TemporaryDirectory() as tmp:
                page_file = render.write_page(data, Path(tmp))
                page = b.new_page(viewport={"width": 1080, "height": 1920})
                page.goto(Path(page_file).resolve().as_uri())
                page.wait_for_function("window.kiSeek !== undefined", timeout=60000)
                page.wait_for_timeout(1500)
                page.evaluate("window.kiSeek(3.0)")
                page.evaluate("names => names.forEach(function (n, j) { var d = document.createElement('div');"
                              f" d.textContent = n; d.style.cssText = 'position:absolute;font:600 22px sans-serif;color:#2a6;"
                              f"left:' + ((j % {COLS}) * {CELL_W} + 8) + 'px;top:' + (Math.floor(j / {COLS}) * {CELL_H} + 34) + 'px';"
                              " document.body.appendChild(d); })", chunk)
                f = a.out / f"sheet_{k // per + 1}.png"
                page.screenshot(path=str(f))
                page.close()
                print(f)
        b.close()


if __name__ == "__main__":
    main()
