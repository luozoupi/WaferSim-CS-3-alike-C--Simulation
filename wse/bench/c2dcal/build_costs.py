#!/usr/bin/env python3
"""Stage 1 Addendum D: cost table for the <collectives_2d> port from the calibration timelines (P = 12).
Key fields: kind | root position (first, mid, last) | PE class (root, first, last, lo, hi, guard) | parity.
Entries (value = a + b * count, from counts 4 and 24):
  cfg1|key          ts1 -> first FSM pass start, minus the ts2 read offset k (applied in the port)
  cfgn|key          op call issued from the callback task (reps = 2 rows; root first only)
  fsmpre|key|k      k-th FSM pass: start -> first async DSD issue (-1: no issue)
  fsmlen|key|k      k-th FSM pass length
  tdlen|key|k       k-th teardown-handler invocation length
  lock, done        f_lock and final callback lengths
Writes ../../stage1/results/c2d_costs.txt"""
import json, os, collections, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "../../stage1/results")
KIND = ["bcast", "scatter", "gather", "reduce"]


def rootpos(root, P):
    return "first" if root == 0 else "last" if root == P - 1 else "mid"


def pclass(x, root, P, kind):
    if x == root:
        return "root"
    if x == 0:
        return "first"
    if x == P - 1:
        return "last"
    if kind == "gather" and x == root + 1:
        return "guard"
    return "lo" if x < root else "hi"


def lsq(pts):
    """value = a + b*count + c*P by least squares over (count, P, value) medians (c = 0 with one P)"""
    import numpy as np
    A = np.array([[1.0, c, p] for c, p, v in pts]); y = np.array([v for c, p, v in pts])
    cols = [0] + ([1] if len({c for c, p, v in pts}) > 1 else []) + ([2] if len({p for c, p, v in pts}) > 1 else [])
    sol = np.linalg.lstsq(A[:, cols], y, rcond=None)[0]
    out = [0.0, 0.0, 0.0]
    for i, k in enumerate(cols):
        out[k] = float(sol[i])
    return out


def main():
    import sys
    Ps = [int(x) for x in (sys.argv[1].split(",") if len(sys.argv) > 1 else ["12"])]
    vals = collections.defaultdict(lambda: collections.defaultdict(list))   # entry -> (count, P) -> [values]
    for P in Ps:
      T = json.load(open(os.path.join(RES, "c2dcal_timeline.json" if P == 12 else f"c2dcal_timeline_P{P}.json")))
      for r in T:
          kind = KIND[r["op"]]; rp = rootpos(r["root"], P)
          for pe in r["pes"]:
              key = f"{kind}|{rp}|{pclass(pe['x'], r['root'], P, kind)}|{pe['x'] % 2}"
              seq = pe["seq"]; st = pe["stamps"]; c = (r["count"], P)
              dones = [v for v in seq if v["task"] == "done"]
              if r["reps"] == 1:
                  f1 = next(v for v in seq if v["task"] == "fsm")
                  vals[f"cfg1|{key}"][c].append(f1["t"] - (dones[-1]["t"] - (st[2] - st[1])))
                  fs = [v for v in seq if v["task"] == "fsm"]; tds = [v for v in seq if v["task"] == "td"]
                  for k, v in enumerate(fs):
                      vals[f"fsmpre|{key}|{k}"][c].append(v["issue"][0] if v["issue"] else -1)
                      vals[f"fsmlen|{key}|{k}"][c].append(v["len"])
                  for k, v in enumerate(tds):
                      vals[f"tdlen|{key}|{k}"][c].append(v["len"])
                  for v in seq:
                      if v["task"] == "lock":
                          vals["lock"][c].append(v["len"])
                  vals["done"][c].append(dones[-1]["len"])
              else:
                  vals[f"cfgn|{key}"][c].append(dones[0]["len"] - dones[-1]["len"])
    lines = []
    for e, byc in sorted(vals.items()):
        pts = [(c, p, statistics.median(v)) for (c, p), v in byc.items()]
        if e.startswith("fsmpre") and any(v == -1 for c, p, v in pts):
            a, b, cP = -1.0, 0.0, 0.0
        else:
            a, b, cP = lsq(pts)
        lines.append(f"{e} {a:.3f} {b:.5f} {cP:.5f}")
    name = "c2d_costs.txt" if Ps == [12] else "c2d_costs_" + "_".join(map(str, Ps)) + ".txt"
    open(os.path.join(RES, name), "w").write("\n".join(lines) + "\n")
    print(len(lines), "entries ->", os.path.join(RES, name))


if __name__ == "__main__":
    main()
