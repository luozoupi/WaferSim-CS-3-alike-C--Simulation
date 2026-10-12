// Stage 1 gate item 3 (Addendum F): the Stage 0 regression kernels on the Stage 1 engine (fabric.h + pe.h + c2d.h).
// Kernels (task graphs from their CSL sources, wse/bench/test/*, muchisim_eval/pilot/sdk/{gemv,gemm}):
//   kernel=gemv   (GEMV, U1, U2):  MT NT C0 C1 KI [TIC TOC]
//   kernel=summa  (SUMMA, U3, T1): WX WY SC KI
//   kernel=t2     (T2 topic-11):   CH KIX KIY RPC
//   kernel=u4     (allreduce-2D):  CNT KIX KIY
// ls=<file>: launch state, one line per row y: "L_row E_row" (Stage 0c launch law v2); PE (x, y) is launched at
// 2x + L_row[y] and its TSC enabled at 2x + E_row[y].  The remaining key=value arguments are profile_m1 / profile_m5e
// (fabric, PE, collectives port with its cost table) as for c2dsim.
// Output: {"ok", "cs"} (+ "x", "y" for T2): device_internal_v2 windows in local TSC frames.
#include "../../src/wse/c2d.h"
#include <cstring>
#include <cmath>
#include <climits>
#include <string>
#include <memory>
using namespace wse;

