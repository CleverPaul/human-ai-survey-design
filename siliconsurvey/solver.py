"""Convex MIQP design and independently computed survey baselines."""

from __future__ import annotations

import importlib.util
import math
import os
from pathlib import Path
import threading
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp, minimize

from .scenario import _native


_LICENSE_ENV_LOCK = threading.Lock()


def ground_cost(sc):
    x = np.r_[sc["x_h"], sc["x_t"]]
    g = np.r_[sc["group_h"], sc["group_t"]]
    return (np.abs(x[:, None] - sc["x_t"][None, :])
            + .5 * (g[:, None] != sc["group_t"][None, :]))


def _cdf_spec(sc, active):
    x = np.r_[sc["x_h"], sc["x_t"]][active]
    group = np.r_[sc["group_h"], sc["group_t"]][active]
    rows, offsets, gaps = [], [], []
    for g in (0, 1):
        tx, tm = sc["x_t"][sc["group_t"] == g], sc["target_mass"][sc["group_t"] == g]
        positions = np.unique(np.r_[x[group == g], tx])
        for left, right in zip(positions[:-1], positions[1:]):
            rows.append(((group == g) & (x <= left)).astype(float))
            offsets.append(float(tm[tx <= left].sum()))
            gaps.append(right - left)
    return np.asarray(rows), np.asarray(offsets), np.asarray(gaps)


def _weight_problem(sc, active, tolerance):
    """Linear feasible region for a fixed set of available source profiles."""
    active = np.asarray(active, dtype=int)
    na, nt = len(active), len(sc["x_t"])
    full = sc["config"]["geometry"] == "full_transport"
    if full:
        d = ground_cost(sc)[active]
        nv = na + na * nt
        ae = np.zeros((na + nt, nv))
        be = np.r_[np.zeros(na), sc["target_mass"]]
        for i in range(na):
            ae[i, i] = -1.
            ae[i, na + i * nt:na + (i + 1) * nt] = 1.
        for k in range(nt):
            ae[na + k, na + k::nt] = 1.
        au = np.zeros((1, nv))
        au[0, na:] = d.ravel()
        bu = np.array([tolerance])
        transport_linear = au[0].copy()
    else:
        rows, offsets, gaps = _cdf_spec(sc, active)
        nl, nv = len(rows), na + len(rows)
        ae = np.zeros((2, nv))
        ae[0, :na] = 1.
        all_groups = np.r_[sc["group_h"], sc["group_t"]][active]
        ae[1, :na] = all_groups == 0
        be = np.array([1., sc["target_mass"][sc["group_t"] == 0].sum()])
        au = np.zeros((2 * nl + 1, nv))
        bu = np.r_[offsets, -offsets, tolerance]
        au[:nl, :na], au[nl:2 * nl, :na] = rows, -rows
        au[:nl, na:] = -np.eye(nl)
        au[nl:2 * nl, na:] = -np.eye(nl)
        au[-1, na:] = gaps
        transport_linear = np.r_[np.zeros(na), gaps]
    return {"active": active, "na": na, "nv": nv, "Aeq": ae, "beq": be,
            "Aub": au, "bub": bu, "transport_linear": transport_linear}


def _continuous_weights(sc, active, tolerance, maxiter=150):
    problem = _weight_problem(sc, active, tolerance)
    na, nv = problem["na"], problem["nv"]
    # This LP also supplies a genuinely feasible starting point for the QP.
    feasible = linprog(problem["transport_linear"], A_ub=problem["Aub"], b_ub=problem["bub"],
                       A_eq=problem["Aeq"], b_eq=problem["beq"],
                       bounds=[(0., 1.)] * nv, method="highs")
    if not feasible.success:
        return None
    q = sc["Q"][np.ix_(problem["active"], problem["active"])]
    def fun(v):
        return float(v[:na] @ q @ v[:na])
    def jac(v):
        return np.r_[2. * q @ v[:na], np.zeros(nv - na)]
    constraints = [LinearConstraint(problem["Aeq"], problem["beq"], problem["beq"]),
                   LinearConstraint(problem["Aub"], -np.inf, problem["bub"])]
    fit = minimize(fun, feasible.x, jac=jac, method="SLSQP", bounds=Bounds(0., 1.),
                   constraints=constraints,
                   options={"maxiter": maxiter, "ftol": 1e-11, "disp": False})
    candidate = fit.x if (np.max(problem["Aub"] @ fit.x - problem["bub"]) < 1e-6
                           and np.max(np.abs(problem["Aeq"] @ fit.x - problem["beq"])) < 1e-6) else feasible.x
    weights = np.zeros(len(sc["Q"]))
    weights[problem["active"]] = np.maximum(0., candidate[:na])
    return {"weights": weights, "objective": float(weights @ sc["Q"] @ weights),
            "status": "optimal" if fit.success else "feasible_qp_iteration_limit",
            "message": str(fit.message), "feasible_vector": candidate}


