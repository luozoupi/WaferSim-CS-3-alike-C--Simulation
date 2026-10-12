#!/usr/bin/env python3
"""Stage 0c predictions for the pre-registered test kernels (U1-U4) and regression kernels (GEMV, SUMMA, T1, T2).

  S0c        0b mechanisms + second-module teardown cost (TWO_MODULES) + launch law v2 (per-P table, local-entry
             offsets) + refitted P2_CPL + host tic/toc protocol (U1)                              -> gate
  S0c-probe  as S0c, launch state from probe replays of each host sequence (ablation)
  S0b        the Stage 0b mechanisms and constants applied to the same kernel descriptions (launch law v1, no
             second-module cost, P2 = 140, no tic/toc protocol)
  A0c        analytic composition (launch law v2 + op laws + coll2d overlap + chain transitions + second-module
             cost + tic/toc offsets)
usage: s0c_predict.py twin <predictor> | analytic
"""
import json, os, re, subprocess, sys, statistics
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
FORK = os.environ.get("CLONE") or os.path.abspath(os.path.join(HERE, "../.."))
RUNNER = "/mnt/data/luo00466/muchisim_eval/scripts/muchi_fft.sh"
OUT = os.path.join(HERE, os.environ.get("PRED_OUT", "results/s0c_predictions.json"))
BASE = "-DWSE_TWIN -DWSE_MCAST -DON_DIE_HOP_LAT=2 -DLAUNCH_X=2"
P2_0C = int(os.environ.get("P2_0C", "0")) or json.load(open(os.path.join(HERE, "results/s0c_p2.json")))["P2_CPL"]
FLAGS = {"S0c": f"-DS0B -DS0C -DS0_GATHER_TD -DWSE_GATES -DS0_GATES -DS0_PE -DTWO_MODULES -DP2_CPL={P2_0C} -DWSE_LAUNCH_STATE",
         "S0c-probe": f"-DS0B -DS0C -DS0_GATHER_TD -DWSE_GATES -DS0_GATES -DS0_PE -DTWO_MODULES -DP2_CPL={P2_0C} -DWSE_LAUNCH_STATE",
         "S0b": "-DS0B -DS0_GATHER_TD -DWSE_GATES -DS0_GATES -DS0_PE -DWSE_LAUNCH_STATE"}
T, M = ["timer", 1], ["main"]
one = lambda n: ["h2d", 0, 0, 1, 1, n, 1]
full = lambda n: ["h2d", 0, 0, "P", "P", n, 1]


def cases():
    TT = "-DTT_TIC=227 -DTT_TOC=207"
    for P in (4, 8, 16, 32, 64):
        g = [full(32), one(4 * P), one(8 * P), T, M]
        yield "U1", P, 5, "-DK_INIT=123", TT, g, "main", "gemv"
        yield "U2_32x16", P, 5, "-DK_INIT=123 -DGEMV_MT=32 -DGEMV_NT=16 -DGEMV_C0=1112 -DGEMV_C1=1094", "", \
            [full(512), one(16 * P), one(32 * P), T, M], "main", "U2_32x16"
        yield "U2_2x2", P, 5, "-DK_INIT=123 -DGEMV_MT=2 -DGEMV_NT=2 -DGEMV_C0=49 -DGEMV_C1=46", "", \
            [full(4), one(2 * P), one(2 * P), T, M], "main", "U2_2x2"
        for c in (8, 64):
            yield f"U4_c{c}", P, 9, f"-DAR_COUNT={c} -DK_INIT_X=124 -DK_INIT_Y=124", "", [full(c), T, M], "main", None
    for P in (4, 8, 16, 32):
        yield "U3_4x16x8", P, 6, "-DGEMM_WX=64 -DGEMM_WY=128 -DSUMMA_C=4846 -DK_INIT=25", "", [full(64), full(128), T, M], "main", None
        yield "U3_2x2x2", P, 6, "-DGEMM_WX=4 -DGEMM_WY=4 -DSUMMA_C=146 -DK_INIT=25", "", [full(4), full(4), T, M], "main", None
    for P in (16, 32, 64):   # regression (P >= 16 only)
        yield "GEMV", P, 5, "-DK_INIT=123", "", [full(32), one(4 * P), one(8 * P), T, M], "main", "gemv"
        yield "SUMMA", P, 6, "-DK_INIT=25", "", [["timer", 0], full(196), full(196), M], "main", None
        for ch in (3, 16):
            yield f"T2_c{ch}", P, 8, f"-DT2_CHUNK={ch}", "", [["h2d", 0, 0, 1, "P", ch * P, 0], ["h2d", 0, 0, "P", 1, ch * P, 0], T, M, M], "task", f"T2_c{ch}"
    for P in (16, 32):
        for t, comp in ((8, 2895), (4, 611)):
            yield f"T1_t{t}", P, 6, f"-DGEMM_W={t * t} -DSUMMA_C={comp} -DK_INIT=25", "", [full(t * t), full(t * t), T, M], "main", None


def write_header(P, L_rows, E_rows):
    L = [int(round(2 * x + L_rows[y])) for y in range(P) for x in range(P)]
    E = [int(round(2 * x + E_rows[y])) for y in range(P) for x in range(P)]
    with open(os.path.join(FORK, "src/apps/wse_launch_state.h"), "w") as f:
        f.write(f"#define LS_P {P}\nstatic const int ls_L[{P * P}] = {{{','.join(map(str, L))}}};\n")
        f.write(f"static const int ls_E[{P * P}] = {{{','.join(map(str, E))}}};\n")


