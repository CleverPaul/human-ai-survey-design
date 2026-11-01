"""Solve the original convex design model without a commercial license."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from siliconsurvey import make_scenario, solve_design


@unittest.skipUnless(importlib.util.find_spec("pyscipopt"), "PySCIPOpt unavailable")
class SCIPBackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sc = make_scenario()
        cls.result = solve_design(cls.sc, 3, .08, backend="scip", time_limit=10.)

    def test_default_matches_known_global_optimum_and_constraints(self):
        r = self.result
        self.assertEqual(r["status"], "optimal")
        self.assertEqual(r["solver_license"], "open_source")
        self.assertEqual(r["diagnostics"]["variable_count"], 189)
        self.assertEqual(r["diagnostics"]["quadratic_constraints"], 1)
        self.assertAlmostEqual(r["objective"], .021538113381858636, delta=2e-7)
        self.assertEqual(r["selected_indices"], [3, 5, 7])
        self.assertLessEqual(r["objective_bound"], .021538113381858636 + 1e-7)
        self.assertGreaterEqual(r["objective"], r["objective_bound"] - 1e-8)
        self.assertLessEqual(r["gap"], 1e-6)
        w, z = np.array(r["weights"]), np.array(r["selection"])
        self.assertAlmostEqual(w.sum(), 1., places=7)
        self.assertTrue(np.all(w >= -1e-9))
        self.assertTrue(np.all(np.array(r["ws"]) <= z + 1e-8))
        self.assertLessEqual(z.sum(), 3)
        self.assertLessEqual(r["representation_distance"], .08 + 1e-7)
        self.assertAlmostEqual(r["objective"], w @ self.sc["Q"] @ w, places=12)
        self.assertFalse(r["baselines"]["human_only"]["feasible"])
        json.dumps(r, allow_nan=False)

    def test_zero_budget_and_infeasible_representation_constraint(self):
        for budget, tolerance in ((0, .08), (3, .025)):
            r = solve_design(self.sc, budget, tolerance, backend="scip")
            self.assertEqual(r["status"], "infeasible")
            self.assertIsNone(r["objective"])
            self.assertIsNone(r["gap"])
            self.assertEqual(r["selected_indices"], [])
            json.dumps(r, allow_nan=False)
        good = solve_design(self.sc, 0, .25, backend="scip")
        self.assertIn(good["status"], ("optimal", "optimal_within_tolerance"))
        self.assertLessEqual(good["gap"], 1e-6)
        self.assertEqual(good["budget_used"], 0)
        self.assertAlmostEqual(good["silicon_mass"], 0., places=9)
        self.assertAlmostEqual(good["objective"], good["baselines"]["human_only"]["response_risk"],
                               delta=2e-7)

    def test_stratified_geometry_retains_exact_group_masses(self):
        sc = make_scenario({"geometry": "stratified_w1"})
        r = solve_design(sc, 3, .08, backend="scip")
        self.assertEqual(r["status"], "optimal")
        self.assertLessEqual(r["representation_distance"], .08 + 1e-7)
        group = np.r_[sc["group_h"], sc["group_t"]]
        weights = np.asarray(r["weights"])
        for g in (0, 1):
            self.assertAlmostEqual(weights[group == g].sum(),
                                   sc["target_mass"][sc["group_t"] == g].sum(), places=7)

    def test_auto_uses_scip_when_gurobi_is_unavailable(self):
        with patch("siliconsurvey.solver._solve_gurobi", side_effect=ImportError("test unavailable")):
            r = solve_design(self.sc, 3, .08, backend="auto")
        self.assertEqual(r["solver"], "SCIP convex MIQCP")
        self.assertEqual(r["diagnostics"]["solver_attempts"][0]["backend"], "gurobi")
        self.assertAlmostEqual(r["objective"], self.result["objective"], places=10)

    def test_design_does_not_read_simulator_truth_or_fresh_answers(self):
        altered = deepcopy(self.sc)
        altered["f_h_true"] += 20.
        altered["f_t_true"] -= 10.
        altered["b_h_true"] *= 100.
        altered["b_t_true"] *= 100.
        altered["fresh_ai_raw"] += 50.
        altered["corrected_ai"] += 50.
        r = solve_design(altered, 3, .08, backend="scip")
        np.testing.assert_allclose(r["weights"], self.result["weights"], atol=1e-9)
        self.assertGreater(abs(r["estimated_mean"] - self.result["estimated_mean"]), 1.)

    def test_time_limit_keeps_actual_status_and_bound(self):
        sc = make_scenario({"n_human": 20, "n_target": 16})
        r = solve_design(sc, 5, .08, backend="scip", time_limit=.1)
        self.assertIn(r["status"], ("optimal", "optimal_within_tolerance", "time_limit"))
        if r["objective"] is not None:
            if r["objective_bound"] is None:
                self.assertEqual(r["status"], "time_limit")
            else:
                self.assertLessEqual(r["objective_bound"], r["objective"] + 1e-7)
            # A very short run can leave SCIP's relative gap undefined/infinite.
            # The JSON API reports this honestly as null, without certification.
            if r["gap"] is None:
                self.assertEqual(r["status"], "time_limit")
            else:
                self.assertGreaterEqual(r["gap"], 0.)
            if r["status"] == "optimal":
                self.assertLessEqual(r["gap"], 1e-6)
        self.assertEqual(r["diagnostics"]["solver_status"] == "timelimit",
                         r["status"] == "time_limit")
        json.dumps(r, allow_nan=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
