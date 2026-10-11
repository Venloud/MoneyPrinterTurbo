# Kindled Iron: writing scripts in batches

Write a week (or a month) of scripts at once, drop them in `kindled_iron/queue/`, and the daily run posts one
per day in file-name order. Nothing is written or changed by AI at run time.

## Files

- `kindled_iron/queue/NNN-<id>.json`: one finished script each. `NNN` sets the order (`001-`, `002-`, ...).
- `kindled_iron/queue/done/`: scripts that were posted (the daily run moves them; the built scene goes to `kindled_iron/scenes/<id>.json`).
- `kindled_iron/blocks/`: the scene blocks. `example_script.json` is a complete example (not queued).

## Script format

```json
{
 "id": "why-did-god-rest",                     // lowercase-with-dashes, unique forever (the ledger key)
 "title": "Why Did God Rest?",                 // YouTube title becomes "Why Did God Rest? #shorts"
 "post": {
  "caption": "If God never gets tired, why did he rest on day seven? #bible #god #faith #sabbath #christian",
  "threads": "optional; default = the question + 3 hashtags",
  "description": "optional; 'Scripture: World English Bible' is added automatically"
 },
 "lines": [
  {"block": "hook_question", "say": "[curious] If God never gets tired, why did he rest on day seven?",
   "slots": {"question_text": "GOD... TIRED?", "clip_query": "night sky stars", "point_word": "tired", "reaction_word": "rest"}}
 ]
}
```

(JSON has no comments: the `//` notes above are only for this page.)

## Rules the builder enforces (a broken script fails before any credit is spent)

- 4-14 lines (7-10 works best), 130-230 words in total; aim for 150-200 words = about 60-75 s at the measured 165 wpm.
- Caption = the hook question (ending in `?`) + 3-5 hashtags. YouTube: "<title> #shorts", not made for kids.
- Every `*_word` slot is a word of that same line (`God#2` = the second "God" in the line).
- A `scripture_card` quote is spoken word for word in its line AND is the World English Bible text (or a
  contiguous part of one verse). Check a verse: `python -c "from kindled_iron import scripture as s; print(s.verse_text('Mark 2:27'))"`.
- Optional slots (marked "optional") can be left out; their drawings are skipped.

## Writing rules (yours to keep)

- Line 1 is the question, under 2 s. Line 2 answers it (answer on screen by ~10 s).
- One idea per line. No filler, no long goodbye. Adults, simple words.
- `[tags]` steer the v4 voice: `[curious]`, `[matter-of-fact]`, `[light laugh]`, `[leaning in]`, `[warm]`, `[softer]`,
  `[firm]`, `[quiet, confident]`. `...` and `—` make pauses. Tags are never shown or captioned.
- Faith rules: no occult imagery; God is never drawn as a figure (GOD as a word or light).
- Stock clip queries: 2-4 plain nouns ("old bible open pages", "sunrise over mountains"); no people's faces as the point.

## Blocks

| Block | What it draws | Slots |
|---|---|---|
| `aside_popup` | A light aside / joke line: the guide shrugs, a popup lands on one word, a controller doodle fills the corner. | `popup_text`, `popup_word` |
| `big_answer` | The short answer as one huge word with a freeze-zoom (by 10 s). A Bible is drawn next to the guide. | `headline`, `answer_text`, `answer_word` |
| `closing` | Last line: a title lands, a sunrise clip and light burst, then two big closing words (GOD in the accent color works best). | `title_text`, `title_word`, `clip_query`, `final_1`, `final_1_word`, `final_2`, `final_2_word` |
| `concept_clip` | Explain one idea: a clip on one word, a big label and an accent sub-label, the guide looks up and points. | `clip_query`, `clip_word`, `label_text`, `label_word`, `sub_text`, `sub_word` |
| `hook_question` | Line 1. The hook question in a big popup over a clip; the guide points, a confused reaction pops up. | `question_text`, `clip_query`, `point_word`, `reaction_word` |
| `not_this` | 'Not X. Not Y. Z.': each wrong option is written and struck out on its word, then the right one lands big. | `items`, `final_text`, `final_word` |
| `scripture_card` | A Bible quote: a clip, then the scripture card while the quote is spoken (WEB-checked). The quote MUST be spoken word for word in the line. | `ref`, `verse`, `clip_query`, `note_text`, `note_word` |
| `three_examples` | Three everyday examples, each a real clip on its own word, then a conclusion in the accent color. | `headline`, `items`, `conclusion_text`, `conclusion_word` |
Between your anchors the builder adds small guide moves (look up, point, pulse, react) about every 5 words, so
the frame never sits still for more than ~2 s. New blocks: copy a block file, keep `{{id}}_` in front of every
object id, list every `{{slot}}` in `slots`.

## Batch routine

1. Write N scripts, numbered in posting order.
2. Check them all: `for f in kindled_iron/queue/*.json; do python -m kindled_iron.build_scene "$f" --out /tmp/x.json || break; done`
3. Commit and push to main.
4. Optional: run **Kindled Iron Daily** with `dry_run` on the first one to watch it (the voice is cached, so the
   real run re-uses it for 0 credits).

## Credits

Each video costs one ElevenLabs request. The guard counts the characters the voice reads x 1.3 (about 1,500 for a
190-word script) and keeps 3,000 in reserve (`kindled_iron/daily_config.json`); measured billing on eleven_v4 was
126 credits for 1,149 characters, so the guard is on the safe side. Low credits = the day is skipped, the script
stays queued and ntfy tells you.

## Turning the schedule on

When you say go: in `.github/workflows/kindled_iron_daily.yml` remove the two `#` in front of `schedule:` and the
cron line (14:40 UTC = 10:40 AM New York). Keep at least 7 scripts in the queue; ntfy warns at 3 or fewer.
