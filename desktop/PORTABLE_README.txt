Survey Design Lab - portable Windows demonstration
==================================================

Open SurveyDesignLab.exe to start. Keep the _internal folder next to the
executable. No Python installation, Gurobi license, browser, or internet
connection is needed. Computation runs locally using the bundled SCIP solver.

The demonstration uses synthetic survey data. Change the controls to explore
the estimated AI bias, debiasing uncertainty, and optimized human/AI weights.
Use Download run to save the current scenario, fitted matrices, and solution
as a JSON file. Trace frontier compares different representational tolerances.

Source and rebuild instructions accompany the research materials in code/:
  README.md
  desktop/BUILD.md
  desktop/requirements-build.txt
  desktop/SurveyDesignLab.spec

Third-party licenses are in _internal/third_party_notices. The adjacent
THIRD_PARTY_NOTICES.txt lists the bundled components and upstream sources.
