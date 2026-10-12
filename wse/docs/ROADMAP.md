# wsesim: a mechanism-level WSE performance simulator (fork of muchiSim)

*Research plan, 2026-09-24. Owner: luo00466. Fork of PrincetonUniversity/muchiSim @ 9efffecc, branch `wse`.
Evidence base:*
- *the WSE-3 characterization study (`xkernel/studies/wse3-characterization`, simfab and CS-3 silicon);*
- *the muchiSim evaluation (`/mnt/data/luo00466/muchisim_eval/REPORT.md`);*
- *the twin pilot (`muchisim_eval/pilot/PILOT_REPORT.md`).*

## 1. Goal and research questions

Build an open, validated simulator that predicts the performance of CSL programs on WSE-3 (and WSE-2) from
**measured mechanisms** rather than per-kernel fitted knobs. It should be fast enough to reach full-wafer scale,
where simfab takes days per million cycles.

- **RQ1.** Can mechanism-level models predict held-out sizes of real CSL kernels within ±5% of simfab? Can they
  predict silicon within ±10% using a silicon profile? The constants come from targeted microbenchmarks, and
  nothing is fitted to the application under test.
- **RQ2.** Which WSE mechanisms dominate prediction error? Answered by ablation: multicast, switch advance,
  teardown, turns, DSD rates, bank conflicts, async overlap.
- **RQ3.** What changes at wafer scale that small simfab runs cannot show? Examples: collective algorithm choice
  (the three reduce_dp decision flips), west-direction degradation, contention.
- **RQ4 (later).** Architecture what-ifs, with energy, area and cost (muchiSim's models).

**Why this is research and not tuning.** The pilot showed two things:
- Knob-calibrated twins in stock muchiSim are only 1.25× better than simple formulas.
- Their errors trace to specific WSE mechanisms that muchiSim lacks. For GEMV collectives the error was
  −8/−10/−22% at P = 16/32/64. The missing mechanisms are hardware multicast, switch-position-serialized
  gather/scatter, teardown and route reconfiguration.

The hypothesis is that modelling those mechanisms, with constants measured once by microbenchmarks,
generalizes where knobs do not.

## 2. Evidence base

### 2.1 Measured constants
Entries marked `sil` come from CS-3 silicon, `sim` from simfab, and `cmp` from the compiler.
F:NNN refers to lines in `studies/wse3-characterization/FINDINGS.md`.

| mechanism | simfab profile | silicon profile | source |
|---|---|---|---|
| hop latency | 2.000 cyc | 2.000 (W: degrades past 32 hops, 2.9 avg) | F:81-87, F:728-739 |
| link rate | 1.000 cyc/wavelet | 1.125 | F:82, relay 1.001 (F:712) |
| turn | ~33 | ~20 | F:83 |
| contention | – | full serialization (1.3% err) | F:84 |
| send → first wavelet | 7 cyc, then 1/cyc | – | F:1030-1055 |
| store-and-forward relay stage | 16.1 cyc/stage (T = 1.001·N·B + 16.1·N + 16.5) | not run | F:707-720 |
| DSD setup | 15-17 (TSC); 8-13 in suite | 15-17 | F:55-60, F:563-567 |
| DSD rates (elem/cyc) | copy f16 8, f32 4; fma f16 4, f32 0.5 | 4.82 / 2.44 / 2.92 / 0.50 | F:55-67 |
| sync DSD blocks scalar issue | yes (serial) | – | F:1064-1079 |
| core issue | in-order, 1 IPC, 3-stage D→X, dep-FP 2, taken branch 6, back edge 9-10 | – | F:197-241, F:771-789 |
| memory | 49,152 B, 8 banks; 44,976 B usable | bank conflict 1.94× (≤2.86×) | F:23, F:69-75, F:288-300 |
| colours / queues | 24 colours (21-23 memcpy); IQ/OQ 0-7, memcpy IQ0/1, OQ0; 1 rx dir per colour | – | F:24, F:426, F:1386 |
| microthreads | ut_id 0-7; concurrent async ops need distinct ut_ids | – | F:25, F:1384 |
| completion task | fires 3 cyc after last wavelet | – | F:1039, F:1052 |

### 2.2 Unmeasured mechanisms (gaps this project fills; FINDINGS open items)

Each gap is filled by the stage listed.

| gap | filled by |
|---|---|
| collectives (broadcast / scatter / gather / reduce) — no WSE-3 data | Stage 0 |
| multicast fan-out cost (generator exists, no results) | Stage 0/1 |
| switch positions, control wavelets, sentinels, advance | Stage 0/1 |
| teardown and filter cost | Stage 0/1 |
| data-task per-wavelet cost | Stage 2 |
| task-switch cost | Stage 2 |
| async DSD overlap | Stage 2 |
| microthread scaling | Stage 2 |
| backpressure, queue depth, per-port bandwidth | Stage 1 |
| silicon relay | Stage 4 |
| silicon multicast | Stage 4 |
| silicon collectives | Stage 4 |

### 2.3 Known sim-vs-silicon discrepancies
The simulator must expose these as **profile** constants, not bake them in:
- memory-path rates (the sim is 1.37-1.66× optimistic);
- per-wavelet cost;
- turn cost;
- west anisotropy;
- bank conflicts (contradictory evidence: F:74 vs F:547; to settle on silicon);
- long-kernel silicon noise (up to 2×).

## 3. Architecture of the fork

### 3.1 What is kept and what is replaced

| muchiSim component | decision |
|---|---|
| parallel engine (tile threads + router threads, time sync) | **keep, fix determinism**: lock-step reference mode, then prove the parallel mode is equal |
| stats, energy/area/cost models, chiplet/board hierarchy | keep (re-parameterize 7 nm → 5 nm later) |
| packet-switched DOR router, 4 logical queues | **replace**: WSE colour-routed router |
| latency-returning C++ tasks | **replace**: WSE PE model (task scheduler, microthreads, DSD cost model) |
| square power-of-two grids | **replace**: rectangular grids (762×1172, 750×994) |
| app headers (`src/apps`) | keep for legacy apps; new front-end API for WSE programs |

### 3.2 Fabric model (Stage 1)
- **Router state:** per tile × 24 colours. Each colour has a route configuration: one rx direction, a tx set
  over {RAMP, N, S, E, W} (fan-out = multicast), switch positions pos0-3 advanced by control wavelets, ring mode,
  pop mode, a counter filter, and a teardown flag.
- **Wavelets:** 32-bit data plus a colour and a control bit.
- **Links:** one wavelet per `link_cycles` (profile: 1.000 / 1.125). Hop latency 2. Turn penalty (profile).
  West anisotropy (silicon profile).
- **Queuing:** per-colour input buffering with backpressure; depth is a Stage-1 measurement.
- **Correctness:** the compiler's route tables (`cs_readelf --routing/--switching`, xkernel
  `tools/fabric_probe.py`) can be loaded directly, so routes are **imported, not re-specified**.