def representation_distance(sc, weights):
    """Minimum transport cost, recomputed independently from solver Pi."""
    weights = np.asarray(weights, dtype=float)
    if sc["config"]["geometry"] == "stratified_w1":
        groups = np.r_[sc["group_h"], sc["group_t"]]
        discrepancy = max(abs(weights[groups == g].sum()
                              - sc["target_mass"][sc["group_t"] == g].sum()) for g in (0, 1))
        if discrepancy > 1e-6:
            return None
        rows, offsets, gaps = _cdf_spec(sc, np.arange(len(weights)))
        return float(gaps @ np.abs(rows @ weights - offsets))
    nt = len(sc["x_t"])
    n = len(weights)
    d = ground_cost(sc)
    ae = np.zeros((n + nt, n * nt))
    for i in range(n):
        ae[i, i * nt:(i + 1) * nt] = 1.
    for k in range(nt):
        ae[n + k, k::nt] = 1.
    fit = linprog(d.ravel(), A_eq=ae, b_eq=np.r_[weights, sc["target_mass"]],
                  bounds=(0., None), method="highs")
    return float(fit.fun) if fit.success else None


def _minimum_human_distance(sc):
    nh = len(sc["x_h"])
    d = ground_cost(sc)[:nh]
    if sc["config"]["geometry"] == "stratified_w1":
        d = d.copy()
        d[sc["group_h"][:, None] != sc["group_t"][None, :]] = np.inf
    return float(sc["target_mass"] @ np.min(d, axis=0))


def _estimate(sc, weights):
    nh = len(sc["x_h"])
    return float(weights[:nh] @ sc["y_h"] + weights[nh:] @ sc["corrected_ai"])


def _assess(sc, weights):
    nh = len(sc["x_h"])
    response_mean = float(weights @ sc["response_error_mean"])
    variance = float(weights @ sc["C"] @ weights)
    representation_bias = float(weights[:nh] @ sc["f_h_true"]
                                + weights[nh:] @ sc["f_t_true"] - sc["true_target_mean"])
    estimate = _estimate(sc, weights)
    return {"estimated_mean": estimate, "response_risk": float(weights @ sc["Q"] @ weights),
            "representation_distance": representation_distance(sc, weights),
            "true_target_mean": sc["true_target_mean"],
            "absolute_error_assessment": abs(estimate - sc["true_target_mean"]),
            "conditional_response_mean": response_mean,
            "conditional_response_variance": variance,
            "representation_bias_assessment": representation_bias,
            "conditional_total_mse_assessment": variance + (representation_bias + response_mean) ** 2,
            "conditional_mse_scope": "Fitted bias-posterior conditional MSE using simulated true f for assessment; not oracle MSE under the fixed simulator bias."}


def baselines(sc, tolerance):
    nh, n = len(sc["x_h"]), len(sc["Q"])
    raw_w = np.r_[np.full(nh, 1. / nh), np.zeros(n - nh)]
    raw = {"name": "Unweighted human responses", "wh": raw_w[:nh], "ws": raw_w[nh:],
           **_assess(sc, raw_w)}
    raw["feasible"] = (raw["representation_distance"] is not None
                       and raw["representation_distance"] <= tolerance + 1e-7)
    minimum = _minimum_human_distance(sc)
    human = {"name": "Optimally reweighted humans under the same representation constraint",
             "min_representation_distance": minimum,
             "feasible": minimum <= tolerance + 1e-8}
    if human["feasible"]:
        fit = _continuous_weights(sc, np.arange(nh), tolerance)
        if fit is not None:
            human.update(wh=fit["weights"][:nh], ws=fit["weights"][nh:],
                         qp_status=fit["status"], **_assess(sc, fit["weights"]))
        else:
            human.update(feasible=False, status="continuous_baseline_numerical_failure")
    return {"unweighted": raw, "human_only": human}


def _gram(q):
    eig, vec = np.linalg.eigh((q + q.T) / 2.)
    if eig.min() < -1e-8:
        raise ValueError("Q is not PSD.")
    return np.sqrt(np.maximum(eig, 0.))[:, None] * vec.T


def _gurobi_env():
    # HTTP requests can run in parallel; serialize temporary process-env changes.
    with _LICENSE_ENV_LOCK:
        return _gurobi_env_locked()


