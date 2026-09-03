// ── RECEIPT PLAYER (Workstream G: game-in-the-loop replay of a receipt) ───────────────────────────
// Included from dllmain.cpp right after the sprite-walker hook; shares logf/safeRead/RR_RVA/RR_BLK_PTR.
//
// WHAT IT DOES. A receipt is one character-select snapshot of the GGPO region blk[0..0x33B18) plus the
// two seat words per frame (docs/FRAME-READSET.md s5, STEAM-GGPO-DETERMINISM.md s4). The driver
// (receipt/replay_receipt.py) relocates the snapshot to THIS process's blk and hands it over through a
// command file; this code writes it into the live block and, on EVERY frame tick, overwrites the two
// seat words with the receipt's inputs for that sim frame, so the game itself walks from character
// select into the fight and plays the recorded match. Each tick also appends one 128-byte state record
// (clock, inputs, mode bytes, six fighters' hp/x/y/sid) to a log the driver gates against the tape.
//
// THE HOOK POINT, and why it is this one (Ghidra, mvc_dump.bin):
//   * FUN_140607d60 is the WHOLE frame (sim + render dispatch + walker + submit): FRAME-READSET s1.
//     It is reachable only through the function pointer game_state+0x10, which FUN_140607b50 (engine
//     init) sets ONCE and nothing rewrites (xrefs: 0x140607bef/0x140607c0e data refs, static initial
//     value at 0x140ac6d50). So one detour covers character select, the transition and the battle.
//   * Its two callers both store the pad words at game_state+0x218/+0x21C IMMEDIATELY before calling
//     it: the offline loop FUN_140039de0 (stores 0x14003a33b / 0x14003a35f, CALL [RAX+0x10] at
//     0x14003a3ac) and the GGPO wrapper FUN_140118950 (pad[seat(k)] = inputs[k] & 0xffffff, then the
//     same indirect call). Writing the seat words at the detour's entry therefore lands AFTER the
//     pad store and BEFORE the sim reads them (FUN_140048630 <- FUN_14060b7d0, the translation into
//     blk+0x3C66) -- no code patch (the old NOP of the two stores, replay-kit/inputrec.py) is needed,
//     and the `prev = cur` shuffle that precedes the store sees OUR previous word, so just-pressed /
//     just-released stay right.
//   * The record is taken at ENTRY, i.e. clock == c means "the state the tick that produced c left
//     behind", which is exactly what the agent's row c is (it samples while blk+0x3CC8 == c).
//   * The anchor is written at entry too, on the game thread: no other thread touches blk between two
//     ticks (the render dispatcher runs INSIDE the tick), so the copy cannot tear.
//
// FASTER THAN REAL TIME (`speed n`): FUN_140039de0 refills game_state+0x798 (frames-to-run) with the
// immediate at 0x14003a2d0 (C7 82 98 07 00 00 | imm32 = 1) and drains it in a loop around the tick;
// patching the immediate to n runs n ticks per vsync with rendering suppressed on the catch-up ones
// (game_state+0x770). STEAM-GGPO-DETERMINISM s4 named this patch; it is applied only on command.
//
// SAFETY: every command that writes into the game is refused while a GGPO session is live
// (*0x142E10B98 != 0); nothing here runs unless the driver writes the command file.
#define RR_TICK_FN    0x140607D60ULL   // frame entry = *(game_state+0x10)
#define RR_GS_PTR     0x140ACD3A0ULL   // PTR_DAT_140acd3a0 -> game_state (0x140AC6D40)
#define RR_GGPO_SESS  0x142E10B98ULL   // ggpo session handle (0 = offline)
#define RR_SPEED_INSN 0x14003A2D0ULL   // MOV dword ptr [RDX+0x798],imm32 in FUN_140039de0
#define RR_GS_IN0     0x218u           // game_state+0x218/+0x21C = seat 0 / seat 1 raw words
#define RR_GS_PAUSE   0x780u           // game_state+0x780: != 0 gates the whole tick loop
#define RR_CLOCK_OFF  0x3CC8u          // blk+0x3CC8 = sim frame clock (== GGPO _framecount)
#define RR_MODE_OFF   0x3CB8u          // blk+0x3CB8 byte[2]: 1 char select, 2 battle
#define RR_H0         0x3DB8u          // fighter slot 0; stride 0x738
#define RR_HSTRIDE    0x738u
#define RR_SLOTPTRS   0x32500u         // six absolute self-pointers (blk+H0+n*stride) or all zero on a fresh block