### 3.3 PE model (Stage 2)
- **Task scheduler:** local tasks and data tasks (bound to input queues on WSE-3), with
  activate / block / unblock semantics.
- **Microthreads:** 8 async engines running fabin, fabout and memory DSD ops concurrently with the main
  thread (concurrency is a Stage-2 measurement).
- **Main-thread cost model:** a DSD op costs setup + ⌈n / rate(op, dtype, profile)⌉ and blocks issue.
  Scalar code is costed per instruction class from FINDINGS §A.
- **Memory:** 48 KiB enforced. Bank model is optional (profile).

### 3.4 Program front-ends
- **F1 (Stages 0-2):** hand-written twins in a CSL-like C++ API (`colour`, `route`, `dsd_send`, `dsd_recv`,
  `task`, `activate`). This is the *reference* front-end for validation.
- **F2 (Stage 3):** trace-driven generation. Run the kernel on simfab at small scale with traces and extract:
  - per-PE task timelines (dispatch/pipe records);
  - wavelet flows per colour (wavelet records plus imported routes);
  - costs parameterized by size.

  These are then replayed at scale. xkernel already has the parsers (`wse3study/trace.py CtfTraceReader`,
  `tools/decode_trace.py`).
- **F3 (stretch):** from compiler IR / ELF (`xkernel tools/cslc_ir.py`, `csdisasm`) without running simfab.

### 3.5 Profiles
- `simfab-2.10`: reproduce simfab.
- `cs3-silicon`: reproduce CS-3.
- `wse2` (later).

Every constant lives in one profile file with its FINDINGS reference.

## 4. Validation methodology
- **Ground-truth tiers.**
  - simfab (deterministic to ±0.8%; cheap up to about 64²).
  - CS-3 silicon via the ALCF appliance (`xkernel/code_translation/hw_vs_sim.py`; `HW_VS_SIM` geomean 1.03).
- **Pre-registration.** Every stage fixes its train and hold-out sizes, predictors and gate *before* running,
  as in the pilot.
