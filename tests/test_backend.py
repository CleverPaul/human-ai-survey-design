"""Research backend checks using unittest (no pytest dependency)."""

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from siliconsurvey import make_scenario, scenario_to_json, solve_design
from siliconsurvey.calibration import fit_bias_posterior, build_response_second_moment
from siliconsurvey.solver import representation_distance


class CalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sc = make_scenario()

    def test_seeded_data_and_strict_json_export(self):
        a, b = self.sc, make_scenario()
        np.testing.assert_array_equal(a["Q"], b["Q"])
        exported = scenario_to_json(a, include_matrices=True)
        json.dumps(exported, allow_nan=False)
        self.assertEqual(len(exported["human"]), 12)
        self.assertEqual(len(exported["target"]), 8)
        self.assertEqual(exported["config"]["geometry"], "full_transport")
        self.assertEqual(exported["calibration"]["basis_dimension"], 18)
        self.assertFalse(exported["diagnostics"]["truth_used_for_fit_or_design"])

    def test_calibration_receives_only_observable_differences(self):
        s = self.sc
        posterior = fit_bias_posterior(s["x_h"], s["group_h"], s["delta"],
                                       s["x_t"], s["group_t"],
                                       s["human_variance"], s["paired_variance"])
        np.testing.assert_allclose(posterior["joint_mean"], s["posterior"]["joint_mean"])
        self.assertGreater(s["grid"][1]["sd"][-1], s["grid"][1]["sd"][15])

    def test_Q_is_full_second_moment_with_cross_terms_and_one_fresh_noise(self):
        s = self.sc
        nh = len(s["x_h"])
        p = s["posterior"]
        q = build_response_second_moment(p, s["delta"], s["human_variance"],
                                         s["paired_variance"], s["fresh_ai_variance"])
        np.testing.assert_allclose(q["Q"], s["Q"])
        np.testing.assert_allclose(s["Q"], s["C"] + np.outer(s["response_error_mean"], s["response_error_mean"]))
        np.testing.assert_allclose(s["C"][:nh, nh:], s["kappa"][:, None] * p["joint_covariance"][:nh, nh:])
        np.testing.assert_allclose(s["C"][nh:, nh:], p["joint_covariance"][nh:, nh:] + np.diag(s["fresh_ai_variance"]))
        self.assertGreater(np.linalg.norm(s["C"][:nh, nh:]), 1e-4)
        self.assertGreater(np.linalg.eigvalsh(s["Q"]).min(), 0.)

    def test_conditional_response_moments_against_simulation(self):
        s = self.sc
        rng = np.random.default_rng(20261101)
        nh, nt, draws = len(s["x_h"]), len(s["x_t"]), 25000
        p = s["posterior"]
        theta = rng.multivariate_normal(p["coefficient_mean"], p["coefficient_covariance"], size=draws)
        bh, bt = theta @ p["basis_h"].T, theta @ p["basis_t"].T
        eh = ((bh - s["delta"]) * s["kappa"]
              + rng.normal(size=(draws, nh)) * np.sqrt(s["human_conditional_variance"]))
        es = (bt - p["joint_mean"][nh:]
              + rng.normal(size=(draws, nt)) * np.sqrt(s["fresh_ai_variance"]))
        errors = np.column_stack((eh, es))
        empirical = errors.T @ errors / draws
        np.testing.assert_allclose(empirical, s["Q"], atol=.005, rtol=.08)

    def test_full_transport_raw_and_perfect_target(self):
        s = self.sc
        nh = len(s["x_h"])
        perfect = np.r_[np.zeros(nh), s["target_mass"]]
        self.assertAlmostEqual(representation_distance(s, perfect), 0., places=10)
        raw = np.r_[np.full(nh, 1. / nh), np.zeros(len(s["x_t"]))]
        self.assertTrue(np.isfinite(representation_distance(s, raw)))


