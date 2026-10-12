// wsesim Stage 1: deterministic wavelet-level WSE fabric model (M2).
// Tiles x 24 colours.  Each colour has one rx direction and a tx set over {RAMP, N, S, E, W} (fan-out =
// multicast).  Wavelets are 32-bit, header-less, carry colour + ctrl bit.  Per tile and colour: one input FIFO
// (depth BUF; RAMP_IN_BUF for ramp injections) with per-colour credits.  A router accepts a colour's wavelet only
// from the input its current switch position selects and not while the colour is in teardown mode; otherwise the
// wavelet waits upstream.  Wavelets already in the FIFO drain in order across switch changes.  Control commands
// act in two places, matching WSE's separate current input and output switch positions: on ACCEPTANCE (input
// side: ADVANCE/RESET move the input position, TEARDOWN stops further input) and on FORWARDING (output side:
// ADVANCE/RESET move the output position, TEARDOWN puts the colour in teardown mode and raises the PE handler).
// (simfab sa_rx / sa_chain / td traces, topic-06, collectives_2d gather teardown sequence; Addendum A)  Per tile and output port: one wavelet per
// LINK cycles, round-robin among colours.  A wavelet moves only when every tx target has space (all-or-nothing
// multicast).  Link latency HOP.  Single-threaded, cycle-stepped over an active set => deterministic.
#pragma once
#include <cstdint>
#include <cstdio>
#include <deque>
#include <vector>
#include <array>
#include <algorithm>
#include <functional>
#include <unordered_set>

