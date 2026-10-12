// Stage 1 harness: simulate one M1 fabric case (spec from gen.py --spec) on the wavelet-level fabric.
// PE model (minimal, M3 will replace it): every PE starts main at launch time LW*x; a sender's first wavelet is
// injected S0 cycles later (DSD setup), then one per cycle subject to ramp backpressure; a receiver drains its
// input queue one word per cycle once armed (A0 + delay*DL after start); a relay re-sends after its receive
// completes (RELAY cycles later).  Output: injection/arrival metrics like the simfab sweep.
#include "../../src/wse/fabric.h"
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
using namespace wse;

struct Send { int x, y, c, n, relay; int sent = 0; long start = -1; };
struct Recv { int x, y, c, n, delay; int got = 0; long arm = 0; long done = -1; };

int main(int argc, char** argv){
  Profile pr;
  int LW = 2, S0 = 7, A0 = 12, RELAY = 20; double DL = 1.0;
  for (int i = 2; i < argc; i++){                       // key=value overrides
    char k[64]; double v; if (sscanf(argv[i], "%63[^=]=%lf", k, &v) != 2) continue;
    std::string K(k);
    if (K == "hop") pr.hop = (int)v; else if (K == "link") pr.link = (int)v; else if (K == "buf") pr.buf = (int)v;
    else if (K == "rin") pr.ramp_in_buf = (int)v; else if (K == "rout") pr.ramp_out_buf = (int)v; else if (K == "turn") pr.turn = (int)v;
    else if (K == "LW") LW = (int)v; else if (K == "S0") S0 = (int)v; else if (K == "A0") A0 = (int)v;
    else if (K == "RELAY") RELAY = (int)v; else if (K == "DL") DL = v;
  }
  FILE* f = fopen(argv[1], "r"); if (!f){ perror("spec"); return 1; }
  char tag[16]; int W = 0, H = 0;
  std::vector<std::array<int, 5>> routes; std::vector<Send> sends; std::vector<Recv> recvs;
  while (fscanf(f, "%15s", tag) == 1){
    if (!strcmp(tag, "GRID")) fscanf(f, "%d %d", &W, &H);
    else if (!strcmp(tag, "ROUTE")){ std::array<int, 5> r; fscanf(f, "%d %d %d %d %d", &r[0], &r[1], &r[2], &r[3], &r[4]); routes.push_back(r); }
    else if (!strcmp(tag, "SEND")){ Send s; fscanf(f, "%d %d %d %d %d", &s.x, &s.y, &s.c, &s.n, &s.relay); sends.push_back(s); }
    else if (!strcmp(tag, "RECV")){ Recv r; fscanf(f, "%d %d %d %d %d", &r.x, &r.y, &r.c, &r.n, &r.delay); recvs.push_back(r); }
  }
  fclose(f);
  Fabric fab(W, H, pr);
  for (auto& r : routes) fab.route(r[0], r[1], r[2], r[3], (uint8_t)r[4]);
  for (auto& s : sends) if (!s.relay) s.start = (long)LW * s.x + S0;
  for (auto& r : recvs) r.arm = (long)LW * r.x + A0 + (long)(r.delay * DL);
  long limit = 5000000; bool busy = true;
  while (busy && (long)fab.now < limit){
    busy = false;
    for (auto& s : sends){
      if (s.start < 0 || s.sent >= s.n){ if (s.sent < s.n) busy = true; continue; }
      busy = true;
      if ((long)fab.now >= s.start && fab.inject(s.x, s.y, s.c, s.sent)) s.sent++;
    }
    for (auto& r : recvs){
      if (r.got >= r.n) continue;
      busy = true;
      if ((long)fab.now >= r.arm && fab.deliver(r.x, r.y, r.c, nullptr)){
        r.got++;
        if (r.got == r.n){
          r.done = fab.now;
          for (auto& s : sends) if (s.relay && s.x == r.x && s.y == r.y) s.start = fab.now + RELAY;
        }
      }
    }
    fab.step();
  }
  // metrics from the fabric trace: injection per (src tile, colour), arrival per (dst tile, colour)
  std::map<std::string, std::array<long, 3>> src, dst;
  auto upd = [](std::array<long, 3>& a, long v){ if (a[2] == 0){ a[0] = a[1] = v; } else { a[0] = std::min(a[0], v); a[1] = std::max(a[1], v); } a[2]++; };
  for (auto& s : sends) src[std::to_string(s.x) + "," + std::to_string(s.y) + "," + std::to_string(s.c)] = {0, 0, 0};
  for (auto& r : recvs) dst[std::to_string(r.x) + "," + std::to_string(r.y) + "," + std::to_string(r.c)] = {0, 0, 0};
  for (auto& tr : fab.trace){
    std::string k = std::to_string(tr.x) + "," + std::to_string(tr.y) + "," + std::to_string(tr.colour);
    if (tr.link == R){ auto it = src.find(k); if (it != src.end()) upd(it->second, tr.cycle); }
    else { auto it = dst.find(k); if (it != dst.end()) upd(it->second, tr.cycle); }
  }
  printf("{\"src\": {");
  bool first = true;
  for (auto& kv : src){ printf("%s\"%s\": [%ld, %ld, %ld]", first ? "" : ", ", kv.first.c_str(), kv.second[0], kv.second[1], kv.second[2]); first = false; }
  printf("}, \"dst\": {"); first = true;
  for (auto& kv : dst){ printf("%s\"%s\": [%ld, %ld, %ld]", first ? "" : ", ", kv.first.c_str(), kv.second[0], kv.second[1], kv.second[2]); first = false; }
  printf("}, \"cycles\": %lu}\n", (unsigned long)fab.now);
  return 0;
}
