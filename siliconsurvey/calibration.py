"""Nonlinear conjugate Bayesian spline/GAM calibration, not BART.

Knots and Gaussian coefficient priors are fixed before seeing responses.
Only paired-minus-human differences enter the bias fit.
The explicit level/trend columns overlap the spline span. Their proper
Gaussian priors still define a unique posterior over the function; individual
overlapping coefficients are not separately identifiable interpretations.
"""

from __future__ import annotations

import numpy as np
from scipy.interpolate import BSpline


def basis(x, group):
    """Fixed cubic B-splines plus group-specific smooth deviations."""
    x = np.asarray(x, dtype=float)
    group = np.asarray(group, dtype=float)
    knots = np.r_[np.zeros(4), [.25, .5, .75], np.ones(4)]
    splines = BSpline.design_matrix(x, knots, 3, extrapolate=False).toarray()
    centered_group = group - .5
    return np.column_stack((np.ones(len(x)), centered_group, x - .5,
                            centered_group * (x - .5), splines,
                            splines * centered_group[:, None]))


def prior_std():
    # Proper, fixed priors on level, group effect, linear trend and smooth terms.
    return np.r_[.45, .5, .5, .45, np.full(7, .45), np.full(7, .45)]


def fit_bias_posterior(x_h, group_h, delta, x_t, group_t, human_variance, paired_variance):
    x_h, x_t = np.asarray(x_h), np.asarray(x_t)
    delta = np.asarray(delta, dtype=float)
    ph, pt = basis(x_h, group_h), basis(x_t, group_t)
    noise = np.asarray(human_variance) + np.asarray(paired_variance)
    if np.any(noise <= 0):
        raise ValueError("Known paired-difference noise variances must be positive.")
    std = prior_std()
    precision = np.diag(1.0 / std ** 2) + ph.T @ (ph / noise[:, None])
    covariance = np.linalg.solve(precision, np.eye(len(std)))
    coefficient_mean = covariance @ (ph.T @ (delta / noise))
    joint_basis = np.vstack((ph, pt))
    mean = joint_basis @ coefficient_mean
    latent_covariance = joint_basis @ covariance @ joint_basis.T
    return {"coefficient_mean": coefficient_mean, "coefficient_covariance": covariance,
            "joint_mean": mean, "joint_covariance": latent_covariance,
            "basis_h": ph, "basis_t": pt,
            "method": "Bayesian cubic-spline GAM with group-specific smooths",
            "prior_coefficient_std": std, "knots": np.array([0., .25, .5, .75, 1.])}


def build_response_second_moment(posterior, delta, human_variance, paired_variance,
                                 fresh_ai_variance):
    """Conditional second moment with reuse of human calibration responses.

delta=b_H+eps_p-eps_h. Given delta and b_H, eps_h has mean
kappa*(b_H-delta), variance h*p/(h+p). A fresh corrected silicon response
has error b_T-E[b_T|delta]+eps_new. Their posterior cross covariance is
therefore kappa*K_HT, not zero. Q already contains new-response variance.
"""
    delta = np.asarray(delta, dtype=float)
    h, p = np.asarray(human_variance), np.asarray(paired_variance)
    fresh = np.asarray(fresh_ai_variance)
    nh, nt = len(delta), len(fresh)
    kappa = h / (h + p)
    latent = posterior["joint_covariance"]
    mean = np.r_[kappa * (posterior["joint_mean"][:nh] - delta), np.zeros(nt)]
    scale = np.r_[kappa, np.ones(nt)]
    covariance = latent * np.outer(scale, scale)
    covariance += np.diag(np.r_[h * p / (h + p), fresh])
    q = covariance + np.outer(mean, mean)
    return {"Q": (q + q.T) / 2., "C": covariance, "response_error_mean": mean,
            "kappa": kappa, "human_conditional_variance": h * p / (h + p)}
