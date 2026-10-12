# Stage 0c report: targeted re-scope after the 0b failure (2026-09-26)

**Pre-registered verdict: FAIL (narrow).**
- 15 of 19 test points are within 5%; the worst miss is −6.1%.
- S0c's median |error| is **1.05%**, against 2.10% for the Stage 0b model applied to the same kernels and
  3.75% for the analytic control A0c.
- Regression: SUMMA −0.36%, GEMV ≤ 4.6%, T1 ≤ 3.5%, T2 x windows ≤ 1.7%. One regression point misses: T2
  chunk 3 y window at P = 16, −6.8%. This was disclosed in the freeze addendum before the test.

Order of work, all dated in git:
1. pre-registration (`82dd480`);
2. model freeze and addendum A (`0b539b6`);
3. blind predictions (`3907146`);
4. ground truth and gate (`b65cf87`).

![Stage 0c errors](results/fig_s0c.png)

## Test results (S0c signed error vs simfab; gate points bold)
| series | P = 4 | 8 | 16 | 32 | 64 |
|---|---:|---:|---:|---:|---:|
| U1 xkernel GEMV, host tic/toc | +2.7 | +2.0 | **+2.1** | **+4.2** | **+5.7** |
| U2 GEMV-c2d 32×16 | −0.3 | +0.8 | **+2.6** | **+0.4** | **+2.2** |
| U2 GEMV-c2d 2×2 | −3.8 | +1.4 | **−1.1** | **+3.1** | **+5.1** |
| U3 GEMM-c2d 4×16×8 (asymmetric) | +0.2 | +0.3 | **0.0** | **0.0** | – |
| U3 GEMM-c2d 2×2×2 (count 4) | −3.5 | −4.9 | **−5.7** | **−6.1** | – |
| U4 allreduce-2D c = 8 | −0.8 | −0.9 | **−0.8** | **−0.2** | **+0.7** |
| U4 allreduce-2D c = 64 | −1.1 | −1.1 | **−1.0** | **−0.5** | **+0.4** |

The Stage 0b model applied to the same kernels (S0b) misses U1 by −8% to −10% because it has no
host-protocol model, and misses U2 2×2 at P = 64 by −9.8% because its launch law fails at P = 64.
S0c-probe (launch state measured rather than predicted) has a median of 0.79%.

## What the targeted microbenchmarks found
1. **G1, T2 x-path: two mechanisms, both measured.**
   - **Second-module teardown cost.** When the other dimension's collectives module exists, every teardown
     event costs 17 more cycles if that module is uninitialised, or 6 if it is initialised. This holds at
     every P and count; reduce has two teardowns.
   - **Local-entry offset of stalled rows.** δ = 20 for a direct launch, 54 for an RPC-activated task.
   - Refuted: custom queue/DSR ids and task activation have no effect.
   - Effect: T2 x windows went from −4.6% to −7.3% down to +0.8% to +1.7%. SUMMA and T1 per-step deficits
     shrank as well.
2. **G2, concurrency.** simfab traces show concurrent transfers **share bandwidth**; they do not take turns.
   The twin's exclusive engine plus serialized completions fits symmetric and large counts within about
   2%, but it cannot represent count-4 concurrency. That regime is U3 2×2×2's −5.7% to −6.1%, and T1 4³
   at −3.5% is the same effect.
3. **G3, launch at large P.** Single-PE copy stalls are not smooth in P:
   - the per-word cost falls from 1.23 to 1.0 cycles at P ≥ 32;
   - at P = 64 each copy gains about 230 cycles of fixed stall, and stalls become super-additive.

   Launch law v2, a per-P table from family C, fixed the Stage 0b failure: GEMV at P = 64 went from −5.3%
   to +4.6%. However, U1, U2 2×2 and GEMV at P = 64 now over-predict by 4.6–5.7%, and S0c-probe shows the
   same, so the remaining error is not in the launch law. It is in how the P = 64 launch state propagates
   through the GEMV collective chain.

## Assessment
- **Three stages, three narrow failures, and steady improvement on unseen kernels:**
  - Stage 0: GEMV −22% to −29%;
  - Stage 0b: 14/16 within 5%, median 3.1%;
  - Stage 0c: 15/19 within 5%, median 1.05%.

  Each failure was diagnosed to a concrete, measurable mechanism, and each fix came from microbenchmarks
  alone.
- **What is left is structural:**
  - bandwidth-shared concurrent transfers (small-count concurrency);
  - the y chain after a lagged row-0 launch (T2 chunk 3);
  - the P = 64 GEMV-chain launch propagation.

  The first needs a real PE data-path model (processor-sharing DSDs), which is the roadmap's Stage 2 scope.
  The other two need per-phase stamps inside those kernels.
- **Recommendation:** stop iterating Stage 0 re-scopes. The collective and runtime layer is now modelled to
  about 1% median. Remaining errors come from PE-level mechanisms that the roadmap assigns to Stages 1–2.
  - Carry the three gaps forward as named Stage 1 and 2 targets.
  - Treat the Stage 0c model (1.05% median, worst −6.8%) as the collectives baseline those stages must
    not regress.

## Reproduce
Calibration families:
- `bench/idbench/sweep.py`, `bench/t2xbench/sweep.py`
- `bench/coll2d/sweep3.py`
- `bench/launch2d/sweep.py` with `FAMILY_C=1` and `FAMILY_C2=1`
- `s0c_compute.sh`

Model:
- `launch_law2.py fit`
- `s0b_coll2d.py run 0 140 8` with `C2_EXTRA=… -DTWO_MODULES`

Predictions, truth and gate:
- `s0c_predict.py twin S0c|S0c-probe|S0b` and `s0c_predict.py analytic`
- `s0c_truth.py`, then `s0c_gate.py`
