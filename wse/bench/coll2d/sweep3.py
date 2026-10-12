#!/usr/bin/env python3
"""Stage-0c family B: concurrent x+y broadcasts at small and asymmetric counts -> ../../stage0/results/coll2d.jsonl"""
import json, os, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "../../stage0/results/coll2d.jsonl")
LOCK = "/tmp/xkernel_singularity.lock"
env = dict(os.environ); env["PATH"] = "/home/luo00466/cs_sdk:/home/luo00466/.local/opt/apptainer-1.5.3/bin:" + env["PATH"]
env["APPTAINERENV_SIMFAB_THREADS"] = "2"
done = {json.loads(l)["tag"] for l in open(OUT)}
CFG = []
for P in (4, 8, 16):
    for root in sorted({0, P // 2}):
        for c in (2, 4, 8, 32):                      # 16 already measured in 0b
            for mode in (0, 1, 2):
                CFG.append((P, root, mode, c, c))
        for cx, cy in ((64, 128), (128, 64), (4, 16), (16, 4)):
            CFG.append((P, root, 2, cx, cy))
        CFG.append((P, root, 0, 128, 128)); CFG.append((P, root, 1, 128, 128))   # single-direction at 128
for P, root, mode, cx, cy in CFG:
    tag = f"P{P}_m{mode}_r{root}_c{cx}" + (f"_y{cy}" if cy != cx else "")
    if tag in done:
        continue
    out = f"out_{tag}"
    subprocess.run(["flock", LOCK, "cslc", "--arch=wse3", "./layout.csl", f"--fabric-dims={P + 7},{P + 2}",
                    "--fabric-offsets=4,1", f"--params=P:{P},MODE:{mode},COUNT:{cx},ROOT:{root},COUNTY:{cy}", "--memcpy",
                    "--channels=1", "-o", out], cwd=HERE, env=env, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.STDOUT)
    js = f"r_{tag}.json"
    r = subprocess.run(["flock", LOCK, "cs_python", "run.py", "--name", out, "--json", js], cwd=HERE, env=env,
                       capture_output=True, text=True)
    subprocess.run(["rm", "-rf", os.path.join(HERE, out)])
    assert "SUCCESS" in r.stdout, r.stdout[-800:] + r.stderr[-800:]
    res = json.load(open(os.path.join(HERE, js))); res["tag"] = tag; os.remove(os.path.join(HERE, js))
    open(OUT, "a").write(json.dumps(res) + "\n"); print(tag, res["op_only"], flush=True)
