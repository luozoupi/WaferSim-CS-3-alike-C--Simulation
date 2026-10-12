# Stage 1 pre-registration (2026-09-26, before any Stage 1 measurement)

## Hypothesis
A wavelet-level fabric model predicts every fabric mechanism measured by simfab within ±3% on held-out
configurations. Its constants are hop, link rate, turn, input-buffer depth, arbitration, multicast and
control-wavelet costs, each measured once. Collectives rebuilt from routing configuration on that fabric
(M5) reproduce the Stage 0 collectives baseline without the Stage 0 per-op primitives.

## Ground truth
- **simfab 2.10 WSE-3.** Traced runs give per-router wavelet timing, paired by wavelet `ident`. TSC windows
  are used for kernel-level metrics.
- **Families**, each with train and hold-out sizes fixed in `wse/bench/fabric/cases.py` before any run:
  - straight paths (4 directions × hops × payload);
  - turns (orientation × leg length);
  - multicast (trunk × fan-out, tap position);
  - contention (distinct colours sharing a link, 2–8 sources);
  - store-and-forward relay (N stages × payload);
  - switch advance (positions, number of control wavelets);
  - teardown (reset, re-configure);
  - backpressure (receiver delay × payload; exposes input-buffer depth).
- **Metric** per case: first-wavelet latency, last-wavelet latency and inter-wavelet spacing at the
  destination (from traces), plus the TSC window where one applies.

## Gate (all must hold)
1. **Fabric curves.** Every hold-out case in every family within ±3% of simfab on its primary metric, the
   last-wavelet arrival at the destination.
2. **Collectives from routing configuration** (M5):
   - collbench (144 configs) median |error| ≤ 1% and max ≤ 5%;
   - chain family median ≤ 1.5%;
   - coll2d single-direction median ≤ 1.5%.
3. **Stage 0 regression suite** (Stage 0c truths):
   - median |error| on the 19 U gate points ≤ 1.55%;
   - no point currently within 5% moves outside 5%;
   - SUMMA within 1%.
4. **Determinism.** Identical cycle counts across three repeated runs of every gate case.

## Baselines reported alongside
- the Stage 0c model (the frozen collectives baseline);
- the FINDINGS closed forms (hop 2, wavelet 1.000, turn ≈ 33, relay T = 1.001·N·B + 16.1·N + 16.5).

## Addenda
(dated, written before the corresponding measurements or predictions)

### Addendum A (2026-09-26): switch-advance and teardown families; hold-out handling
Written before any run of these families. The cases are fixed in `wse/bench/fabric/cases.py:addendum_a()` (61 cases).
They run on the probe program `pe_ctl.csl`, and every run is traced. Control words use the collectives_2d
encoding: commands at bits 22 and 25, every command with the no_ce bit set.

| family | configuration | parameters (hold-out) | primary metric |
|---|---|---|---|
| sa_tx | Sender at 0, switch tile m, end L = 2m. Tile m: pos0 W→R, pos1 tx E. The sender sends B1 data, one ADVANCE, then B2 data. | m ∈ {1, 4, **8**, 16}, B1 ∈ {1, 64}, B2 ∈ {64, 512} | last B2 arrival at L − first injection |
| sa_rx | Root at m with pos0 W→R and pos1 rx E. The left sender sends B data then an ADVANCE; the right sender (at 2m) sends B data. | m ∈ {1, **4**, 8}, B ∈ {8, 64, 512} | last arrival at root − first injection (either sender) |
| sa_chain | Gather chain. Tiles 0..N−1 have pos0 R→E and pos1 rx W; each sends B with `.advance_switch`. The root at N receives N·B. | N ∈ {2, 4, **8**, 12}, B ∈ {1, 8, 64, 256} | last arrival at root − first injection (any sender) |
| sa_ring | Timed replica of the topic-06 tutorial: the centre of a 3×3 has pos1–3 = W, E, S, current position 1 and ring mode, and sends [ADVANCE, B data] × 4. | B ∈ {1, 16, **64**, 256} | last data arrival over the 4 receivers − first injection |
| td_line | Sender sends B data then a TEARDOWN over L hops; tiles have tx {R, E}. Each PE's teardown handler injects a marker (R→R colour 9) and exits teardown. With P2 > 0, the sender then sends P2 words and every receiver receives them. | L ∈ {1, 4, **8**, 16}, B ∈ {1, 64}, P2 ∈ {0, 64} | P2 = 64: last P2 arrival at L − first injection. P2 = 0: marker injection at L − first injection. |

