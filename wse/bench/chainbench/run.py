# Stage-0 collectives microbenchmark host driver: launch main(), read 3 stamps per PE, emit JSON.
import argparse, json, os
import numpy as np
from cerebras.sdk.runtime.sdkruntimepybind import SdkRuntime, MemcpyDataType, MemcpyOrder  # pylint: disable=no-name-in-module

p = argparse.ArgumentParser()
p.add_argument("--name", required=True)
p.add_argument("--json", default="result.json")
a = p.parse_args()
params = json.load(open(f"{a.name}/out.json"))["params"]
Pw, Ph = int(params["Pw"]), int(params["Ph"])
rt = SdkRuntime(a.name, cmaddr=None, suppress_simfab_trace=(os.environ.get("TRACE", "0") != "1"),
                simfab_numthreads=int(os.environ.get("SIMFAB_THREADS", "2")))
sym = rt.get_id("time_buf_u16")
rt.load(); rt.run()
rt.launch("f_enable_timer", nonblock=False)
rt.launch("main", nonblock=False)
rt.launch("f_memcpy_timestamps", nonblock=False)
buf = np.zeros((Ph, Pw, 9), dtype=np.uint32)
rt.memcpy_d2h(buf, sym, 0, 0, Pw, Ph, 9, streaming=False, data_type=MemcpyDataType.MEMCPY_16BIT,
              nonblock=False, order=MemcpyOrder.ROW_MAJOR)
rt.stop()
t = buf.astype(np.uint64)
st = t[..., 0::3] + (t[..., 1::3] << np.uint64(16)) + (t[..., 2::3] << np.uint64(32))   # (Ph, Pw, 3)
s0, s1, s2 = st[..., 0].astype(np.int64), st[..., 1].astype(np.int64), st[..., 2].astype(np.int64)
line = s2.reshape(-1)
res = {k: int(params[k]) for k in ("Pw", "Ph", "OP", "DIM", "COUNT", "ROOT", "REPS", "OP2", "ROOT2")}
res.update(total=int(s2.max() - s0.min()), op_only=int(s2.max() - s1.min()),
           init_max=int((s1 - s0).max()), start_skew=int(s0.max() - s0.min()),
           end_per_pe=[int(v - s1.min()) for v in line])
json.dump(res, open(a.json, "w"))
print(f"cycles_send = {res['total']} cycles ; op_only = {res['op_only']}")
print("SUCCESS")
