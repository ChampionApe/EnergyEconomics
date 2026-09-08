# Using AI in this course

Short version: **use it, let it write your code if you would rather not, and
turn off autocomplete when you are writing prose.**

## What you are allowed to do

Everything. There is no AI restriction on the exercises or on your preparation.
Use whatever tools you like, as much as you like.

This is not permissiveness for its own sake. The exam is sat at the department,
closed book, without internet or AI. Nothing you do during the term is assessed
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

So on the economics, the assistant in this repository is built to make you do the
retrieval: it starts with a question rather than an answer, and works up from
there. Not to withhold help — you can ask it for the answer at any point and it
will give you one. It defaults to questions because that is what transfers to the
exam room.

On code it does the opposite, and the next section explains why.

## You do not have to learn Python

This is a course in economics. Programming is a tool it uses, not a subject it
teaches, and there is no code at the exam — you will not be asked to write any,
read any, or explain any.

So if you would rather not spend this term learning Python, don't. Ask the
assistant to write the code and to run it, and it will: no argument, no asking
you to try it yourself first, no making you ask twice. Tell it once that this is
how you want to work and it will keep working that way.

Two things stay yours either way, and they are the two the exam is about:

- **Guessing the answer before you see it.** The assistant will ask you what you
  expect the result to look like before it shows you. One sentence. Do not skip
  it — it is most of what the exercise is for.
- **Saying what it means.** Why the constraint binds, what the shadow price is
  telling you, what moves when the carbon price rises. Here the assistant will
  keep asking you questions rather than handing over answers, because this is the
  part you need to be able to do alone.

Learning some Python is still worth doing if you want to — it is a useful skill
and the models are more legible from the inside. If that is what you want, say so
and the assistant will stay out of your way instead.

## Turn off inline autocomplete when you write prose

This is the one concrete request in this document.

GitHub Copilot's **inline completions** — the grey ghost text that appears as you
type — are not governed by anything in this repository. The course assistant's
instructions reach Copilot **Chat** and agent mode; they have no effect on
completions whatsoever.

For code that no longer matters much: if you want the code written for you, ask,
and you will get something better than a guess from a model that cannot see what
you are trying to do. Prose is the problem. When you are writing out what a
result means — in a notebook cell, in your notes, in a draft answer — ghost text
will finish the sentence for you, and that sentence is precisely what the exam
asks you to produce unaided. Watching a plausible interpretation appear feels
like having had the thought. It is not the same thought, and the difference only
becomes visible in the exam room, which is too late to discover it.

**In VS Code:** click the Copilot status-bar icon and *Disable Completions* (you
can scope it to this workspace). Chat stays on.

Use chat instead. Typing your question out is itself part of the work — most of
the time you will locate your own confusion in the act of writing it down.

## What the assistant will not do

- Write hand-in text for you to submit as your own. It will critique a draft you
  wrote; it will not produce the draft. This is about your written economics, not
  your code — it will write as much Python as you like.
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
