"""Seeded synthetic data. Ground truth is reserved for assessment."""

from __future__ import annotations

import numpy as np

from .calibration import basis, fit_bias_posterior, build_response_second_moment


DEFAULT_CONFIG = {"seed": 42, "coverage": .45, "n_human": 12, "n_target": 8,
                  "noise": .35, "geometry": "full_transport"}


def _truth_response(x, group):
    return 3.0 + .9 * x + .45 * group + .32 * np.sin(2.0 * np.pi * x)


def _truth_bias(x, group):
    return .1 + .5 * x * x + .3 * np.sin(1.5 * np.pi * x) + group * (.25 + .35 * x)


def make_scenario(config=None):
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(config or {})
    cfg["seed"] = int(cfg["seed"])
    cfg["n_human"], cfg["n_target"] = int(cfg["n_human"]), int(cfg["n_target"])
    cfg["coverage"], cfg["noise"] = float(cfg["coverage"]), float(cfg["noise"])
    if not 0 <= cfg["coverage"] <= 1 or not .02 <= cfg["noise"] <= 2:
        raise ValueError("coverage must be in [0,1]; noise in [0.02,2].")
    if not 4 <= cfg["n_human"] <= 200 or not 4 <= cfg["n_target"] <= 100:
        raise ValueError("Use 4..200 humans and 4..100 target profiles.")
    if cfg["geometry"] not in ("stratified_w1", "full_transport"):
        raise ValueError("geometry must be stratified_w1 or full_transport.")
    rng = np.random.default_rng(cfg["seed"])
    nh, nt, coverage = cfg["n_human"], cfg["n_target"], cfg["coverage"]
    ng1 = max(1, min(nh - 1, int(round(nh * (.06 + .44 * coverage)))))
    gh = np.r_[np.zeros(nh - ng1, dtype=int), np.ones(ng1, dtype=int)]
    # Coverage changes availability, not the external target population.
    ceiling = np.where(gh == 0, .45 + .55 * coverage, .16 + .84 * coverage)
    xh = rng.beta(1.6, 1.8, nh) * ceiling
    order = np.lexsort((xh, gh))
    xh, gh = xh[order], gh[order]
    n0 = nt // 2
    gt = np.r_[np.zeros(n0, dtype=int), np.ones(nt - n0, dtype=int)]
    xt = np.r_[(np.arange(n0) + .5) / n0,
               (np.arange(nt - n0) + .5) / (nt - n0)]
    mass = np.r_[np.full(n0, .5 / n0), np.full(nt - n0, .5 / (nt - n0))]
    hvar = np.full(nh, cfg["noise"] ** 2)
    pvar = np.full(nh, (.85 * cfg["noise"]) ** 2)
    freshvar = np.full(nt, (.85 * cfg["noise"]) ** 2)
    # These functions generate data; the fitting function never receives them.
    fh, ft = _truth_response(xh, gh), _truth_response(xt, gt)
    bh, bt = _truth_bias(xh, gh), _truth_bias(xt, gt)
    y = fh + rng.normal(0., np.sqrt(hvar))
    paired = fh + bh + rng.normal(0., np.sqrt(pvar))
    fresh = ft + bt + rng.normal(0., np.sqrt(freshvar))
    delta = paired - y
    posterior = fit_bias_posterior(xh, gh, delta, xt, gt, hvar, pvar)
    risk = build_response_second_moment(posterior, delta, hvar, pvar, freshvar)
    grid = []
    for group in (0, 1):
        gx = np.linspace(0., 1., 81)
        phi = basis(gx, np.full(len(gx), group))
        gm = phi @ posterior["coefficient_mean"]
        gv = np.einsum("ij,jk,ik->i", phi, posterior["coefficient_covariance"], phi)
        grid.append({"group": group, "x": gx, "age": 18. + 62. * gx,
                     "biasmean": gm, "sd": np.sqrt(np.maximum(gv, 0.)),
                     "truebias": _truth_bias(gx, group)})
    sc = {"config": cfg, "x_h": xh, "group_h": gh, "y_h": y, "paired_h": paired,
          "delta": delta, "x_t": xt, "group_t": gt, "target_mass": mass,
          "human_variance": hvar, "paired_variance": pvar, "fresh_ai_variance": freshvar,
          "posterior": posterior, "fresh_ai_raw": fresh,
          "corrected_ai": fresh - posterior["joint_mean"][nh:],
          "f_h_true": fh, "f_t_true": ft, "b_h_true": bh, "b_t_true": bt,
          "true_target_mean": float(mass @ ft), "grid": grid, **risk}
    return sc


