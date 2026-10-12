#!/usr/bin/env python3
"""Stage 1 gate item 2 (Addendum D evaluation, run once after m5_pred.json was committed)."""
import json, os, statistics
HERE = os.path.dirname(os.path.abspath(__file__)); S0 = os.path.join(HERE, "../stage0/results")
PRED = os.environ.get("PRED", "results/m5_pred.json"); GOUT = os.environ.get("GOUT", "results/gate_m5.json")
P = json.load(open(os.path.join(HERE, PRED)))["predictions"]
D = json.load(open(os.path.join(HERE, "results/m5_pred.json")))["predictions"] if PRED != "results/m5_pred.json" else None
B = json.load(open(os.path.join(HERE, "results/m5_eval.json")))
truth = {}
for fn, fams in (("collbench.jsonl", None), ("chain.jsonl", None), ("coll2d.jsonl", None)):
    for r in map(json.loads, open(os.path.join(S0, fn))):
        truth[r["tag"]] = r["op_only"]
TH = {"collbench": ("median", 1.0, "max", 5.0), "chain": ("median", 1.5), "coll2d_single": ("median", 1.5), "coll2d_concurrent": ()}
ok_all = True; out = {}
for f, preds in P.items():
    e = [(abs(100 * (m / truth[t] - 1)), 100 * (m / truth[t] - 1), t, truth[t], m) for t, m in preds.items()]
    a = [x[0] for x in e]; med, mx = statistics.median(a), max(a)
    th = TH[f]; passed = True
    if th:
        passed = med <= th[1] and (len(th) < 4 or mx <= th[3])
    if th and not passed:
        ok_all = False
    bmed = statistics.median([x[0] for x in B[f]])
    dmed = statistics.median([abs(100 * (m / truth[t] - 1)) for t, m in D[f].items()]) if D else None
    w = max(e)
    print(f"{f:18s} n={len(a):3d} median|e|={med:5.2f}% max|e|={mx:6.2f}% within5%={sum(x <= 5 for x in a)}/{len(a)} "
          f"| gate {'PASS' if passed else 'FAIL'}{'' if th else ' (reported, not gated)'} | B median {bmed:5.2f}%" + (f" D median {dmed:5.2f}%" if D else "") + f" | worst {w[2]} {w[3]}->{w[4]}")
    out[f] = dict(n=len(a), median=med, max=mx, passed=passed, gated=bool(th), addendumB_median=bmed)
print("GATE ITEM 2:", "PASS" if ok_all else "FAIL")
json.dump(out, open(os.path.join(HERE, GOUT), "w"), indent=1)
