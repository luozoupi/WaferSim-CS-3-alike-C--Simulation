# Stage 0 pre-registration (2026-09-24, written before any Stage-0 measurement)

**Hypothesis.** The pilot twin's GEMV error (−8/−10/−22% at P = 16/32/64) comes from unmodelled `<collectives_2d>`
mechanisms: hardware multicast, switch-advance serialization, teardown and route reconfiguration. If they are
modelled in the fork with constants measured on collective microbenchmarks, GEMV and SUMMA can be predicted at
every size with **no fitting on GEMV or SUMMA**.

## Data rules
- **Calibration data:** the collectives microbenchmarks only (`wse/bench/collbench`, simfab WSE-3). All of it
  (every P) may be used to shape and fit the per-op latency laws and the simulator's collective constants.
  Microbenchmark P ∈ {32, 64} are also reported as a secondary diagnostic of the laws.
- **Compute cost:** the local compute of each kernel is measured on-device with per-phase stamps at the smallest
  size, P = 2. It is size-independent. As a sensitivity check it is also estimated from FINDINGS DSD rates.
- **Test data:** GEMV collectives_2d (8×4 block per PE) and SUMMA GEMM (14³ tile per PE) `cycles_send` at
  P = 2…64. These are already measured in the pilot (`muchisim_eval/pilot/results/sdk_pilot.jsonl`). They are
  **never used for fitting** and are only compared at the end.
- **Simulator protocol:** deterministic runs only (2 host threads; 4 for SUMMA P = 64). A parallel run is reported
  only if it matches.

## Predictors compared on GEMV/SUMMA

| id | predictor |
|---|---|
| S | fork simulator: native multicast plus collective primitives with microbenchmark constants, plus measured compute |
| A | analytic composition: sum of the microbenchmark latency laws along the kernel's collective sequence, plus measured compute (no simulator) |
| B | pilot twin (knob-fitted on P ≤ 8), for reference |
| C | pilot pre-registered closed form, for reference |

## Gate
- **Pass** if and only if S has |error| ≤ 5% on GEMV at every P ∈ {16, 32, 64}, **and** S's GEMV median |error|
  is ≤ A's, **and** S has |error| ≤ 1% on SUMMA at every P ∈ {16, 32, 64}.
- If S passes only because of A-level composition (S ≈ A), the report states that the simulator adds nothing yet
  for sequential collective chains.
