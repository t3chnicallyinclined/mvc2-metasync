// rr_runner.cpp -- THE RECEIPT RUNNER, Gate 1 (docs/RECEIPT-RUNNER-RE.md s2-s3, docs/WORKSTREAM-RECEIPT-RUNNER.md s4 step 1).
//
// A thin native wrapper that maps the user's OWN unpacked Steam MvC2 image (exe_image.bin, BYOR: never in any repo) at its
// link base 0x140000000, reserves the game's memory arena at the anchor's own addresses (Delta = 0: no pointer relocation,
// the configuration the p-code harness runs and has gated), restores blk / blk2 / ctx / DC-RAM / game_state from a run
// directory (d3dcap/ttd/dump_live.py + d3dcap/receipt/anchor_to_run.py + pl_rebuild.py), replaces the six external calls the
// tick makes (all in the UCRT sprintf path, contract C6), traps every other import, forces the seat map {0,1,-1,-1}
// (contract C2) and calls the GGPO sim tick FUN_140118950 once per frame with the two seat words, dumping blk after every
// tick. The oracle is the p-code harness (emu_frame.py / EmuGate.java): same images, same inputs, byte-exact expectation.
//
// RE METHOD (locked, docs/RE-METHOD.md): 1. port the SH4 annotations to the Steam binary by function matching; 2. seed with
// unique constants, then propagate along the call graph; 3. translate globals through the block map before comparing
// reference sets; 4. tag CONFIRMED versus INFERRED, and store the pairs as edges in the knowledge graph. This program is at
// step 4: every address below is CONFIRMED in the cited doc; nothing here is a new derivation except the two corrections
// noted at UCRT_TABLE (found by the trace's kind-3 records + same-boot export resolution, 2026-09-03).
//
// Addresses (all CONFIRMED unless tagged):
//   FUN_140118950   the GGPO sim tick: (RCX=&DAT_142d10b90, RDX=inputs[4], R8=0)      FRAME-READSET s1, DETERMINISM C2
//   FUN_140607d60   the whole frame = *(game_state+0x10)                                FRAME-READSET s1
//   game_state      0x140ac6d40 (exe+0xAC6D40), pads +0x218.., seat map +0x258..        DETERMINISM s1.1, C1/C2
//   DAT_142d10b90   GGPO frame counter / save root (wrapper only)                         DETERMINISM s1.1
//   DAT_142edf560   blk; DAT_142edf580 = blk+0x3CB8 (G); DAT_142edf628 = blk+0x324E0       DETERMINISM C1
//   DAT_142ef0ab0   ctx; ctx+8 = dcram; ctx+0x1f81b0 = blk; ctx+0x1f80a4 = 1              DETERMINISM C1/C4
//   DAT_142ebc010   heap object with the 64-entry debug ring at +0x346AC..+0x34AB0 (FUN_14006b5d0); the tick WRITES it
//   DAT_142eefbd8   UCRT FMA3 dispatch flag (0 = SSE2 path; both bit-identical, C3); the harness runs with 0
//   DAT_142e10b98   GGPO session pointer (must be 0)
//   IAT             .rdata 0x1408db000..: RtlAllocateHeap *0x1408db240, RtlReAllocateHeap *0x1408db140, HeapFree *0x1408db238,
//                   GetLastError *0x1408db2d8, SetLastError *0x1408db510 (trace kind-3 records, emu_frame.CRT_SLOTS)
//   UCRT_TABLE      0x142eefca0 = the UCRT `try_get_function` cache (FUN_140820798): entry id holds
//                   rol(ptr, cookie & 0x3f) ^ cookie, cookie = __security_cookie 0x140ab12d8; decoded -1 = "unavailable".
//                   id 5 = FlsGetValue (caller 0x140820b80: `mov ecx,5`), id 6 = FlsSetValue (caller 0x140820bd8: `mov ecx,6`).
//                   CORRECTION to RECEIPT-RUNNER-RE s3.1 / emu_frame.CRT_SLOTS: the Fls* calls are NOT IAT calls; IAT slot
//                   0x1408db218 is kernel32!TlsSetValue (same-boot export resolution) and the harness's extret on it never fired.
//                   In the harness both Fls* calls returned RAX=0 (not in extalloc/extret) -> FlsSetValue "failed" -> the CRT
//                   freed the fresh ptd (the 4x HeapFree per frame). `--crt stub` mirrors that exactly; `--crt real` keeps a
//                   real per-index FLS value (the CRT then reuses its ptd) -- the one-variable test that the sprintf path
//                   never reaches blk.
//
// Build: build.bat (MSVC, same toolchain as d3dcap/build.bat). The runner is a normal /DYNAMICBASE /HIGHENTROPYVA exe so it
// never lands on 0x140000000 or on the arena; both are asserted before anything is mapped.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#define PSAPI_VERSION 1
#include <windows.h>
#include <psapi.h>
#include <intrin.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <string>
#include <vector>
#include <map>
#include <algorithm>

#pragma comment(lib, "psapi.lib")

// ---- constants (see header comment for the evidence of each) ----------------------------------------------------------
static const uint64_t EXE_BASE_EXPECT   = 0x140000000ull;
static const uint64_t FRAME_TICK        = 0x140118950ull;
static const uint64_t FRAME_FN          = 0x140607d60ull;
static const uint64_t GS_ADDR           = 0x140ac6d40ull;
static const uint64_t GGPO_STATE        = 0x142d10b90ull;
static const uint64_t DAT_BLK           = 0x142edf560ull;
static const uint64_t DAT_G             = 0x142edf580ull;
static const uint64_t DAT_ENTITY        = 0x142edf628ull;
static const uint64_t DAT_CTX           = 0x142ef0ab0ull;
static const uint64_t DAT_DEBUGRING     = 0x142ebc010ull;
static const uint64_t DAT_FMAFLAG       = 0x142eefbd8ull;
static const uint64_t DAT_GGPOSESS      = 0x142e10b98ull;
static const uint64_t SECURITY_COOKIE   = 0x140ab12d8ull;
static const uint64_t UCRT_TABLE        = 0x142eefca0ull;   // try_get_function cache, FUN_140820798
static const int      UCRT_TABLE_N      = 32;               // entries 0..31 decode to null/ptr; entry 32 does not (image scan)
static const int      UCRT_ID_FLSGET    = 5, UCRT_ID_FLSSET = 6;
static const uint64_t IAT_LO            = 0x1408db000ull, IAT_HI = 0x1408dc000ull;   // .rdata head (257 import slots, image scan)
static const uint64_t SLOT_RTLALLOC     = 0x1408db240ull, SLOT_RTLREALLOC = 0x1408db140ull, SLOT_HEAPFREE = 0x1408db238ull,
                      SLOT_GETLASTERR   = 0x1408db2d8ull, SLOT_SETLASTERR = 0x1408db510ull;