def _gurobi_env_locked():
    # Prefer the installed legal restricted license over an expired ambient WLS.
    # Only a path is selected; no license contents or keys are read or changed.
    spec = importlib.util.find_spec("gurobipy")
    if spec is None:
        raise RuntimeError("gurobipy is not installed.")
    bundled = Path(spec.origin).resolve().parent / "gurobi.lic"
    original = os.environ.get("GRB_LICENSE_FILE")
    mode = os.environ.get("SURVEY_GUROBI_LICENSE", "auto").lower().strip()
    if mode not in ("auto", "bundled", "configured"):
        raise ValueError("SURVEY_GUROBI_LICENSE must be auto, bundled or configured.")
    if mode == "bundled" and not bundled.exists():
        raise RuntimeError("The installed gurobipy package has no bundled license file.")
    attempts = []
    if mode == "configured":
        # Respect GRB_LICENSE_FILE, standard license discovery and other Gurobi
        # configuration without substituting the bundled restricted license.
        paths = [original]
    elif mode == "bundled":
        paths = [str(bundled)]
    else:
        paths = [str(bundled), original] if bundled.exists() else [original]
    for path in dict.fromkeys(paths):
        try:
            if path:
                os.environ["GRB_LICENSE_FILE"] = path
            # Gurobi reads the license environment when its module is imported.
            import gurobipy as gp
            env = gp.Env(params={"OutputFlag": 0})
            label = ("configured_license" if mode == "configured" else
                     "bundled_restricted" if path == str(bundled) else "configured_license")
            return env, label
        except Exception as exc:
            attempts.append(str(exc))
        finally:
            if original is None:
                os.environ.pop("GRB_LICENSE_FILE", None)
            else:
                os.environ["GRB_LICENSE_FILE"] = original
    raise RuntimeError("No usable Gurobi environment: " + "; ".join(attempts))


def _solve_gurobi(sc, budget, tolerance, time_limit):
    env, license_label = _gurobi_env()
    import gurobipy as gp
    from gurobipy import GRB
    nh, nt, n = len(sc["x_h"]), len(sc["x_t"]), len(sc["Q"])
    try:
        with gp.Model("silicon_survey_fixed_Q", env=env) as model:
            model.Params.OutputFlag = 0
            model.Params.TimeLimit = time_limit
            model.Params.MIPGap = 1e-5
            model.Params.NonConvex = 0
            w = model.addVars(n, lb=0., ub=1., name="w")
            z = model.addVars(nt, vtype=GRB.BINARY, name="z")
            model.addConstr(gp.quicksum(w.values()) == 1.)
            model.addConstr(gp.quicksum(z.values()) <= budget)
            for k in range(nt):
                model.addConstr(w[nh + k] <= z[k])
            if sc["config"]["geometry"] == "full_transport":
                d = ground_cost(sc)
                pi = model.addVars(n, nt, lb=0., name="Pi")
                for i in range(n):
                    model.addConstr(gp.quicksum(pi[i, k] for k in range(nt)) == w[i])
                for k in range(nt):
                    model.addConstr(gp.quicksum(pi[i, k] for i in range(n)) == sc["target_mass"][k])
                model.addConstr(gp.quicksum(float(d[i, k]) * pi[i, k]
                                           for i in range(n) for k in range(nt)) <= tolerance)
            else:
                rows, offsets, gaps = _cdf_spec(sc, np.arange(n))
                groups = np.r_[sc["group_h"], sc["group_t"]]
                model.addConstr(gp.quicksum(w[i] for i in range(n) if groups[i] == 0)
                                == float(sc["target_mass"][sc["group_t"] == 0].sum()))
                u = model.addVars(len(rows), lb=0., name="CDF_absolute_gap")
                for j, row in enumerate(rows):
                    difference = gp.quicksum(float(row[i]) * w[i] for i in range(n)) - float(offsets[j])
                    model.addConstr(u[j] >= difference)
                    model.addConstr(u[j] >= -difference)
                model.addConstr(gp.quicksum(float(gaps[j]) * u[j] for j in range(len(rows))) <= tolerance)
            objective = gp.QuadExpr()
            for row in _gram(sc["Q"]):
                term = gp.quicksum(float(row[i]) * w[i] for i in range(n))
                objective += term * term
            model.setObjective(objective, GRB.MINIMIZE)
            model.optimize()
            result = {"solver": "Gurobi convex MIQP", "solver_license": license_label,
                      "status": {GRB.OPTIMAL: "optimal", GRB.INFEASIBLE: "infeasible",
                                 GRB.TIME_LIMIT: "time_limit"}.get(model.Status, str(model.Status)),
                      "solver_status_code": int(model.Status), "variable_count": model.NumVars,
                      "quadratic_constraints": model.NumQConstrs}
            if model.SolCount:
                result.update(weights=np.array([w[i].X for i in range(n)]),
                              selection=np.array([int(z[k].X > .5) for k in range(nt)]),
                              objective_bound=float(model.ObjBound), gap=float(model.MIPGap))
            return result
    finally:
        env.dispose()