def _native(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): _native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_native(v) for v in value]
    return value


def scenario_to_json(sc, include_matrices=False):
    nh = len(sc["x_h"])
    mean, covariance = sc["posterior"]["joint_mean"], sc["posterior"]["joint_covariance"]
    sd = np.sqrt(np.maximum(np.diag(covariance), 0.))
    human = [{"index": i, "x": float(x), "age": float(18 + 62 * x),
              "group": int(sc["group_h"][i]), "y": float(sc["y_h"][i]),
              "paired": float(sc["paired_h"][i]), "delta": float(sc["delta"][i]),
              "biasmean": float(mean[i]), "sd": float(sd[i])}
             for i, x in enumerate(sc["x_h"])]
    target = [{"index": k, "x": float(x), "age": float(18 + 62 * x),
               "group": int(sc["group_t"][k]), "mass": float(sc["target_mass"][k]),
               "biasmean": float(mean[nh + k]), "sd": float(sd[nh + k])}
              for k, x in enumerate(sc["x_t"])]
    grid_sd = np.concatenate([g["sd"] for g in sc["grid"]])
    grid_mean = np.concatenate([g["biasmean"] for g in sc["grid"]])
    grid_truth = np.concatenate([g["truebias"] for g in sc["grid"]])
    out = {"config": sc["config"], "human": human, "target": target,
           "grid": sc["grid"], "true_target_mean": sc["true_target_mean"],
           "calibration": {"method": sc["posterior"]["method"],
                           "basis_dimension": len(sc["posterior"]["coefficient_mean"]),
                           "knots_normalized_age": sc["posterior"]["knots"],
                           "coefficient_prior_std": sc["posterior"]["prior_coefficient_std"],
                           "human_noise_sd": float(np.sqrt(sc["human_variance"][0])),
                           "AI_noise_sd": float(np.sqrt(sc["fresh_ai_variance"][0])),
                           "fit_inputs": "profiles and paired-minus-human differences only",
                           "Q_semantics": "complete conditional response-error second moment; fresh AI variance included once",
                           "Q_dimension": len(sc["Q"])},
           "diagnostics": {"Q_min_eigenvalue": float(np.linalg.eigvalsh(sc["Q"])[0]),
                           "Q_trace": float(np.trace(sc["Q"])),
                           "calibration_grid_rmse_assessment": float(np.sqrt(np.mean((grid_mean - grid_truth) ** 2))),
                           "grid_true_bias_inside_two_posterior_sd_fraction": float(np.mean(np.abs(grid_mean - grid_truth) <= 2. * grid_sd)),
                           "truth_used_for_fit_or_design": False,
                           "uncertainty_scope": "Model-based under fixed spline basis, priors and known simulated noise; not a distribution-free extrapolation guarantee."},
           "geometry": {"mode": sc["config"]["geometry"],
                        "description": ("Ground metric = absolute normalized-age difference + 0.5 for different groups; finite cross-group transport allowed."
                                        if sc["config"]["geometry"] == "full_transport" else
                                        "Optional variant: exact target group masses and normalized-age W1 within each group; no cross-group transport."),
                        "age_range": [18, 80],
                        "tolerance_units": ("normalized-age equivalent cost; multiply by 62 for age-year-equivalent cost (the 0.5 cross-group penalty equals 31 years of age-distance cost)"
                                            if sc["config"]["geometry"] == "full_transport" else
                                            "normalized within-group age distance; multiply by 62 for age-years")}}
    if include_matrices:
        out.update(Q=sc["Q"], C=sc["C"], response_error_mean=sc["response_error_mean"],
                   posterior_bias_covariance=covariance,
                   fresh_AI_variance=sc["fresh_ai_variance"])
    return _native(out)
