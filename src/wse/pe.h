// wsesim Stage 1 (M3): PE interface F1 on top of the wavelet-level fabric.
// Per PE: a non-preemptive task scheduler (activate / block / unblock; the lowest ready id runs first), async DSD
// microthreads that move wavelets between memory and the fabric, teardown handlers raised by router events, and
// TSC stamps.  Task bodies are C++ callables that issue operations; each operation takes effect at the body's
// start time plus the cycles the body has spent so far (spend()).  Timing constants live in PeProfile.
#pragma once
#include "fabric.h"
#include <map>

namespace wse {

struct PeProfile {               // simfab-2.10; values fitted on M1 train rows (Addendum A families)
  int s0 = 7;                    // fabout: issue -> first wavelet offered to the router
  int s0_ctl = 7;                // fabout of a control word: issue -> offered
  int a0 = 5;                    // fabin: issue -> first pop possible
  int cpl = 3;                   // last wavelet moved -> completion activation of the bound task
  int disp = 2;                  // activation -> task body start (CE idle)
  int td_disp = 8;               // router enters teardown -> handler body start (CE idle)
  int body = 6;                  // default cycles a task body spends before its first operation
  int exit_cost = 2;             // teardown exit (config write) -> router accepts traffic again
  int fwd_lat = 2;               // streaming fabin -> (fadds) -> fabout: pop -> result offered
  int fwd_cap = 4;               // results in flight in a streaming op
  int in_bubble = 0;             // fabin: one idle cycle after every in_bubble words (simfab: ~49-50; 0 = off)
  int oq_depth = 0;              // send output queue (Addendum D): a fabout completes once its remaining words fit
                                 // in the queue (0 = legacy: completes when its last wavelet enters the router)
};

class Machine;

struct Op {                      // one async DSD microthread
  enum Kind { OUT, IN, FWD } kind;   // FWD: pop colour `in_colour`, offer the result on `colour` (fadds fabin+mem->fabout)
  int colour; int n;             // remaining wavelets
  uint64_t next;                 // earliest cycle for the next wavelet
  uint8_t ctrl = 0; uint32_t word = 0; uint8_t adv = 0;
  int on_done = -1;              // task id activated at completion (-1: none)
  std::function<void(uint64_t)> done_cb;   // optional completion callback (cycle of last wavelet)
  int in_colour = -1; int n_in = 0; std::deque<std::pair<uint64_t, uint32_t>> fly;   // FWD state (ready, value)
  const uint32_t* src = nullptr; uint32_t* dst = nullptr; int stride = 1; int idx = 0;   // optional payload tracking
  const uint32_t* add = nullptr;                    // FWD: value += add[idx] (fadds with a mem operand)
};

struct Pe {
  int x, y;
  std::map<int, std::function<void()>> task;         // bound tasks (local / data task ids)
  std::map<int, std::function<void()>> td_handler;   // per colour
  std::vector<uint64_t> act_at;                      // activation time per id (UINT64_MAX: not activated)
  std::vector<bool> blocked;
  uint64_t busy_until = 0;                           // CE busy running a body until this cycle
  std::vector<Op> ops;
  std::vector<int64_t> stamp = std::vector<int64_t>(32, -1);
  Pe(int x_, int y_) : x(x_), y(y_), act_at(64, UINT64_MAX), blocked(64, false) {}
};

class Machine {
 public:
  Fabric& f; PeProfile pp; std::vector<Pe> pe;
  Pe* cur = nullptr; uint64_t body_t = 0;            // running body and its current time
  std::vector<std::pair<uint64_t, std::function<void()>>> timed;   // deferred fabric-side actions
  Machine(Fabric& fab, PeProfile p) : f(fab), pp(p) {
    for (int y = 0; y < f.GH; y++) for (int x = 0; x < f.GW; x++) pe.emplace_back(x, y);
    f.on_teardown = [this](int x, int y, int c, uint64_t t){
      Pe& q = at(x, y);
      if (q.td_handler.count(c)) td_pending.push_back({t + pp.td_disp, &q, c});
    };
  }
  Pe& at(int x, int y){ return pe[y * f.GW + x]; }