static const uint64_t ARENA_SIZE        = 0x10000000ull;    // 256 MiB: ctx +0x8000000, dcram +0x8400000, staging +0xA400000, blk per boot
static const uint64_t BLK_SIZE_EXPECT   = 0x33B18ull;
static const uint32_t CLOCK_OFF = 0x3CC8, MODE_OFF = 0x3CB8, SLOTPTRS_OFF = 0x32500, FIGHTER0 = 0x3DB8, FSTRIDE = 0x738;
static const uint64_t DEBUGRING_BYTES   = 0x40000ull;       // ring at +0x346AC..+0x34AB0, count word +0x34AAC
static const uint64_t HEAP_BYTES        = 64ull << 20;

// ---- state ------------------------------------------------------------------------------------------------------------
struct Meta { uint64_t exe_base = 0, exe_size = 0, blk = 0, blk_size = 0, blk2 = 0, blk2_size = 0, ctx = 0, ctx_size = 0,
              dcram = 0, dcram_size = 0, dc_base = 0; uint64_t clock_value = 0; };
static Meta M;
static uint64_t g_arena = 0, g_heapBase = 0, g_heapCur = 0, g_heapEnd = 0;
static uint8_t* g_trapPage = nullptr; static int g_trapCount = 0;
static std::vector<std::string> g_trapNames;
static std::map<uint64_t, std::string> g_exports;          // same-boot export map addr -> module!name (diagnostic only)
static bool g_crtReal = false; static DWORD g_lastErr = 0; static void* g_fls[256] = {0};
static volatile long g_tick = 0;
static uint64_t g_cnt[8] = {0};   // 0 alloc 1 realloc 2 free 3 getlasterr 4 setlasterr 5 flsget 6 flsset
static uint64_t g_allocBytes = 0;
static FILE* g_log = nullptr;
// Lazy zero-commit of host-heap pages the tick touches through pointers baked into the dumped image (RECEIPT-RUNNER-RE s5.3):
// the p-code harness backs every unmapped address with sparse zero memory (writes absorbed, reads = 0 and logged `uninit`);
// the runner reproduces that on first touch and LOGS the page + the touching PC, so each such object is a named finding.
struct LazyPage { uint64_t page, rip; int kind; long tick; };
static std::vector<LazyPage> g_lazy; static bool g_lazyOn = true; static const size_t LAZY_MAX = 4096;

static void logf_(const char* fmt, ...) {
    va_list ap; va_start(ap, fmt); char b[2048]; _vsnprintf_s(b, sizeof(b), _TRUNCATE, fmt, ap); va_end(ap);
    fputs(b, stdout); fputc('\n', stdout); fflush(stdout);
    if (g_log) { fputs(b, g_log); fputc('\n', g_log); fflush(g_log); }
}
[[noreturn]] static void die(int code, const char* fmt, ...) {
    va_list ap; va_start(ap, fmt); char b[2048]; _vsnprintf_s(b, sizeof(b), _TRUNCATE, fmt, ap); va_end(ap);
    logf_("FATAL(%d): %s", code, b); ExitProcess(code);
}
static std::string hx(uint64_t v) { char b[32]; sprintf_s(b, "%llx", v); return b; }

// ---- tiny JSON string-field reader (meta.json fields are "key": "0x..." or "key": 1716) ---------------------------------
static std::string readFile(const std::string& p) {
    FILE* f = nullptr; if (fopen_s(&f, p.c_str(), "rb") || !f) die(2, "cannot open %s", p.c_str());
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    std::string s((size_t)n, '\0'); if (n && fread(&s[0], 1, (size_t)n, f) != (size_t)n) die(2, "short read %s", p.c_str());
    fclose(f); return s;
}
static bool jsonField(const std::string& j, const char* key, std::string& out) {
    std::string k = std::string("\"") + key + "\"";
    size_t p = j.find(k); if (p == std::string::npos) return false;
    p = j.find(':', p + k.size()); if (p == std::string::npos) return false; ++p;
    while (p < j.size() && (j[p] == ' ' || j[p] == '\t' || j[p] == '\n' || j[p] == '\r')) ++p;
    if (p < j.size() && j[p] == '"') { size_t e = j.find('"', p + 1); out = j.substr(p + 1, e - p - 1); return true; }
    size_t e = p; while (e < j.size() && (isalnum((unsigned char)j[e]) || j[e] == 'x' || j[e] == '-')) ++e;
    out = j.substr(p, e - p); return !out.empty();
}
static uint64_t jsonU64(const std::string& j, const char* key) {
    std::string s; if (!jsonField(j, key, s)) die(2, "meta.json lacks %s", key);
    return _strtoui64(s.c_str(), nullptr, 0);
}
static void loadInto(const std::string& p, uint64_t addr, uint64_t expectSize) {
    FILE* f = nullptr; if (fopen_s(&f, p.c_str(), "rb") || !f) die(2, "cannot open %s", p.c_str());
    fseek(f, 0, SEEK_END); uint64_t n = (uint64_t)_ftelli64(f); fseek(f, 0, SEEK_SET);
    if (expectSize && n != expectSize) die(2, "%s is %llu bytes, expected %llu", p.c_str(), n, expectSize);
    if (fread((void*)(uintptr_t)addr, 1, (size_t)n, f) != (size_t)n) die(2, "short read %s", p.c_str());
    fclose(f);
    const char* base = strrchr(p.c_str(), '\\'); base = base ? base + 1 : p.c_str();
    logf_("  loaded %-16s -> 0x%llx (%llu B)", base, addr, n);
}
static void dumpRange(const std::string& p, uint64_t addr, uint64_t n) {
    FILE* f = nullptr; if (fopen_s(&f, p.c_str(), "wb") || !f) die(2, "cannot write %s", p.c_str());
    fwrite((const void*)(uintptr_t)addr, 1, (size_t)n, f); fclose(f);
}

