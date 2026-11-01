"""Loopback HTTP/API integration tests using Python's standard library only.

Run with the project's Python environment from the repository root:
    python -m unittest discover -s tests -p test_app.py -v
"""

import http.client
from http.server import ThreadingHTTPServer
import json
import math
from pathlib import Path
import sys
import threading
import unittest
from urllib.parse import urlencode


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class AppHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.server.daemon_threads = True
        cls.port = cls.server.server_port
        cls.origin = f"http://127.0.0.1:{cls.port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      kwargs={"poll_interval": .02}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2.)
        app.cached_scenario.cache_clear()
        if cls.thread.is_alive():
            raise AssertionError("The test HTTP server did not shut down.")

    def request(self, method, path, payload=None, *, raw=None, headers=None):
        request_headers = dict(headers or {})
        if raw is not None:
            body = raw
        elif payload is not None:
            body = json.dumps(payload).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        else:
            body = None
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30.)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def request_json(self, method, path, payload=None, **kwargs):
        status, headers, data = self.request(method, path, payload, **kwargs)
        self.assertIn("application/json", headers["Content-Type"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(int(headers["Content-Length"]), len(data))
        return status, headers, json.loads(data)

    def test_health(self):
        status, _, result = self.request_json("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(result, {"status": "ok", "simulation": True})

    def test_default_scenario_and_optional_matrices(self):
        status, _, scenario = self.request_json("GET", "/api/scenario")
        self.assertEqual(status, 200)
        self.assertEqual(len(scenario["human"]), 12)
        self.assertEqual(len(scenario["target"]), 8)
        self.assertNotIn("Q", scenario)
        self.assertFalse(scenario["diagnostics"]["truth_used_for_fit_or_design"])
        status, _, full = self.request_json("GET", "/api/scenario?matrices=1")
        self.assertEqual(status, 200)
        self.assertEqual(len(full["Q"]), 20)
        self.assertTrue(all(len(row) == 20 for row in full["Q"]))
        self.assertEqual(len(full["C"]), 20)
        self.assertEqual(len(full["posterior_bias_covariance"]), 20)
        self.assertEqual(len(full["response_error_mean"]), 20)

    def test_interactive_config_limits_and_fixed_model_settings(self):
        query = urlencode({"seed": 5, "coverage": 1., "n_human": 6,
                           "n_target": 99, "noise": 2., "geometry": "stratified_w1"})
        status, _, scenario = self.request_json("GET", "/api/scenario?" + query)
        self.assertEqual(status, 200)
        self.assertEqual(len(scenario["human"]), 6)
        self.assertEqual(len(scenario["target"]), 8)
        self.assertEqual(scenario["config"]["seed"], 5)
        self.assertEqual(scenario["config"]["coverage"], 1.)
        self.assertEqual(scenario["config"]["noise"], .35)
        self.assertEqual(scenario["config"]["geometry"], "full_transport")
        for invalid in ({"n_human": 13}, {"n_human": 5}, {"n_human": 6.5},
                        {"seed": -1}, {"seed": 1.5},
                        {"coverage": 1.1}, {"coverage": "nan"}):
            with self.subTest(invalid=invalid):
                code, _, error = self.request_json("GET", "/api/scenario?" + urlencode(invalid))
                self.assertEqual(code, 400)
                self.assertTrue(error["error"])

    def test_actual_solve_satisfies_constraints(self):
        status, _, result = self.request_json(
            "POST", "/api/solve",
            {"config": {"seed": 42, "coverage": .45, "n_human": 6},
             "budget": 8, "tolerance": .08, "backend": "auto"},
            headers={"Origin": self.origin})
        self.assertEqual(status, 200, result)
        self.assertIn(result["status"], {"optimal", "optimal_within_tolerance", "time_limit"})
        self.assertEqual(len(result["wh"]), 6)
        self.assertEqual(len(result["ws"]), 8)
        self.assertEqual(len(result["selection"]), 8)
        weights = result["wh"] + result["ws"]
        self.assertAlmostEqual(sum(weights), 1., places=6)
        self.assertTrue(all(math.isfinite(w) and w >= -1e-7 for w in weights))
        self.assertTrue(all(w <= z + 1e-6 for w, z in zip(result["ws"], result["selection"])))
        self.assertLessEqual(sum(result["selection"]), 8)
        self.assertEqual(result["budget_used"], sum(result["selection"]))
        self.assertEqual(result["selected_indices"],
                         [i for i, z in enumerate(result["selection"]) if z])
        self.assertLessEqual(result["representation_distance"], .08 + 1e-6)
        self.assertTrue(math.isfinite(result["objective"]))
        self.assertGreaterEqual(result["objective"], -1e-8)
        self.assertTrue(result["diagnostics"]["representation_feasible"])
        self.assertFalse(result["diagnostics"]["truth_used_for_fit_or_design"])
        self.assertTrue(result["diagnostics"]["reuse_cross_covariance_retained"])
        self.assertIn(result["solver"], {"Gurobi convex MIQP", "SCIP convex MIQCP",
                                         "HiGHS convex outer approximation"})

    def test_invalid_post_requests_return_400(self):
        for payload in ([], {"budget": 1.5}, {"budget": 9},
                        {"budget": -1}, {"tolerance": -.1},
                        {"backend": "unknown"}, {"config": None}):
            with self.subTest(payload=payload):
                status, _, error = self.request_json("POST", "/api/solve", payload)
                self.assertEqual(status, 400, error)
                self.assertTrue(error["error"])
        for body in (b"", b"{invalid-json", b"x" * 16385):
            with self.subTest(raw_length=len(body)):
                status, _, error = self.request_json("POST", "/api/solve", raw=body)
                self.assertEqual(status, 400, error)
                self.assertTrue(error["error"])

    def test_cross_origin_post_is_rejected(self):
        for origin in ("https://example.invalid", f"http://127.0.0.1:{self.port + 1}", "null"):
            with self.subTest(origin=origin):
                status, headers, error = self.request_json(
                    "POST", "/api/solve", {"budget": 0}, headers={"Origin": origin})
                self.assertEqual(status, 403)
                self.assertTrue(error["error"])
                self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_static_assets_and_unknown_routes(self):
        for path, mime in (("/", "text/html"), ("/app.js", "text/javascript"),
                           ("/styles.css", "text/css"), ("/desktop.js", "text/javascript")):
            with self.subTest(path=path):
                status, headers, data = self.request("GET", path)
                self.assertEqual(status, 200)
                self.assertIn(mime, headers["Content-Type"])
                self.assertEqual(int(headers["Content-Length"]), len(data))
                self.assertEqual(headers["Cache-Control"], "no-cache")
                self.assertGreater(len(data), 50)
        for path in ("/missing", "/api/missing", "/../app.py"):
            with self.subTest(path=path):
                status, _, error = self.request_json("GET", path)
                self.assertEqual(status, 404)
                self.assertEqual(error["error"], "Not found")
        status, _, error = self.request_json("POST", "/api/missing", {})
        self.assertEqual(status, 404)
        self.assertEqual(error["error"], "Not found")


if __name__ == "__main__":
    unittest.main()
