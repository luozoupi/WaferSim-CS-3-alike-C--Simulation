#!/usr/bin/env cs_python
# 2D launch probe runner.  SEQ (JSON list) is the host command sequence under test, e.g.
#  [["h2d",x0,y0,w,h,n,blocking], ["timer",blocking], ["main"], ["main"]]
# Coordinates may be negative (counted from the far edge: -1 = last column/row).
import argparse, json, os
import numpy as np
from cerebras.sdk.runtime.sdkruntimepybind import SdkRuntime, MemcpyDataType, MemcpyOrder  # pylint: disable=no-name-in-module

p = argparse.ArgumentParser(); p.add_argument("--name", required=True); p.add_argument("--json", default="result.json")
a = p.parse_args()
params = json.load(open(f"{a.name}/out.json"))["params"]
Pw, Ph = int(params["Pw"]), int(params["Ph"])
seq = json.loads(os.environ["SEQ"])
rt = SdkRuntime(a.name, cmaddr=None, suppress_simfab_trace=(os.environ.get("TRACE", "0") != "1"),
                simfab_numthreads=int(os.environ.get("SIMFAB_THREADS", "2")))
sb, st = rt.get_id("buf"), rt.get_id("time_buf_u16")
rt.load(); rt.run()
rounds = 0
for s in seq:
    if s[0] == "h2d":
        x0, y0, w, h, n, blk = s[1:]
        x0 %= Pw; y0 %= Ph
        w = Pw if w == "P" else w; h = Ph if h == "P" else h
        rt.memcpy_h2d(sb, np.random.rand(w * h * n).astype(np.float32), x0, y0, w, h, n, streaming=False,
                      data_type=MemcpyDataType.MEMCPY_32BIT, nonblock=not blk, order=MemcpyOrder.ROW_MAJOR)
    elif s[0] == "d2h":
        x0, y0, w, h, n = s[1:]
        x0 %= Pw; y0 %= Ph
        tmpo = np.zeros(w * h * n, dtype=np.float32)
        rt.memcpy_d2h(tmpo, sb, x0, y0, w, h, n, streaming=False, data_type=MemcpyDataType.MEMCPY_32BIT,
                      nonblock=False, order=MemcpyOrder.ROW_MAJOR)
    elif s[0] == "timer":
        rt.launch("f_enable_timer", nonblock=not s[1])
    elif s[0] == "main":
        rt.launch("main", nonblock=False); rounds += 1
rt.launch("f_memcpy_timestamps", nonblock=False)
NW = int(os.environ.get("NWORDS", "18"))
buf = np.zeros((Ph, Pw, NW), dtype=np.uint32)
rt.memcpy_d2h(buf, st, 0, 0, Pw, Ph, NW, streaming=False, data_type=MemcpyDataType.MEMCPY_16BIT, nonblock=False,
              order=MemcpyOrder.ROW_MAJOR)
rt.stop()
t = buf.astype(np.uint64)
ns = 6 if NW == 18 else 4
s = (t[..., 0:3 * ns:3] + (t[..., 1:3 * ns:3] << np.uint64(16)) + (t[..., 2:3 * ns:3] << np.uint64(32))).astype(np.int64)
res = {"Pw": Pw, "Ph": Ph, "seq": seq, "rounds": rounds, "stamps": s.tolist()}
if NW == 16:
    res["tsc_ok"] = buf[..., 12:16].astype(int).tolist()     # per slot: TSC was running when stamped
json.dump(res, open(a.json, "w"))
print("SUCCESS")
