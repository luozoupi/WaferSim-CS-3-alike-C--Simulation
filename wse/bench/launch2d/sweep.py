#!/usr/bin/env python3
"""Stage-0b launch-probe family (calibration data for the launch law) -> ../../stage0/results/launch2d.jsonl
Test-kernel host sequences are NOT in this family (see PREREGISTRATION_0b.md)."""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
PROBE4 = os.environ.get("PROBE4", "1") == "1"      # four-direction probe (pe4.csl), default
OUT = os.path.join(HERE, "../../stage0/results/launch4.jsonl" if PROBE4 else "../../stage0/results/launch2d.jsonl")
LOCK = "/tmp/xkernel_singularity.lock"


def family(P):
    """v2 (probe unblocks immediately).  name -> (sequence, probe directions)"""
    m = P // 2
    T, M = ["timer", 1], ["main"]
    one = lambda x, y, n, b=1: ["h2d", x, y, 1, 1, n, b]
    row = lambda y, n, b=1: ["h2d", 0, y, "P", 1, n, b]
    col = lambda x, n, b=1: ["h2d", x, 0, 1, "P", n, b]
    full = lambda n, b=1: ["h2d", 0, 0, "P", "P", n, b]
    SN, ALL = (1, 3), (0, 1, 2, 3)
    f = {
        "base": ([T, M, M], ALL),
        "gemv": ([full(32), one(0, 0, 4 * P), one(0, 0, 8 * P), T, M, M], ALL),
        "full_8": ([full(8), T, M, M], SN), "full_256": ([full(256), T, M, M], SN),
        "col0_8": ([col(0, 8), T, M, M], ALL), "col0_256": ([col(0, 256), T, M, M], SN),
        "sP0_64": ([one(P - 1, 0, 64), T, M, M], ALL),
        "s0P_64": ([one(0, P - 1, 64), T, M, M], SN), "smid_64": ([one(m, m, 64), T, M, M], SN),
        "rowmid_64": ([row(m, 64), T, M, M], SN), "rowP_64": ([row(P - 1, 64), T, M, M], SN),
        "disj_64": ([one(0, 0, 64), one(0, 1, 64), T, M, M], SN),
        "add3_64": ([full(256), one(0, 0, 64), one(0, 0, 64), one(0, 0, 64), T, M, M], SN),
        "tbetween_256": ([one(0, 0, 256), T, one(0, 0, 256), M, M], SN),
        "resync00": ([one(0, 0, 256), ["d2h", 0, 0, 1, 1, 1], T, M, M], SN),
        "resync01": ([one(0, 0, 256), ["d2h", 0, 1, 1, 1, 1], T, M, M], SN),
        "nb_s00_256": ([one(0, 0, 256, 0), T, M, M], SN), "nb_row0_64": ([row(0, 64, 0), T, M, M], SN),
        "tfirst_s00_256": ([["timer", 0], one(0, 0, 256), M, M], SN),
        "tfirst_full_256x2": ([["timer", 0], full(256), full(256), M, M], SN),
    }
    for n in (8, 64, 256, 1024):
        f[f"s00_{n}"] = ([one(0, 0, n), T, M, M], SN)
    for n in (8, 64, 256):
        f[f"row0_{n}"] = ([row(0, n), T, M, M], SN)
    return f


def test_family(P):
    """test-kernel host sequences replayed by the probe (S0b-probe ablation only; never used by the launch law)"""
    T, M = ["timer", 1], ["main"]
    full = lambda n, b=1: ["h2d", 0, 0, "P", "P", n, b]
    f = {}
    for t in (8, 4):
        f[f"T1_t{t}"] = ([full(t * t), full(t * t), T, M], (1, 3))
    for ch in (3, 16):
        f[f"T2_c{ch}"] = ([["h2d", 0, 0, 1, "P", ch * P, 0], ["h2d", 0, 0, "P", 1, ch * P, 0], T, M, M], (1, 3))
    return f


def family_c(P):
    """Stage-0c family C: large-P launch stalls (single-PE copies, additivity, row copy, GEMV-like)"""
    T, M = ["timer", 1], ["main"]
    one = lambda x, y, n, b=1: ["h2d", x, y, 1, 1, n, b]
    full = lambda n, b=1: ["h2d", 0, 0, "P", "P", n, b]
    SN = (1, 3)
    return {"base": ([T, M, M], SN), "s00_64": ([one(0, 0, 64), T, M, M], SN), "s00_256": ([one(0, 0, 256), T, M, M], SN),
            "s00_1024": ([one(0, 0, 1024), T, M, M], SN), "add2_256": ([one(0, 0, 256), one(0, 0, 256), T, M, M], SN),
            "row0_64": ([["h2d", 0, 0, "P", 1, 64, 1], T, M, M], SN),
            "gemv": ([full(32), one(0, 0, 4 * P), one(0, 0, 8 * P), T, M, M], SN)}