- **Secondary metrics** (reported; not gated):
  - sa_tx switch gap: first B2 arrival at L minus last B1 arrival at m;
  - td_line handler latency per tile: marker injection minus TD arrival at the same router;
  - sa_chain per-sender hand-off.
- **Gate.** Gate item 1 applies to these families unchanged: every hold-out case within ±3% on its primary metric.
- **Semantics under test.** The switch semantics in `src/wse/fabric.h` come from `wse/refs/` and the tutorials.
  The engine reproduces topic-06's functional result: East 0, South 2, North 4, West 6. The behaviours under test
  are:
  - a control wavelet is routed on the current position, then executes cmd0 at every router it passes;
  - pop modes shift cmd1 into cmd0 downstream;
  - no_ce suppresses ramp delivery;
  - teardown holds the colour until the PE exits it;
  - `.advance_switch` advances only the sender's own router after the DSD's last wavelet, as a sideband with no
    control wavelet on the wire. This is inferred from the gather protocol and is the least certain item; sa_chain
    tests it.
- **Hold-out handling for all M1 families.**
  - Profile constants are fitted on train rows only (`compare.py --role train`).
  - The fitted profile is committed. Hold-out predictions are then written to `results/fabric_pred_holdout.json`
    and committed before any hold-out row is compared.
  - **Disclosure:** during a progress check on 2026-09-26, the raw rows of two straight hold-out cases
    (`straight_E_h8_B8` and `straight_E_h8_B64`) were displayed in the terminal. No model constant has been changed
    since, and none will be changed on their account.

### Addendum B (2026-09-26): M5 constant sources; written before any M5 comparison with simfab
The M5 model is:
- the fabric (`src/wse/fabric.h`) with the M1 profile fitted on train rows;
- the F1 PE model (`src/wse/pe.h`) with the same fit;
- the `<collectives_2d>` port (`src/wse/c2d.h`), which follows `pe.csl` function by function.

Its functional test is `wse/stage1/tests/test_c2d.cpp`: 720 of 720 configurations move the right data.

**Constant sources.** No constant is fitted on collbench, chain or coll2d. Every constant comes from one of these
sources:

| constant | value | source |
|---|---|---|
| fabric: hop, link, buffers, turn | M1 fit | M1 train rows |
| F1 PE: s0, s0_ctl, a0, cpl, disp, td_disp, exit, fwd_lat | M1 fit | M1 train rows (Addendum A families) |
| `handler`, `lock` (task bodies that only activate a task) | M1 fit | the M1-fitted generic task-body cost |
| `init` | 25 | collbench `init_max` (measured stamp, not a fit) |
| `init2` | 9 | coll2d `init_max` 34 − 25 (measured stamp) |
| `cfg` | 101 | Stage 0c C_CFG |
| `act` | 55 | Stage 0c A_ACT |
| `tdd` | 42 | Stage 0c T_TDD (simfab trace) |
| `td2` | 6 | Stage 0c Q_TD2_INIT |
| `copy`, `fadd` | 1.0 cycle/word | FINDINGS wavelet rate |
| launch | LW = 2, LY = 0 | as in Stage 0 for these benches |

None of Stage 0's per-op primitives is used: no S0_F, S0_B, S0_TRANS, P2_CPL or CPL_BLOCK.

**Evaluation.**
- Gate item 2 metrics as pre-registered, on `op_only`:
  - collbench (144 configurations): median ≤ 1%, max ≤ 5%;
  - chain (92): median ≤ 1.5%;
  - coll2d MODE 0/1: median ≤ 1.5%.
- MODE 2 (concurrent) is reported but not gated. Concurrent-DSD bandwidth sharing is a Stage 2 gap.
- The Stage 0c model's errors on the same sets are reported alongside.

**Disclosure.** During development, `c2dsim` printed model values for P = 8, count = 8, x-dimension, all four ops,
roots first/last, as a completion smoke test. While the collbench row format was being inspected, the simfab rows
for gather at P = 8, x, reps 1 (counts 1/8/64, roots first/last) were displayed. No constant was chosen with
reference to either.

