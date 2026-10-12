// wsesim Stage 1 (M5): <collectives_2d> (SDK 2.10, wse/refs/c2d_lib/collectives_2d/pe.csl) ported to the F1 PE
// model on the wavelet-level fabric.  The port follows pe.csl function by function: the op call configures the
// router (routes, switch positions, pop mode, counter filter) and exits teardown; an FSM task moves the data with
// fabout/fabin DSDs; the root(s) end the op with teardown control wavelets; teardown handlers activate C_LOCK,
// which runs only once the op has finished locally and then activates the user callback.  The data path,
// switch hand-offs, teardown propagation and backpressure are produced by the fabric; only CPU costs of task
// bodies come from C2dProfile.
#pragma once
#include "pe.h"
#include <fstream>
#include <sstream>
#include <string>
#include <unordered_map>

namespace wse {

// Addendum D: measured CPU costs of the library, value = a + b * count, keyed
// kind|rootpos|class|parity[|k] (wse/bench/c2dcal/build_costs.py).  Missing keys fall back to the other parity,
// then to the Addendum B constants.
struct CostTable {
  std::unordered_map<std::string, std::array<double, 3>> v;   // a + b * count + c * P
  bool loaded = false;
  int k_ts2 = 0;                 // final callback: start -> ts2 read (cfg1 entries include it)
  int tail = 6;                  // an activation issued this many cycles before a body's end (ACTVT + return)
  bool load(const std::string& path){                       // lines: key a b [c]
    std::ifstream f(path); std::string line;
    while (std::getline(f, line)){
      std::istringstream is(line); std::string k; double a = 0, b = 0, c = 0;
      if (!(is >> k >> a >> b)) continue;
      if (!(is >> c)) c = 0;
      v[k] = {a, b, c};
    }
    loaded = !v.empty(); return loaded;
  }
  bool get(const std::string& k, int count, int P, double* out) const {
    auto it = v.find(k); if (it == v.end()) return false;
    *out = it->second[0] + it->second[1] * count + it->second[2] * P; return true;
  }
};

struct C2dProfile {              // PE CPU costs (not produced by the fabric)
  int init = 25;                 // mpi.init()                                   (Stage 0: K_INIT)
  int cfg = 101;                 // op call: block, clear filter/switch, configure, exit teardown (Stage 0c: C_CFG)
  int act = 55;                  // issuing task end -> first wavelet offered    (Stage 0c: A_ACT)
  int tdd = 42;                  // root: last data wavelet -> teardown offered  (Stage 0c: T_TDD)
  int handler = 2;               // teardown handler body (activate C_LOCK)
  int lock = 2;                  // f_lock body (activate the callback)
  double copy = 1.0;             // local mem -> mem copy, cycles per word (scatter / gather root)
  double fadd = 1.0;             // local mem fadds, cycles per word (reduce root)
  int init2 = 9;                 // init() of a second module on the PE (coll2d init_max 34 - 25)
  int td2 = 6;                   // teardown handler cost per event with a second initialised module (Stage 0c: Q_TD2_INIT)
  int td2x = 0;                  // Addendum G: extra cycles per teardown event for two-module (prefixed) table entries
  int dcy = 0;                   // Addendum G: extra cycles per y-dimension op call
};

enum C2dKind { BCAST = 0, SCATTER = 1, GATHER = 2, REDUCE = 3 };

class C2D {                      // one <collectives_2d/pe> module instance (one dimension) on one PE
 public:
  Machine& m; Fabric& f; Pe& pe; C2dProfile cp; int dim;
  int pe_id, NP, C0, C1, FSM, LOCK, POS, NEG;
  int root = 0, count = 0, kind = BCAST, callback = 10;
  enum { CONFIGURE, TRANSFER, CALLBACK } state = CONFIGURE;
  int counter = 0, td_reduce_state = 0, num_tds = 0;
  int neg_c, pos_c;
  bool two_modules = false;      // another <collectives_2d/pe> instance on this PE (coll2d)
  bool other_init = false;       // ... and it is initialised (Addendum G: selects the y. / x2. cost entries)
  uint32_t* sb = nullptr; uint32_t* rb = nullptr;   // optional user buffers (payload tracking; integer "fadds")
  const CostTable* ct = nullptr;                     // Addendum D cost table (nullptr: Addendum B constants)
  std::string key; int fsm_k = 0, td_k = 0;          // cost key of the current op; invocation counters

