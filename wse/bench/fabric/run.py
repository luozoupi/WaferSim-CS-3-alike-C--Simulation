#!/usr/bin/env cs_python
# Stage 1 / M1 runner: enable timer, main, read 8 stamps per PE.  TRACE=1 keeps simfab traces.
import argparse, json, os
import numpy as np
from cerebras.sdk.runtime.sdkruntimepybind import SdkRuntime, MemcpyDataType, MemcpyOrder  # pylint: disable=no-name-in-module
p = argparse.ArgumentParser(); p.add_argument("--name", required=True); p.add_argument("--json", default="stamps.json")
a = p.parse_args()
params = json.load(open(f"{a.name}/out.json"))["params"]
W, H = int(params["W"]), int(params["H"])
rt = SdkRuntime(a.name, cmaddr=None, suppress_simfab_trace=(os.environ.get("TRACE", "0") != "1"),
                simfab_numthreads=int(os.environ.get("SIMFAB_THREADS", "2")))
sym = rt.get_id("time_buf_u16")
rt.load(); rt.run()
rt.launch("f_enable_timer", nonblock=False)
rt.launch("main", nonblock=False)
rt.launch("f_memcpy_timestamps", nonblock=False)
buf = np.zeros((H, W, 24), dtype=np.uint32)
rt.memcpy_d2h(buf, sym, 0, 0, W, H, 24, streaming=False, data_type=MemcpyDataType.MEMCPY_16BIT, nonblock=False,
              order=MemcpyOrder.ROW_MAJOR)
rt.stop()
t = buf.astype(np.uint64)
s = (t[..., 0::3] + (t[..., 1::3] << np.uint64(16)) + (t[..., 2::3] << np.uint64(32))).astype(np.int64)
json.dump({"W": W, "H": H, "stamps": s.tolist()}, open(a.json, "w"))
print("SUCCESS")