def _solve_highs(sc, budget, tolerance, time_limit):
    """Certified convex outer approximation with SciPy/HiGHS MILP masters.

Each cut t>=2*x'Q*w-x'Q*x globally underestimates the PSD quadratic.
The best feasible true quadratic value is an upper bound; each master dual
bound is a lower bound. A time-limited result retains its honest gap.
"""
    start = time.perf_counter()
    nh, nt, n = len(sc["x_h"]), len(sc["x_t"]), len(sc["Q"])
    problem = _weight_problem(sc, np.arange(n), tolerance)
    nv0, nv = problem["nv"], problem["nv"] + nt + 1
    zstart, tindex = nv0, nv - 1
    rows, lower, upper = [], [], []
    for row, rhs in zip(problem["Aeq"], problem["beq"]):
        rows.append(np.r_[row, np.zeros(nt + 1)])
        lower.append(rhs); upper.append(rhs)
    for row, rhs in zip(problem["Aub"], problem["bub"]):
        rows.append(np.r_[row, np.zeros(nt + 1)])
        lower.append(-np.inf); upper.append(rhs)
    row = np.zeros(nv); row[zstart:zstart + nt] = 1.
    rows.append(row); lower.append(-np.inf); upper.append(budget)
    for k in range(nt):
        row = np.zeros(nv); row[nh + k], row[zstart + k] = 1., -1.
        rows.append(row); lower.append(-np.inf); upper.append(0.)
    def cut(w):
        row = np.zeros(nv)
        row[:n] = 2. * (sc["Q"] @ w)
        row[tindex] = -1.
        rows.append(row); lower.append(-np.inf); upper.append(float(w @ sc["Q"] @ w))
    # Deterministic valid cuts, with no use of simulator truth or fresh answers.
    for w in np.eye(n):
        cut(w)
    cut(np.full(n, 1. / n))
    objective = np.zeros(nv); objective[tindex] = 1.
    lb = np.zeros(nv); ub = np.r_[np.ones(nv - 1), np.inf]
    integrality = np.zeros(nv); integrality[zstart:zstart + nt] = 1
    best, lower_bound, iterations = None, 0., 0
    while time.perf_counter() - start < time_limit and iterations < 60:
        remaining = time_limit - (time.perf_counter() - start)
        master = milp(objective, integrality=integrality, bounds=Bounds(lb, ub),
                      constraints=LinearConstraint(np.asarray(rows), lower, upper),
                      options={"time_limit": max(.05, remaining), "mip_rel_gap": 1e-5})
        iterations += 1
        if master.x is None:
            if master.status == 2:
                return {"solver": "HiGHS convex outer approximation", "status": "infeasible",
                        "solver_license": "open_source", "outer_iterations": iterations}
            break
        candidate_w = np.maximum(0., master.x[:n])
        candidate_z = np.rint(master.x[zstart:zstart + nt]).astype(int)
        value = float(candidate_w @ sc["Q"] @ candidate_w)
        if best is None or value < best["objective"]:
            best = {"weights": candidate_w, "selection": candidate_z, "objective": value}
        bound = getattr(master, "mip_dual_bound", None)
        if bound is not None and math.isfinite(bound):
            lower_bound = max(lower_bound, float(bound))
        cut(candidate_w)
        # Improve the incumbent on its fixed binary support with a convex QP.
        if time.perf_counter() - start < time_limit * .75:
            active = np.r_[np.arange(nh), nh + np.flatnonzero(candidate_z)]
            refined = _continuous_weights(sc, active, tolerance, maxiter=80)
            if refined is not None:
                cut(refined["weights"])
                if refined["objective"] < best["objective"]:
                    best = {"weights": refined["weights"], "selection": candidate_z,
                            "objective": refined["objective"]}
        relative = max(0., best["objective"] - lower_bound) / max(1e-12, abs(best["objective"]))
        if relative <= 1e-4:
            break
    if best is None:
        return {"solver": "HiGHS convex outer approximation", "solver_license": "open_source",
                "status": "time_limit_no_solution", "outer_iterations": iterations}
    gap = max(0., best["objective"] - lower_bound) / max(1e-12, abs(best["objective"]))
    return {**best, "solver": "HiGHS convex outer approximation", "solver_license": "open_source",
            "status": "optimal_within_tolerance" if gap <= 1e-4 else "time_limit",
            "objective_bound": lower_bound, "gap": gap, "outer_iterations": iterations}


