# Vendored from chrisaswain/stickman-animation-agent

- Source: https://github.com/chrisaswain/stickman-animation-agent
- Commit: c4b935f7d610c623e91a4afb702a50388ae96a00 (cloned 2026-10-05)
- License: MIT. The upstream README's "License" section says MIT, but the upstream repo
  has NO LICENSE file. `LICENSE` here is the standard MIT text written from that statement
  so the notice travels with the files. If upstream adds its own LICENSE, replace this one.

## What was copied
- `components/` – all SVG character parts (heads, expressions, hair, arms, legs, props...).
  Used at render time: `tier1/heads/front.svg`, `tier1/expressions/*.svg`, `tier1/hair/*.svg`
  (recoloured to Kindled Iron ink/board by `render.py`).
- `animations.js` – upstream's GSAP animation library, kept as reference. Not loaded at render
  time: its ideas (stroke-dashoffset draw-in, camera wrapper, expression swap, point / wave /
  celebrate / head-shake) are re-implemented in `kindled_iron/runtime/runtime.js` on an
  articulated rig. Upstream's walk cycle only mirrored a static legs SVG; ours rotates hips
  and knees.
- `whiteboard-template.json`, `svg-style-guide.md` – reference for the style.

## Not copied
- `src/pipeline/orchestrator.js`, `src/render/pipeline.js` (hard-coded `.venv\Scripts\python.exe`,
  expects Claude Code to run skills, missing `scripts/*.py`), HyperFrames dependency
  (`"hyperframes": "latest"`), Gemini enhancer, publisher. Rendering here is our own
  headless-Chrome frame capture (`kindled_iron/render.py`).
