#!/usr/bin/env python3
"""Stage 1 / M1: packed traced sweep.  Many cases share one simfab fabric (shelf packing; each case keeps its own
routes and roles, only translated), so one compile + one traced run covers a batch.  Cases are independent: no
tile, route or link is shared, and every metric is relative to the case's own first injection.  Per case the record
matches the unpacked sweeps (base: src/dst [min, max, n] + tsc; Addendum A: per-tile obs lists + tsc) and adds
`obs` (full per-tile injection/arrival lists) for the base families, plus `batch` and `offset` for provenance.
usage: packed.py [--ctl|--base] [--maxw 130] [--maxtiles 2200] [filters...]"""
import json, os, subprocess, sys, collections, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cases import all_cases, addendum_a, tag
from gen import build, build_ctl, CTL_FAMILIES, Spec, CtlSpec, layout, layout_ctl
RES = os.path.join(HERE, "../../stage1/results")
OUT_BASE = os.path.join(RES, "fabric_m1_packed.jsonl"); OUT_CTL = os.path.join(RES, "fabric_m1_ctl_packed.jsonl")
# (separate from the unpacked sweeps' files; rows of the same case in both files cross-check the packing)
ENV = dict(os.environ, PATH="/home/luo00466/cs_sdk:/home/luo00466/.local/opt/apptainer-1.5.3/bin:" + os.environ["PATH"],
           APPTAINERENV_SIMFAB_THREADS="2", APPTAINERENV_TRACE="1")
LOCK = "/tmp/xkernel_singularity.lock"
sys.path.insert(0, "/home/luo00466/xkernel/studies/wse3-characterization")   # read-only use of the CTF reader
from wse3study.trace import CtfTraceReader  # noqa: E402


def pack(specs, maxw, maxtiles):
    """shelf packing -> batches of [(case, spec, x0, y0)], each batch with its (W, H)"""
    order = sorted(specs, key=lambda cs: (-cs[1].H, -cs[1].W))
    batches, cur, x, y, shelf_h, W = [], [], 0, 0, 0, 0
    for c, s in order:
        if x + s.W > maxw:                         # new shelf
            y += shelf_h; x = 0; shelf_h = 0
        if cur and (max(W, x + s.W) * max(y + shelf_h, y + s.H) > maxtiles):
            batches.append((cur, W, y + shelf_h)); cur, x, y, shelf_h, W = [], 0, 0, 0, 0
        cur.append((c, s, x, y)); x += s.W; shelf_h = max(shelf_h, s.H); W = max(W, x)
    if cur:
        batches.append((cur, W, y + shelf_h))
    return batches


def merge(items, W, H, ctl):
    m = (CtlSpec if ctl else Spec)(W, H)
    for c, s, x0, y0 in items:
        for (x, y), cols in s.routes.items():
            for col, (rx, tx) in cols.items():
                m.routes.setdefault((x + x0, y + y0), {})[col] = (rx, list(tx))
        for (x, y), r in s.roles.items():
            m.roles[(x + x0, y + y0)] = dict(r)
        if ctl:
            for (x, y, col), sw in s.sw.items():
                m.sw[(x + x0, y + y0, col)] = sw
    return m


def wavelet_events(trdir):
    """every wavelet_trace_entry from ALL CTF streams (simfab splits tiles over `traceFiles` streams per
    global_simdata.json streamMap; tools/decode_trace.py reads stream0 only).  Returns (events, width, discarded)."""
    g = json.load(open(os.path.join(trdir, "global_simdata.json")))
    width = int(g["xsize"]); nfiles = int(g.get("traceFiles", 1))
    streams = [os.path.join(trdir, f"stream{i}") for i in range(nfiles)]
    assert all(os.path.exists(p) for p in streams), (streams, os.listdir(trdir))
    out, discarded = [], 0
    for sp in streams:
        rd = CtfTraceReader(sp, os.path.join(trdir, "metadata"))
        for e in rd.iter_events():
            if e.get("event_type") == "wavelet_trace_entry":
                out.append((e["tile_index"], e["raw"]))
        discarded += rd.discarded_events_total
    return out, width, discarded


def observe(trdir, W, H):
    """first record per (tile, colour, ident): {(x, y, c): {"inj","arr","kinj","karr": sorted cycles}}"""
    first = {}
    evs, width, discarded = wavelet_events(trdir)
    if discarded:
        raise RuntimeError(f"CTF reports {discarded} discarded events: trace incomplete")
    for tile, r in evs:
        x, y = tile % width - 4, tile // width - 1
        if not (0 <= x < W and 0 <= y < H):
            continue
        f = r["fields"]
        k = (x, y, f & 0x1F, r["ident"])
        if k not in first or r["cycle"] < first[k][0]:
            first[k] = (r["cycle"], (f >> 10) & 1, (f >> 5) & 1)
    out = collections.defaultdict(lambda: {"inj": [], "arr": [], "kinj": [], "karr": []})
    for (x, y, col, _), (cyc, ramp, ctrl) in first.items():
        out[(x, y, col)][("k" if ctrl else "") + ("inj" if ramp else "arr")].append(cyc)
    for v in out.values():
        for a in v.values():
            a.sort()
    return out