**If the gate fails,** one diagnosis round is allowed. It needs a new dated addendum naming the mechanism.
Structural fixes (for example, the port or fabric semantics) are allowed if they are justified by SDK source or M1
traces. Retuning constants on the gate sets is not allowed.

### Addendum C (2026-09-26): M1 data, model changes from train traces, freeze procedure
Written after fitting on train rows and before any hold-out comparison. No hold-out primary metric has been displayed
or computed.

**Data.**
- All 333 M1 cases ran as 8 shelf-packed traced simfab runs (`wse/bench/fabric/packed.py`); every case passed its
  count checks.
- **Packing check:** 21 cases also run unpacked match the packed rows in relative time on 19 cases. The two that
  differ (`straight_E_h1_B256`, `straight_E_h1_B512`) differ because of runtime traffic at a different placement;
  see below. For the held-out one of the two, only the match flag was displayed, not its values.
- **Decoding fix:** simfab splits traces over several CTF streams, and the old decoder read `stream0` only. The
  first packed pass therefore produced empty or partial rows. These were discarded (`*_stream0only.jsonl`) and all
  batches re-run.

**Fabric semantics revised from train traces** (sa_rx, sa_chain, td; each change re-verified by the unit tests and
the 720-configuration collectives test):
- one FIFO per colour;
- a wavelet is accepted only on the input the current switch position selects, and not in teardown mode;
- control commands act on the input side at acceptance and on the output side at forwarding;
- `.advance_switch` advances the input side when the last wavelet enters from the ramp.

**Runtime traffic replay (new input condition).**
- On train rows, every 1-cycle receive bubble on eastbound data falls one cycle after a memcpy-runtime wavelet
  (colours 21/22) at that router: 47/47 straight-E, 242/242 multicast, 30/30 relay, 105/105 backpressure.
  Westbound, northbound and southbound data show none.
- The model therefore replays each run's measured runtime wavelets, relative to the case's first injection. Each
  one reserves the eastbound link into its tile for that cycle.
- The replay replaces the fixed receive-bubble period (`ib = 0`). It uses runtime traffic only, never the case's own
  data.

**Backpressure family flaw.**
- The receiver's delay loop in `pe.csl` was removed by the compiler. On train rows the arm stamp is 237 for every D,
  and arrivals do not depend on D.
- The family therefore degenerates to straight transfers. It stays in gate item 1 as pre-registered, with `DL = 0`
  set from the train stamps.
- Input-buffer depth is not exposed by M1. A corrected probe needs a new addendum.

**Known limitation.** The same data-to-control transition in `pe_ctl.csl` takes 79–89 cycles depending on the
compiled probe variant. It is not modelled per variant, so sa_rx hold-out cases at small B may miss ±3%.

**Freeze procedure.**
1. Final train-only fit → `wse/stage1/profile_m1.txt`.
2. `predict_holdout.py` writes `results/fabric_pred_holdout.json`. It reads from each hold-out row only its runtime
   traffic and first-injection time.
3. Commit steps 1 and 2.
4. `gate_m1.py` compares the predictions with simfab.

No constant changes after step 3.

### Addendum D (2026-09-27): M5 diagnosis round — library CPU costs from a disjoint traced calibration set
Written before the calibration run, after the M5 evaluation under Addendum B failed gate item 2 (collbench median
25.6%, chain 30.0%, coll2d single-direction 10.0%; `results/m5_eval.json`, commit 4d1ee66).

**Diagnosis.**
- The fabric side of the port is right: broadcast's P-slope matches simfab to the cycle.
- The deficit is a per-op-kind constant: about 33 cycles for bcast, 190 for scatter, 120–225 for gather and
  250–630 for reduce. Reduce also has a P-dependent term of about 4.5 cycles per PE.
- These are CPU costs inside `<collectives_2d>` and the runtime: configure functions, FSM passes, the teardown
  handler (task 29), `f_lock` and the callback. Addendum B represented them with single Stage 0c constants.
- An existing simfab trace, used only for analysis design, shows:
  - main 216 cycles, FSM passes 36 and 40, teardown handler 48, lock 3, callback 24;
  - the send DSD completes before its data is injected, which implies an output queue.

