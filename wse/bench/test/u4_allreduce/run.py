#!/usr/bin/env cs_python
# U4 runner: full-grid h2d of v, enable timer, main (timed on-device: main entry -> final callback), check global sum
import argparse, json, os
import numpy as np
from cerebras.sdk.runtime.sdkruntimepybind import SdkRuntime, MemcpyDataType, MemcpyOrder  # pylint: disable=no-name-in-module
p = argparse.ArgumentParser(); p.add_argument("--name", required=True)
a = p.parse_args()
params = json.load(open(f"{a.name}/out.json"))["params"]
P, C = int(params["P"]), int(params["COUNT"])
rt = SdkRuntime(a.name, cmaddr=None, suppress_simfab_trace=True, simfab_numthreads=int(os.environ.get("SIMFAB_THREADS", "2")))
sv, st_, stime = rt.get_id("v"), rt.get_id("tot"), rt.get_id("time_buf_u16")
rt.load(); rt.run()
np.random.seed(7)
V = np.random.rand(P, P, C).astype(np.float32)
rt.memcpy_h2d(sv, V.ravel(), 0, 0, P, P, C, streaming=False, data_type=MemcpyDataType.MEMCPY_32BIT, nonblock=False,
              order=MemcpyOrder.ROW_MAJOR)
rt.launch("f_enable_timer", nonblock=False)
rt.launch("main", nonblock=False)
rt.launch("f_memcpy_timestamps", nonblock=False)
tot = np.zeros(P * P * C, dtype=np.float32)
rt.memcpy_d2h(tot, st_, 0, 0, P, P, C, streaming=False, data_type=MemcpyDataType.MEMCPY_32BIT, nonblock=False,
              order=MemcpyOrder.ROW_MAJOR)
tb = np.zeros((P, P, 6), dtype=np.uint32)
rt.memcpy_d2h(tb, stime, 0, 0, P, P, 6, streaming=False, data_type=MemcpyDataType.MEMCPY_16BIT, nonblock=False,
              order=MemcpyOrder.ROW_MAJOR)
rt.stop()
t = tb.astype(np.uint64)
s = (t[..., 0::3] + (t[..., 1::3] << np.uint64(16)) + (t[..., 2::3] << np.uint64(32))).astype(np.int64)
cycles_send = int(s[..., 1].max() - s[..., 0].min())
expect = V.sum(axis=(0, 1))
np.testing.assert_allclose(tot.reshape(P, P, C), np.broadcast_to(expect, (P, P, C)), rtol=1e-4, atol=1e-3)
print(f"cycles_send = {cycles_send} cycles")
print("SUCCESS")
