#!/usr/bin/env python3
"""Stage 1 gate item 1: committed hold-out predictions vs simfab (every hold-out case within +-3% on its primary
metric).  Run only after results/fabric_pred_holdout.json is committed."""
import json, os, statistics, collections
import compare2
HERE = os.path.dirname(os.path.abspath(__file__))
P = json.load(open(os.path.join(HERE, "results/fabric_pred_holdout.json")))["predictions"]
fam = collections.defaultdict(list); fails = []
for r in compare2.rows():
    if r["role"] != "holdout":
        continue
    ps = compare2.primary_ctl(r, r["obs"]) if r["family"] in compare2.CTL_FAMILIES else compare2.primary_legacy(r)
    for k, v in ps.items():
        m = P[r["tag"]].get(k)
        e = 100 * (m / v - 1) if (m is not None and v) else float("inf")
        fam[r["family"]].append(abs(e))
        if abs(e) > 3:
            fails.append((r["tag"], k, v, m, e))
tot = []
for f, es in sorted(fam.items()):
    tot += es
    print(f"{f:12s} n={len(es):3d} median|e|={statistics.median(es):5.2f}% max|e|={max(es):6.2f}% within3%={sum(e <= 3 for e in es)}/{len(es)}")
print(f"{'ALL':12s} n={len(tot):3d} median|e|={statistics.median(tot):5.2f}% within3%={sum(e <= 3 for e in tot)}/{len(tot)}")
print("GATE ITEM 1:", "PASS" if not fails else f"FAIL ({len(fails)} hold-out metrics outside +-3%)")
for f in sorted(fails, key=lambda t: -abs(t[4])):
    print(f"  {f[0]:28s} {f[1]:12s} simfab {f[2]} model {f[3]} {f[4]:+.2f}%")