// ---- replacement externals (contract C6; harness semantics = emu_frame.CRT_SLOTS + EmuGate `extstub on`) -----------------
static PVOID WINAPI rr_RtlAllocateHeap(PVOID, ULONG, SIZE_T n) {
    ++g_cnt[0]; g_allocBytes += n;
    uint64_t p = g_heapCur; g_heapCur = (g_heapCur + n + 15) & ~15ull;
    if (g_heapCur > g_heapEnd) die(5, "runner heap exhausted (%llu B requested at tick %ld)", (uint64_t)n, g_tick);
    return (PVOID)(uintptr_t)p;   // zeroed: fresh VirtualAlloc'd pages, never reused (the CRT asks HEAP_ZERO_MEMORY=8)
}
static PVOID WINAPI rr_RtlReAllocateHeap(PVOID, ULONG, PVOID, SIZE_T n) { ++g_cnt[1]; return rr_RtlAllocateHeap(nullptr, 0, n); }   // harness: extalloc R9, no copy
static BOOL  WINAPI rr_HeapFree(PVOID, ULONG, PVOID) { ++g_cnt[2]; return TRUE; }
static DWORD WINAPI rr_GetLastError() { ++g_cnt[3]; return g_crtReal ? g_lastErr : 0; }
static void  WINAPI rr_SetLastError(DWORD e) { ++g_cnt[4]; if (g_crtReal) g_lastErr = e; }
static PVOID WINAPI rr_FlsGetValue(DWORD i) { ++g_cnt[5]; return g_crtReal ? g_fls[i & 0xff] : nullptr; }
static BOOL  WINAPI rr_FlsSetValue(DWORD i, PVOID p) { ++g_cnt[6]; if (!g_crtReal) return FALSE; g_fls[i & 0xff] = p; return TRUE; }

// ---- traps: every other import slot / cached UCRT pointer jumps here with its id --------------------------------------
static void __cdecl rr_trap(uint32_t id) {
    void* ret = _ReturnAddress();
    const char* nm = (id < g_trapNames.size()) ? g_trapNames[id].c_str() : "?";
    die(6, "TRAP: unexpected external call through %s from 0x%p (exe RVA 0x%llx) at tick %ld -- an import outside the C6 set is a FINDING",
        nm, ret, (uint64_t)(uintptr_t)ret - EXE_BASE_EXPECT, g_tick);
}
static uint64_t makeTrap(const std::string& name) {
    if (!g_trapPage) { g_trapPage = (uint8_t*)VirtualAlloc(nullptr, 0x10000, MEM_RESERVE | MEM_COMMIT, PAGE_EXECUTE_READWRITE); if (!g_trapPage) die(2, "trap page alloc failed"); }
    if (g_trapCount >= 0x10000 / 32) die(2, "too many traps");
    uint8_t* s = g_trapPage + 32 * g_trapCount;
    uint32_t id = (uint32_t)g_trapCount; uint64_t fn = (uint64_t)(uintptr_t)&rr_trap;
    s[0] = 0xB9; memcpy(s + 1, &id, 4);                 // mov ecx, id
    s[5] = 0x48; s[6] = 0xB8; memcpy(s + 7, &fn, 8);    // mov rax, imm64
    s[15] = 0xFF; s[16] = 0xE0;                         // jmp rax
    g_trapNames.push_back(name); ++g_trapCount;
    return (uint64_t)(uintptr_t)s;
}

// ---- same-boot export resolution (diagnostic names for the dump's IAT values; kernel32/ntdll bases are per boot) --------
static void buildExportMap() {
    HMODULE mods[512]; DWORD need = 0;
    if (!EnumProcessModules(GetCurrentProcess(), mods, sizeof(mods), &need)) return;
    for (DWORD i = 0; i < need / sizeof(HMODULE); ++i) {
        MODULEINFO mi; if (!GetModuleInformation(GetCurrentProcess(), mods[i], &mi, sizeof(mi))) continue;
        char nm[MAX_PATH]; GetModuleBaseNameA(GetCurrentProcess(), mods[i], nm, sizeof(nm));
        uint8_t* b = (uint8_t*)mi.lpBaseOfDll;
        IMAGE_DOS_HEADER* dh = (IMAGE_DOS_HEADER*)b; IMAGE_NT_HEADERS64* nt = (IMAGE_NT_HEADERS64*)(b + dh->e_lfanew);
        IMAGE_DATA_DIRECTORY d = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_EXPORT];
        if (!d.VirtualAddress || !d.Size) continue;
        IMAGE_EXPORT_DIRECTORY* ed = (IMAGE_EXPORT_DIRECTORY*)(b + d.VirtualAddress);
        uint32_t* names = (uint32_t*)(b + ed->AddressOfNames); uint16_t* ords = (uint16_t*)(b + ed->AddressOfNameOrdinals);
        uint32_t* funcs = (uint32_t*)(b + ed->AddressOfFunctions);
        for (DWORD k = 0; k < ed->NumberOfNames; ++k) {
            uint32_t fa = funcs[ords[k]];
            if (fa >= d.VirtualAddress && fa < d.VirtualAddress + d.Size) continue;   // forwarder
            g_exports.emplace((uint64_t)(uintptr_t)(b + fa), std::string(nm) + "!" + (const char*)(b + names[k]));
        }
    }
}
static std::string nameOf(uint64_t target) {
    auto it = g_exports.find(target); if (it != g_exports.end()) return it->second;
    return "target 0x" + hx(target) + " (unresolved: not an export of a module in this process)";
}

// ---- UCRT pointer-cache encoding (FUN_140820798, read 2026-09-03) ------------------------------------------------------
static uint64_t crtDecode(uint64_t v) { uint64_t c = *(uint64_t*)(uintptr_t)SECURITY_COOKIE; return _rotr64(v ^ c, (int)(c & 0x3f)); }
static uint64_t crtEncode(uint64_t p) { uint64_t c = *(uint64_t*)(uintptr_t)SECURITY_COOKIE; return _rotl64(p, (int)(c & 0x3f)) ^ c; }

