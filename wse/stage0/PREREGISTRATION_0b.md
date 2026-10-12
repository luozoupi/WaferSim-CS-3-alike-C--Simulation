# Stage 0b pre-registration (2026-09-24)

Written before any Stage 0b measurement: launch-probe family, 2D-concurrency family, chain family, and all
test-kernel ground truth. Model-form choices made later, but before predictions, go in dated addenda at the
end of this file.

**Hypothesis.** Stage 0's composition failure has three causes. If each is modelled with constants measured
only on microbenchmarks, the fork predicts **unseen** collective kernels within 5% at P ≥ 16. The causes:
1. launch state induced by the host command sequence;
2. serialization of concurrent collectives on a PE;
3. transition cost between chained collectives.

## Calibration data (microbenchmarks only; train P ≤ 16, larger P = diagnostics)
- `collbench`: the existing 144 runs.
- **Launch-probe family** (`bench/launchprobe`). Host sequences built from:
  - h2d copies to a single PE, a row, a column and the full grid, with several positions and sizes;
  - blocking and non-blocking copies;
  - timer enabled before or after the copies;
  - a launch following a previous launch.
- **2D-concurrency family** (`bench/coll2d`): x-only, y-only and concurrent x+y collectives with count
  c ∈ {1…512} and roots at an end or mid-line.
- **Chain family**: op1 → op2 on one dimension, root first or last, x and y. **Excluded:** broadcast →
  reduce_fadds on x and scatter → gather on y with roots at 0, which are T2's chains.
- Compute: the local compute of each test kernel is measured on-device with phase stamps at P = 2 only.

## Test kernels (ground truth measured only after predictions are committed)
- **T1**: xkernel `GEMM Collectives 2D`, ported to SDK 2.10 with its `device_internal_v2` timing unchanged.
  Host sequence: h2d A and B to the full grid, enable timer, `main`.
  - Tiles (Mt, Kt, Nt) = (8, 8, 8) and (4, 4, 4); the second is communication-dominated.
  - P ∈ {4, 8, 16, 32}.
- **T2**: SDK tutorial `topic-11-collectives`.
  - Host sequence: h2d to column 0 and to row 0, both non-blocking, then `f_run_x`, then `f_run_y`.
  - Instrumented with device stamps: `f_enable_timer` is launched after the copies and before `f_run_x`.
    Each PE stamps on entry to its x task and at completion of its x chain, and likewise for y.
  - Metric per window: max end − min start (the `device_internal_v2` convention).
  - Chains: x = init + broadcast of Nx = chunk·P words from root 0, then reduce_fadds of Nx to root 0;
    y = init + scatter of chunk from root 0, then gather to root 0.
  - chunk ∈ {3, 16}, P ∈ {4, 8, 16, 32, 64}; x window and y window reported separately.
- **Regression checks** (seen in Stage 0, not tests): GEMV collectives_2d and SUMMA (xkernel GEMM), P = 2…64.

## Predictors
| id | predictor |
|---|---|
| S0b | fork with the three new mechanisms; launch state from the **launch law** (fitted on the probe family, test host sequences excluded) |
| S0b-probe | as S0b, but launch state measured by the probe replaying the test kernel's own host sequence (kernel-agnostic; an ablation isolating launch-law error) |
| S0 | the Stage 0 model, unchanged |
| A0b | analytic composition of the same laws (launch offset + per-op laws + concurrency law + chain law), no simulator |

## Gate (all must hold)
1. S0b |error| ≤ 5% at every P ∈ {16, 32} for T1, and at every P ∈ {16, 32, 64} for T2, on all six test
   series: T1 × 2 tiles, and T2 × {x, y} × 2 chunks.
2. S0b median |error| over the gate points ≤ A0b median |error|.
3. Regression: GEMV P = 16/32/64 within 5% and SUMMA P = 16/32/64 within 1%.

If S0b fails but S0b-probe passes, the report states that the launch law is the failing component. Protocol:
2 host threads, deterministic; a parallel run is reported only if it matches.

## Addenda
(dated, written before predictions)

### Addendum A — model freeze (2026-09-25, before any T1/T2 prediction or ground truth)
Everything below was fixed using calibration data only: collbench, the launch-probe family, the 2D
concurrency family (coll2d) and the chain family, with training at P ≤ 16. No T1 or T2 simfab run exists yet.

