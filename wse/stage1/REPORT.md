# Stage 1 report: WSE fabric core (M1–M6), 2026-09-28

**Verdict: the Stage 1 gate FAILED.** Items 2 (collectives) and 4 (determinism) passed. Item 1 (fabric) failed
narrowly and item 3 (Stage 0 regression suite) failed. No item was waived. Stage 1 is closed here as pre-registered in
Addendum G. Its engine, calibrations and findings carry into Stage 2.

| gate item (PREREGISTRATION.md) | final model | result |
|---|---|---|
| 1. Fabric: every hold-out case within ±3% | profile_m1 (Addendum C) | **FAIL**: 203/205 within ±3%, median 0.00% |
| 2. Collectives from routing configuration | Addendum G model | **PASS**: collbench median 0.41% / max 2.06%, chain 1.00%, coll2d single-direction 1.01% |
| 3. Stage 0 regression suite | Addendum G model | **FAIL**: U gate median 2.01% (≤ 1.55% required); 53/55 within 5% (Stage 0c: 50/55); 2 regressions; SUMMA within 1% |
| 4. Determinism | all gate runs | **PASS**: 3 repeated runs byte-identical |

## 1. What was built
- **`src/wse/fabric.h`: wavelet-level fabric.**
  - 24 colours per tile, each with one input FIFO and per-colour credits.
  - Switch positions pos0–3 with separate input and output positions, ring mode, and the pop modes.
  - Control wavelets with two commands and the no_ce bit.
  - Teardown mode, counter filters, multicast, and credit-aware round-robin link arbitration.
  - Deterministic and single-threaded; rectangular grids.
- **`src/wse/pe.h`: PE model F1.**
  - Non-preemptive task scheduler (activate, block, unblock) with async DSD operations (fabout, fabin, streaming fadds).
  - Teardown handlers raised by router events, and TSC stamps.
  - An optional send output queue (Addendum D).
