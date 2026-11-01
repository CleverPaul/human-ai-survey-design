"""Open-source SCIP solution of the same fixed-Q survey design model.

SCIP requires a linear objective.  The single quadratic constraint
``sum((G @ w)**2) <= t`` is its exact epigraph, where ``G.T @ G = Q``.
Transport/CDF constraints are shared with the other solver backends.
PySCIPOpt is imported only when this backend is requested.
"""

from __future__ import annotations

import math

import numpy as np


def solve_scip(sc, budget, tolerance, time_limit):
    """Return the common backend result, including SCIP's global dual bound."""
    from pyscipopt import Model, quicksum

    # A local import avoids a mandatory PySCIPOpt dependency and an import cycle.
    from .solver import _gram, _weight_problem

    nh, nt, n = len(sc["x_h"]), len(sc["x_t"]), len(sc["Q"])
    problem = _weight_problem(sc, np.arange(n), tolerance)
    gram = _gram(sc["Q"])
    model = Model("silicon_survey_fixed_Q")
    try:
        model.hideOutput()
        model.setRealParam("limits/time", time_limit)
        model.setRealParam("limits/gap", 1e-7)
        model.setRealParam("numerics/feastol", 1e-9)
        model.setIntParam("parallel/maxnthreads", 1)
        model.setIntParam("randomization/randomseedshift", 0)
        variables = [model.addVar(name=f"v_{j}", lb=0., ub=1.)
                     for j in range(problem["nv"])]
        w = variables[:n]
        z = [model.addVar(name=f"z_{k}", vtype="B") for k in range(nt)]
        t = model.addVar(name="response_risk", lb=0.)

        def linear(row):
            return quicksum(float(row[j]) * variables[j]
                            for j in np.flatnonzero(row))

        for j, (row, rhs) in enumerate(zip(problem["Aeq"], problem["beq"])):
            model.addCons(linear(row) == float(rhs), name=f"balance_{j}")
        for j, (row, rhs) in enumerate(zip(problem["Aub"], problem["bub"])):
            model.addCons(linear(row) <= float(rhs), name=f"representation_{j}")
        model.addCons(quicksum(z) <= budget, name="generation_budget")
        for k in range(nt):
            model.addCons(w[nh + k] <= z[k], name=f"activation_{k}")
        quadratic = quicksum(
            quicksum(float(row[i]) * w[i] for i in np.flatnonzero(row)) ** 2
            for row in gram
        )
        model.addCons(quadratic <= t, name="quadratic_epigraph")
        model.setObjective(t, "minimize")
        variable_count = problem["nv"] + nt + 1
        model.optimize()

        raw_status = str(model.getStatus())
        status = {"timelimit": "time_limit",
                  "gaplimit": "optimal_within_tolerance"}.get(raw_status, raw_status)
        result = {"solver": "SCIP convex MIQCP", "solver_license": "open_source",
                  "status": status, "solver_status": raw_status,
                  "variable_count": variable_count, "quadratic_constraints": 1}
        if model.getNSols():
            solution = model.getBestSol()
            weights = np.array([model.getSolVal(solution, var) for var in w])
            objective = float(weights @ sc["Q"] @ weights)
            bound = float(model.getDualbound())
            gap = float(model.getGap())
            finite_bound = (math.isfinite(bound) and not model.isInfinity(abs(bound)))
            finite_gap = math.isfinite(gap) and not model.isInfinity(gap)
            # SCIP measures its gap using the epigraph objective.  Account also
            # for numerical slack when reporting the recomputed quadratic.
            if finite_bound and finite_gap:
                gap = max(gap, max(0., objective - bound) / max(1e-12, abs(objective)))
            result.update(
                weights=weights,
                selection=np.array([int(model.getSolVal(solution, var) > .5) for var in z]),
                objective=objective,
                objective_bound=bound if finite_bound else None,
                gap=gap if finite_gap else None,
            )
        return result
    finally:
        model.freeProb()
