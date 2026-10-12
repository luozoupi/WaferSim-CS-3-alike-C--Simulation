#!/usr/bin/env python3
"""Stage 1 Addendum F: predictions for the Stage 0 regression suite with the Stage 1 engine (kersim) and frozen
profiles (profile_m1 fabric + profile_m5e collectives/PE).  Kernel constants and launch state exactly as Stage 0c's
S0c predictor (s0c_predict.cases(), launch_law2).  Writes results/m5f_pred.json."""
import json, os, re, subprocess, sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__)); S0 = os.path.join(HERE, "../stage0")
sys.path.insert(0, S0)
import s0c_predict, launch_law2
SCR = os.environ.get("SCR", tempfile.gettempdir())
PROFILE = os.environ.get("PROFILE", "profile_m5e.txt"); OUTF = os.environ.get("OUT", "results/m5f_pred.json")
prof = [kv if not kv.startswith("costs=") else "costs=" + os.path.join(HERE, kv[6:]) for kv in open(os.path.join(HERE, PROFILE)).read().split()]


def D(defs, k, dflt):
    m = re.search(r"-D" + k + r"=(-?\d+)", defs)
    return int(m.group(1)) if m else dflt


def args_for(name, P, k, defs, tt):
    if k == 5:
        return ["kernel=gemv", f"MT={D(defs, 'GEMV_MT', 8)}", f"NT={D(defs, 'GEMV_NT', 4)}", f"C0={D(defs, 'GEMV_C0', 107)}",
                f"C1={D(defs, 'GEMV_C1', 101)}", f"KI={D(defs, 'K_INIT', 123)}", f"TIC={D(tt, 'TT_TIC', 0)}", f"TOC={D(tt, 'TT_TOC', 0)}"]
    if k == 6:
        w = D(defs, "GEMM_W", 196)
        return ["kernel=summa", f"WX={D(defs, 'GEMM_WX', w)}", f"WY={D(defs, 'GEMM_WY', w)}", f"SC={D(defs, 'SUMMA_C', 11904)}", f"KI={D(defs, 'K_INIT', 25)}"]
    if k == 8:
        return ["kernel=t2", f"CH={D(defs, 'T2_CHUNK', 3)}", "KIX=86", "KIY=79", "RPC=206"]
    if k == 9:
        return ["kernel=u4", f"CNT={D(defs, 'AR_COUNT', 8)}", f"KIX={D(defs, 'K_INIT_X', 124)}", f"KIY={D(defs, 'K_INIT_Y', 124)}"]
    raise ValueError(k)


def run(c):
    name, P, k, defs, tt, seq, entry, probe = c
    L, E = launch_law2.predict(seq, P, entry)
    lsf = os.path.join(SCR, f"ls_{name}_{P}.txt")
    open(lsf, "w").write("".join(f"{l} {e}\n" for l, e in zip(L, E)))
    out = subprocess.run([os.path.join(HERE, "kersim"), f"P={P}", f"ls={lsf}"] + args_for(name, P, k, defs, tt) + prof,
                         capture_output=True, text=True).stdout
    d = json.loads(out)
    return f"{name}/P{P}", ({kk: d[kk] for kk in ("cs", "x", "y") if kk in d} if d["ok"] else None)


cs = list(s0c_predict.cases())
with ThreadPoolExecutor(16) as ex:
    res = dict(ex.map(run, cs))
json.dump({"profile": " ".join(prof), "predictions": res}, open(os.path.join(HERE, OUTF), "w"), indent=1)
print(len(res), "cases; failed:", [k for k, v in res.items() if v is None])
