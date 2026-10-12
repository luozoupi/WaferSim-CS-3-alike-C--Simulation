#!/usr/bin/env python3
"""Stage 1 / M1: traced simfab sweep of all fabric cases; extracts per-wavelet router timing -> results/fabric_m1.jsonl"""
import gzip, json, os, subprocess, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cases import all_cases, tag
from gen import build
OUT = os.path.join(HERE, "../../stage1/results/fabric_m1.jsonl")
os.makedirs(os.path.dirname(OUT), exist_ok=True)
LINK = {0: "E", 1: "N", 2: "W", 3: "S"}


def wavelets(d, W, H):
    """{colour: {ident: [(cycle, x, y, link, ctrl)]}} for kernel tiles"""
    out = collections.defaultdict(lambda: collections.defaultdict(list))
    for l in gzip.open(os.path.join(d, "events.jsonl.gz"), "rt"):
        e = json.loads(l)
        if e["event_type"] != "wavelet_trace_entry":
            continue
        c = e["coordinates"]["simulator"]; x, y = c["x"] - 4, c["y"] - 1
        if not (0 <= x < W and 0 <= y < H):
            continue
        f = e["raw"]["fields"]; r = e["raw"]
        out[f & 0x1F][r["ident"]].append((r["cycle"], x, y, "R" if (f >> 10) & 1 else LINK[(f >> 8) & 3], (f >> 5) & 1))
    return out


def metrics(c, s, wav):
    """per destination (tile, colour): first/last arrival; per source: first/last injection"""
    res = {"src": {}, "dst": {}}
    for (x, y), r in s.roles.items():
        if r["send_n"] and r["send_c"] in wav:
            inj = [min(o for o in obs if o[1] == x and o[2] == y and o[3] == "R")[0]
                   for obs in wav[r["send_c"]].values() if any(o[1] == x and o[2] == y and o[3] == "R" for o in obs)]
            if inj:
                res["src"][f"{x},{y},{r['send_c']}"] = [min(inj), max(inj), len(inj)]
        for col, n in r["recv"]:
            arr = [min(o[0] for o in obs if o[1] == x and o[2] == y) for obs in wav.get(col, {}).values()
                   if any(o[1] == x and o[2] == y for o in obs)]
            if arr:
                res["dst"][f"{x},{y},{col}"] = [min(arr), max(arr), len(arr)]
    return res


def main(filt):
    done = {json.loads(l)["tag"] for l in open(OUT)} if os.path.exists(OUT) else set()
    for c in all_cases():
        t = tag(c)
        if t in done or (filt and not any(f in t for f in filt)):
            continue
        r = subprocess.run([os.path.join(HERE, "one.sh"), t, "1"], capture_output=True, text=True)
        if r.returncode:
            print(t, "FAILED", r.stdout[-300:], r.stderr[-300:], flush=True); continue
        d = os.path.join(HERE, "runs", t); s = build(c)
        m = metrics(c, s, wavelets(d, s.W, s.H))
        st = json.load(open(os.path.join(d, "stamps.json")))["stamps"]
        rec = dict(c, tag=t, W=s.W, H=s.H, **m,
                   tsc={f"{x},{y}": st[y][x] for (x, y) in s.roles if s.roles[(x, y)]["send_n"] or s.roles[(x, y)]["recv"]})
        open(OUT, "a").write(json.dumps(rec) + "\n")
        os.remove(os.path.join(d, "events.jsonl.gz"))
        print(t, "src", m["src"], "dst", m["dst"], flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
