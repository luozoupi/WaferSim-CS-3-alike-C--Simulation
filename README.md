# WaferSim: a CS-3-like wafer-scale simulator in C++

WaferSim models the Cerebras WSE-3 (CS-3) at **wavelet granularity**. It has three layers:
- a deterministic router and fabric model;
- a task-level processing-element (PE) model;
- a behavioural model of the SDK's `<collectives_2d>` library.

Every constant comes from traces of the Cerebras SDK 2.10 fabric simulator (*simfab*), which serves as ground truth.
The work is organised in pre-registered stages with gates, train/hold-out splits and predictions committed before
evaluation.

**Status (Stage 1, closed 2026-09-28):**

| gate item | result |
|---|---|
| 1. Fabric microbenchmarks (205 hold-out metrics) | 203/205 within ±3% of simfab, median 0.00%. FAIL narrowly. |
| 2. Collectives replays (collbench 144, chain 92, coll2d 207) | median 0.41% / 1.00% / 1.01%. PASS. |
| 3. Kernel regression suite (GEMV, SUMMA, T1, T2, U1–U4; 55 rows) | median 1.42%, 53/55 within 5%; U gate points 2.01% median. FAIL. |
| 4. Determinism | byte-identical repeats. PASS. |

See [`wse/stage1/REPORT.md`](wse/stage1/REPORT.md) for the full results and findings.

## What is modelled
- **Fabric** ([`src/wse/fabric.h`](src/wse/fabric.h)):
  - 24 colours per tile, each with one input FIFO and per-colour credits;
  - acceptance only on the input the current switch position selects;
  - switch positions 0–3, with separate input and output positions, ring and pop modes;
  - control wavelets: two commands with the no_ce bit, acting on the input side at acceptance and on the output side
    at forwarding;
  - teardown mode, counter filters and multicast;
  - credit-aware round-robin link arbitration; 2 cycles per hop and 1 wavelet per cycle per link.
- **PE** ([`src/wse/pe.h`](src/wse/pe.h)):
  - a non-preemptive task scheduler (activate, block, unblock);
  - async fabout/fabin DSD streams and streaming fadds;
  - an 8-deep send output queue, teardown handlers and TSC stamps.
- **Collectives** ([`src/wse/c2d.h`](src/wse/c2d.h)):
  - an independent C++ behavioural model of `<collectives_2d>` (broadcast, scatter, gather, reduce): configure,
    FSM passes, teardown protocol, C_LOCK, two-colour reduce;
  - task costs from instruction-trace calibration (`wse/stage1/results/c2d_costs*.txt`).
- **Not modelled yet:** instructions. The PE does not execute CSL, LLVM IR or machine code. Library timing that
  depends on the compiled program is therefore approximated, which is the main Stage 2 target.

## Layout
```
src/wse/                  engine headers (fabric, PE, collectives)
wse/stage1/               harnesses, analysis, profiles, results, PLAN / PREREGISTRATION / REPORT
  fabsim2.cpp             M1 fabric-probe harness
  c2dsim.cpp              collbench / chain / coll2d replays
  kersim.cpp              regression kernels (GEMV/U1/U2, SUMMA/U3/T1, T2, U4) and calibration replays
  compare2.py, fit_*.py, predict_*.py, gate_*.py     comparison, train-only fits, blind predictions, gates
  profile_m1.txt, profile_m5{,e,g}.txt               frozen profiles (fabric; collectives/PE per addendum)
  tests/                  fabric unit tests; 720-configuration collectives functional test
  results/                gate outputs, predictions, cost tables, compressed simfab data
wse/bench/fabric/         CSL probes for the M1 fabric families (generator, packed traced sweep)
wse/bench/c2dcal*/        traced calibration kernels for the library cost tables (P = 12, 40, and 24 in 2D)
wse/bench/{collbench,chainbench,coll2d,launch2d}/     CSL benches that produced the collectives ground truth
wse/bench/test/           regression-suite kernels (CSL), some adapted from Cerebras SDK examples (see NOTICE)
wse/stage0/               Stage 0 reports, launch law v2, ground-truth tables used by Stage 1
wse/docs/ROADMAP.md       staged research plan
docs/DEV_HISTORY.md       commit log of the private development fork (pre-registration timeline)
```

## Build and reproduce (no SDK needed)
```bash
cd wse/stage1
g++ -O2 -std=c++17 -o fabsim2 fabsim2.cpp
g++ -O2 -std=c++17 -o c2dsim  c2dsim.cpp
g++ -O2 -std=c++17 -o kersim  kersim.cpp
g++ -O2 -std=c++17 -o /tmp/tf tests/test_fabric.cpp && /tmp/tf
g++ -O2 -std=c++17 -o /tmp/tc tests/test_c2d.cpp   && /tmp/tc

# the scripts read uncompressed copies of the M1 datasets
gunzip -k results/fabric_m1*.jsonl.gz

python3 compare2.py --role train $(cat profile_m1.txt)    # gate item 1, train rows
python3 gate_m1.py                                        # gate item 1, committed hold-out predictions
PRED=results/m5g_pred.json  GOUT=/tmp/g2.json python3 gate_m5.py    # gate item 2 (final model)
PRED=results/m5g3_pred.json GOUT=/tmp/g3.json python3 gate_m5f.py   # gate item 3 (final model)
PROFILE=profile_m5g.txt OUT=/tmp/m5g.json python3 predict_m5.py     # regenerate predictions
```
All engines are single-threaded and deterministic.

## Ground truth (needs the Cerebras SDK)
- The probe and calibration benches under `wse/bench/` build with `cslc` and run on simfab (SDK 2.10.1, `--arch=wse3`).
- Their drivers contain absolute paths from the development machine: the SDK install and a CTF trace reader from a
  separate WSE-3 characterisation study (`wse3study.trace.CtfTraceReader`). Adapt these before use.
- SDK jobs were serialised with `flock` on one lock file, because concurrent container runs can hang.
- simfab can split a trace across several CTF streams (`global_simdata.json` → `traceFiles`). Decode all of them.

## Provenance and licensing
- **Cerebras-derived kernels.** The files listed in [`NOTICE`](NOTICE) are adapted from Cerebras SDK examples
  (Apache-2.0) and keep their headers.
- **No Cerebras SDK library sources are included.** `c2d.h` is an independent behavioural model written against the
  documented library behaviour and simfab traces.
- **muchiSim.** Stage 0 of this project used a fork of Princeton's
  [muchiSim](https://github.com/PrincetonUniversity/muchiSim) (Clear BSD). The Stage 1 engine in this repository is
  separate code and does not include muchiSim.
- **No licence yet** for the remaining code; it has not been chosen.
