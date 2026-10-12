# Stage 0c pre-registration: re-scope after the Stage 0b gate failure (2026-09-25)

Written before any Stage 0c measurement: calibration families A–C, test-kernel compute stamps and test ground
truth. Stage 0b's model (`0fada00`) is the starting point. Changes made later, but before predictions, go in
dated addenda.

**Why re-scope.** The Stage 0b gate failed narrowly (14 of 16 points within 5%). Three attributable gaps
remained:
- (G1) a near-constant 66–94 cycle deficit on T2's x path, for every predictor;
- (G2) under-serialization of concurrent broadcasts at small counts (T1 4³ drifted to −4%);
- (G3) single-PE h2d copy stalls about double at P = 64 (GEMV at P = 64 was −5.3%).

Stage 0c measures each gap with its own microbenchmark family, updates the model, and runs a new gated test
on kernels and regimes not used before.

## Calibration families (microbenchmarks only)
- **A. Module and activation path (G1).** One collective, or one chain, on a line of P PEs, in three
  variants:
  - `main` with default queue/DSR ids;
  - `main` with custom ids (topic-11 style);
  - custom ids with the op started from a task that an RPC activates (topic-11 style), stamped at task
    entry before init.

  Ops: bcast, scatter, gather, reduce, and chains bcast→reduce and scatter→gather. Counts 8 and 64.
  Train P ∈ {4, 8, 16}; check at P = 32.
- **B. Concurrency at small and asymmetric counts (G2).** coll2d with concurrent x+y broadcasts:
  - symmetric counts {2, 4, 8, 16, 32};
  - asymmetric (x, y) counts {(64, 128), (128, 64), (4, 16), (16, 4)};
  - roots at 0 and mid-line.

  Train P ∈ {4, 8}; check at P = 16.
- **C. Launch stalls at large P (G3).** Launch-probe sequences with single-PE copies (n ∈ {64, 256, 1024}),
  a GEMV-like full-grid copy followed by two single-PE copies, and a row copy. Run at P ∈ {32, 48, 64} plus
  the existing P ≤ 16 data. Training covers all probe sizes: the gap is at large P and probes are not test
  data.
- Existing families (collbench, coll2d, chain, launch probe) remain calibration data. T1 and T2 ground truth
  are **regression data** from now on: they may be used for diagnosis but not for fitting.

## Test kernels (new; ground truth only after predictions are committed)
| id | kernel | what is new | sizes |
|---|---|---|---|
| U1 | xkernel `GEMV` (host-launched `f_tic`/`main`/`f_toc` timing) | timing protocol (three host launches) | P ∈ {4, 8, 16, 32, 64} |
| U2 | GEMV collectives_2d, blocks (Mt, Nt) = (32, 16) and (2, 2) | counts 16–32 and 2; single-PE copies of up to 2,048 words at P = 64 | P ∈ {4, 8, 16, 32, 64} |
| U3 | GEMM collectives_2d, tiles (Mt, Kt, Nt) = (4, 16, 8) and (2, 2, 2) | asymmetric concurrent broadcasts (64 x / 128 y) and count 4 | P ∈ {4, 8, 16, 32} |
| U4 | allreduce-2D composition (**written by the modeller** before any measurement): reduce_fadds x → bcast x → reduce_fadds y → bcast y, roots P−1, full-grid input copy | mixed-op chains across dimensions, bcast after reduce | c ∈ {8, 64}, P ∈ {4, 8, 16, 32, 64} |

Compute costs (U2 local GEMV and U3 local GEMM) are measured with phase stamps at P = 2 only. U4 has no
compute beyond the collectives' fadds.

## Predictors
| id | predictor |
|---|---|
| S0c | fork with the Stage 0b mechanisms plus the family A–C updates; launch state from the updated launch law |
| S0c-probe | as S0c, with launch state from probe replays of each test's host sequence (ablation) |
| S0b | the frozen Stage 0b model (`0fada00`), unchanged |
| A0c | analytic composition: updated launch law + op laws + concurrency and chain laws |

## Gate (all must hold)
1. S0c |error| ≤ 5% at every gate point: U1, U2 and U4 at P ∈ {16, 32, 64}; U3 at P ∈ {16, 32}. That is
   19 points across 7 series.
2. S0c median |error| over the gate points ≤ A0c median, **and** ≤ S0b median.
3. Regression with the updated model, at P ≥ 16:
   - GEMV and T2 (x and y windows) within 5%;
   - T1 within 5%;
   - SUMMA within 1%.

Protocol: 2 host threads (4 for twins with P = 64 GEMM), deterministic.

## Addenda
(dated, written before predictions)

### Addendum A — model freeze (2026-09-26, before any U1–U4 ground truth or prediction)
All changes below come from calibration families A–C and follow-up microbenchmarks. T2 ground truth was used
only for the disclosed diagnostic at the end; no U1–U4 simfab timing exists.