typedef void (*PFN_Tick)(void);
static PFN_Tick oTick = nullptr;
static bool g_tickHooked = false;

struct RcInputs { uint32_t first, n; uint32_t* w; uint8_t* has; };
static RcInputs* volatile g_rcIn = nullptr;
static uint8_t* g_rcAnchorBuf = nullptr;
static volatile LONG g_rcAnchorPending = 0;
static volatile LONG g_rcLogOn = 0;
static FILE* g_rcLog = nullptr;
static volatile LONG g_rcTicks = 0, g_rcFed = 0, g_rcAnchorLoads = 0, g_rcLastClock = -1, g_rcActive = 0;
static unsigned g_rcSinceFlush = 0;
static uint8_t g_rcScratch[0x3000];

#pragma pack(push, 1)
struct RcSlot { uint8_t active, cid; uint16_t hp; float x, y; uint16_t sid; uint8_t drawn, pad; };   // 16 B
struct RcRec  { uint32_t magic, clock, in0, in1, flags, present; uint8_t mode[8]; RcSlot s[6]; };    // 128 B
#pragma pack(pop)
#define RC_MAGIC 0x31434552u   // "REC1"

static void hkTick(void) {
    uintptr_t blk = 0, gs = 0;
    if (g_imgBase && safeRead((const void*)RR_RVA(RR_BLK_PTR), &blk, sizeof(blk))
                  && safeRead((const void*)RR_RVA(RR_GS_PTR), &gs, sizeof(gs)) && blk && gs) {
        uint32_t flags = 0;
        if (g_rcAnchorPending && g_rcAnchorBuf) {
            memcpy((void*)blk, g_rcAnchorBuf, RR_BLK_SZ);
            InterlockedExchange(&g_rcAnchorPending, 0);
            InterlockedIncrement(&g_rcAnchorLoads);
            flags |= 2;
        }
        uint32_t clock = 0;
        memcpy(&clock, (const void*)(blk + RR_CLOCK_OFF), 4);
        uint32_t in0 = 0, in1 = 0;
        memcpy(&in0, (const void*)(gs + RR_GS_IN0), 4);
        memcpy(&in1, (const void*)(gs + RR_GS_IN0 + 4), 4);
        RcInputs* t = g_rcIn;
        if (t && clock >= t->first && clock - t->first < t->n && t->has[clock - t->first]) {
            in0 = t->w[2 * (clock - t->first)];
            in1 = t->w[2 * (clock - t->first) + 1];
            memcpy((void*)(gs + RR_GS_IN0), &in0, 4);
            memcpy((void*)(gs + RR_GS_IN0 + 4), &in1, 4);
            flags |= 1;
            InterlockedIncrement(&g_rcFed);
        }
        if (g_rcLogOn && g_rcLog) {
            // one read of blk+0x3CB8 .. slot 5 end (0x6908): mode bytes, clock, the six fighters
            if (safeRead((const void*)(blk + RR_MODE_OFF), g_rcScratch, 0x6908 - RR_MODE_OFF)) {
                RcRec r = {};
                r.magic = RC_MAGIC; r.clock = clock; r.in0 = in0; r.in1 = in1; r.flags = flags; r.present = g_frame;
                memcpy(r.mode, g_rcScratch, 8);
                for (int i = 0; i < 6; ++i) {
                    const uint8_t* H = g_rcScratch + (RR_H0 - RR_MODE_OFF) + i * RR_HSTRIDE;
                    r.s[i].active = H[0];
                    r.s[i].cid    = H[0x6C0];
                    memcpy(&r.s[i].hp,  H + 0x578, 2);
                    memcpy(&r.s[i].x,   H + 0x50, 4);
                    memcpy(&r.s[i].y,   H + 0x54, 4);
                    memcpy(&r.s[i].sid, H + 0x188, 2);
                    r.s[i].drawn = H[0x170];
                }
                fwrite(&r, sizeof(r), 1, g_rcLog);
                if (++g_rcSinceFlush >= 60) { fflush(g_rcLog); g_rcSinceFlush = 0; }
            }
        }
        InterlockedIncrement(&g_rcTicks);
        InterlockedExchange(&g_rcLastClock, (LONG)clock);
    }
    if (oTick) oTick();
}

