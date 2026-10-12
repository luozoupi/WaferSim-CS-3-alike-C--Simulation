# Stage 0b report: modelling the collectives stack on unseen kernels (2026-09-25)

**Pre-registered verdict: FAIL (narrow).**
- 14 of 16 test points are within 5%. The two misses are T2 with chunk 3 at P = 16: x window −6.2%, y window
  −7.2%.
- S0b's median |error| is 3.1%, against 4.6% for the analytic control A0b.
- SUMMA regression now passes: −0.40% at every size (Stage 0: −1.12%).
- GEMV regression misses at P = 64 (−5.3%). Addendum A predicted this limitation before the test.

Order of work, all dated in git:
1. pre-registration (`70387a9`);
2. model freeze and addendum A (`0fada00`);
3. blind predictions (`5fa25fc`);
4. simfab ground truth and gate (`966b1dc`).

![Stage 0b errors](results/fig_s0b.png)

## Test results (signed error vs simfab)

| series | P | simfab | S0b | S0b-probe | S0 (Stage 0) | A0b |
|---|---:|---:|---:|---:|---:|---:|
| T1 8³ | 16 | 56,944 | **−1.3%** | −1.3% | −0.4% | +0.2% |
| T1 8³ | 32 | 113,970 | **−1.5%** | −1.4% | −0.5% | +2.7% |
| T1 4³ | 16 | 19,172 | **−3.7%** | −3.7% | +1.4% | +2.4% |
| T1 4³ | 32 | 38,452 | **−4.0%** | −4.0% | +1.0% | +9.7% |
| T2 c3 x | 16 / 32 / 64 | 1,404 / 1,711 / 2,319 | **−6.2** / −4.8 / −2.9% | −4.8 / −3.6 / −2.0% | −6.8 / −5.3 / −3.2% | −9.3 / −7.5 / −5.2% |
| T2 c3 y | 16 / 32 / 64 | 2,910 / 5,974 / 17,088 | **−7.2** / −2.4 / −0.5% | −5.6 / −4.1 / −1.0% | −58 / −75 / −88% | −11.9 / −7.4 / −4.2% |
| T2 c16 x | 16 / 32 / 64 | 1,925 / 2,751 / 4,399 | −4.6 / −3.0 / −1.5% | −3.5 / −2.3 / −1.1% | −5.0 / −3.3 / −1.7% | −6.5 / −4.2 / −2.2% |
| T2 c16 y | 16 / 32 / 64 | 6,897 / 20,364 / 72,414 | −3.2 / +2.6 / +4.3% | −4.2 / −1.9 / −0.8% | −77 / −89 / −95% | −4.9 / +1.2 / +3.5% |
| GEMV (regr.) | 16 / 32 / 64 | 4,209 / 4,792 / 6,676 | −0.9 / +2.0 / **−5.3%** | – | −22 / −22 / −29% | −0.5 / +3.3 / −3.0% |
| SUMMA (regr.) | 16 / 32 / 64 | 205,306 / 410,630 / 821,255 | −0.40 / −0.40 / −0.40% | – | −1.12% | +0.2 / +0.9 / +2.3% |

Median |error| over the 16 gate points:
- S0b: 3.1%;
- S0b-probe (launch state measured rather than predicted): 2.9%;
- S0 (Stage 0 model): 5.2%;
- A0b: 4.6%.

## What changed since Stage 0, and what it bought
Each mechanism comes from the SDK 2.10 library source (`collectives_2d`, `memcpy`) or from simfab traces, and
was calibrated only on microbenchmark families.

1. **Launch state from host command queues.** Each row has its own command fan, and a copy-mode h2d stalls
   only the rows it covers (`launch_law.py`).
   - This is what makes T2's y window predictable at all: row 0 starts up to 72k cycles late at P = 64, and
     the Stage 0 model misses by −35% to −95%.
   - It also fixes GEMV, from −22–29% to within ±2% up to P = 32.
2. **Colour teardown mode** (router gates), **gather switch advance** and **gather teardowns**. Together
   these make op chains exact where Stage 0 was only approximate (gather→gather 920 vs 920 cycles).
3. **PE collective engine.**
   - Configuration and FSM activation split out from the fixed cost (trace).
   - One data engine shared per PE.
   - Serialized completions for overlapping ops (coll2d).

   Concurrent x+y broadcasts went from −7% to −15% down to a median of 1–2%. SUMMA went from −1.12% to −0.40%.
4. **Chain transition costs** (chain family, excluding T2's pairs) and the **program-level init rule**.

## Why it still failed (post-hoc, labelled; no refit on test data)
- **T2 x windows share a near-constant absolute offset.** Every predictor (S0b, S0b-probe, S0, A0b) is short
  by 66–94 cycles at every P. This is a missing fixed cost on T2's x path, not a scaling error. Candidates:
  - the init of a module instantiated with custom queue and DSR ids;
  - the activation path of `f_run_x` → `task_x`.

  At P = 16 this offset alone is −6%. Per-phase stamps in T2 would settle it.
- **T2 y windows at small P** lie below the launch-lag regime and inherit a similar small-P fixed-cost
  deficit. At large P they track the launch law, whose error is ±5% on row copies.
- **T1 with 4³ tiles drifts from −2.8% to −4.0%** (about −48 cycles per step at P = 32). Concurrent
  broadcasts are still slightly under-serialized at count 16. This is consistent with the coll2d
  validation (small counts −4% to −9%).
- **GEMV at P = 64** misses because single-PE-copy stalls roughly double at P = 64, which was known and
  declared before the test (addendum A).

## Assessment
- The research direction holds up. A mechanistic model of the software and runtime stack (launch queues,
  colour teardown, PE engine) predicts unseen collective kernels to a 3.1% median. The Stage 0 model scored
  5.2%, and fails badly wherever host launch state matters.
- The misses are small, attributable, and each points to a measurable mechanism. That is the right regime
  for Stage 1 (fabric and PE model).
- Before a further gated stage, the three gaps above should get their own microbenchmark families:
  1. T2-like x-path fixed cost, measured through module init with custom ids and RPC-activated tasks;
  2. concurrency at small counts;
  3. single-PE copy stalls at P ≥ 32.

## Reproduce
- `launch_law.py fit`
- `s0_calibrate.py calib|validate` with `S0_EXTRA="-DS0B -DS0_GATHER_TD -DWSE_GATES -DS0_GATES -DS0_PE"`
- `s0b_coll2d.py`, `s0b_chain.py`, `s0b_trans.py`
- `s0b_predict.py twin S0b|S0|S0b-probe` and `s0b_predict.py analytic`
- `s0b_truth.py`, then `s0b_gate.py`

Data are in `results/` (`s0b_*`, `launch4.jsonl`, `coll2d.jsonl`, `chain.jsonl`, `t1_compute.json`).
