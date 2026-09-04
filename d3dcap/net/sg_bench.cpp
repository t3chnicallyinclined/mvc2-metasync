// SUPERGUN netcode measurement harness (lane: senior-re-generalist / SUPERGUN NETCODE).
// Measures the host-side terms of the input-to-photon budget that we CONTROL, on this machine.
// Nothing here touches the game image; the tick cost itself is measured by d3dcap/receipt/runner.
//   sg_bench state   - rollback save/restore cost for the 0x33B18-byte GGPO region (ring depths)
//   sg_bench timer   - Windows pacing precision: Sleep, high-resolution waitable timer, spin
//   sg_bench udp     - loopback UDP ping-pong RTT + sendto syscall cost
//   sg_bench all
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <timeapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <algorithm>
#include <vector>
#include <thread>
#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "winmm.lib")

static const size_t BLKSZ = 0x33B18; // 211,736 B - the ONE registered GGPO rollback region (rr-ggpo-determinism)

static LARGE_INTEGER g_qpf;
static inline double now_ms() { LARGE_INTEGER t; QueryPerformanceCounter(&t); return t.QuadPart * 1000.0 / g_qpf.QuadPart; }

struct Stat {
  std::vector<double> v;
  void add(double x) { v.push_back(x); }
  double q(double p) { if (v.empty()) return 0; size_t i = (size_t)(p * v.size()); if (i >= v.size()) i = v.size() - 1; return v[i]; }
  void done(const char* name, const char* unit = "ms") {
    std::sort(v.begin(), v.end());
    double s = 0; for (double x : v) s += x;
    printf("%-44s n=%-7zu min %.4f  p50 %.4f  p90 %.4f  p99 %.4f  max %.4f  mean %.4f  (%s)\n",
           name, v.size(), v.empty() ? 0 : v[0], q(.5), q(.9), q(.99), v.empty() ? 0 : v.back(), v.empty() ? 0 : s / v.size(), unit);
  }
};

// ---------------------------------------------------------------- state
static void bench_state() {
  printf("\n=== ROLLBACK STATE COST  (region = 0x33B18 = %zu B, the single registered GGPO region) ===\n", BLKSZ);
  unsigned char* live = (unsigned char*)_aligned_malloc(BLKSZ, 64);
  for (size_t i = 0; i < BLKSZ; i++) live[i] = (unsigned char)((i * 2654435761u) >> 13);

  const int depths[] = { 1, 8, 16, 60, 120 };
  for (int d : depths) {
    std::vector<unsigned char*> ring(d);
    for (int i = 0; i < d; i++) { ring[i] = (unsigned char*)_aligned_malloc(BLKSZ, 64); memset(ring[i], 0, BLKSZ); }
    Stat sv, rs;
    const int N = 4000;
    for (int i = 0; i < N; i++) {                       // save: live -> ring[i%d]
      live[(i * 4099) % BLKSZ] ^= (unsigned char)i;     // dirty a byte so nothing is optimised away
      double t0 = now_ms(); memcpy(ring[i % d], live, BLKSZ); double t1 = now_ms(); sv.add(t1 - t0);
    }
    for (int i = 0; i < N; i++) {                       // restore: ring[i%d] -> live
      double t0 = now_ms(); memcpy(live, ring[i % d], BLKSZ); double t1 = now_ms(); rs.add(t1 - t0);
    }
    char nm[96];
    snprintf(nm, sizeof nm, "save    memcpy blk -> ring[%d]", d); sv.done(nm);
    snprintf(nm, sizeof nm, "restore memcpy ring[%d] -> blk", d); rs.done(nm);
    for (int i = 0; i < d; i++) _aligned_free(ring[i]);
  }

  // Desync / state-hash cost (FNV-1a over the whole region, 8 bytes at a time).
  {
    Stat h; volatile unsigned long long sink = 0;
    for (int i = 0; i < 2000; i++) {
      double t0 = now_ms();
      unsigned long long acc = 1469598103934665603ull;
      const unsigned long long* p = (const unsigned long long*)live;
      for (size_t k = 0; k < BLKSZ / 8; k++) { acc ^= p[k]; acc *= 1099511628211ull; }
      double t1 = now_ms(); sink ^= acc; h.add(t1 - t0);
    }
    h.done("state hash FNV-1a over 0x33B18"); (void)sink;
  }

  // Copy-cost scaling: prices a delta/dirty-page save of a given byte count. HOW MANY bytes
  // actually change per frame is a GAME question, not answered here.
  {
    printf("  copy cost scaling (single destination, hot source):\n");
    size_t szs[4] = { 4096, 65536, 262144, BLKSZ };
    for (int i = 0; i < 4; i++) {
      size_t sz = szs[i];
      unsigned char* dst = (unsigned char*)_aligned_malloc(sz, 64); memset(dst, 0, sz);
      Stat s; for (int k = 0; k < 4000; k++) { double t0 = now_ms(); memcpy(dst, live, sz); double t1 = now_ms(); s.add(t1 - t0); }
      char nm[96]; snprintf(nm, sizeof nm, "    memcpy %zu B", sz); s.done(nm); _aligned_free(dst);
    }
  }
  _aligned_free(live);
}

