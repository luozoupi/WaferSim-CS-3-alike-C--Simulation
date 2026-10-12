#!/usr/bin/env cs_python
import argparse, json, os
import numpy as np
from cerebras.sdk.runtime.sdkruntimepybind import SdkRuntime, MemcpyDataType, MemcpyOrder  # pylint: disable=no-name-in-module
p = argparse.ArgumentParser(); p.add_argument("--name", required=True); p.add_argument("--json", default="result.json")
a = p.parse_args()
params = json.load(open(f"{a.name}/out.json"))["params"]
P = int(params["P"])
rt = SdkRuntime(a.name, cmaddr=None, suppress_simfab_trace=True, simfab_numthreads=int(os.environ.get("SIMFAB_THREADS", "2")))
sym = rt.get_id("time_buf_u16")
rt.load(); rt.run()
rt.launch("f_enable_timer", nonblock=False)
rt.launch("main", nonblock=False)
rt.launch("f_memcpy_timestamps", nonblock=False)
buf = np.zeros((P, P, 9), dtype=np.uint32)
rt.memcpy_d2h(buf, sym, 0, 0, P, P, 9, streaming=False, data_type=MemcpyDataType.MEMCPY_16BIT, nonblock=False,
              order=MemcpyOrder.ROW_MAJOR)
rt.stop()
t = buf.astype(np.uint64)
st = (t[..., 0::3] + (t[..., 1::3] << np.uint64(16)) + (t[..., 2::3] << np.uint64(32))).astype(np.int64)
s0, s1, s2 = st[..., 0], st[..., 1], st[..., 2]
res = {k: int(params[k]) for k in ("P", "MODE", "COUNT", "ROOT", "COUNTY")}
res.update(total=int(s2.max() - s0.min()), op_only=int(s2.max() - s1.min()), init_max=int((s1 - s0).max()),
           start_skew=int(s0.max() - s0.min()), op_per_pe_max=int((s2 - s1).max()))
json.dump(res, open(a.json, "w"))
print(json.dumps(res)); print("SUCCESS")