def family_c2(P):
    """Stage-0c family C2: within-row lag of column copies (four-direction probes), plus T2-sequence replays"""
    T, M = ["timer", 1], ["main"]
    ALL = (0, 1, 2, 3)
    f = {"base": ([T, M, M], ALL)}
    for n in (8, 64, 256, 1024):
        f[f"col0_{n}"] = ([["h2d", 0, 0, 1, "P", n, 1], T, M, M], ALL)
    f["colmid_64"] = ([["h2d", P // 2, 0, 1, "P", 64, 1], T, M, M], ALL)
    for ch in (3, 16):
        f[f"T2_c{ch}"] = ([["h2d", 0, 0, 1, "P", ch * P, 0], ["h2d", 0, 0, "P", 1, ch * P, 0], T, M, M], ALL)
    return f


def test_family_0c(P):
    """Stage-0c test host-sequence replays (S0c-probe ablation only; never used by the launch law): U2 blocks"""
    T, M = ["timer", 1], ["main"]
    one = lambda n: ["h2d", 0, 0, 1, 1, n, 1]
    full = lambda n: ["h2d", 0, 0, "P", "P", n, 1]
    return {"U2_32x16": ([full(512), one(16 * P), one(32 * P), T, M, M], (1, 3)),
            "U2_2x2": ([full(4), one(2 * P), one(2 * P), T, M, M], (1, 3))}


def main(Ps, only):
    env = dict(os.environ)
    env["PATH"] = "/home/luo00466/cs_sdk:/home/luo00466/.local/opt/apptainer-1.5.3/bin:" + env["PATH"]
    done = {json.loads(l)["tag"] for l in open(OUT)} if os.path.exists(OUT) else set()
    for P in Ps:
        env["APPTAINERENV_SIMFAB_THREADS"] = "8" if P >= 64 else "2"
        env["APPTAINERENV_NWORDS"] = "16" if PROBE4 else "18"
        fam = (test_family(P) if os.environ.get("TEST_REPLAY") == "1" else
               family_c(P) if os.environ.get("FAMILY_C") == "1" else
               family_c2(P) if os.environ.get("FAMILY_C2") == "1" else
               test_family_0c(P) if os.environ.get("TEST_0C") == "1" else family(P))
        for d in ((0, 1, 2, 3) if PROBE4 else (0, 1)):
            out = f"out4_P{P}_d{d}" if PROBE4 else f"out_P{P}_d{d}"
            if not os.path.isdir(os.path.join(HERE, out)):
                subprocess.run(["flock", LOCK, "cslc", "--arch=wse3", "./layout4.csl" if PROBE4 else "./layout.csl", f"--fabric-dims={P + 7},{P + 2}",
                                "--fabric-offsets=4,1", f"--params=Pw:{P},Ph:{P},DIR:{d}", "--memcpy", "--channels=1",
                                "-o", out], cwd=HERE, env=env, check=True, stdout=subprocess.DEVNULL)
            for name, (seq, dirs) in fam.items():
                tag = f"{name}_P{P}_d{d}"
                if tag in done or (only and name not in only) or d not in dirs:
                    continue
                env["APPTAINERENV_SEQ"] = json.dumps(seq)
                js = f"tmp_{tag}.json"
                r = subprocess.run(["flock", LOCK, "cs_python", "run.py", "--name", out, "--json", js], cwd=HERE,
                                   env=env, capture_output=True, text=True)
                if "SUCCESS" not in r.stdout:
                    print(tag, "FAILED", r.stdout[-800:], r.stderr[-800:], flush=True); continue
                res = json.load(open(os.path.join(HERE, js))); os.remove(os.path.join(HERE, js))
                res.update(tag=tag, name=name, P=P, dir=d)
                open(OUT, "a").write(json.dumps(res) + "\n")
                print(tag, "ok", flush=True)


if __name__ == "__main__":
    Ps = [int(a) for a in sys.argv[1:] if a.isdigit()] or [4, 8, 16]
    only = [a for a in sys.argv[1:] if not a.isdigit()]
    main(Ps, only)
