# Stage 1 plan: WSE fabric core (2026-09-26)

**Scope** (ROADMAP §5, amended below): a wavelet-level WSE fabric model, a deterministic engine, rectangular
grids and route import. Collectives are rebuilt from routing configuration rather than from the Stage 0
primitives. Stage 0 closed with the Stage 0c model as the collectives baseline (`wse/stage0/STAGE0_CLOSURE.md`).

## Architecture decision (amends ROADMAP §3.1 "keep engine")
The fabric is a **new deterministic engine inside the fork** (`src/wse/`, flag `-DWSE_FABRIC`). muchiSim's
router is not retrofitted. The reasons:
1. **Determinism.** muchiSim's core and router threads synchronise through racing timers, and results are
   reproducible only at 2 host threads (pilot and Stage 0). The new engine is single-threaded, cycle-stepped
   over an **active set** of links and colours, so it is deterministic by construction. A parallel mode
   (spatial partitions with conservative synchronisation) comes later, in Stage 4, and is accepted only if
   it is bit-identical.
2. **Router semantics.** WSE routing has 24 colours per tile. Each colour has one rx direction and a tx set
   over {RAMP, N, S, E, W}, with switch positions pos0–3 advanced by control wavelets, ring mode, pop mode,
   a counter filter and teardown mode. Wavelets have no header. muchiSim's router instead has four
   dimension-ordered logical channels and address-based wormhole routing; mapping one onto the other would
   fight its structure everywhere.
3. **Rectangular grids.** 762×1172 and 750×994 are required. muchiSim's power-of-two square assumption runs
   through `global()`, head-flit encoding and the thread partitioning (15 sites).
4. **Reuse is not lost.** Stage 0's value is in its constants, mechanisms and data, all of which carry over.
   The collectives must be rebuilt at wavelet level for the gate in any case. muchiSim's energy, area and cost
   models can be linked later (RQ4).

## Milestones
| id | milestone | output |
|---|---|---|
| M1 | **Fabric microbenchmark campaign on simfab.** One generator (`wse/bench/fabric/`) takes a route spec: path with turns, multicast taps, colours, payload, number of sources, receiver delay, switch positions and teardown. Every run is **traced**: per-router cycles per wavelet are paired by `ident` (decoded `fields`: colour, ctrl, link, ramp), with TSC stamps as a cross-check. | ground-truth curves for straight paths, turns, multicast, contention, relay, switch advance, teardown and backpressure |
| M2 | **Fabric engine.** Tiles × 24 colours; per-colour route state (rx, tx set, pos0–3, ring, pop, filter, teardown); per-port link arbitration at 1 wavelet per `link_cycles`; hop latency; turn penalty; per-colour input-buffer depth; control-wavelet commands (advance, reset, teardown); active-set stepping; rectangular grids. Constants live in profile `simfab-2.10`. | `src/wse/fabric.h`, unit tests |
| M3 | **PE interface (F1, fabric-level).** fabout/fabin DSD streams (setup, then 1 wavelet/cycle; completion task +3 cycles), data tasks, TSC stamps, a minimal task scheduler. Launch state comes from Stage 0c launch law v2. | `src/wse/pe.h`; the M1 microbenchmarks as F1 programs |
| M4 | **Route import.** Load `fabric_probe.py` JSON (`cs_readelf --routing --switching`) or `cslc --out-routes` tables into the fabric's static configuration; check round-trip identity on the M1 benches and on Stage 0 kernels. | `wse/stage1/route_import.py`, a C++ loader |
| M5 | **Collectives from routing configuration.** Port `collectives_2d` (pe.csl 1,312 lines: `configure_*_network`, the switch-advance FSM, teardown handlers, reduce with two colours) to F1 on top of the fabric. Stage 0c PE-engine constants (config/activate cost, completion costs, second-module cost) are used where the fabric does not yet produce them. | wavelet-level collectives; collbench/chain/coll2d replays |
| M6 | **Gate and report.** | `wse/stage1/REPORT.md` |

## Validation and ground truth
- **simfab traces are the primary ground truth for the fabric**: per-hop timing at wavelet granularity,
  with no TSC or launch-skew ambiguity. TSC windows (the device_internal_v2 convention) are used for
  kernel-level comparisons.
- **Train and hold-out by size in every family.** For example, straight paths train on hops
  {1, 2, 4, 16, 32, 64} with payload {1, 8, 64, 512} and hold out hops {8, 128} and payload 256.
- **Carried gaps** (Stage 0 closure): the wavelet-level fabric should remove the gather count = 1 packet
  artifact and the chained-gather over-prediction. The memcpy command fabric at large P (single-PE copy
  stalls at P = 64 and launch propagation) is a stretch goal, M7, taken on only if M1–M6 finish.
  Bandwidth-shared concurrent DSDs stay in Stage 2.

## Risks
- **Unknown router internals** (buffer depth, arbitration policy, turn mechanism). M1 measures them
  directly; where simfab behaviour cannot be isolated, the model uses the simplest structure that matches
  the curves and says so.
- **Control-wavelet semantics** (advance, reset, teardown, ring mode). Taken from the collectives_2d and
  memcpy source (`wse/refs/`), with dedicated M1 probes.
- **Performance at wafer scale.** Active-set stepping is measured from M2 on, as tile-cycles/s against
  simfab and muchiSim.

## Effort
Three to four weeks per the roadmap. M1 and M2 come first and run in parallel; M5 is the largest milestone.