**Mechanisms added to the fork.** Build flags: `-DS0B -DS0_GATHER_TD -DWSE_GATES -DS0_GATES -DS0_PE
-DWSE_LAUNCH_STATE`. Semantics come from the SDK 2.10 csl-libs source (collectives_2d, memcpy), which is
extracted under `wse/refs/`.
1. **Launch state (host command queues).** Each row has its own command fan, and the host runs ahead. A
   copy-mode h2d stalls every row its region covers:
   - S(w,n) = 290.2 + 22.44·w + 1.0668·w·n + 0.1692·n;
   - copies of at most 15 words cost 39 (fast path);
   - rows outside the region are not stalled.

   Stalls add up per row. The main-launch lag counts the copies before `main`; the TSC-enable lag counts the
   copies before the timer launch. The baseline wave is 2 cycles per column. A launch that follows a
   finished kernel starts T2_RPC = 206 cycles after that PE's own completion.
   Fitted on 186 probe runs at P ≤ 16, on single-copy sequences (`launch_law.py`, `results/launch_law.json`).
2. **Colour teardown mode.** A router holds a colour's link traffic until the PE configures its next op. It
   closes again at op completion. A gather non-root opens for transit only after its own chunk has fully
   left (switch advance).
3. **Gather teardown.** The end PEs send a teardown after their chunk, and every PE's callback waits for it
   (C_LOCK).
4. **PE collective engine.**
   - An op call costs C_CFG = 101 on the CPU. Transfers start A_ACT = 55 after the issuing task ends. Both
     values come from simfab traces.
   - Concurrently active ops share one data engine in issue order. A receive holds the engine until its data
     is in.
   - The root sends its teardown T_TDD = 42 after its last data wavelet (broadcast/scatter, from the trace).
   - Completion = condition + F_post. When ops overlap, the next completion is at least P2_CPL = 140 after
     the previous one (P1_CPL = 0), fitted on coll2d at P ≤ 8.
   - F_post, recalibrated two-pass on collbench (train x, P ≤ 16):
     bcast 88/91, scatter 251/240, gather 239/355, reduce 485/590 (root first/last).
   - Per-word root cost B: scatter 1.31, gather 0.52/0.32. Reduce stage L_RE = 5.
5. **Chain transition.** op2's configuration cost gains δ(op1→op2) = u[op1] + v[op2] + s·[same].
   - Fitted on the 60 root-first chain rows, which exclude T2's pairs.
   - Table `S0_TRANS` (rows = op1 bc/sc/ga/re, columns = op2):
     {{−7.2, 11.7, 14.7, 9.0}, {12.5, −18.3, 9.6, 3.9}, {21.6, 15.7, −6.1, 13.0}, {6.8, 0.9, 3.9, −26.6}}.
6. **Init per dimension** = the maximum isolated init over that dimension's ops (chain family). This gives
   T1/SUMMA 25, GEMV 123, T2 x 86, T2 y 79.
7. **Compute** (P = 2 phase stamps): T1 8³ = 2,895 and 4³ = 611 per step; GEMV 107/101; SUMMA 11,904.

**Validation of the frozen model (calibration families, not test data):**
- microbenchmarks: training median 0.30% (max 2.9%), hold-out P = 32/64 median 0.55% (max 9.8%, gather
  c = 1), y-dimension median 0.85%, chained ×3 median 2.6% (max 9.1%);
- coll2d: concurrent median 1.8% (max 5.5%) at P ≤ 8, and median 1.2% (max 8.0%) at P = 16;
- chain family: median 0.73% (max 6.5%).

**Predictors.** Driver `s0b_predict.py`.
- **S0b:** twin plus launch-law header.
- **S0b-probe:** twin plus probe-replay header. The replays of T1/T2's host sequences were measured before
  any ground truth; they are kernel-agnostic launch-state inputs.
- **S0:** the Stage 0 flags and parameters.
- **A0b:** law row-0 lag + `laws.json` op laws + coll2d overlap (median x + y − xy over P ≤ 8, interpolated
  in count) + additive chain transition fitted on the chain family (chain − Σ isolated) + init + compute.
- Metrics: T1/GEMV/SUMMA use `TWIN_CS` (max end − min start in local TSC frames); T2 uses `TWIN_T2_X` and
  `TWIN_T2_Y`.

**Known limitations, stated before the test:**
- **(a) Single-PE copies at P = 64.** Diagnostic probes show the law under-predicts by 22–48% (per-copy
  stall ≈ 750 against ≈ 390 at P ≤ 32). Row copies hold (−4.7% at P = 64), and full-grid copies give no lag.
  Consequence: the GEMV regression check at P = 64 (two single-PE copies) is expected to miss by about 9%.
  T2 uses row copies: law vs probe replay is within ±5.4% at every T2 size (+12.5% = 48 cycles at P = 4,
  chunk 3).
- **(b) Chained ×3 gather** is over-predicted by 7–9%.
- **(c) Concurrent broadcasts at P = 16** reach 8% worst case.

The gate stays as pre-registered. S0b-probe is reported to separate launch-law error from everything else.