static void installTickHook() {
    if (!g_imgBase) return;
    void* tt = (void*)RR_RVA(RR_TICK_FN);
    uint8_t pro[5] = {0};
    // FUN_140607d60 prologue: 48 83 EC 28 (SUB RSP,0x28) E8 (CALL FUN_1408441d0). Refuse a build we do not know.
    if (!safeRead(tt, pro, 5) || pro[0] != 0x48 || pro[1] != 0x83 || pro[2] != 0xEC || pro[3] != 0x28 || pro[4] != 0xE8) {
        logf("[mh] %-22s NOT hooked: unexpected prologue %02X %02X %02X %02X %02X at %p", "FrameTick",
             pro[0], pro[1], pro[2], pro[3], pro[4], tt);
        return;
    }
    MH_STATUS a = MH_CreateHook(tt, (void*)&hkTick, (void**)&oTick);
    MH_STATUS b = (a == MH_OK) ? MH_EnableHook(tt) : a;
    g_tickHooked = (b == MH_OK);
    logf("[mh] %-22s create=%d enable=%d  (%p; receipt player: seat words injected + state logged per tick)",
         "FrameTick", (int)a, (int)b, tt);
}

// ── command channel: %TEMP%\rrcap\CMD (one line), answered in CMD.ack; status in receipt_status.json ──
static char g_rcCmdPath[MAX_PATH], g_rcAckPath[MAX_PATH], g_rcStatusPath[MAX_PATH];

static void rcAck(const char* fmt, ...) {
    char msg[1024];
    va_list ap; va_start(ap, fmt);
    _vsnprintf_s(msg, sizeof(msg), _TRUNCATE, fmt, ap);
    va_end(ap);
    logf("[receipt] %s", msg);
    FILE* f = nullptr;
    if (fopen_s(&f, g_rcAckPath, "wb") == 0 && f) { fputs(msg, f); fclose(f); }
}

static bool rcOnline() {
    uintptr_t s = 0;
    return g_imgBase && safeRead((const void*)RR_RVA(RR_GGPO_SESS), &s, sizeof(s)) && s != 0;
}

static void rcStatus() {
    uintptr_t blk = 0, gs = 0, arena = 0;
    uint32_t pause = 0, clock = 0, imm = 0;
    uint8_t mode[5] = {0};
    if (g_imgBase) {
        safeRead((const void*)RR_RVA(RR_BLK_PTR), &blk, sizeof(blk));
        safeRead((const void*)RR_RVA(RR_GS_PTR), &gs, sizeof(gs));
        if (gs) { safeRead((const void*)gs, &arena, sizeof(arena)); safeRead((const void*)(gs + RR_GS_PAUSE), &pause, 4); }
        if (blk) { safeRead((const void*)(blk + RR_CLOCK_OFF), &clock, 4); safeRead((const void*)(blk + RR_MODE_OFF), mode, 5); }
        safeRead((const void*)(RR_RVA(RR_SPEED_INSN) + 6), &imm, 4);
    }
    RcInputs* t = g_rcIn;
    FILE* f = nullptr;
    char tmp[MAX_PATH];
    _snprintf_s(tmp, sizeof(tmp), _TRUNCATE, "%s.tmp", g_rcStatusPath);
    if (fopen_s(&f, tmp, "wb") != 0 || !f) return;
    fprintf(f, "{\"hooked\":%s,\"online\":%s,\"paused\":%u,\"blk\":%llu,\"arena\":%llu,\"clock\":%u,"
               "\"mode\":[%u,%u,%u,%u,%u],\"ticks\":%ld,\"fed\":%ld,\"last_clock\":%ld,\"anchor_pending\":%ld,"
               "\"anchor_loads\":%ld,\"log_on\":%ld,\"inputs\":{\"first\":%u,\"n\":%u},\"speed_imm\":%u,\"present\":%u}\n",
            g_tickHooked ? "true" : "false", rcOnline() ? "true" : "false", pause,
            (unsigned long long)blk, (unsigned long long)arena, clock,
            mode[0], mode[1], mode[2], mode[3], mode[4], g_rcTicks, g_rcFed, g_rcLastClock, g_rcAnchorPending,
            g_rcAnchorLoads, g_rcLogOn, t ? t->first : 0, t ? t->n : 0, imm, g_frame);
    fclose(f);
    MoveFileExA(tmp, g_rcStatusPath, MOVEFILE_REPLACE_EXISTING);
}

