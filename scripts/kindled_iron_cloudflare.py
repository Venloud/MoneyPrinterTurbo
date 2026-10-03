#!/usr/bin/env python3
"""Generate Kindled Iron Genesis scenes and narration with Cloudflare Workers AI."""

import base64
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ACCOUNT = os.environ["CLOUDFLARE_ACCOUNT_ID"]
TOKEN = os.environ["CLOUDFLARE_API_TOKEN"]
ROOT = Path(os.environ.get("KINDLED_OUTPUT_DIR", "storage/bible/episode_001"))
SCENES_FILE = Path("content/bible/episodes/001_creation_scenes.json")
IMAGE_MODEL = os.environ.get("CLOUDFLARE_IMAGE_MODEL", "@cf/black-forest-labs/flux-2-dev")
TTS_MODEL = "@cf/deepgram/aura-2-en"
TTS_SPEAKER = os.environ.get("CLOUDFLARE_TTS_SPEAKER", "atlas")


def api_url(model):
    return f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/ai/run/{model}"


def multipart_body(fields):
    boundary = "----KindledIron" + uuid.uuid4().hex
    chunks = []
    for key, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


def generate_image(prompt, output):
    body, boundary = multipart_body({
        "prompt": prompt,
        "width": "1024",
        "height": "1792",
        "steps": "25",
        "guidance": "4",
    })
    req = urllib.request.Request(
        api_url(IMAGE_MODEL),
        data=body,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=900) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    image_b64 = payload.get("result", {}).get("image")
    if not image_b64:
        raise RuntimeError(f"Cloudflare image response missing result.image: {payload}")
    output.write_bytes(base64.b64decode(image_b64))


def generate_audio(text, output):
    payload = {
        "text": text,
        "speaker": TTS_SPEAKER,
        "encoding": "mp3",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        api_url(TTS_MODEL),
        data=data,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        audio = resp.read()
    if not audio:
        raise RuntimeError("Cloudflare TTS returned an empty response")
    output.write_bytes(audio)


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    data = json.loads(SCENES_FILE.read_text(encoding="utf-8"))
    style = data["style"]
    parts = [data["narration"]] + [s["narration"] for s in data["scenes"]] + [data["cta"], data["end_card"]]
    full_script = "\n\n".join(parts)
    (ROOT / "episode_001_story.txt").write_text(full_script + "\n", encoding="utf-8")

    print(f"Generating Aura 2 narration with speaker={TTS_SPEAKER}")
    generate_audio(full_script, ROOT / "narration.mp3")

    for scene in data["scenes"]:
        output = ROOT / f"scene_{scene['id']:02d}.png"
        print(f"Generating scene {scene['id']}: {scene['overlay']}")
        generate_image(f"{style} {scene['visual']}", output)

    (ROOT / "scenes.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Generated {len(data['scenes'])} Cloudflare scenes.")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"Cloudflare API error {exc.code}: {detail}", file=sys.stderr)
        raise
