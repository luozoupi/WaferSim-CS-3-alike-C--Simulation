# Stage 0 closure (2026-09-26)

**Decision (user, 2026-09-26):** close Stage 0 and start Stage 1. No Stage 0 gate was waived. Stages 0, 0b
and 0c each failed their pre-registered gate, recorded in `REPORT.md`, `REPORT_0b.md` and `REPORT_0c.md`.
Stage 0 is closed because the remaining errors come from mechanisms the roadmap assigns to Stages 1–2, not
because the gate was met.

## Outcome across the three rounds (unseen test kernels each time)
| round | test kernels | within 5% | median \|error\| | main new mechanisms |
|---|---|---:|---:|---|
| 0 | GEMV, SUMMA | – | GEMV −22 to −29% | router multicast, collective primitives from microbenchmarks |
| 0b | T1 GEMM-c2d, T2 topic-11 | 14/16 | 3.1% | launch law (host command queues), colour teardown gates, gather teardown, PE collective engine, chain transitions |
| 0c | U1–U4 (tic/toc GEMV, GEMV-c2d blocks, GEMM-c2d tiles, allreduce-2D) | 15/19 | **1.05%** | second-module teardown cost, stalled-row entry offset, per-P launch law |

## Frozen baseline for later stages
- **The Stage 0c model is the collectives baseline:** git `0b539b6`, flags `-DS0B -DS0C -DS0_GATHER_TD
  -DWSE_GATES -DS0_GATES -DS0_PE -DTWO_MODULES -DP2_CPL=140 -DWSE_LAUNCH_STATE` plus `launch_law2.py`.
- **Its predictions and simfab truths** (`results/s0c_summary.json` and `results/s0b_summary.json`) form
  the Stage 0 regression suite:
  - 19 U-points;
  - T1 and T2 (x and y);
  - GEMV and SUMMA at P = 16/32/64.

  A later stage must not worsen the suite's median |error| (1.05% on the U gate points) by more than 0.5
  points, nor push any point that is currently within 5% beyond 5%.
- **Calibration data remain valid** for all later stages: collbench, chain, coll2d (families B), launch
  probes (families C/C2), idbench and the 2D T2-x bench.

## Carried-forward gaps (named targets)
| gap | evidence | assigned to |
|---|---|---|
| concurrent transfers share PE bandwidth (processor sharing, not exclusive) | simfab traces of 64/128 concurrent broadcasts; U3 2×2×2 −6%; T1 4³ −3.5% | Stage 2 (PE data path: microthreads and DSDs) |
| y-chain deficit after a lagged row-0 launch | T2 chunk 3 y at P = 16, −6.8% | Stage 1 (fabric and runtime tasks) or Stage 2 |
| P = 64 launch propagation through GEMV chains | U1, U2 2×2 and GEMV at P = 64: +4.6% to +5.7% even with measured launch state | Stage 1 (memcpy/command fabric at scale) |
| single-PE copy stalls step up at P = 64 (no mechanism yet) | family C | Stage 1 (memcpy fabric model) |
| gather count = 1 packet artifact; chained ×3 gather over-prediction | microbenchmark validation | Stage 1 (wavelet-level fabric replaces packets) |

Git tag: `stage0-closed`.