static uint8_t* rcReadFile(const char* path, size_t* len) {
    FILE* f = nullptr;
    if (fopen_s(&f, path, "rb") != 0 || !f) return nullptr;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    uint8_t* b = (n > 0) ? (uint8_t*)malloc((size_t)n) : nullptr;
    if (b && fread(b, 1, (size_t)n, f) != (size_t)n) { free(b); b = nullptr; }
    fclose(f);
    if (len) *len = b ? (size_t)n : 0;
    return b;
}

static void rcCmdAnchor(char* args) {
    // anchor <blk_hex> <arena_hex> <force 0|1> <path>
    char* ctx = nullptr;
    const char* sBlk = args ? strtok_s(args, " ", &ctx) : nullptr;
    const char* sArena = sBlk ? strtok_s(nullptr, " ", &ctx) : nullptr;
    const char* sForce = sArena ? strtok_s(nullptr, " ", &ctx) : nullptr;
    const char* path = sForce ? ctx : nullptr;
    if (!sBlk || !sArena || !sForce || !path || !*path) { rcAck("ERR anchor: usage anchor <blk_hex> <arena_hex> <force> <path>"); return; }
    if (rcOnline()) { rcAck("REFUSED anchor: a GGPO session is live (*0x142E10B98 != 0)"); return; }
    if (!g_tickHooked) { rcAck("REFUSED anchor: FrameTick hook not installed"); return; }
    uintptr_t blk = 0, gs = 0, arena = 0;
    safeRead((const void*)RR_RVA(RR_BLK_PTR), &blk, sizeof(blk));
    safeRead((const void*)RR_RVA(RR_GS_PTR), &gs, sizeof(gs));
    if (gs) safeRead((const void*)gs, &arena, sizeof(arena));
    unsigned long long wantBlk = _strtoui64(sBlk, nullptr, 16), wantArena = _strtoui64(sArena, nullptr, 16);
    if (!blk || (uintptr_t)wantBlk != blk) { rcAck("REFUSED anchor: relocated for blk 0x%llx but live blk is 0x%llx", wantBlk, (unsigned long long)blk); return; }
    if ((uintptr_t)wantArena != arena && sForce[0] != '1') { rcAck("REFUSED anchor: relocated for arena 0x%llx but live arena is 0x%llx (force=1 to override)", wantArena, (unsigned long long)arena); return; }
    size_t len = 0;
    uint8_t* b = rcReadFile(path, &len);
    if (!b || len != RR_BLK_SZ) { rcAck("ERR anchor: %s is %zu bytes, need %u", path, len, RR_BLK_SZ); free(b); return; }
    // self-check (rrtape4.restore_anchor): the six self-pointers at blk+0x32500 are either all zero (a block
    // that has not run a match yet -- what a char-select anchor taken right after init looks like) or a
    // permutation of the six slot bases in THIS process.
    unsigned zero = 0, seen = 0;
    for (int k = 0; k < 6; ++k) {
        uint64_t p = 0; memcpy(&p, b + RR_SLOTPTRS + 8 * k, 8);
        if (!p) { ++zero; continue; }
        long long rel = (long long)p - (long long)blk - (long long)RR_H0;
        if (rel < 0 || rel % RR_HSTRIDE || rel / RR_HSTRIDE >= 6) { rcAck("REFUSED anchor: self-check slot %d = 0x%llx is not a slot base of blk 0x%llx", k, (unsigned long long)p, (unsigned long long)blk); free(b); return; }
        seen |= 1u << (rel / RR_HSTRIDE);
    }
    if (zero != 6 && seen != 0x3F) { rcAck("REFUSED anchor: self-check not a permutation (mask 0x%X, %u zero)", seen, zero); free(b); return; }
    uint32_t clk = 0; memcpy(&clk, b + RR_CLOCK_OFF, 4);
    if (!g_rcAnchorBuf) g_rcAnchorBuf = (uint8_t*)malloc(RR_BLK_SZ);
    if (!g_rcAnchorBuf) { rcAck("ERR anchor: out of memory"); free(b); return; }
    memcpy(g_rcAnchorBuf, b, RR_BLK_SZ);
    free(b);
    LONG before = g_rcTicks;
    InterlockedExchange(&g_rcAnchorPending, 1);
    InterlockedExchange(&g_rcActive, 1);
    for (int i = 0; i < 200 && g_rcAnchorPending; ++i) Sleep(10);   // the game thread applies it at the next tick
    if (g_rcAnchorPending) {
        uint32_t pause = 0; if (gs) safeRead((const void*)(gs + RR_GS_PAUSE), &pause, 4);
        rcAck("QUEUED anchor (clock %u, self-check %s): no tick in 2 s -- game paused/unfocused? (game_state+0x780=%u, ticks %ld)",
              clk, zero == 6 ? "fresh block" : "permutation", pause, g_rcTicks - before);
    } else {
        rcAck("OK anchor applied at tick (anchor clock %u, self-check %s, live clock now %ld)", clk,
              zero == 6 ? "fresh block" : "permutation", g_rcLastClock);
    }
}

