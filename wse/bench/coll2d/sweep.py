#!/usr/bin/env python3
"""coll2d sweep (post-hoc Stage-0 diagnostic of SUMMA's per-step gap) -> ../../stage0/results/coll2d.jsonl"""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "../../stage0/results/coll2d.jsonl")
LOCK = "/tmp/xkernel_singularity.lock"
env = dict(os.environ)
env["PATH"] = "/home/luo00466/cs_sdk:/home/luo00466/.local/opt/apptainer-1.5.3/bin:" + env["PATH"]
env["APPTAINERENV_SIMFAB_THREADS"] = "2"
done = {json.loads(l)["tag"] for l in open(OUT)} if os.path.exists(OUT) else set()
CFG = [(P, root, mode, 196) for P in (4, 8, 16) for root in sorted({0, P // 2, P - 1}) for mode in (0, 1, 2)]
CFG += [(P, root, mode, c) for P in (4, 8, 16) for root in sorted({0, P // 2}) for mode in (0, 1, 2) for c in (1, 16, 64, 512)]
for P, root, mode, c in CFG:
            tag = f"P{P}_m{mode}_r{root}_c{c}"
            if tag in done:
                continue
            out = f"out_{tag}"
            subprocess.run(["flock", LOCK, "cslc", "--arch=wse3", "./layout.csl", f"--fabric-dims={P + 7},{P + 2}",
                            "--fabric-offsets=4,1", f"--params=P:{P},MODE:{mode},COUNT:{c},ROOT:{root}", "--memcpy",
                            "--channels=1", "-o", out], cwd=HERE, env=env, check=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.STDOUT)
            js = f"r_{tag}.json"
            r = subprocess.run(["flock", LOCK, "cs_python", "run.py", "--name", out, "--json", js], cwd=HERE, env=env,
                               capture_output=True, text=True)
            assert "SUCCESS" in r.stdout, r.stdout[-1500:] + r.stderr[-1500:]
            res = json.load(open(os.path.join(HERE, js))); res["tag"] = tag
            subprocess.run(["rm", "-rf", os.path.join(HERE, out)])
            open(OUT, "a").write(json.dumps(res) + "\n")
            print(tag, res["op_only"], res["init_max"], flush=True)
