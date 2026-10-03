#!/usr/bin/env python3
import json
import sys
from pathlib import Path

from faster_whisper import WhisperModel


def ts(seconds: float) -> str:
    total = max(0, int(round(seconds * 100)))
    h, rem = divmod(total, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def ass_color(hex_rgb: str) -> str:
    h = hex_rgb.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"&H00{b:02X}{g:02X}{r:02X}"


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: build_word_captions.py AUDIO_FILE OUTPUT_ASS LANGUAGE", file=sys.stderr)
        return 2

    audio_file = Path(sys.argv[1])
    output_ass = Path(sys.argv[2])
    language = sys.argv[3]

    if not audio_file.is_file():
        raise FileNotFoundError(audio_file)

    model = WhisperModel("base", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        str(audio_file),
        language=language,
        word_timestamps=True,
        vad_filter=True,
    )

    words = []
    for segment in segments:
        for word in segment.words or []:
            value = word.word.strip()
            if value:
                words.append({
                    "word": value,
                    "start": float(word.start),
                    "end": float(word.end),
                })

    if not words:
        raise RuntimeError("Whisper returned no word timestamps.")

    white = ass_color("FFFFFF")
    orange = ass_color("FF8A00")

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1080",
        "PlayResY: 1920",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,DejaVu Sans,46,{white},{white},&H80000000,&H00000000,1,0,0,0,100,100,0,0,1,3,1,2,60,60,180,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]

    chunk = []
    for word in words:
        chunk.append(word)
        if len(chunk) >= 4 or (word["end"] - word["start"]) >= 0.55:
            for i, active in enumerate(chunk):
                parts = []
                for j, item in enumerate(chunk):
                    color = orange if i == j else white
                    parts.append(f"{{\\c{color}}}{esc(item['word'])}")
                lines.append(
                    f"Dialogue: 0,{ts(active['start'])},{ts(active['end'])},Default,,0,0,180,,"
                    + " ".join(parts)
                )
            chunk = []

    if chunk:
        for i, active in enumerate(chunk):
            parts = []
            for j, item in enumerate(chunk):
                color = orange if i == j else white
                parts.append(f"{{\\c{color}}}{esc(item['word'])}")
            lines.append(
                f"Dialogue: 0,{ts(active['start'])},{ts(active['end'])},Default,,0,0,180,,"
                + " ".join(parts)
            )

    output_ass.parent.mkdir(parents=True, exist_ok=True)
    output_ass.write_text("\n".join(lines) + "\n", encoding="utf-8")

    Path(output_ass.with_suffix(".words.json")).write_text(
        json.dumps(words, indent=2), encoding="utf-8"
    )

    print(f"Created {output_ass} with {len(words)} word timestamps.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