- **Baselines.** Every result is reported against:
  - a closed form fitted on the same training runs;
  - xkernel's WSE-3 runtime model (HPDC form, 27% median);
  - the previous stage of this simulator.
- **Determinism.** Every reported simulator number is from the deterministic mode. The parallel mode is
  accepted only once it matches the deterministic mode to 0.1% on the regression suite.
- **Regression suite.** Microbenchmark curves (fabric, collectives, single-PE) plus kernel predictions,
  re-run on every change.

## 5. Stages and gates

| stage | scope | gate (pre-registered) | effort |
|---|---|---|---|
| **0** | collectives mechanisms: SDK microbenchmarks, multicast in router, collective primitives from measured constants, predict GEMV and SUMMA with no app-level fitting | GEMV P = 16/32/64 within ±5%, and not worse than the analytic composition of the same microbenchmarks; SUMMA P = 16-64 within ±1% | ~1 week |
| 1 | WSE fabric core, deterministic engine, rectangular grids, route import | fabric microbench curves (hop/wavelet/turn/relay/contention/multicast/switch) within ±3% of simfab; collectives emerge from routing config (not primitives) and still pass the Stage-0 gate | 3-4 weeks |
| 2 | PE model (tasks, microthreads, DSD costs, memory) | single-PE suite within ±5%; 1-PE xkernel kernels within ±10% | 3-4 weeks |
| 3 | trace-driven front-end F2 | xkernel suite at held-out sizes: median ≤5%, better than the runtime model and closed forms | 4-8 weeks |
| 4 | scale and silicon: full-wafer runs, `cs3-silicon` profile validated on HW_VS_SIM kernels plus silicon microbenchmarks | silicon median ≤10% | ~4 weeks |
| 5 | stretch: IR front-end, architecture DSE, energy | – | – |

Failing a gate stops the project or re-scopes it; it is never waived.

## 6. Stage 0: detailed plan

**Hypothesis.** The GEMV twin's error comes from unmodelled collective mechanisms. Modelling them, with constants
measured independently on collective microbenchmarks, predicts GEMV (and SUMMA) at held-out sizes without any
fitting on those kernels.

1. **Microbenchmark campaign (simfab)**, `wse/bench/collbench`:
   - One `<collectives_2d>` op on a line of P PEs, with device-internal stamps: entry, after init, callback.
   - Matrix: op ∈ {broadcast, scatter, gather, reduce_fadds} × P ∈ {4, 8, 16, 32, 64} × COUNT ∈ {1, 8, 64}
     × root ∈ {first, last} × dim ∈ {x, spot y}, plus chained REPS = 3 to measure per-op transition cost.
   - Train P ≤ 16; hold-out P ∈ {32, 64}.
   - This fills FINDINGS open items (collectives, multicast, switch advance, teardown) and is a result in itself.
2. **Primitive models.** A physically structured latency law per op (set-up, per-word, per-hop, per-PE
   switch/handoff, teardown), fitted on train and checked on the hold-out microbenchmarks.
3. **Router: native multicast.** The head flit carries a flag that makes every router on the path also deliver
   the message to its core (drop-and-continue, i.e. router fan-out, not PE forwarding). Each direction gets its
   own channel, so a mid-line root streams both ways at once.
4. **Collective library in the fork.**
   - broadcast = native multicast + teardown;
   - scatter/gather = switch-advance chains;
   - reduce = pipelined fadds chain.

   All constants come from step 2. Runs use the deterministic ≤2-thread protocol until Stage 1 fixes the engine.
5. **Application prediction.** GEMV and SUMMA at P = 2…64 use only step-2 constants plus on-device compute
   costs measured by per-phase stamps at the smallest size. Nothing is fitted to the application.
6. **Controls:**
   - (A) analytic composition: the sum of step-2 op latencies along the critical path, with no simulator;
   - (B) the pilot twin (knob-fitted);
   - (C) the pre-registered closed form.
7. **Gate and report**, in `wse/stage0/REPORT.md`.

### 6.1 Stage 0 outcome (2026-09-24): gate FAILED; proposed re-scope
- **Result.** GEMV S error −22 / −22 / −29% (P = 16/32/64), no better than control A. SUMMA −1.12% against a
  1% bar. The primitives themselves validate within ±2% up to P = 64, on 2D grids and with unseen root
  positions.
