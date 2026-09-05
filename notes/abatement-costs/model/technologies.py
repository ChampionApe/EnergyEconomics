"""Technical abatement: a menu of end-of-pipe technologies (section 2).

Each technology $i$ removes emissions rather than avoiding them. It is
described by three numbers:

    potential          theta_i, the share of emissions it could remove
    average_cost       c_i, its average cost per tonne at full utilisation
    cost_dispersion    sigma_i, how spread out its unit costs are

Utilisation is $a_i = A_i / (\\theta_i M) \\in [0, 1]$ and costs are
$AC_i = \\theta_i M f_i(a_i)$ for a convex $f_i$. Writing costs this way makes
the problem scale-invariant, so $f_i$ depends on the utilisation rate alone.

The note's appendix works out the case where the unit costs inside a
technology are log-normally distributed with mean cost $c_i$. Optimal
utilisation and the cost of achieving it are then both standard normal
distribution functions of the ratio $\\lambda_i = D'(M) / c_i$:

    a_i      = Phi( (ln(lambda_i) + sigma_i^2 / 2) / sigma_i )
    f_i(a_i) = c_i * Phi( (ln(lambda_i) - sigma_i^2 / 2) / sigma_i )

Both are used here exactly as the appendix states them. No optimisation is
run: the closed form *is* the first-order condition f_i'(a_i) = D'(M).

The module takes the marginal damage D'(M) as its argument throughout, since
that is the single price every technology responds to.
"""

from dataclasses import dataclass

import numpy as np
from scipy import stats

from model.economy import Economy


@dataclass(frozen=True)
class Technology:
    """One abatement technology on the menu."""

    name: str
    potential: float          # theta_i, share of emissions it can remove
    average_cost: float       # c_i, average cost per tonne at full use
    cost_dispersion: float    # sigma_i, dispersion of unit costs within it

    def utilisation(self, marginal_damages):
        """a_i*, the share of the technology's potential that is used.

        Rises from zero to one as the carbon price passes through c_i; how
        sharply is governed by sigma_i, so a technology with tightly clustered
        unit costs switches on almost as a step.
        """
        return _normal_cdf(self._z(marginal_damages, +0.5))

    def unit_cost(self, marginal_damages):
        """f_i(a_i*), the average cost per tonne of the potential deployed.

        Converges to c_i as utilisation approaches one, which is what makes
        c_i readable as "the average cost of this technology".
        """
        return self.average_cost * _normal_cdf(self._z(marginal_damages, -0.5))

    def _z(self, marginal_damages, half_variance_sign):
        """The standard normal argument shared by both expressions above."""
        sigma = self.cost_dispersion
        ratio = np.divide(np.asarray(marginal_damages, dtype=float),
                          self.average_cost)
        with np.errstate(divide="ignore"):
            log_ratio = np.log(ratio)
        return (log_ratio + half_variance_sign * sigma ** 2) / sigma


def _normal_cdf(z):
    """Phi(z), with -inf (a zero carbon price) mapped to zero rather than nan."""
    return np.where(np.isneginf(z), 0.0, stats.norm.cdf(np.nan_to_num(z)))


class TechnologyMenu:
    """The set of technologies available, and what they do together."""

    def __init__(self, technologies):
        self.technologies = list(technologies)
        total = sum(t.potential for t in self.technologies)
        if not 0.0 < total < 1.0:
            raise ValueError(
                f"the potentials sum to {total:.3f}; section 2 assumes "
                "0 < sum(theta_i) < 1, so that some emissions always remain")

    def __iter__(self):
        return iter(self.technologies)

    @property
    def total_potential(self):
        """sum(theta_i): the share of emissions the menu could remove in full."""
        return sum(t.potential for t in self.technologies)

    def abated_share(self, marginal_damages):
        """sum_i theta_i a_i, the share of emissions actually removed."""
        return sum(t.potential * t.utilisation(marginal_damages)
                   for t in self.technologies)

    def cost_share(self, marginal_damages):
        """sum_i theta_i f_i(a_i), the cost of that removal per tonne emitted."""
        return sum(t.potential * t.unit_cost(marginal_damages)
                   for t in self.technologies)

    def marginal_cost_of_emissions(self, marginal_damages):
        """The right-hand side of the note's condition for optimal energy use.

            D'(M) (1 - sum_i theta_i a_i) + sum_i theta_i f_i(a_i)

        Damages are only borne on the emissions that survive abatement, but
        the abatement itself has to be paid for. Below the menu's own costs
        the two effects cancel and this lies on the 45-degree line; above
        them it falls away from it, and the gap is what technology buys.
        """
        return (marginal_damages * (1.0 - self.abated_share(marginal_damages))
                + self.cost_share(marginal_damages))


#: The three technologies the note's figures use. Deliberately spread out in
#: cost (0.5, 2 and 5 EUR per tonne) so that the menu switches on in three
#: visible steps, and in dispersion so that C switches on more abruptly than B.
NOTE_MENU = TechnologyMenu([
    Technology("A", potential=0.1, average_cost=0.5, cost_dispersion=0.10),
    Technology("B", potential=0.2, average_cost=2.0, cost_dispersion=0.20),
    Technology("C", potential=0.3, average_cost=5.0, cost_dispersion=0.05),
])


def abatement_with_technology(economy: Economy, menu: TechnologyMenu,
                              marginal_damages):
    """Trace the whole model over a grid of carbon prices D'(M).

    Taking D'(M) as the parameter rather than solving for it turns a system
    of equations into four assignments, because every other quantity is an
    explicit function of it:

        X = D'(M)(1 - sum theta_i a_i) + sum theta_i f_i(a_i)   marginal cost
        E = (alpha gamma / (phi X + p_e)) ** (1 / (1 - alpha))  from F'(E)
        M = phi E (1 - sum theta_i a_i)                         net emissions
        A = M0 - M                                              abatement

    and the marginal abatement cost at that point is D'(M) itself.

    Returns a dictionary of arrays, one entry per column of the figures.
    """
    marginal_damages = np.asarray(marginal_damages, dtype=float)
    abated = menu.abated_share(marginal_damages)
    cost = menu.cost_share(marginal_damages)
    marginal_cost = menu.marginal_cost_of_emissions(marginal_damages)

    alpha = economy.output_elasticity
    energy = np.power(
        economy.output_elasticity * economy.productivity
        / (economy.emission_intensity * marginal_cost + economy.energy_price),
        1.0 / (1.0 - alpha))
    emissions = economy.emission_intensity * energy * (1.0 - abated)

    # The note derives the marginal abatement cost as
    #   (F'(E) - p_e) / (phi (1 - sum theta a)) - sum theta f / (1 - sum theta a)
    # and it collapses to D'(M) exactly. Computing it the long way and
    # checking is the cheapest available test that the algebra above is the
    # algebra in the note.
    long_way = (marginal_cost - cost) / (1.0 - abated)
    np.testing.assert_allclose(long_way, marginal_damages, atol=1e-10)

    return {
        "marginal_damages": marginal_damages,
        "abated_share": abated,
        "cost_share": cost,
        "marginal_cost_of_emissions": marginal_cost,
        "energy": energy,
        "emissions": emissions,
        "abatement": economy.baseline_emissions() - emissions,
        "marginal_abatement_cost": marginal_damages,
    }
