#!/usr/bin/env python3
"""Stage 0c launch law (v2): the Stage 0b per-row command-queue stall law plus family-C large-P terms.

  single-PE copy (w = 1):  S1(n, P) = a_P + b_P * n        (per-P fit; P <= 16 pooled; fast path <= 15 words: 39)
  row/band copy (w > 1):   Stage 0b law  a + b*w + c0*w*n + c1*n
  large-P interactions:    + k_prev(P) for a single-PE copy that follows another single-PE copy (two-copy probe)
                           + k_full(P) for a single-PE copy that follows a full-grid copy (GEMV-sequence probe)
  local-entry offset:      a stalled row's TSC enable lags its launch by delta less (probe main: 20; RPC-activated
                           task: 54, 2D T2-x bench)
Fitted on launch-probe families only (launch4.jsonl: v2 family P <= 16, family C P = 32/48/64).
usage: launch_law2.py fit | predict '<json seq>' P [entry]"""
import json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
LAW2 = os.path.join(HERE, "results/launch_law2.json")
FAST = 15
DELTA = {"main": 20, "task": 54}
PS = (4, 8, 16, 32, 48, 64)


def row0(runs, name, P):
    import launch_state
    st = launch_state.state(runs, name, P) if (name, P) in runs else None
    return None if st is None or st["l1"] is None else float(st["l1"].mean(axis=1)[0] - np.delete(st["l1"].mean(axis=1), 0).min())


def fit():
    import launch_state
    runs = launch_state.load()
    law1 = json.load(open(os.path.join(HERE, "results/launch_law.json")))["coef"]
    single = {}
    for grp in ((4, 8, 16), (32,), (48,), (64,)):
        X, y = [], []
        for P in grp:
            for n in (64, 256, 1024):
                v = row0(runs, f"s00_{n}", P)
                if v is not None:
                    X.append([1, n]); y.append(v)
        a, b = np.linalg.lstsq(np.array(X, float), np.array(y), rcond=None)[0]
        for P in grp:
            single[P] = (float(a), float(b))
    S1 = lambda n, P: 39.0 if n <= FAST else single[P][0] + single[P][1] * n
    kprev, kfull, check = {}, {}, {}
    for P in PS:
        v2 = row0(runs, "add2_256", P)
        kprev[P] = 0.0 if (P <= 16 or v2 is None) else v2 - 2 * S1(256, P)
        g = row0(runs, "gemv", P)
        kfull[P] = 0.0 if (P <= 16 or g is None) else g - (S1(4 * P, P) + S1(8 * P, P) + kprev[P])
    out = {"single": {str(P): single[P] for P in PS}, "kprev": {str(P): kprev[P] for P in PS},
           "kfull": {str(P): kfull[P] for P in PS}, "row_law": law1, "fast": [FAST, 39.0], "delta": DELTA}
    json.dump(out, open(LAW2, "w"), indent=1)
    for P in PS:
        print(f"P={P:2d}: S1 = {single[P][0]:6.1f} + {single[P][1]:.3f} n   k_prev {kprev[P]:6.1f}  k_full {kfull[P]:6.1f}")
    # check on every family sequence with a single measured row lag
    for name in ("s00_64", "s00_256", "s00_1024", "add2_256", "gemv", "row0_64", "add3_64", "disj_64", "tbetween_256"):
        line = []
        for P in PS:
            m = row0(runs, name, P)
            if m is None:
                continue
            seq = seqs(P).get(name)
            if seq is None:
                continue
            L, E = predict(seq, P)
            line.append(f"P{P}: {m:6.0f}/{L[0]:6.0f} ({100 * (L[0] / m - 1) if m > 50 else 0:+5.1f}%)")
        print(f"  {name:12s} " + "  ".join(line))


def seqs(P):
    src = open(os.path.join(HERE, "../bench/launch2d/sweep.py")).read().replace("__file__", repr(os.path.join(HERE, "../bench/launch2d/sweep.py")))
    ns = {}
    exec(src.split("def main(")[0], ns)
    f = {k: v[0] for k, v in ns["family"](P).items()}
    f.update({k: v[0] for k, v in ns["family_c"](P).items()})
    return f


def coef_at(tab, P):
    keys = sorted(int(k) for k in tab)
    if P in keys:
        return tab[str(P)]
    lo = max([k for k in keys if k <= P], default=keys[0]); hi = min([k for k in keys if k >= P], default=keys[-1])
    if lo == hi:
        return tab[str(lo)]
    f = (np.log2(P) - np.log2(lo)) / (np.log2(hi) - np.log2(lo))
    a, b = tab[str(lo)], tab[str(hi)]
    return [x + f * (yv - x) for x, yv in zip(a, b)] if isinstance(a, list) else a + f * (b - a)


def predict(seq, P, entry="main"):
    law = json.load(open(LAW2))
    a, b = coef_at(law["single"], P)
    kp, kf = coef_at(law["kprev"], P), coef_at(law["kfull"], P)
    r = law["row_law"]
    D = np.zeros(P); Denable = None
    prev_single = np.zeros(P, bool); prev_full = False
    for st in seq:
        if st[0] == "timer" and Denable is None:
            Denable = D.copy()
        if st[0] == "main":
            break
        if st[0] != "h2d":
            continue
        _, x0, y0, w, h, n, _b = st
        w = P if w == "P" else w; h = P if h == "P" else h; y0 %= P
        rows = slice(y0, y0 + h)
        if w == P and h == P:
            prev_full = True           # full-grid copies stall every row equally (no relative lag)
            continue
        if w * n <= FAST:
            S = 39.0
        elif w == 1:
            S = a + b * n
            S += kp * prev_single[rows] + (kf if prev_full else 0.0)
        else:
            S = r["a"] + r["b"] * w + r["c0"] * w * n + r["c1"] * n
        D[rows] += S
        if w == 1:
            prev_single[rows] = True
        prev_full = False if w == 1 else prev_full
    if Denable is None:
        Denable = D.copy()
    L = D - D.min(); E = Denable - Denable.min()
    stalled = L > 0
    E = np.where(stalled & (np.abs(E - L) < 1e-6), L - law["delta"][entry], E)   # local-entry offset of stalled rows
    return L, np.maximum(E, 0)


if __name__ == "__main__":
    if sys.argv[1] == "fit":
        fit()
    else:
        L, E = predict(json.loads(sys.argv[2]), int(sys.argv[3]), sys.argv[4] if len(sys.argv) > 4 else "main")
        print("main lag:", np.round(L).astype(int).tolist()[:6], "enable lag:", np.round(E).astype(int).tolist()[:6])