  C2D(Machine& mm, Pe& p, int dim_, C2dProfile c) : m(mm), f(mm.f), pe(p), cp(c), dim(dim_) {
    pe_id = dim ? pe.y : pe.x; NP = dim ? f.GH : f.GW;
    C0 = dim ? 4 : 0; C1 = dim ? 5 : 1; FSM = dim ? 16 : 14; LOCK = dim ? 17 : 15;
    POS = dim ? S : E; NEG = dim ? N : W;
    int cs[2] = {C0, C1}; neg_c = cs[pe_id % 2]; pos_c = cs[(pe_id + 1) % 2];
    // comptime: C0 / C1 start in teardown mode, broadcast network rooted at 0, no-op counter filter
    auto& c0 = f.at(pe.x, pe.y).cfg[C0];
    if (pe_id == 0) f.route(pe.x, pe.y, C0, R, 1 << POS);
    else if (pe_id == NP - 1) f.route(pe.x, pe.y, C0, NEG, 1 << R);
    else f.route(pe.x, pe.y, C0, NEG, (1 << R) | (1 << POS));
    c0.teardown = true;
    f.route(pe.x, pe.y, C1, R, 1 << R); f.at(pe.x, pe.y).cfg[C1].teardown = true;
    pe.task[FSM] = [this]{ fsm(); };
    pe.task[LOCK] = [this]{ m.spend(ct ? (int)cost0("lock", cp.lock) : cp.lock); m.activate(callback); };
    pe.td_handler[C0] = [this]{
      int len = td_cost(); m.spend(len - tailof(len));
      if (kind == REDUCE){ if (++num_tds == 2){ num_tds = 0; m.activate(LOCK); } }
      else m.activate(LOCK);
      m.spend(tailof(len));
    };
    pe.td_handler[C1] = [this]{
      int len = td_cost(); m.spend(len - tailof(len));
      if (++num_tds == 2){ num_tds = 0; m.activate(LOCK); }
      m.spend(tailof(len));
    };
  }

  void init(bool second = false){ m.spend(second ? cp.init2 : cp.init); }

  // user-facing calls (run inside the calling task body)
  // first: called from main right after the ts1 stamp; otherwise from the callback task (chained op)
  enum Call { FIRST = 0, CHAINED = 1, NEXT = 2 };   // from main after ts1 / from the callback task / 2nd call in a body
  void op(int k, int root_, int count_, int cb, uint32_t* send_buf = nullptr, uint32_t* recv_buf = nullptr, int call = FIRST){
    sb = send_buf; rb = recv_buf;
    m.block(LOCK);
    kind = k; root = root_; count = count_; callback = cb; state = CONFIGURE; counter = 0;
    fsm_k = td_k = 0; key = cost_key();
    double c;
    if (ct && call == FIRST && lookup("cfg1|" + key, &c)) m.spend(std::max(0, (int)c - ct->k_ts2 - m.pp.disp));
    else if (ct && call == CHAINED && lookup("cfgn|" + key, &c)) m.spend(std::max(0, (int)(c + cost0("done", 25)) - m.pp.disp));
    else if (ct && call == NEXT && lookup("cfgn|" + key, &c)) m.spend((int)c);
    else if (ct && lookup("cfg1|" + key, &c)) m.spend(std::max(0, (int)c - ct->k_ts2 - m.pp.disp));   // cfgn unmeasured
    else m.spend(cp.cfg);
    if (ct && dim == 1 && two_modules && other_init) m.spend(cp.dcy);   // Addendum G: two-module y-ops only
    int x = pe.x, y = pe.y;
    m.cfg([this, x, y]{ clear_filter_and_switch(x, y); configure(x, y); });
    m.teardown_exit(C0); if (kind == REDUCE) m.teardown_exit(C1);
    state = TRANSFER; m.activate(FSM);
  }

 public:                       // (helpers are public: harnesses read table costs)
  int fsm_body() const { return std::max(0, cp.act - m.pp.disp - m.pp.s0); }
  int cb_body() const { return std::max(0, cp.tdd - m.pp.cpl - m.pp.disp - m.pp.s0_ctl); }
  uint8_t bit(int d) const { return (uint8_t)(1 << d); }

