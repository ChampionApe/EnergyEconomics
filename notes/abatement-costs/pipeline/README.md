# Pipeline

Stages 2 and 3. There is no stage 1: this note has no external data.

    run_simple.py      model/ -> results/simple_*
    run_technical.py   model/ -> results/technical_*
    build.py           results/ -> writing/generated/

## `run_simple.py`

Section 1 on a grid of fossil energy use, from zero to the point where
consumption is back to zero. Writes the baseline curves, the marginal
abatement cost curve, the marginal damage curve and the optimum.

Two details are worth knowing, because both show up in a figure:

- The energy grid ends at $(\gamma/p_e)^{1/(1-\alpha)}$, which is where
  $C$ returns to zero. That endpoint is what makes figure 1.1 close.
- The marginal abatement cost is unbounded at $E = 0$, so the grid for it
  starts one step in. At that first point it is already an order of magnitude
  above the axis limit, so the curve still leaves the top of the frame and no
  infinity has to be plotted.

## `run_technical.py`

Section 2 on a grid of carbon prices $D'(M)$, running to twice the most
expensive technology's average cost so that the menu is fully deployed at the
top of the range.

The sweep variable is the carbon price rather than energy use, and that is the
one design decision in this script. Section 2's equations are simultaneous in
$E$ and the utilisation rates $a_i$, but every one of them is an explicit
function of $D'(M)$ — so fixing $D'(M)$ turns the system into four
assignments. The model is closed at the end by the one root-find that is left:
the price at which $D'(M)$ equals the marginal damage of the emissions that
price produces.

## `build.py`

**Reads only `results/`.** Two guards, because one is easy to route around:

- an import blocker on `sys.meta_path` that raises if anything imports
  `model`, which is how this stage usually turns into a solve — somebody
  reaches for a constant or an axis label;
- a `read()` helper that is the only way a file enters the script, refuses
  anything outside `results/`, and prints what it opened at the end of the run.

It emits five figures and `numbers.tex`, a file of LaTeX macros holding every
number the note could quote in prose. The note currently quotes none of them —
it is a note about shapes, not levels — but the file is loaded by `main.tex`
so that the first sentence that wants a number has somewhere to get it.

Set `FIGURE_PNG=/some/dir` to also write PNG copies of each figure, which is
convenient for checking layout without opening a PDF.

One trap worth knowing: LaTeX command names may contain letters only, so
generated macro names have their digits spelled out. Getting that wrong
produces an error several files away from the cause.
