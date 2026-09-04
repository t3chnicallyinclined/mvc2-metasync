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
#pragma comment(lib, "user32.lib")

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
static uint64_t HEAP_BYTES              = 64ull << 20;   // --heap-mb. A WRAP re-zeroes the heap inside one tick,
                                                         // which becomes a single huge outlier in the N1b max
                                                         // column, so deep-ring timing runs must avoid wrapping.

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
static uint64_t g_heapWraps = 0;
static PVOID WINAPI rr_RtlAllocateHeap(PVOID, ULONG, SIZE_T n) {
    ++g_cnt[0]; g_allocBytes += n;
    if (g_heapCur + n + 16 > g_heapEnd) {
        // GATE N1: a resim re-runs the same ticks, so the bump heap is consumed N+1 times faster. Wrap and re-zero the
        // USED part -- the CRT asks HEAP_ZERO_MEMORY and Gate 1 proved 300 ticks byte-exact with a monotonically
        // advancing pointer, so handing back a re-zeroed chunk is equivalent. Logged: a wrap pollutes one tick sample.
        memset((void*)(uintptr_t)g_heapBase, 0, (size_t)(g_heapCur - g_heapBase));
        g_heapCur = g_heapBase; ++g_heapWraps;
    }
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
struct Job { int ticks; std::vector<uint32_t> w0, w1; std::string out; int dumpEvery; bool dumpEnd; std::vector<double> ms;
             bool play = false; int playFrames = 1200; bool playHarvest = false;
             bool harvest = false; std::vector<uint8_t> dcShadow; uint64_t dcDeltaPages = 0, dcDeltaBytes = 0; std::string dcDeltaSummary; };
static Job J;
// ---- GATE 2 harvest dump (docs/RECEIPT-RUNNER-GATE2.md): everything the agent's harvest reads, per tick -----------------
// The harvest (RetroReceipts-agent agent/src/harvest.rs, RENDER s2.2 field->region table) reads blk, the game_state page
// (seat words G+0x218, seat map, localPlayerNum, rollback counter), the exe page 0x142edf300..0x700 (entity/set-score
// pointer DAT_142edf628) and DC-RAM through pointers (palettes at *(H+0x1B8), polygon-list objects at *(node+0xA0)).
// blk is dumped per tick already; this adds the two pages per tick and the DC-RAM pages that CHANGED since the previous
// tick (4 KiB granularity, memcmp against a shadow copy) -- measured, because RECEIPT-RUNNER-RE s1.1 measured the write
// set on the training stage only and a real stage animates props in place (RE s1.2 LAB_14064cb20). The tape emitter
// replays the deltas in order to hold the exact DC-RAM image of tick k.
//   gs_tNNN.bin     0x1000 B @ 0x140ac6d40          exe_tNNN.bin  0x400 B @ 0x142edf300
//   dcram_tNNN.dlt  records {u32 dc_off_from_dcram_base, u32 len=4096, 4096 B} for every page that differs from tick NNN-1
//   t000 = the state after the loader/self-checks, before the first tick (the anchor as the runner holds it).
static const uint64_t EXE_PAGE_ADDR = 0x142edf300ull, EXE_PAGE_LEN = 0x400ull, DC_PAGE = 0x1000ull;
static void harvestDump(int k) {
    char p[MAX_PATH];
    sprintf_s(p, "%s\\gs_t%03d.bin", J.out.c_str(), k); dumpRange(p, GS_ADDR, 0x1000);
    sprintf_s(p, "%s\\exe_t%03d.bin", J.out.c_str(), k); dumpRange(p, EXE_PAGE_ADDR, EXE_PAGE_LEN);
    if (k == 0) { J.dcShadow.assign((const uint8_t*)(uintptr_t)M.dcram, (const uint8_t*)(uintptr_t)(M.dcram + M.dcram_size)); return; }
    sprintf_s(p, "%s\\dcram_t%03d.dlt", J.out.c_str(), k);
    FILE* f = nullptr; if (fopen_s(&f, p, "wb") || !f) die(2, "cannot write %s", p);
    const uint8_t* live = (const uint8_t*)(uintptr_t)M.dcram; uint64_t pages = 0; std::string ranges; uint64_t rs = ~0ull, re = 0;
    for (uint64_t off = 0; off < M.dcram_size; off += DC_PAGE) {
        if (memcmp(live + off, J.dcShadow.data() + off, (size_t)DC_PAGE) == 0) { if (rs != ~0ull) { ranges += " " + hx(M.dc_base + rs) + "-" + hx(M.dc_base + re); rs = ~0ull; } continue; }
        uint32_t o32 = (uint32_t)off, l32 = (uint32_t)DC_PAGE;
        fwrite(&o32, 4, 1, f); fwrite(&l32, 4, 1, f); fwrite(live + off, 1, (size_t)DC_PAGE, f);
        memcpy(J.dcShadow.data() + off, live + off, (size_t)DC_PAGE); ++pages;
        if (rs == ~0ull) rs = off; re = off + DC_PAGE;
    }
    if (rs != ~0ull) ranges += " " + hx(M.dc_base + rs) + "-" + hx(M.dc_base + re);
    fclose(f);
    J.dcDeltaPages += pages; J.dcDeltaBytes += pages * DC_PAGE;
    if (k <= 3 || pages > 64) logf_("  harvest tick %3d: %llu DC-RAM pages changed (DC%s)", k, pages, ranges.c_str());
    if (J.dcDeltaSummary.size() < 4000) J.dcDeltaSummary += (J.dcDeltaSummary.empty() ? "" : ";") + std::to_string(k) + ":" + std::to_string(pages);
}
// ---- GATE N1: rollback / resimulation -- sufficiency proof + interleaved timing --------------------------------------
// docs/RECEIPT-RUNNER-GATE-N1.md.  The shipped netcode's GGPO save/load callbacks persist only `blk`.  Our runner
// additionally touches host state the shipped game never has to think about: the lazily-committed device-object page
// *(0x140acd3a8) whose PALETTE_RAM the tick WRITES (GATE1 s3.4) and the ctx page-table records (GATE1 s3.5, proven
// run-dependent in GATE3 s5).  `--rollback N` answers both questions in ONE interleaved loop, which is the point --
// a save measurement and a tick measurement composed after the fact are not a rollback measurement:
//   (a) SUFFICIENCY: save only the chosen set every tick; after tick k, restore the slot saved at tick k-N, re-tick
//       the same N inputs, and compare EVERY candidate region against the straight-line state at the same clock.
//       If the set is `blk` and everything still matches, blk-only rollback is sufficient for this runner.
//   (b) TIMING: save / restore / resim measured inside that loop, per event, with the straight-line tick alongside.
// N = 0 is the floor: save + restore, zero resim ticks (must be trivially exact).
struct Region { uint64_t addr, size; const char* name; };
static int         g_rbN = -1;              // -1 = mode off
static std::string g_rbSet = "blk";
static std::vector<std::pair<uint64_t, uint64_t> > g_rbCtxExtra;   // --rb-ctx-extra LO-HI[,LO-HI...] (ctx offsets)         // blk | blk2 | sim | full
static int         g_rbVerify = 2;          // 0 = blk only, 1 = small regions, 2 = + ctx/dcram/lazy pages
static bool        g_rbReset = true;        // on a mismatch, restore the reference so later events stay independent
static int         g_rbMaxEvents = 0;       // 0 = an event after every tick k >= N
static std::vector<double> g_rbSaveMs, g_rbRestoreMs, g_rbResimMs;
// N1b (netcode lane, 2026-09-04): the amortised ms/frame column is ELIGIBILITY-WEIGHTED -- a depth-N rollback can
// only fire after tick k >= N, so dividing by ALL ticks understates the cost by (ticks-N)/ticks and is undefined for
// a run of <= N ticks. A frame budget is a DEADLINE, not an average. These two vectors carry the per-EVENT cost:
//   g_rbEventMs = save + restore + resim   -- the rollback overhead on the frame that rolled back
//   g_rbFrameMs = that + the straight-line tick of the same frame -- the TOTAL work that frame must fit in 16.667 ms
static std::vector<double> g_rbEventMs, g_rbFrameMs;
static const double FRAME_BUDGET_MS = 16.667;
static int g_rbEvents = 0, g_rbFailEvents = 0;
static std::string g_rbJson;
static std::map<std::string, uint64_t> g_rbCtxBuckets;
static std::string g_rbCtxJson;
static uint64_t g_rbNondetEvents = 0, g_rbNondetBytes = 0;
static std::string g_rbFirstFail;
// the ctx page-table residual of GATE1 s3.5 / GATE3 s5: isolated 4-byte fields at stride 0x130 inside the decoded
// texture-page area.  It is run-dependent host state that the tick never reads, so it is counted but NOT a failure.
static const uint64_t CTX_PT_LO = 0x100000ull, CTX_PT_HI = 0x120000ull;
// The ctx READ set of one frame (FRAME-READSET s3.4): the texture-slot table (which the tick both reads and writes,
// so it is a candidate rollback region) and the NaomiLib matrix-stack state (GATE3 s6, 288 B, individually gated).
static const uint64_t CTX_SLOTTAB_LO = 0x1E0030ull, CTX_SLOTTAB_HI = 0x1E31CCull;
static const uint64_t CTX_MATRIX_LO  = 0x1F80A0ull, CTX_MATRIX_HI  = 0x1F81C0ull;
// GATE N1, bisected 2026-09-04: with blk + blk2 + gs page + exe page + the ctx slot table + the ctx matrix state all
// restored, a resim STILL diverged in blk (object-pool node 144 field +0x124, a sprite-walker placement field --
// blkmap: blk+0x1D6FC = DC 0x8C27B034) on 3 of 193 events at depth 8. Restoring these EIGHT bytes as well makes it
// exact, and every 4-byte half of them fails on its own, so both dwords are load-bearing. They sit inside the
// NaomiLib projection/viewport block that FUN_140846a40 initialises wholesale (MOVUPS [ctx+0x1F8230],XMM1 at
// 0x140846BF7); no literal 0x1F8230/0x1F8234 displacement exists anywhere in the 10,803-function disassembly cache,
// so the per-frame access is indexed -- the reader is INFERRED, the requirement is CONFIRMED by bisection.
// Neighbours for orientation: +0x1F8200/+0x1F8214 = +/-812.357 (focal length), +0x1F8220 = -320.0, +0x1F8224 = -338.4.
static const uint64_t CTX_PROJ_LO = 0x1F8230ull, CTX_PROJ_HI = 0x1F8238ull;
// Buckets used to CLASSIFY a ctx difference instead of guessing at it (FRAME-READSET s3.4 write list).
struct CtxBucket { uint64_t lo, hi; const char* name; };
static const CtxBucket CTX_BUCKETS[] = {
    { 0x000030ull, 0x0007ECull, "TA-records-1" },
    { 0x030030ull, 0x03130Cull, "TA-records-2" },
    { 0x100030ull, 0x108FC0ull, "decoded-texture-pages" },
    { 0x108FC0ull, 0x1E0030ull, "page-table-records(GATE1 s3.5 stale stack)" },
    { 0x1E0030ull, 0x1E31CCull, "TEXTURE-SLOT-TABLE(read+write)" },
    { 0x1F8000ull, 0x1F9000ull, "matrix-stack" },
};
// Two ctx buckets are PROVEN nondeterministic, not missing rollback state: at depth 1 with --rb-set full (blk +
// blk2 + gs page + exe page + the whole 4 MB ctx + the whole 32 MB DC-RAM + the GGPO counter all restored), a single
// re-executed tick with the SAME input word still rewrites them. Nothing is left that could carry the difference, and
// neither range is on the frame's ctx READ set (FRAME-READSET s3.4: reads are ctx+0x8, +0x1E0030..0x1E31CA and
// +0x1F80A4..0x1F8564). This is the GATE1 s3.5 uninitialised-stack family, reproduced inside one process. Counted and
// reported, never a failure. Any OTHER ctx bucket differing IS a failure -- especially the texture-slot table, which
// the tick reads as well as writes and which would therefore be genuine rollback state.
static bool ctxBucketNondet(const char* n) {
    return strcmp(n, "decoded-texture-pages") == 0 || strcmp(n, "page-table-records(GATE1 s3.5 stale stack)") == 0;
}
static const char* ctxBucket(uint64_t off) {
    for (auto& b : CTX_BUCKETS) if (off >= b.lo && off < b.hi) return b.name;
    return "other";
}

static std::vector<Region> rbSaveSet() {
    std::vector<Region> v;
    v.push_back({ M.blk, M.blk_size, "blk" });
    if (g_rbSet != "blk" && g_rbSet != "rr" && g_rbSet != "blkctx") v.push_back({ M.blk2, M.blk2_size, "blk2" });
    // (blk is always first; the bisect tiers simctx / simdc / simtile exist to attribute a failure to ctx vs DC-RAM
    //  vs just the 0x0CE60000 tile buffer without re-running the whole matrix.)
    if (g_rbSet == "sim" || g_rbSet == "simctx" || g_rbSet == "simdc" || g_rbSet == "simtile" || g_rbSet == "full") {
        v.push_back({ GS_ADDR, 0x1000, "gs_page" });
        v.push_back({ EXE_PAGE_ADDR, EXE_PAGE_LEN, "exe_page" });
    }
    // `rr` is the RECOMMENDED set: the shipped game's blk, plus the 8 bytes GATE N1 proved are also required.
    if (g_rbSet == "rr") v.push_back({ M.ctx + CTX_PROJ_LO, CTX_PROJ_HI - CTX_PROJ_LO, "ctx_proj" });
    if (g_rbSet == "blkctx" || g_rbSet == "sim" || g_rbSet == "simctx" || g_rbSet == "simdc" || g_rbSet == "simtile" || g_rbSet == "full") {
        // the ctx READ set only: 0x319C slot table + 0x120 matrix state = 12,956 B, not the whole 4 MB context
        v.push_back({ M.ctx + CTX_SLOTTAB_LO, CTX_SLOTTAB_HI - CTX_SLOTTAB_LO, "ctx_slottab" });
        v.push_back({ M.ctx + CTX_MATRIX_LO, CTX_MATRIX_HI - CTX_MATRIX_LO, "ctx_matrix" });
        v.push_back({ M.ctx + CTX_PROJ_LO, CTX_PROJ_HI - CTX_PROJ_LO, "ctx_proj" });
    }
    for (size_t i = 0; i < g_rbCtxExtra.size(); ++i)
        v.push_back({ M.ctx + g_rbCtxExtra[i].first, g_rbCtxExtra[i].second - g_rbCtxExtra[i].first, "ctx_extra" });
    if (g_rbSet == "simctx" || g_rbSet == "full") v.push_back({ M.ctx, M.ctx_size, "ctx" });
    if (g_rbSet == "simdc" || g_rbSet == "full") v.push_back({ M.dcram, M.dcram_size, "dcram" });
    if (g_rbSet == "simtile") v.push_back({ M.dcram + 0x0E60000ull, 0x5000ull, "dcram_tilebuf" });
    // The GGPO counter at 0x142d10b90 is the WRAPPER's, not game state (contract C2, GATE1 s3.6): FUN_140118950
    // bumps it once per call, so a resim would advance it by N and every comparison would fail on bookkeeping.
    // It is restored in EVERY tier, and that is stated in the log so the choice is never silent.
    v.push_back({ GGPO_STATE, 0x10, "ggpo" });
    return v;
}
static std::vector<Region> rbVerifySet() {
    std::vector<Region> v;
    v.push_back({ M.blk, M.blk_size, "blk" });
    if (g_rbVerify >= 1) {
        v.push_back({ M.blk2, M.blk2_size, "blk2" });
        v.push_back({ GS_ADDR, 0x1000, "gs_page" });
        v.push_back({ EXE_PAGE_ADDR, EXE_PAGE_LEN, "exe_page" });
    }
    if (g_rbVerify >= 2) {
        v.push_back({ M.ctx, M.ctx_size, "ctx" });
        v.push_back({ M.dcram, M.dcram_size, "dcram" });
    }
    return v;
}
static uint64_t rbBlobSize(const std::vector<Region>& v) { uint64_t n = 0; for (auto& r : v) n += r.size; return n; }
static void rbSaveTo(uint8_t* dst, const std::vector<Region>& v) {
    for (auto& r : v) { memcpy(dst, (const void*)(uintptr_t)r.addr, (size_t)r.size); dst += r.size; }
}
static void rbRestoreFrom(const uint8_t* src, const std::vector<Region>& v) {
    for (auto& r : v) { memcpy((void*)(uintptr_t)r.addr, src, (size_t)r.size); src += r.size; }
}
// first differing offset + byte count + run count for one region
struct Diff { uint64_t bytes = 0, runs = 0, first = ~0ull; std::map<std::string, uint64_t> buckets; };
static Diff rbDiff(const uint8_t* ref, uint64_t addr, uint64_t size, bool ctxClassify) {
    Diff d; const uint8_t* live = (const uint8_t*)(uintptr_t)addr;
    for (uint64_t i = 0; i < size; ) {
        if (live[i] == ref[i]) { ++i; continue; }
        uint64_t j = i; while (j < size && live[j] != ref[j]) ++j;
        d.bytes += j - i; ++d.runs; if (d.first == ~0ull) d.first = i;
        if (ctxClassify) d.buckets[ctxBucket(i)] += j - i;
        i = j;
    }
    return d;
}

// ---- PLAY MODE: put a human at one end ---------------------------------------------------------------------------
// Pad word layout, CONFIRMED and verified in docs/CONFIRMED-TAPE-AND-FLYR-REPLAY.md s5 ("Rosetta, solved + verified"):
//   0x10 UP  0x20 RIGHT  0x40 DOWN  0x80 LEFT | 0x200 A1  0x800 A2  0x1000 HP  0x2000 HK  0x4000 LK  0x8000 LP
// Cross-checked against real recorded tapes: 0x000080 = walk left, 0x000020 = walk right, 0x0020C0 = down-left + HK.
// The wrapper FUN_140118950 takes these two seat words as its whole input (DETERMINISM-CONTRACT s1), so a human
// pressing a button IS the same object the receipt replays -- there is no second input path to get wrong.
static const uint32_t PAD_UP = 0x10, PAD_RIGHT = 0x20, PAD_DOWN = 0x40, PAD_LEFT = 0x80,
                      PAD_A1 = 0x200, PAD_A2 = 0x800, PAD_HP = 0x1000, PAD_HK = 0x2000,
                      PAD_LK = 0x4000, PAD_LP = 0x8000;
typedef DWORD (WINAPI *XInputGetState_t)(DWORD, void*);
static XInputGetState_t g_xiGet = nullptr;
static bool g_padIsXInput = false;

static const uint32_t PAD_DIRS = PAD_UP | PAD_DOWN | PAD_LEFT | PAD_RIGHT;   // 0xF0
static const char* padName(uint32_t w);

// Raw sources, kept so a session can be audited instead of guessed at. Tris 600-frame session had a low byte of
// 00 on EVERY frame, i.e. no direction ever reached the sim, and the log could not say whether he never pressed
// one or whether we dropped it -- because nothing raw was recorded. That is the defect this struct closes.
struct PadRaw {
    uint32_t xiMask = 0;        // which XInput user indices are connected
    uint16_t xiButtons = 0;
    int16_t  xiLX = 0, xiLY = 0;
    uint16_t kbBits = 0;        // bit k = keys[k] down
    uint32_t word = 0;          // the synthesised seat word
};
static PadRaw g_padRaw;

struct PadKey { int vk; uint32_t bit; const char* name; };
static const PadKey PAD_KEYS[] = {
    {VK_UP,PAD_UP,"Up"},{VK_DOWN,PAD_DOWN,"Down"},{VK_LEFT,PAD_LEFT,"Left"},{VK_RIGHT,PAD_RIGHT,"Right"},
    {'Z',PAD_LP,"Z=LP"},{'X',PAD_HP,"X=HP"},{'C',PAD_A1,"C=A1"},
    {'A',PAD_LK,"A=LK"},{'S',PAD_HK,"S=HK"},{'D',PAD_A2,"D=A2"} };

static void padInit() {
    const char* dlls[] = { "xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll" };
    for (const char* d : dlls) {
        HMODULE h = LoadLibraryA(d);
        if (!h) continue;
        g_xiGet = (XInputGetState_t)GetProcAddress(h, "XInputGetState");
        if (g_xiGet) { g_padIsXInput = true; logf_("  pad: loaded %s XInputGetState", d); break; }
    }
    if (!g_padIsXInput) logf_("  pad: no XInput DLL available");
    uint32_t mask = 0;
    if (g_xiGet) {
        uint8_t st[16];
        for (DWORD i = 0; i < 4; ++i) { memset(st, 0, sizeof(st)); if (g_xiGet(i, st) == 0) mask |= (1u << i); }
    }
    logf_("  pad: XInput controllers connected on user index mask 0x%X ; the KEYBOARD is ALWAYS polled too", mask);
    logf_("  pad: directions = d-pad / left stick / arrow keys ; buttons = X,Y,A,B,LB,RB or Z,X,C,A,S,D");
    if (mask == 0) logf_("  pad: NO CONTROLLER DETECTED -- keyboard only. Directions are the ARROW KEYS.");
}

// XINPUT_STATE: dwPacketNumber@0, wButtons@4, LT@6, RT@7, sThumbLX@8, sThumbLY@10 (16 B total).
// THREE FIXES over the first version, all of which could silently drop direction input:
//   1. it returned early from the XInput branch, so with any controller connected the KEYBOARD WAS NEVER READ;
//   2. it polled user index 0 only, so a pad enumerated on 1..3 contributed nothing;
//   3. the stick deadzone was 12000 (37% of full scale) versus XInput's own 7849.
// Both sources are now OR-ed, every index is polled, and the raw values are recorded in g_padRaw.
static uint32_t padRead() {
    uint32_t w = 0;
    PadRaw r;
    if (g_xiGet) {
        uint8_t st[16];
        for (DWORD i = 0; i < 4; ++i) {
            memset(st, 0, sizeof(st));
            if (g_xiGet(i, st) != 0) continue;
            r.xiMask |= (1u << i);
            uint16_t b = *(uint16_t*)(st + 4);
            int16_t lx = *(int16_t*)(st + 8), ly = *(int16_t*)(st + 10);
            r.xiButtons |= b; if (lx) r.xiLX = lx; if (ly) r.xiLY = ly;
            const int DZ = 7849;                      // XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE
            if ((b & 0x0001) || ly > DZ)  w |= PAD_UP;
            if ((b & 0x0002) || ly < -DZ) w |= PAD_DOWN;
            if ((b & 0x0004) || lx < -DZ) w |= PAD_LEFT;
            if ((b & 0x0008) || lx > DZ)  w |= PAD_RIGHT;
            if (b & 0x4000) w |= PAD_LP;    // X
            if (b & 0x8000) w |= PAD_HP;    // Y
            if (b & 0x1000) w |= PAD_LK;    // A
            if (b & 0x2000) w |= PAD_HK;    // B
            if (b & 0x0100) w |= PAD_A1;    // LB
            if (b & 0x0200) w |= PAD_A2;    // RB
        }
    }
    for (int k = 0; k < (int)(sizeof(PAD_KEYS) / sizeof(PAD_KEYS[0])); ++k)
        if (GetAsyncKeyState(PAD_KEYS[k].vk) & 0x8000) { w |= PAD_KEYS[k].bit; r.kbBits |= (uint16_t)(1u << k); }
    r.word = w;
    g_padRaw = r;
    return w;
}

// A 5-second check of the INPUT PATH ALONE: no image, no anchor, no tick. If a direction never shows up here,
// the fault is ours; if it does, the sim is the next place to look. This exists because the first play session
// could not distinguish "he pressed no direction" from "we dropped it".
static int padProbe(int seconds) {
    padInit();
    printf("\nPAD PROBE -- press things. Directions are the ARROW KEYS or a d-pad/left stick.\n");
    printf("Watching for %d s. A direction sets a LOW-BYTE bit: UP 10 RIGHT 20 DOWN 40 LEFT 80.\n\n", seconds);
    LARGE_INTEGER f, t0, now; QueryPerformanceFrequency(&f); QueryPerformanceCounter(&t0);
    uint32_t last = 0xFFFFFFFF, dirsSeen = 0, btnsSeen = 0;
    int samples = 0;
    for (;;) {
        QueryPerformanceCounter(&now);
        double el = (double)(now.QuadPart - t0.QuadPart) / (double)f.QuadPart;
        if (el > seconds) break;
        uint32_t w = padRead(); ++samples;
        dirsSeen |= (w & PAD_DIRS); btnsSeen |= (w & ~PAD_DIRS);
        if (w != last) {
            printf("  t=%5.1fs  pad %06x [%-14s]   xi mask %x buttons %04x LX %6d LY %6d   kb %03x\n",
                   el, w, padName(w), g_padRaw.xiMask, g_padRaw.xiButtons, g_padRaw.xiLX, g_padRaw.xiLY, g_padRaw.kbBits);
            last = w;
        }
        Sleep(8);
    }
    printf("\nPAD PROBE RESULT after %d samples:\n", samples);
    printf("  directions seen : %s  (mask %02x)\n", dirsSeen ? padName(dirsSeen) : "NONE", dirsSeen);
    printf("  buttons seen    : %s\n", btnsSeen ? padName(btnsSeen) : "NONE");
    if (!dirsSeen) {
        printf("\n  >> NO DIRECTION REGISTERED. If you pressed one, the input path is at fault -- send this output.\n");
        return 2;
    }
    printf("\n  >> Directions reach the pad word. The input path is good.\n");
    return 0;
}

static const char* padName(uint32_t w) {
    static char b[96]; b[0] = 0;
    if (w & PAD_UP) strcat_s(b, "U"); if (w & PAD_DOWN) strcat_s(b, "D");
    if (w & PAD_LEFT) strcat_s(b, "L"); if (w & PAD_RIGHT) strcat_s(b, "R");
    if (w & PAD_LP) strcat_s(b, " LP"); if (w & PAD_HP) strcat_s(b, " HP");
    if (w & PAD_LK) strcat_s(b, " LK"); if (w & PAD_HK) strcat_s(b, " HK");
    if (w & PAD_A1) strcat_s(b, " A1"); if (w & PAD_A2) strcat_s(b, " A2");
    return b[0] ? b : "-";
}

typedef void (*TickFn)(void*, uint32_t*, uint32_t);

// ---- GATE N1 state: the ring, the reference snapshot, and one rollback event ------------------------------------------
static std::vector<std::vector<uint8_t>> g_ring;          // g_rbN+1 slots of the SAVE set
static std::vector<uint8_t> g_ref;                        // reference copy of the VERIFY set (untimed)
static std::map<uint64_t, std::vector<uint8_t>> g_refLazy;// reference copy of every committed lazy host page
static double qms(LARGE_INTEGER a, LARGE_INTEGER b, LARGE_INTEGER f) { return 1000.0 * (double)(b.QuadPart - a.QuadPart) / (double)f.QuadPart; }

// After straight-line tick `kk` (1-based) has run, resimulate the last g_rbN frames from the ring and compare.
static void rollbackEvent(int kk, TickFn tick, LARGE_INTEGER f) {
    std::vector<Region> sv = rbSaveSet(), vf = rbVerifySet();
    LARGE_INTEGER t0, t1;
    // (0) reference = the straight-line state at clock(kk). UNTIMED: it exists only to prove sufficiency.
    rbSaveTo(g_ref.data(), vf);
    g_refLazy.clear();
    if (g_rbVerify >= 2) for (auto& L : g_lazy) {
        std::vector<uint8_t>& b = g_refLazy[L.page]; b.resize(0x10000);
        memcpy(b.data(), (const void*)(uintptr_t)L.page, 0x10000);
    }
    uint32_t refClock = RD32(M.blk + CLOCK_OFF);
    size_t lazyBefore = g_lazy.size();
    // (1) restore the slot saved after tick kk-N  (TIMED)
    QueryPerformanceCounter(&t0);
    rbRestoreFrom(g_ring[(size_t)((kk - g_rbN) % (g_rbN + 1))].data(), sv);
    QueryPerformanceCounter(&t1);
    g_rbRestoreMs.push_back(qms(t0, t1, f));
    // (2) re-tick the same N inputs  (TIMED)
    alignas(16) uint32_t in[4];
    QueryPerformanceCounter(&t0);
    for (int j = kk - g_rbN; j < kk; ++j) {                 // straight-line tick index j+1 consumed J.w0[j]
        in[0] = J.w0[j] & 0xFFFFFF; in[1] = J.w1[j] & 0xFFFFFF; in[2] = 0; in[3] = 0;
        tick((void*)(uintptr_t)GGPO_STATE, in, 0);
    }
    QueryPerformanceCounter(&t1);
    g_rbResimMs.push_back(qms(t0, t1, f));
    double saveMs = g_rbSaveMs.empty() ? 0.0 : g_rbSaveMs.back();
    double ev = saveMs + g_rbRestoreMs.back() + g_rbResimMs.back();
    g_rbEventMs.push_back(ev);
    g_rbFrameMs.push_back(ev + (J.ms.empty() ? 0.0 : J.ms.back()));
    ++g_rbEvents;
    // (3) compare every candidate region against the reference
    uint32_t clk = RD32(M.blk + CLOCK_OFF);
    bool fail = (clk != refClock);
    std::string detail;
    if (clk != refClock) detail += " clock " + std::to_string(clk) + " != " + std::to_string(refClock);
    const uint8_t* rp = g_ref.data();
    for (auto& r : vf) {
        Diff d = rbDiff(rp, r.addr, r.size, strcmp(r.name, "ctx") == 0);
        if (d.bytes) {
            bool isCtx = strcmp(r.name, "ctx") == 0;
            uint64_t fatalB = 0, nondetB = 0;
            for (auto& b : d.buckets) {
                g_rbCtxBuckets[b.first] += b.second;
                (ctxBucketNondet(b.first.c_str()) ? nondetB : fatalB) += b.second;
            }
            if (!isCtx) fatalB = d.bytes;
            if (fatalB) {
                fail = true;
                detail += std::string(" ") + r.name + "=" + std::to_string(fatalB) + "B/" + std::to_string(d.runs) +
                          "runs@+0x" + hx(d.first);
                for (auto& b : d.buckets) if (!ctxBucketNondet(b.first.c_str())) detail += " {" + b.first + ":" + std::to_string(b.second) + "B}";
            }
            if (nondetB) { g_rbNondetEvents += (fatalB ? 0 : 1); g_rbNondetBytes += nondetB; }
        }
        rp += r.size;
    }
    for (auto& kv : g_refLazy) {
        const uint8_t* live = (const uint8_t*)(uintptr_t)kv.first;
        if (memcmp(live, kv.second.data(), 0x10000) != 0) {
            uint64_t nb = 0, fo = ~0ull;
            for (uint64_t i = 0; i < 0x10000; ++i) if (live[i] != kv.second[i]) { ++nb; if (fo == ~0ull) fo = i; }
            fail = true;
            detail += " lazypage0x" + hx(kv.first) + "=" + std::to_string(nb) + "B@+0x" + hx(fo);
        }
    }
    if (g_lazy.size() != lazyBefore) detail += " [" + std::to_string(g_lazy.size() - lazyBefore) + " NEW lazy page(s) committed during the resim]";
    if (fail) {
        ++g_rbFailEvents;
        if (g_rbFirstFail.empty()) g_rbFirstFail = "tick " + std::to_string(kk) + ":" + detail;
        logf_("  ROLLBACK tick %3d depth %d set %s: MISMATCH%s", kk, g_rbN, g_rbSet.c_str(), detail.c_str());
        if (g_rbReset) { rbRestoreFrom(g_ref.data(), vf); for (auto& kv : g_refLazy) memcpy((void*)(uintptr_t)kv.first, kv.second.data(), 0x10000); }
    } else if (g_rbEvents <= 2 || (g_rbEvents % 100) == 0) {
        logf_("  ROLLBACK tick %3d depth %d set %s: EXACT (restore %.4f ms, resim %d ticks %.4f ms)%s",
              kk, g_rbN, g_rbSet.c_str(), g_rbRestoreMs.back(), g_rbN, g_rbResimMs.back(), detail.c_str());
    }
}
// The interactive loop. No netcode, no rollback, no opponent: one human, seat 0, paced at 60 Hz.
// Everything it touches is already gated -- the tick (GATE 1), the DC-RAM image built from the arc (GATE 3/4),
// and the per-tick harvest dump (GATE 2). The only new thing is the person.
static void playLoop(TickFn tick, LARGE_INTEGER f) {
    padInit();
    uint32_t clock0 = RD32(M.blk + CLOCK_OFF);
    FILE* fi = nullptr; fopen_s(&fi, (J.out + "/inputs_play.txt").c_str(), "wb");
    float px0 = *(float*)(uintptr_t)(M.blk + FIGHTER0 + 0x50);
    float py0 = *(float*)(uintptr_t)(M.blk + FIGHTER0 + 0x54);
    logf_("PLAY: seat 0 is yours. %d frames at 60 Hz. start px %.3f py %.3f (clock %u)", J.playFrames, px0, py0, clock0);
    // py oscillates on its own (the idle animation bobs), so py is NOT evidence of a human. px is stable at rest,
    // so the honest claim is: the first frame with a non-zero pad, and the first px change AFTER one.
    int firstInput = -1, firstMove = -1; uint32_t firstMovePad = 0; float pxAtInput = px0;
    // STEERING is the claim that matters, and it needs a DIRECTION bit, not just any input. The first session
    // reported a "human-caused move" on pad 000800 = A2 alone: an assist call, whose subsequent px slide is
    // animation displacement, not locomotion. These two track the honest claim.
    int firstDir = -1, firstDirMove = -1; float pxAtDir = px0; uint32_t dirsEverSeen = 0;
    LARGE_INTEGER t0, t1, w0q, w1q; double budget = 1000.0 / 60.0;
    std::vector<double> loopMs;
    QueryPerformanceCounter(&w0q);
    char pth[MAX_PATH];
    if (J.harvest && J.playHarvest) {
        sprintf_s(pth, "%s/blk_t000.bin", J.out.c_str()); dumpRange(pth, M.blk, M.blk_size);
        harvestDump(0);
    }
    logf_("PLAY: per-tick harvest is %s (it is a RECORDING concern; with it inline the frame tail blew out to 97 ms"
          " on a real session while the tick stayed under 0.75 ms)", (J.harvest && J.playHarvest) ? "ON" : "OFF");
    for (int k = 0; k < J.playFrames; ++k) {
        g_tick = k + 1;
        LARGE_INTEGER fs; QueryPerformanceCounter(&fs);
        uint32_t pad = padRead();
        alignas(16) uint32_t in[4]; in[0] = pad & 0xFFFFFF; in[1] = 0; in[2] = 0; in[3] = 0;
        QueryPerformanceCounter(&t0);
        tick((void*)(uintptr_t)GGPO_STATE, in, 0);
        QueryPerformanceCounter(&t1);
        double tickMs = 1000.0 * (double)(t1.QuadPart - t0.QuadPart) / (double)f.QuadPart;
        J.ms.push_back(tickMs);
        if (J.harvest && J.playHarvest) {
            sprintf_s(pth, "%s/blk_t%03d.bin", J.out.c_str(), k + 1); dumpRange(pth, M.blk, M.blk_size);
            harvestDump(k + 1);
        }
        if (fi) fprintf(fi, "%06x %06x", in[0], in[1]), fputc(10, fi);
        float px = *(float*)(uintptr_t)(M.blk + FIGHTER0 + 0x50);
        float py = *(float*)(uintptr_t)(M.blk + FIGHTER0 + 0x54);
        if (firstInput < 0 && pad) {
            firstInput = k + 1; pxAtInput = px;
            logf_("PLAY: *** FIRST INPUT *** frame %d (clock %u): pad %06x [%s], px %.3f",
                  k + 1, RD32(M.blk + CLOCK_OFF), pad, padName(pad), px);
        }
        dirsEverSeen |= (pad & PAD_DIRS);
        if (firstDir < 0 && (pad & PAD_DIRS)) {
            firstDir = k + 1; pxAtDir = px;
            logf_("PLAY: *** FIRST DIRECTION *** frame %d (clock %u): pad %06x [%s], px %.3f",
                  k + 1, RD32(M.blk + CLOCK_OFF), pad, padName(pad), px);
        }
        if (firstDir > 0 && firstDirMove < 0 && px != pxAtDir) {
            firstDirMove = k + 1;
            logf_("PLAY: *** STEERING PROVEN *** frame %d, %d frames after the first direction: px %.3f -> %.3f",
                  k + 1, k + 1 - firstDir, pxAtDir, px);
        }
        if (firstInput > 0 && firstMove < 0 && px != pxAtInput) {
            firstMove = k + 1; firstMovePad = pad;
            logf_("PLAY: *** FIRST HUMAN-CAUSED MOVE *** frame %d (clock %u), %d frames after the first input:"
                  " pad %06x [%s] moved px %.3f -> %.3f", k + 1, RD32(M.blk + CLOCK_OFF), k + 1 - firstInput,
                  pad, padName(pad), pxAtInput, px);
        }
        if ((k % 15) == 0 || pad)
            logf_("  f%-5d clock %-6u pad %06x [%-12s] px %8.2f py %8.2f  tick %.3f ms", k + 1,
                  RD32(M.blk + CLOCK_OFF), pad, padName(pad), px, py, tickMs);
        LARGE_INTEGER fe; QueryPerformanceCounter(&fe);
        double usedMs = 1000.0 * (double)(fe.QuadPart - fs.QuadPart) / (double)f.QuadPart;
        loopMs.push_back(usedMs);
        int sleepMs = (int)(budget - usedMs);
        if (sleepMs > 0) Sleep(sleepMs);
    }
    QueryPerformanceCounter(&w1q);
    if (fi) fclose(fi);
    double wall = 1000.0 * (double)(w1q.QuadPart - w0q.QuadPart) / (double)f.QuadPart;
    std::vector<double> q = loopMs; std::sort(q.begin(), q.end());
    double sum = 0; for (double x : loopMs) sum += x;
    auto pc = [&](double t) { return q.empty() ? 0.0 : q[std::min(q.size() - 1, (size_t)(t * q.size()))]; };
    logf_("PLAY DONE: %d frames in %.0f ms wall (%.1f fps). per-frame WORK (pad+tick+harvest, excl. the 60 Hz sleep):"
          " p50 %.3f p99 %.3f max %.3f ms", J.playFrames, wall, 1000.0 * J.playFrames / wall, pc(0.5), pc(0.99), q.empty() ? 0 : q.back());
    logf_("PLAY: first input frame %d ; first human-caused px change frame %d (pad %06x) ; inputs -> %s/inputs_play.txt",
          firstInput, firstMove, firstMovePad, J.out.c_str());
    if (firstInput < 0) logf_("PLAY: NO INPUT WAS EVER PRESSED -- nothing was proven about a human in the loop.");
    else if (!dirsEverSeen)
        logf_("PLAY: *** NO DIRECTION WAS EVER PRESSED *** (every pad word had a low byte of 00). Inputs reached the"
              " sim, but STEERING IS UNPROVEN -- a px slide under an attack/assist pad is animation displacement,"
              " not locomotion. Run --pad-probe 5 and hold LEFT to check the input path.");
    else
        logf_("PLAY: STEERING -- first direction frame %d, first px change after it frame %d (directions seen: %s)",
              firstDir, firstDirMove, padName(dirsEverSeen));
}

static DWORD WINAPI tickThread(LPVOID) {
    unsigned csr = _mm_getcsr();
    logf_("MXCSR at entry = 0x%x (%s; contract C3 wants 0x1f80)", csr, csr == 0x1f80 ? "OK" : "DIFFERS");
    LARGE_INTEGER f, t0, t1; QueryPerformanceFrequency(&f);
    TickFn tick = (TickFn)(uintptr_t)FRAME_TICK;
    if (J.play) { playLoop(tick, f); return 0; }
    alignas(16) uint32_t inputs[4];
    uint32_t clock0 = RD32(M.blk + CLOCK_OFF);
    if (J.harvest) { char p[MAX_PATH]; sprintf_s(p, "%s\\blk_t000.bin", J.out.c_str()); dumpRange(p, M.blk, M.blk_size); harvestDump(0); }
    // GATE N1: allocate the ring + the reference buffer, and seed slot 0 with the pre-first-tick state
    if (g_rbN >= 0) {
        std::vector<Region> sv = rbSaveSet(), vf = rbVerifySet();
        uint64_t sb = rbBlobSize(sv), vb = rbBlobSize(vf);
        g_ring.assign((size_t)g_rbN + 1, std::vector<uint8_t>((size_t)sb));
        g_ref.assign((size_t)vb, 0);
        std::string names; for (auto& r : sv) names += std::string(names.empty() ? "" : "+") + r.name;
        std::string vnames; for (auto& r : vf) vnames += std::string(vnames.empty() ? "" : "+") + r.name;
        logf_("ROLLBACK MODE: depth %d, save set '%s' = %s (%llu B x %d slots = %llu B ring), verify = %s%s, on-mismatch %s",
              g_rbN, g_rbSet.c_str(), names.c_str(), sb, g_rbN + 1, sb * (uint64_t)(g_rbN + 1), vnames.c_str(),
              g_rbVerify >= 2 ? "+lazy host pages" : "", g_rbReset ? "reset-to-reference" : "continue");
        logf_("  NOTE: the GGPO counter at 0x%llx (0x10 B) is restored in EVERY tier -- it is wrapper bookkeeping that", GGPO_STATE);
        logf_("        FUN_140118950 increments once per call (contract C2, GATE1 s3.6), not game state; without it every resim differs by N.");
        rbSaveTo(g_ring[0].data(), sv);
    }
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
        if (J.harvest) harvestDump(k + 1);
        if (g_rbN >= 0) {
            LARGE_INTEGER s0, s1; QueryPerformanceCounter(&s0);
            rbSaveTo(g_ring[(size_t)((k + 1) % (g_rbN + 1))].data(), rbSaveSet());
            QueryPerformanceCounter(&s1); g_rbSaveMs.push_back(qms(s0, s1, f));
            if (k + 1 >= g_rbN && (g_rbMaxEvents == 0 || g_rbEvents < g_rbMaxEvents)) rollbackEvent(k + 1, tick, f);
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
         "  --lazy off : any such touch is fatal and reported (RIP, address, region)\n"
         "  --rollback N        GATE N1: ring depth N; after every tick k >= N, restore the slot saved at k-N, re-tick\n"
         "                      the same N inputs, and compare EVERY region against the straight-line state at that clock\n"
         "                      (N = 0 = save + restore with no resim: the floor measurement)\n"
         "  --rb-set S          what the ring saves/restores: blk (the shipped GGPO set) | rr (blk + the 8 bytes at\n"
         "                      ctx+0x1F8230 that GATE N1 proved are also required -- the RECOMMENDED set)\n"
         "                      | blkctx (+ the ctx READ set:\n"
         "                      slot table + matrix state, 12,956 B) | blk2 | sim (+gs+exe page)\n"
         "                      | full (+ctx+dcram). The GGPO counter is restored in every tier (wrapper-only, C2)  [blk]\n"
         "  --rb-verify V       off = blk only | small = +blk2/gs/exe | all = +ctx/dcram/lazy host pages            [all]\n"
         "  --rb-events M       stop firing events after M of them (0 = every eligible tick)                          [0]\n"
         "  --rb-ctx-extra R    extra ctx ranges to save/restore, hex offsets 'LO-HI[,LO-HI...]' (bisecting the ctx set)\n"
         "  --heap-mb N         runner bump-heap size. A resim consumes it depth+1 times faster; a WRAP re-zeroes\n"
         "                      it inside one tick and becomes a huge outlier in the max column, so deep-ring\n"
         "                      TIMING runs must size this so heap_wraps stays 0                            [64]\n"
         "  --rb-on-mismatch X  reset (restore the reference so later events stay independent) | continue          [reset]\n");
    exit(1);
}

int main(int argc, char** argv) {
    std::string pre, out, inputs; int ticks = 20, dumpEvery = 1, padProbeSecs = 0; bool gsFile = false, rwx = false, force = false, dumpEnd = true; int fma = 0;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i]; auto next = [&]() -> std::string { if (i + 1 >= argc) usage(); return argv[++i]; };
        if (a == "--pre") pre = next(); else if (a == "--out") out = next(); else if (a == "--ticks") ticks = atoi(next().c_str());
        else if (a == "--inputs") inputs = next(); else if (a == "--gs") gsFile = next() == "file"; else if (a == "--crt") g_crtReal = next() == "real";
        else if (a == "--fma") fma = atoi(next().c_str()); else if (a == "--prot") rwx = next() == "rwx"; else if (a == "--dump-every") dumpEvery = atoi(next().c_str());
        else if (a == "--rollback") g_rbN = atoi(next().c_str());
        else if (a == "--rb-set") g_rbSet = next();
        else if (a == "--rb-verify") { std::string v = next(); g_rbVerify = (v == "off") ? 0 : (v == "small") ? 1 : 2; }
        else if (a == "--rb-events") g_rbMaxEvents = atoi(next().c_str());
        else if (a == "--heap-mb") HEAP_BYTES = (uint64_t)atoi(next().c_str()) << 20;
        else if (a == "--play") J.play = true;
        else if (a == "--play-frames") J.playFrames = atoi(next().c_str());
        else if (a == "--pad-probe") padProbeSecs = atoi(next().c_str());
        else if (a == "--play-harvest") J.playHarvest = next() != "off";
        else if (a == "--rb-ctx-extra") {
            std::string t = next(), cur;
            t += ',';
            for (char c : t) {
                if (c == ',') {
                    size_t d = cur.find('-');
                    if (d != std::string::npos) g_rbCtxExtra.push_back({ strtoull(cur.substr(0, d).c_str(), nullptr, 16), strtoull(cur.substr(d + 1).c_str(), nullptr, 16) });
                    cur.clear();
                } else cur += c;
            }
        }
        else if (a == "--rb-on-mismatch") g_rbReset = next() != "continue";
        else if (a == "--no-dump-end") dumpEnd = false; else if (a == "--force") force = true; else if (a == "--lazy") g_lazyOn = next() != "off"; else if (a == "--harvest-dump") J.harvest = true; else usage();
    }
    if (padProbeSecs > 0) return padProbe(padProbeSecs);   // input path only: no image, no anchor, no tick
    if (pre.empty() || out.empty()) usage();
    if (g_rbN >= 0 && g_rbSet != "blk" && g_rbSet != "rr" && g_rbSet != "blkctx" && g_rbSet != "blk2" && g_rbSet != "sim" && g_rbSet != "simctx" && g_rbSet != "simdc" && g_rbSet != "simtile" && g_rbSet != "full") {
        fprintf(stderr, "--rb-set must be blk|rr|blkctx|blk2|sim|simctx|simdc|simtile|full\n"); usage();
    }
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
    if (g_rbN >= 0) {
        auto stat = [&](std::vector<double> v, const char* nm) {
            if (v.empty()) { logf_("  %-8s n=0", nm); return std::string("null"); }
            std::vector<double> q = v; std::sort(q.begin(), q.end());
            double sm = 0; for (double x : q) sm += x;
            auto pc = [&](double t) { return q[std::min(q.size() - 1, (size_t)(t * q.size()))]; };
            logf_("  %-8s n=%zu  min %.4f  p50 %.4f  mean %.4f  p90 %.4f  p99 %.4f  max %.4f ms",
                  nm, q.size(), q[0], pc(0.5), sm / q.size(), pc(0.9), pc(0.99), q.back());
            char b[320]; sprintf_s(b, "{\"n\":%zu,\"min\":%.5f,\"p50\":%.5f,\"mean\":%.5f,\"p90\":%.5f,\"p99\":%.5f,\"max\":%.5f}",
                                   q.size(), q[0], pc(0.5), sm / q.size(), pc(0.9), pc(0.99), q.back());
            return std::string(b);
        };
        logf_("ROLLBACK (GATE N1) depth %d set %s verify %d: %d events, %d mismatch -> %s",
              g_rbN, g_rbSet.c_str(), g_rbVerify, g_rbEvents, g_rbFailEvents,
              g_rbFailEvents == 0 ? "PASS (every resim byte-identical to the straight-line run on every verified region)" : "FAIL");
        if (!g_rbFirstFail.empty()) logf_("  first mismatch: %s", g_rbFirstFail.c_str());
        logf_("  ctx render-scratch nondeterminism (NOT a failure, see ctxBucketNondet): %llu events, %llu B total",
              g_rbNondetEvents, g_rbNondetBytes);
        std::string bj;
        for (auto& b : g_rbCtxBuckets) {
            logf_("  ctx differing bytes by region: %-45s %llu B (summed over all mismatching events)", b.first.c_str(), b.second);
            bj += (bj.empty() ? "" : ",") + std::string("\"") + b.first + "\":" + std::to_string(b.second);
        }
        g_rbCtxJson = "{" + bj + "}";
        std::string js = stat(g_rbSaveMs, "save"), jr = stat(g_rbRestoreMs, "restore"), jx = stat(g_rbResimMs, "resim");
        std::string je = stat(g_rbEventMs, "event"), jf = stat(g_rbFrameMs, "frame");
        size_t over = 0;
        for (double x : g_rbFrameMs) if (x > FRAME_BUDGET_MS) ++over;
        double worst = 0.0;
        for (double x : g_rbFrameMs) if (x > worst) worst = x;
        logf_("  N1b: ticks=%d events=%d  per-EVENT frame cost (save+restore+resim+tick) max %.4f ms;"
              " events over the %.3f ms budget: %zu of %zu",
              J.ticks, g_rbEvents, worst, FRAME_BUDGET_MS, over, g_rbFrameMs.size());
        double sS = 0, sR = 0, sX = 0;
        for (double x : g_rbSaveMs) sS += x;
        for (double x : g_rbRestoreMs) sR += x;
        for (double x : g_rbResimMs) sX += x;
        double perFrame = J.ms.empty() ? 0.0 : (sS + sR + sX) / (double)J.ms.size();
        logf_("  interleaved worst case (a rollback EVERY frame): save+restore+resim = %.4f ms per straight-line frame;"
              " straight-line tick p50 %.4f ms; ring %llu B; heap wraps %llu",
              perFrame, pct(0.5), (uint64_t)(g_ring.empty() ? 0 : g_ring.size() * g_ring[0].size()), g_heapWraps);
        char pf[64]; sprintf_s(pf, "%.5f", perFrame);
        g_rbJson = "{\"depth\":" + std::to_string(g_rbN) + ",\"set\":\"" + g_rbSet + "\",\"verify\":" + std::to_string(g_rbVerify)
                 + ",\"events\":" + std::to_string(g_rbEvents) + ",\"mismatch_events\":" + std::to_string(g_rbFailEvents)
                 + ",\"pass\":" + (g_rbFailEvents == 0 ? "true" : "false")
                 + ",\"ring_bytes\":" + std::to_string((uint64_t)(g_ring.empty() ? 0 : g_ring.size() * g_ring[0].size()))
                 + ",\"heap_wraps\":" + std::to_string(g_heapWraps)
                 + ",\"ticks\":" + std::to_string(J.ticks)
                 + ",\"save_ms\":" + js + ",\"restore_ms\":" + jr + ",\"resim_ms\":" + jx
                 + ",\"event_ms\":" + je + ",\"frame_ms\":" + jf
                 + ",\"frame_budget_ms\":16.667,\"events_over_budget\":" + std::to_string(over)
                 + ",\"ctx_nondet_events\":" + std::to_string(g_rbNondetEvents)
                 + ",\"ctx_nondet_bytes\":" + std::to_string(g_rbNondetBytes)
                 + ",\"amortised_ms_per_frame\":" + pf + ",\"ctx_buckets\":" + (g_rbCtxJson.empty() ? "{}" : g_rbCtxJson)
                 + ",\"first_mismatch\":\"" + g_rbFirstFail + "\"}";
    }
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
        fprintf(fs, "{\"harvest_dump\":%s,\"dcram_delta_pages\":%llu,\"dcram_delta_bytes\":%llu,\"dcram_delta_per_tick\":\"%s\",\"dc_base\":\"0x%llx\",\"gs_addr\":\"0x%llx\",\"exe_page_addr\":\"0x%llx\",",
                J.harvest ? "true" : "false", J.dcDeltaPages, J.dcDeltaBytes, J.dcDeltaSummary.c_str(), M.dc_base, GS_ADDR, EXE_PAGE_ADDR);
        fprintf(fs, "\"ticks\":%d,\"clock_start\":%llu,\"clock_end\":%u,\"gs\":\"%s\",\"crt\":\"%s\",\"fma\":%d,\"prot\":\"%s\",\"ext\":{\"RtlAllocateHeap\":%llu,\"alloc_bytes\":%llu,\"RtlReAllocateHeap\":%llu,\"HeapFree\":%llu,\"GetLastError\":%llu,\"SetLastError\":%llu,\"FlsGetValue\":%llu,\"FlsSetValue\":%llu},\"lazy_pages\":[%s],\"rollback\":%s,\"ms\":[",
                ticks, M.clock_value, RD32(M.blk + CLOCK_OFF), gsFile ? "file" : "exe", g_crtReal ? "real" : "stub", fma, rwx ? "rwx" : "sections", g_cnt[0], g_allocBytes, g_cnt[1], g_cnt[2], g_cnt[3], g_cnt[4], g_cnt[5], g_cnt[6], lazyJson.c_str(), g_rbJson.empty() ? "null" : g_rbJson.c_str());
        for (size_t i = 0; i < J.ms.size(); ++i) fprintf(fs, "%s%.4f", i ? "," : "", J.ms[i]);
        fprintf(fs, "]}\n"); fclose(fs);
    }
    if (J.harvest) logf_("HARVEST DUMP: %llu DC-RAM pages (%llu B) changed over %d ticks (per-tick in summary.json)", J.dcDeltaPages, J.dcDeltaBytes, ticks);
    logf_("DONE: %d ticks, clock %llu -> %u, dumps in %s", J.play ? J.playFrames : ticks, M.clock_value, RD32(M.blk + CLOCK_OFF), out.c_str());
    return 0;
}