  void clear_filter_and_switch(int x, int y){
    f.set_filter(x, y, C0, false); f.invalidate_switches(x, y, C0); f.set_pop(x, y, C0, NO_POP);
  }
  void configure(int x, int y){
    if (kind == BCAST || kind == SCATTER){
      if (kind == SCATTER){
        int chunk = count, send = NP * count;
        f.set_filter(x, y, C0, true, chunk, send - chunk, (send - pe_id * chunk) % send);
      }
      if (pe_id == root){
        if (pe_id == 0) f.route(x, y, C0, R, bit(POS));
        else if (pe_id == NP - 1) f.route(x, y, C0, R, bit(NEG));
        else f.route(x, y, C0, R, bit(POS) | bit(NEG));
      } else if (pe_id == 0) f.route(x, y, C0, POS, bit(R));
      else if (pe_id == NP - 1) f.route(x, y, C0, NEG, bit(R));
      else if (pe_id < root) f.route(x, y, C0, POS, bit(R) | bit(NEG));
      else f.route(x, y, C0, NEG, bit(R) | bit(POS));
    } else if (kind == GATHER){
      if (pe_id == root){
        if (pe_id == 0) f.route(x, y, C0, POS, bit(R));
        else f.route(x, y, C0, NEG, bit(R));
        if (pe_id > 0 && pe_id < NP - 1) f.set_switch_in(x, y, C0, 1, POS);
      } else if (pe_id == 0) f.route(x, y, C0, R, bit(POS));
      else if (pe_id == NP - 1) f.route(x, y, C0, R, bit(NEG));
      else if (pe_id < root){ f.route(x, y, C0, R, bit(POS)); f.set_switch_in(x, y, C0, 1, NEG); }
      else { f.route(x, y, C0, R, bit(NEG)); f.set_switch_in(x, y, C0, 1, POS); }
      if (pe_id == root + 1) f.set_pop(x, y, C0, ALWAYS_POP);
    } else {
      for (int c : {C0, C1}){
        if (c == neg_c){
          if (pe_id == 0) f.route(x, y, c, R, bit(R));
          else if (pe_id <= root) f.route(x, y, c, NEG, bit(R));
          else f.route(x, y, c, R, bit(NEG));
        } else {
          if (pe_id == NP - 1) f.route(x, y, c, R, bit(R));
          else if (pe_id < root) f.route(x, y, c, R, bit(POS));
          else f.route(x, y, c, POS, bit(R));
        }
      }
    }
  }

  void fsm(){
    double pre = -1, len = -1; int k = fsm_k++;
    bool tab = ct && lookup("fsmlen|" + key + "|" + std::to_string(k), &len);
    if (tab) lookup("fsmpre|" + key + "|" + std::to_string(k), &pre);
    if (!tab){
      if (state == TRANSFER){ m.spend(fsm_body()); transfer(); }
      else if (state == CALLBACK){ m.spend(cb_body()); initiate_teardowns(); m.unblock(LOCK); }
      return;
    }
    int L = (int)len, t = tailof(L), P0 = pre >= 0 ? std::min((int)pre, L) : std::max(0, L - t);
    m.spend(P0);                                               // up to the DSD issue (or the activation)
    if (state == TRANSFER) transfer(); else if (state == CALLBACK){ initiate_teardowns(); m.unblock(LOCK); }
    m.spend(L - P0);
  }
  // cost key: kind | root position | PE class | parity (build_costs.py)
  std::string cost_key() const {
    static const char* K[4] = {"bcast", "scatter", "gather", "reduce"};
    const char* rp = root == 0 ? "first" : root == NP - 1 ? "last" : "mid";
    const char* cl = pe_id == root ? "root" : pe_id == 0 ? "first" : pe_id == NP - 1 ? "last"
                   : (kind == GATHER && pe_id == root + 1) ? "guard" : pe_id < root ? "lo" : "hi";
    return std::string(K[kind]) + "|" + rp + "|" + cl + "|" + std::to_string(pe_id % 2);
  }
  // Addendum G lookup order: y-ops y. -> x2. -> x entry; x-ops with the other module initialised x2. -> x entry
  bool lookup1(const std::string& k, double* out) const {
    if (ct->get(k, count, NP, out)) return true;
    std::string alt = k;                                       // other parity
    size_t p = alt.find('|'); for (int i = 0; i < 3 && p != std::string::npos; i++) p = alt.find('|', p + 1);
    if (p != std::string::npos && p + 1 < alt.size()){ alt[p + 1] = alt[p + 1] == '0' ? '1' : '0'; if (ct->get(alt, count, NP, out)) return true; }
    return false;
  }
  bool lookup(const std::string& k, double* out, bool* prefixed = nullptr) const {
    if (prefixed) *prefixed = false;
    if (dim == 1 && two_modules && other_init){
      if (lookup1("y." + k, out)){ if (prefixed) *prefixed = true; return true; }
      if (lookup1("x2." + k, out)){ if (prefixed) *prefixed = true; return true; }
    } else if (dim == 0 && two_modules && other_init){
      if (lookup1("x2." + k, out)){ if (prefixed) *prefixed = true; return true; }
    }
    return lookup1(k, out);
  }
  double cost0(const std::string& k, double dflt) const { double v; return (ct && ct->get(k, count, NP, &v)) ? v : dflt; }
  int td_cost(){
    double v; int k = td_k++; bool pre = false;
    if (ct && lookup("tdlen|" + key + "|" + std::to_string(k), &v, &pre)) return (int)v + (pre ? cp.td2x : (two_modules ? cp.td2 : 0));
    return cp.handler + (two_modules ? cp.td2 : 0);
  }
  int tailof(int len) const { return ct ? std::min(ct->tail, len) : 0; }

