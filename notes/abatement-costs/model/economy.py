"""The stylised economy of section 1: fossil energy, output and damages.

One representative producer turns fossil energy $E$ into output with an
isoelastic technology, pays $p_e$ per unit of energy, and emits $\\phi$ tonnes
of CO2 per unit burned. Damages are quadratic in the stock of emissions.

    F(E) = gamma * E**alpha          output
    C(E) = F(E) - p_e * E            consumption, ignoring damages
    M(E) = phi * E                   emissions
    D(M) = damage_curvature * M**2 / 2

Three quantities follow, and they are the whole of section 1:

    the baseline        E0 maximises C, and M0 = phi * E0
    abatement           A = M0 - M, so cutting energy is the only way to abate
    marginal abatement  MAC = (F'(E) - p_e) / phi

The optimum internalising damages solves MAC = D'(M).

Everything here is closed form except the optimum, which is one root of a
scalar equation. Nothing is solved numerically that does not have to be.
"""

from dataclasses import dataclass

import numpy as np
from scipy import optimize


@dataclass(frozen=True)
class Economy:
    """Parameters of the section 1 model.

    The defaults are the ones the note's figures use. They are illustrative:
    the units are nominal ("ton CO2", "EUR/ton CO2") and the point of the
    model is the shape of the curves, not the levels.
    """

    output_elasticity: float = 0.5      # alpha, the exponent on E in F(E)
    productivity: float = 1.0           # gamma, the level of F(E)
    energy_price: float = 1.0           # p_e, the cost of extracting one unit
    emission_intensity: float = 0.25    # phi, tonnes of CO2 per unit of E
    damage_curvature: float = 100.0     # gamma_D in D(M) = gamma_D M^2 / 2

    # -- production and consumption -------------------------------------
    def output(self, energy):
        """F(E)."""
        return self.productivity * np.power(energy, self.output_elasticity)

    def marginal_product(self, energy):
        """F'(E). Unbounded as E approaches zero, which is why the marginal
        abatement cost curve is vertical at full abatement."""
        return (self.productivity * self.output_elasticity
                * np.power(energy, self.output_elasticity - 1.0))

    def consumption(self, energy):
        """C = F(E) - p_e E. Damages are not subtracted here."""
        return self.output(energy) - self.energy_price * energy

    def consumption_net_of_damages(self, energy):
        """The objective of the planner who internalises the externality."""
        return self.consumption(energy) - self.damages(self.emissions(energy))

    # -- emissions and damages ------------------------------------------
    def emissions(self, energy):
        """M = phi E."""
        return self.emission_intensity * energy

    def damages(self, emissions):
        """D(M)."""
        return self.damage_curvature * np.square(emissions) / 2.0

    def marginal_damages(self, emissions):
        """D'(M), the social cost of carbon in this model."""
        return self.damage_curvature * emissions

    # -- the baseline ----------------------------------------------------
    def baseline_energy(self):
        """E0, the unregulated optimum: F'(E) = p_e."""
        return (self.productivity * self.output_elasticity
                / self.energy_price) ** (1.0 / (1.0 - self.output_elasticity))

    def baseline_consumption(self):
        """C0."""
        return self.consumption(self.baseline_energy())

    def baseline_emissions(self):
        """M0, the emissions that abatement is measured against."""
        return self.emissions(self.baseline_energy())

    # -- abatement -------------------------------------------------------
    def abatement(self, energy):
        """A = M0 - M(E). Negative for E above the baseline."""
        return self.baseline_emissions() - self.emissions(energy)

    def marginal_abatement_cost(self, energy):
        """MAC = (F'(E) - p_e) / phi.

        The numerator is the output given up by burning one unit less; the
        denominator turns that unit into tonnes. Zero at the baseline by
        construction, and rising as abatement bites into productive energy use.
        """
        return (self.marginal_product(energy) - self.energy_price) \
            / self.emission_intensity

    # -- the optimum with damages ---------------------------------------
    def optimal_energy(self):
        """E* solving MAC = D'(M), i.e. F'(E) - p_e = gamma_D phi^2 E.

        Bracketed rather than started from a guess: the left-hand side is
        unbounded as E falls to zero and is exactly zero at the baseline,
        where the right-hand side is positive, so a root always sits strictly
        between the two and Brent's method finds it without a starting point.
        """
        baseline = self.baseline_energy()

        def excess(energy):
            return (self.marginal_abatement_cost(energy)
                    - self.marginal_damages(self.emissions(energy)))

        return optimize.brentq(excess, 1e-12 * baseline, baseline)

    def optimum(self):
        """The optimal allocation, as a dictionary of scalars."""
        energy = self.optimal_energy()
        emissions = self.emissions(energy)
        return {
            "energy": energy,
            "consumption": self.consumption_net_of_damages(energy),
            "emissions": emissions,
            "abatement": self.abatement(energy),
            "carbon_price": self.marginal_abatement_cost(energy),
        }
