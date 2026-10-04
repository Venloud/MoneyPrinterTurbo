# Shared Media Library Research

Full research and detailed implementation plan: `Venloud/bouriko-shorts/docs/MEDIA_LIBRARY_RESEARCH.md`

Core sources:
- Stock: Pexels, Pixabay, Coverr
- Open/archive: Openverse, Wikimedia Commons, Internet Archive, Library of Congress, NASA, NOAA
- Meme/reaction: KLIPY, Twitch Clips, GIPHY Clips, Vlipsy, MemeScreens
- Anime: Blitz Anime API, anime-sdk, animeclips.online (manual), trace.moe
- SFX: Freesound, Lots of Sounds
- Clip mining: OpenClip, Clips Studio
- Architecture reference: web-media-getter

Use visual-intent requests and provider abstraction. Preserve provider, asset ID, source URL, creator, license, license URL, query, timestamp, and hash. Do not treat unknown rights as cleared.

Reference Bouriko research commit: 1d0695108c9a936717cd418bf45326f16a104d70
