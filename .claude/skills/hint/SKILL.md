---
name: hint
description: >
  Give the student exactly one nudge on the problem they are stuck on, then stop
  and wait. Use when they ask for a hint, say they are stuck, or invoke /hint.
  Deliberately gives less than a full explanation.
user-invocable: true
argument-hint: "[what you're stuck on]"
---

# Hint

One rung. Then stop.

## What this does

The student wants to keep working, not to be handed the problem. Give them the
smallest thing that unblocks them and get out of the way.

## How

1. **Find out where they actually are.** If you do not know what they have
   already tried, ask — one question, then wait. Do not guess and hint at the
   wrong thing; a hint aimed at the wrong misunderstanding is worse than no hint,
   because they will chase it.

2. **Give one rung above where they are stuck.** If they have not started:
   orient them (what kind of problem is this, what is the relevant part of the
   course). If they have a setup but no progress: name the concept or constraint
   they are missing. If they have an approach that is going wrong: point at the
   step where it goes wrong, without correcting it.

3. **Stop.** Do not follow the hint with the next hint. Do not add "and then
   you'll want to...". End with an invitation to come back — *"try that and tell
   me what you get"* — and wait.

## Length

Two or three sentences. A hint that runs to a paragraph is an explanation
wearing a disguise.

## Escalating

If they come back having tried it and still stuck, give the next rung. Repeat.
Each round is a rung, and each round they get more.

If they ask for the answer outright, give it — fully, with reasoning. See the
help ladder in `CLAUDE.md`.

## Not for plumbing

If they are stuck on a `KeyError`, a broken environment, a plot that will not
render, or how to call a function in the course code — this is not the skill for it.
Just fix it, completely, and hand it back. Use `/debug-my-setup` if it is
environment trouble.

The same goes for code they want written. A hint is about the economics; code is
not rationed in this course and is never withheld a rung at a time. If what they
actually need is the script, write the script.