**G1: T2 x-path deficit, resolved by two mechanisms.** Both were measured with the 2D T2-x bench and
`idbench`.
- Refuted: custom queue/DSR ids have no effect; RPC-activated tasks change timing by −10 to +6 cycles.
- **Second-module teardown cost** (`-DTWO_MODULES`). When the other dimension's collectives module exists,
  each teardown event costs:
  - Q_TD2 = 17 if that module is **not** initialised (2D bench: bcast +17, reduce +34, bcast→reduce +51,
    constant in P and count);
  - Q_TD2_INIT = 6 if it **is** initialised (coll2d single-direction vs collbench: +6 at every P and count).

  Reduce has two teardowns. The twin tracks module initialisation per PE: T2's x-run has an uninitialised
  y module; every other kernel initialises both.
- **Local-entry offset of stalled rows.** A row delayed by host copies has its TSC enable lag its launch by δ
  less than its launch lag: δ = 20 for a directly launched function (probe), 54 for an RPC-activated task
  (2D bench: +54 on row 0 only; chain lengths unchanged).
- Diagnostic: column copies of ≥ 64 words create no within-row lag (four-direction probes, family C2).

**G2: concurrency.**
- Family B: small counts under the 0b model are −1% to −3.8%; asymmetric (x, y) = (64, 128) is +6% to +8%.
- simfab traces show that concurrent transfers **share bandwidth** (they interleave at about half rate)
  rather than serialising. The twin keeps the exclusive engine: a known structural limitation, worth +6% to
  +9% on communication time for (64, 128).
- With the second-module cost in place, P2_CPL was refitted on coll2d at P ≤ 8 (grid 125/140/155) and stays
  at **140**.
- `S0_ARRIVAL` (conditions taken from message delivery times) was evaluated and **rejected**: it degraded the
  gather calibration and did not remove the asymmetry. CPL_BLOCK stays at 1.
- Validation (S0c model):
  - single-direction coll2d: median 0.4–1.3%, max 2.2%;
  - concurrent: median 2.1 / 1.3 / 1.8% (max 9.3 / 8.9 / 9.0%) at P = 4 / 8 / 16, with P = 16 as the check.

**G3: launch law v2** (`launch_law2.py`, `results/launch_law2.json`), fitted on the probe families,
including family C at P = 32/48/64.
- Single-PE copies, S1(n, P) = a_P + b_P·n:
  - P ≤ 16: 315.7 + 1.226n;
  - P = 32: 321.0 + 1.000n;
  - P = 48: 317.7 + 0.993n;
  - P = 64: 547.0 + 1.000n.
- A single-PE copy following another single-PE copy adds k_prev: 69 at P = 32, 0.5 at P = 48, 126 at P = 64.
- One following a full-grid copy adds k_full: −5 at P = 32, 84.5 at P = 48, 208 at P = 64.
- Both terms are 0 at P ≤ 16.
- Row copies use the Stage 0b law; full-grid copies cause no relative lag.
- Held-out check (full copy + 3 single-PE copies): P = 64 +1.6%, P = 32 +9.5%.

**Test-kernel twins.**
- U1: kernel 5 with TT_TIC = 227 (`main` starts 227 after the f_tic stamp) and TT_TOC = 207 (f_toc stamps
  207 after completion), both from the launch probe's launch-to-launch latency.
- U2: kernel 5 with the measured compute (32×16: 1112/1094; 2×2: 49/46).
- U3: kernel 6 with asymmetric counts (GEMM_WX/WY) and compute 4846 / 146.
- U4: kernel 9, init 124 + 124 by the program-dimension init rule.
- Constants are otherwise the Stage 0b ones (`wse_s0c_params.h` = the 0b parameters).

**Predictors** (`s0c_predict.py`):
- **S0c:** flags `-DS0B -DS0C -DS0_GATHER_TD -DWSE_GATES -DS0_GATES -DS0_PE -DTWO_MODULES -DP2_CPL=140
  -DWSE_LAUNCH_STATE` plus launch law v2.
- **S0c-probe:** the same, with probe-replayed launch states. U1 uses the GEMV sequence and U2 uses its own
  replays; U3 and U4 copy only full grids, which give zero lag.
- **S0b:** the 0b flags plus launch law v1 on the same kernel descriptions, without the tic/toc offsets.
- **A0c:** as defined in the driver.

**Disclosed diagnostic on regression data** (T2 at P = 16/32, computed with the frozen S0c model):
- x windows: +1.3 / +0.9 / +1.3 / +0.8%;
- y windows: −6.8% (chunk 3, P = 16), −3.0%, −2.2%, +2.7%.

Regression criterion 3 is therefore at risk at T2 chunk 3, P = 16. About 54 cycles of that miss come from
launch-law error at that size; the rest is an unexplained y-chain deficit in context. Nothing was changed in
response.
