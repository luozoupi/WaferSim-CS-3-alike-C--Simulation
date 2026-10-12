// Stage 1 harness for M1 Addendum A (switch advance / teardown): simulates one case from `gen.py <tag> --spec`
// with the F1 PE model (src/wse/pe.h) running the pe_ctl.csl program, and prints per-tile observations in the
// sweep_ctl.py format: {"x,y,c": {"inj": [...], "arr": [...], "kinj": [...], "karr": [...]}, ...}.
// Parameters (key=value): fabric hop link buf rin rout turn; PE s0 s0c a0 cpl disp tdd body exit;
// program costs BM (main entry -> first op), BS (seg task -> op), BT (handler -> marker), BX (marker -> exit);
// launch LW (cycles per column), LY (per row).
#include "../../src/wse/pe.h"
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
using namespace wse;

struct Prog { int send_c = 0, tdc = 0, mkc = 0, tdx = 0, p2s = 0, p2r = 0; std::vector<std::pair<int, int>> segs, recv;
              int seg = 0; bool p2s_on = false, p2r_on = false;
              bool legacy = false; int send_n = 0, relay = 0, delay = 0; };   // legacy: pe.csl (M1 base families)

int main(int argc, char** argv){
  Profile pr; PeProfile pp;
  int LW = 2, LY = 0, BM = 12, BS = 10, BT = 6, BX = 4;
  int BE = 0, BD = 0;                                  // task entry (before its stamp); one_done() bookkeeping
  int KC = 0, KP = 0;   // pe_ctl.csl start delay (launch -> main) when the program contains control segments / a P2 send
                        // (measured: senders with ctrl segments start ~18 later, +9 with P2S; code-variant property)
  int BM0 = 0, BR = 5, BRL = 8; double DL = 1.0;      // legacy pe.csl: main -> send, arm, relay costs; delay loop
  for (int i = 2; i < argc; i++){
    char k[64]; double v; if (sscanf(argv[i], "%63[^=]=%lf", k, &v) != 2) continue;
    std::string K(k); int iv = (int)v;
    if (K == "hop") pr.hop = iv; else if (K == "link") pr.link = iv; else if (K == "buf") pr.buf = iv;
    else if (K == "rin") pr.ramp_in_buf = iv; else if (K == "rout") pr.ramp_out_buf = iv; else if (K == "turn") pr.turn = iv;
    else if (K == "s0") pp.s0 = iv; else if (K == "s0c") pp.s0_ctl = iv; else if (K == "a0") pp.a0 = iv;
    else if (K == "cpl") pp.cpl = iv; else if (K == "disp") pp.disp = iv; else if (K == "tdd") pp.td_disp = iv;
    else if (K == "exit") pp.exit_cost = iv; else if (K == "ib") pp.in_bubble = iv;
    else if (K == "KC") KC = iv; else if (K == "KP") KP = iv;
    else if (K == "BE") BE = iv; else if (K == "BD") BD = iv;
    else if (K == "BM") BM = iv; else if (K == "BS") BS = iv; else if (K == "BT") BT = iv; else if (K == "BX") BX = iv;
    else if (K == "LW") LW = iv; else if (K == "LY") LY = iv;
    else if (K == "BM0") BM0 = iv; else if (K == "BR") BR = iv; else if (K == "BRL") BRL = iv; else if (K == "DL") DL = v;
  }
  FILE* fp = fopen(argv[1], "r"); if (!fp){ perror("spec"); return 1; }
  char tag[16]; int W = 0, H = 0;
  struct R5 { int x, y, c, a, b; }; std::vector<R5> routes, sws; struct SWC { int x, y, c, cur, ring, pop; }; std::vector<SWC> swcs;
  std::map<std::pair<int, int>, Prog> prog;
  struct BG { int x, y; long rel; }; std::vector<BG> bgs;   // runtime traffic replay (Addendum C)
  while (fscanf(fp, "%15s", tag) == 1){
    if (!strcmp(tag, "GRID")) fscanf(fp, "%d %d", &W, &H);
    else if (!strcmp(tag, "ROUTE")){ R5 r; fscanf(fp, "%d %d %d %d %d", &r.x, &r.y, &r.c, &r.a, &r.b); routes.push_back(r); }
    else if (!strcmp(tag, "SW")){ int x, y, c, pos, rx, tx; fscanf(fp, "%d %d %d %d %d %d", &x, &y, &c, &pos, &rx, &tx); sws.push_back({x, y, c, pos * 1000 + (rx + 1), tx}); }
    else if (!strcmp(tag, "SWC")){ SWC s; fscanf(fp, "%d %d %d %d %d %d", &s.x, &s.y, &s.c, &s.cur, &s.ring, &s.pop); swcs.push_back(s); }
    else if (!strcmp(tag, "PE")){ int x, y; Prog p; fscanf(fp, "%d %d %d %d %d %d %d %d", &x, &y, &p.send_c, &p.tdc, &p.mkc, &p.tdx, &p.p2s, &p.p2r); prog[{x, y}] = p; }
    else if (!strcmp(tag, "SEG")){ int x, y, k, n; fscanf(fp, "%d %d %d %d", &x, &y, &k, &n); prog[{x, y}].segs.push_back({k, n}); }
    else if (!strcmp(tag, "RECV")){ int x, y, c, n, d; fscanf(fp, "%d %d %d %d %d", &x, &y, &c, &n, &d); prog[{x, y}].recv.push_back({c, n}); prog[{x, y}].delay = d; }
    else if (!strcmp(tag, "BG")){ BG b; if (fscanf(fp, "%d %d %ld", &b.x, &b.y, &b.rel) == 3) bgs.push_back(b); }
    else if (!strcmp(tag, "SEND")){ int x, y, c, n, rl; fscanf(fp, "%d %d %d %d %d", &x, &y, &c, &n, &rl); auto& p = prog[{x, y}]; p.send_c = c; p.send_n = n; p.relay = rl; }
  }
  fclose(fp);
  Fabric fab(W, H, pr);
  for (auto& r : routes) fab.route(r.x, r.y, r.c, r.a, (uint8_t)r.b);
  for (auto& s : sws){ int pos = s.a / 1000, rx = s.a % 1000 - 1; if (rx >= 0) fab.set_switch_in(s.x, s.y, s.c, pos, rx); if (s.b) fab.set_switch_out(s.x, s.y, s.c, pos, (uint8_t)s.b); }
  for (auto& s : swcs){ auto& cf = fab.at(s.x, s.y).cfg[s.c]; cf.cur_in = cf.pos[s.cur].in_valid ? s.cur : 0; cf.cur_out = cf.pos[s.cur].out_valid ? s.cur : 0;
                        cf.ring = s.ring; cf.pop = s.pop; }
  Machine m(fab, pp);
  static const uint32_t CTRLW[7] = {0, 0, 0, ctrl_word(ADVANCE, true), ctrl_word(TEARDOWN, true),
                                    ctrl_word(TEARDOWN, true, RESET, true), ctrl_word(TEARDOWN, true, TEARDOWN, true)};
  bool any_pe = false; for (auto& kv : prog) if (!kv.second.segs.empty() || kv.second.tdc) any_pe = true;
  if (!any_pe) for (auto& kv : prog) kv.second.legacy = true;
  for (auto& kv : prog){
    Pe& q = m.at(kv.first.first, kv.first.second); Prog* P = &kv.second;
    uint64_t t0 = (uint64_t)(LW * kv.first.first + LY * kv.first.second);
    if (P->legacy){                                                     // pe.csl
      q.task[10] = [&m]{ m.stamp(1); };
      for (int k = 0; k < 4; k++) q.task[11 + k] = [&m, P, k, BRL]{
        m.stamp(3 + k);
        if (k == 0 && P->relay){ m.spend(BRL); m.fabout(P->send_c, P->send_n, 10); }
      };
      m.launch(q, t0, [&m, P, BM0, BR, DL]{
        m.stamp(0); m.spend(BM0);
        if (P->send_n && !P->relay) m.fabout(P->send_c, P->send_n, 10);
        if (!P->recv.empty()){
          m.spend((int)(P->delay * DL)); m.stamp(2); m.spend(BR);
          for (size_t k = 0; k < P->recv.size(); k++) m.fabin(P->recv[k].first, P->recv[k].second, 11 + (int)k);
        }
      });
      continue;
    }
    q.task[10] = [&m, P, BS, BE, BD]{                                   // seg_task
      m.spend(BE);
      if (P->p2s_on){ P->p2s_on = false; m.stamp(12); m.spend(BD); return; }
      if (P->seg > 0) m.stamp(P->seg);
      if (P->seg >= (int)P->segs.size()){ m.spend(BD); return; }
      auto [k, n] = P->segs[P->seg++];
      m.spend(BS);
      if (k == 1) m.fabout(P->send_c, n, 10);
      else if (k == 2) m.fabout(P->send_c, n, 10, 1);
      else m.fabout_ctl(P->send_c, CTRLW[k], 10);
    };
    q.task[11] = [&m, P, BE, BD]{ m.spend(BE); if (P->p2r_on){ P->p2r_on = false; m.stamp(13); } else m.stamp(9); m.spend(BD); };
    q.task[12] = [&m, BE, BD]{ m.spend(BE); m.stamp(10); m.spend(BD); };
    if (P->tdc) q.td_handler[P->tdc] = [&m, P, BT, BX, BD]{
      m.stamp(11); m.spend(BT);
      if (P->mkc) m.fabout(P->mkc, 1, -1);
      if (P->tdx){
        m.spend(BX); m.teardown_exit(P->tdc);
        if (P->p2s){ P->p2s_on = true; m.fabout(P->send_c, P->p2s, 10); }
        if (P->p2r){ P->p2r_on = true; m.fabin(P->recv[0].first, P->p2r, 11); }
      }
      m.spend(BD);
    };
    bool has_ctl = false; for (auto& sg : P->segs) if (sg.first >= 3) has_ctl = true;
    t0 += (has_ctl ? KC : 0) + (P->p2s ? KP : 0);
    m.launch(q, t0, [&m, P, BM]{                                        // main
      m.stamp(0); m.spend(BM);
      if (P->recv.size() > 0) m.fabin(P->recv[0].first, P->recv[0].second, 11);
      if (P->recv.size() > 1) m.fabin(P->recv[1].first, P->recv[1].second, 12);
      if (!P->segs.empty()) m.activate(10);
    });
  }
  // runtime memcpy traffic: a wavelet recorded at (x, y) `rel` cycles after the case's first injection (simfab)
  // crossed the eastbound link from (x-1, y); reserved relative to the model's own first injection
  bool armed = bgs.empty();
  long limit = 2000000; long quiet = 0;
  while ((long)fab.now < limit){
    m.step();
    if (!armed && !fab.trace.empty()){
      long t_first = -1;
      for (auto& tr : fab.trace) if (tr.link == R){ t_first = (long)tr.cycle; break; }
      if (t_first >= 0){
        armed = true;
        for (auto& b : bgs){ long c = t_first + b.rel - pr.hop; if (b.x >= 1 && c >= 0) fab.reserve(b.x - 1, b.y, E, (uint64_t)c); }
      }
    }
    if (m.idle()){ if (++quiet > 64) break; } else quiet = 0;
  }
  // observations: first record per (tile, colour, ident)
  std::map<std::tuple<int, int, int, uint64_t>, std::pair<uint64_t, int>> first;   // -> (cycle, ramp*2 + ctrl)
  for (auto& tr : fab.trace){
    auto k = std::make_tuple(tr.x, tr.y, tr.colour, tr.ident);
    int cls = (tr.link == R ? 2 : 0) + tr.ctrl;
    auto it = first.find(k);
    if (it == first.end() || tr.cycle < it->second.first) first[k] = {tr.cycle, cls};
  }
  std::map<std::string, std::array<std::vector<uint64_t>, 4>> obs;   // inj, arr, kinj, karr
  for (auto& kv : first){
    auto [x, y, c, id] = kv.first; int cls = kv.second.second;
    int slot = (cls & 1 ? 2 : 0) + (cls & 2 ? 0 : 1);
    obs[std::to_string(x) + "," + std::to_string(y) + "," + std::to_string(c)][slot].push_back(kv.second.first);
  }
  static const char* nm[4] = {"inj", "arr", "kinj", "karr"};
  printf("{\"obs\": {"); bool f1 = true;
  for (auto& kv : obs){
    printf("%s\"%s\": {", f1 ? "" : ", ", kv.first.c_str()); f1 = false;
    for (int s = 0; s < 4; s++){
      auto v = kv.second[s]; std::sort(v.begin(), v.end());
      printf("%s\"%s\": [", s ? ", " : "", nm[s]);
      for (size_t i = 0; i < v.size(); i++) printf("%s%lu", i ? ", " : "", (unsigned long)v[i]);
      printf("]");
    }
    printf("}");
  }
  printf("}, \"tsc\": {"); f1 = true;
  for (auto& kv : prog){
    Pe& q = m.at(kv.first.first, kv.first.second);
    printf("%s\"%d,%d\": [", f1 ? "" : ", ", q.x, q.y); f1 = false;
    for (int s = 0; s < 16; s++) printf("%s%ld", s ? ", " : "", (long)q.stamp[s]);
    printf("]");
  }
  printf("}, \"cycles\": %lu}\n", (unsigned long)fab.now);
  return 0;
}