namespace wse {

enum Dir : int { R = 0, N = 1, S = 2, E = 3, W = 4, NDIR = 5 };
static inline const char* dname(int d){ static const char* n[] = {"R", "N", "S", "E", "W"}; return n[d]; }
static inline int opposite(int d){ return d == N ? S : d == S ? N : d == E ? W : d == W ? E : R; }
constexpr int NCOL = 24;

struct Profile {                 // simfab-2.10 defaults; every value is replaced by M1 measurements
  int hop = 2;                   // cycles from leaving a router to arriving at the neighbour's router
  int link = 1;                  // cycles per wavelet per output port
  int buf = 4;                   // wavelets per (tile, colour) input buffer
  int ramp_in_buf = 4;           // PE output queue -> router
  int ramp_out_buf = 4;          // router -> PE input queue (per colour)
  int turn = 0;                  // extra cycles when a wavelet changes direction (tx != opposite(rx))
};

struct Wavelet { uint32_t data; uint8_t colour; uint8_t ctrl; uint64_t ident; uint64_t ready; uint8_t adv = 0; };
// adv: sideband of a fabout DSD with .advance_switch -- the injecting router advances its own switch when this
// (last) wavelet enters it from the ramp; nothing extra travels on the wire (sa_chain traces, Addendum A)

// control wavelet commands (collectives_2d ctrl_wavelet.csl): 3 bits each {no_ce, type:2}; cmd0 at bit 22, cmd1 at 25
enum Cmd : int { NOP = 0, ADVANCE = 1, RESET = 2, TEARDOWN = 3 };
enum PopMode : int { NO_POP = 0, ALWAYS_POP = 1, POP_ON_ADVANCE = 2, POP_ON_ADVANCE_OR_NOP = 3 };
static inline int cmd_type(uint32_t w, int k){ return (w >> (22 + 3 * k)) & 3; }
static inline bool cmd_no_ce(uint32_t w, int k){ return (w >> (22 + 3 * k + 2)) & 1; }
static inline uint32_t ctrl_word(int t0, bool nce0, int t1 = NOP, bool nce1 = false){
  return ((uint32_t)(t0 | (nce0 << 2)) << 22) | ((uint32_t)(t1 | (nce1 << 2)) << 25);
}
constexpr int SW_INVALID = -2;

struct SwitchPos { int in = SW_INVALID; uint8_t out = 0; bool in_valid = false, out_valid = false; };
struct Filter { bool on = false; int pass_n = 0, drop_n = 0, phase = 0; };   // counter filter on CE delivery

struct ColourCfg {
  int rx = -1; uint8_t tx = 0;                       // pos0 (base route); tx: bit per Dir
  std::array<SwitchPos, 4> pos{};                    // pos1..pos3 (index 0 unused)
  int cur_in = 0, cur_out = 0;                       // current input / output switch positions
  bool ring = false; int pop = NO_POP;
  bool teardown = false;                             // colour in teardown mode: holds traffic
  bool td_in = false;                                // a TEARDOWN was accepted: input closed until it is forwarded
  Filter filt;
  int eff_rx() const { return cur_in == 0 ? rx : pos[cur_in].in; }
  uint8_t eff_tx() const { return cur_out == 0 ? tx : pos[cur_out].out; }
};

struct Tile {
  std::array<ColourCfg, NCOL> cfg;
  std::array<std::deque<Wavelet>, NCOL> in;          // input FIFO per colour
  std::array<std::deque<Wavelet>, NCOL> to_pe;       // delivered to the PE (ramp out), per colour
  std::array<uint64_t, NDIR> port_free{};            // next cycle an output port may send
  std::array<int, NDIR> rr{};                        // round-robin pointer per output port
};

struct TraceRec { uint64_t cycle; int x, y; int colour; uint64_t ident; int link; uint8_t ctrl = 0; };
struct TdEvent { uint64_t cycle; int x, y, colour; };   // router entered teardown mode (PE teardown handler)

class Fabric {
 public:
  int GW, GH; Profile p; uint64_t now = 0; uint64_t next_ident = 1;   // grid size (not the Dir enum)
  std::vector<Tile> t;
  std::vector<TraceRec> trace; bool tracing = true;
  std::vector<TdEvent> td_events;                    // consumed by the PE model
  std::function<void(int, int, int, uint64_t)> on_teardown;   // optional callback (x, y, colour, cycle)
  std::unordered_set<uint64_t> reserved;            // (tile, port, cycle): output port used by background traffic
  Fabric(int w, int h, Profile pr) : GW(w), GH(h), p(pr), t(w * h) {}
  static uint64_t rkey(int tile, int port, uint64_t cyc){ return ((uint64_t)(tile * NDIR + port) << 36) | cyc; }
  // background (runtime) wavelet crossing the link out of (x, y) in direction port at cycle cyc
  void reserve(int x, int y, int port, uint64_t cyc){ reserved.insert(rkey(y * GW + x, port, cyc)); }
  Tile& at(int x, int y){ return t[y * GW + x]; }
  void route(int x, int y, int c, int rx, uint8_t tx){ at(x, y).cfg[c].rx = rx; at(x, y).cfg[c].tx = tx; }
  // runtime switch / teardown configuration (collectives_2d configure_*_network, tile_config)
  void set_switch_in(int x, int y, int c, int pos, int dir){ auto& p = at(x, y).cfg[c].pos[pos]; p.in = dir; p.in_valid = true; }
  void set_switch_out(int x, int y, int c, int pos, uint8_t mask){ auto& p = at(x, y).cfg[c].pos[pos]; p.out = mask; p.out_valid = true; }
  void invalidate_switches(int x, int y, int c){ auto& cf = at(x, y).cfg[c]; for (auto& p : cf.pos) p = SwitchPos(); cf.cur_in = cf.cur_out = 0; }
  void set_pop(int x, int y, int c, int mode){ at(x, y).cfg[c].pop = mode; }
  void set_ring(int x, int y, int c, bool on){ at(x, y).cfg[c].ring = on; }
  void teardown_exit(int x, int y, int c){ at(x, y).cfg[c].teardown = false; at(x, y).cfg[c].td_in = false; }
  void set_filter(int x, int y, int c, bool on, int pass_n = 0, int drop_n = 0, int phase = 0){ at(x, y).cfg[c].filt = {on, pass_n, drop_n, phase}; }
  // local switch advance after a DSD's last wavelet (fabout .advance_switch = true)
  void local_advance(int x, int y, int c){ advance_side(at(x, y).cfg[c], true); advance_side(at(x, y).cfg[c], false); }

