// Stage 1 M5 harness: replays the Stage 0 collectives benches on the wavelet-level fabric with the ported
// <collectives_2d> (src/wse/c2d.h).  Kernels (wse/bench/*/pe.csl):
//   kernel=collbench op= P= count= root= dim= reps=      (one module; REPS chained ops)
//   kernel=chain     op= op2= P= count= root= root2= dim=  (one module; two chained ops)
//   kernel=coll2d    P= mode= count= countY= root=       (P x P, both modules initialised; x and/or y bcast)
// Device-internal timing as in the SDK runs: stamps ts0 (main entry), ts1 (after init), ts2 (last callback) in
// each PE's local TSC frame (global - launch offset LW*x + LY*y); prints op_only, total, end_per_pe.
// Other key=value: fabric (hop link buf rin rout turn), PE (s0 s0c a0 cpl disp tdd exit fwl fwc),
// collectives (init cfg act tdd2 handler lock copy fadd init2 td2), launch LW LY.
#include "../../src/wse/c2d.h"
#include <cstring>
#include <string>
#include <memory>
using namespace wse;

int main(int argc, char** argv){
  Profile pr; PeProfile pp; C2dProfile cp;
  std::map<std::string, double> a = {{"op", 0}, {"op2", 0}, {"P", 4}, {"count", 1}, {"root", 0}, {"root2", 0}, {"dim", 0},
                                     {"reps", 1}, {"mode", 0}, {"countY", 0}, {"LW", 2}, {"LY", 0}};
  std::string kernel = "collbench"; CostTable ct; std::string costs;
  for (int i = 1; i < argc; i++){
    char k[64], sv[1024]; if (sscanf(argv[i], "%63[^=]=%1023s", k, sv) != 2) continue;
    std::string K(k);
    if (K == "kernel"){ kernel = sv; continue; }
    if (K == "costs"){ costs = sv; continue; }
    double v = atof(sv); int iv = (int)v;
    if (K == "hop") pr.hop = iv; else if (K == "link") pr.link = iv; else if (K == "buf") pr.buf = iv;
    else if (K == "rin") pr.ramp_in_buf = iv; else if (K == "rout") pr.ramp_out_buf = iv; else if (K == "turn") pr.turn = iv;
    else if (K == "s0") pp.s0 = iv; else if (K == "s0c") pp.s0_ctl = iv; else if (K == "a0") pp.a0 = iv;
    else if (K == "cpl") pp.cpl = iv; else if (K == "disp") pp.disp = iv; else if (K == "tdd") pp.td_disp = iv;
    else if (K == "exit") pp.exit_cost = iv; else if (K == "fwl") pp.fwd_lat = iv; else if (K == "fwc") pp.fwd_cap = iv;
    else if (K == "init") cp.init = iv; else if (K == "cfg") cp.cfg = iv; else if (K == "act") cp.act = iv;
    else if (K == "tdd2") cp.tdd = iv; else if (K == "handler") cp.handler = iv; else if (K == "lock") cp.lock = iv;
    else if (K == "copy") cp.copy = v; else if (K == "fadd") cp.fadd = v; else if (K == "init2") cp.init2 = iv;
    else if (K == "td2") cp.td2 = iv; else if (K == "td2x") cp.td2x = iv; else if (K == "dcy") cp.dcy = iv;
    else if (K == "kts2") ct.k_ts2 = iv; else if (K == "tail") ct.tail = iv; else if (K == "oq") pp.oq_depth = iv;
    else if (K == "ib") pp.in_bubble = iv;
    else a[K] = v;
  }
  if (!costs.empty() && !ct.load(costs)){ fprintf(stderr, "cannot load %s\n", costs.c_str()); return 1; }
  const CostTable* CT = ct.loaded ? &ct : nullptr;
  int P = (int)a["P"], dim = (int)a["dim"], LW = (int)a["LW"], LY = (int)a["LY"];
  int GW, GH;
  if (kernel == "coll2d"){ GW = GH = P; } else if (dim == 0){ GW = P; GH = 1; } else { GW = 1; GH = P; }
  Fabric fab(GW, GH, pr); fab.tracing = false;
  Machine m(fab, pp);
  std::vector<std::unique_ptr<C2D>> mx, my;
  std::vector<int> rep(GW * GH, 0), pending(GW * GH, 0);
  for (auto& q : m.pe){
    int idx = q.y * GW + q.x;
    if (kernel == "coll2d"){
      mx.emplace_back(new C2D(m, q, 0, cp)); my.emplace_back(new C2D(m, q, 1, cp));
      mx.back()->two_modules = my.back()->two_modules = true;
      mx.back()->ct = my.back()->ct = CT;
      mx.back()->other_init = my.back()->other_init = true;          // coll2d main initialises both modules
    } else {
      mx.emplace_back(new C2D(m, q, dim, cp)); my.emplace_back(nullptr); mx.back()->ct = CT;
    }
    C2D* X = mx.back().get(); C2D* Y = my.back().get();
    uint64_t t0 = (uint64_t)(LW * q.x + LY * q.y);
    if (kernel == "collbench" || kernel == "chain"){
      int reps = kernel == "chain" ? 2 : (int)a["reps"];
      auto start = [&m, X, &a, &rep, idx, kernel]{
        bool second = kernel == "chain" && rep[idx] > 0;
        X->op((int)a[second ? "op2" : "op"], (int)a[second ? "root2" : "root"], (int)a["count"], 10, nullptr, nullptr,
              rep[idx] > 0 ? C2D::CHAINED : C2D::FIRST);
      };
      q.task[10] = [&m, &rep, idx, reps, start, CT, X]{
        if (++rep[idx] < reps){ start(); return; }
        if (CT){ m.spend(CT->k_ts2); m.stamp(2); m.spend(std::max(0, (int)X->cost0("done", 25) - CT->k_ts2)); }
        else m.stamp(2);
      };
      m.launch(q, t0, [&m, X, start]{ m.stamp(0); X->init(); m.stamp(1); start(); });
    } else {
      int mode = (int)a["mode"];
      auto one_done = [&m, &pending, idx, CT]{
        if (--pending[idx] > 0) return;
        if (CT) m.spend(CT->k_ts2);
        m.stamp(2);
      };
      q.task[10] = one_done; q.task[11] = one_done;
      m.launch(q, t0, [&m, X, Y, &a, &pending, idx, mode]{
        m.stamp(0); X->init(); Y->init(true); m.stamp(1);
        pending[idx] = mode == 2 ? 2 : 1;
        if (mode != 1) X->op(BCAST, (int)a["root"], (int)a["count"], 10);
        if (mode != 0) Y->op(BCAST, (int)a["root"], (int)(a["countY"] > 0 ? a["countY"] : a["count"]), 11, nullptr, nullptr,
                             mode == 2 ? C2D::NEXT : C2D::FIRST);
      });
    }
  }
  long limit = 5000000, quiet = 0;
  while ((long)fab.now < limit){ m.step(); if (m.idle()){ if (++quiet > 256) break; } else quiet = 0; }
  int64_t min0 = INT64_MAX, min1 = INT64_MAX, max2 = INT64_MIN; bool ok = true;
  std::vector<int64_t> s1(GW * GH), s2(GW * GH);
  for (auto& q : m.pe){
    int64_t L = LW * q.x + LY * q.y;
    if (q.stamp[2] < 0) ok = false;
    int i = q.y * GW + q.x; s1[i] = q.stamp[1] - L; s2[i] = q.stamp[2] - L;
    min0 = std::min(min0, q.stamp[0] - L); min1 = std::min(min1, s1[i]); max2 = std::max(max2, s2[i]);
  }
  printf("{\"ok\": %s, \"op_only\": %ld, \"total\": %ld, \"end_per_pe\": [", ok ? "true" : "false", (long)(max2 - min1), (long)(max2 - min0));
  for (int i = 0; i < GW * GH; i++) printf("%s%ld", i ? ", " : "", (long)(s2[i] - min1));
  printf("], \"cycles\": %lu}\n", (unsigned long)fab.now);
  return ok ? 0 : 2;
}
