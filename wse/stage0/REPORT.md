# Stage 0 report: can microbenchmark-calibrated collectives predict GEMV and SUMMA? (2026-09-24)

**Pre-registered verdict: FAIL.** The fork simulator (S), calibrated only on simfab collective microbenchmarks,
missed GEMV by −22.1 / −21.6 / −29.3% at P = 16 / 32 / 64 and was no better than the analytic composition of the
same laws (A). It missed SUMMA by −1.12 / −1.13 / −1.12% against a 1% bar.

**Post-hoc finding (not a pass): both misses come from mechanisms that 1D collective microbenchmarks cannot see.
Each was isolated with a new, independent microbenchmark.**

1. **Host-induced launch skew (GEMV).** In GEMV's host sequence, single-PE host→device copies precede the
   launch. After them, row 0 enters `main` 362–2208 cycles after the other rows (P = 2…64). Every PE's TSC is
   enabled by the same delayed command stream, so local stamps hide the skew, yet `cycles_send`
   (max end − min start) contains it. Adding the skew, measured by a separate launch probe, to the unchanged
   simulator brings GEMV to **−1.8 / −0.3 / +1.0 %** at P = 16 / 32 / 64, and within ±2.3% at every P.
2. **Concurrent x+y broadcast serialization (SUMMA).** Two broadcasts in flight at once on a PE take 860–943
   cycles against about 500 for either alone. The simulator under-serializes this by 60–137 cycles, which
   matches SUMMA's residual of 144 cycles per step.

The collective primitives themselves are accurate. The single-op microbenchmarks match within ±2% (median
0.3%) up to P = 64, 4× beyond the training sizes; the one exception is gather with count = 1. They also
generalize to full 2D grids and mid-line roots never used in calibration (−0.6 to −2.6%).

![Stage 0 errors](results/fig_s0.png)

## 1. What was built
- **Router multicast** (`src/network/router.h`, `-DWSE_MCAST`). A head flit tagged MC_ROW or MC_COL fans out
  from the core to both line directions, and each hop delivers to its core and forwards. The path stays
  reserved until the tail flit. This replaces the pilot's multicast emulation.
- **Collective primitives** (`src/apps/wse_twin.h`, kernels ≥ 4): broadcast, scatter, gather and
  reduce_fadds, each modelled as
  - a fixed cost F[op][root side] (set-up + teardown + callback);
  - a per-word root cost B;
  - 1 word/cycle streams and 2-cycle hops;
  - the memcpy launch wave (2 cycles/column);
  - reduce as a pipelined chain with a per-stage delay L_RE.
- **Twin kernels:** 4 = microbenchmark, 5 = GEMV, 6 = SUMMA, 7 = 2D broadcast (post-hoc).
- **simfab benches** (`wse/bench`):
  - `collbench`: 144 runs, 4 ops × P 4…64 × counts 1/8/64 × root first/last, plus y-dimension spot checks
    and chained ×3 runs.
  - `phase`: compute stamps at P = 2.
  - Post-hoc: `diag` (GEMV with 8 stamps per PE), `launchprobe` and `coll2d`.

## 2. Calibration (microbenchmarks only, x dimension, P ≤ 16)
Pass 1 ran with F = 0. Its residual, SDK − twin, is fitted as F + B·c + D·(P−1) for each op and side.
Any slope in c or P means a structural term is missing:
- **gather:** residual slope in c → per-word root cost B = 0.52 (root first) and 0.32 (root last).
- **reduce:** residual slope in P of −3.2 per PE. muchiSim's task dispatch already adds cycles, so the
  per-stage delay drops from 8 to L_RE = 5.
- **bcast and scatter:** flat residuals; the a-priori structure held.

Pass 2 sets F to the median residual. Afterwards every residual is flat, varying by ≤ 8 cycles, or ≤ 22 for
gather with root first.

| F (cycles) | bcast | scatter | gather | reduce |
|---|---:|---:|---:|---:|
| root first | 286 | 449 | 397 | 641 |
| root last | 289 | 438 | 513 | 746 |

Init cost (K_INIT) per dimension was read from the microbenchmarks: 123 per dimension for GEMV's op mix and
25 for SUMMA's broadcasts. Compute was measured at P = 2: GEMV 107 / 101 cycles, SUMMA 11,904 per step.

## 3. Primitive validation (all 144 microbenchmark configs)

| set | n | median \|err\| | max \|err\| |
|---|---:|---:|---:|
| train (x, P ≤ 16) | 72 | 0.27% | 2.9% |
| hold-out P = 32/64 (x) | 48 | 0.54% | 9.8%* |
| y-dimension spot checks | 16 | 0.89% | 2.1% |
| chained ×3 | 8 | 4.4% | 6.1% |

