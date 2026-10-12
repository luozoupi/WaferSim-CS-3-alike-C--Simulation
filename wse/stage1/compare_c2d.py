#!/usr/bin/env python3
"""Stage 1 M5 (gate item 2): ported <collectives_2d> on the fabric + F1 vs simfab collbench / chain / coll2d op_only.
Constants per Addendum B: fabric + F1 from profile_m1.txt; collectives CPU costs from Stage 0c / measured stamps;
handler and lock = the M1 generic task-entry cost (BE).  Nothing is fitted here.
usage: compare_c2d.py [--show] [key=value overrides for diagnosis only]"""
import json, os, subprocess, sys, statistics
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__)); S0 = os.path.join(HERE, "../stage0/results")
prof = dict(kv.split("=") for kv in open(os.path.join(HERE, "profile_m1.txt")).read().split())
BASE = [f"{k}={prof[k]}" for k in ("hop", "link", "buf", "rin", "rout", "turn", "s0", "s0c", "cpl", "disp", "tdd", "exit")]
BASE += [f"handler={prof['BE']}", f"lock={prof['BE']}", "init=25", "init2=9", "cfg=101", "act=55", "tdd2=42", "td2=6",
         "copy=1.0", "fadd=1.0", f"LW={prof['LW']}", f"LY={prof['LY']}"]


def run(args):
    out = subprocess.run([os.path.join(HERE, "c2dsim")] + args, capture_output=True, text=True).stdout
    return json.loads(out)


def cases():
    out = []
    for r in map(json.loads, open(os.path.join(S0, "collbench.jsonl"))):
        if r.get("op_only"):
            root = 0 if r["root"] == "first" else r["P"] - 1
            out.append(("collbench", r["tag"], r["op_only"], [f"kernel=collbench", f"op={r['op']}", f"P={r['P']}", f"count={r['count']}",
                                                          f"root={root}", f"dim={r['dim']}", f"reps={r['reps']}"]))
    for r in map(json.loads, open(os.path.join(S0, "chain.jsonl"))):
        if r.get("op_only"):
            root = 0 if r["roots"] == "ff" else r["P"] - 1
            out.append(("chain", r["tag"], r["op_only"], [f"kernel=chain", f"op={r['op']}", f"op2={r['op2']}", f"P={r['P']}",
                                                      f"count={r['count']}", f"root={root}", f"root2={root}", f"dim={r['dim']}"]))
    for r in map(json.loads, open(os.path.join(S0, "coll2d.jsonl"))):
        if r.get("op_only"):
            fam = "coll2d_single" if r["MODE"] in (0, 1) else "coll2d_concurrent"
            out.append((fam, r["tag"], r["op_only"], [f"kernel=coll2d", f"P={r['P']}", f"mode={r['MODE']}", f"count={r['COUNT']}",
                                                   f"countY={r.get('COUNTY', r['COUNT'])}", f"root={r['ROOT']}"]))
    return out


def main():
    extra = [a for a in sys.argv[1:] if "=" in a]
    cs = cases()
    with ThreadPoolExecutor(16) as ex:
        res = list(ex.map(lambda c: run(c[3] + BASE + extra), cs))
    fam = {}
    for (f, tag, sim, _), m in zip(cs, res):
        e = 100 * (m["op_only"] / sim - 1) if m.get("ok") else float("inf")
        fam.setdefault(f, []).append((abs(e), e, tag, sim, m.get("op_only")))
        if "--show" in sys.argv:
            print(f"  {f:18s} {tag:34s} simfab {sim:6d} model {m.get('op_only')!s:>6} {e:+7.2f}%")
    for f, es in fam.items():
        a = [x[0] for x in es]; w = max(es)
        print(f"{f:18s} n={len(a):3d} median|e|={statistics.median(a):5.2f}% max|e|={w[0]:7.2f}% within5%={sum(x <= 5 for x in a)}/{len(a)} "
              f"(worst {w[2]} simfab {w[3]} model {w[4]})")
    json.dump({f: [list(x) for x in es] for f, es in fam.items()}, open(os.path.join(HERE, "results/m5_eval.json"), "w"))


if __name__ == "__main__":
    main()
