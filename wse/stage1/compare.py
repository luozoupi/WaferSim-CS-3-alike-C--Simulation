#!/usr/bin/env python3
"""Stage 1: fabric engine vs simfab on the M1 cases.  Primary metric per destination: last-wavelet arrival minus
the case's first injection (PREREGISTRATION gate 1).  usage: compare.py [key=value ...] [--role train|holdout] [--family f]"""
import json, os, subprocess, sys, statistics
import tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "../bench/fabric"))
from cases import tag as ctag
from gen import build, spec_text
SIM = os.path.join(HERE, "fabsim"); SCR = os.environ.get("SCR", tempfile.gettempdir())


def primary(m):
    t0 = min(v[0] for v in m["src"].values())
    return {k: v[1] - t0 for k, v in m["dst"].items()}, {k: v[0] - t0 for k, v in m["dst"].items()}


def run(case, kv):
    p = os.path.join(SCR, "spec.txt"); open(p, "w").write(spec_text(build(case)))
    return json.loads(subprocess.run([SIM, p] + kv, capture_output=True, text=True).stdout)


def main():
    args = sys.argv[1:]; kv = [a for a in args if "=" in a and not a.startswith("--")]
    role = args[args.index("--role") + 1] if "--role" in args else None
    fam = args[args.index("--family") + 1] if "--family" in args else None
    rows = [json.loads(l) for l in open(os.path.join(HERE, "results/fabric_m1.jsonl"))]
    errs = {}
    for r in rows:
        if (role and r["role"] != role) or (fam and r["family"] != fam):
            continue
        m = run(r, kv)
        last_s, first_s = primary(r); last_m, first_m = primary(m)
        for k in last_s:
            e = 100 * (last_m.get(k, 0) / last_s[k] - 1) if last_s[k] else 0
            errs.setdefault(r["family"], []).append((abs(e), r["tag"], k, last_s[k], last_m.get(k), first_s[k], first_m.get(k)))
    for f, es in errs.items():
        a = [e[0] for e in es]
        w = max(es)
        print(f"{f:12s} n={len(a):3d} median|e|={statistics.median(a):5.2f}% max|e|={w[0]:6.2f}% ({w[1]} {w[2]} simfab {w[3]} model {w[4]}; first {w[5]}/{w[6]})")


if __name__ == "__main__":
    main()
