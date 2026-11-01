# Implementation and relation to the appendix

The target contains demographics `x_k^t` with given weights `w_k^t`. The human sample contains `(x_i^h,y_i^h)`. Human and AI outcomes follow

```math
y_i^h=f(x_i^h)+\varepsilon_i^h,\qquad
y_k^s=f(x_k^t)+b(x_k^t)+\varepsilon_k^s.
```

Parallel AI simulation at each human profile provides

```math
\delta_i=y_i^{h,AI}-y_i^h=b(x_i^h)+\varepsilon_i^p-\varepsilon_i^h.
```

Only profiles, paired differences, and declared noise inputs enter calibration. The simulator's true `f` and `b` and the potential fresh target responses never enter the decision objective or constraints. Potential fresh responses are drawn once per scenario to make comparisons reproducible; they are revealed only for selected profiles after design.

## Bias model

The prototype uses a nonlinear Gaussian Bayesian spline/GAM:

```math
b(x)=\phi(x)^\top\theta,\quad \theta\sim N(0,V_0),\quad
\boldsymbol\delta\mid\theta\sim N(\Phi_h\theta,D),\quad
D=\operatorname{diag}(h_i+p_i).
```

Here `h_i,p_i` are the known human and paired-AI noise variances in the simulation. Cubic B-splines in normalized age have knots at 0, .25, .5, .75, 1, and group-specific smooth deviations. Priors are proper and fixed; their standard deviations are exported. The 18-column basis has overlapping level/linear/spline terms. Proper priors make predictions well-defined; individual overlapping coefficients should not be interpreted separately. The interface displays function curves.

```math
V=(V_0^{-1}+\Phi_h^\top D^{-1}\Phi_h)^{-1},\qquad
\widehat\theta=V\Phi_h^\top D^{-1}\boldsymbol\delta.
```

For the concatenated human and target profiles, the joint bias mean/covariance are `Phi theta_hat` and `K = Phi V Phiᵀ`. Target bias corrections and uncertainty follow from the target rows. The chart band is `bias mean ± 1.96 × bias standard deviation`; it excludes fresh individual-response noise. Profiles outside the human sample but inside the defined age domain can be evaluated. These posterior intervals depend on the chosen basis and prior.

## Reusing humans for calibration

Condition throughout on profiles, observed paired differences, and fitted settings. Do not additionally condition on realized human outcomes. Write `kappa_i=h_i/(h_i+p_i)`. Gaussian conditioning gives

```math
E[\varepsilon_i^h\mid b_H,\delta_i]=\kappa_i(b(x_i^h)-\delta_i),\qquad
\operatorname{Var}(\varepsilon_i^h\mid b_H,\delta_i)=h_ip_i/(h_i+p_i).
```

For response errors `e=(epsilon_h; b_T-bhat_T+epsilon_fresh)`, let

```math
m=\begin{pmatrix}\kappa\odot(\widehat b_H-\delta)\\0\end{pmatrix},\quad
A=\operatorname{diag}(\kappa_1,\ldots,\kappa_{n_h},1,\ldots,1).
```

Then the implemented second moment is

```math
Q=A K A^\top+
\operatorname{diag}\left(\frac{h_ip_i}{h_i+p_i},\tau_k^2\right)+mm^\top.
```

This includes the positive human–target cross covariance and human conditional mean. Fresh target-generation variance `tau_k²` enters once. `Q` is positive semidefinite by construction. In JSON exports, `C` denotes the **full response covariance** `Q-mmᵀ`, whereas the paper uses `C` for the **target latent-bias covariance**; `posterior_bias_covariance` exports the joint human/target `K`. Dimensions and meaning must be respected when comparing them.

For fixed weights, the identity checked is

```math
\operatorname{MSE}(\widehat\mu)
=\Delta_f^2+2\Delta_f w^\top m+w^\top Qw
\le 2\Delta_f^2+2w^\top Qw.
```

The reported `conditional_total_mse_assessment` evaluates this fitted-model expression using simulated `f` only for assessment. It is not the MSE under the simulator's fixed true bias function. The optimizer never receives `Delta_f` or `f`.

## Design problem

```math
\min_{w,z}\;w^\top Qw\quad\text{s.t.}\quad
W_1(P_{mix}^w,P_t)\le\epsilon,\quad
\sum_k z_k\le B,\quad 0\le w_k^s\le z_k,\quad
w_i^h\ge0,\quad \mathbf1^\top w=1,\quad z_k\in\{0,1\}.
```

The default full transport formulation has ground cost `|age/62 difference| + .5 × group mismatch`, with age normalized from 18–80. A group mismatch therefore costs the equivalent of 31 years in the chosen metric; it is not a literal age difference. All human and target profiles can transport to all target profiles at finite cost. Target weights are .125 each. The default problem has 20 weights, 8 binaries, and 160 transport variables, for 188 variables total.

Gurobi directly solves the convex MIQP. The optional license-free backend builds a MILP epigraph approximation with tangent cuts `t ≥ 2vᵀQw − vᵀQv`, refining feasible supports using a convex continuous problem. MILP dual bounds are valid lower bounds; the actual quadratic objective at feasible returned weights is an upper bound. A nonzero gap or time limit remains visible.

The optional CLI geometry `stratified_w1` imposes exact group masses and within-group transport. It is a stricter alternative and is **not used by the interface or default results**.

## What the example establishes

The human-only geometric limit matches an independently solved transport LP. Conditional second moments match independent Gaussian conditioning and Monte Carlo checks. The default fixed-model frontier has an infeasible region, then decreasing optimal response risk as tolerance increases. These verify the implementation and set-containment result. They do not establish uncertainty calibration on real data, superiority to existing survey estimators, or a universal benefit from adding AI respondents.
