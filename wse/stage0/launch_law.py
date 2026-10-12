#!/usr/bin/env python3
"""Stage 0b launch law (fitted on the launch-probe family only; test host sequences excluded).

Mechanism (memcpy runtime, SDK 2.10 csl-libs; see REPORT_0b): every row has its own command fan and queue and the
host runs ahead of the device.  A copy-mode h2d stalls the command stream of every row its region covers by
    S(w, n) = a + b*w + c0*w*n + c1*n      (w = region width in PEs, n = words per PE; w*n > FAST, else s_fast)
and rows outside the region skip it.  Stalls accumulate and are never recovered, so a later launch (and the TSC
enable) reaches row y late by D_y = sum of stalls covering y (minus the minimum over rows).  A blocking d2h
re-synchronises (not used by the test kernels).
usage: launch_law.py fit | launch_law.py predict '<json host sequence>' P
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import launch_state  # noqa: E402

LAW = os.path.join(HERE, "results/launch_law.json")
FAST = 15            # copies of <= FAST words in total take the command-wavelet fast path (s00_8 vs s00_64)


def seqs(P):
    sys.argv_backup = sys.argv
    src = open(os.path.join(HERE, "../bench/launch2d/sweep.py")).read().replace("__file__", repr(os.path.join(HERE, "../bench/launch2d/sweep.py")))
    ns = {}
    exec(src.split("def main(")[0], ns)
    return {k: v[0] for k, v in ns["family"](P).items()}


def region(step, P):
    _, x0, y0, w, h, n, _b = step
    w = P if w == "P" else w; h = P if h == "P" else h
    return x0 % P, y0 % P, w, h, n


def row_stalls(seq, P, coef, upto="main"):
    """per-row accumulated stall before the first `upto` command ('main' or 'timer')"""
    a, b, c0, c1, s_fast = coef
    D = np.zeros(P)
    for st in seq:
        if st[0] == upto:
            break
        if st[0] == "h2d":
            x0, y0, w, h, n = region(st, P)
            S = s_fast if w * n <= FAST else a + b * w + c0 * w * n + c1 * n
            D[y0:y0 + h] += S
        if st[0] == "d2h":
            D[:] = D.min()      # blocking read-back re-synchronises (only in the resync probes)
    return D - D.min()


def measured_rows(runs, name, P):
    st = launch_state.state(runs, name, P)
    if st is None or st["l1"] is None:
        return None
    return st["l1"].mean(axis=1), st["eps1"].mean(axis=1)


SINGLE = ["s00_64", "s00_256", "s00_1024", "row0_8", "row0_64", "row0_256", "rowP_64", "sP0_64", "s0P_64", "nb_s00_256",
          "nb_row0_64"]
MULTI = ["gemv", "add3_64", "disj_64", "tbetween_256", "full_256", "col0_256", "rowmid_64", "smid_64", "s00_8"]


def fit():
    runs = launch_state.load()
    X, y, meta = [], [], []
    for P in (4, 8, 16):
        fam = seqs(P)
        for name in SINGLE:
            m = measured_rows(runs, name, P)
            if m is None:
                continue
            h2d = [s for s in fam[name] if s[0] == "h2d"][0]
            x0, y0, w, h, n = region(h2d, P)
            lag = m[0][y0:y0 + h].mean() - np.delete(m[0], range(y0, y0 + h)).mean()
            X.append([1, w, w * n, n]); y.append(lag); meta.append((name, P, w, n))
    X, y = np.array(X, float), np.array(y, float)
    coef = np.linalg.lstsq(X, y, rcond=None)[0]
    s_fast = float(np.mean([measured_rows(runs, "s00_8", P)[0][0] for P in (4, 8, 16)]))
    full = [*coef.tolist(), s_fast]
    out = {"coef": dict(zip(["a", "b", "c0", "c1", "s_fast"], full)), "fast_words": FAST, "fit": [], "check": []}
    print("S(w,n) = %.1f + %.2f*w + %.4f*w*n + %.4f*n   (fast path <= %d words: %.0f)" % (*coef, FAST, s_fast))
    for (name, P, w, n), yy, xx in zip(meta, y, X):
        pr = float(xx @ coef)
        out["fit"].append({"name": name, "P": P, "w": w, "n": n, "meas": yy, "pred": pr})
        print(f"  fit   {name:12s} P={P:2d} w={w:2d} n={n:4d}: meas {yy:7.0f} law {pr:7.0f} ({pr - yy:+6.0f})")
    for P in (4, 8, 16):
        fam = seqs(P)
        for name in MULTI:
            m = measured_rows(runs, name, P)
            if m is None:
                continue
            pl = row_stalls(fam[name], P, full, "main"); pe = row_stalls(fam[name], P, full, "timer")
            err = float(np.abs(pl - m[0]).max()); erre = float(np.abs(pe - m[1]).max())
            out["check"].append({"name": name, "P": P, "max_abs_err_main": err, "max_abs_err_enable": erre,
                                 "meas_main": m[0].round().tolist(), "law_main": pl.round().tolist()})
            print(f"  check {name:12s} P={P:2d}: max|law-meas| main {err:6.0f}  enable {erre:6.0f}   meas row0..2 {np.round(m[0][:3]).astype(int).tolist()} law {np.round(pl[:3]).astype(int).tolist()}")
    json.dump(out, open(LAW, "w"), indent=1)


def predict(seq, P):
    law = json.load(open(LAW))
    c = law["coef"]; full = [c["a"], c["b"], c["c0"], c["c1"], c["s_fast"]]
    return row_stalls(seq, P, full, "main"), row_stalls(seq, P, full, "timer")


if __name__ == "__main__":
    if sys.argv[1] == "fit":
        fit()
    else:
        L, E = predict(json.loads(sys.argv[2]), int(sys.argv[3]))
        print("main lag by row:", np.round(L).astype(int).tolist()); print("enable lag by row:", np.round(E).astype(int).tolist())