  // PE side: inject a wavelet from the PE (ramp in); false if the ramp buffer is full
  bool inject(int x, int y, int c, uint32_t data, uint8_t ctrl = 0, uint8_t adv = 0){
    Tile& tl = at(x, y);
    ColourCfg& cf = tl.cfg[c];
    if (cf.teardown || cf.td_in || cf.eff_rx() != R) return false;   // ramp not selected: output queue backpressure
    if ((int)tl.in[c].size() >= p.ramp_in_buf) return false;
    Wavelet w{data, (uint8_t)c, ctrl, next_ident++, now, adv};
    accept(tl, c, w);
    if (adv) advance_side(cf, true);                             // .advance_switch: input side at ramp injection
    if (tracing) trace.push_back({now, x, y, c, w.ident, R, ctrl});
    return true;
  }
  // PE side: pop a delivered wavelet of colour c (ramp out)
  bool deliver(int x, int y, int c, Wavelet* w){
    auto& q = at(x, y).to_pe[c];
    if (q.empty() || q.front().ready > now) return false;
    if (w) *w = q.front();
    q.pop_front(); return true;
  }
  size_t delivered_pending(int x, int y, int c){ return at(x, y).to_pe[c].size(); }
  bool can_deliver(int x, int y, int c){ auto& q = at(x, y).to_pe[c]; return !q.empty() && q.front().ready <= now; }
  bool can_inject(int x, int y, int c){ Tile& tl = at(x, y); return !tl.cfg[c].teardown && tl.cfg[c].eff_rx() == R && (int)tl.in[c].size() < p.ramp_in_buf; }

  // one fabric cycle
  void step(){
    for (int y = 0; y < GH; y++) for (int x = 0; x < GW; x++) step_tile(x, y);
    now++;
  }

