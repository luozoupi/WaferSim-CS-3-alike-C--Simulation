#!/usr/bin/env python3
"""Stage 1 Addendum D: blind predictions for the gate-item-2 sets with the frozen profile_m5.txt.  Reads only the
configuration fields of each simfab row (never op_only).  Writes results/m5_pred.json."""
import json, os, subprocess
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__)); S0 = os.path.join(HERE, "../stage0/results")
PROFILE = os.environ.get("PROFILE", "profile_m5.txt"); OUTF = os.environ.get("OUT", "results/m5_pred.json")
prof = [kv if not kv.startswith("costs=") else "costs=" + os.path.join(HERE, kv[6:]) for kv in open(os.path.join(HERE, PROFILE)).read().split()]


def configs():
    out = []
    for r in map(json.loads, open(os.path.join(S0, "collbench.jsonl"))):
        root = 0 if r["root"] == "first" else r["P"] - 1
        out.append(("collbench", r["tag"], ["kernel=collbench", f"op={r['op']}", f"P={r['P']}", f"count={r['count']}", f"root={root}", f"dim={r['dim']}", f"reps={r['reps']}"]))
    for r in map(json.loads, open(os.path.join(S0, "chain.jsonl"))):
        root = 0 if r["roots"] == "ff" else r["P"] - 1
        out.append(("chain", r["tag"], ["kernel=chain", f"op={r['op']}", f"op2={r['op2']}", f"P={r['P']}", f"count={r['count']}", f"root={root}", f"root2={root}", f"dim={r['dim']}"]))
    for r in map(json.loads, open(os.path.join(S0, "coll2d.jsonl"))):
        fam = "coll2d_single" if r["MODE"] in (0, 1) else "coll2d_concurrent"
        out.append((fam, r["tag"], ["kernel=coll2d", f"P={r['P']}", f"mode={r['MODE']}", f"count={r['COUNT']}", f"countY={r.get('COUNTY', r['COUNT'])}", f"root={r['ROOT']}"]))
    return out


def run(a):
    d = json.loads(subprocess.run([os.path.join(HERE, "c2dsim")] + a + prof, capture_output=True, text=True).stdout)
    return d["op_only"] if d.get("ok") else None


cs = configs()
with ThreadPoolExecutor(16) as ex:
    res = list(ex.map(lambda c: run(c[2]), cs))
pred = {}
for (f, t, _), v in zip(cs, res):
    pred.setdefault(f, {})[t] = v
json.dump({"profile": " ".join(prof), "predictions": pred}, open(os.path.join(HERE, OUTF), "w"), indent=1)
print({f: len(v) for f, v in pred.items()}, "failed:", sum(v is None for d in pred.values() for v in d.values()))