@unittest.skipUnless(importlib.util.find_spec("gurobipy"), "gurobipy unavailable")
class SolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sc = make_scenario()
        cls.result = solve_design(cls.sc, 3, .08, backend="gurobi", time_limit=10.)

    def test_actual_MIQP_and_constraints(self):
        r = self.result
        self.assertEqual(r["status"], "optimal")
        self.assertEqual(r["diagnostics"]["variable_count"], 188)
        self.assertEqual(r["diagnostics"]["quadratic_constraints"], 0)
        self.assertLessEqual(r["gap"], 1e-5)
        w, z = np.r_[r["wh"], r["ws"]], np.asarray(r["selection"])
        self.assertAlmostEqual(w.sum(), 1.)
        self.assertTrue(np.all(w >= -1e-8))
        self.assertTrue(np.all(np.asarray(r["ws"]) <= z + 1e-8))
        self.assertLessEqual(z.sum(), 3)
        self.assertLessEqual(r["representation_distance"], .08 + 1e-7)
        self.assertAlmostEqual(r["objective"], w @ self.sc["Q"] @ w, places=10)
        self.assertFalse(r["baselines"]["human_only"]["feasible"])

    def test_zero_budget_infeasible_and_feasible(self):
        bad = solve_design(self.sc, 0, .08, backend="gurobi")
        self.assertEqual(bad["status"], "infeasible")
        self.assertIsNone(bad["objective"])
        good = solve_design(self.sc, 0, .25, backend="gurobi")
        self.assertEqual(good["status"], "optimal")
        self.assertEqual(good["budget_used"], 0)
        self.assertAlmostEqual(good["objective"], good["baselines"]["human_only"]["response_risk"], places=7)
        json.dumps(good, allow_nan=False)

    def test_true_functions_and_fresh_answers_do_not_change_design(self):
        altered = deepcopy(self.sc)
        altered["f_h_true"] += 20.
        altered["f_t_true"] -= 10.
        altered["b_h_true"] *= 100.
        altered["b_t_true"] *= 100.
        altered["fresh_ai_raw"] += 50.
        altered["corrected_ai"] += 50.
        other = solve_design(altered, 3, .08, backend="gurobi")
        np.testing.assert_allclose(other["wh"], self.result["wh"], atol=1e-7)
        np.testing.assert_allclose(other["ws"], self.result["ws"], atol=1e-7)
        self.assertGreater(abs(other["estimated_mean"] - self.result["estimated_mean"]), 1.)

    def test_fixed_Q_frontier_is_monotone(self):
        finite = []
        for epsilon in (0., .04, .08, .16, .35):
            fit = solve_design(self.sc, 3, epsilon, backend="gurobi")
            if fit["objective"] is not None:
                self.assertEqual(fit["status"], "optimal")
                finite.append(fit["objective"])
            else:
                self.assertEqual(fit["status"], "infeasible")
        self.assertGreaterEqual(len(finite), 3)
        self.assertTrue(all(b <= a + 1e-7 for a, b in zip(finite, finite[1:])))

    def test_HiGHS_bounds_bracket_gurobi_optimum(self):
        other = solve_design(self.sc, 3, .08, backend="highs", time_limit=3.)
        self.assertIsNotNone(other["objective"])
        self.assertLessEqual(other["objective_bound"], self.result["objective"] + 1e-7)
        self.assertGreaterEqual(other["objective"], self.result["objective"] - 1e-7)
        self.assertLess(other["gap"], .03)

    def test_license_selection_in_fresh_processes(self):
        spec = importlib.util.find_spec("gurobipy")
        bundled = Path(spec.origin).parent / "gurobi.lic"
        self.assertTrue(bundled.exists())
        script = ("from siliconsurvey import make_scenario, solve_design; "
                  "r=solve_design(make_scenario(),3,.08,backend='gurobi'); "
                  "print(r['solver_license'],r['status'])")
        for mode, label in (("bundled", "bundled_restricted"),
                            ("configured", "configured_license")):
            env = dict(os.environ, SURVEY_GUROBI_LICENSE=mode,
                       GRB_LICENSE_FILE=str(bundled))
            proc = subprocess.run([sys.executable, "-X", "utf8", "-c", script],
                                  cwd=Path(__file__).resolve().parents[1],
                                  env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn(label + " optimal", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
