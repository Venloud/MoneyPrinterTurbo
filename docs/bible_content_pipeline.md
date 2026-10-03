# Bible Content Pipeline

## Source rule

The production content system is restricted to the 66 canonical books listed in `content/bible/canonical_books.json`.

The system must not use the Apocrypha, Deuterocanon, Book of Enoch, Pseudepigrapha, later tradition, denominational material, archaeology, general internet knowledge, or model memory as biblical source material.

## Content lanes

1. Biblical storyline progression
2. One character per episode
3. One episode for each of Jesus' Twelve disciples
4. Jesus' teachings
5. Bible topics
6. Hard Bible questions
7. Passage and story deep dives

## Chronological rule

The storyline begins with:

Creation -> Adam -> Eve -> Cain -> Abel -> Seth -> Noah -> ...

The engine advances only after the current episode is recorded. It does not randomly select a character.

## Script rule

Each short video uses:

1. Hook
2. Short introduction
3. Scripture-grounded body
4. Very short call to action
5. Read-it-yourself end card

The CTA must not become a long interruption.

## Claim rule

Every biblical factual claim must be traceable to one or more supplied canonical Scripture references.

If Scripture does not establish a detail, the system must not invent it.

If Scripture gives little or no physical description of a person, the visual layer must use a neutral or minimal representation rather than inventing supposedly biblical appearance details.

## Visual rule

Visual prompts receive the biblical description available in the supplied passages. They may depict events and environments described by Scripture, but may not turn unstated appearance details into claimed biblical facts.

## First episode

Episode 1 is Creation, based on Genesis 1.

The next storyline episode is Adam.

## History

`storage/bible/content_history.json` records episode, references, fingerprint, and publication metadata. The fingerprint prevents the same episode from being selected twice.

## Production note

GitHub Actions schedules can run the automation, but the final render and direct platform publishing remain dependent on the configured video-generation and platform credentials. Scheduled workflows run from the default branch. See GitHub Actions documentation for scheduling behavior.