- **Post-hoc causes, each isolated by an independent microbenchmark:**
  1. Host-sequence-induced launch skew. Row 0 enters `main` 362–2,208 cycles late after single-PE h2d
     copies, which is hidden from local TSC stamps but included in `cycles_send`. Adding it brings GEMV to
     −1.8 / −0.3 / +1.0%.
  2. Concurrent x+y collectives nearly serialize, because the PE ramp is shared across colours. The twin
     under-serializes by up to 137 cycles, against SUMMA's 144 cycles per step.
  3. Chaining overlap between back-to-back ops, which is smaller.
- **Proposed re-scope (Stage 0b, before Stage 1):**
  - Add a launch model (per-row offsets as a function of the host sequence, from a launch-probe family), a
    shared-ramp core port in the router, and a chaining transition cost.
  - Calibrate these on microbenchmarks only: `launchprobe`, `coll2d` with P ≤ 8, and mixed-op chains.
  - Pre-register a new gate on **unseen** kernels. GEMV and SUMMA are now seen, so they may only be reported
    as regression checks. Candidates: xkernel collectives kernels with other host sequences, and GEMM
    variants with different tile sizes.

## 7. Risks and mitigations

| risk | mitigation |
|---|---|
| muchiSim engine nondeterminism (12-23% at ≥8 threads) | deterministic protocol now; lock-step mode in Stage 1 |
| CSL semantics breadth (teardown, filters, switch positions) | coverage driven by a fixed kernel list; routes imported from the compiler |
| mechanisms still unmeasured on silicon | silicon campaigns in Stage 4, via the existing `wse3study` appliance path (τ = 2 re-sync) |
| a simulator adds nothing over analytic composition | every stage reports control (A); a simulator is justified only where interactions (contention, skew, overlap) matter |
| licence (muchiSim is academic-only) | the fork stays a separate repo under muchiSim's licence, with attribution; nothing is vendored into xkernel (BSD-3) |
| effort | stage gates; Stage 3 is the first point of broad value |

## 8. Expected outputs
- WSE-3 collectives and switch/teardown/multicast measurements (Stage 0-1): new FINDINGS sections.
- A validated simulator with simfab and silicon profiles, and a regression suite.
- A trace-driven front-end, so any CSL kernel can be simulated from a small simfab run.
- Full-wafer case studies:
  - collective algorithm choice at scale;
  - scale oracle for the xkernel agent;
  - architecture what-ifs.
- Paper: "a mechanism-level, silicon-validated performance simulator for wafer-scale engines" (ISPASS / IISWC / SC workshop).

### 6.2 Stage 0b outcome (2026-09-25): gate FAILED narrowly (`wse/stage0/REPORT_0b.md`)
- Results on unseen kernels:
  - 14 of 16 test points within 5%; S0b median 3.1%, against 4.6% for A0b and 5.2% for the Stage 0 model;
  - SUMMA regression −0.40%;
  - GEMV regression −5.3% at P = 64, a launch-law limitation declared before the test.
- Remaining gaps, each needing its own microbenchmark family before the next gated stage:
  1. a constant ~80-cycle fixed cost on T2's x path;
  2. under-serialization of concurrent broadcasts at small counts;
  3. single-PE copy stalls at P ≥ 64.

### 6.3 Stage 0c outcome (2026-09-26): gate FAILED narrowly (`wse/stage0/REPORT_0c.md`)
- Results on new kernels:
  - 15 of 19 test points within 5%; S0c median 1.05%, against 2.10% for the S0b model and 3.75% for A0c;
  - regression all within bars except T2 chunk 3 y at P = 16 (−6.8%, disclosed before the test).
- Mechanisms added:
  - second-module teardown cost (17 uninitialised / 6 initialised per teardown);
  - local-entry offset of stalled rows;
  - per-P launch law with large-P interaction terms.
- Remaining gaps, which are structural:
  1. bandwidth-shared concurrent transfers (count-4 concurrency, −6%);
  2. the y chain after a lagged row-0 launch;
  3. P = 64 launch propagation through GEMV chains (+5%).
- **Proposal:** close Stage 0 with the Stage 0c model as the collectives baseline, and move the three gaps
  into Stage 1 (fabric) and Stage 2 (PE data path: processor-sharing DSDs).

### 6.4 Stage 1 start (2026-09-26): architecture amendment
Stage 0 is closed (tag `stage0-closed`). The Stage 1 fabric is built as a **new deterministic wavelet-level
engine inside the fork** (`src/wse/`), not a retrofit of muchiSim's router and engine; rationale in
`wse/stage1/PLAN.md`. Pre-registration: `wse/stage1/PREREGISTRATION.md`.
