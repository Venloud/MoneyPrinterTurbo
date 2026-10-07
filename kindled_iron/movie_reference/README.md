# Movie references (private)

This repo is PUBLIC: no meme images, reaction clips or film/TV clips here (git ignores this folder).
They live in the PRIVATE repo Venloud/kindled-iron-voice, folders `reactions/` (meme images and reaction
clips, named by emotion: `confused.jpg`, `god_did.mp4`) and `movie_reference/` (film/TV clips, named by
scene: `burning_bush.mp4`). Add a file there on GitHub (Add file -> Upload files) or with
`python kindled_iron/tools/fetch_clip.py "<url or search>" --start S --dur 2 --name <words> --folder <folder>`.
The workflow loads them at render time with VOICE_REPO_TOKEN. Switch: voice_profiles.json ->
`use_third_party_clips` (or the workflow input), off = the pinned stock / guide fallbacks.
