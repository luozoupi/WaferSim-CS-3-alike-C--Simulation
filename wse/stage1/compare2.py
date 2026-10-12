#!/usr/bin/env python3
"""Stage 1: fabric engine + F1 PE model (fabsim2) vs simfab on all M1 cases (base families and Addendum A).
Primary metrics follow PREREGISTRATION.md (gate 1, Addendum A); one metric function is applied to simfab and model.
usage: compare2.py [key=value ...] [--role train|holdout] [--family f] [--show] [--secondary]"""
import json, os, subprocess, sys, statistics, itertools
import tempfile
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.join(HERE, "../bench/fabric"))
from gen import build, spec_text, build_ctl, spec_text_ctl, CTL_FAMILIES, MARK
SIM = os.path.join(HERE, "fabsim2")
SCR = os.environ.get("SCR", tempfile.gettempdir())


def legacy_obs(case, obs):
    """model obs -> the base sweep's src/dst [min, max, n] per role (sweep.py metrics())"""
    s = build(case); res = {"src": {}, "dst": {}}
    for (x, y), r in s.roles.items():
        if r["send_n"]:
            v = obs.get(f"{x},{y},{r['send_c']}", {}).get("inj", [])
            if v:
                res["src"][f"{x},{y},{r['send_c']}"] = [v[0], v[-1], len(v)]
        for col, n in r["recv"]:
            v = obs.get(f"{x},{y},{col}", {}).get("arr", [])
            if v:
                res["dst"][f"{x},{y},{col}"] = [v[0], v[-1], len(v)]
    return res


def primary_legacy(m):
    if not m["src"]:
        return {}
    t0 = min(v[0] for v in m["src"].values())
    return {k: v[1] - t0 for k, v in m["dst"].items()}


def g(obs, x, y, c, kind):
    return obs.get(f"{x},{y},{c}", {}).get(kind, [])


def first_inj(obs, tiles):
    v = [a for (x, y, c) in tiles for kind in ("inj", "kinj") for a in g(obs, x, y, c, kind)[:1]]
    return min(v) if v else None


def primary_ctl(c, obs):
    """{metric key: cycles} for an Addendum A case (primary metric only)"""
    f = c["family"]
    try:
        if f == "sa_tx":
            L = 2 * c["m"]; return {"last@L": g(obs, L, 0, 1, "arr")[-1] - first_inj(obs, [(0, 0, 1)])}
        if f == "sa_rx":
            m = c["m"]; return {"last@root": g(obs, m, 0, 1, "arr")[-1] - first_inj(obs, [(0, 0, 1), (2 * m, 0, 1)])}
        if f == "sa_chain":
            N = c["N"]; return {"last@root": g(obs, N, 0, 1, "arr")[-1] - first_inj(obs, [(x, 0, 1) for x in range(N)])}
        if f == "sa_ring":
            last = max(g(obs, x, y, 1, "arr")[-1] for (x, y) in ((1, 0), (0, 1), (2, 1), (1, 2)))
            return {"last@rx": last - first_inj(obs, [(1, 1, 1)])}
        if f == "td_line":
            L = c["L"]; t0 = first_inj(obs, [(0, 0, 1)])
            if c["P2"]:
                return {"p2last@L": g(obs, L, 0, 1, "arr")[-1] - t0}
            return {"marker@L": g(obs, L, 0, MARK, "inj")[0] - t0}
    except (IndexError, TypeError, ValueError):
        return {}
    raise ValueError(f)


def secondary_ctl(c, obs):
    f = c["family"]; out = {}
    try:
        if f == "sa_tx":
            m, L = c["m"], 2 * c["m"]
            out["switch_gap"] = g(obs, L, 0, 1, "arr")[0] - g(obs, m, 0, 1, "arr")[c["B1"] - 1]
        if f == "td_line":
            for x in range(c["L"] + 1):
                td = (g(obs, x, 0, 1, "kinj") if x == 0 else g(obs, x, 0, 1, "karr"))[0]
                out[f"handler@{x}"] = g(obs, x, 0, MARK, "inj")[0] - td
    except (IndexError, TypeError):
        pass
    return out


_SPEC = {}
_CNT = itertools.count()
WORKERS = int(os.environ.get("CMP_WORKERS", "16"))