**Calibration set** (the train set of this round). It is disjoint from every gate set: collbench uses
P ∈ {4, 8, 16, 32, 64}, chain P ∈ {8, 16} and coll2d P ∈ {4, 8, 16}.
- One packed, traced simfab run of x-dimension lines with P = 12.
- 28 independent rows:
  - 4 ops × roots {0, 5, 11} × counts {4, 24}, reps 1;
  - 4 ops × root 0 × count 4, reps 2 (the second call is issued from the callback task).
- The collbench `pe.csl` and `run.py` are used unchanged.

**Extraction.**
- From instruction traces, per PE:
  - each task invocation, identified by the task's entry PC, with its start and end;
  - the async DSD issue, i.e. the first dispatch with `ut_id` ≠ 255.
- From wavelet traces: injections and arrivals on C0/C1.
- From device stamps: each row's `op_only`.

**Allowed model changes.**
- Structural, in the port or PE model:
  - an output queue between a send DSD and the router, whose depth is measured;
  - task costs per op kind, per PE role and per FSM pass (start to issue, and length), as measured;
  - measured activation latency, teardown-handler latency and length;
  - reduce stage latency and pace;
  - local copy and add rates.
- Constants are initialised from trace medians. A residual end-to-end fit is allowed only on the calibration rows'
  `op_only`.
- The M1 fabric profile (`profile_m1.txt`) stays frozen.

**Evaluation.**
1. Commit the calibrated cost table and the gate-set predictions (collbench 144, chain 92, coll2d 207).
2. Evaluate once against gate item 2's pre-registered thresholds.
3. Report the Addendum B result alongside.

No further diagnosis round is pre-authorised.

### Addendum E (2026-09-27): second calibration P for the M5 cost table (user-approved second diagnosis round)
Written before the P = 40 calibration run.

**Reason.**
- Under Addendum D, gate item 2 failed only on the collbench max: 6.72%.
- All 5 cases beyond 5% are reduce at P ≥ 32, where the model is short by about 1.5 cycles per PE. This is the
  per-stage forward latency: the traces show 7–8 cycles, while the fit settled at `fwl = 5`.
- With a single calibration P, per-stage latency cannot be separated from fixed offsets.

**Calibration set E.**
- The Addendum D design at P = 40, in one packed traced simfab run. P = 40 is not in any gate set.
- 28 rows: 4 ops × roots {0, 20, 39} × counts {4, 24}, reps 1; plus 4 ops × root 0 × count 4, reps 2.
- The collbench `pe.csl` is used unchanged.
- The P = 12 data (commit dfbbec9) are kept unchanged.

**Model.**
- Each cost-table entry becomes a + b·count + c·P, least squares over the 4 points (P ∈ {12, 40} × counts
  {4, 24}), with no count·P term.
- The residual scalars are refit on both calibration sets (56 rows). The M1 fabric profile stays frozen.
- No other change.

**Evaluation.**
1. Commit the frozen profile and the gate-set predictions.
2. Evaluate once against the pre-registered gate item 2 thresholds.
3. Report alongside the Addendum B and Addendum D results.

No further round is pre-authorised.

### Addendum F (2026-09-27): gate item 3 — the Stage 0 regression suite on the Stage 1 engine
Written before implementing the kernel port. The Stage 0c truths are already known: they were the Stage 0c gate.
So nothing is fitted on them, and the evaluation is run once, after the predictions are committed.

**Scope.** The 55 rows of `wse/stage0/results/s0c_summary.json`:
- GEMV and SUMMA at P = 16/32/64;
- T1_t4/t8 at P = 16/32;
- T2_c3/c16 x and y at P = 16/32/64;
- U1, U2_2x2, U2_32x16, U4_c8 and U4_c64 at P = 4–64;
- U3_2x2x2 and U3_4x16x8 at P = 4–32.

The kernels are ported function by function from their CSL sources (`wse/bench/test/*`,
`muchisim_eval/pilot/sdk/gemm`, `gemv`) onto `fabric.h`, `pe.h` and `c2d.h`. Each kernel's task graph (main,
callback tasks, compute tasks, pass-through tasks, the exit stamp) follows its source.

**Constant sources** (nothing fitted on the regression suite):