- **`src/wse/c2d.h`: `<collectives_2d>` ported function by function from `pe.csl`.**
  - Covers configure, the FSM passes, teardown initiation (including gather's guard and pop), the reduce with two
    alternating colours, the teardown handlers, and the C_LOCK protocol.
  - A functional test moves the right data in 720/720 configurations (`tests/test_c2d.cpp`).
  - CPU costs come from a measured cost table (Addenda D, E and G).
- **Harnesses:**
  - `fabsim2` for the M1 probes;
  - `c2dsim` for collbench, chain and coll2d;
  - `kersim` for GEMV/U1/U2, SUMMA/U3/T1, T2 and U4, plus the calibration replay.
- **Measurement tooling:**
  - a shelf-packed traced sweep (`wse/bench/fabric/packed.py`), with 333 cases in 8 simfab runs;
  - a CTF reader that decodes every trace stream;
  - instruction-trace task segmentation (`wse/bench/c2dcal*`).

## 2. M1: fabric microbenchmarks (gate item 1)
- **Data.**
  - 272 base cases (straight, turn, multicast, contention, relay, backpressure) and 61 Addendum A cases (switch
    advance, rx switch, gather chain, ring, teardown). All ran traced and all are complete.
  - Packed and unpacked runs agree in relative time for every wavelet, except where runtime traffic differs by
    placement (below).
- **Method.** Constants were fitted on train rows only. Blind hold-out predictions were committed before any hold-out
  row was compared (commit cb77add).
- **Hold-out result.** Every base family was exact on hold-out data (median and max 0.00%): straight 52, turn 24,
  multicast 40, relay 39, contention 16 and backpressure 18 metrics. The two misses:
  - `sachain_N8_B1`: 25 cycles against 26 (−3.85%, a single cycle);
  - `saring_B64`: +3.39%. This is a probe-program code-variant effect, flagged in Addendum C before scoring.

**Fabric semantics established from the traces** (each re-checked by the unit and functional tests):
1. **Acceptance.** A router accepts a colour's wavelet only on the input its current switch position selects, and not
   while the colour is in teardown; otherwise the wavelet waits upstream. Wavelets already queued drain in order.
2. **Two-sided commands.** Control commands act on the input side when the wavelet is accepted (ADVANCE and RESET
   move the input position; TEARDOWN closes the input). They act on the output side when it is forwarded (output
   position; the colour enters teardown and raises the PE handler). This matches WSE's separate input and output
   switch positions, and it is what makes collectives_2d's gather teardown sequence work.
3. **`.advance_switch`.** It advances the sender's own router when the last wavelet enters from the ramp.
4. **Turns cost nothing extra.** No turn penalty was needed; turns are exact at 2 cycles per hop.
5. **Runtime traffic.** The memcpy runtime's launch-command wavelets (colours 21/22) stream eastward along rows and
   occupy links:
   - every 1-cycle receive bubble on eastbound data sits one cycle after one of them (47/47, 242/242, 30/30, 105/105);
   - westbound, northbound and southbound data show none.

   The model replays each run's measured runtime traffic as an input condition.

**Probe flaws (disclosed):**
- The backpressure receiver's delay loop was removed by the compiler: the arm stamp is 237 for every D. That family
  therefore measures straight transfers, and router buffer depth is still unmeasured.
- The `pe_ctl.csl` start delay and its data-to-control transition vary by compiled variant (79–89 cycles).

## 3. M5: collectives from routing configuration (gate item 2)
The port was evaluated on collbench (144 configurations), chain (92) and coll2d (207). Each round's constants were
pre-registered, its predictions committed, and the evaluation run once.

| round (addendum) | constant sources | collbench median / max | chain | coll2d single | coll2d concurrent* | item 2 |
|---|---|---|---|---|---|---|
| B | M1 profile + Stage 0c scalars (C_CFG, A_ACT, T_TDD) | 25.6% / 51.7% | 30.0% | 10.0% | 13.9% | FAIL |
| D | per-task costs from P = 12 traced calibration | 0.52% / 6.72% | 1.04% | 0.28% | 2.70% | FAIL (max) |
| E | + P = 40 calibration (costs linear in count and P) | **0.41% / 2.06%** | **1.00%** | **0.28%** | 2.70% | **PASS** |
| G (final) | + two-module and y-dimension entries (P = 24, 2D) | 0.41% / 2.06% | 1.00% | 1.01% | 2.08% | **PASS** |

\*concurrent x+y was reported, not gated.

**Library-cost findings** (instruction traces, `wse/bench/c2dcal*`):
- **Per-task costs.**
  - The costs differ by op kind, PE role (root, end, before or after the root, the gather guard) and even PE parity
    (reduce).
  - The op call costs 105 cycles (bcast), 200–220 (scatter, whose filter setup computes a software modulo), 146–196
    (gather) and 142–154 (reduce).
  - The teardown handler (task 29) takes 49 cycles for bcast, 57 for scatter and gather, and 50–77 for reduce.
- **Send completion.** A send DSD completes once its remaining words fit an 8-deep output queue, not when the data
  are injected. The first wavelet reaches the router 7 cycles after issue.
- **Reduce forwarding.** Each reduce stage forwards 7–8 cycles after arrival, at 1 word/cycle. A single calibration P
  cannot separate this per-stage latency from fixed costs (Addendum D's failure); a second P fixed it (Addendum E).
- **Two modules initialised.** The teardown handler grows from 49 to 66 cycles (+17 per event, against the Stage 0c
  constant of 6).
- **Init depends on the compiled program's op mix.** Measured init (ts1 − ts0) with two modules is 38 cycles for
  bcast/bcast, 146 for scatter/scatter, 189 for scatter/gather-last and 236 for reduce-last/reduce-last. Stage 0's
  "program-level init rule" is therefore a real effect of the compiled code.

## 4. Gate item 3: the Stage 0 regression suite
The kernels were ported from their CSL task graphs (Addendum F). Kernel constants (init rule, compute, host tic/toc,
T2's run-to-run latency) and the launch law v2 are exactly Stage 0c's, so only the fabric and collectives model changed.

| | Stage 0c | Stage 1, Addendum F (E model) | Stage 1, Addendum G (final) |
|---|---|---|---|
| U gate points (19), median \|error\| | 1.05% | 2.15% | 2.01% |
| rows within 5% (of 55) | 50 | 53 | 53 |
| median over all 55 rows | 1.28% | 1.29% | 1.42% |
| SUMMA (P = 16/32/64) | −0.36% | −0.1 to −0.2% | −0.2 to −0.3% |
| points moved outside 5% | – | T2_c16_y P64 (+5.1%), U2_2x2 P4 (−5.6%) | same (+5.12%, −5.27%) |

- **Stage 1 fixes 4 of Stage 0c's 5 misses:**
  - U3_2x2x2 at P = 16/32 went from −5.7/−6.1% to +0.3/+0.05% under F (−2.3/−2.6% under G);
  - U1 at P = 64: 5.7% → 4.2%;
  - U2_2x2 at P = 64: 5.1% → 3.1%;
  - T2_c3_y at P = 16: −6.8% → −4.1%.
- **What is still wrong.**
  - U4, T1 and U3 are now 1–3.5% low.
  - The G calibration reproduces its own windows to 0.31% mean (1.08% max), yet it does not transfer to the
    multi-op kernels.
  - Post-hoc check: correcting Stage 0c's init constants to the measured values (38 against 50 for SUMMA/U3/T1; 236
    against 248 for U4) would shorten the predicted times by 12 cycles and worsen the under-prediction, so init is
    not the cause.

The evidence points to costs that depend on the whole compiled program's op mix. Init shows the effect most clearly:
the same `mpi.init()` costs 38–236 cycles depending on which ops the ELF contains. Per-op cost tables measured on
single-op or two-op programs miss this. Concurrent ops on one PE (SUMMA's step, coll2d concurrent, 2.1%) and runtime
traffic during the launch window (there are no traces of those runs to replay) are secondary candidates.

## 5. Integrity notes
- **Pre-registration.** Addenda A–G were each committed before the data or evaluation they govern. Each gate
  evaluation ran once on predictions committed beforehand. The thresholds are the ones pre-registered on 2026-09-26.
- **Disclosures.**
  - Two straight hold-out rows were displayed during a progress check before M1's freeze (Addendum A).
  - The first packed pass decoded only CTF `stream0`. It was discarded and re-run (Addendum C).
  - The Addendum G calibration replay uses each PE's measured init and trace launch time as inputs.
  - Before any G evaluation, `dcy` was restricted to two-module y-ops. This matches Addendum G's statement that
    single-module sets are unaffected; collbench and chain were verified unchanged.
- **Stage 0 exposure found in Stage 1.** Stage 0's `bc_col16` trace had two CTF streams and was analysed from the
  first only.

## 6. Carried into Stage 2
1. **Program-dependent CPU costs.** Library code timing depends on the compiled program's op mix (init: 38–236
   cycles). A code-level PE model, or ELF-aware costs from traced kernels, is needed for gate item 3's kind of
   kernel.
2. **Concurrent ops on one PE.** coll2d concurrent is 2.1% median, 7.1% max. This is the processor-sharing gap
   carried from Stage 0.
3. **Runtime (memcpy) traffic in kernels without traces.** This needs a generative launch-command traffic model, not
   replay.
4. **Unmeasured router buffer depth.** A corrected backpressure probe is needed.
5. **Host launch law at scale.** T2_c16_y at P = 64 is +5.1%, and was +4.3% in Stage 0c.
6. **Performance at wafer scale.** The engine is single-threaded; Stage 4's partitioned mode.

## 7. Artefacts
- Pre-registration: `wse/stage1/PREREGISTRATION.md`, Addenda A–G.
- Profiles:
  - `profile_m1.txt` (fabric);
  - `profile_m5e.txt`, `profile_m5g.txt` (collectives and PE);
  - cost tables `results/c2d_costs*.txt`.
- Predictions and gates:
  - `results/fabric_pred_holdout.json` and `gate_m1.txt`;
  - `results/m5*_pred.json` and `gate_m5*.txt`/`.json`;
  - `results/m5f_pred.json`, `m5g3_pred.json`, `gate_m5f.txt`, `gate_m5g3.txt`.
- Data: `results/fabric_m1*.jsonl.gz`, `c2dcal*.json.gz` (calibration traces extracted).
- Git: local branch `wse`, tag `stage1-closed`.
