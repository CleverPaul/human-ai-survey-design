# Validation record · 2026-11-01

All results here use synthetic data. No real questionnaire outcomes or LLM service were used.

**Environment:** Windows, Python 3.10.20, NumPy 2.2.5, SciPy 1.15.3, Gurobi/gurobipy 13.0.2. The package's legitimate restricted license solved the 188-variable default MIQP.

**Python checks:** `python -m unittest discover -s tests -v` passed **18 tests**. They cover posterior moments, full second moments and reuse dependence, transport, truth separation, actual Gurobi solutions, the HiGHS lower/upper bounds, infeasibility, the fixed-Q frontier, fresh-process license selection, and HTTP behavior. The API tests also reject noninteger budgets, nonobject JSON, invalid configurations, and foreign browser origins.

**Independent mathematical check:** conditioning the full primitive Gaussian vector `(theta, human noise, paired-AI noise, fresh-AI noise)` in one operation agrees with the implemented `Q` to at most **3.84e-16** over three seeds. The human-only geometric limit agrees with an independent transport LP to **2.78e-17** over six scenarios. The MSE identity and factor-two/Wasserstein bounds also hold in those checks. These checks validate calculations under the working model, not the correctness of its prior on new populations.

**Actual optimization:** seed 42, coverage .45, 12 humans, 8 target profiles, budget 3, tolerance .08. Selected indices `[3,5,7]`; response risk `0.021538113381858636`; independently recomputed distance `.08`; Gurobi gap zero. All seven feasible points of the stored fixed-Q frontier also had gap zero. Tolerances 0 and .025 were infeasible at budget 3.

**Browser checks:** local headless Chrome at 1440px and 390px widths. Verified initial solve, group switching, chart inspection/dragging, truth overlay, weights view, infeasible budget-zero case, feasible relaxed human-only case, human-coverage refit, frontier solving, and JSON download containing the complete 20×20 `Q`. The final run had no JavaScript/console errors and no horizontal page overflow at either width. Screenshots were inspected visually. Browser automation dependencies were installed outside this deliverable folder.

**Paper:** combined proposal/appendix 13 pages; independent appendix 8 pages; separate technical supplement 4 pages. A4/A5 and Figure A.1 were updated, the transport computation moved to S4, and obsolete solver-availability text removed. Existing A1–A3, main source, and proposal source were retained. The final LaTeX builds had no reported undefined citations/references or box warnings; selected pages were rendered and inspected.

**Remaining research work:** validate bias uncertainty with demographic holdouts, estimate noise from data, investigate metric/prior sensitivity, compare survey estimators, and run a real human–AI study. A single seeded demo does not establish empirical superiority or calibrated extrapolation uncertainty.
