#!/usr/bin/env python3
"""Stage 1 M1: fit profile constants on TRAIN rows only (PREREGISTRATION Addendum A, hold-out handling).
Coordinate descent over integer key=value parameters of fabsim2; objective = mean |error| (%) of the primary
metrics over the selected train families (optionally + max term).  Hold-out rows are never evaluated here.
usage: fit_m1.py --params s0=7,cpl=3,... [--families f1,f2] [--span 6] [--rounds 3] [--maxw 0.2] [fixed k=v ...]"""
import sys, statistics
import compare2


def score(kv, fams):
    errs = []
    for f in fams:
        for fam, es in compare2.evaluate(kv, role="train", fam=f).items():
            errs += [e[0] for e in es]
    if not errs:
        return float("inf"), 0, 0
    return statistics.mean(errs), statistics.median(errs), max(errs)


def main():
    a = sys.argv[1:]
    params = dict(p.split("=") for p in a[a.index("--params") + 1].split(","))
    params = {k: int(v) for k, v in params.items()}
    fams = a[a.index("--families") + 1].split(",") if "--families" in a else [None]
    span = int(a[a.index("--span") + 1]) if "--span" in a else 6
    rounds = int(a[a.index("--rounds") + 1]) if "--rounds" in a else 3
    wmax = float(a[a.index("--maxw") + 1]) if "--maxw" in a else 0.2
    fixed = [x for x in a if "=" in x and not x.startswith("--") and x.split("=")[0] not in params
             and x not in (a[a.index("--params") + 1],)]
    obj = lambda p: (lambda m: m[0] + wmax * m[2])(score(fixed + [f"{k}={v}" for k, v in p.items()], fams))
    best = obj(params)
    print(f"start {params} obj={best:.3f}", flush=True)
    for r in range(rounds):
        improved = False
        for k in list(params):
            for d in sorted(range(-span, span + 1), key=abs):
                if d == 0 or params[k] + d < 0:
                    continue
                q = dict(params, **{k: params[k] + d}); v = obj(q)
                if v < best - 1e-9:
                    best, params, improved = v, q, True
        m = score(fixed + [f"{k}={v}" for k, v in params.items()], fams)
        print(f"round {r}: {params} mean={m[0]:.3f}% median={m[1]:.3f}% max={m[2]:.3f}%", flush=True)
        if not improved:
            break
    print("FIT", ",".join(f"{k}={v}" for k, v in params.items()), " ".join(fixed))


if __name__ == "__main__":
    main()