\* Gather with count = 1 and root last is +4.7% at P = 32 and +9.8% at P = 64. This is a packet-granularity
artifact: a 1-word stream costs 2 flits per PE. Every other hold-out is within 2.1%:
- bcast and scatter ≤ 1.0%;
- reduce ≤ 2.1%;
- gather ≤ 2.1% (excluding count = 1).

The chained runs show that isolated F double-counts part of the set-up/teardown between back-to-back ops, by
about 15 cycles per op for bcast/reduce and more for gather. Before predicting, I recorded the decision not to
add a chaining correction (`s0_state.json: decisions_before_prediction`).

## 4. Pre-registered test (GEMV, SUMMA; never used for fitting)

| kernel | P | SDK | S | S err | A err | B err (pilot twin) | C err (closed form) |
|---|---:|---:|---:|---:|---:|---:|---:|
| GEMV | 2 | 3,196 | 2,859 | −10.5% | −10.4% | +9.6% | +3.2% |
| GEMV | 4 | 3,658 | 2,919 | −20.2% | −19.9% | −2.8% | −4.2% |
| GEMV | 8 | 3,863 | 3,039 | −21.3% | −20.8% | −5.1% | +1.3% |
| GEMV | 16 | 4,209 | 3,279 | **−22.1%** | −21.0% | −7.8% | +12.5% |
| GEMV | 32 | 4,792 | 3,759 | **−21.6%** | −19.7% | −10.0% | +33.1% |
| GEMV | 64 | 6,676 | 4,719 | **−29.3%** | −26.6% | −22.5% | +44.7% |
| SUMMA | 16 | 205,306 | 203,000 | **−1.12%** | −2.91% | −0.03% | −0.18% |
| SUMMA | 32 | 410,630 | 405,989 | **−1.13%** | −2.43% | −0.02% | −0.63% |
| SUMMA | 64 | 821,255 | 812,052 | **−1.12%** | −1.43% | +0.08% | −1.57% |

**Gate (pre-registered):**
- S within 5% on GEMV at every P ≥ 16: **no**.
- S's GEMV median ≤ A's: **no** (22.1% vs 21.0%).
- S within 1% on SUMMA: **no** (1.12%).

**Result: FAIL.** S ≈ A on GEMV, so the simulator added nothing over summing the laws. On SUMMA, S was
2.6× closer than A, because it models the overlap of concurrent streams, but it still missed.

**Determinism:**
- GEMV (2 threads) reproduced exactly.
- SUMMA P = 16 is identical at 2 and 4 threads.
- SUMMA P = 64 at 4 threads differed by 5 cycles out of 812k between repeats (6×10⁻⁶).

## 5. Post-hoc diagnosis (after the gate; labelled as such)
### 5.1 GEMV: the missing time is a host-induced launch skew, not collective cost
Per-PE stamps at every phase boundary (`bench/diag`, adding about 85 cycles of stamping overhead) show the
problem is in column 0's `scatter_y`:
- The root finishes on schedule: 487 cycles at P = 2 and 600 at P = 16, close to the isolated law.
- The non-root PEs finish 885–3,194 cycles after their own start (P = 2 to 64), against an isolated
  472–1,111 cycles.

Every other phase matches its isolated cost once the row-0 offset is accounted for.

A simfab trace at P = 4 (`bench/diag/trace_gemv`) settles it in global cycles. Rows 1–3 dispatch their first
post-`main` task at cycles 4,231–4,238; row 0 dispatches at 4,978–4,982. Row 0 therefore enters `main`
**about 747 cycles late**. Row 0 also runs 6 memcpy command dispatches (colour 27, until cycle about 4,250)
against 2 in the other rows. Its TSC is enabled by the same delayed stream, so its local entry stamp is only
54 cycles late.

A **launch probe** (`bench/launchprobe`) measures this independently of GEMV. Row 0 sends one wavelet south at
`main` entry, and every PE stamps its entry and the arrival. The probe replays GEMV's host sequence:
- an h2d copy to all PEs;
- two h2d copies to PE (0,0);
- enable timer, then `main`.

| P | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---:|---:|---:|---:|---:|---:|
| row-0 lag D = probe arrival − entry − 28 | 362 | 662 | 770 | 896 | 1,109 | 2,208 |
| GEMV shortfall SDK − S | 337 | 739 | 824 | 930 | 1,033 | 1,957 |
| **S with row-0 launch offset D** | **+0.78%** | −2.27% | −1.86% | **−1.81%** | **−0.29%** | **+0.97%** |

