# Installing

The following lists things that are useful to install or setup for the
numerical/code part of the repository to work. They are guides and suggestions,
if you have your own setup that works - that is fine as well.

## Python

The minimum requirement is that you have:
- Python 3.11 or newer,
- and the packages listed in [`environment.yml`](environment.yml).

Here are a few suggestions of ways to set this up, if you don't have a preferred route:

### With conda

If you have no strong preference, this is the path with the fewest ways to go
wrong, and it is what I can help you debug fastest.

Install the [Anaconda distribution](https://www.anaconda.com/download) with
default settings, then from the repository folder:

```
conda env create -f environment.yml
conda activate EE2026
```

`conda activate EE2026` again in each new terminal session.

### With venv and pip

If you already work this way, keep working this way.

```
python -m venv .venv
```

Activate it — `.venv\Scripts\activate` on Windows, `source .venv/bin/activate`
on macOS and Linux — then install the packages named under `dependencies:` in
[`environment.yml`](environment.yml).

### With anything else

uv, poetry, pixi, a system Python you manage yourself — all fine. Read the
dependencies out of `environment.yml` and install them your way.

## Checking that it works

```
python -c "import pandas, numpy, scipy, pypsa, highspy; print('ok')"
```

If that prints `ok`, you are set up.

## Getting the repository

Use some Git tool to clone the repository (any will do):

- `git clone https://github.com/ChampionApe/EnergyEconomics.git`
- [GitHub Desktop](https://desktop.github.com/) — **Code** → **Open with GitHub Desktop**

Material is likely added and corrected during the term, so a simple command like `git pull`
will pick up changes for you (or clicking `pull` in Github Desktop).

## AI setup - Github Copilot - AI assistant

If you do not subscribe to the latest Claude or Mistral setup, no worries.
As a student at UCPH, you are at least eligible for GitHub Copilot's free
student plan (see steps below). This should provide enough tokens/usage to
allow you to engage with the course assistant (see [`AI-POLICY.md`](AI-POLICY.md))
to explore the course material.

Do this early in the term — verification is not always instant.
GitHub redesigns these pages from time to time, so the wording may not match
exactly; the sequence does.

1. **Get a GitHub account, with your KU email on it.** If you already have one,
   add your university address (`...@alumni.ku.dk` or your `@ku.dk` address) under
   [Settings → Emails](https://github.com/settings/emails) and verify it. This is
   what proves you are a student, so it has to be on the account before you apply.

2. **Apply for the Student Developer Pack.** Go to
   [education.github.com/pack](https://education.github.com/pack) and choose *Get
   student benefits*. You will be asked for your school (University of Copenhagen),
   your KU email, and usually a photo of your student ID or a proof of enrolment
   from [selvbetjening.ku.dk](https://selvbetjening.ku.dk). Approval takes anything
   from a few minutes to a few days.

3. **Turn Copilot on.** Once the pack is approved, Copilot Pro is included at no
   cost. Enable it at [github.com/settings/copilot](https://github.com/settings/copilot).
   You can check it is active there: the page should say your plan comes from
   GitHub Education rather than a trial.

4. **Install the extension in your editor.** In VS Code, open the Extensions panel
   and install **GitHub Copilot** — this pulls in **GitHub Copilot Chat**, which is
   the part that matters here — then sign in with the same GitHub account when
   prompted. JetBrains IDEs, Visual Studio and Xcode have equivalent plugins if you
   prefer one of those.

5. **Open this repository as a folder in the editor.** That is the whole setup for
   the course assistant. Copilot Chat reads `CLAUDE.md` at the root of the repo and
   the skills in `.claude/skills/`, so the commands in the README — `/hint`,
   `/exercise-coach`, `/model-explainer`, `/check-my-reasoning`, `/debug-my-setup`,
   `/exam-prep` — appear in the chat's slash menu. Nothing else to install, and
   nothing to configure.

6. **Turn off inline completions while you work on exercises.** Click the Copilot
   icon in the VS Code status bar and choose *Disable Completions*.
   [`AI-POLICY.md`](AI-POLICY.md) explains why this is the single most useful thing
   in this document.

Two things worth knowing. Chat and agent requests are **metered** on the free plan
while autocomplete is effectively unlimited — so ask targeted questions rather than
asking the assistant to read half the repository, and it will last you the term.
And if the pack is refused or you would rather not use any of this, everything in
the course can be done without it; nothing depends on having an assistant.

## Numerical solvers: Gurobi or HiGHS

Everything in the course solves with HiGHS, and at the default instance
sizes it does so pretty quickly. The note's own figures in sections 6-9
take longer (up to hours on HiGHS) and several times less on
[Gurobi](https://www.gurobi.com/), a commercial solver that is **free for
students**. This is how to set that up instead:

1. Register at [gurobi.com/academia](https://www.gurobi.com/academia/academic-program-and-licenses/)
   with your KU email address and request a *named-user academic licence*.
   It is free, valid for a year, and renewable.
2. Install it into your course environment. The course only ever calls
   Gurobi from Python, so the Python package is the whole installation —
   there is no separate program to download:

   ```
   pip install gurobipy
   ```

   or, in the conda environment, `conda install -c gurobi gurobi`. On its
   own the package comes with a trial licence limited to 2000 variables.
3. Activate the licence. The licence page gives you a `grbgetkey` command
   with your key in it; run it in the same environment while you are on
   the university network (on campus, or through the KU VPN). Afterwards
   the licence works anywhere.
4. Tell the course models to use it. The network models read one environment
   variable and default to HiGHS when it is unset:

   ```
   export ESM_SOLVER=gurobi          # macOS, Linux, Git Bash
   $env:ESM_SOLVER = "gurobi"        # PowerShell
   ```

   Set it in the terminal you launch Jupyter or the scripts from.


## When it goes wrong

Setup problems are not part of the course and you should not spend an evening on
them. Ask the course assistant — `/debug-my-setup` is built for exactly this and
will give you direct answers rather than questions. Failing that, ask me.

If the problem turns out to be in the course material — a package that will not
install, a file that is missing — please report it. That is a bug and I want to
know.
