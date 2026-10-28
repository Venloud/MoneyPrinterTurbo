# Kindled Iron: from your MP3 to every platform (three manual workflows)

Nothing runs on a schedule and nothing posts without your approval. Each step is a separate workflow in
**Actions** (MoneyPrinterTurbo). The video and every private file stay in the private repo
`Venloud/kindled-iron-voice`; MoneyPrinterTurbo is public, so nothing private goes into its artifacts.

| # | Workflow | What it does | Can it post? |
|---|---|---|---|
| 1 | **Kindled Iron 1 - Generate Video** (`kindled_iron_director_preview.yml`) | MP3 + script -> finished private video + review package | No |
| 2 | **Kindled Iron 2 - Approve and Add to Buffer** (`kindled_iron_approve.yml`) | You approve one exact video -> `buffer/<id>.json` | No |
| 3 | **Kindled Iron 3 - Publish Everywhere** (`kindled_iron_publish.yml`) | Posts one approved video to its approved platforms | Yes, only this one |

## 1. Generate a video

GitHub Actions has no MP3 upload box, so the MP3 goes into the private repo first (an authenticated file
reference only you and the workflow token can read):

1. In `Venloud/kindled-iron-voice`, open `approved_audio/`, **Add file > Upload files**, and upload into a new
   folder named after the video id (lowercase words joined by `-`, e.g. `why-bugs-are-called-bugs`):
   - `narration.mp3`: your approved recording (used as-is, never regenerated; 5-180 s)
   - `script.txt`: the exact words you say (the director aligns them to the MP3)
   - optional `settings.json`: `{"theme": "blueprint", "character": "teen"}` (per-video look and narrator)
   - optional `post.txt`: the text that goes out with the video:
     ```
     title: Why Bugs Are Called Bugs
     caption: A moth, a log book and a joke that stuck. #history #tech
     description: Extra line for YouTube
     ```
     Without it the post uses the video title only.
2. Actions > **Kindled Iron 1 - Generate Video** > Run workflow > `video_id` = the folder name.

It checks the MP3 (real MP3 audio, sane length) and the script before any AI call, then directs, finds media
(your meme/still library, Pexels/Pixabay footage), renders, runs every gate and one vision review, and saves the
review package in `previews/<id>/`:

| File | What it is |
|---|---|
| `<id>.mp4` | the video |
| `video.json` | sha256, duration, gates, review verdict, `accepted` and why not |
| `<id>-8-frames.jpg`, `<id>-box_contact.jpg` | stills to review |
| `scene.json`, `plan.json`, `<id>.srt` | timing: every drawing, caption and media cue |
| `media.json` | every footage / meme / still: source, licence page, why it fits the line, what was turned down |
| `gates.json`, `review.json`, `<id>-meta.json` | quality results (coverage, audit, audio, scripture, voice) |
| `status.json`, `fail_report.md` | the latest run; a failed run explains what to fix |

One folder per video: a new video replaces the old one only when it is complete and accepted, or the old one
was not accepted either. A failed run never destroys the last accepted video.

**Runtime services and cost:** the director needs one AI planner (Gemini free tier first; GitHub Models, Groq,
Hugging Face, OpenRouter `:free`, Cloudflare as free fallbacks; at most 3 plan calls + 1 vision call per video, all
free-tier) and the Pexels/Pixabay free APIs for footage. No paid service is called. Without AI quota the run
waits (`waiting_quota`) and can be re-run after the reset.

## 2. Approve and add to the buffer

Watch `previews/<id>/<id>.mp4`. If it's right:

Actions > **Kindled Iron 2 - Approve and Add to Buffer** > Run workflow:
- `video_id` = the id, `confirm` = the same id typed again, optional `platforms` (e.g. `tiktok,youtube`).
- `list_only` shows every video and why it can or cannot be approved.

It is refused unless you are an allowed approver (repo variable `KI_APPROVERS`, default `Venloud`), the MP4 is
the one its manifest describes, every gate and the vision review passed (`accepted`), the narration MP3 is still
the one it was rendered from, the render's voice / scripture / audio checks pass, and the video is not buffered or
posted already. The approval goes to `buffer/<id>.json`: who, their GitHub id, the MP4's sha256, when, the run,
the platforms and the post text. If you never run this workflow the buffer stays empty.

## 3. Publish everywhere

Actions > **Kindled Iron 3 - Publish Everywhere** > Run workflow > `video_id` = the approved id.

Refused when the buffer is empty, the video is not approved, its MP4 changed after approval (sha256), or every
approved platform already has it. Each platform is connection-checked first (missing or expired credentials:
that platform is skipped and reported); one failing never stops the others; every post id and URL is written to
`approved/posted.json` at once. The run summary lists each platform's result and URL. If a platform failed, the
video stays in the buffer and re-running posts **only** the missing platforms; once all have it, the buffer
entry becomes `published`. `check_only` refreshes tokens and checks every connection without posting.

TikTok: the app may not post directly, so TikTok receives an **inbox draft** (open TikTok to finish the post);
the ledger says `draft`, not `live`.

## Videos approved before this system

`approved/index.json` lists renders approved before 2026-10-28 (Where Did God Come From, Love of Money v3,
Epicurean Paradox v3); all are in `approved/posted.json`. The publish workflow no longer reads that list.