static void rcCmdInputs(const char* path) {
    if (!path || !*path) { rcAck("ERR inputs: usage inputs <path>"); return; }
    if (rcOnline()) { rcAck("REFUSED inputs: a GGPO session is live"); return; }
    size_t len = 0;
    uint8_t* b = rcReadFile(path, &len);
    if (!b || len < 12 || len % 12) { rcAck("ERR inputs: %s is %zu bytes (need (u32 clock,u32 s0,u32 s1)*)", path, len); free(b); return; }
    size_t n = len / 12;
    uint32_t lo = 0xFFFFFFFFu, hi = 0;
    for (size_t i = 0; i < n; ++i) { uint32_t c; memcpy(&c, b + 12 * i, 4); if (c < lo) lo = c; if (c > hi) hi = c; }
    if (hi - lo > 4000000) { rcAck("ERR inputs: clock span %u..%u too wide", lo, hi); free(b); return; }
    RcInputs* t = (RcInputs*)calloc(1, sizeof(RcInputs));
    if (!t) { free(b); rcAck("ERR inputs: out of memory"); return; }
    t->first = lo; t->n = hi - lo + 1;
    t->w = (uint32_t*)calloc((size_t)t->n * 2, 4);
    t->has = (uint8_t*)calloc(t->n, 1);
    if (!t->w || !t->has) { free(b); rcAck("ERR inputs: out of memory"); return; }
    for (size_t i = 0; i < n; ++i) {
        uint32_t c, s0, s1; memcpy(&c, b + 12 * i, 4); memcpy(&s0, b + 12 * i + 4, 4); memcpy(&s1, b + 12 * i + 8, 4);
        t->w[2 * (c - lo)] = s0; t->w[2 * (c - lo) + 1] = s1; t->has[c - lo] = 1;
    }
    free(b);
    InterlockedExchangePointer((PVOID volatile*)&g_rcIn, t);   // the old table is intentionally leaked: the game thread may still hold it
    InterlockedExchange(&g_rcFed, 0);
    InterlockedExchange(&g_rcActive, 1);
    rcAck("OK inputs: %zu entries, entry clocks %u..%u", n, lo, hi);
}

static void rcCmdStart(const char* path) {
    if (!path || !*path) { rcAck("ERR start: usage start <logpath>"); return; }
    if (g_rcLog) { InterlockedExchange(&g_rcLogOn, 0); Sleep(50); fclose(g_rcLog); g_rcLog = nullptr; }
    FILE* f = nullptr;
    if (fopen_s(&f, path, "wb") != 0 || !f) { rcAck("ERR start: cannot open %s", path); return; }
    setvbuf(f, nullptr, _IOFBF, 1 << 20);
    g_rcLog = f; g_rcSinceFlush = 0;
    InterlockedExchange(&g_rcTicks, 0);
    InterlockedExchange(&g_rcLogOn, 1);
    InterlockedExchange(&g_rcActive, 1);
    rcAck("OK start: logging %zu-byte tick records to %s", sizeof(RcRec), path);
}