def _solve_scip(sc, budget, tolerance, time_limit):
    from .scip_backend import solve_scip
    return solve_scip(sc, budget, tolerance, time_limit)


def solve_design(sc, budget, tolerance, backend="auto", time_limit=10.):
    start = time.perf_counter()
    if int(budget) != budget or budget < 0:
        raise ValueError("budget must be a nonnegative integer number of one-response profiles.")
    budget = min(int(budget), len(sc["x_t"]))
    tolerance, time_limit = float(tolerance), float(time_limit)
    if not math.isfinite(tolerance) or tolerance < 0 or not 0.1 <= time_limit <= 300:
        raise ValueError("Use nonnegative finite tolerance and 0.1..300 seconds.")
    if backend not in ("auto", "gurobi", "scip", "highs"):
        raise ValueError("backend must be auto, gurobi, scip or highs.")
    attempts = []
    fit = None
    if backend in ("auto", "gurobi"):
        try:
            fit = _solve_gurobi(sc, budget, tolerance, time_limit)
        except Exception as exc:
            attempts.append({"backend": "gurobi", "error": str(exc)})
            if backend == "gurobi":
                raise RuntimeError("Gurobi optimization failed: " + str(exc)) from exc
    if fit is None and (backend == "scip" or
                        (backend == "auto" and importlib.util.find_spec("pyscipopt") is not None)):
        try:
            fit = _solve_scip(sc, budget, tolerance, time_limit)
        except Exception as exc:
            attempts.append({"backend": "scip", "error": str(exc)})
            if backend == "scip":
                raise RuntimeError("SCIP optimization failed (requires PySCIPOpt): " + str(exc)) from exc
    if fit is None:
        fit = _solve_highs(sc, budget, tolerance, time_limit)
    baseline = baselines(sc, tolerance)
    result = {"budget": budget, "tolerance": tolerance, "config": sc["config"],
              "solver": fit["solver"], "solver_license": fit.get("solver_license"),
              "status": fit["status"], "gap": fit.get("gap"),
              "objective_bound": fit.get("objective_bound"), "baselines": baseline,
              "true_target_mean": sc["true_target_mean"],
              "diagnostics": {"solver_attempts": attempts, "truth_used_for_fit_or_design": False,
                              "Q_min_eigenvalue": float(np.linalg.eigvalsh(sc["Q"])[0]),
                              "fresh_AI_variance_included_once": True,
                              "reuse_cross_covariance_retained": True,
                              "geometry": sc["config"]["geometry"],
                              "one_response_per_selected_profile": True,
                              "variable_count": fit.get("variable_count"),
                              "quadratic_constraints": fit.get("quadratic_constraints"),
                              "solver_status": fit.get("solver_status"),
                              "outer_iterations": fit.get("outer_iterations")}}
    if "weights" in fit:
        nh = len(sc["x_h"])
        w = np.maximum(0., fit["weights"])
        z = fit["selection"]
        # Zero-weight selected profiles can be omitted without changing the design.
        z = np.asarray(z, dtype=int)
        indices = np.flatnonzero(z).tolist()
        assessment = _assess(sc, w)
        result.update(selected_indices=indices, selection=z, wh=w[:nh], ws=w[nh:],
                      weights=w, objective=assessment["response_risk"],
                      budget_used=int(z.sum()), silicon_mass=float(w[nh:].sum()),
                      selected_responses=[{"index": k, "raw": float(sc["fresh_ai_raw"][k]),
                                           "correction": float(sc["posterior"]["joint_mean"][nh + k]),
                                           "corrected": float(sc["corrected_ai"][k]),
                                           "weight": float(w[nh + k])} for k in indices],
                      **assessment)
        distance = assessment["representation_distance"]
        result["diagnostics"].update(simplex_error=abs(float(w.sum()) - 1.),
                                     activation_violation=max(0., float(np.max(w[nh:] - z))),
                                     representation_feasible=distance is not None and distance <= tolerance + 1e-6,
                                     group_1_mass=float(w[np.r_[sc["group_h"], sc["group_t"]] == 1].sum()))
    else:
        result.update(selected_indices=[], selection=[], wh=[], ws=[],
                      objective=None, response_risk=None, representation_distance=None,
                      budget_used=0, estimated_mean=None)
    result["elapsed_seconds"] = time.perf_counter() - start
    return _native(result)
