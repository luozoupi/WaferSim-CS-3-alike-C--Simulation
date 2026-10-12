#!/usr/bin/env python3
"""Stage 1 Addendum D: per-PE task timelines from the calibration traces.
A task invocation starts at the task's entry PC (first PC ever dispatched for that task id on that PE) or when the
running task changes; it ends at its last main-thread dispatch.  Async DSD issues = dispatches with ut_id != 255.
Prints, per (op kind, PE role, count): the invocation sequence with start (relative to the main invocation start),
length and issue offsets; writes results/c2dcal_timeline.json for the cost-table builder."""
import gzip, json, os, sys, collections, statistics
HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "../../stage1/results")
TASKS = {1: "main/rpc", 14: "fsm", 15: "lock", 29: "td", 10: "done"}


def invocations(disp):
    entry = {}
    inv = []
    for cyc, pc, task, ut, name in disp:
        if ut != 255:
            if inv:
                inv[-1]["issue"].append(cyc)
            continue
        entry.setdefault(task, pc)
        if not inv or inv[-1]["task"] != task or pc == entry[task]:
            inv.append({"task": task, "start": cyc, "end": cyc, "n": 1, "issue": []})
        else:
            inv[-1]["end"] = cyc; inv[-1]["n"] += 1
    return inv


def role(x, root, P):
    if x == root:
        return "root"
    if x == 0:
        return "first"
    if x == P - 1:
        return "last"
    return "mid"


def timeline(pe, r, P):
    inv = invocations(pe["disp"])
    fsm0 = next((i for i, v in enumerate(inv) if v["task"] == 14), None)
    if fsm0 is None:
        return None
    main = max(range(fsm0), key=lambda i: inv[i]["n"])        # longest task-1 invocation before the first FSM pass
    t0 = inv[main]["start"]
    seq = [dict(inv[main], task="main")] + [v for v in inv[fsm0:] if v["task"] in (14, 15, 29, 10)]
    # stop after the last callback of the op sequence (next launch starts a new task-1 invocation)
    out = []
    for v in seq:
        out.append({"task": TASKS.get(v["task"], v["task"]) if v["task"] != "main" else "main", "t": v["start"] - t0,
                    "len": v["end"] - v["start"] + 1, "n": v["n"], "issue": [c - v["start"] for c in v["issue"]]})
        if v["task"] == 10 and len([o for o in out if o["task"] == "done"]) >= r["reps"]:
            break
    w = {"inj": [], "arr": [], "kinj": [], "karr": []}
    for cyc, col, ctrl, ramp, link, ident in pe["wav"]:
        if col in (0, 1):
            w[("k" if ctrl else "") + ("inj" if ramp else "arr")].append((cyc - t0, col))
    return {"x": pe["x"], "role": role(pe["x"], r["root"], P), "seq": out, "wav": w, "stamps": pe["stamps"]}


def main():
    CP = int(os.environ.get("CAL_P", "12"))
    d = json.load(gzip.open(os.path.join(RES, "c2dcal.json.gz" if CP == 12 else f"c2dcal_P{CP}.json.gz"), "rt"))
    P = d["P"]; print("discarded events:", d["discarded"])
    allt = []
    for r in d["rows"]:
        st = [pe["stamps"] for pe in r["pes"]]
        op_only = max(s[2] for s in st) - min(s[1] for s in st)
        tl = [timeline(pe, r, P) for pe in r["pes"]]
        allt.append(dict({k: r[k] for k in ("op", "root", "count", "reps", "tag")}, op_only=op_only, pes=tl))
        if "-q" in sys.argv:
            continue
        print(f"== {r['tag']} op_only={op_only}")
        for t in tl:
            if t is None:
                print("   (no FSM invocation)"); continue
            if t["role"] in ("root", "first", "last") or t["x"] == (r["root"] + 1) % P:
                s = " ".join(f"{v['task']}@{v['t']}+{v['len']}" + (f"[i{','.join(map(str, v['issue']))}]" if v["issue"] else "") for v in t["seq"])
                print(f"   x={t['x']:2d} {t['role']:5s} {s}")
    json.dump(allt, open(os.path.join(RES, "c2dcal_timeline.json" if CP == 12 else f"c2dcal_timeline_P{CP}.json"), "w"))


if __name__ == "__main__":
    main()
