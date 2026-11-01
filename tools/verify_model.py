"""Independent numerical scientific audit; no backend files are changed."""
from pathlib import Path
import json
import sys

import numpy as np
from scipy.optimize import linprog

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from siliconsurvey.scenario import make_scenario
from siliconsurvey.calibration import prior_std, basis
from siliconsurvey.solver import _minimum_human_distance, ground_cost, representation_distance


def joint_conditioning_check(sc):
    # Independent route: condition the entire primitive Gaussian vector
    # (theta, eps_h, eps_pair, eps_fresh) on delta, then map to response errors.
    ph, pt = sc["posterior"]["basis_h"], sc["posterior"]["basis_t"]
    nh, nt, nc = len(ph), len(pt), ph.shape[1]
    primitive_cov = np.diag(np.r_[prior_std() ** 2, sc["human_variance"],
                                  sc["paired_variance"], sc["fresh_ai_variance"]])
    label_map = np.column_stack((ph, -np.eye(nh), np.eye(nh), np.zeros((nh, nt))))
    label_cov = label_map @ primitive_cov @ label_map.T
    gain = np.linalg.solve(label_cov, label_map @ primitive_cov).T
    conditional_mean = gain @ sc["delta"]
    conditional_cov = primitive_cov - gain @ label_map @ primitive_cov
    error_map = np.zeros((nh + nt, nc + 2 * nh + nt))
    error_map[:nh, nc:nc + nh] = np.eye(nh)
    error_map[nh:, :nc] = pt
    error_map[nh:, nc + 2 * nh:] = np.eye(nt)
    correction = np.r_[np.zeros(nh), sc["posterior"]["joint_mean"][nh:]]
    mean = error_map @ conditional_mean - correction
    covariance = error_map @ conditional_cov @ error_map.T
    reference_q = covariance + np.outer(mean, mean)
    assert np.max(np.abs(reference_q - sc["Q"])) < 2e-12
    assert np.max(np.abs(mean - sc["response_error_mean"])) < 2e-12
    weights = np.arange(1., nh + nt + 1.)
    weights /= weights.sum()
    gap = float(weights @ np.r_[sc["f_h_true"], sc["f_t_true"]]
                - sc["true_target_mean"])
    exact = float(weights @ covariance @ weights + (gap + weights @ mean) ** 2)
    expansion = float(gap ** 2 + 2 * gap * (weights @ mean)
                      + weights @ sc["Q"] @ weights)
    upper = float(2 * gap ** 2 + 2 * (weights @ sc["Q"] @ weights))
    distance = representation_distance(sc, weights)
    lipschitz_f = .9 + .64 * np.pi  # Assessment only: simulator f derivative bound.
    transport_upper = float(2 * lipschitz_f ** 2 * distance ** 2
                            + 2 * (weights @ sc["Q"] @ weights))
    assert abs(exact - expansion) < 2e-12
    assert exact <= upper + 2e-12
    assert abs(gap) <= lipschitz_f * distance + 2e-12
    assert exact <= transport_upper + 2e-12
    h, p = sc["human_variance"], sc["paired_variance"]
    # Distinct assessment only: the simulator uses a fixed true bias function.
    # Its conditional-on-delta risk need not equal the fitted-model average.
    true_error_mean = np.r_[h / (h + p) * (sc["b_h_true"] - sc["delta"]),
                            sc["b_t_true"] - correction[nh:]]
    true_noise_variance = np.r_[h * p / (h + p), sc["fresh_ai_variance"]]
    fixed_truth_mse = float((weights ** 2) @ true_noise_variance
                           + (gap + weights @ true_error_mean) ** 2)
    return {"max_Q_error": float(np.max(np.abs(reference_q - sc["Q"]))),
            "max_mean_error": float(np.max(np.abs(mean - sc["response_error_mean"]))),
            "minimum_Q_eigenvalue": float(np.linalg.eigvalsh(sc["Q"])[0]),
            "human_error_mean_norm": float(np.linalg.norm(mean[:nh])),
            "human_AI_cross_block_norm": float(np.linalg.norm(covariance[:nh, nh:])),
            "exact_model_MSE": exact, "two_risk_upper_bound": upper,
            "representation_distance": distance, "W1_two_risk_upper_bound": transport_upper,
            "fixed_simulation_truth_conditional_MSE_assessment_only": fixed_truth_mse}


def transport_check(sc):
    # Eliminate free human weights, optimizing only allowed transport arcs.
    nh, nt = len(sc["x_h"]), len(sc["x_t"])
    costs = ground_cost(sc)[:nh]
    allowed = np.ones((nh, nt), dtype=bool)
    if sc["config"]["geometry"] == "stratified_w1":
        allowed = sc["group_h"][:, None] == sc["group_t"][None, :]
    ii, kk = np.nonzero(allowed)
    columns = (np.arange(nt)[:, None] == kk[None, :]).astype(float)
    lp = linprog(costs[ii, kk], A_eq=columns, b_eq=sc["target_mass"],
                 bounds=(0., None), method="highs")
    assert lp.success
    formula = _minimum_human_distance(sc)
    assert abs(formula - lp.fun) < 2e-12
    # Reconstruct its human weights and independently recompute transport cost.
    human_weights = np.bincount(ii, weights=lp.x, minlength=nh)
    actual = representation_distance(sc, np.r_[human_weights, np.zeros(nt)])
    assert actual is not None and abs(actual - formula) < 2e-12
    return {"geometry": sc["config"]["geometry"], "epsilon_H": formula,
            "independent_LP_error": abs(float(lp.fun) - formula),
            "recomputed_distance_error": abs(actual - formula)}


def main():
    result = {"scope": "Synthetic model/implementation audit, not real-data validation",
              "joint_conditioning_checks": [], "human_distance_checks": []}
    for seed in (2, 42, 97):
        for geometry in ("full_transport", "stratified_w1"):
            sc = make_scenario({"seed": seed, "geometry": geometry})
            if geometry == "full_transport":
                result["joint_conditioning_checks"].append(joint_conditioning_check(sc))
            result["human_distance_checks"].append(transport_check(sc))
    cross_group_case = make_scenario({"n_human": 6, "n_target": 4})
    cross_group_case["x_h"] = np.where(cross_group_case["group_h"] == 0, .1, .9)
    cross_group_case["x_t"] = np.where(cross_group_case["group_t"] == 0, .9, .1)
    result["cross_group_transport_case"] = []
    for geometry, expected in (("full_transport", .5), ("stratified_w1", .8)):
        cross_group_case["config"]["geometry"] = geometry
        check = transport_check(cross_group_case)
        assert abs(check["epsilon_H"] - expected) < 2e-12
        result["cross_group_transport_case"].append(check)
    dense = basis(np.linspace(0., 1., 100), np.tile([0, 1], 50))
    result["basis_columns"] = dense.shape[1]
    result["basis_rank"] = int(np.linalg.matrix_rank(dense))
    # A deterministic counterexample is sufficient to refute an unconditional
    # monotonicity claim for a slider that changes, rather than nests, profiles.
    coverages = [0., .2, .4, .6, .8, 1.]
    example = None
    for seed in range(12):
        distances = [_minimum_human_distance(make_scenario({"seed": seed, "coverage": c}))
                     for c in coverages]
        if np.max(np.diff(distances)) > 1e-6:
            example = {"seed": seed, "coverage": coverages, "epsilon_H": distances}
            break
    result["coverage_nonmonotonicity_example"] = example
    result["status"] = "all numerical assertions passed"
    target = Path(__file__).resolve().parents[1] / "results" / "independent_checks.json"
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
