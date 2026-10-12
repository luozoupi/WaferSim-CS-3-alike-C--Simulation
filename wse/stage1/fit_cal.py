#!/usr/bin/env python3
"""Stage 1 Addendum D: residual fit of the port's scalar constants on the CALIBRATION rows only (P = 12; op_only).
Fabric constants stay at profile_m1.txt; the cost table is results/c2d_costs.txt.  Prints the fit and the
per-row errors.  usage: fit_cal.py [--params k=v,...] [--span 6] [--rounds 4] [--show]"""
import gzip, json, os, subprocess, sys, statistics
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__))
prof = dict(kv.split("=") for kv in open(os.path.join(HERE, "profile_m1.txt")).read().split())
FAB = [f"{k}={prof[k]}" for k in ("hop", "link", "buf", "rin", "rout", "turn")]
COSTS = os.environ.get("COSTS", "results/c2d_costs.txt")
CALP = [int(x) for x in os.environ.get("CAL_PS", "12").split(",")]
FIXED = FAB + ["costs=" + os.path.join(HERE, COSTS), "init=25", "init2=9", "td2=6",
               f"LW={prof['LW']}", f"LY={prof['LY']}"]
CASES = []
for Pc in CALP:
    d = json.load(gzip.open(os.path.join(HERE, "results/c2dcal.json.gz" if Pc == 12 else f"results/c2dcal_P{Pc}.json.gz"), "rt"))
    for r in d["rows"]:
        st = [pe["stamps"] for pe in r["pes"]]
        CASES.append((r["tag"], max(s[2] for s in st) - min(s[1] for s in st),
                      ["kernel=collbench", f"op={r['op']}", f"P={d['P']}", f"count={r['count']}", f"root={r['root']}", "dim=0", f"reps={r['reps']}"]))


def run(args):
    o = subprocess.run([os.path.join(HERE, "c2dsim")] + args, capture_output=True, text=True).stdout
    try:
        d = json.loads(o); return d["op_only"] if d.get("ok") else None
    except Exception:
        return None


def errs(p):
    kv = [f"{k}={v}" for k, v in p.items()]
    with ThreadPoolExecutor(16) as ex:
        res = list(ex.map(lambda c: run(c[2] + FIXED + kv), CASES))
    return [(100 * (m / s - 1) if m else 1e3, t, s, m) for (t, s, _), m in zip(CASES, res)]


def obj(p):
    e = [abs(x[0]) for x in errs(p)]
    return statistics.mean(e) + 0.2 * max(e)


def main():
    a = sys.argv[1:]
    p = dict(x.split("=") for x in (a[a.index("--params") + 1].split(",") if "--params" in a else
             "kts2=10,disp=6,cpl=-4,fwl=7,s0=7,s0c=7,oq=8,a0=5,tdd=3,tail=6".split(",")))
    p = {k: int(v) for k, v in p.items()}
    span = int(a[a.index("--span") + 1]) if "--span" in a else 6
    rounds = int(a[a.index("--rounds") + 1]) if "--rounds" in a else 4
    best = obj(p); print("start", p, f"{best:.3f}", flush=True)
    for r in range(rounds):
        imp = False
        for k in list(p):
            for d in sorted(range(-span, span + 1), key=abs):
                if d == 0:
                    continue
                q = dict(p, **{k: p[k] + d}); v = obj(q)
                if v < best - 1e-9:
                    best, p, imp = v, q, True
        e = [abs(x[0]) for x in errs(p)]
        print(f"round {r}: {p} mean={statistics.mean(e):.3f}% median={statistics.median(e):.3f}% max={max(e):.3f}%", flush=True)
        if not imp:
            break
    for e, t, s, m in sorted(errs(p), key=lambda x: -abs(x[0])):
        if "--show" in a or abs(e) > 1:
            print(f"  {t:30s} simfab {s:5d} model {m} {e:+.2f}%")
    print("FIT", ",".join(f"{k}={v}" for k, v in p.items()))


if __name__ == "__main__":
    main()
