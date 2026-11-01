"""Human--silicon survey research prototype.

The public API deliberately separates simulation, calibration and design.
"""

from .scenario import make_scenario, scenario_to_json
from .solver import solve_design

__all__ = ["make_scenario", "scenario_to_json", "solve_design"]