// ---- crash diagnostics: name the faulting address's region, then exit (a precise failure is a deliverable) ---------------
static const char* region(uint64_t a) {
    if (a >= M.exe_base && a < M.exe_base + M.exe_size) return "exe image";
    if (a >= g_arena && a < g_arena + ARENA_SIZE) {
        if (a >= M.blk && a < M.blk + M.blk_size) return "arena/blk";
        if (a >= M.blk2 && a < M.blk2 + M.blk2_size) return "arena/blk2";
        if (a >= M.ctx && a < M.ctx + M.ctx_size) return "arena/ctx";
        if (a >= M.dcram && a < M.dcram + M.dcram_size) return "arena/dcram";
        if (a >= M.dcram + M.dcram_size) return "arena/staging(beyond dcram)";
        return "arena/other";
    }
    if (a >= g_heapBase && a < g_heapEnd) return "runner heap";
    if (a < 0x10000) return "null page";
    return "outside every mapped image (host heap/stack/DLL?)";
}
static LONG CALLBACK veh(EXCEPTION_POINTERS* ep) {
    EXCEPTION_RECORD* r = ep->ExceptionRecord; CONTEXT* c = ep->ContextRecord;
    if (r->ExceptionCode == DBG_PRINTEXCEPTION_C || r->ExceptionCode == 0x4001000Aul || r->ExceptionCode == 0x406D1388ul) return EXCEPTION_CONTINUE_SEARCH;
    uint64_t rip = c->Rip;
    if (g_lazyOn && r->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && r->NumberParameters >= 2 && r->ExceptionInformation[0] <= 1) {
        uint64_t a = r->ExceptionInformation[1];
        bool inImg = a >= M.exe_base && a < M.exe_base + M.exe_size, inArena = a >= g_arena && a < g_arena + ARENA_SIZE;
        MEMORY_BASIC_INFORMATION mbi;
        if (!inImg && !inArena && a >= 0x10000 && a < 0x7ff000000000ull && g_lazy.size() < LAZY_MAX &&
            VirtualQuery((void*)(uintptr_t)a, &mbi, sizeof(mbi)) && mbi.State == MEM_FREE) {
            uint64_t pg = a & ~0xFFFFull;
            if (VirtualAlloc((void*)(uintptr_t)pg, 0x10000, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE) == (void*)(uintptr_t)pg) {
                g_lazy.push_back({pg, rip, (int)r->ExceptionInformation[0], g_tick});
                return EXCEPTION_CONTINUE_EXECUTION;
            }
        }
    }
    std::string rva = (rip >= M.exe_base && rip < M.exe_base + M.exe_size) ? " RVA 0x" + hx(rip - M.exe_base) : "";
    logf_("EXCEPTION 0x%08lx at RIP 0x%llx (%s%s) tick %ld", r->ExceptionCode, rip, region(rip), rva.c_str(), g_tick);
    if (r->ExceptionCode == EXCEPTION_ACCESS_VIOLATION && r->NumberParameters >= 2) {
        uint64_t a = r->ExceptionInformation[1];
        std::string bo = (a >= M.blk && a < M.blk + M.blk_size) ? " blk+0x" + hx(a - M.blk) : "";
        logf_("  access violation: %s 0x%llx  region=%s%s", r->ExceptionInformation[0] == 0 ? "READ" : r->ExceptionInformation[0] == 1 ? "WRITE" : "EXEC(DEP)", a, region(a), bo.c_str());
    }
    logf_("  RSP 0x%llx RAX 0x%llx RCX 0x%llx RDX 0x%llx R8 0x%llx R9 0x%llx RBX 0x%llx RDI 0x%llx RSI 0x%llx",
          c->Rsp, c->Rax, c->Rcx, c->Rdx, c->R8, c->R9, c->Rbx, c->Rdi, c->Rsi);
    uint64_t* sp = (uint64_t*)(uintptr_t)c->Rsp;
    std::string st = "  stack qwords:";
    for (int i = 0; i < 12; ++i) { MEMORY_BASIC_INFORMATION mbi; if (VirtualQuery(sp + i, &mbi, sizeof(mbi)) && (mbi.State & MEM_COMMIT)) st += " " + hx(sp[i]); }
    logf_("%s", st.c_str());
    ExitProcess(3);
}

// ---- protections from the (packer's) section table: RX code, RW data, RWX where the header says so ----------------------
static void applySectionProtections(bool rwxAll) {
    uint8_t* b = (uint8_t*)(uintptr_t)M.exe_base;
    if (rwxAll) { logf_("  protections: whole image RWX (--prot rwx)"); return; }
    IMAGE_DOS_HEADER* dh = (IMAGE_DOS_HEADER*)b; IMAGE_NT_HEADERS64* nt = (IMAGE_NT_HEADERS64*)(b + dh->e_lfanew);
    IMAGE_SECTION_HEADER* sh = IMAGE_FIRST_SECTION(nt);
    DWORD old;
    VirtualProtect(b, 0x1000, PAGE_READONLY, &old);
    for (int i = 0; i < nt->FileHeader.NumberOfSections; ++i) {
        DWORD ch = sh[i].Characteristics; bool x = (ch & IMAGE_SCN_MEM_EXECUTE) != 0, w = (ch & IMAGE_SCN_MEM_WRITE) != 0;
        DWORD prot = x ? (w ? PAGE_EXECUTE_READWRITE : PAGE_EXECUTE_READ) : (w ? PAGE_READWRITE : PAGE_READONLY);
        uint64_t va = M.exe_base + sh[i].VirtualAddress, sz = sh[i].Misc.VirtualSize;
        if (!VirtualProtect((void*)(uintptr_t)va, (SIZE_T)sz, prot, &old)) die(2, "VirtualProtect section %d failed", i);
        logf_("  section %2d va 0x%llx size 0x%llx char 0x%08lx -> %s", i, va, sz, ch, prot == PAGE_EXECUTE_READWRITE ? "RWX" : prot == PAGE_EXECUTE_READ ? "RX" : prot == PAGE_READWRITE ? "RW" : "R");
    }
}

// ---- C1 self-checks ------------------------------------------------------------------------------------------------------
static int g_fail = 0;
static void check(bool ok, const char* what, uint64_t got, uint64_t want) {
    logf_("  %s %-52s got 0x%llx want 0x%llx", ok ? "OK  " : "FAIL", what, got, want); if (!ok) ++g_fail;
}
#define RD64(a) (*(uint64_t*)(uintptr_t)(a))
#define RD32(a) (*(uint32_t*)(uintptr_t)(a))
#define WR64(a, v) (*(uint64_t*)(uintptr_t)(a) = (uint64_t)(uintptr_t)(v))
#define WR32(a, v) (*(uint32_t*)(uintptr_t)(a) = (uint32_t)(v))

