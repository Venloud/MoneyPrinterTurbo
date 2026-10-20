# Love of Money V3 private restart

Owner request: replace the previous two-minute car-sale edit with the attached `goodone.mp3` and a new handwritten scene. Drawings lead the explanation; uploaded cultural references illustrate the spoken idea.

- Branch `claude/love-money-v3`, based on `claude/kind-keller-sxexzo` at `18024e0`. The old money scenes and preview builders are not used.
- Scene: `scenes/love-of-money-v3.json`; entry point: `python -m kindled_iron.render ... --audio ... --review-phase preview|video`.
- Narration: private `approved_audio/love-of-money-v3/goodone.mp3`; SHA256 `5152b33af4e95b6b433d4749160bb34231d14f05d2a064a9d21c1ae1a7f74969`. Recording duration 77.55755 s. No detected silence exceeds 0.8 s at the specified -40 dB threshold, so none is cut. No TTS, voice speed change, or speech-generation credits.
- Final wording comes from the supplied script, aligned against the recording. Delivery tags are not captioned. WEB checks validate both scripture quotations.
- Private `movie_reference/` assets are required by filename. Four provider pins resolve inside Actions with repository secrets. Any required missing/undecodable file fails by name/ID.
- Six guide positions, 220 px/s (about 1.5 steps/s at the approved scale) maximum planned walking, distance-driven gait; protect pointing, reactions, freezing and scripture typing/hold intervals.
- Reuse the established generic renderer's word-timed typewriter, fixed-size page layout, captions, stride and bounds checks. New hand-drawn primitives add the clown, Bible myth and cross-out, house/groceries/plane, hammer/window cracks, 62¢, money-heart, chain/lock, opening hand, and hand/heart contrast.
- Preview mode audits every output frame, writes a 2160×2000 JPEG, report and metadata; it does not encode a video. Video mode uses the same private alignment cache and scene, audits again, mixes private `theme_1`, encodes H.264/AAC and decodes the whole MP4 to validate it.
- Delivery: private `Venloud/kindled-iron-voice/previews/love-of-money-v3/` only. No release uploads, public workflow artifacts, platform posts, approval ledger/queue/index changes or daily workflow edits.

Regression checks: `python -m pytest test/services/test_kindled_v3.py -q` (scene and meme constraints, WEB verse/page boundaries, fail-closed missing filenames). `node --check kindled_iron/runtime/runtime.js`.

The owner's optional YouTube reconnection request is separate from rendering. Existing helper: `kindled_iron/tools/connect_youtube.py`. It needs interactive owner OAuth on their own computer; never place tokens in chat. No publishing is authorized by this review.
