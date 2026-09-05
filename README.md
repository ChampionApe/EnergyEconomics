# Energy Economics of the Green Transition

Course material for *Energy Economics of the Green Transition*, MSc in
Economics, University of Copenhagen.

## What is here

| | |
|---|---|
| [`INSTALL.md`](INSTALL.md) | Setting up Python, if you want a walkthrough |
| [`AI-POLICY.md`](AI-POLICY.md) | Using AI in this course — **please read this** |
| [`environment.yml`](environment.yml) | The packages the material needs |
| [`CURRICULUM.md`](CURRICULUM.md) | The reading list, and where to find the papers |

### Lecture notes, and the code behind them

| | |
|---|---|
| [`notes/abatement-costs.pdf`](notes/abatement-costs.pdf) | **A Simple Model of Abatement Costs** — the short introductory note; start here |
| [`notes/abatement-costs/`](notes/abatement-costs/) | The model and scripts behind that note's figures |
| [`notes/technologies.pdf`](notes/technologies.pdf) | **Generation Technologies** — what each machine is and what it costs |
| [`notes/technologies/`](notes/technologies/) | The data and scripts behind that note's figures |
| [`notes/energy-system-models.pdf`](notes/energy-system-models.pdf) | **Energy System Models** — the course's main quantitative note |
| [`notes/energy-system-models/`](notes/energy-system-models/) | Every model, dataset and script behind it |
| [`notes/energy-system-models/notebooks/`](notes/energy-system-models/notebooks/) | Instructional notebooks — the way in to the models |

Read them in that order.

*A Simple Model of Abatement Costs* is eleven pages and the place to start.
Its section 2 framework comes back in the exercise classes.

*Generation Technologies* is a catalogue rather than an argument: read it once,
then use it as a lookup — Appendix C is a glossary written for exactly that.
It solves nothing and asks you to run nothing.

*Energy System Models* is the long one, and the one the course is built
around. It explains the economics and deliberately says nothing about
code. Everything about running the models — installing, reproducing any figure
or table, and exploring further — lives in
[the note's README](notes/energy-system-models/README.md) and in the
notebooks beside it. Start with `00-start-here.ipynb`.

**Nothing in the note requires you to run anything.** The notebooks are there
for the things that are easier to learn by turning a knob.

Course material is added during the term. If you cloned with git, `git pull`
brings you up to date.

## Requirements

Python 3.11 or newer and the packages listed in
[`environment.yml`](environment.yml).

**If you already have a working Python setup, use it.** Nothing here depends on
a particular installation method, editor, or environment manager. If you would
rather have a route that is known to work, [`INSTALL.md`](INSTALL.md) gives one.

## The course assistant

This repository ships an AI teaching assistant. It knows the course material and
the model code, and it is set up to help you learn rather than to hand you
answers — [`AI-POLICY.md`](AI-POLICY.md) explains what it does and why.

It works with **GitHub Copilot**, free for verified students through the
[GitHub Student Developer Pack](https://education.github.com/pack), and with
**Claude Code**. Both read the same configuration from this repository, so there
is nothing to install beyond the tool itself: clone the repo, open it, and the
assistant is there.

Ask it things directly, or use:

| | |
|---|---|
| `/hint` | One nudge on the problem you are stuck on |
| `/exercise-coach` | Work through a problem you are stuck on |
| `/model-explainer` | What a piece of model code means economically |
| `/check-my-reasoning` | Critique an argument you have written |
| `/debug-my-setup` | Installation, environment and import problems |
| `/exam-prep` | Practice problems and closed-book drilling |

**One request:** turn off Copilot's inline autocomplete while you work on
exercises, and use chat instead. [`AI-POLICY.md`](AI-POLICY.md) explains why —
it is the most useful thing in that document.

Everything in this course can be done without any of this. If you do not have
Copilot or Claude, you are not at a disadvantage.

## Problems

Open an issue on this repository, or raise it in class. That includes problems
with the assistant — it is new this year and I want to know where it fails.