static void selfChecks() {
    logf_("C1 self-checks (DETERMINISM-CONTRACT s7):");
    check(RD64(GS_ADDR) == g_arena, "game_state+0 == arena", RD64(GS_ADDR), g_arena);
    check(RD64(GS_ADDR + 0x10) == FRAME_FN, "game_state+0x10 == FUN_140607d60", RD64(GS_ADDR + 0x10), FRAME_FN);
    check(RD64(GS_ADDR + 0x1B0) == M.blk, "game_state+0x1B0 == blk", RD64(GS_ADDR + 0x1B0), M.blk);
    check(RD64(GS_ADDR + 0x1B8) == BLK_SIZE_EXPECT, "game_state+0x1B8 == 0x33B18", RD64(GS_ADDR + 0x1B8), BLK_SIZE_EXPECT);
    check(RD64(GS_ADDR + 0x208) == g_arena + 0xA400000, "game_state+0x208 == arena+0xA400000 (staging)", RD64(GS_ADDR + 0x208), g_arena + 0xA400000);
    check(RD64(DAT_BLK) == M.blk, "DAT_142edf560 == blk", RD64(DAT_BLK), M.blk);
    check(RD64(DAT_G) == M.blk + 0x3CB8, "DAT_142edf580 == blk+0x3CB8", RD64(DAT_G), M.blk + 0x3CB8);
    check(RD64(DAT_ENTITY) == M.blk + 0x324E0, "DAT_142edf628 == blk+0x324E0", RD64(DAT_ENTITY), M.blk + 0x324E0);
    check(RD64(DAT_CTX) == M.ctx, "DAT_142ef0ab0 == ctx", RD64(DAT_CTX), M.ctx);
    check(RD64(DAT_GGPOSESS) == 0, "DAT_142e10b98 (GGPO session) == 0", RD64(DAT_GGPOSESS), 0);
    check(RD64(M.ctx + 0) == g_arena, "ctx[0] == arena (AFS image)", RD64(M.ctx), g_arena);
    check(RD64(M.ctx + 8) == M.dcram, "ctx[1] == dcram", RD64(M.ctx + 8), M.dcram);
    check(RD64(M.ctx + 16) == M.blk, "ctx[2] == blk", RD64(M.ctx + 16), M.blk);
    check(RD64(M.ctx + 0x1f81b0) == M.blk, "ctx+0x1f81b0 (matrix storage) == blk", RD64(M.ctx + 0x1f81b0), M.blk);
    check(RD32(M.ctx + 0x1f80a4) == 1, "ctx+0x1f80a4 (matrix mode) == 1", RD32(M.ctx + 0x1f80a4), 1);
    unsigned seen = 0; bool okp = true;
    for (int k = 0; k < 6; ++k) {
        uint64_t p = RD64(M.blk + SLOTPTRS_OFF + 8 * k); int64_t rel = (int64_t)p - (int64_t)M.blk - FIGHTER0;
        if (rel < 0 || rel % FSTRIDE || rel / FSTRIDE >= 6) { okp = false; logf_("    self-pointer %d = 0x%llx is not a fighter slot", k, p); }
        else seen |= 1u << (rel / FSTRIDE);
    }
    check(okp && seen == 0x3F, "blk+0x32500+8k = permutation of blk+0x3DB8+n*0x738", seen, 0x3F);
    uint8_t* mb = (uint8_t*)(uintptr_t)(M.blk + MODE_OFF);
    check(mb[0] == 2 && mb[1] == 1 && mb[2] == 2, "mode bytes blk+0x3CB8[0..2] == 2,1,2", (uint64_t)mb[0] | ((uint64_t)mb[1] << 8) | ((uint64_t)mb[2] << 16), 0x020102);
    check(RD32(M.blk + CLOCK_OFF) == M.clock_value, "blk+0x3CC8 clock == meta.clock_value", RD32(M.blk + CLOCK_OFF), M.clock_value);
}

// ---- the tick loop (own thread: 16 MiB stack; single thread, contract C9) -------------------------------------------------
struct Job { int ticks; std::vector<uint32_t> w0, w1; std::string out; int dumpEvery; bool dumpEnd; std::vector<double> ms; };
static Job J;
typedef void (*TickFn)(void*, uint32_t*, uint32_t);
static DWORD WINAPI tickThread(LPVOID) {
    unsigned csr = _mm_getcsr();
    logf_("MXCSR at entry = 0x%x (%s; contract C3 wants 0x1f80)", csr, csr == 0x1f80 ? "OK" : "DIFFERS");
    LARGE_INTEGER f, t0, t1; QueryPerformanceFrequency(&f);
    TickFn tick = (TickFn)(uintptr_t)FRAME_TICK;
    alignas(16) uint32_t inputs[4];
    uint32_t clock0 = RD32(M.blk + CLOCK_OFF);
    for (int k = 0; k < J.ticks; ++k) {
        g_tick = k + 1;
        inputs[0] = J.w0[k] & 0xFFFFFF; inputs[1] = J.w1[k] & 0xFFFFFF; inputs[2] = 0; inputs[3] = 0;
        QueryPerformanceCounter(&t0);
        tick((void*)(uintptr_t)GGPO_STATE, inputs, 0);
        QueryPerformanceCounter(&t1);
        double ms = 1000.0 * (double)(t1.QuadPart - t0.QuadPart) / (double)f.QuadPart; J.ms.push_back(ms);
        uint32_t clk = RD32(M.blk + CLOCK_OFF);
        if (clk != clock0 + k + 1) logf_("  tick %d: clock %u (EXPECTED %u)", k + 1, clk, clock0 + k + 1);
        if ((J.dumpEvery > 0 && ((k + 1) % J.dumpEvery) == 0) || k + 1 == J.ticks) {
            char p[MAX_PATH]; sprintf_s(p, "%s\\blk_t%03d.bin", J.out.c_str(), k + 1); dumpRange(p, M.blk, M.blk_size);
        }
        if (k < 3 || (k + 1) % 50 == 0 || k + 1 == J.ticks)
            logf_("  tick %3d: clock %u  in {%06x,%06x}  %.3f ms  rng %02x%02x  ext[alloc %llu free %llu flsget %llu flsset %llu gle %llu sle %llu]",
                  k + 1, clk, inputs[0], inputs[1], ms, *(uint8_t*)(uintptr_t)(M.blk + 0x32BD4), *(uint8_t*)(uintptr_t)(M.blk + 0x32BD5),
                  g_cnt[0], g_cnt[2], g_cnt[5], g_cnt[6], g_cnt[3], g_cnt[4]);
    }
    if (J.dumpEnd) {
        dumpRange(J.out + "\\gs_out.bin", GS_ADDR, 0x1000);
        dumpRange(J.out + "\\ctx_out.bin", M.ctx, M.ctx_size);
        dumpRange(J.out + "\\exe_dat_out.bin", 0x142edf300ull, 0x300);
        dumpRange(J.out + "\\exe_str_out.bin", 0x142eed900ull, 0x300);
        dumpRange(J.out + "\\ggpo_out.bin", GGPO_STATE, 0x10);
    }
    return 0;
}

