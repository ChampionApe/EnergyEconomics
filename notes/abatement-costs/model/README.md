# Models

The abatement model behind the lecture note. **Published to students.**

Everything here is read by people learning from it, so it is written to be
read: named for what it does, documented at the level a reader needs to run
and modify it, no dead parameters and no commented-out alternatives. Work that
is not at that standard belongs in `../scratch/` until it is.

There is no optimisation solver anywhere in this directory. Both sections of
the note are closed form up to one scalar root, so the "instance size"
parameter the other notes need does not arise: every figure is a grid
evaluation and the whole pipeline runs in about a second.

## Contents

- `economy.py` — section 1. The `Economy` dataclass holds the five parameters
  ($\alpha$, $\gamma$, $p_e$, $\phi$, $\gamma_D$) and evaluates output,
  consumption, emissions, damages, the baseline $(E^0, C^0, M^0)$, abatement,
  the marginal abatement cost, and the optimum where marginal cost meets
  marginal damage. Figures 1.1–1.3 depend on it.
- `technologies.py` — section 2. A `Technology` is a potential $\theta_i$, an
  average cost $c_i$ and a cost dispersion $\sigma_i$; `TechnologyMenu`
  aggregates a set of them into $\sum_i\theta_i a_i$ and
  $\sum_i\theta_i f_i(a_i)$. `abatement_with_technology()` traces the whole
  extended model over a grid of carbon prices. Figures 2.1–2.2 depend on it.

## The log-normal closed form

`Technology.utilisation()` and `Technology.unit_cost()` are the two
expressions the note's appendix derives, used verbatim:

    a_i      = Phi( (ln(D'(M)/c_i) + sigma_i^2/2) / sigma_i )
    f_i(a_i) = c_i * Phi( (ln(D'(M)/c_i) - sigma_i^2/2) / sigma_i )

They are not a numerical solution of the first-order condition
$f_i'(a_i) = D'(M)$ — they *are* its solution, which is the point of the
appendix. Nothing here re-derives them, so if the appendix's assumption about
the cost distribution changes, these two lines change with it.

## Taking the carbon price as the parameter

`abatement_with_technology()` sweeps $D'(M)$ rather than solving for it. Every
other quantity is then an explicit function of the sweep variable, and the
system of equations in section 2 becomes four assignments. The marginal
abatement cost is recovered two ways — once as $D'(M)$ itself, once through
the note's own expression — and the two are asserted equal, which is the
cheapest available check that the code implements the algebra on the page.