  // ---- API for task bodies (valid while a body runs) ----
  void spend(int k){ body_t += k; }
  uint64_t t(){ return body_t; }
  void stamp(int slot){ cur->stamp[slot] = (int64_t)body_t; }
  // act_at = earliest start; a task activated by a body starts pp.disp later (and not before the CE is free)
  void activate(int id, Pe* q = nullptr){ Pe& p = q ? *q : *cur; p.act_at[id] = std::min(p.act_at[id], body_t + pp.disp); }
  void block(int id){ cur->blocked[id] = true; }
  void unblock(int id){ cur->blocked[id] = false; }
  void fabout(int colour, int n, int on_done, uint8_t adv = 0, const uint32_t* src = nullptr, int stride = 1){
    Op o{Op::OUT, colour, n, body_t + pp.s0, 0, 0, adv, on_done, nullptr}; o.src = src; o.stride = stride;
    if (pp.oq_depth > 0 && n <= pp.oq_depth){ complete(*cur, o, body_t); o.on_done = -1; }
    cur->ops.push_back(o);
  }
  void fabout_ctl(int colour, uint32_t word, int on_done){
    Op o{Op::OUT, colour, 1, body_t + pp.s0_ctl, 1, word, 0, on_done, nullptr};
    if (pp.oq_depth > 0){ complete(*cur, o, body_t); o.on_done = -1; }
    cur->ops.push_back(o);
  }
  void complete(Pe& q, const Op& o, uint64_t t){
    if (o.on_done >= 0) q.act_at[o.on_done] = std::min(q.act_at[o.on_done], t + pp.cpl + pp.disp);
  }
  void fabin(int colour, int n, int on_done, uint32_t* dst = nullptr, int stride = 1, const uint32_t* add = nullptr){
    Op o{Op::IN, colour, n, body_t + pp.a0, 0, 0, 0, on_done, nullptr}; o.dst = dst; o.stride = stride; o.add = add;
    cur->ops.push_back(o);
  }
  void fwd(int in_colour, int out_colour, int n, int on_done, const uint32_t* add = nullptr){
    Op o{Op::FWD, out_colour, n, body_t + pp.s0, 0, 0, 0, on_done, nullptr};
    o.in_colour = in_colour; o.n_in = n; o.add = add; cur->ops.push_back(o);
  }
  // router / tile configuration written by the running body (takes effect at the body's current time)
  void cfg(std::function<void()> fn){ timed.push_back({body_t, fn}); }
  void teardown_exit(int colour){
    int x = cur->x, y = cur->y;
    timed.push_back({body_t + pp.exit_cost, [this, x, y, colour]{ f.teardown_exit(x, y, colour); }});
  }
  // launch main-like entry on a PE at cycle t0 (body runs at t0, CE busy per spend)
  void launch(Pe& q, uint64_t t0, std::function<void()> body){ launches.push_back({t0, &q, body}); }

  // ---- simulation ----
  void step(){
    uint64_t now = f.now;
    for (auto it = timed.begin(); it != timed.end();){
      if (it->first <= now){ auto fn = it->second; it = timed.erase(it); fn(); } else ++it;
    }
    for (auto it = launches.begin(); it != launches.end();){
      if (std::get<0>(*it) <= now && std::get<1>(*it)->busy_until <= now){
        auto L = *it; it = launches.erase(it); run(*std::get<1>(L), now, std::get<2>(L));
      } else ++it;
    }
    for (auto it = td_pending.begin(); it != td_pending.end();){
      Pe& q = *std::get<1>(*it);
      if (std::get<0>(*it) <= now && q.busy_until <= now){
        int c = std::get<2>(*it); it = td_pending.erase(it); run(q, now, q.td_handler[c]);
      } else ++it;
    }
    for (auto& q : pe){
      if (q.busy_until <= now){                      // dispatch the lowest ready task id
        for (int id = 0; id < 64; id++){
          if (q.act_at[id] == UINT64_MAX || q.blocked[id] || q.act_at[id] > now || !q.task.count(id)) continue;
          q.act_at[id] = UINT64_MAX; run(q, now, q.task[id]); break;
        }
      }
      for (auto it = q.ops.begin(); it != q.ops.end();){
        Op& o = *it; bool moved = false;
        if (o.kind == Op::FWD){
          if (o.next <= now && !o.fly.empty() && o.fly.front().first <= now && f.inject(q.x, q.y, o.colour, o.fly.front().second)){
            o.fly.pop_front(); moved = true;
          }
          Wavelet w;
          if (o.next <= now && o.n_in > 0 && (int)o.fly.size() < pp.fwd_cap && f.deliver(q.x, q.y, o.in_colour, &w)){
            uint32_t v = w.data + (o.add ? o.add[o.idx] : 0); o.idx++;
            o.n_in--; o.fly.push_back({now + pp.fwd_lat, v});
          }
        } else if (o.next <= now){
          if (o.kind == Op::OUT){
            uint32_t v = o.ctrl ? o.word : (o.src ? o.src[(long)o.idx * o.stride] : 0);
            moved = f.inject(q.x, q.y, o.colour, v, o.ctrl, (o.n == 1) ? o.adv : 0);
            if (moved) o.idx++;
          } else {
            Wavelet w; moved = f.deliver(q.x, q.y, o.colour, &w);
            if (moved){ if (o.dst){ uint32_t* d = o.dst + (long)o.idx * o.stride; *d = w.data + (o.add ? *d : 0); } o.idx++; }
          }
        }
        if (moved){
          o.n--; if (o.kind != Op::FWD) o.next = now + 1;
          if (o.kind == Op::OUT && pp.oq_depth > 0 && o.n == pp.oq_depth){ complete(q, o, now); o.on_done = -1; }
          if (o.kind == Op::IN && pp.in_bubble > 0 && o.idx % pp.in_bubble == 0) o.next = now + 2;
          if (o.n == 0){
            complete(q, o, now);
            if (o.done_cb) o.done_cb(now);
            it = q.ops.erase(it); continue;
          }
        }
        ++it;
      }
    }
    f.step();
  }
  bool idle() const {
    if (!timed.empty() || !launches.empty() || !td_pending.empty()) return false;
    for (auto& q : pe){
      if (!q.ops.empty() || q.busy_until > f.now) return false;
      for (int id = 0; id < 64; id++) if (q.act_at[id] != UINT64_MAX && !q.blocked[id] && q.task.count(id)) return false;
    }
    return true;
  }

 private:
  std::vector<std::tuple<uint64_t, Pe*, std::function<void()>>> launches;
  std::vector<std::tuple<uint64_t, Pe*, int>> td_pending;
  void run(Pe& q, uint64_t start, const std::function<void()>& body){
    Pe* save = cur; uint64_t save_t = body_t;
    cur = &q; body_t = start;
    body();
    q.busy_until = std::max(q.busy_until, body_t + 1);
    cur = save; body_t = save_t;
  }
};

}  // namespace wse