 private:
  bool neighbour(int x, int y, int d, int* nx, int* ny){
    int X = x + (d == E) - (d == W), Y = y + (d == S) - (d == N);
    if (X < 0 || Y < 0 || X >= GW || Y >= GH) return false;
    *nx = X; *ny = Y; return true;
  }
  bool target_has_space(int x, int y, int c, int d){
    if (d == R) return (int)at(x, y).to_pe[c].size() < p.ramp_out_buf;
    int nx, ny; if (!neighbour(x, y, d, &nx, &ny)) return false;
    Tile& n = at(nx, ny);
    // simfab: a router accepts a colour's wavelet only on the input its current switch position selects, and not
    // while the colour is in teardown mode; otherwise the wavelet waits upstream (sa_rx / td traces, Addendum A)
    if (n.cfg[c].teardown || n.cfg[c].td_in || n.cfg[c].eff_rx() != opposite(d)) return false;
    return (int)n.in[c].size() < p.buf;                          // per-colour credits
  }
  static void advance_side(ColourCfg& cf, bool is_in){
    int cur = is_in ? cf.cur_in : cf.cur_out, nxt = cur;
    for (int k = 1; k <= 3; k++){
      int n = cur + k;
      if (n > 3){ if (!cf.ring) break; n -= 4; }
      if (n == 0){ nxt = 0; break; }
      if (is_in ? cf.pos[n].in_valid : cf.pos[n].out_valid){ nxt = n; break; }
    }
    (is_in ? cf.cur_in : cf.cur_out) = nxt;
  }
  // a wavelet enters a router's FIFO: input-side effect of a control wavelet's cmd0
  void accept(Tile& tl, int c, const Wavelet& w){
    tl.in[c].push_back(w);
    if (!w.ctrl) return;
    ColourCfg& cf = tl.cfg[c]; int t0 = cmd_type(w.data, 0);
    if (t0 == ADVANCE) advance_side(cf, true);
    else if (t0 == RESET) cf.cur_in = 0;
    else if (t0 == TEARDOWN) cf.td_in = true;
  }
  void step_tile(int x, int y){
    Tile& tl = at(x, y);
    for (int c = 0; c < NCOL; c++){
      ColourCfg& cf = tl.cfg[c];
      if (tl.in[c].empty()) continue;
      if (cf.teardown) continue;                                   // teardown mode holds the colour
      int rxe = cf.eff_rx();
      Wavelet w = tl.in[c].front();
      if (w.ready > now) continue;
      uint8_t tx = cf.eff_tx();
      if (!tx) continue;
      uint8_t need = need_mask(cf, w);
      bool ok = can_move(x, y, c, need);
      for (int d = 0; d < NDIR && ok; d++) if ((need & (1 << d)) && !rr_allows(x, y, d, c)) ok = false;
      if (!ok) continue;
      tl.in[c].pop_front();
      if (!w.ctrl && (tx & (1 << R)) && cf.filt.on) filter_pass(cf.filt, true);   // count the wavelet
      int extra = (rxe >= 0 && rxe != R && !(tx & (1 << opposite(rxe)))) ? p.turn : 0;
      Wavelet o = w;
      if (w.ctrl){                                                 // pop the command for downstream routers
        int t0 = cmd_type(w.data, 0);
        bool pop = cf.pop == ALWAYS_POP || (cf.pop == POP_ON_ADVANCE && t0 == ADVANCE) ||
                   (cf.pop == POP_ON_ADVANCE_OR_NOP && (t0 == ADVANCE || t0 == NOP));
        if (pop) o.data = (w.data & ~(0x3Fu << 22)) | (((w.data >> 25) & 7u) << 22);
      }
      for (int d = 0; d < NDIR; d++) if (need & (1 << d)){
        tl.port_free[d] = now + p.link;
        tl.rr[d] = (c + 1) % NCOL;
        Wavelet q = (d == R) ? w : o; q.adv = 0;
        if (d == R){ q.ready = now; tl.to_pe[c].push_back(q); }
        else {
          int nx, ny; neighbour(x, y, d, &nx, &ny);
          q.ready = now + p.hop + extra;
          accept(at(nx, ny), c, q);
          if (tracing) trace.push_back({q.ready, nx, ny, c, q.ident, d, q.ctrl});
        }
      }
      if (w.adv) advance_side(cf, false);                          // .advance_switch: output side when forwarded
      if (w.ctrl){                                                 // output-side effect of cmd0 after forwarding
        int t0 = cmd_type(w.data, 0);
        if (t0 == ADVANCE) advance_side(cf, false);
        else if (t0 == RESET) cf.cur_out = 0;
        else if (t0 == TEARDOWN){
          cf.teardown = true; cf.td_in = false; td_events.push_back({now, x, y, c});
          if (on_teardown) on_teardown(x, y, c, now);
        }
      }
    }
  }
  // counter filter: pass pass_n wavelets to the CE, then drop drop_n, periodic; commit=false only queries
  static bool filter_pass(Filter& f, bool commit){
    int period = f.pass_n + f.drop_n;
    bool pass = period <= 0 || (f.phase % period) < f.pass_n;
    if (commit) f.phase = (f.phase + 1) % std::max(period, 1);
    return pass;
  }
  // ports a head wavelet needs: tx set minus the ramp for no_ce control wavelets and filtered data
  uint8_t need_mask(ColourCfg& cf, const Wavelet& w){
    uint8_t need = cf.eff_tx();
    if (w.ctrl && cmd_no_ce(w.data, 0)) need &= ~(1 << R);
    if (!w.ctrl && (need & (1 << R)) && cf.filt.on && !filter_pass(cf.filt, false)) need &= ~(1 << R);
    return need;
  }
  // every needed port free and every target buffer has space (per-colour credits)
  bool can_move(int x, int y, int c, uint8_t need){
    Tile& tl = at(x, y);
    for (int d = 0; d < NDIR; d++) if (need & (1 << d)){
      if (tl.port_free[d] > now || !target_has_space(x, y, c, d)) return false;
      if (!reserved.empty() && d != R && reserved.count(rkey(y * GW + x, d, now))) return false;
    }
    return true;
  }
  // round-robin: a colour may use port d this cycle unless another colour earlier in RR order wants d and can
  // move now (a colour blocked by its own downstream credits does not hold the port)
  bool rr_allows(int x, int y, int d, int c){
    Tile& tl = at(x, y);
    for (int k = 0; k < NCOL; k++){
      int cc = (tl.rr[d] + k) % NCOL;
      if (cc == c) return true;
      if (tl.in[cc].empty() || tl.in[cc].front().ready > now || tl.cfg[cc].teardown) continue;
      uint8_t need = need_mask(tl.cfg[cc], tl.in[cc].front());
      if ((need & (1 << d)) && can_move(x, y, cc, need)) return false;
    }
    return true;
  }
};

}  // namespace wse