int main(int argc, char** argv){
  Profile pr; PeProfile pp; C2dProfile cp; CostTable ct;
  std::map<std::string, double> a = {{"P", 4}, {"MT", 8}, {"NT", 4}, {"C0", 107}, {"C1", 101}, {"KI", 123}, {"TIC", 0}, {"TOC", 0},
                                     {"WX", 196}, {"WY", 196}, {"SC", 11904}, {"CH", 3}, {"KIX", 86}, {"KIY", 79}, {"RPC", 206},
                                     {"CNT", 8}, {"GL", 4}, {"TD2U", 17}};
  std::string kernel = "gemv", costs, ls, lsx;
  for (int i = 1; i < argc; i++){
    char k[64], sv[1024]; if (sscanf(argv[i], "%63[^=]=%1023s", k, sv) != 2) continue;
    std::string K(k);
    if (K == "kernel"){ kernel = sv; continue; }
    if (K == "costs"){ costs = sv; continue; }
    if (K == "ls"){ ls = sv; continue; }
    if (K == "lsx"){ lsx = sv; continue; }
    double v = atof(sv); int iv = (int)v;
    if (K == "hop") pr.hop = iv; else if (K == "link") pr.link = iv; else if (K == "buf") pr.buf = iv;
    else if (K == "rin") pr.ramp_in_buf = iv; else if (K == "rout") pr.ramp_out_buf = iv; else if (K == "turn") pr.turn = iv;
    else if (K == "s0") pp.s0 = iv; else if (K == "s0c") pp.s0_ctl = iv; else if (K == "a0") pp.a0 = iv;
    else if (K == "cpl") pp.cpl = iv; else if (K == "disp") pp.disp = iv; else if (K == "tdd") pp.td_disp = iv;
    else if (K == "exit") pp.exit_cost = iv; else if (K == "fwl") pp.fwd_lat = iv; else if (K == "fwc") pp.fwd_cap = iv;
    else if (K == "oq") pp.oq_depth = iv; else if (K == "ib") pp.in_bubble = iv;
    else if (K == "init") cp.init = iv; else if (K == "init2") cp.init2 = iv; else if (K == "td2") cp.td2 = iv; else if (K == "td2x") cp.td2x = iv; else if (K == "dcy") cp.dcy = iv;
    else if (K == "handler") cp.handler = iv; else if (K == "lock") cp.lock = iv; else if (K == "cfg") cp.cfg = iv;
    else if (K == "act") cp.act = iv; else if (K == "tdd2") cp.tdd = iv;
    else if (K == "kts2") ct.k_ts2 = iv; else if (K == "tail") ct.tail = iv;
    else a[K] = v;                                   // kernel parameters (and LW / LY, unused with ls=)
  }
  if (!costs.empty() && !ct.load(costs)){ fprintf(stderr, "cannot load %s\n", costs.c_str()); return 1; }
  const CostTable* CT = ct.loaded ? &ct : nullptr;
  int P = (int)a["P"];
  std::vector<double> Lr(P, 0), Er(P, 0);
  if (!ls.empty()){ FILE* f = fopen(ls.c_str(), "r"); if (!f){ perror("ls"); return 1; } for (int y = 0; y < P; y++) if (fscanf(f, "%lf %lf", &Lr[y], &Er[y]) != 2) return 1; fclose(f); }
  std::vector<long> Lpe, Epe, INpe;                             // lsx=: per-PE launch / enable times [/ init] (row-major)
  if (!lsx.empty()){ FILE* f = fopen(lsx.c_str(), "r"); if (!f){ perror("lsx"); return 1; }
    char line[256];
    while (fgets(line, sizeof line, f)){ long l, e, in; int n = sscanf(line, "%ld %ld %ld", &l, &e, &in);
      if (n >= 2){ Lpe.push_back(l); Epe.push_back(e); if (n == 3) INpe.push_back(in); } }
    fclose(f);
    if ((int)Lpe.size() != P * P){ fprintf(stderr, "lsx: need P*P lines\n"); return 1; } }
  auto Lof = [&](int x, int y){ return Lpe.empty() ? (long)llround(2.0 * x + Lr[y]) : Lpe[y * P + x]; };
  auto Eof = [&](int x, int y){ return Epe.empty() ? (long)llround(2.0 * x + Er[y]) : Epe[y * P + x]; };
  long Lmin = 0; for (int y = 0; y < P; y++) for (int x = 0; x < P; x++) Lmin = std::min(Lmin, Lof(x, y));

  Fabric fab(P, P, pr); fab.tracing = false;
  Machine m(fab, pp);
  std::vector<std::unique_ptr<C2D>> mx, my;
  int N = P * P; std::vector<long> st0(N, -1), st1(N, -1), st2(N, -1), st3(N, -1);
  std::vector<int> state(N, 0), step(N, 0);
  const int T_A = 8, T_B = 9, T_C = 10, T_D = 11, T_E = 12, T_X = 13;   // kernel tasks (FSM/LOCK use 14..17)
  int GL = (int)a["GL"];
  auto glue = [&m, GL](int next){ m.spend(std::max(0, GL - m.pp.disp)); m.activate(next); };
  auto exit_stamp = [&m, CT](std::vector<long>& v, int i, int extra){ if (CT) m.spend(CT->k_ts2); v[i] = (long)m.t() + extra; };

  for (auto& q : m.pe){
    int i = q.y * P + q.x;
    mx.emplace_back(new C2D(m, q, 0, cp)); my.emplace_back(new C2D(m, q, 1, cp));
    C2D* X = mx.back().get(); C2D* Y = my.back().get();
    X->two_modules = Y->two_modules = true; X->ct = Y->ct = CT;
    X->other_init = Y->other_init = (kernel != "t2");               // main initialises both modules (T2: y later)
    uint64_t t0 = (uint64_t)(Lof(q.x, q.y) - Lmin);
    int px = q.x, py = q.y;
    if (kernel == "gemv"){
      int MT = (int)a["MT"], NT = (int)a["NT"], KI = (int)a["KI"], TIC = (int)a["TIC"], TOC = (int)a["TOC"];
      int C = px == 0 ? (int)a["C0"] : (int)a["C1"];
      q.task[T_A] = [&, X, py]{                                          // scatter_x
        if (py == 0) X->op(SCATTER, 0, NT, T_B, nullptr, nullptr, C2D::CHAINED); else glue(T_B);
      };
      q.task[T_B] = [&, Y]{ Y->op(BCAST, 0, NT, T_C, nullptr, nullptr, C2D::CHAINED); };   // broadcast_x_down
      q.task[T_C] = [&, X, C, P]{ m.spend(C); X->op(REDUCE, P - 1, (int)a["MT"], T_D, nullptr, nullptr, C2D::CHAINED); };  // compute
      q.task[T_D] = [&, Y, P]{ Y->op(GATHER, P - 1, (int)a["MT"], T_X, nullptr, nullptr, C2D::CHAINED); };  // gather_result
      q.task[T_X] = [&, i, TOC]{ exit_stamp(st1, i, TOC); };                                      // f_exit (f_toc_dev / host toc)
      m.launch(q, t0, [&, Y, i, px, MT, KI, TIC]{
        st0[i] = (long)m.t();                                             // f_tic_dev (U1: host f_tic, main TIC later)
        m.spend(TIC + 2 * KI);
        if (px == 0) Y->op(SCATTER, 0, MT, T_A, nullptr, nullptr, C2D::FIRST); else m.activate(T_A);
      });
    } else if (kernel == "summa"){
      int WX = (int)a["WX"], WY = (int)a["WY"], SC = (int)a["SC"], KI = (int)a["KI"];
      auto do_step = [&, X, Y, i, WX, WY](int call){
        X->op(BCAST, step[i], WX, T_A, nullptr, nullptr, call);
        Y->op(BCAST, step[i], WY, T_B, nullptr, nullptr, C2D::NEXT);
      };
      q.blocked[T_C] = true;                                              // compute starts blocked (y_done unblocks)
      q.task[T_A] = [&]{ glue(T_C); };                                    // x_done: activate compute
      q.task[T_B] = [&m, GL]{ m.spend(GL); m.unblock(T_C); };            // y_done: unblock compute
      q.task[T_C] = [&, i, SC, P, do_step]{                              // compute
        m.spend(SC); step[i]++; m.block(T_C);
        if (step[i] != P) do_step(C2D::CHAINED); else m.activate(T_X);
      };
      q.task[T_X] = [&, i]{ exit_stamp(st1, i, 0); };
      m.launch(q, t0, [&, i, KI, do_step]{ st0[i] = (long)m.t(); m.spend(2 * KI); do_step(C2D::FIRST); });
    } else if (kernel == "t2"){
      int CH = (int)a["CH"], KIX = (int)a["KIX"], KIY = (int)a["KIY"], RPC = (int)a["RPC"], Nx = CH * P;
      int TD2U = (int)a["TD2U"], TD2I = cp.td2;
      X->cp.td2 = Y->cp.td2 = TD2U;                                       // x-run: the y module is not initialised yet
      q.task[T_A] = [&, X, Y, i, KIX, KIY, RPC, Nx, TD2I, CH, P]{        // task_x state machine
        int s = state[i]++;
        if (s == 0){ st0[i] = (long)m.t(); m.spend(KIX); X->op(BCAST, 0, Nx, T_A, nullptr, nullptr, C2D::FIRST); }
        else if (s == 1){ X->op(REDUCE, 0, Nx, T_A, nullptr, nullptr, C2D::CHAINED); }
        else {
          st1[i] = (long)m.t();
          // f_run_y (host launch): task_y starts RPC after this PE's x-run ended (Stage 0c T2_RPC); PE idle meanwhile
          X->cp.td2 = Y->cp.td2 = TD2I;
          X->other_init = Y->other_init = true;                      // task_y initialises the y module
          Pe* qq = m.cur;
          m.launch(*qq, m.t() + RPC, [&, Y, i, KIY, CH]{
            st2[i] = (long)m.t(); m.spend(KIY);
            Y->op(SCATTER, 0, CH, T_B, nullptr, nullptr, C2D::FIRST);
          });
        }
      };
      q.task[T_B] = [&, Y, i, CH]{                                        // task_y state machine
        int s = state[i]++;
        if (s == 3) Y->op(GATHER, 0, CH, T_B, nullptr, nullptr, C2D::CHAINED);
        else st3[i] = (long)m.t();
      };
      m.launch(q, t0, [&]{ m.activate(T_A); });                          // f_run_x
    } else if (kernel == "u4"){
      int CNT = (int)a["CNT"], KIX = (int)a["KIX"], KIY = (int)a["KIY"];
      q.task[T_A] = [&, X, Y, i, CNT, P]{                                // step task
        int s = ++state[i];
        if (s == 1) X->op(BCAST, P - 1, CNT, T_A, nullptr, nullptr, C2D::CHAINED);
        else if (s == 2) Y->op(REDUCE, P - 1, CNT, T_A, nullptr, nullptr, C2D::CHAINED);
        else if (s == 3) Y->op(BCAST, P - 1, CNT, T_A, nullptr, nullptr, C2D::CHAINED);
        else exit_stamp(st1, i, 0);
      };
      m.launch(q, t0, [&, X, i, CNT, KIX, KIY, P]{
        st0[i] = (long)m.t(); m.spend(KIX + KIY);
        X->op(REDUCE, P - 1, CNT, T_A, nullptr, nullptr, C2D::FIRST);
      });
    } else if (kernel == "cal2d"){                                    // Addendum G calibration program (pe2d.csl)
      static const int OPK[4] = {BCAST, SCATTER, GATHER, REDUCE};
      auto cfg = [P](int k, int* op, int* root, int* cnt){ *op = k / 6; int r = (k / 2) % 3; *root = r == 0 ? 0 : r == 1 ? P / 2 : P - 1; *cnt = (k % 2) ? 24 : 4; };
      int xo, xr, xc, yo, yr, yc; cfg(py, &xo, &xr, &xc); cfg(px, &yo, &yr, &yc);
      int IN = INpe.empty() ? (int)a["IN"] : (int)INpe[py * P + px];   // measured per-PE init (calibration input)
      q.task[T_A] = [&, Y, i, yo, yr, yc, CT]{                        // x_done: stamp ts2, call the y op
        st2[i] = (long)m.t() + (CT ? CT->k_ts2 : 0);
        Y->op(OPK[yo], yr, yc, T_B, nullptr, nullptr, C2D::CHAINED);
      };
      q.task[T_B] = [&, i]{ exit_stamp(st3, i, 0); };                  // y_done: ts3
      m.launch(q, t0, [&, X, i, xo, xr, xc, IN]{ st0[i] = (long)m.t(); m.spend(IN); st1[i] = (long)m.t();
                                                   X->op(OPK[xo], xr, xc, T_A, nullptr, nullptr, C2D::FIRST); });
    } else { fprintf(stderr, "unknown kernel\n"); return 1; }
  }
  long limit = 50000000, quiet = 0;
  while ((long)fab.now < limit){ m.step(); if (m.idle()){ if (++quiet > 256) break; } else quiet = 0; }
  bool ok = true;
  auto window = [&](std::vector<long>& s, std::vector<long>& e){
    long emax = LONG_MIN, smin = LONG_MAX;
    for (int y = 0; y < P; y++) for (int x = 0; x < P; x++){
      int i = y * P + x; long E = Eof(x, y) - Lmin;
      if (s[i] < 0 || e[i] < 0){ ok = false; continue; }
      emax = std::max(emax, e[i] - E); smin = std::min(smin, s[i] - E);
    }
    return emax - smin;
  };
  if (kernel == "cal2d"){                                           // per-row x windows, per-column y windows
    printf("{\"ok\": %s, \"wx\": [", ok ? "true" : "false");
    for (int y = 0; y < P; y++){ long emax = LONG_MIN, smin = LONG_MAX;
      for (int x = 0; x < P; x++){ int i = y * P + x; long E = Eof(x, y) - Lmin; emax = std::max(emax, st2[i] - E); smin = std::min(smin, st1[i] - E); }
      printf("%s%ld", y ? ", " : "", emax - smin); }
    printf("], \"wy\": [");
    for (int x = 0; x < P; x++){ long emax = LONG_MIN, smin = LONG_MAX;
      for (int y = 0; y < P; y++){ int i = y * P + x; long E = Eof(x, y) - Lmin; emax = std::max(emax, st3[i] - E); smin = std::min(smin, st2[i] - E); }
      printf("%s%ld", x ? ", " : "", emax - smin); }
    for (int i = 0; i < N; i++) if (st3[i] < 0) ok = false;
    printf("], \"done\": %s}\n", ok ? "true" : "false");
    return ok ? 0 : 2;
  }
  long cs = window(st0, kernel == "t2" ? st3 : st1);
  if (kernel == "t2"){
    long wx = window(st0, st1), wy = window(st2, st3);
    printf("{\"ok\": %s, \"cs\": %ld, \"x\": %ld, \"y\": %ld, \"cycles\": %lu}\n", ok ? "true" : "false", cs, wx, wy, (unsigned long)fab.now);
  } else printf("{\"ok\": %s, \"cs\": %ld, \"cycles\": %lu}\n", ok ? "true" : "false", cs, (unsigned long)fab.now);
  return ok ? 0 : 2;
}
