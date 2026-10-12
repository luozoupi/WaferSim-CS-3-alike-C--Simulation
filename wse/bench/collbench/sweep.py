#!/usr/bin/env python3
"""Stage-0 collectives microbenchmark sweep on simfab (WSE-3).

One <collectives_2d> op (or REPS chained ops) on a line of P PEs; device-internal stamps give
`total` (entry -> last callback, incl. init) and `op_only` (after init -> last callback).
Appends one JSON line per run to ../../stage0/results/collbench.jsonl.
usage: sweep.py [filter ...]   (filter matches the run tag)
"""
import json, os, re, shutil, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "../../stage0/results/collbench.jsonl")
LOCK = "/tmp/xkernel_singularity.lock"
OPS = {0: "bcast", 1: "scatter", 2: "gather", 3: "reduce"}

RUNS = []
for op in OPS:
    for P in (4, 8, 16, 32, 64):
        for cnt in (1, 8, 64):
            for root in ("first", "last"):
                RUNS.append(dict(op=op, P=P, count=cnt, root=root, dim=0, reps=1))
for op in OPS:                       # y-dimension spot checks (isotropy)
    for P in (8, 32):
        for root in ("first", "last"):
            RUNS.append(dict(op=op, P=P, count=8, root=root, dim=1, reps=1))
for op in OPS:                       # chained ops: per-op transition cost
    for P in (8, 32):
        RUNS.append(dict(op=op, P=P, count=8, root="first" if op in (0, 1) else "last", dim=0, reps=3))


def tag(r):
    return f"{OPS[r['op']]}_P{r['P']}_c{r['count']}_{r['root']}_{'xy'[r['dim']]}_r{r['reps']}"


def main(filters):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    done = set()
    if os.path.exists(OUT):
        done = {json.loads(l)["tag"] for l in open(OUT) if json.loads(l).get("total")}
    env = dict(os.environ)
    env["PATH"] = "/home/luo00466/cs_sdk:/home/luo00466/.local/opt/apptainer-1.5.3/bin:" + env["PATH"]
    env["APPTAINERENV_CSL_SUPPRESS_SIMFAB_TRACE"] = "1"
    env["APPTAINERENV_SIMFAB_THREADS"] = "2"
    for r in RUNS:
        t = tag(r)
        if t in done or (filters and not any(f in t for f in filters)):
            continue
        P, dim = r["P"], r["dim"]
        Pw, Ph = (P, 1) if dim == 0 else (1, P)
        root = 0 if r["root"] == "first" else P - 1
        rd = os.path.join(HERE, "runs", t)
        os.makedirs(rd, exist_ok=True)
        out = os.path.relpath(os.path.join(rd, "out"), HERE)
        t0 = time.time()
        with open(os.path.join(rd, "compile.log"), "w") as f:
            crc = subprocess.run(["flock", LOCK, "cslc", "--arch=wse3", "./layout.csl",
                                  f"--fabric-dims={Pw + 7},{Ph + 2}", "--fabric-offsets=4,1",
                                  f"--params=Pw:{Pw},Ph:{Ph},OP:{r['op']},DIM:{dim},COUNT:{r['count']},ROOT:{root},REPS:{r['reps']}",
                                  "--memcpy", "--channels=1", "-o", out],
                                 cwd=HERE, env=env, stdout=f, stderr=subprocess.STDOUT).returncode
        res = dict(r, tag=t, root_idx=root, compile_rc=crc)
        if crc == 0:
            js = os.path.join(rd, "result.json")
            with open(os.path.join(rd, "run.log"), "w") as f:
                rrc = subprocess.run(["flock", LOCK, "cs_python", "run.py", "--name", out, "--json",
                                      os.path.relpath(js, HERE)], cwd=HERE, env=env, stdout=f,
                                     stderr=subprocess.STDOUT).returncode
            res["run_rc"] = rrc
            if os.path.exists(js):
                res.update({k: v for k, v in json.load(open(js)).items() if k in ("total", "op_only", "init_max", "start_skew", "end_per_pe")})
            for fn in ("sim_stats.json", "simconfig.json", "sim.log"):
                if os.path.exists(os.path.join(HERE, fn)):
                    shutil.move(os.path.join(HERE, fn), os.path.join(rd, fn))
            shutil.rmtree(os.path.join(rd, "out"), ignore_errors=True)
        res["wall_s"] = time.time() - t0
        with open(OUT, "a") as f:
            f.write(json.dumps(res) + "\n")
        print(f"{t}: total={res.get('total')} op_only={res.get('op_only')} rc={crc}/{res.get('run_rc')} {res['wall_s']:.0f}s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
