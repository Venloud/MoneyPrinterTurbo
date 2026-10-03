#!/usr/bin/env python3
"""Bible-only content planner and first-episode validator.

This layer deliberately does not invent Scripture. It manages canonical scope,
chronological progression, content history, claim metadata, and concise video
structure before the existing video renderer is invoked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIBLE_DIR = ROOT / "content" / "bible"
STATE_DIR = ROOT / "storage" / "bible"
STATE_FILE = STATE_DIR / "content_history.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def fingerprint(item: dict) -> str:
    stable = {
        "title": item.get("title"),
        "type": item.get("type"),
        "references": item.get("references", []),
        "next_episode": item.get("next_episode"),
    }
    return hashlib.sha256(
        json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:16]


def validate_canon() -> None:
    data = load_json(BIBLE_DIR / "canonical_books.json")
    books = data["books"]
    if len(books) != 66 or len(set(books)) != 66:
        raise SystemExit("Bible canon validation failed: expected exactly 66 unique books")

    topics = load_json(BIBLE_DIR / "topics.json")
    sequence = load_json(BIBLE_DIR / "story_sequence.json")

    allowed = set(books)
    for section in topics.get("categories", {}).values():
        if not isinstance(section, list):
            raise SystemExit("Invalid topic configuration")

    for entry in sequence["opening"]:
        for ref in entry["references"]:
            book = ref.rsplit(" ", 1)[0]
            if ref.startswith(("1 ", "2 ", "3 ")):
                parts = ref.split()
                book = " ".join(parts[:-1])
            elif " " in ref:
                book = ref.rsplit(" ", 1)[0]
            if book not in allowed:
                raise SystemExit(f"Non-canonical source detected: {ref}")


def load_history() -> dict:
    if not STATE_FILE.exists():
        return {"published": [], "next_story_order": 1}
    return load_json(STATE_FILE)


def save_history(history: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def prepare_episode(number: int) -> dict:
    episode_path = BIBLE_DIR / "episodes" / f"{number:03d}_creation.json"
    if number != 1 or not episode_path.exists():
        raise SystemExit(f"Episode {number} is not implemented in the first build")

    episode = load_json(episode_path)
    history = load_history()
    existing = {x.get("fingerprint") for x in history.get("published", [])}

    fp = fingerprint(episode)
    if fp in existing:
        raise SystemExit("Episode already recorded. Refusing duplicate first post.")

    episode["fingerprint"] = fp
    episode["source_policy"] = "66 canonical Bible books only"
    episode["status"] = "ready_for_render"
    return episode


def record_episode(episode: dict, publication: dict | None = None) -> None:
    history = load_history()
    history.setdefault("published", []).append(
        {
            "episode": episode["episode"],
            "title": episode["title"],
            "type": episode["type"],
            "references": episode["references"],
            "fingerprint": episode["fingerprint"],
            "published": bool(publication),
            "publication": publication or {},
        }
    )
    history["next_story_order"] = episode["episode"] + 1
    save_history(history)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", type=int, default=1)
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args()

    validate_canon()
    episode = prepare_episode(args.episode)

    output = ROOT / "storage" / "bible" / f"episode_{args.episode:03d}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(episode, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if args.record:
        record_episode(episode)

    print(json.dumps(episode, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
