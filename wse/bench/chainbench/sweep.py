#!/usr/bin/env python3
"""Stage-0b chain family: op1 -> op2 (op2 issued in op1's callback) on a line of P PEs -> ../../stage0/results/chain.jsonl
Excluded by pre-registration (T2's chains): bcast->reduce on x with roots (0,0); scatter->gather on y with roots (0,0)."""
import json, os, shutil, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "../../stage0/results/chain.jsonl")
LOCK = "/tmp/xkernel_singularity.lock"
OPS = {0: "bcast", 1: "scatter", 2: "gather", 3: "reduce"}
EXCL = {(0, 3, 0, "ff"), (1, 2, 1, "ff")}          # (op1, op2, dim, roots)
RUNS = []
for o1 in OPS:
    for o2 in OPS:
        for P in (8, 16):
            for rr in ("ff", "ll"):
                RUNS.append(dict(op=o1, op2=o2, P=P, count=8, roots=rr, dim=0))
        RUNS.append(dict(op=o1, op2=o2, P=8, count=64, roots="ff", dim=0))
        RUNS.append(dict(op=o1, op2=o2, P=8, count=8, roots="ff", dim=1))
RUNS = [r for r in RUNS if (r["op"], r["op2"], r["dim"], r["roots"]) not in EXCL]


def tag(r):
    return f"{OPS[r['op']]}-{OPS[r['op2']]}_P{r['P']}_c{r['count']}_{r['roots']}_{'xy'[r['dim']]}"


def main():
    env = dict(os.environ)
    env["PATH"] = "/home/luo00466/cs_sdk:/home/luo00466/.local/opt/apptainer-1.5.3/bin:" + env["PATH"]
    env["APPTAINERENV_CSL_SUPPRESS_SIMFAB_TRACE"] = "1"; env["APPTAINERENV_SIMFAB_THREADS"] = "2"
    done = {json.loads(l)["tag"] for l in open(OUT)} if os.path.exists(OUT) else set()
    for r in RUNS:
        t = tag(r)
        if t in done:
            continue
        P, dim = r["P"], r["dim"]
        Pw, Ph = (P, 1) if dim == 0 else (1, P)
        root = 0 if r["roots"][0] == "f" else P - 1
        root2 = 0 if r["roots"][1] == "f" else P - 1
        out = f"out_{t}"
        subprocess.run(["flock", LOCK, "cslc", "--arch=wse3", "./layout.csl", f"--fabric-dims={Pw + 7},{Ph + 2}",
                        "--fabric-offsets=4,1",
                        f"--params=Pw:{Pw},Ph:{Ph},OP:{r['op']},DIM:{dim},COUNT:{r['count']},ROOT:{root},REPS:2,OP2:{r['op2']},ROOT2:{root2}",
                        "--memcpy", "--channels=1", "-o", out], cwd=HERE, env=env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        js = f"r_{t}.json"
        rr = subprocess.run(["flock", LOCK, "cs_python", "run.py", "--name", out, "--json", js], cwd=HERE, env=env,
                            capture_output=True, text=True)
        shutil.rmtree(os.path.join(HERE, out), ignore_errors=True)
        if "SUCCESS" not in rr.stdout:
            print(t, "FAILED", rr.stdout[-500:], rr.stderr[-500:], flush=True); continue
        res = dict(r, tag=t, **{k: v for k, v in json.load(open(os.path.join(HERE, js))).items()
                                 if k in ("total", "op_only", "init_max", "start_skew", "end_per_pe")})
        os.remove(os.path.join(HERE, js))
        open(OUT, "a").write(json.dumps(res) + "\n")
        print(t, res["op_only"], flush=True)


if __name__ == "__main__":
    main()