def run_batch(bi, items, W, H, ctl):
    d = os.path.join(HERE, "runs", f"packed_{'ctl' if ctl else 'base'}_{bi:03d}")
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d)
    m = merge(items, W, H, ctl)
    open(os.path.join(d, "layout.csl"), "w").write((layout_ctl if ctl else layout)(m))
    for f in ("pe.csl", "pe_ctl.csl", "run.py", "run_ctl.py"):
        shutil.copy(os.path.join(HERE, f), d)
    comp = subprocess.run(["flock", LOCK, "cslc", "--arch=wse3", "./layout.csl", f"--fabric-dims={W + 7},{H + 2}",
                           "--fabric-offsets=4,1", f"--params=W:{W},H:{H}", "--memcpy", "--channels=1", "-o", "out"],
                          cwd=d, env=ENV, capture_output=True, text=True)
    open(os.path.join(d, "compile.log"), "w").write(comp.stdout + comp.stderr)
    if comp.returncode:
        return None, "compile failed: " + (comp.stdout + comp.stderr)[-400:]
    run = subprocess.run(["flock", LOCK, "cs_python", "run_ctl.py" if ctl else "run.py", "--name", "out", "--json", "stamps.json"],
                         cwd=d, env=ENV, capture_output=True, text=True)
    open(os.path.join(d, "run.log"), "w").write(run.stdout + run.stderr)
    if "SUCCESS" not in run.stdout:
        return None, "run failed: " + (run.stdout + run.stderr)[-400:]
    obs = observe(os.path.join(d, "simfab_traces"), W, H)
    shutil.rmtree(os.path.join(d, "simfab_traces"), ignore_errors=True); shutil.rmtree(os.path.join(d, "out"), ignore_errors=True)
    st = json.load(open(os.path.join(d, "stamps.json")))["stamps"]
    recs = []
    for c, s, x0, y0 in items:
        loc = {}
        for (x, y, col), v in obs.items():
            if x0 <= x < x0 + s.W and y0 <= y < y0 + s.H:
                loc[f"{x - x0},{y - y0},{col}"] = v
        rec = dict(c, tag=tag(c), W=s.W, H=s.H, obs=loc, batch=os.path.basename(d), offset=[x0, y0],
                   tsc={f"{x},{y}": st[y + y0][x + x0] for (x, y) in s.roles})
        if not ctl:                                # base-sweep metrics (sweep.py metrics(), from the lists)
            rec["src"], rec["dst"] = {}, {}
            for (x, y), r in s.roles.items():
                if r["send_n"]:
                    v = loc.get(f"{x},{y},{r['send_c']}", {}).get("inj", [])
                    if v:
                        rec["src"][f"{x},{y},{r['send_c']}"] = [v[0], v[-1], len(v)]
                for col, n in r["recv"]:
                    v = loc.get(f"{x},{y},{col}", {}).get("arr", [])
                    if v:
                        rec["dst"][f"{x},{y},{col}"] = [v[0], v[-1], len(v)]
        recs.append(rec)
    return recs, None


def main():
    args = sys.argv[1:]
    maxw = int(args[args.index("--maxw") + 1]) if "--maxw" in args else 130
    maxtiles = int(args[args.index("--maxtiles") + 1]) if "--maxtiles" in args else 2200
    filt = [a for a in args if not a.startswith("--") and not a.isdigit()]
    kinds = ["ctl"] if "--ctl" in args else ["base"] if "--base" in args else ["ctl", "base"]
    for kind in kinds:
        ctl = kind == "ctl"; out = OUT_CTL if ctl else OUT_BASE
        done = {json.loads(l)["tag"] for l in open(out)} if os.path.exists(out) else set()
        cases = [c for c in (addendum_a() if ctl else [c for c in all_cases() if c["family"] not in CTL_FAMILIES])
                 if tag(c) not in done and (not filt or any(f in tag(c) for f in filt))]
        specs = [(c, build_ctl(c) if ctl else build(c)) for c in cases]
        batches = pack(specs, maxw, maxtiles)
        print(f"{kind}: {len(cases)} cases in {len(batches)} batches", flush=True)
        for bi, (items, W, H) in enumerate(batches):
            recs, err = run_batch(bi, items, W, H, ctl)
            if err:
                print(f"{kind} batch {bi} ({len(items)} cases, {W}x{H}) FAILED: {err}", flush=True); continue
            with open(out, "a") as f:
                for r in recs:
                    f.write(json.dumps(r) + "\n")
            print(f"{kind} batch {bi}: {len(recs)} cases ({W}x{H}) ok", flush=True)


if __name__ == "__main__":
    main()
