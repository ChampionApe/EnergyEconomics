# Using AI in this course

Short version: **use it, and turn off autocomplete while you work the exercises.**

## What you are allowed to do

Everything. There is no AI restriction on the exercises or on your preparation.
Use whatever tools you like, as much as you like.

This is not permissiveness for its own sake. The exam is sat at the department,
on paper, without internet or AI. Nothing you do during the term is assessed
against an integrity rule, so there is nothing to enforce. What you do during the
term determines only one thing: whether you can do this material without help
when it counts.

## The thing worth being careful about

There is a well-documented gap between *watching a correct solution appear* and
*being able to produce one*. Reading a clear worked answer feels like learning.
It creates a strong sense of understanding, and that sense is largely
independent of whether you could reproduce the argument an hour later.

For a course assessed by an open-ended, closed-book exam, this is the failure
mode that matters. Students who worked every problem set with an AI answering
them do not arrive under-prepared in their own estimation — they arrive
confident and under-prepared, which is worse, because they stopped revising.

So the assistant in this repository is built to make you do the retrieval: it
starts with a question rather than an answer, and works up from there. Not to
withhold help — you can ask it for the answer at any point and it will give you
one. It defaults to questions because that is what transfers to the exam room.

## Turn off inline autocomplete for the exercises

This is the one concrete request in this document, and it matters more than
anything else here.

GitHub Copilot's **inline completions** — the grey ghost text that appears as you
type — will happily complete an entire exercise answer for you before you have
finished reading the question. They are not governed by the
instructions in this repository; those apply to Copilot **Chat** and agent mode,
not to completions. So the course assistant's behaviour has no effect on
autocomplete whatsoever.

Autocomplete is also the part of Copilot that is effectively unlimited on the
free student plan, while chat is metered. The cheapest surface is the one that
does the most damage to your preparation. Be deliberate about it.

**In VS Code:** click the Copilot status-bar icon and *Disable Completions* (you
can scope it to this workspace). Chat stays on.

Use chat instead. Typing your question out is itself part of the work — most of
the time you will locate your own confusion in the act of writing it down.

## What the assistant will not do

- Write hand-in text for you to submit as your own. It will critique a draft you
  wrote; it will not produce the draft.
- Tell you anything about exam content. It has no access to it.

## If you do not have Copilot or Claude

You are not disadvantaged. Every exercise in this course is completable with the
notes, the course material and no AI at all, and the exam is written on that
assumption. The assistant is a second route, never the only one.

If something in the material only makes sense after you ask an AI about it, that
is a bug in the material. Tell me and I will fix it.

## Feedback

If the assistant gives you something wrong, misleading, or maddening, please tell
me — open an issue on the repository or mention it in class. It is new this year
and I would like to know where it fails.