def launch_rows(pred, seq, P, entry, probe):
    if pred == "S0b":
        import launch_law
        return launch_law.predict(seq, P)
    if pred == "S0c-probe" and probe:
        import launch_state
        st = launch_state.state(launch_state.load(), probe, P)
        if st is not None and st["l1"] is not None:
            L = st["l1"].mean(axis=1); E = st["eps1"].mean(axis=1)
            return L - L.min(), E - E.min()
    if pred == "S0c-probe" and not probe:
        return np.zeros(P), np.zeros(P)          # full-grid copies only: no relative lag (family C)
    import launch_law2
    return launch_law2.predict(seq, P, entry)


def twin(P, kernel, defs, name, threads):
    env = dict(os.environ, EXTRA_DEFS=f"{BASE} -DTWIN_KERNEL={kernel} {defs}", NICE="0")
    subprocess.run([RUNNER, FORK, str(P), str(threads), name, "0"], env=env, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    log = open(os.path.join(FORK, f"sim_logs/DATA-fft1--{P}-X-{P}--B{name}-A6.log")).read()
    g = lambda k: int(re.findall(k + r":\s*(-?[\d,]+)", log)[-1].replace(",", ""))
    return {"cs": g("TWIN_CS"), **({"x": g("TWIN_T2_X"), "y": g("TWIN_T2_Y")} if kernel == 8 else {})}


def run_twins(pred):
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for name, P, k, defs, tt, seq, entry, probe in cases():
        key = f"{name}/P{P}"
        r = res.setdefault(key, {})
        if pred in r:
            continue
        L, E = launch_rows(pred, seq, P, entry, probe)
        write_header(P, L, E)
        extra = tt if pred != "S0b" else ""
        th = 4 if (k == 6 and P >= 64) else 2
        r[pred] = twin(P, k, f"{FLAGS[pred]} {defs} {extra}", f"Q{pred[:3].replace('-', '')}{name[:6]}{P}", th)
        json.dump(res, open(OUT, "w"), indent=1)
        print(key, pred, r[pred], flush=True)


# ---------------- analytic control A0c ----------------
def analytic():
    import launch_law2
    from s0b_predict import law_T, chain_uv, coll2d_overlap
    laws = json.load(open(os.path.join(HERE, "results/laws.json")))["laws"]
    tr = chain_uv(); Q = 17
    BC, SC, GA, RE = 0, 1, 2, 3
    res = json.load(open(OUT)) if os.path.exists(OUT) else {}
    for name, P, k, defs, tt, seq, entry, probe in cases():
        key = f"{name}/P{P}"
        L, E = launch_law2.predict(seq, P, entry)
        D0 = float(L[0])
        if name.startswith(("U3", "T1", "SUMMA")):
            if name.startswith("U3"):
                cx, cy, comp = (64, 128, 4846) if "4x16" in name else (4, 4, 146)
            elif name.startswith("T1"):
                t = int(name[-1]); cx = cy = t * t; comp = 2895 if t == 8 else 611
            else:
                cx = cy = 196; comp = 11904
            tot = 50
            for s in range(P):
                side = "first" if s == 0 else "last"
                tot += (law_T(laws, f"bcast/{side}/x", P, cx) + law_T(laws, f"bcast/{side}/y", P, cy)
                        - coll2d_overlap(min(cx, cy)) + 2 * Q + comp)
            res.setdefault(key, {})["A0c"] = {"cs": tot}
        elif name.startswith("T2"):
            ch = int(name.split("c")[1]); Nx = ch * P
            x = 86 + law_T(laws, "bcast/first/x", P, Nx) + law_T(laws, "reduce/first/x", P, Nx) + tr(BC, RE) + 3 * Q
            y = D0 + 79 + law_T(laws, "scatter/first/y", P, ch) + law_T(laws, "gather/first/y", P, ch) + tr(SC, GA) + 2 * Q
            res.setdefault(key, {})["A0c"] = {"x": x, "y": y}
        elif name.startswith("U4"):
            c = int(name.split("c")[1])
            a = 248 + 2 * (law_T(laws, "reduce/last/x", P, c) + law_T(laws, "bcast/last/x", P, c) + tr(RE, BC) + 3 * Q)
            res.setdefault(key, {})["A0c"] = {"cs": a}
        else:   # GEMV family: U1, U2, GEMV
            mt, nt, c0 = (32, 16, 1112) if "32x16" in name else (2, 2, 49) if "2x2" in name else (8, 4, 107)
            a = (124 + 122 + law_T(laws, "scatter/first/y", P, mt) + law_T(laws, "scatter/first/x", P, nt)
                 + law_T(laws, "bcast/first/y", P, nt) + c0 + law_T(laws, "reduce/last/x", P, mt)
                 + law_T(laws, "gather/last/y", P, mt) + 6 * Q + D0 + (227 + 207 if name == "U1" else 0))
            res.setdefault(key, {})["A0c"] = {"cs": a}
    json.dump(res, open(OUT, "w"), indent=1)
    print("A0c written for", len(res), "cases")


if __name__ == "__main__":
    if sys.argv[1] == "twin":
        run_twins(sys.argv[2])
    else:
        analytic()