| component | source |
|---|---|
| fabric | `profile_m1.txt` (frozen) |
| collectives port and PE | `profile_m5e.txt` (frozen, Addendum E) |
| init per module | Stage 0c program-dimension init rule, as used by `s0c_predict.py`: K_INIT = 123 for the GEMV family, 25 for SUMMA/U3/T1, 124 + 124 for U4; T2 uses 86 for x and 79 for y |
| compute | Stage 0c on-device measurements: GEMV_C0/C1 per variant, SUMMA_C per variant |
| U1 host tic/toc | TT_TIC = 227, TT_TOC = 207 |
| T2 run-to-run latency | T2_RPC = 206 |
| launch state | Stage 0c launch law v2 (`launch_law2.predict`): L = 2x + L_row[y], E = 2x + E_row[y] |
| op-call costs | port call types: the first op after main's inits → cfg1; ops issued from a callback-activated task → chained (cfgn); a second op in the same body → cfgn only |
| glue tasks | tasks that only activate or unblock another task (skip paths, SUMMA x_done/y_done) → the measured `lock` length (4 cycles) |
| exit stamp | taken k_ts2 into the exit task |

- **No runtime-traffic replay:** there are no traces of these runs.
- **Metric:** `cycles_send` = max(end − E) − min(start − E). For T2: the x window (stamps 0–1) and the y window (stamps 2–3).

**Gate item 3,** as pre-registered:
- the median |error| on the 19 U gate points is ≤ 1.55%;
- no point that Stage 0c had within 5% moves outside 5%;
- SUMMA is within 1%.

The regression rows (P ≥ 16, non-U) are reported against the same 5% rule, with 1% for SUMMA.

### Addendum G (2026-09-28): y-dimension and two-module library costs (user-approved third diagnosis round)
Written before the calibration run.

**Reason.**
- Gate item 3 failed (Addendum F, commit 60b3009): U gate median 2.15%. U4 is 1.4–3% low on all 6 of its gate
  points, and there are 2 regressions.
- Every y-dimension op and every two-module teardown cost is modelled with x-dimension, single-module costs from the
  P = 12/40 calibration, plus the Stage 0c constant Q_TD2_INIT = 6. No run has measured them.

**Calibration set G** (train set of this round; P = 24 is not in any gate set):
- One packed traced simfab run on a 24 × 24 grid. Every PE initialises both `<collectives_2d>` modules.
- Row r runs an x-dimension op with configuration r, called from main after both inits. Its callback task calls a
  y-dimension op with configuration c (the PE's column). That callback marks the y-op's completion.
- Configurations: 4 ops × roots {0, 12, 23} × counts {4, 24}, the same list for rows and columns.
- Stamps: ts0 at main entry, ts1 after both inits, ts2 in the x callback, ts3 in the y callback.

**Extraction.** As in Addendum D, per task invocation, attributed per op:
- x-ops (tasks 14/15 plus teardown handlers before the x callback) give `x2.` entries: x-ops with the other module
  initialised.
- y-ops (tasks 16/17 plus handlers after the x callback) give `y.` entries. `y.cfgn` = x-callback length − y-callback
  length.
- P dependence: `x2.`/`y.` value(P) = value(24) + c·(P − 24), where c is the corresponding x-dimension coefficient
  (Addendum E).

**Model.**
- Lookup order:
  - y-ops: `y.` → `x2.` → the x-dimension entry;
  - x-ops whose other module is initialised: `x2.` → the x-dimension entry.
- Prefixed teardown-handler lengths already include the second module, so Q_TD2_INIT is not added to them.
- T2's x-run (y module not initialised) keeps the x-dimension entries plus Q_TD2 = 17.
- Frozen: the Addendum E scalars, the Addendum F kernel constants and launch law, and `profile_m1.txt`.
- A residual fit is allowed only for two new scalars, on the G calibration windows only (per row
  max ts2 − min ts1; per column max ts3 − min ts2):
  - `td2x`: cycles added per teardown event for prefixed entries (default 0);
  - `dcy`: cycles added to y-dimension op calls (default 0).

**Evaluation.**
1. The G model is the final Stage 1 model.
2. Commit its predictions for the gate item 2 sets (collbench and chain are unaffected, since they are single-module;
   coll2d changes) and the gate item 3 suite.
3. Then evaluate once. Report gate items 2 and 3 for the G model, alongside E and F.

No further round is pre-authorised. After this, Stage 1 is closed with the M6 report whatever the outcome.