The last row is the twin rerun with only this change (rows 1… follow a measured 3 cycles/row wave).
- The 28-cycle hop latency comes from the probe **without** host copies. There, row 0 is not late: arrival −
  entry = 28, rising about 2 cycles per row.
- With SUMMA's host sequence (enable timer first, then full-grid copies only), there is also **no** row-0 lag,
  just a y-wave of about 3 cycles per row.
- The probe is reproducible with a different binary size.
- At P = 4 the probe underestimates GEMV's own trace-measured lag by about 85 cycles (662 vs 747). This
  program-dependent residue is the main source of the remaining −2%.

**Implications beyond this simulator:**
1. `device_internal_v2` `cycles_send` includes host-sequence-dependent launch skew. For GEMV at P = 16 that
   is about 21% of the reported cycles. Kernels whose critical path starts on row 0 after single-PE copies
   pay it; others do not. Any model, or any cross-kernel comparison in xkernel, that treats `cycles_send` as
   pure kernel time inherits this.
2. Launch state is a first-class input for a WSE performance model: it depends on the host sequence, the
   rows involved and P.

### 5.2 SUMMA: concurrent x+y broadcasts nearly serialize
`bench/coll2d` runs the whole P×P grid broadcasting along x, along y, or both at once, with 196 words and the
root at an end or mid-line.

| P | root | x alone | y alone | x+y concurrent (SDK) | twin (x+y) |
|---:|---|---:|---:|---:|---:|
| 4 | 0 / mid / last | 493 / 508 / 507 | 497 / 505 / 503 | 860 / 883 / 893 | −9.7 / −11.6 / −12.3% |
| 8 | 0 / mid / last | 493 / 517 / 523 | 507 / 506 / 509 | 860 / 904 / 915 | −8.7 / −13.2 / −13.6% |
| 16 | 0 / mid / last | 494 / 534 / 555 | 528 / 515 / 521 | 861 / 930 / 943 | −7.0 / −14.7 / −14.4% |

Single-direction twin error is −0.6 to −2.6% for every root, mid-line included. The concurrent case costs
about 1.75× a single broadcast on the SDK, but only about 1.55× in the twin. In muchiSim each queue ejects
into the core independently, while a WSE PE's ramp and data path are shared across colours. The
under-serialization at P = 16 with a mid-line root is 137 cycles, against SUMMA's residual of 144 cycles
per step, whose roots are mostly mid-line.

## 6. What Stage 0 says about the research direction
- **The engine and primitive approach works.** Four collective primitives calibrated with 11 constants (8 F, 2 gather B, L_RE) predict
  every single-op configuration within ±2% up to P = 64, including 2D grids and unseen root positions.
- **Composition failed for two nameable, measurable reasons. Neither is fabric-level, and both are invisible
  to 1D single-op microbenchmarks:**
  - launch state from the host command sequence;
  - PE ingress sharing between concurrent collectives.
  Chaining overlap (§3) is a third, smaller one.
- **Next (Stage 1, revising ROADMAP):**
  1. A launch model: per-row launch offsets as a function of the host sequence, from a launch-probe family.
     This should be validated on a kernel with a different host sequence, not GEMV again.
  2. A shared PE ramp in the router's core port, calibrated on `coll2d` P ≤ 8 and tested on P = 16 and
     SUMMA.
  3. A chaining transition cost from chained microbenchmarks with mixed ops.
  4. A fresh pre-registration with **new** test kernels, since GEMV and SUMMA have now been seen.

## Reproduce
```bash
cd /mnt/data/luo00466/wsesim
python3 wse/bench/collbench/sweep.py            # simfab microbenchmarks -> results/collbench.jsonl
python3 wse/stage0/analysis.py                  # laws (control A)
python3 wse/stage0/s0_calibrate.py calib        # two-pass calibration -> src/apps/wse_s0_params.h
python3 wse/stage0/s0_calibrate.py validate     # 144 configs
python3 wse/stage0/s0_calibrate.py predict      # GEMV/SUMMA (pre-registered test)
python3 wse/stage0/s0_gate.py                   # gate, summary, figure
# post-hoc
python3 wse/bench/diag/diag.py run 2 4 8 16 32 64
python3 wse/bench/coll2d/sweep.py
# launch probe: wse/bench/launchprobe (cslc + run.py per P; H2D=0/1/2 selects the host sequence)
```
Results: `results/s0_summary.json`, `s0_state.json`, `validate.log`, `predict.log`, `diag_gemv.json`,
`launch_row0.json`, `posthoc_gemv_launch.json`, `coll2d.jsonl`, `coll2d_twin.json`,
`twin_gemv_phases.txt`.