static void rcCmdStop() {
    InterlockedExchange(&g_rcLogOn, 0);
    Sleep(50);
    if (g_rcLog) { fclose(g_rcLog); g_rcLog = nullptr; }
    rcAck("OK stop: ticks=%ld fed=%ld last_clock=%ld anchor_loads=%ld", g_rcTicks, g_rcFed, g_rcLastClock, g_rcAnchorLoads);
}

static void rcCmdSpeed(const char* sN) {
    int n = sN ? atoi(sN) : 0;
    if (n < 1 || n > 64) { rcAck("ERR speed: 1..64"); return; }
    if (rcOnline()) { rcAck("REFUSED speed: a GGPO session is live"); return; }
    uint8_t* insn = (uint8_t*)RR_RVA(RR_SPEED_INSN);
    uint8_t cur[10] = {0};
    if (!safeRead(insn, cur, 10) || cur[0] != 0xC7 || cur[1] != 0x82 || cur[2] != 0x98 || cur[3] != 0x07 || cur[4] != 0 || cur[5] != 0) {
        rcAck("REFUSED speed: unexpected code at 0x14003A2D0 (%02X %02X %02X %02X %02X %02X)", cur[0], cur[1], cur[2], cur[3], cur[4], cur[5]);
        return;
    }
    uint32_t was = 0; memcpy(&was, cur + 6, 4);
    DWORD old = 0;
    if (!VirtualProtect(insn, 10, PAGE_EXECUTE_READWRITE, &old)) { rcAck("ERR speed: VirtualProtect %lu", GetLastError()); return; }
    uint32_t imm = (uint32_t)n;
    memcpy(insn + 6, &imm, 4);
    VirtualProtect(insn, 10, old, &old);
    FlushInstructionCache(GetCurrentProcess(), insn, 10);
    rcAck("OK speed: frames-to-run immediate at 0x14003A2D6 = %d (was %u)", n, was);
}

static void rcPoll() {
    static bool init = false;
    static ULONGLONG lastStatus = 0;
    if (!init) {
        init = true;
        _snprintf_s(g_rcCmdPath, sizeof(g_rcCmdPath), _TRUNCATE, "%s\\CMD", g_dir);
        _snprintf_s(g_rcAckPath, sizeof(g_rcAckPath), _TRUNCATE, "%s\\CMD.ack", g_dir);
        _snprintf_s(g_rcStatusPath, sizeof(g_rcStatusPath), _TRUNCATE, "%s\\receipt_status.json", g_dir);
        DeleteFileA(g_rcCmdPath);
    }
    if (g_rcActive && GetTickCount64() - lastStatus >= 250) { lastStatus = GetTickCount64(); rcStatus(); }
    if (GetFileAttributesA(g_rcCmdPath) == INVALID_FILE_ATTRIBUTES) return;
    Sleep(20);                                     // let the writer finish the line
    size_t len = 0;
    uint8_t* raw = rcReadFile(g_rcCmdPath, &len);
    DeleteFileA(g_rcCmdPath);
    if (!raw) return;
    char line[2048] = {0};
    size_t n = len < sizeof(line) - 1 ? len : sizeof(line) - 1;
    memcpy(line, raw, n); free(raw);
    for (size_t i = 0; i < n; ++i) if (line[i] == '\r' || line[i] == '\n') { line[i] = 0; break; }
    char* ctx = nullptr;
    char* verb = strtok_s(line, " ", &ctx);
    char* rest = ctx;
    if (!verb) { rcAck("ERR empty command"); return; }
    if      (!_stricmp(verb, "anchor")) rcCmdAnchor(rest);
    else if (!_stricmp(verb, "inputs")) rcCmdInputs(rest);
    else if (!_stricmp(verb, "start"))  rcCmdStart(rest);
    else if (!_stricmp(verb, "stop"))   rcCmdStop();
    else if (!_stricmp(verb, "speed"))  rcCmdSpeed(rest);
    else if (!_stricmp(verb, "status")) { InterlockedExchange(&g_rcActive, 1); rcStatus(); rcAck("OK status"); }
    else if (!_stricmp(verb, "reset"))  { InterlockedExchangePointer((PVOID volatile*)&g_rcIn, nullptr); rcCmdStop(); rcCmdSpeed("1"); rcAck("OK reset"); }
    else rcAck("ERR unknown command '%s'", verb);
    rcStatus();
}