// ---------------------------------------------------------------- timer
static void bench_timer() {
  printf("\n=== HOST PACING PRECISION (bounds how late we can sample input before a tick) ===\n");
  { LARGE_INTEGER f; QueryPerformanceFrequency(&f); printf("QPC frequency %lld Hz (tick %.1f ns)\n", f.QuadPart, 1e9 / (double)f.QuadPart); }
  { Stat s; for (int i = 0; i < 200000; i++) { double a = now_ms(), b = now_ms(); s.add((b - a) * 1e6); } s.done("QueryPerformanceCounter call pair", "ns"); }

  for (int period = 0; period <= 1; period++) {
    if (period) timeBeginPeriod(1);
    printf("-- timeBeginPeriod(%d)\n", period);
    { Stat s; for (int i = 0; i < 600; i++) { double t0 = now_ms(); Sleep(1); s.add(now_ms() - t0); } s.done("  Sleep(1) actual"); }
    { Stat s; for (int i = 0; i < 5000; i++) { double t0 = now_ms(); Sleep(0); s.add(now_ms() - t0); } s.done("  Sleep(0) actual"); }
    HANDLE ht = CreateWaitableTimerExW(NULL, NULL, CREATE_WAITABLE_TIMER_HIGH_RESOLUTION, TIMER_ALL_ACCESS);
    if (ht) {
      double targets[3] = { 0.5, 1.0, 2.0 };
      for (int ti = 0; ti < 3; ti++) {
        double target = targets[ti];
        Stat s; LARGE_INTEGER due; due.QuadPart = -(LONGLONG)(target * 10000.0);
        for (int i = 0; i < 400; i++) { double t0 = now_ms(); SetWaitableTimerEx(ht, &due, 0, NULL, NULL, NULL, 0); WaitForSingleObject(ht, INFINITE); s.add(now_ms() - t0 - target); }
        char nm[96]; snprintf(nm, sizeof nm, "  hi-res waitable timer %.1f ms OVERSHOOT", target); s.done(nm);
      }
      CloseHandle(ht);
    } else printf("  CREATE_WAITABLE_TIMER_HIGH_RESOLUTION unavailable (err %lu)\n", GetLastError());
    { Stat s; for (int i = 0; i < 5000; i++) { double t0 = now_ms(), tgt = t0 + 0.2; while (now_ms() < tgt) YieldProcessor(); s.add(now_ms() - tgt); } s.done("  spin-to-deadline 0.2 ms OVERSHOOT"); }
    if (period) timeEndPeriod(1);
  }
}

// ---------------------------------------------------------------- udp
struct EchoArgs { unsigned short port; volatile bool* stop; };
static void echo_thread(EchoArgs a) {
  SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_TIME_CRITICAL);
  SOCKET s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
  sockaddr_in sa; memset(&sa, 0, sizeof sa);
  sa.sin_family = AF_INET; sa.sin_addr.s_addr = htonl(INADDR_LOOPBACK); sa.sin_port = htons(a.port);
  bind(s, (sockaddr*)&sa, sizeof sa);
  char buf[2048]; sockaddr_in from; int fl = sizeof from;
  DWORD tv = 200; setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (char*)&tv, sizeof tv);
  while (!*a.stop) { int n = recvfrom(s, buf, sizeof buf, 0, (sockaddr*)&from, &fl); if (n > 0) sendto(s, buf, n, 0, (sockaddr*)&from, fl); }
  closesocket(s);
}

static void bench_udp() {
  printf("\n=== UDP SOCKET FLOOR (loopback: OS+stack cost only, ZERO wire time) ===\n");
  WSADATA w; WSAStartup(MAKEWORD(2, 2), &w);
  volatile bool stop = false; unsigned short port = 47311;
  std::thread th(echo_thread, EchoArgs{ port, &stop });
  Sleep(120);
  SOCKET s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
  sockaddr_in to; memset(&to, 0, sizeof to);
  to.sin_family = AF_INET; to.sin_addr.s_addr = htonl(INADDR_LOOPBACK); to.sin_port = htons(port);
  char buf[2048]; memset(buf, 0x5a, sizeof buf);
  sockaddr_in from; int fl = sizeof from;

  int szs[4] = { 16, 64, 256, 1200 };
  for (int i2 = 0; i2 < 4; i2++) {
    int sz = szs[i2];
    Stat rtt, send_only;
    for (int i = 0; i < 4000; i++) {
      double t0 = now_ms();
      sendto(s, buf, sz, 0, (sockaddr*)&to, sizeof to);
      double t1 = now_ms();
      int n = recvfrom(s, buf, sizeof buf, 0, (sockaddr*)&from, &fl);
      double t2 = now_ms();
      if (n > 0 && i > 200) { rtt.add(t2 - t0); send_only.add(t1 - t0); }
    }
    char nm[96];
    snprintf(nm, sizeof nm, "loopback RTT %4d B payload", sz); rtt.done(nm);
    snprintf(nm, sizeof nm, "  sendto() syscall %4d B", sz); send_only.done(nm);
  }
  stop = true; th.join(); closesocket(s); WSACleanup();
}

int main(int argc, char** argv) {
  QueryPerformanceFrequency(&g_qpf);
  SetPriorityClass(GetCurrentProcess(), HIGH_PRIORITY_CLASS);
  SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_TIME_CRITICAL);
  const char* m = argc > 1 ? argv[1] : "all";
  bool all = !strcmp(m, "all");
  if (all || !strcmp(m, "state")) bench_state();
  if (all || !strcmp(m, "timer")) bench_timer();
  if (all || !strcmp(m, "udp"))   bench_udp();
  return 0;
}
