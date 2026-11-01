"""Generate the small actually-solved demonstration and a fixed-Q frontier."""

import csv
import json
from pathlib import Path

from . import make_scenario, scenario_to_json, solve_design


def main():
    destination = Path(__file__).resolve().parents[1] / "results"
    destination.mkdir(parents=True, exist_ok=True)
    sc = make_scenario()
    result = solve_design(sc, 3, .08, backend="gurobi", time_limit=10.)
    frontier = []
    previous = None
    for epsilon in (0., .025, .04, .06, .08, .12, .16, .25, .35):
        fit = solve_design(sc, 3, epsilon, backend="gurobi", time_limit=10.)
        row = {"budget": 3, "tolerance": epsilon, "status": fit["status"],
               "response_risk": fit["response_risk"],
               "representation_distance": fit["representation_distance"],
               "selected_count": fit["budget_used"], "gap": fit["gap"]}
        if fit["response_risk"] is not None:
            if previous is not None:
                assert fit["response_risk"] <= previous + 1e-7
            previous = fit["response_risk"]
        frontier.append(row)
    demo = {"scenario": scenario_to_json(sc, include_matrices=True), "result": result,
            "frontier": frontier,
            "frontier_note": "Same data, calibration posterior, Q, candidate pool and budget for every row. Increasing tolerance enlarges the feasible set; optimal response risk cannot increase. Infeasible rows are explicit.",
            "empirical_scope": "One seeded synthetic scenario; not evidence of out-of-sample validity or uniformly better realized estimation."}
    (destination / "demo.json").write_text(json.dumps(demo, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    with (destination / "frontier.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(frontier[0]))
        writer.writeheader(); writer.writerows(frontier)
    summary = []
    for name, values in (("unweighted_human", result["baselines"]["unweighted"]),
                          ("reweighted_human", result["baselines"]["human_only"]),
                          ("designed_human_AI", result)):
        summary.append({"method": name, "feasible_at_tolerance": values.get("feasible", result["diagnostics"]["representation_feasible"]),
                        "response_risk": values.get("response_risk"),
                        "representation_distance": values.get("representation_distance"),
                        "minimum_achievable_distance": values.get("min_representation_distance"),
                        "estimated_mean": values.get("estimated_mean"),
                        "true_target_mean": sc["true_target_mean"],
                        "absolute_error_one_realization": values.get("absolute_error_assessment")})
    with (destination / "summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader(); writer.writerows(summary)
    print(json.dumps({"solver": result["solver"], "license": result["solver_license"],
                      "status": result["status"], "objective": result["objective"],
                      "selected": result["selected_indices"], "frontier": frontier,
                      "saved": str(destination)}, indent=2))


if __name__ == "__main__":
    main()