static void usage() {
    puts("rr_runner --pre <run\\pre dir> --out <dir> [--ticks N] [--inputs <file: one line per tick, hex 'w0 w1'>]\n"
         "          [--gs exe|file] [--crt stub|real] [--fma 0|1] [--prot sections|rwx] [--dump-every N] [--no-dump-end] [--force]\n"
         "  --gs exe   : keep the game_state page embedded in exe_image.bin (what the p-code oracle uses)   [default]\n"
         "  --gs file  : overlay game_state.bin (the tape anchor's page) -- the one-variable test of RECEIPT-RUNNER-RE s1.4\n"
         "  --crt stub : FlsGetValue->0, FlsSetValue->0, GetLastError->0 (exactly the harness's extstub)      [default]\n"
         "  --crt real : a real per-index FLS value + last-error variable (the CRT reuses its ptd)\n"
         "  --fma 0    : DAT_142eefbd8 = 0 (SSE2 CRT path, what the harness runs)                                  [default]\n"
         "  --lazy on  : zero-commit host-heap pages on first touch (the harness's sparse-memory model), logged   [default]\n"
         "  --lazy off : any such touch is fatal and reported (RIP, address, region)\n");
    exit(1);
}

int main(int argc, char** argv) {
    std::string pre, out, inputs; int ticks = 20, dumpEvery = 1; bool gsFile = false, rwx = false, force = false, dumpEnd = true; int fma = 0;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i]; auto next = [&]() -> std::string { if (i + 1 >= argc) usage(); return argv[++i]; };
        if (a == "--pre") pre = next(); else if (a == "--out") out = next(); else if (a == "--ticks") ticks = atoi(next().c_str());
        else if (a == "--inputs") inputs = next(); else if (a == "--gs") gsFile = next() == "file"; else if (a == "--crt") g_crtReal = next() == "real";
        else if (a == "--fma") fma = atoi(next().c_str()); else if (a == "--prot") rwx = next() == "rwx"; else if (a == "--dump-every") dumpEvery = atoi(next().c_str());
        else if (a == "--no-dump-end") dumpEnd = false; else if (a == "--force") force = true; else if (a == "--lazy") g_lazyOn = next() != "off"; else usage();
    }
    if (pre.empty() || out.empty()) usage();
    CreateDirectoryA(out.c_str(), nullptr);
    fopen_s(&g_log, (out + "\\runner.log").c_str(), "wb");
    AddVectoredExceptionHandler(1, veh);

    // -- 0. where am I? the runner must not sit on the link base or the arena --------------------------------------
    std::string meta = readFile(pre + "\\meta.json");
    M.exe_base = jsonU64(meta, "exe_base"); M.exe_size = jsonU64(meta, "exe_size");
    M.blk = jsonU64(meta, "blk"); M.blk_size = jsonU64(meta, "blk_size"); M.blk2 = jsonU64(meta, "blk2"); M.blk2_size = jsonU64(meta, "blk2_size");
    M.ctx = jsonU64(meta, "ctx"); M.ctx_size = jsonU64(meta, "ctx_size"); M.dcram = jsonU64(meta, "dcram"); M.dcram_size = jsonU64(meta, "dcram_size");
    M.dc_base = jsonU64(meta, "dc_base"); M.clock_value = jsonU64(meta, "clock_value");
    if (M.exe_base != EXE_BASE_EXPECT) die(2, "meta exe_base 0x%llx != 0x140000000 (the image is position-dependent, contract C1)", M.exe_base);
    std::string gsp = readFile(pre + "\\game_state.bin"); if (gsp.size() != 0x1000) die(2, "game_state.bin is not 0x1000 B");
    memcpy(&g_arena, gsp.data(), 8);
    if (M.ctx != g_arena + 0x8000000 || M.dcram != g_arena + 0x8400000) die(2, "arena layout: ctx 0x%llx dcram 0x%llx do not sit at arena 0x%llx +0x8000000/+0x8400000", M.ctx, M.dcram, g_arena);
    if (M.blk < g_arena || M.blk2 + M.blk2_size > g_arena + ARENA_SIZE) die(2, "blk 0x%llx..0x%llx outside the 256 MiB arena at 0x%llx", M.blk, M.blk2 + M.blk2_size, g_arena);
    uint64_t self = (uint64_t)(uintptr_t)GetModuleHandleA(nullptr);
    logf_("rr_runner pid %lu self-image 0x%llx  arena 0x%llx..0x%llx  exe 0x%llx..0x%llx  blk 0x%llx  ctx 0x%llx  dcram 0x%llx  clock %llu",
          GetCurrentProcessId(), self, g_arena, g_arena + ARENA_SIZE, M.exe_base, M.exe_base + M.exe_size, M.blk, M.ctx, M.dcram, M.clock_value);
    if ((self >= M.exe_base && self < M.exe_base + M.exe_size) || (self >= g_arena && self < g_arena + ARENA_SIZE)) die(2, "the runner itself is mapped inside the game's ranges");

    // -- 1. reserve + commit the arena and the image at their exact addresses (fail loudly) --------------------------
    auto reserveAt = [&](uint64_t base0, uint64_t size0, DWORD prot, const char* what) {
        // VirtualAlloc rounds a base down to the 64 KiB allocation granularity (the game's arena base 0x..1000 is not
        // aligned: it is an offset into a larger allocation), so request the rounded range and check THAT.
        uint64_t base = base0 & ~0xFFFFull, size = ((base0 + size0 + 0xFFFFull) & ~0xFFFFull) - base;
        void* p = VirtualAlloc((void*)(uintptr_t)base, (SIZE_T)size, MEM_RESERVE | MEM_COMMIT, prot);
        if ((uint64_t)(uintptr_t)p != base) {
            DWORD err = GetLastError(); MEMORY_BASIC_INFORMATION mbi; uint64_t a = base; std::string who;
            while (a < base + size && VirtualQuery((void*)(uintptr_t)a, &mbi, sizeof(mbi))) {
                if (mbi.State != MEM_FREE) who += "\n    busy 0x" + hx((uint64_t)(uintptr_t)mbi.BaseAddress) + "..0x" + hx((uint64_t)(uintptr_t)mbi.BaseAddress + mbi.RegionSize) + " state 0x" + hx(mbi.State) + " type 0x" + hx(mbi.Type);
                a = (uint64_t)(uintptr_t)mbi.BaseAddress + mbi.RegionSize;
            }
            die(2, "%s: VirtualAlloc(0x%llx, 0x%llx) returned %p (error %lu); conflicting regions:%s", what, base, size, p, err, who.c_str());
        }
        logf_("  reserved+committed %s at 0x%llx (0x%llx B; requested 0x%llx+0x%llx)", what, base, size, base0, size0);
    };
    reserveAt(g_arena, ARENA_SIZE, PAGE_READWRITE, "arena");
    reserveAt(M.exe_base, M.exe_size, PAGE_EXECUTE_READWRITE, "exe image");
    g_heapBase = (uint64_t)(uintptr_t)VirtualAlloc(nullptr, (SIZE_T)HEAP_BYTES, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (!g_heapBase) die(2, "runner heap alloc failed");
    g_heapCur = g_heapBase; g_heapEnd = g_heapBase + HEAP_BYTES;

    // -- 2. images ------------------------------------------------------------------------------------------------
    logf_("loading images from %s", pre.c_str());
    loadInto(pre + "\\exe_image.bin", M.exe_base, M.exe_size);
    if (gsFile) { memcpy((void*)(uintptr_t)GS_ADDR, gsp.data(), 0x1000); logf_("  game_state.bin overlaid at 0x%llx (--gs file)", GS_ADDR); }
    else logf_("  game_state page = the one embedded in exe_image.bin (--gs exe; the oracle's configuration)");
    loadInto(pre + "\\blk.bin", M.blk, M.blk_size);
    loadInto(pre + "\\blk2.bin", M.blk2, M.blk2_size);
    loadInto(pre + "\\ctx.bin", M.ctx, M.ctx_size);
    loadInto(pre + "\\dcram.bin", M.dcram, M.dcram_size);

    // -- 3. externals: replace the six, trap the rest ---------------------------------------------------------------
    buildExportMap();
    logf_("IAT 0x%llx..0x%llx: replacing the C6 set, trapping every other slot", IAT_LO, IAT_HI);
    int nslots = 0, nrepl = 0, ntrap = 0;
    struct Repl { uint64_t slot; void* fn; const char* name; };
    Repl repl[] = {
        { SLOT_RTLALLOC, (void*)&rr_RtlAllocateHeap, "RtlAllocateHeap" }, { SLOT_RTLREALLOC, (void*)&rr_RtlReAllocateHeap, "RtlReAllocateHeap" },
        { SLOT_HEAPFREE, (void*)&rr_HeapFree, "HeapFree" }, { SLOT_GETLASTERR, (void*)&rr_GetLastError, "GetLastError" }, { SLOT_SETLASTERR, (void*)&rr_SetLastError, "SetLastError" } };
    FILE* fm = nullptr; fopen_s(&fm, (out + "\\iat_map.txt").c_str(), "wb");
    for (uint64_t s = IAT_LO; s < IAT_HI; s += 8) {
        uint64_t v = RD64(s); if (v < 0x7ff000000000ull || v >= 0x800000000000ull) continue;
        ++nslots; std::string nm = nameOf(v); bool done = false;
        for (auto& r : repl) if (r.slot == s) {
            if (nm.find(r.name) == std::string::npos && nm.find("unresolved") == std::string::npos) die(2, "slot 0x%llx expected %s but the same-boot export map says %s", s, r.name, nm.c_str());
            WR64(s, r.fn); ++nrepl; done = true; logf_("  slot 0x%llx = %-40s -> runner %s", s, nm.c_str(), r.name);
        }
        if (!done) { WR64(s, makeTrap("import slot 0x" + hx(s) + " = " + nm)); ++ntrap; }
        if (fm) fprintf(fm, "0x%llx 0x%llx %s%s\n", s, v, nm.c_str(), done ? "  [REPLACED]" : "  [TRAP]");
    }
    if (fm) fclose(fm);
    logf_("  %d import slots: %d replaced, %d trapped (map: iat_map.txt)", nslots, nrepl, ntrap);
    if (nrepl != 5) die(2, "expected to replace 5 IAT slots, replaced %d", nrepl);
    logf_("UCRT try_get_function cache 0x%llx (cookie 0x%llx):", UCRT_TABLE, RD64(SECURITY_COOKIE));
    for (int i = 0; i < UCRT_TABLE_N; ++i) {
        uint64_t e = RD64(UCRT_TABLE + 8 * i), d = crtDecode(e);
        if (d == 0 || d == ~0ull) continue;
        std::string nm = nameOf(d);
        if (i == UCRT_ID_FLSGET) {
            if (nm.find("FlsGetValue") == std::string::npos && nm.find("unresolved") == std::string::npos) die(2, "cache id 5 is not FlsGetValue: %s", nm.c_str());
            WR64(UCRT_TABLE + 8 * i, crtEncode((uint64_t)(uintptr_t)&rr_FlsGetValue)); logf_("  [%2d] %-40s -> runner FlsGetValue (%s)", i, nm.c_str(), g_crtReal ? "real" : "stub -> 0");
        } else if (i == UCRT_ID_FLSSET) {
            if (nm.find("FlsSetValue") == std::string::npos && nm.find("unresolved") == std::string::npos) die(2, "cache id 6 is not FlsSetValue: %s", nm.c_str());
            WR64(UCRT_TABLE + 8 * i, crtEncode((uint64_t)(uintptr_t)&rr_FlsSetValue)); logf_("  [%2d] %-40s -> runner FlsSetValue (%s)", i, nm.c_str(), g_crtReal ? "real" : "stub -> 0");
        } else {
            WR64(UCRT_TABLE + 8 * i, crtEncode(makeTrap("UCRT cache id " + std::to_string(i) + " = " + nm))); logf_("  [%2d] %-40s -> TRAP", i, nm.c_str());
        }
    }
    if (crtDecode(RD64(UCRT_TABLE + 8 * UCRT_ID_FLSGET)) != (uint64_t)(uintptr_t)&rr_FlsGetValue) die(2, "UCRT cache encode/decode round trip failed");

    // -- 4. process-specific globals (RECEIPT-RUNNER-RE s3.1 'exe globals holding process-specific pointers') --------
    void* ring = VirtualAlloc(nullptr, (SIZE_T)DEBUGRING_BYTES, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    logf_("globals: DAT_142ebc010 0x%llx -> runner zeroed ring buffer %p; DAT_142eefbd8 %u -> %d; seat map -> {0,1,-1,-1}", RD64(DAT_DEBUGRING), ring, RD32(DAT_FMAFLAG), fma);
    WR64(DAT_DEBUGRING, ring); WR32(DAT_FMAFLAG, fma);
    WR32(GS_ADDR + 0x258, 0); WR32(GS_ADDR + 0x25C, 1); WR32(GS_ADDR + 0x260, 0xFFFFFFFFu); WR32(GS_ADDR + 0x264, 0xFFFFFFFFu);

    // -- 5. protections + self-checks --------------------------------------------------------------------------------
    applySectionProtections(rwx);
    selfChecks();
    if (g_fail && !force) die(4, "%d self-check(s) failed; refusing to tick (--force to override)", g_fail);

    // -- 6. inputs -------------------------------------------------------------------------------------------------
    J.ticks = ticks; J.out = out; J.dumpEvery = dumpEvery; J.dumpEnd = dumpEnd;
    if (!inputs.empty()) {
        std::string t = readFile(inputs); size_t p = 0;
        while (p < t.size()) {
            size_t e = t.find('\n', p); if (e == std::string::npos) e = t.size();
            std::string ln = t.substr(p, e - p); p = e + 1;
            if (ln.empty() || ln[0] == '#') continue;
            char* endp = nullptr; uint32_t a = (uint32_t)strtoul(ln.c_str(), &endp, 16); uint32_t b = (uint32_t)strtoul(endp, nullptr, 16);
            J.w0.push_back(a); J.w1.push_back(b);
        }
        if ((int)J.w0.size() < ticks) die(2, "inputs file has %zu lines, need %d", J.w0.size(), ticks);
    } else { J.w0.assign(ticks, 0); J.w1.assign(ticks, 0); }
    logf_("ticking FUN_140118950 x %d (inputs: %s)", ticks, inputs.empty() ? "idle, all zero" : inputs.c_str());

    // -- 7. run ----------------------------------------------------------------------------------------------------
    HANDLE th = CreateThread(nullptr, 16u << 20, tickThread, nullptr, 0, nullptr);
    if (!th) die(2, "CreateThread failed");
    WaitForSingleObject(th, INFINITE);

    // -- 8. summary ------------------------------------------------------------------------------------------------
    std::vector<double> s = J.ms; std::sort(s.begin(), s.end());
    double sum = 0; for (double x : s) sum += x;
    auto pct = [&](double q) { return s.empty() ? 0.0 : s[std::min(s.size() - 1, (size_t)(q * s.size()))]; };
    logf_("TIMING per tick (ms): n=%zu min %.3f p50 %.3f mean %.3f p90 %.3f p99 %.3f max %.3f  (real-time budget 16.667)", s.size(), s.empty() ? 0 : s[0], pct(0.5), s.empty() ? 0 : sum / s.size(), pct(0.9), pct(0.99), s.empty() ? 0 : s.back());
    logf_("EXTERNALS: RtlAllocateHeap %llu (%llu B) RtlReAllocateHeap %llu HeapFree %llu GetLastError %llu SetLastError %llu FlsGetValue %llu FlsSetValue %llu; traps hit 0",
          g_cnt[0], g_allocBytes, g_cnt[1], g_cnt[2], g_cnt[3], g_cnt[4], g_cnt[5], g_cnt[6]);
    // host-heap pages of the DUMPING process that the tick touched through baked pointers: name the .data global that
    // points into each 64 KiB page (owner hint) -- these are the s5.3 objects the loader must provide (zeroed suffices
    // for byte-exactness vs the harness; READ-first pages are the ones the harness listed as `uninit`).
    logf_("LAZY host-heap pages committed on first touch: %zu%s", g_lazy.size(), g_lazy.size() >= LAZY_MAX ? " (CAP HIT)" : "");
    std::string lazyJson;
    for (auto& L : g_lazy) {
        // owner hint: .data qwords pointing into the page, or up to 1 MiB below it (the object's base pointer; e.g. the
        // NaomiLib device object *0x140acd3a8 whose PALETTE_RAM at +0xD8D04 is what FUN_140613390 uploads).
        std::string owners; std::vector<std::pair<uint64_t, uint64_t>> cands;
        for (uint64_t g = 0x140a31000ull; g < 0x142f71000ull; g += 8) {   // .data section (packer's table: va 0xA31000, size 0x2540000)
            uint64_t v = RD64(g); if (v + 0x100000 >= L.page && v < L.page + 0x10000) cands.push_back({v, g});
        }
        std::sort(cands.begin(), cands.end(), [](auto& x, auto& y) { return x.first > y.first; });
        for (size_t i = 0; i < cands.size() && i < 6; ++i) owners += " *0x" + hx(cands[i].second) + "=0x" + hx(cands[i].first);
        if (cands.size() > 6) owners += " ...";
        logf_("  page 0x%llx first %s by RIP 0x%llx (RVA 0x%llx) tick %ld; .data globals pointing into it:%s", L.page, L.kind ? "WRITE" : "READ", L.rip, L.rip - M.exe_base, L.tick, owners.empty() ? " none" : owners.c_str());
        lazyJson += (lazyJson.empty() ? "" : ",") + std::string("{\"page\":\"0x") + hx(L.page) + "\",\"kind\":\"" + (L.kind ? "write" : "read") + "\",\"rip\":\"0x" + hx(L.rip) + "\",\"tick\":" + std::to_string(L.tick) + ",\"owners\":\"" + owners + "\"}";
    }
    FILE* fs = nullptr; fopen_s(&fs, (out + "\\summary.json").c_str(), "wb");
    if (fs) {
        fprintf(fs, "{\"ticks\":%d,\"clock_start\":%llu,\"clock_end\":%u,\"gs\":\"%s\",\"crt\":\"%s\",\"fma\":%d,\"prot\":\"%s\",\"ext\":{\"RtlAllocateHeap\":%llu,\"alloc_bytes\":%llu,\"RtlReAllocateHeap\":%llu,\"HeapFree\":%llu,\"GetLastError\":%llu,\"SetLastError\":%llu,\"FlsGetValue\":%llu,\"FlsSetValue\":%llu},\"lazy_pages\":[%s],\"ms\":[",
                ticks, M.clock_value, RD32(M.blk + CLOCK_OFF), gsFile ? "file" : "exe", g_crtReal ? "real" : "stub", fma, rwx ? "rwx" : "sections", g_cnt[0], g_allocBytes, g_cnt[1], g_cnt[2], g_cnt[3], g_cnt[4], g_cnt[5], g_cnt[6], lazyJson.c_str());
        for (size_t i = 0; i < J.ms.size(); ++i) fprintf(fs, "%s%.4f", i ? "," : "", J.ms[i]);
        fprintf(fs, "]}\n"); fclose(fs);
    }
    logf_("DONE: %d ticks, clock %llu -> %u, dumps in %s", ticks, M.clock_value, RD32(M.blk + CLOCK_OFF), out.c_str());
    return 0;
}
