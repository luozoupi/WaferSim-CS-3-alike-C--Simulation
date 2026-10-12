#!/usr/bin/env python3
"""Stage 1 Addendum G: validation of the x2./y. entries on the 2D calibration windows and residual fit of the two
pre-registered scalars (td2x, dcy) on those windows only.  Launch times from the trace (input); init = measured
calibration-program init (input); everything else from profile_m5e.txt with the G cost table."""
import json, os, subprocess, sys, statistics, itertools
import tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
V = json.load(open(os.path.join(HERE, "results/c2dcal2d_val.json"))); P = V["P"]
SCR = os.environ.get("SCR", tempfile.gettempdir())
lsx = os.path.join(SCR, "lsx_cal2d.txt"); open(lsx, "w").write("".join(f"{l} {l} {i}\n" for l, i in zip(V["launch"], V["init_pe"])))
prof = [kv for kv in open(os.path.join(HERE, "profile_m5e.txt")).read().split() if not kv.startswith("costs=")]
prof += ["costs=" + os.path.join(HERE, os.environ.get("COSTS", "results/c2d_costs_G.txt"))]


def run(td2x, dcy):
    o = subprocess.run([os.path.join(HERE, "kersim"), "kernel=cal2d", f"P={P}", f"lsx={lsx}", f"IN={int(round(V['init']))}",
                        f"td2x={td2x}", f"dcy={dcy}"] + prof, capture_output=True, text=True).stdout
    d = json.loads(o)
    assert d["done"], "incomplete"
    e = [100 * (m / s - 1) for m, s in zip(d["wx"] + d["wy"], V["wx"] + V["wy"])]
    return e, d


def score(e):
    a = [abs(x) for x in e]; return statistics.mean(a), statistics.median(a), max(a)


if __name__ == "__main__":
    e0, _ = run(0, 0)
    print("G entries, td2x=0 dcy=0: x windows mean/median/max = %.2f/%.2f/%.2f%%" % score(e0[:P]),
          "| y windows %.2f/%.2f/%.2f%%" % score(e0[P:]))
    best = None
    for td2x, dcy in itertools.product(range(-8, 9, 2), range(-24, 25, 4)):
        e, _ = run(td2x, dcy); m = score(e)[0] + 0.2 * score(e)[2]
        if best is None or m < best[0]:
            best = (m, td2x, dcy, e)
    _, td2x, dcy, e = best
    for lo, hi in ((max(-8, td2x - 2), td2x + 2), ):
        pass
    fine = None
    for t2 in range(td2x - 2, td2x + 3):
        for dc in range(dcy - 4, dcy + 5):
            e, _ = run(t2, dc); m = score(e)[0] + 0.2 * score(e)[2]
            if fine is None or m < fine[0]:
                fine = (m, t2, dc, e)
    _, td2x, dcy, e = fine
    print(f"FIT td2x={td2x} dcy={dcy}: x windows %.2f/%.2f/%.2f%% | y windows %.2f/%.2f/%.2f%%" % (score(e[:P]) + score(e[P:])))
    C = [(op, r, c) for op in range(4) for r in (0, P // 2, P - 1) for c in (4, 24)]
    for i, err in enumerate(e):
        if abs(err) > 1.5:
            op, r, c = C[i % P]
            print(f"   {'x' if i < P else 'y'} window cfg {['bcast','scatter','gather','reduce'][op]} root {r} count {c}: {err:+.2f}%")
