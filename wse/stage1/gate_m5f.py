#!/usr/bin/env python3
"""Stage 1 gate item 3 (Addendum F, run once): Stage 0 regression suite on the Stage 1 engine vs the Stage 0c truths.
Rows and gate points exactly as wse/stage0/s0c_gate.py; Stage 1 rule: median |e| over the 19 U gate points <= 1.55%,
no point that Stage 0c had within 5% moves outside 5%, SUMMA within 1%."""
import json, os, statistics
HERE = os.path.dirname(os.path.abspath(__file__)); R0 = os.path.join(HERE, "../stage0/results")
PRED = os.environ.get("PRED", "results/m5f_pred.json"); GOUT = os.environ.get("GOUT", "results/gate_m5f.json")
pred = json.load(open(os.path.join(HERE, PRED)))["predictions"]
s0c = {(r["series"], r["P"]): r for r in json.load(open(os.path.join(R0, "s0c_summary.json")))["rows"]}
rows = []
for (series, P), r in sorted(s0c.items()):
    base = series.rsplit("_", 1)[0] if series.startswith("T2") else series
    metric = series.rsplit("_", 1)[1] if series.startswith("T2") else "cs"
    p = pred.get(f"{base}/P{P}")
    m = p.get(metric) if p else None
    e = 100 * (m / r["truth"] - 1) if m else None
    rows.append(dict(series=series, P=P, truth=r["truth"], S1=m, S1_err=e, S0c=r["S0c"], S0c_err=r["S0c_err"]))
isU = lambda r: r["series"].startswith("U")
gate = [r for r in rows if isU(r) and ((r["series"].startswith("U3") and r["P"] in (16, 32)) or (not r["series"].startswith("U3") and r["P"] in (16, 32, 64)))]
med = statistics.median(abs(r["S1_err"]) for r in gate)
regress = [r for r in rows if abs(r["S0c_err"]) <= 5 and abs(r["S1_err"]) > 5]
summa = [r for r in rows if r["series"] == "SUMMA"]
summa_ok = all(abs(r["S1_err"]) <= 1 for r in summa)
print(f"{'series':12s} {'P':>3s} {'truth':>8s} {'Stage1':>8s} {'S1 err':>7s} {'S0c err':>7s}")
for r in rows:
    tag = " *gate" if r in gate else ""
    print(f"{r['series']:12s} {r['P']:3d} {r['truth']:8d} {r['S1']!s:>8} {r['S1_err']:+7.2f} {r['S0c_err']:+7.2f}{tag}")
res = {"n_gate_points": len(gate), "S1_median_abs_gate": med, "S0c_median_abs_gate": statistics.median(abs(r["S0c_err"]) for r in gate),
       "within5_S1": sum(abs(r["S1_err"]) <= 5 for r in rows), "within5_S0c": sum(abs(r["S0c_err"]) <= 5 for r in rows), "n_rows": len(rows),
       "regressions": [(r["series"], r["P"], round(r["S1_err"], 2)) for r in regress], "SUMMA_ok": summa_ok,
       "median_all_S1": statistics.median(abs(r["S1_err"]) for r in rows), "median_all_S0c": statistics.median(abs(r["S0c_err"]) for r in rows)}
res["PASS"] = med <= 1.55 and not regress and summa_ok
print(json.dumps(res, indent=1)); print("GATE ITEM 3:", "PASS" if res["PASS"] else "FAIL")
json.dump({"rows": rows, "gate": res}, open(os.path.join(HERE, GOUT), "w"), indent=1)
