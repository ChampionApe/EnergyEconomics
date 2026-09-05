# Installing

**You do not have to follow this guide.** If you already have Python and can
install packages, use whatever you normally use — nothing in this course depends
on a particular installation method, and a setup you understand is worth more
than one you copied.

This is here for anyone who wants a route that is known to work.

## What you actually need

- Python 3.11 or newer
- The packages listed in [`environment.yml`](environment.yml)
- A copy of this repository

That is the whole requirement. Everything below is one way of arriving at it.

## Getting the repository

Any of these is fine:

- `git clone https://github.com/ChampionApe/EnergyEconomics.git`
- [GitHub Desktop](https://desktop.github.com/) — **Code** → **Open with GitHub Desktop**
- **Code** → **Download ZIP**, if you would rather not use git at all

Git is worth it if you are comfortable with it, because material is added and
corrected during the term and `git pull` picks that up. With the ZIP you will
need to download again when things change. Neither is required.

## Installing the packages

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

## Checking it worked

```
python -c "import pandas, numpy, scipy, pypsa, highspy; print('ok')"
```

If that prints `ok`, you are set up.

`pypsa` is the energy system modelling package the course is built on, and
`highspy` is the solver it uses — that one is worth checking explicitly, because
it is the piece that does the actual optimisation and the piece most likely to
be missing if something went wrong during installation. You do not need to
install a commercial solver such as Gurobi or CPLEX; nothing in the course
requires one. If you want one anyway, the next section says how.

## Optional: Gurobi

Everything in the course solves with HiGHS, and at the default instance
sizes it does so in seconds. The larger instances behind the modelling
note's own figures — the twelve-zone network models of sections 6 to 9 at
their full size — take minutes to hours on HiGHS and several times less on
[Gurobi](https://www.gurobi.com/), a commercial solver that is **free for
students**. Worth it if you plan to run those instances at full size or to
use these models in a thesis; not worth an evening otherwise.

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
   own the package comes with a trial licence limited to 2000 variables,
   which the network models exceed — hence step 1.
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

   Set it in the terminal you launch Jupyter or the scripts from. The
   results are the same solution and the same prices; only the time changes.

If any of this fights you, skip it. HiGHS is the supported route and the one
every figure in the course can be reproduced with.

## Editor

Whatever you like. [VS Code](https://code.visualstudio.com/) is a reasonable
default if you have no preference, and it is where GitHub Copilot works best if
you plan to use the course assistant — see [`AI-POLICY.md`](AI-POLICY.md).

If you use VS Code, make sure it is pointed at the environment you created:
**Ctrl/Cmd + Shift + P** → *Python: Select Interpreter*. Choosing the wrong
interpreter is the single most common cause of "it says the package isn't
installed but I installed it".

## When it goes wrong

Setup problems are not part of the course and you should not spend an evening on
them. Ask the course assistant — `/debug-my-setup` is built for exactly this and
will give you direct answers rather than questions. Failing that, ask me.

If the problem turns out to be in the course material — a package that will not
install, a file that is missing — please report it. That is a bug and I want to
know.
