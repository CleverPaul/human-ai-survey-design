"""Local, dependency-light interface for the silicon-survey design prototype."""

from __future__ import annotations

import argparse
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlparse

import numpy as np

from siliconsurvey import make_scenario, scenario_to_json, solve_design
from siliconsurvey.solver import ground_cost, representation_distance


ROOT = Path(__file__).resolve().parent
LOCK = threading.RLock()


def bounded_int(value, low, high, name):
    numeric = float(value)
    if not np.isfinite(numeric) or not numeric.is_integer() or not low <= numeric <= high:
        raise ValueError(f"{name} must be an integer between {low} and {high}.")
    return int(numeric)


def normalized_config(raw):
    """Keep the interactive example within the bundled Gurobi QP size limit."""
    cfg = {
        "seed": bounded_int(raw.get("seed", 42), 0, 2**31 - 1, "Seed"),
        "coverage": float(raw.get("coverage", .45)),
        "n_human": bounded_int(raw.get("n_human", 12), 6, 12, "Human count"),
        "n_target": 8,
        "noise": .35,
        "geometry": "full_transport",
    }
    if not np.isfinite(cfg["coverage"]) or not 0 <= cfg["coverage"] <= 1:
        raise ValueError("Human coverage must be between zero and one.")
    return cfg


@lru_cache(maxsize=32)
def cached_scenario(config_key):
    return make_scenario(json.loads(config_key))


def get_scenario(config):
    return cached_scenario(json.dumps(normalized_config(config), sort_keys=True))


def scenario_payload(sc, matrices=False):
    payload = scenario_to_json(sc, include_matrices=matrices)
    nh, nt = len(sc["x_h"]), len(sc["x_t"])
    raw = np.r_[np.full(nh, 1. / nh), np.zeros(nt)]
    payload["reference"] = {
        "raw_human_distance": representation_distance(sc, raw),
        "minimum_human_distance": float(sc["target_mass"] @ ground_cost(sc)[:nh].min(axis=0)),
        "raw_human_estimate": float(sc["y_h"].mean()),
    }
    return payload


def dispatch_api(path, body=None, *, backend=None):
    """Shared computation for the HTTP and embedded desktop interfaces."""
    url = urlparse(path)
    if body is None:
        if url.path == "/api/health":
            return {"status": "ok", "simulation": True}
        if url.path != "/api/scenario":
            raise ValueError("Unknown API route.")
        args = {k: v[0] for k, v in parse_qs(url.query).items()}
        with LOCK:
            return scenario_payload(get_scenario(args), args.get("matrices") == "1")
    if not isinstance(body, dict) or not isinstance(body.get("config", {}), dict):
        raise ValueError("Send a JSON object with a configuration object.")
    if url.path not in ("/api/solve", "/api/frontier"):
        raise ValueError("Unknown API route.")
    budget = bounded_int(body.get("budget", 3), 0, 8, "AI budget")
    selected_backend = backend or body.get("backend", "auto")
    with LOCK:
        sc = get_scenario(body.get("config", {}))
        if url.path == "/api/solve":
            return solve_design(sc, budget, float(body.get("tolerance", .08)),
                                backend=selected_backend, time_limit=8.)
        keys = ("tolerance", "objective", "response_risk", "status", "gap",
                "representation_distance", "silicon_mass", "budget_used")
        return {"budget": budget, "points": [
            {k: v for k, v in solve_design(sc, budget, eps, backend=selected_backend,
                                           time_limit=3.).items() if k in keys}
            for eps in [.025, .04, .06, .08, .12, .16, .25, .35]]}


class Handler(BaseHTTPRequestHandler):
    server_version = "SurveyDesignLab/1.0"

    def log_message(self, fmt, *args):
        # Requests contain no credentials or personal records in this simulation.
        pass

    def respond(self, payload, status=200):
        data = json.dumps(payload, allow_nan=False, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path == "/api/health":
                return self.respond(dispatch_api(self.path))
            if url.path == "/api/scenario":
                return self.respond(dispatch_api(self.path))
            files = {"/": ("index.html", "text/html"),
                     "/app.js": ("app.js", "text/javascript"),
                     "/desktop.js": ("desktop.js", "text/javascript"),
                     "/styles.css": ("styles.css", "text/css")}
            if url.path not in files:
                return self.respond({"error": "Not found"}, 404)
            name, mime = files[url.path]
            content = (ROOT / "web" / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        except (ValueError, TypeError) as exc:
            self.respond({"error": str(exc)}, 400)
        except Exception as exc:
            self.respond({"error": f"Could not prepare the simulation: {exc}"}, 500)

    def do_POST(self):
        try:
            # The app binds to loopback. Reject browser requests from other origins.
            origin = self.headers.get("Origin")
            allowed = {f"http://127.0.0.1:{self.server.server_port}",
                       f"http://localhost:{self.server.server_port}"}
            if origin and origin not in allowed:
                return self.respond({"error": "Use the local application address."}, 403)
            size = int(self.headers.get("Content-Length", 0))
            if size <= 0 or size > 16384:
                return self.respond({"error": "Invalid request size."}, 400)
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict) or not isinstance(body.get("config", {}), dict):
                raise ValueError("Send a JSON object with a configuration object.")
            if self.path not in ("/api/solve", "/api/frontier"):
                return self.respond({"error": "Not found"}, 404)
            self.respond(dispatch_api(self.path, body))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self.respond({"error": str(exc)}, 400)
        except Exception as exc:
            self.respond({"error": f"Optimization could not finish: {exc}"}, 500)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Survey Design Lab: http://127.0.0.1:{args.port}", flush=True)
    print("Synthetic data only. Press Ctrl+C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
