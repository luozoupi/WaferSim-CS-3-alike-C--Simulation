// Stage 1 M5 functional tests: the ported <collectives_2d> moves the right data (payload tracking through the
// fabric): broadcast, scatter (counter filter windows), gather (reversed NEG side, switch hand-offs, guard pop),
// reduce (alternating colours, integer adds); chained ops (teardown/reconfigure between ops); x and y dims.
#include "../../../src/wse/c2d.h"
#include <memory>
using namespace wse;
static int fails = 0, checks = 0;

static bool run(int kind, int NP, int root, int count, int dim, int reps){
  Profile pr; PeProfile pp; C2dProfile cp;
  int GW = dim ? 1 : NP, GH = dim ? NP : 1;
  Fabric f(GW, GH, pr); f.tracing = false; Machine m(f, pp);
  std::vector<std::unique_ptr<C2D>> mod; std::vector<std::vector<uint32_t>> sb(NP), rb(NP); std::vector<int> rep(NP, 0);
  for (auto& q : m.pe){
    int id = dim ? q.y : q.x;
    mod.emplace_back(new C2D(m, q, dim, cp)); C2D* X = mod.back().get();
    sb[id].resize(count * NP); rb[id].assign(count * NP, 0xDEAD);
    for (int i = 0; i < count * NP; i++) sb[id][i] = 1000 * (id + 1) + i;
    auto start = [X, kind, root, count, &sb, &rb, id]{ X->op(kind, root, count, 10, sb[id].data(), rb[id].data()); };
    q.task[10] = [&m, &rep, id, reps, start]{ if (++rep[id] < reps) start(); else m.stamp(2); };
    m.launch(q, 2 * q.x, [&m, X, start]{ X->init(); start(); });
  }
  long quiet = 0;
  while (f.now < 2000000){ m.step(); if (m.idle()){ if (++quiet > 256) break; } else quiet = 0; }
  bool ok = true;
  for (auto& q : m.pe) if (q.stamp[2] < 0) ok = false;              // every PE completed every op
  for (int p = 0; p < NP && ok; p++) for (int i = 0; i < count && ok; i++){
    uint32_t want, got;
    if (kind == BCAST){ want = 1000 * (root + 1) + i; got = sb[p][i]; if (p == root) continue; }
    else if (kind == SCATTER){ want = 1000 * (root + 1) + p * count + i; got = rb[p][i]; }
    else if (kind == GATHER){ if (p != root) continue; for (int s = 0; s < NP && ok; s++) for (int j = 0; j < count; j++)
        if (rb[root][s * count + j] != (uint32_t)(1000 * (s + 1) + j)) ok = false; continue; }
    else { if (p != root) continue; want = 0; for (int s = 0; s < NP; s++) want += 1000 * (s + 1) + i;
           want += (reps - 1) * 0; got = rb[root][i]; if (reps > 1) continue; }
    if (got != want) ok = false;
  }
  return ok;
}

int main(){
  const char* nm[4] = {"bcast", "scatter", "gather", "reduce"};
  for (int kind = 0; kind < 4; kind++) for (int NP : {2, 3, 4, 5, 8}) for (int count : {1, 3, 8}) for (int dim : {0, 1})
    for (int reps : {1, 3}){
      for (int root : {0, NP / 2, NP - 1}){
        checks++;
        if (!run(kind, NP, root, count, dim, reps)){ fails++; printf("FAIL %s NP=%d root=%d count=%d dim=%d reps=%d\n", nm[kind], NP, root, count, dim, reps); }
      }
    }
  printf("%s: %d/%d configurations correct\n", fails ? "FAILED" : "ALL PASS", checks - fails, checks);
  return fails != 0;
}
