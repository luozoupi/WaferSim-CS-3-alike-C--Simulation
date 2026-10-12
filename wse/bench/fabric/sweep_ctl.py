#!/usr/bin/env python3
"""Stage 1 / M1 Addendum A: traced simfab sweep of the switch-advance / teardown families -> results/fabric_m1_ctl.jsonl.
Per kernel tile and colour: sorted injection cycles (ramp records) and arrival cycles (link records), data and control
wavelets separately; plus the 16 pe_ctl.csl stamps of every PE with a role."""
import gzip, json, os, subprocess, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cases import addendum_a, tag
from gen import build_ctl
OUT = os.path.join(HERE, "../../stage1/results/fabric_m1_ctl.jsonl")
LINK = {0: "E", 1: "N", 2: "W", 3: "S"}


def observe(d, W, H):
    """{"x,y,c": {"inj": [...], "arr": [...], "kinj": [...], "karr": [...]}} (first record per wavelet per tile)"""
    first = {}
    for l in gzip.open(os.path.join(d, "events.jsonl.gz"), "rt"):
        e = json.loads(l)
        if e["event_type"] != "wavelet_trace_entry":
            continue
        c = e["coordinates"]["simulator"]; x, y = c["x"] - 4, c["y"] - 1
        if not (0 <= x < W and 0 <= y < H):
            continue
        f = e["raw"]["fields"]; r = e["raw"]
        ramp = (f >> 10) & 1; ctrl = (f >> 5) & 1
        k = (x, y, f & 0x1F, r["ident"])
        if k not in first or r["cycle"] < first[k][0]:
            first[k] = (r["cycle"], ramp, ctrl)
    out = collections.defaultdict(lambda: {"inj": [], "arr": [], "kinj": [], "karr": []})
    for (x, y, col, _), (cyc, ramp, ctrl) in first.items():
        out[f"{x},{y},{col}"][("k" if ctrl else "") + ("inj" if ramp else "arr")].append(cyc)
    for v in out.values():
        for a in v.values():
            a.sort()
    return dict(out)


def main(filt):
    done = {json.loads(l)["tag"] for l in open(OUT)} if os.path.exists(OUT) else set()
    for c in addendum_a():
        t = tag(c)
        if t in done or (filt and not any(f in t for f in filt)):
            continue
        r = subprocess.run([os.path.join(HERE, "one.sh"), t, "1"], capture_output=True, text=True)
        if r.returncode:
            print(t, "FAILED", r.stdout[-300:], r.stderr[-300:], flush=True); continue
        d = os.path.join(HERE, "runs", t); s = build_ctl(c)
        obs = observe(d, s.W, s.H)
        st = json.load(open(os.path.join(d, "stamps.json")))["stamps"]
        rec = dict(c, tag=t, W=s.W, H=s.H, obs=obs, tsc={f"{x},{y}": st[y][x] for (x, y) in s.roles})
        open(OUT, "a").write(json.dumps(rec) + "\n")
        os.remove(os.path.join(d, "events.jsonl.gz"))
        print(t, "ok", {k: (v["arr"][-1] if v["arr"] else None) for k, v in obs.items()}, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
