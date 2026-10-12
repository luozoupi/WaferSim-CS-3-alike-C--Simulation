#!/usr/bin/env python3
"""Stage 1 Addendum D: build, traced run and trace extraction of the calibration set (one packed simfab run).
Writes ../../stage1/results/c2dcal.json.gz: per row, per PE: stamps, task invocations (task, start, end, issue
cycles of async DSD ops), C0/C1 wavelet events, runtime (21/22) wavelet arrivals.  Raw CTF streams are kept."""
import gzip, json, os, subprocess, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, "/home/luo00466/xkernel/studies/wse3-characterization")   # read-only use of the CTF reader
from wse3study.trace import CtfTraceReader  # noqa: E402
from cases import rows, tag, P
LOCK = "/tmp/xkernel_singularity.lock"
ENV = dict(os.environ, PATH="/home/luo00466/cs_sdk:/home/luo00466/.local/opt/apptainer-1.5.3/bin:" + os.environ["PATH"],
           APPTAINERENV_SIMFAB_THREADS="2", APPTAINERENV_TRACE="1")
OUT = os.path.join(HERE, "../../stage1/results/c2dcal.json.gz" if P == 12 else f"../../stage1/results/c2dcal_P{P}.json.gz")


def build_and_run():
    R = rows(); W, H = P, len(R)
    subprocess.run(["python3", "gen.py"], cwd=HERE, check=True)
    c = subprocess.run(["flock", LOCK, "cslc", "--arch=wse3", "./layout.csl", f"--fabric-dims={W + 7},{H + 2}", "--fabric-offsets=4,1",
                        f"--params=Pw:{W},Ph:{H}", "--memcpy", "--channels=1", "-o", "out"], cwd=HERE, env=ENV, capture_output=True, text=True)
    open(os.path.join(HERE, "compile.log"), "w").write(c.stdout + c.stderr)
    if c.returncode:
        sys.exit("compile failed:\n" + (c.stdout + c.stderr)[-1500:])
    r = subprocess.run(["flock", LOCK, "cs_python", "run_cal.py", "--name", "out", "--json", "stamps.json"], cwd=HERE, env=ENV,
                       capture_output=True, text=True)
    open(os.path.join(HERE, "run.log"), "w").write(r.stdout + r.stderr)
    if "SUCCESS" not in r.stdout:
        sys.exit("run failed:\n" + (r.stdout + r.stderr)[-1500:])


def extract():
    R = rows(); W, H = P, len(R)
    tr = os.path.join(HERE, "simfab_traces")
    g = json.load(open(os.path.join(tr, "global_simdata.json")))
    width = int(g["xsize"]); nfiles = int(g.get("traceFiles", 1))
    disp = collections.defaultdict(list); wav = collections.defaultdict(list); discarded = 0
    for i in range(nfiles):
        rd = CtfTraceReader(os.path.join(tr, f"stream{i}"), os.path.join(tr, "metadata"))
        for e in rd.iter_events():
            et = e.get("event_type"); r = e.get("raw", {}); ti = r.get("tile_index")
            if ti is None:
                continue
            x, y = ti % width - 4, ti // width - 1
            if not (0 <= x < W and 0 <= y < H):
                continue
            if et == "hwm_dispatch_trace_entry":
                disp[(x, y)].append((r["cycle"], r["inst_ptr"], r["task_color"], r["ut_id"], r["name"]))
            elif et == "wavelet_trace_entry":
                f = r["fields"]
                wav[(x, y)].append((r["cycle"], f & 0x1F, (f >> 5) & 1, (f >> 10) & 1, (f >> 8) & 3, r["ident"]))
        discarded += rd.discarded_events_total
    st = json.load(open(os.path.join(HERE, "stamps.json")))["stamps"]
    out = {"P": P, "discarded": discarded, "rows": []}
    for y, r in enumerate(R):
        pes = []
        for x in range(W):
            d = sorted(disp[(x, y)]); w = sorted(wav[(x, y)])
            pes.append({"x": x, "stamps": st[y][x], "disp": d, "wav": w})
        out["rows"].append(dict(r, tag=tag(r), y=y, pes=pes))
    json.dump(out, gzip.open(OUT, "wt"))
    print("rows", len(R), "discarded events", discarded, "->", OUT)


if __name__ == "__main__":
    if "--extract-only" not in sys.argv:
        build_and_run()
    extract()