def spec_file(case):
    """spec text written once per case (cached path)"""
    t = case["tag"]
    if t not in _SPEC:
        ctl = case["family"] in CTL_FAMILIES
        p = os.path.join(SCR, f"spec_{os.getpid()}_{next(_CNT)}.txt")
        open(p, "w").write((spec_text_ctl(build_ctl(case)) if ctl else spec_text(build(case))) + (case.get("bg", "") if BG else ""))
        _SPEC[t] = p
    return _SPEC[t]


def model(case, kv):
    out = subprocess.run([SIM, spec_file(case)] + kv, capture_output=True, text=True).stdout
    return json.loads(out)["obs"]


_ROWS = None
BG = os.environ.get("BG", "1") == "1"      # Addendum C: replay runtime memcpy traffic (colours 21/22)


def bg_lines(r):
    """runtime traffic arrivals (link records, colours 21/22) per tile, relative to the case's first injection"""
    o = r["obs"]
    inj = [v for k, d in o.items() if not k.endswith((",21", ",22")) for kind in ("inj", "kinj") for v in d.get(kind, [])[:1]]
    if not inj:
        return ""
    t0 = min(inj); out = []
    for k, d in o.items():
        if k.endswith((",21", ",22")):
            x, y, _ = k.split(",")
            out += [f"BG {x} {y} {v - t0}" for kind in ("arr", "karr") for v in d.get(kind, [])]
    return "\n".join(out) + "\n"


def rows():
    """one row per case: packed rows (full per-wavelet lists) take precedence over unpacked rows of the same case.
    Cached; memcpy colours (21, 22) dropped from obs."""
    global _ROWS
    if _ROWS is not None:
        return _ROWS
    out = {}
    for fn in ("results/fabric_m1.jsonl", "results/fabric_m1_ctl.jsonl",
               "results/fabric_m1_packed.jsonl", "results/fabric_m1_ctl_packed.jsonl"):
        p = os.path.join(HERE, fn)
        if os.path.exists(p):
            for l in open(p):
                r = json.loads(l)
                if "obs" in r:
                    r["bg"] = bg_lines(r)
                    r["obs"] = {k: v for k, v in r["obs"].items() if not k.endswith((",21", ",22"))}
                out[r["tag"]] = r
    _ROWS = list(out.values())
    return _ROWS


def evaluate(kv, role=None, fam=None, show=False, secondary=False):
    errs = {}
    sel = [r for r in rows() if not ((role and r["role"] != role) or (fam and r["family"] != fam))]
    for r in sel:
        spec_file(r)
    with ThreadPoolExecutor(WORKERS) as ex:
        models = list(ex.map(lambda r: model(r, kv), sel))
    for r, obs in zip(sel, models):
        if r["family"] in CTL_FAMILIES:
            ps, pm = primary_ctl(r, r["obs"]), primary_ctl(r, obs)
        else:
            ps, pm = primary_legacy(r), primary_legacy(legacy_obs(r, obs))
        for k, v in ps.items():
            e = 100 * (pm.get(k, 0) / v - 1) if v else 0.0
            errs.setdefault(r["family"], []).append((abs(e), e, r["tag"], k, v, pm.get(k)))
            if show:
                print(f"  {r['tag']:28s} {k:12s} simfab {v:6d} model {pm.get(k)!s:>6} {e:+6.2f}%")
        if secondary and r["family"] in CTL_FAMILIES:
            ss, sm = secondary_ctl(r, r["obs"]), secondary_ctl(r, obs)
            print(f"  {r['tag']:28s} " + " ".join(f"{k} {ss[k]}/{sm.get(k)}" for k in ss))
    return errs


def main():
    args = sys.argv[1:]; kv = [a for a in args if "=" in a and not a.startswith("--")]
    role = args[args.index("--role") + 1] if "--role" in args else None
    fam = args[args.index("--family") + 1] if "--family" in args else None
    errs = evaluate(kv, role, fam, "--show" in args, "--secondary" in args)
    allv = []
    for f, es in errs.items():
        a = [e[0] for e in es]; allv += a; w = max(es)
        print(f"{f:12s} n={len(a):3d} median|e|={statistics.median(a):5.2f}% max|e|={w[0]:6.2f}% "
              f"({w[2]} {w[3]} simfab {w[4]} model {w[5]})")
    if allv:
        print(f"{'ALL':12s} n={len(allv):3d} median|e|={statistics.median(allv):5.2f}% max|e|={max(allv):6.2f}%")


if __name__ == "__main__":
    main()
