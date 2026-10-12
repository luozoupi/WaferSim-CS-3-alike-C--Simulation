#!/usr/bin/env python3
"""Stage 1 Addendum G: x2. / y. cost entries from the 2D calibration traces (P = 24, both modules initialised).
Per PE: main = longest task-1 invocation before the first x FSM pass; x phase = invocations up to the x callback
(task 10); y phase = invocations after it up to the y callback (task 11).  Entries (a + b*count + c*P, with c taken
from the x-dimension table of Addendum E):
  x2.cfg1|key, x2.fsmpre|key|k, x2.fsmlen|key|k, x2.tdlen|key|k      (x-ops, other module initialised)
  y.cfgn|key,  y.fsmpre|key|k,  y.fsmlen|key|k,  y.tdlen|key|k       (y-ops, chained from the x callback)
Also writes the validation inputs: results/c2dcal2d_val.json (per-PE launch times, stamp windows, init)."""
import gzip, json, os, sys, collections, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "../../stage1/results")
sys.path.insert(0, os.path.join(HERE, "../c2dcal"))
from analyze_cal import invocations   # noqa: E402
from build_costs import rootpos, pclass, KIND   # noqa: E402


def main():
    d = json.load(gzip.open(os.path.join(RES, "c2dcal2d.json.gz"), "rt"))
    P = d["P"]; print("discarded events:", d["discarded"])
    base = {}
    for l in open(os.path.join(RES, "c2d_costs_12_40.txt")):
        k, a, b, c = l.split(); base[k] = (float(a), float(b), float(c))
    vals = collections.defaultdict(lambda: collections.defaultdict(list))
    bad = 0; launch = {}; st = {}
    for pe in d["pes"]:
        x, y = pe["x"], pe["y"]; xc, yc = pe["xcfg"], pe["ycfg"]
        inv = invocations(pe["disp"])
        f0 = next((i for i, v in enumerate(inv) if v["task"] == 14), None)
        if f0 is None:
            bad += 1; continue
        mi = max(range(f0), key=lambda i: inv[i]["n"]); t0 = inv[mi]["start"]
        seq = [v for v in inv[f0:] if v["task"] in (14, 15, 16, 17, 29, 10, 11)]
        try:
            ix = next(i for i, v in enumerate(seq) if v["task"] == 10)
            iy = next(i for i, v in enumerate(seq) if v["task"] == 11 and i > ix)
        except StopIteration:
            bad += 1; continue
        xs, ys = seq[:ix], seq[ix + 1:iy]; xd, yd = seq[ix], seq[iy]
        s = pe["stamps"]; launch[(x, y)] = t0; st[(x, y)] = s
        xk = f"{KIND[xc['op']]}|{rootpos(xc['root'], P)}|{pclass(x, xc['root'], P, KIND[xc['op']])}|{x % 2}"
        yk = f"{KIND[yc['op']]}|{rootpos(yc['root'], P)}|{pclass(y, yc['root'], P, KIND[yc['op']])}|{y % 2}"
        fx = [v for v in xs if v["task"] == 14]; tx = [v for v in xs if v["task"] == 29]
        fy = [v for v in ys if v["task"] == 16]; ty = [v for v in ys if v["task"] == 29]
        cx, cy = xc["count"], yc["count"]
        vals[f"x2.cfg1|{xk}"][cx].append(fx[0]["start"] - (yd["start"] - (s[3] - s[1])))
        for k, v in enumerate(fx):
            vals[f"x2.fsmpre|{xk}|{k}"][cx].append((v["issue"][0] - v["start"]) if v["issue"] else -1)
            vals[f"x2.fsmlen|{xk}|{k}"][cx].append(v["end"] - v["start"] + 1)
        for k, v in enumerate(tx):
            vals[f"x2.tdlen|{xk}|{k}"][cx].append(v["end"] - v["start"] + 1)
        vals[f"y.cfgn|{yk}"][cy].append((xd["end"] - xd["start"] + 1) - (yd["end"] - yd["start"] + 1))
        for k, v in enumerate(fy):
            vals[f"y.fsmpre|{yk}|{k}"][cy].append((v["issue"][0] - v["start"]) if v["issue"] else -1)
            vals[f"y.fsmlen|{yk}|{k}"][cy].append(v["end"] - v["start"] + 1)
        for k, v in enumerate(ty):
            vals[f"y.tdlen|{yk}|{k}"][cy].append(v["end"] - v["start"] + 1)
    print("PEs used", len(launch), "incomplete", bad)
    lines = open(os.path.join(RES, "c2d_costs_12_40.txt")).read().splitlines()
    n = 0
    for e, byc in sorted(vals.items()):
        med = {c: statistics.median(v) for c, v in byc.items()}
        cP = base.get(e.split(".", 1)[1], (0, 0, 0))[2]
        if e.split(".", 1)[1].startswith("fsmpre") and any(v == -1 for v in med.values()):
            a, b, cP = -1.0, 0.0, 0.0
        elif 4 in med and 24 in med:
            b = (med[24] - med[4]) / 20.0; a = med[4] - 4 * b - cP * P
        else:
            b = 0.0; a = list(med.values())[0] - cP * P
        lines.append(f"{e} {a:.3f} {b:.5f} {cP:.5f}"); n += 1
    open(os.path.join(RES, "c2d_costs_G.txt"), "w").write("\n".join(lines) + "\n")
    print(n, "prefixed entries ->", os.path.join(RES, "c2d_costs_G.txt"))
    # validation inputs: launch times from the trace, windows from the stamps (local frames)
    ts0 = [s[0] for s in st.values()]
    print("ts0 spread (local frames):", min(ts0), max(ts0))
    wx = [max(st[(x, y)][2] for x in range(P)) - min(st[(x, y)][1] for x in range(P)) for y in range(P)]
    wy = [max(st[(x, y)][3] for y in range(P)) - min(st[(x, y)][2] for y in range(P)) for x in range(P)]
    init = statistics.median(s[1] - s[0] for s in st.values())
    json.dump({"P": P, "launch": [launch[(x, y)] for y in range(P) for x in range(P)], "wx": wx, "wy": wy, "init": init,
               "init_pe": [st[(x, y)][1] - st[(x, y)][0] for y in range(P) for x in range(P)]},
              open(os.path.join(RES, "c2dcal2d_val.json"), "w"))
    print("init (ts1-ts0) median", init, "| wx", wx[:6], "... | wy", wy[:6], "...")


if __name__ == "__main__":
    main()
