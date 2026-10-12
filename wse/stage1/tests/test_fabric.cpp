// Stage 1 fabric-engine unit tests (M2b): switch positions, control wavelets, pop modes, no_ce, teardown,
// .advance_switch sideband, counter filter.  Build: g++ -O2 -std=c++17 -o /tmp/tf test_fabric.cpp && /tmp/tf
#include "../../../src/wse/fabric.h"
using namespace wse;
static int fails = 0;
#define CHECK(c, msg) do { if (!(c)){ printf("FAIL %s\n", msg); fails++; } else printf("ok   %s\n", msg); } while (0)
static long last_data(Fabric& f, int x, int y, int c){ Wavelet w; long v = -1; while (f.deliver(x, y, c, &w)) if (!w.ctrl) v = w.data; return v; }
static void run(Fabric& f, int n){ for (int i = 0; i < n; i++) f.step(); }

int main(){
  Profile p;
  {  // topic-06-switches (SDK tutorial): expected East 0, South 2, North 4, West 6
    Fabric f(3, 3, p);
    f.route(1, 1, 0, R, 1 << N);
    f.set_switch_out(1, 1, 0, 1, 1 << W); f.set_switch_out(1, 1, 0, 2, 1 << E); f.set_switch_out(1, 1, 0, 3, 1 << S);
    f.at(1, 1).cfg[0].cur_out = 1; f.set_ring(1, 1, 0, true);
    f.route(1, 0, 0, S, 1 << R); f.route(0, 1, 0, E, 1 << R); f.route(2, 1, 0, W, 1 << R); f.route(1, 2, 0, N, 1 << R);
    std::vector<std::pair<uint32_t, int>> seq;
    for (int k = 0; k < 4; k++){ seq.push_back({ctrl_word(ADVANCE, true), 1}); seq.push_back({(uint32_t)(2 * k), 0}); }
    size_t i = 0;
    for (int cyc = 0; cyc < 100; cyc++){ if (i < seq.size() && f.inject(1, 1, 0, seq[i].first, seq[i].second)) i++; f.step(); }
    CHECK(last_data(f, 2, 1, 0) == 0 && last_data(f, 1, 2, 0) == 2 && last_data(f, 1, 0, 0) == 4 && last_data(f, 0, 1, 0) == 6,
          "topic-06 replica: E0 S2 N4 W6");
  }
  {  // ctrl ADVANCE routed on the current position, then the tx switch flips
    Fabric f(2, 2, p);
    f.route(0, 0, 1, R, 1 << E); f.set_switch_out(0, 0, 1, 1, 1 << S);
    f.route(1, 0, 1, W, 1 << R); f.route(0, 1, 1, N, 1 << R);
    f.inject(0, 0, 1, ctrl_word(ADVANCE, false), 1); run(f, 3);
    f.inject(0, 0, 1, 42); run(f, 10);
    CHECK(f.delivered_pending(1, 0, 1) == 1 && f.delivered_pending(0, 1, 1) == 1, "ctrl goes east (with CE), data then goes south");
  }
  {  // teardown holds the colour until exit; no_ce TD is not delivered
    Fabric g(3, 1, p);
    for (int x = 0; x < 3; x++) g.route(x, 0, 2, x == 0 ? R : W, x == 2 ? (1 << R) : (1 << E));
    g.inject(0, 0, 2, ctrl_word(TEARDOWN, true), 1); run(g, 6);
    bool in1 = g.inject(0, 0, 2, 7); run(g, 10);
    CHECK(g.td_events.size() == 3 && g.delivered_pending(2, 0, 2) == 0 && !in1, "TD reaches 3 routers, colour held (ramp refused), TD not delivered");
    for (int x = 0; x < 3; x++) g.teardown_exit(x, 0, 2);
    g.inject(0, 0, 2, 7); run(g, 10);
    CHECK(g.delivered_pending(2, 0, 2) == 1, "data flows after teardown exit");
  }
  {  // ALWAYS_POP at the guard router: TD+RESET -> guard tears down, downstream root receives RESET (gather idiom)
    Fabric f(3, 1, p);   // tile 2 sends west; tile 1 = guard (always pop); tile 0 = root with rx switch at pos1
    f.route(2, 0, 3, R, 1 << W); f.route(1, 0, 3, E, 1 << W); f.set_pop(1, 0, 3, ALWAYS_POP);
    f.route(0, 0, 3, W, 1 << R); f.set_switch_in(0, 0, 3, 1, E); f.at(0, 0).cfg[3].cur_in = 1;
    f.inject(2, 0, 3, ctrl_word(TEARDOWN, true, RESET, true), 1); run(f, 12);
    CHECK(f.at(2, 0).cfg[3].teardown && f.at(1, 0).cfg[3].teardown && !f.at(0, 0).cfg[3].teardown && f.at(0, 0).cfg[3].cur_in == 0,
          "guard pops: tiles 2,1 torn down; root reset to pos0 and not torn down");
  }
  {  // .advance_switch sideband: tile 1 sends its own data, then becomes a W->E conduit for tile 0
    Fabric f(3, 1, p);
    f.route(0, 0, 1, R, 1 << E); f.route(1, 0, 1, R, 1 << E); f.set_switch_in(1, 0, 1, 1, W); f.route(2, 0, 1, W, 1 << R);
    int s0 = 0, s1 = 0; std::vector<uint32_t> got; Wavelet w;
    for (int cyc = 0; cyc < 60; cyc++){
      if (s0 < 4 && f.inject(0, 0, 1, 100 + s0)) s0++;
      if (s1 < 4 && f.inject(1, 0, 1, 200 + s1, 0, s1 == 3)) s1++;
      f.step();
      while (f.deliver(2, 0, 1, &w)) got.push_back(w.data);
    }
    bool ok = got.size() == 8; for (int k = 0; k < 4 && ok; k++) ok = got[k] == (uint32_t)(200 + k) && got[4 + k] == (uint32_t)(100 + k);
    CHECK(ok, "advance_switch chain: tile 1 data first, then tile 0 data (gather order)");
  }
  {  // counter filter: pass 2, drop 2 on CE delivery (scatter idiom)
    int s = 0;
    Fabric h(2, 1, p);
    h.route(0, 0, 1, R, 1 << E); h.route(1, 0, 1, W, 1 << R); h.set_filter(1, 0, 1, true, 2, 2, 0);
    std::vector<uint32_t> got;
    for (int cyc = 0; cyc < 40; cyc++){ if (s < 8 && h.inject(0, 0, 1, s)) s++; h.step(); Wavelet w; while (h.deliver(1, 0, 1, &w)) got.push_back(w.data); }
    CHECK(got == std::vector<uint32_t>({0, 1, 4, 5}), "counter filter pass 2 / drop 2");
  }
  printf("%s (%d failures)\n", fails ? "FAILED" : "ALL PASS", fails);
  return fails != 0;
}
