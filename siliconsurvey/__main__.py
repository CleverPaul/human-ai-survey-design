"""Reproducible command-line entry point; no web server is required."""

import argparse
import json
from pathlib import Path

from . import make_scenario, scenario_to_json, solve_design


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--coverage", type=float, default=.45)
    p.add_argument("--humans", type=int, default=12)
    p.add_argument("--targets", type=int, default=8)
    p.add_argument("--noise", type=float, default=.35)
    p.add_argument("--budget", type=int, default=3)
    p.add_argument("--tolerance", type=float, default=.08)
    p.add_argument("--backend", choices=("auto", "gurobi", "scip", "highs"), default="auto")
    p.add_argument("--geometry", choices=("full_transport", "stratified_w1"), default="full_transport")
    p.add_argument("--time-limit", type=float, default=10.)
    p.add_argument("--output", help="Write result JSON to this file.")
    p.add_argument("--scenario-output", help="Write the seeded calibration/scenario JSON.")
    p.add_argument("--matrices", action="store_true", help="Include Q/C in scenario export.")
    a = p.parse_args()
    sc = make_scenario({"seed": a.seed, "coverage": a.coverage, "n_human": a.humans,
                        "n_target": a.targets, "noise": a.noise, "geometry": a.geometry})
    result = solve_design(sc, a.budget, a.tolerance, a.backend, a.time_limit)
    for destination, value in ((a.output, result),
                               (a.scenario_output, scenario_to_json(sc, a.matrices))):
        if destination:
            path = Path(destination)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