  void transfer(){
    if (kind == BCAST){
      if (pe_id == root) m.fabout(C0, count, FSM, 0, sb); else m.fabin(C0, count, FSM, sb);   // bcast: buf in place
      state = CALLBACK;
    } else if (kind == SCATTER){
      if (pe_id == root){
        if (!ct) m.spend((int)(count * cp.copy));
        if (rb) for (int i = 0; i < count; i++) rb[i] = sb[pe_id * count + i];
        m.fabout(C0, count * NP, FSM, 0, sb);
      } else m.fabin(C0, count, FSM, rb);
      state = CALLBACK;
    } else if (kind == GATHER){
      if (pe_id == root){
        if (counter == root){
          if (!ct) m.spend((int)(count * cp.copy));
          counter++;
          if (rb) for (int i = 0; i < count; i++) rb[root * count + i] = sb[i];
          if (root == NP - 1) state = CALLBACK;
          m.activate(FSM);
        } else if (counter == 0){
          m.fabin(C0, count * root, FSM, rb ? rb + count * root - 1 : nullptr, -1); counter = root;   // reversed
        } else {
          m.fabin(C0, (NP - root - 1) * count, FSM, rb ? rb + (root + 1) * count : nullptr); state = CALLBACK;
        }
      } else if (counter == 0){
        bool send_ctrl = (pe_id == 0) && (root != NP - 1);
        if (!send_ctrl) state = CALLBACK;
        if (pe_id < root) m.fabout(C0, count, FSM, 1, sb ? sb + count - 1 : nullptr, -1);   // .advance_switch, reversed
        else m.fabout(C0, count, FSM, 1, sb);
        counter++;
      } else {
        m.fabout_ctl(C0, ctrl_word(ADVANCE, true), FSM); state = CALLBACK;
      }
    } else {                                                       // reduce_fadds
      if (pe_id == root && counter == 0){
        if (pe_id == NP - 1) m.fabin(neg_c, count, FSM, rb); else m.fabin(pos_c, count, FSM, rb);
        counter++;
      } else if (pe_id == root && counter == 1){
        if (pe_id == 0 || pe_id == NP - 1) m.activate(FSM);
        else m.fabin(neg_c, count, FSM, rb, 1, rb);                // mem = neg_fabin + mem
        counter++;
      } else if (pe_id == root){
        if (!ct) m.spend((int)(count * cp.fadd));
        state = CALLBACK; m.activate(FSM);
        if (rb) for (int i = 0; i < count; i++) rb[i] += sb[i];
      } else {
        if (pe_id == 0) m.fabout(pos_c, count, FSM, 0, sb);
        else if (pe_id == NP - 1) m.fabout(neg_c, count, FSM, 0, sb);
        else if (pe_id < root) m.fwd(neg_c, pos_c, count, FSM, sb);
        else m.fwd(pos_c, neg_c, count, FSM, sb);
        state = CALLBACK;
      }
    }
  }

  void initiate_teardowns(){
    const uint32_t TD = ctrl_word(TEARDOWN, true);
    if (kind == BCAST || kind == SCATTER){
      if (pe_id == root) m.fabout_ctl(C0, TD, -1);
    } else if (kind == GATHER){
      if (pe_id == 0){ if (root != 0) m.fabout_ctl(C0, TD, -1); }
      else if (pe_id == NP - 1 && root != NP - 1){
        m.fabout_ctl(C0, root != 0 ? ctrl_word(TEARDOWN, true, RESET, true) : ctrl_word(TEARDOWN, true, TEARDOWN, true), -1);
      }
    } else {
      if (td_reduce_state == 0){
        if (pe_id == 0) m.fabout_ctl(C0, TD, FSM);
        else if (pe_id == NP - 1) m.fabout_ctl(NP % 2 == 0 ? C0 : C1, TD, FSM);
        else m.activate(FSM);
        td_reduce_state = 1;
      } else {
        if (pe_id < root) m.fabout_ctl(pos_c, TD, -1);
        if (root < pe_id) m.fabout_ctl(neg_c, TD, -1);
        td_reduce_state = 0;
      }
    }
  }
};

}  // namespace wse
