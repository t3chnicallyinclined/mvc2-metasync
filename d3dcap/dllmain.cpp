// RETRO RECEIPTS — PATH B capture shim for Steam MvC Fighting Collection (MvC2).
//
// WHY THIS FILE LOOKS THE WAY IT DOES — the history is load-bearing, do not "simplify" it back:
//
//  1. IDXGISwapChain's vtable lives in dxgi.dll .rdata and IS shared across instances. Patching it
//     from our own throwaway swapchain hooks the game's Present. PROVEN STABLE over 41,000+ frames.
//     This is the one and only vtable we patch.
//
//  2. ID3D11DeviceContext's vtable is per-instance (it sits at ctx+8, on the heap) AND THE GAME'S
//     CONTEXT HAS ITS DISPATCH TABLE REWRITTEN AT RUNTIME. Measured 2026-09-01: our patch verified
//     present on the first check ("slot12 still ours=1") and was gone on every check after. That is
//     why four runs measured "zero draws" while the GPU 3D engine was 9.26% busy under this PID.
//     ⚠ It is also UNSAFE: after a rewrite, the "originals" we saved may not match what d3d11
//     reinstalled, so forwarding through them can call a stale pointer. A crash was observed.
//     ⟹ ALL context vtable patching has been REMOVED. Draw interception is INLINE (MinHook) on the
//     d3d11.dll functions themselves, which a table rewrite cannot undo.
//
//  3. Targeting was never the problem: probe 1 confirmed renderer+0xC0 (from Ghidra, FUN_1402B80F0)
//     equals the exact context pointer we had hooked, and renderer+0xB8 equals the censused device.
//
// Ghidra facts used here (mvc2coll_dump, preferred base 0x140000000, REBASED at runtime):
//   0x142EBD8F0 -> renderer;  renderer+0xB8 device, +0xC0 context, +0xC8/+0x892EA8 swapchains
//   renderer+0x38 = "frame has content" gate, +0x43 = MT-render flag (both inside FUN_1402BCC60)
//   0x142EF0AB0 -> nDraw command queue; byte cursor at q+0x1E0080

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d3d11.h>
#include <dxgi.h>
#include <MinHook.h>
#include <cstdio>
#include <cstdarg>
#include <cstdint>
#include <cstring>
#include <intrin.h>
#pragma intrinsic(_ReturnAddress)

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "dxgi.lib")

// IDXGISwapChain vtable index 8 = Present. CONFIRMED against Windows SDK 10.0.26100.0
// (shared/dxgi.h IDXGISwapChainVtbl declaration order).
enum { VT_SC_PRESENT = 8 };
// ID3D11DeviceContext slots we READ addresses from (we never write these tables).
enum { VT_CTX_DRAWINDEXED = 12, VT_CTX_DRAW = 13, VT_CTX_DRAWINDEXEDINSTANCED = 20,
       VT_CTX_DRAWINSTANCED = 21 };

typedef HRESULT (STDMETHODCALLTYPE *PFN_Present)(IDXGISwapChain*, UINT, UINT);
typedef void (STDMETHODCALLTYPE *PFN_DrawIndexed)(ID3D11DeviceContext*, UINT, UINT, INT);
typedef void (STDMETHODCALLTYPE *PFN_Draw)(ID3D11DeviceContext*, UINT, UINT);
typedef void (STDMETHODCALLTYPE *PFN_DrawIndexedInstanced)(ID3D11DeviceContext*, UINT, UINT, UINT, INT, UINT);
typedef void (STDMETHODCALLTYPE *PFN_DrawInstanced)(ID3D11DeviceContext*, UINT, UINT, UINT, UINT);

static PFN_Present              oPresent  = nullptr;
static PFN_DrawIndexed          oDrawIdx  = nullptr;
static PFN_Draw                 oDraw     = nullptr;
static PFN_DrawIndexedInstanced oDrawIdxI = nullptr;
static PFN_DrawInstanced        oDrawI    = nullptr;

static volatile LONG g_arm = 0, g_shot = 0;
static volatile LONG cDrawIdx = 0, cDraw = 0, cDrawIdxI = 0, cDrawI = 0;
static unsigned g_frame = 0;

// -- BURST CAPTURE --------------------------------------------------------------------------------
// One frame proves the renderer; a SEQUENCE of consecutive frames is what makes a playback. Set
// D3DCAP_BURST=<n> before launching and each arm records n CONSECUTIVE frames instead of one.
//
// Three things make a burst affordable that a naive "just capture every frame" would not:
//   * the texture version table is kept ALIVE across the burst, so a texture is re-snapshotted only
//     when the game actually rewrites it. The stage art is dumped once for the whole burst; only the
//     character tiles, which really do change every frame, are re-dumped.
//   * vertex and index buffers are dumped only up to the HIGHEST BYTE any draw in the frame touched.
//     The game's vertex buffer is 2 MiB and a frame uses ~220 KB of it; dumping it whole would cost
//     240 MB for two seconds of match.
//   * the 8 MB scene-RT BMP and the backbuffer PNG are written for the FIRST frame of the burst only.
//     They are the diff's ground truth, and one is enough to prove the sequence renders correctly.
static unsigned g_burst = 1;            // frames per arm; from D3DCAP_BURST
static unsigned g_burstLeft = 0;        // frames still to record in the current burst
static unsigned g_burstFirst = 0;       // frame number the current burst started on
static unsigned g_burstGot = 0;         // frames of the current burst actually recorded
static volatile LONG g_burstDone = 0;   // a full burst is on disk; stop arming
static bool g_manual = false;           // D3DCAP_MANUAL: only arm when told to
static volatile LONG g_wantBurst = 0;   // manual mode: told to, and still trying
static char g_dir[MAX_PATH] = {0};

static uintptr_t g_imgBase = 0, g_imgSize = 0, g_renderer = 0;
static volatile LONG pSamples = 0, pGateA = 0, pGateB = 0, pQnz = 0, pQmax = 0, pProbed = 0;

#define RR_RVA(a) (g_imgBase + (uintptr_t)((a) - 0x140000000ULL))

static void logf(const char* fmt, ...) {
    char path[MAX_PATH];
    _snprintf_s(path, sizeof(path), _TRUNCATE, "%s\\d3dcap.log", g_dir);
    FILE* f = nullptr;
    if (fopen_s(&f, path, "a") != 0 || !f) return;
    va_list ap; va_start(ap, fmt);
    vfprintf(f, fmt, ap);
    va_end(ap);
    fprintf(f, "\n");
    fclose(f);
}

// forward declarations; all defined further down in this file.
static void noteBuf(ID3D11Buffer* b, const char* tag, UINT usedEnd = 0);
static unsigned noteTexVersioned(ID3D11DeviceContext* c, ID3D11Resource* r);
static void markTexDirty(ID3D11Resource* r);
static void noteRT(ID3D11Resource* r);
static const char* moduleOf(void* p);

// -- ASYNC FILE WRITER ----------------------------------------------------------------------------
// ⚠⚠ EVERY BYTE THIS TOOL WRITES USED TO BE WRITTEN FROM Present(), ON THE RENDER THREAD.
// That is fine for one frame every 8 seconds and ruinous for a burst. A 20-second run degraded the
// game from 60 fps to about 2 -- and got worse the longer it ran, which is the signature of file
// creation in a directory that keeps growing, plus an antivirus scan per new file. Handing the bytes
// to a background thread costs one memcpy and a lock, and takes the game's frame time out of the
// filesystem's hands entirely.
//
// Bounded on purpose: if the writer cannot keep up, the producer waits rather than growing until the
// process dies. A stall here shows up as a slow capture, which is visible; an unbounded queue shows
// up as an out-of-memory crash twenty minutes in, which is not.
struct WriteJob { char path[MAX_PATH]; uint8_t* data; size_t len; WriteJob* next; };
static CRITICAL_SECTION g_wcs;
static HANDLE g_wsem = nullptr;
static WriteJob* g_whead = nullptr;
static WriteJob* g_wtail = nullptr;
static volatile LONG64 g_wqueued = 0;      // bytes waiting to be written
static volatile LONG   g_wstalls = 0;
static const LONG64 WRITE_QUEUE_CAP = 512ll << 20;

static DWORD WINAPI writerThread(LPVOID) {
    for (;;) {
        WaitForSingleObject(g_wsem, INFINITE);
        WriteJob* j = nullptr;
        EnterCriticalSection(&g_wcs);
        if (g_whead) { j = g_whead; g_whead = j->next; if (!g_whead) g_wtail = nullptr; }
        LeaveCriticalSection(&g_wcs);
        if (!j) continue;
        FILE* f = nullptr;
        if (fopen_s(&f, j->path, "wb") == 0 && f) { fwrite(j->data, 1, j->len, f); fclose(f); }
        InterlockedAdd64(&g_wqueued, -(LONG64)j->len);
        free(j->data);
        free(j);
    }
}

/** Take ownership of `data` (malloc'd) and write it to `path` off-thread. */
static void writeAsync(const char* path, uint8_t* data, size_t len) {
    if (!data) return;
    if (!g_wsem) { FILE* f = nullptr;   // writer not up yet: fall back rather than lose the bytes
        if (fopen_s(&f, path, "wb") == 0 && f) { fwrite(data, 1, len, f); fclose(f); }
        free(data); return; }
    while (g_wqueued > WRITE_QUEUE_CAP) {
        if (InterlockedIncrement(&g_wstalls) == 1)
            logf("[write] queue full (%lld MB) -- the disk is the bottleneck, capture will slow",
                 (long long)(g_wqueued >> 20));
        Sleep(2);
    }
    WriteJob* j = (WriteJob*)calloc(1, sizeof(WriteJob));
    if (!j) { free(data); return; }
    strncpy_s(j->path, path, _TRUNCATE);
    j->data = data; j->len = len;
    EnterCriticalSection(&g_wcs);
    if (g_wtail) g_wtail->next = j; else g_whead = j;
    g_wtail = j;
    LeaveCriticalSection(&g_wcs);
    InterlockedAdd64(&g_wqueued, (LONG64)len);
    ReleaseSemaphore(g_wsem, 1, nullptr);
}

/** Copy `n` bytes and queue them. For data we do not own (a mapped staging resource). */
static void writeAsyncCopy(const char* path, const void* src, size_t n) {
    uint8_t* buf = (uint8_t*)malloc(n ? n : 1);
    if (!buf) return;
    memcpy(buf, src, n);
    writeAsync(path, buf, n);
}

// -- WHO WRITES THE GEOMETRY? --------------------------------------------------------------------
// ⭐ The question the Ghidra walk kept circling: which function turns game state into the vertices
// Steam draws? Static analysis is slow here because the object system dispatches through per-node
// handler pointers that Ghidra's auto-analysis never resolves (LAB_140653CE0 is not even a defined
// function). But we already hook Map and UpdateSubresource — we just never recorded the CALLER.
//
// A return address names the emitter with no guessing at all. Every distinct call site that writes a
// VERTEX or INDEX buffer is logged once, with its rebased address, so it can be pasted straight into
// Ghidra. This is the same trick that found the draw executor: the capture already knew
// 885 of 890 draws came from 0x1402B72F4 and nobody had looked.
// ⚠ ONE RETURN ADDRESS IS NOT ENOUGH. The first version logged _ReturnAddress(), which for every
// geometry write landed on 0x140371740 — 11,004 hits at a single site inside FUN_140371620, a
// GENERIC BUFFER-UPLOAD HELPER with 24 callers. The helper is not the emitter; its caller is. So
// capture a short backtrace and report every frame that lies inside the game module.
struct WriteSite { uintptr_t ret[4]; unsigned kind; unsigned hits; };
static WriteSite g_wsite[64];
static int g_nwsite = 0;

static void noteWriter(void* ret, ID3D11Resource* r, const char* how) {
    if (!r) return;
    D3D11_RESOURCE_DIMENSION dim = D3D11_RESOURCE_DIMENSION_UNKNOWN;
    r->GetType(&dim);
    if (dim != D3D11_RESOURCE_DIMENSION_BUFFER) return;
    ID3D11Buffer* b = nullptr;
    if (FAILED(r->QueryInterface(__uuidof(ID3D11Buffer), (void**)&b)) || !b) return;
    D3D11_BUFFER_DESC bd = {};
    b->GetDesc(&bd);
    b->Release();
    // vertex/index buffers only — constant buffers are already shadowed elsewhere and their writers
    // are the renderer, not the game.
    if (!(bd.BindFlags & (D3D11_BIND_VERTEX_BUFFER | D3D11_BIND_INDEX_BUFFER))) return;

    // frame 0 is this hook; 1 is the D3D call site; 2+ is who asked for it.
    void* bt[8] = {};
    USHORT n = RtlCaptureStackBackTrace(1, 8, bt, nullptr);
    uintptr_t key[4] = {0, 0, 0, 0};
    int k = 0;
    for (USHORT i = 0; i < n && k < 4; ++i) {
        uintptr_t a = (uintptr_t)bt[i];
        if (g_imgBase && a >= g_imgBase && a < g_imgBase + g_imgSize)
            key[k++] = a - g_imgBase + 0x140000000ULL;      // rebased, paste-ready
    }
    if (!k) key[0] = (uintptr_t)ret;

    for (int i = 0; i < g_nwsite; ++i)
        if (memcmp(g_wsite[i].ret, key, sizeof(key)) == 0) { ++g_wsite[i].hits; return; }
    if (g_nwsite >= 64) return;
    memcpy(g_wsite[g_nwsite].ret, key, sizeof(key));
    g_wsite[g_nwsite].kind = bd.BindFlags;
    g_wsite[g_nwsite].hits = 1;
    ++g_nwsite;

    logf("[emit] NEW %s writer  %u bytes flags=0x%X  call chain: 0x%llX <- 0x%llX <- 0x%llX <- 0x%llX",
         how, bd.ByteWidth, bd.BindFlags,
         (unsigned long long)key[0], (unsigned long long)key[1],
         (unsigned long long)key[2], (unsigned long long)key[3]);
}

static bool safeRead(const void* src, void* dst, size_t n) {
    __try { memcpy(dst, src, n); return true; }
    __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
}



// -- CONSTANT-BUFFER SHADOWING (the stale-snapshot fix) -------------------------------------------
// ⚠ 2026-09-01: snapshotting constant buffers at Present is WRONG. The post-processing chain REUSES
// the same buffer objects and overwrites them in place, so a Present-time read of CBWorld /
// CBViewProjection returns the post chain's identity matrix and camera-at-origin -- which is what
// made "fFogDensity = 0, fog is a no-op" a false finding. The vertex buffer is safe at Present only
// because the game APPENDS to it; that property does not generalise across resource types.
//
// Fix: shadow every small constant buffer at Map/Unmap time, so we hold the bytes the DRAW actually
// saw. Content-hashed and deduped -- CBWorld is 48B, CBFog 80B, the largest seen is 432B.
// Map/Unmap are inline-hooked at their d3d11.dll addresses, like the draws; the context's dispatch
// table is rewritten at runtime so vtable patching is not trusted anywhere in this file.
enum { CVT_MAP = 14, CVT_UNMAP = 15 };

typedef HRESULT (STDMETHODCALLTYPE *PFN_Map)(ID3D11DeviceContext*, ID3D11Resource*, UINT, D3D11_MAP, UINT, D3D11_MAPPED_SUBRESOURCE*);
typedef void (STDMETHODCALLTYPE *PFN_Unmap)(ID3D11DeviceContext*, ID3D11Resource*, UINT);
static PFN_Map   oMap   = nullptr;
static PFN_Unmap oUnmap = nullptr;

#define CB_MAX_BYTES 2048
#define CB_SLOTS     96

struct CbShadow {
    ID3D11Resource* res;
    UINT     size;
    uint32_t hash;
    uint8_t  data[CB_MAX_BYTES];
};
static CbShadow g_cb[CB_SLOTS] = {};
static volatile LONG g_ncb = 0;

struct CbPending { ID3D11Resource* res; void* p; UINT size; };
static CbPending g_pending[8] = {};

static uint32_t fnv1a(const uint8_t* d, size_t n) {
    uint32_t h = 2166136261u;
    for (size_t i = 0; i < n; ++i) { h ^= d[i]; h *= 16777619u; }
    return h;
}

static CbShadow* findCb(ID3D11Resource* r) {
    LONG n = g_ncb;
    for (LONG i = 0; i < n; ++i) if (g_cb[i].res == r) return &g_cb[i];
    return nullptr;
}

static HRESULT STDMETHODCALLTYPE hkMap(ID3D11DeviceContext* c, ID3D11Resource* r, UINT sub,
                                       D3D11_MAP type, UINT flags, D3D11_MAPPED_SUBRESOURCE* mp) {
    HRESULT hr = oMap ? oMap(c, r, sub, type, flags, mp) : E_FAIL;
    if (SUCCEEDED(hr) && r && mp && mp->pData && sub == 0) {
        if (type != D3D11_MAP_READ) noteWriter(_ReturnAddress(), r, "Map");
        // A texture mapped for writing is about to change, so anything a later draw samples from it
        // is NOT what an earlier draw saw. See the stale-texture note above noteTexVersioned.
        if (type != D3D11_MAP_READ) markTexDirty(r);
        D3D11_RESOURCE_DIMENSION dim = D3D11_RESOURCE_DIMENSION_UNKNOWN;
        r->GetType(&dim);
        if (dim == D3D11_RESOURCE_DIMENSION_BUFFER) {
            ID3D11Buffer* b = nullptr;
            if (SUCCEEDED(r->QueryInterface(__uuidof(ID3D11Buffer), (void**)&b)) && b) {
                D3D11_BUFFER_DESC bd = {};
                b->GetDesc(&bd);
                if ((bd.BindFlags & D3D11_BIND_CONSTANT_BUFFER) && bd.ByteWidth <= CB_MAX_BYTES) {
                    for (int i = 0; i < 8; ++i)
                        if (!g_pending[i].res) { g_pending[i].res = r; g_pending[i].p = mp->pData;
                                                 g_pending[i].size = bd.ByteWidth; break; }
                }
                b->Release();
            }
        }
    }
    return hr;
}

static void STDMETHODCALLTYPE hkUnmap(ID3D11DeviceContext* c, ID3D11Resource* r, UINT sub) {
    for (int i = 0; i < 8; ++i) {
        if (g_pending[i].res != r) continue;
        CbShadow* sh = findCb(r);
        if (!sh) {
            LONG slot = InterlockedIncrement(&g_ncb) - 1;
            if (slot < CB_SLOTS) { sh = &g_cb[slot]; sh->res = r; }
        }
        if (sh) {
            UINT n = g_pending[i].size;
            if (n > CB_MAX_BYTES) n = CB_MAX_BYTES;
            __try { memcpy(sh->data, g_pending[i].p, n); sh->size = n; sh->hash = fnv1a(sh->data, n); }
            __except (EXCEPTION_EXECUTE_HANDLER) { }
        }
        g_pending[i].res = nullptr;
        break;
    }
    if (oUnmap) oUnmap(c, r, sub);
}


// UpdateSubresource is the OTHER way a constant buffer gets written, and measurably the one this game
// uses: with only Map/Unmap shadowed, all 501 draws in frame 4730 reported hash 00000000 despite 496
// of them having CBs bound. D3D11_USAGE_DEFAULT buffers cannot be Mapped at all, so this is expected
// in hindsight -- shadow both paths.
// Index 48 CONFIRMED against Windows SDK 10.0.26100.0 ID3D11DeviceContextVtbl order.
enum { CVT_UPDATESUBRESOURCE = 48 };

typedef void (STDMETHODCALLTYPE *PFN_UpdateSubresource)(ID3D11DeviceContext*, ID3D11Resource*, UINT,
                                                       const D3D11_BOX*, const void*, UINT, UINT);
static PFN_UpdateSubresource oUpdateSub = nullptr;

static void STDMETHODCALLTYPE hkUpdateSub(ID3D11DeviceContext* c, ID3D11Resource* r, UINT sub,
                                          const D3D11_BOX* box, const void* src, UINT rp, UINT dp) {
    if (r && src) { markTexDirty(r); noteWriter(_ReturnAddress(), r, "UpdateSubresource"); }
    if (r && src && sub == 0) {
        D3D11_RESOURCE_DIMENSION dim = D3D11_RESOURCE_DIMENSION_UNKNOWN;
        r->GetType(&dim);
        if (dim == D3D11_RESOURCE_DIMENSION_BUFFER) {
            ID3D11Buffer* b = nullptr;
            if (SUCCEEDED(r->QueryInterface(__uuidof(ID3D11Buffer), (void**)&b)) && b) {
                D3D11_BUFFER_DESC bd = {};
                b->GetDesc(&bd);
                if ((bd.BindFlags & D3D11_BIND_CONSTANT_BUFFER) && bd.ByteWidth <= CB_MAX_BYTES) {
                    CbShadow* sh = findCb(r);
                    if (!sh) {
                        LONG slot = InterlockedIncrement(&g_ncb) - 1;
                        if (slot < CB_SLOTS) { sh = &g_cb[slot]; sh->res = r; }
                    }
                    if (sh) {
                        // A pDstBox may write only part of the buffer; without one it is the whole
                        // thing. Partial writes leave the rest of the shadow as previously seen,
                        // which is exactly the semantics of the real buffer.
                        UINT off = (box && box->left < CB_MAX_BYTES) ? box->left : 0;
                        UINT n = box ? (box->right - box->left) : bd.ByteWidth;
                        if (off + n > CB_MAX_BYTES) n = CB_MAX_BYTES - off;
                        __try {
                            memcpy(sh->data + off, src, n);
                            if (off + n > sh->size) sh->size = off + n;
                            sh->hash = fnv1a(sh->data, sh->size);
                        } __except (EXCEPTION_EXECUTE_HANDLER) { }
                    }
                }
                b->Release();
            }
        }
    }
    if (oUpdateSub) oUpdateSub(c, r, sub, box, src, rp, dp);
}

// Emit the CB the draw ACTUALLY saw, and write its bytes once per distinct content.
static uint32_t g_cbWritten[256] = {};
static int g_ncbWritten = 0;

static uint32_t emitCb(ID3D11Buffer* b) {
    CbShadow* sh = findCb((ID3D11Resource*)b);
    if (!sh || !sh->size) return 0;
    bool seen = false;
    for (int i = 0; i < g_ncbWritten; ++i) if (g_cbWritten[i] == sh->hash) { seen = true; break; }
    if (!seen && g_ncbWritten < 256) {
        g_cbWritten[g_ncbWritten++] = sh->hash;
        char path[MAX_PATH];
        _snprintf_s(path, sizeof(path), _TRUNCATE, "%s\\cb_%u_%08X.bin", g_dir, g_frame, sh->hash);
        FILE* f = nullptr;
        if (fopen_s(&f, path, "wb") == 0 && f) { fwrite(sh->data, 1, sh->size, f); fclose(f); }
    }
    return sh->hash;
}

// -- PER-DRAW INVENTORY -------------------------------------------------------------------------
// Runs inside the INLINE (MinHook) draw hooks, so it sees the draws a vtable patch never could.
// Every record carries `ret` = the game-code return address, REBASED to the dump image base, so each
// live draw is attributable to a call site in Ghidra instead of being interpreted by eye. The RE
// named 0x1402B72F0 / 0x1402B7645 as the Draw sites inside FUN_1402B6F30 (the D3D11 command
// executor) -- these records confirm or refute that directly.
// State is read back with the context's own Get* methods, which are NOT hooked, so no re-entrancy.
static volatile LONG g_armDraws = 0;
static bool     g_capturing = false;
static FILE*    g_out = nullptr;
static unsigned g_drawIdx = 0;

static void dumpDraw(ID3D11DeviceContext* ctx, const char* kind, UINT count, UINT inst,
                     UINT start, INT base, void* ret) {
    if (!g_out || !ctx) return;

    // Only rebase addresses that are actually INSIDE the game module. The overlay / ShadowPlay issue
    // their own draws into this same stream (the NV12 conversion quads), and rebasing a DLL address
    // as though it were the exe makes a foreign draw masquerade as a game call site.
    uintptr_t r = (uintptr_t)ret;
    uintptr_t img = 0;
    const char* retmod = "game";
    if (g_imgBase && r >= g_imgBase && r < g_imgBase + g_imgSize) {
        img = r - g_imgBase + 0x140000000ULL;
    } else {
        retmod = moduleOf((void*)r);
    }

    fprintf(g_out, "{\"f\":%u,\"i\":%u,\"kind\":\"%s\",\"count\":%u,\"inst\":%u,\"start\":%u,"
                   "\"base\":%d,\"ret\":\"0x%llX\",\"retmod\":\"%s\"",
            g_frame, g_drawIdx++, kind, count, inst, start, base, (unsigned long long)img, retmod);

    D3D11_PRIMITIVE_TOPOLOGY topo = D3D11_PRIMITIVE_TOPOLOGY_UNDEFINED;
    ctx->IAGetPrimitiveTopology(&topo);
    fprintf(g_out, ",\"topo\":%d", (int)topo);

    ID3D11InputLayout* il = nullptr; ctx->IAGetInputLayout(&il);
    fprintf(g_out, ",\"il\":\"%p\"", (void*)il);
    if (il) il->Release();

    ID3D11VertexShader* vs = nullptr; ctx->VSGetShader(&vs, nullptr, nullptr);
    ID3D11PixelShader*  ps = nullptr; ctx->PSGetShader(&ps, nullptr, nullptr);
    fprintf(g_out, ",\"vs\":\"%p\",\"ps\":\"%p\"", (void*)vs, (void*)ps);
    if (vs) vs->Release();
    if (ps) ps->Release();

    ID3D11Buffer* vb = nullptr; UINT stride = 0, offset = 0;
    ctx->IAGetVertexBuffers(0, 1, &vb, &stride, &offset);
    UINT vbBytes = 0;
    if (vb) {
        D3D11_BUFFER_DESC bd = {};
        vb->GetDesc(&bd);
        vbBytes = bd.ByteWidth;
        // The draw reads vertices [start, start+count) at `stride` bytes each from `offset`. For a
        // DrawIndexed the indices could name any vertex, so those fall back to the whole buffer.
        UINT end = (kind[4] == 'I') ? bd.ByteWidth : offset + (start + count) * stride;
        if (end > bd.ByteWidth) end = bd.ByteWidth;
        noteBuf(vb, "vb", end);
    }
    fprintf(g_out, ",\"vb\":\"%p\",\"stride\":%u,\"voff\":%u,\"vbytes\":%u",
            (void*)vb, stride, offset, vbBytes);
    if (vb) vb->Release();

    // index buffer (the DrawIndexed minority) and VS constant buffer 0 (any projection matrix)
    ID3D11Buffer* ib = nullptr; DXGI_FORMAT ifmt = DXGI_FORMAT_UNKNOWN; UINT ioff = 0;
    ctx->IAGetIndexBuffer(&ib, &ifmt, &ioff);
    fprintf(g_out, ",\"ib\":\"%p\",\"ifmt\":%d,\"ioff\":%u", (void*)ib, (int)ifmt, ioff);
    if (ib) { noteBuf(ib, "ib"); ib->Release(); }

    ID3D11Buffer* cb0 = nullptr;
    ctx->VSGetConstantBuffers(0, 1, &cb0);
    fprintf(g_out, ",\"cb0\":\"%p\"", (void*)cb0);
    if (cb0) { noteBuf(cb0, "cb0"); cb0->Release(); }

    // 8 slots, not 4: a second bound texture is invisible otherwise.
    ID3D11ShaderResourceView* srv[8] = {};
    ctx->PSGetShaderResources(0, 8, srv);
    fprintf(g_out, ",\"tex\":[");
    for (int i = 0; i < 8; ++i) {
        if (i) fprintf(g_out, ",");
        if (!srv[i]) { fprintf(g_out, "null"); continue; }
        ID3D11Resource* res = nullptr; srv[i]->GetResource(&res);
        // A pointer alone is not an identity for a texture: the game rewrites textures mid-frame, so
        // the pointer must be qualified by which GENERATION of its content this draw sampled.
        unsigned ver = res ? noteTexVersioned(ctx, res) : 0;
        ID3D11Texture2D* t2 = nullptr;
        if (res) res->QueryInterface(__uuidof(ID3D11Texture2D), (void**)&t2);
        if (t2) {
            D3D11_TEXTURE2D_DESC td = {}; t2->GetDesc(&td);
            fprintf(g_out, "{\"p\":\"%p#%u\",\"w\":%u,\"h\":%u,\"fmt\":%d,\"mips\":%u}",
                    (void*)res, ver, td.Width, td.Height, (int)td.Format, td.MipLevels);
            t2->Release();
        } else {
            fprintf(g_out, "{\"p\":\"%p#%u\"}", (void*)res, ver);
        }
        if (res) res->Release();
        srv[i]->Release();
    }
    fprintf(g_out, "]");

    ID3D11BlendState* bs = nullptr; FLOAT bf[4] = {0,0,0,0}; UINT smask = 0;
    ctx->OMGetBlendState(&bs, bf, &smask);
    if (bs) {
        D3D11_BLEND_DESC bd = {}; bs->GetDesc(&bd);
        const D3D11_RENDER_TARGET_BLEND_DESC& rb = bd.RenderTarget[0];
        fprintf(g_out, ",\"blend\":{\"en\":%d,\"src\":%d,\"dst\":%d,\"op\":%d,\"srcA\":%d,"
                       "\"dstA\":%d,\"opA\":%d,\"mask\":%d,\"a2c\":%d}",
                (int)rb.BlendEnable, (int)rb.SrcBlend, (int)rb.DestBlend, (int)rb.BlendOp,
                (int)rb.SrcBlendAlpha, (int)rb.DestBlendAlpha, (int)rb.BlendOpAlpha,
                (int)rb.RenderTargetWriteMask, (int)bd.AlphaToCoverageEnable);
        bs->Release();
    } else {
        fprintf(g_out, ",\"blend\":null");
    }
    // bf/smask were being computed and discarded; BLEND_FACTOR(14)/INV_BLEND_FACTOR(15) make them
    // load-bearing, and the post chain uses a partial write mask.
    fprintf(g_out, ",\"bfactor\":[%g,%g,%g,%g],\"smask\":%u", bf[0], bf[1], bf[2], bf[3], smask);

    // samplers: filter/address are directly pixel-visible for a 2D game resampled 1280x960 -> 768
    ID3D11SamplerState* smp[8] = {};
    ctx->PSGetSamplers(0, 8, smp);
    fprintf(g_out, ",\"samp\":[");
    for (int i = 0; i < 8; ++i) {
        if (i) fprintf(g_out, ",");
        if (!smp[i]) { fprintf(g_out, "null"); continue; }
        D3D11_SAMPLER_DESC sdd = {}; smp[i]->GetDesc(&sdd);
        fprintf(g_out, "{\"filter\":%d,\"u\":%d,\"v\":%d,\"w\":%d,\"bias\":%g,\"maxaniso\":%u,"
                       "\"cmp\":%d,\"minlod\":%g,\"maxlod\":%g}",
                (int)sdd.Filter, (int)sdd.AddressU, (int)sdd.AddressV, (int)sdd.AddressW,
                sdd.MipLODBias, sdd.MaxAnisotropy, (int)sdd.ComparisonFunc, sdd.MinLOD, sdd.MaxLOD);
        smp[i]->Release();
    }
    fprintf(g_out, "]");

    // rasterizer + scissor: the scene RT is 2048x1024 with a 1280x960 viewport at (384,32), so a
    // scissor is very likely bounding it; cull matters because flipped sprites reverse winding.
    ID3D11RasterizerState* rs = nullptr;
    ctx->RSGetState(&rs);
    if (rs) {
        D3D11_RASTERIZER_DESC rd = {}; rs->GetDesc(&rd);
        fprintf(g_out, ",\"raster\":{\"fill\":%d,\"cull\":%d,\"ccw\":%d,\"scissor\":%d,\"depthclip\":%d,"
                       "\"dbias\":%d,\"dbiasclamp\":%g,\"dbiasslope\":%g,\"ms\":%d,\"aaline\":%d}",
                (int)rd.FillMode, (int)rd.CullMode, (int)rd.FrontCounterClockwise,
                (int)rd.ScissorEnable, (int)rd.DepthClipEnable,
                (int)rd.DepthBias, rd.DepthBiasClamp, rd.SlopeScaledDepthBias,
                (int)rd.MultisampleEnable, (int)rd.AntialiasedLineEnable);
        rs->Release();
    } else { fprintf(g_out, ",\"raster\":null"); }
    UINT nsc = 1; D3D11_RECT scr = {};
    ctx->RSGetScissorRects(&nsc, &scr);
    if (nsc) fprintf(g_out, ",\"scissor\":[%ld,%ld,%ld,%ld]", scr.left, scr.top, scr.right, scr.bottom);

    // PS constant buffers -- where a 2D engine keeps per-draw tint/alpha modulation
    ID3D11Buffer* pcb[8] = {};
    ctx->PSGetConstantBuffers(0, 8, pcb);
    fprintf(g_out, ",\"pscb\":[");
    for (int i = 0; i < 8; ++i) {
        fprintf(g_out, "%s\"%p\"", i ? "," : "", (void*)pcb[i]);
    }
    fprintf(g_out, "],\"pscbHash\":[");
    for (int i = 0; i < 8; ++i) {
        fprintf(g_out, "%s\"%08X\"", i ? "," : "", pcb[i] ? emitCb(pcb[i]) : 0);
        if (pcb[i]) pcb[i]->Release();
    }
    fprintf(g_out, "]");

    // VS constant buffers 0..7 (was slot 0 only) -- any projection matrix lives here
    ID3D11Buffer* vcb[8] = {};
    ctx->VSGetConstantBuffers(0, 8, vcb);
    fprintf(g_out, ",\"vscb\":[");
    for (int i = 0; i < 8; ++i) {
        fprintf(g_out, "%s\"%p\"", i ? "," : "", (void*)vcb[i]);
    }
    fprintf(g_out, "],\"vscbHash\":[");
    for (int i = 0; i < 8; ++i) {
        fprintf(g_out, "%s\"%08X\"", i ? "," : "", vcb[i] ? emitCb(vcb[i]) : 0);
        if (vcb[i]) vcb[i]->Release();
    }
    fprintf(g_out, "]");

    // vertex buffer slots 1..3 -- a second stream would otherwise be invisible
    ID3D11Buffer* vbx[3] = {}; UINT vsx[3] = {}, vox[3] = {};
    ctx->IAGetVertexBuffers(1, 3, vbx, vsx, vox);
    fprintf(g_out, ",\"vb1_3\":[");
    for (int i = 0; i < 3; ++i) {
        fprintf(g_out, "%s{\"b\":\"%p\",\"stride\":%u,\"off\":%u}", i ? "," : "", (void*)vbx[i], vsx[i], vox[i]);
        if (vbx[i]) { noteBuf(vbx[i], "vb"); vbx[i]->Release(); }
    }
    fprintf(g_out, "]");

    ID3D11DepthStencilState* ds = nullptr; UINT sref = 0;
    ctx->OMGetDepthStencilState(&ds, &sref);
    if (ds) {
        D3D11_DEPTH_STENCIL_DESC dd = {}; ds->GetDesc(&dd);
        // StencilFunc + the three ops: "the comparison always passes" was INFERRED from a zero read
        // mask, never measured. Cheap to measure, so measure it.
        fprintf(g_out, ",\"depth\":{\"en\":%d,\"write\":%d,\"func\":%d,\"sten\":%d,"
                       "\"srmask\":%d,\"swmask\":%d,\"sref\":%u,"
                       "\"ffunc\":%d,\"ffail\":%d,\"fzfail\":%d,\"fpass\":%d,"
                       "\"bfunc\":%d,\"bfail\":%d,\"bzfail\":%d,\"bpass\":%d}",
                (int)dd.DepthEnable, (int)dd.DepthWriteMask, (int)dd.DepthFunc,
                (int)dd.StencilEnable, (int)dd.StencilReadMask, (int)dd.StencilWriteMask, sref,
                (int)dd.FrontFace.StencilFunc, (int)dd.FrontFace.StencilFailOp,
                (int)dd.FrontFace.StencilDepthFailOp, (int)dd.FrontFace.StencilPassOp,
                (int)dd.BackFace.StencilFunc, (int)dd.BackFace.StencilFailOp,
                (int)dd.BackFace.StencilDepthFailOp, (int)dd.BackFace.StencilPassOp);
        ds->Release();
    } else {
        fprintf(g_out, ",\"depth\":null");
    }

    ID3D11RenderTargetView* rtvs[8] = {}; ID3D11DepthStencilView* dsv = nullptr;
    ctx->OMGetRenderTargets(8, rtvs, &dsv);
    int nrt = 0; for (int i = 0; i < 8; ++i) if (rtvs[i]) ++nrt;
    fprintf(g_out, ",\"nrt\":%d", nrt);
    for (int i = 1; i < 8; ++i) if (rtvs[i]) rtvs[i]->Release();
    ID3D11RenderTargetView* rtv = rtvs[0];
    if (rtv) {
        ID3D11Resource* rr = nullptr; rtv->GetResource(&rr);
        noteRT(rr);
        ID3D11Texture2D* rt2 = nullptr;
        if (rr) rr->QueryInterface(__uuidof(ID3D11Texture2D), (void**)&rt2);
        if (rt2) {
            D3D11_TEXTURE2D_DESC rd = {}; rt2->GetDesc(&rd);
            fprintf(g_out, ",\"rt\":{\"p\":\"%p\",\"w\":%u,\"h\":%u,\"fmt\":%d}",
                    (void*)rr, rd.Width, rd.Height, (int)rd.Format);
            rt2->Release();
        } else { fprintf(g_out, ",\"rt\":{\"p\":\"%p\"}", (void*)rr); }
        if (rr) rr->Release();
        rtv->Release();
    } else { fprintf(g_out, ",\"rt\":null"); }
    if (dsv) {
        ID3D11Resource* dr = nullptr; dsv->GetResource(&dr);
        ID3D11Texture2D* dt = nullptr;
        if (dr) dr->QueryInterface(__uuidof(ID3D11Texture2D), (void**)&dt);
        if (dt) {
            D3D11_TEXTURE2D_DESC dd = {}; dt->GetDesc(&dd);
            fprintf(g_out, ",\"dsv\":{\"p\":\"%p\",\"w\":%u,\"h\":%u,\"fmt\":%d}",
                    (void*)dr, dd.Width, dd.Height, (int)dd.Format);
            dt->Release();
        }
        if (dr) dr->Release();
        dsv->Release();
    } else { fprintf(g_out, ",\"dsv\":null"); }

    UINT nvp = 1; D3D11_VIEWPORT vp = {};
    ctx->RSGetViewports(&nvp, &vp);
    if (nvp) fprintf(g_out, ",\"vp\":[%g,%g,%g,%g,%g,%g]", vp.TopLeftX, vp.TopLeftY, vp.Width, vp.Height, vp.MinDepth, vp.MaxDepth);

    fprintf(g_out, "}\n");
}


// -- CLEARS, RECORDED IN SUBMISSION ORDER ---------------------------------------------------------
// If an intermediate render target is NOT cleared, its previous-frame contents are part of the
// answer -- so a replay that starts every RT black is wrong. Clears are interleaved into the same
// event stream as draws (shared index) so the replay can reproduce the exact order.
// Indices CONFIRMED against Windows SDK 10.0.26100.0: 50 ClearRenderTargetView, 53 ClearDepthStencilView.
enum { CVT_CLEARRTV = 50, CVT_CLEARDSV = 53 };

typedef void (STDMETHODCALLTYPE *PFN_ClearRTV)(ID3D11DeviceContext*, ID3D11RenderTargetView*, const FLOAT[4]);
typedef void (STDMETHODCALLTYPE *PFN_ClearDSV)(ID3D11DeviceContext*, ID3D11DepthStencilView*, UINT, FLOAT, UINT8);
static PFN_ClearRTV oClearRTV = nullptr;
static PFN_ClearDSV oClearDSV = nullptr;

static void STDMETHODCALLTYPE hkClearRTV(ID3D11DeviceContext* c, ID3D11RenderTargetView* v, const FLOAT col[4]) {
    if (g_capturing && g_out && v) {
        ID3D11Resource* r = nullptr; v->GetResource(&r);
        UINT w = 0, h = 0; int fmt = -1;
        if (r) {
            ID3D11Texture2D* t = nullptr;
            if (SUCCEEDED(r->QueryInterface(__uuidof(ID3D11Texture2D), (void**)&t)) && t) {
                D3D11_TEXTURE2D_DESC d = {}; t->GetDesc(&d);
                w = d.Width; h = d.Height; fmt = (int)d.Format; t->Release();
            }
        }
        fprintf(g_out, "{\"f\":%u,\"i\":%u,\"kind\":\"ClearRTV\",\"rt\":{\"p\":\"%p\",\"w\":%u,\"h\":%u,\"fmt\":%d},"
                       "\"color\":[%g,%g,%g,%g]}\n",
                g_frame, g_drawIdx++, (void*)r, w, h, fmt,
                col ? col[0] : 0, col ? col[1] : 0, col ? col[2] : 0, col ? col[3] : 0);
        if (r) r->Release();
    }
    if (oClearRTV) oClearRTV(c, v, col);
}

static void STDMETHODCALLTYPE hkClearDSV(ID3D11DeviceContext* c, ID3D11DepthStencilView* v,
                                         UINT flags, FLOAT depth, UINT8 stencil) {
    if (g_capturing && g_out) {
        fprintf(g_out, "{\"f\":%u,\"i\":%u,\"kind\":\"ClearDSV\",\"dsv\":\"%p\",\"flags\":%u,"
                       "\"depth\":%g,\"stencil\":%u}\n",
                g_frame, g_drawIdx++, (void*)v, flags, depth, (unsigned)stencil);
    }
    if (oClearDSV) oClearDSV(c, v, flags, depth, stencil);
}

// ── INLINE DRAW HOOKS (MinHook) ──────────────────────────────────────────────────────────────────
// These detour the d3d11.dll functions themselves. The game rewriting its context's dispatch table
// puts the ORIGINAL addresses back -- which are exactly the addresses we trampolined -- so unlike a
// vtable patch, these keep firing.
static void STDMETHODCALLTYPE hkDrawIndexed(ID3D11DeviceContext* c, UINT n, UINT s, INT b) {
    InterlockedIncrement(&cDrawIdx);
    if (g_capturing) dumpDraw(c, "DrawIndexed", n, 1, s, b, _ReturnAddress());
    oDrawIdx(c, n, s, b);
}
static void STDMETHODCALLTYPE hkDraw(ID3D11DeviceContext* c, UINT n, UINT s) {
    InterlockedIncrement(&cDraw);
    if (g_capturing) dumpDraw(c, "Draw", n, 1, s, 0, _ReturnAddress());
    oDraw(c, n, s);
}
static void STDMETHODCALLTYPE hkDrawIndexedInstanced(ID3D11DeviceContext* c, UINT n, UINT i, UINT si, INT bv, UINT si2) {
    InterlockedIncrement(&cDrawIdxI);
    if (g_capturing) dumpDraw(c, "DrawIndexedInstanced", n, i, si, bv, _ReturnAddress());
    oDrawIdxI(c, n, i, si, bv, si2);
}
static void STDMETHODCALLTYPE hkDrawInstanced(ID3D11DeviceContext* c, UINT n, UINT i, UINT sv, UINT si) {
    InterlockedIncrement(&cDrawI);
    if (g_capturing) dumpDraw(c, "DrawInstanced", n, i, sv, 0, _ReturnAddress());
    oDrawI(c, n, i, sv, si);
}

static const char* moduleOf(void* p) {
    static char buf[MAX_PATH];
    HMODULE m = nullptr;
    if (!GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                            (LPCSTR)p, &m) || !m) return "<none>";
    char full[MAX_PATH];
    if (!GetModuleFileNameA(m, full, sizeof(full))) return "<unknown>";
    const char* base = strrchr(full, '\\');
    _snprintf_s(buf, sizeof(buf), _TRUNCATE, "%s", base ? base + 1 : full);
    return buf;
}

static volatile LONG g_drawHooksDone = 0;

// Read (never write) the draw function addresses out of a live context's table, then trampoline them.
static void installDrawHooks(ID3D11DeviceContext* ctx) {
    if (!ctx || InterlockedExchange(&g_drawHooksDone, 1)) return;
    void** vt = *(void***)ctx;

    void* tDrawIdx  = vt[VT_CTX_DRAWINDEXED];
    void* tDraw     = vt[VT_CTX_DRAW];
    void* tDrawIdxI = vt[VT_CTX_DRAWINDEXEDINSTANCED];
    void* tDrawI    = vt[VT_CTX_DRAWINSTANCED];

    logf("[mh] targets: DrawIndexed=%p(%s) Draw=%p(%s) DII=%p DI=%p",
         tDrawIdx, moduleOf(tDrawIdx), tDraw, moduleOf(tDraw), tDrawIdxI, tDrawI);

    // MinHook is initialised once by the worker (to hook the device-creation export) and this runs
// later, so a second MH_Initialize returns MH_ERROR_ALREADY_INITIALIZED -- which is SUCCESS for our
// purposes. Treating it as fatal is what left the draw hooks uninstalled and every inventory empty.
{
    MH_STATUS ini = MH_Initialize();
    if (ini != MH_OK && ini != MH_ERROR_ALREADY_INITIALIZED) {
        logf("[mh] MH_Initialize FAILED (%d)", (int)ini);
        return;
    }
}

    struct { void* target; void* detour; void** orig; const char* name; } h[] = {
        { tDrawIdx,             (void*)&hkDrawIndexed,          (void**)&oDrawIdx,  "DrawIndexed" },
        { tDraw,                (void*)&hkDraw,                 (void**)&oDraw,     "Draw" },
        { tDrawIdxI,            (void*)&hkDrawIndexedInstanced, (void**)&oDrawIdxI, "DrawIndexedInstanced" },
        { tDrawI,               (void*)&hkDrawInstanced,        (void**)&oDrawI,    "DrawInstanced" },
        { vt[CVT_CLEARRTV],     (void*)&hkClearRTV,             (void**)&oClearRTV, "ClearRenderTargetView" },
        { vt[CVT_CLEARDSV],     (void*)&hkClearDSV,             (void**)&oClearDSV, "ClearDepthStencilView" },
        { vt[CVT_MAP],          (void*)&hkMap,                  (void**)&oMap,      "Map" },
        { vt[CVT_UNMAP],        (void*)&hkUnmap,                (void**)&oUnmap,    "Unmap" },
        { vt[CVT_UPDATESUBRESOURCE], (void*)&hkUpdateSub,       (void**)&oUpdateSub, "UpdateSubresource" },
    };
    for (int i = 0; i < 9; ++i) {
        MH_STATUS a = MH_CreateHook(h[i].target, h[i].detour, h[i].orig);
        MH_STATUS b = (a == MH_OK) ? MH_EnableHook(h[i].target) : a;
        logf("[mh] %-22s create=%d enable=%d", h[i].name, (int)a, (int)b);
    }
}



// -- CREATION-TIME CAPTURE (input layouts + shader bytecode) --------------------------------------
// steam-d3d11-capture-expert, 2026-09-01: do NOT infer the vertex layout from value ranges -- 1.0f
// and 0x3F800000 are the same four bytes, and a UNORM colour channel and a normalised UV are
// indistinguishable without the format tag. The D3D11_INPUT_ELEMENT_DESC[] passed to
// CreateInputLayout IS the answer, and it keys directly to the `il` pointer already in every draw
// record. Likewise ID3D11VertexShader has no GetBytecode -- the ONLY chance to get the bytecode is
// the CreateVertexShader/CreatePixelShader call itself.
// ⚠ THERE IS NO RETROACTIVE PATH. Anything created before we inject is lost; the decoder reports
// coverage (referenced pointers vs captured ones) so an incomplete frame fails loudly.
// Device vtable indices CONFIRMED against Windows SDK 10.0.26100.0 ID3D11DeviceVtbl order:
//   11 CreateInputLayout, 12 CreateVertexShader, 15 CreatePixelShader
enum { DVT_CREATEINPUTLAYOUT = 11, DVT_CREATEVS = 12, DVT_CREATEPS = 15 };

typedef HRESULT (STDMETHODCALLTYPE *PFN_CreateInputLayout)(ID3D11Device*, const D3D11_INPUT_ELEMENT_DESC*, UINT, const void*, SIZE_T, ID3D11InputLayout**);
typedef HRESULT (STDMETHODCALLTYPE *PFN_CreateVS)(ID3D11Device*, const void*, SIZE_T, ID3D11ClassLinkage*, ID3D11VertexShader**);
typedef HRESULT (STDMETHODCALLTYPE *PFN_CreatePS)(ID3D11Device*, const void*, SIZE_T, ID3D11ClassLinkage*, ID3D11PixelShader**);

static PFN_CreateInputLayout oCreateIL = nullptr;
static PFN_CreateVS          oCreateVS = nullptr;
static PFN_CreatePS          oCreatePS = nullptr;
static volatile LONG cIL = 0, cVS = 0, cPS = 0;

static void writeBlob(const char* kind, void* key, const void* data, size_t len) {
    char path[MAX_PATH];
    _snprintf_s(path, sizeof(path), _TRUNCATE, "%s\\%s_%p.cso", g_dir, kind, key);
    FILE* f = nullptr;
    if (fopen_s(&f, path, "wb") == 0 && f) { fwrite(data, 1, len, f); fclose(f); }
}

static HRESULT STDMETHODCALLTYPE hkCreateInputLayout(ID3D11Device* d,
        const D3D11_INPUT_ELEMENT_DESC* elems, UINT n, const void* bc, SIZE_T bclen,
        ID3D11InputLayout** out) {
    HRESULT hr = oCreateIL ? oCreateIL(d, elems, n, bc, bclen, out) : E_FAIL;
    if (SUCCEEDED(hr) && out && *out && elems) {
        InterlockedIncrement(&cIL);
        char path[MAX_PATH];
        _snprintf_s(path, sizeof(path), _TRUNCATE, "%s\\il_%p.json", g_dir, (void*)*out);
        FILE* f = nullptr;
        if (fopen_s(&f, path, "w") == 0 && f) {
            fprintf(f, "{\"il\":\"%p\",\"elements\":[", (void*)*out);
            for (UINT i = 0; i < n; ++i) {
                const D3D11_INPUT_ELEMENT_DESC& e = elems[i];
                fprintf(f, "%s{\"semantic\":\"%s\",\"index\":%u,\"format\":%d,\"slot\":%u,"
                           "\"offset\":%u,\"class\":%d,\"step\":%u}",
                        i ? "," : "", e.SemanticName ? e.SemanticName : "?", e.SemanticIndex,
                        (int)e.Format, e.InputSlot, e.AlignedByteOffset,
                        (int)e.InputSlotClass, e.InstanceDataStepRate);
            }
            fprintf(f, "]}\n");
            fclose(f);
        }
    }
    return hr;
}

static HRESULT STDMETHODCALLTYPE hkCreateVS(ID3D11Device* d, const void* bc, SIZE_T len,
                                            ID3D11ClassLinkage* cl, ID3D11VertexShader** out) {
    HRESULT hr = oCreateVS ? oCreateVS(d, bc, len, cl, out) : E_FAIL;
    if (SUCCEEDED(hr) && out && *out && bc && len) { InterlockedIncrement(&cVS); writeBlob("vs", (void*)*out, bc, len); }
    return hr;
}

static HRESULT STDMETHODCALLTYPE hkCreatePS(ID3D11Device* d, const void* bc, SIZE_T len,
                                            ID3D11ClassLinkage* cl, ID3D11PixelShader** out) {
    HRESULT hr = oCreatePS ? oCreatePS(d, bc, len, cl, out) : E_FAIL;
    if (SUCCEEDED(hr) && out && *out && bc && len) { InterlockedIncrement(&cPS); writeBlob("ps", (void*)*out, bc, len); }
    return hr;
}

// Inline-hook the device creation entry points. Same MinHook technique as the draw functions: the
// context's dispatch table gets rewritten at runtime, so vtable patching is not trusted anywhere.
static void installCreationHooks(ID3D11Device* dev) {
    if (!dev) return;
    void** dvt = *(void***)dev;
    struct { void* t; void* d; void** o; const char* n; } h[] = {
        { dvt[DVT_CREATEINPUTLAYOUT], (void*)&hkCreateInputLayout, (void**)&oCreateIL, "CreateInputLayout" },
        { dvt[DVT_CREATEVS],          (void*)&hkCreateVS,          (void**)&oCreateVS, "CreateVertexShader" },
        { dvt[DVT_CREATEPS],          (void*)&hkCreatePS,          (void**)&oCreatePS, "CreatePixelShader" },
    };
    for (int i = 0; i < 3; ++i) {
        MH_STATUS a = MH_CreateHook(h[i].t, h[i].d, h[i].o);
        MH_STATUS b = (a == MH_OK) ? MH_EnableHook(h[i].t) : a;
        logf("[mh] %-20s @%p create=%d enable=%d", h[i].n, h[i].t, (int)a, (int)b);
    }
}

// -- TEXTURE CAPTURE ------------------------------------------------------------------------------
// -- TEXTURE CAPTURE, VERSIONED ------------------------------------------------------------------
// ⚠⚠ 2026-09-01, THE STALE-TEXTURE BUG. The first version noted each bound texture by pointer and
// snapshotted it ONCE, at Present, exactly the way the vertex buffer is handled. That is wrong for
// precisely the reason the Present-time CONSTANT-BUFFER snapshot was wrong (see the note above
// hkMap): the game REWRITES textures during a frame, so a Present-time read hands every draw the
// LAST content the object ever held. The vertex buffer survives that treatment only because the game
// APPENDS to it -- a property that does not generalise across resource types, and we generalised it
// anyway.
//
// Measured on frame 4261 before the fix: of the 123 character draws, 8 were pixel-exact and six were
// 100% wrong on every pixel they owned. Searching all 123 dumped index tiles for one that reproduces
// those draws found nothing above 8%, so the content they sampled was simply not in the capture. On
// screen the characters came out as scattered sprite shards over a correct stage.
//
// Fix: watch the two paths a texture is written through -- Map/Unmap and UpdateSubresource, the same
// two the constant buffers needed -- and at each DRAW snapshot any bound texture that is new or has
// been written since its last snapshot. The snapshot is a GPU-side CopyResource into a staging
// texture, which does NOT stall the frame; the staging textures are Mapped and written out at
// Present, when the GPU is done with them anyway. Each draw records "ptr#version", so no draw can be
// handed content from an upload that happened after it.
struct TexVer {
    ID3D11Resource*  res;      // identity: the pointer the draw record prints
    ID3D11Texture2D* tex;      // the same object, held with a reference
    unsigned ver;
    unsigned lastFrame;        // last CAPTURED frame that sampled it, for the per-frame count
    bool snapped;
    bool dirty;
};
// Sized for a LONG burst, not a single frame. The table lives for the whole burst -- that is what
// makes a texture re-dump only when it is rewritten -- so it accumulates every distinct texture
// object the game touches over the whole segment, not the ~230 a single frame binds. It also holds a
// reference to each, which is what keeps the pointer a stable identity: without it the game could
// free a texture and hand the same address to a different one.
static TexVer g_texVer[4096];
static int g_nTexVer = 0;

struct TexSnap { ID3D11Texture2D* stg; ID3D11Resource* res; unsigned ver; };
static TexSnap g_texSnap[768];
static int g_nTexSnap = 0;
static unsigned g_texWrites = 0, g_texRewrites = 0;
static int g_frameTex = 0;     // distinct textures sampled by the frame being captured RIGHT NOW
static ID3D11Device* g_texDev = nullptr;

static bool isDumpableTex(DXGI_FORMAT f);
static UINT texBytesPerPixel(DXGI_FORMAT f);

static void markTexDirty(ID3D11Resource* r) {
    if (!r) return;
    D3D11_RESOURCE_DIMENSION dim = D3D11_RESOURCE_DIMENSION_UNKNOWN;
    r->GetType(&dim);
    if (dim != D3D11_RESOURCE_DIMENSION_TEXTURE2D) return;
    ++g_texWrites;
    for (int i = 0; i < g_nTexVer; ++i) {
        if (g_texVer[i].res != r) continue;
        // A rewrite of a texture some draw has ALREADY sampled is the case that used to corrupt the
        // capture silently. Count it so the log says whether this frame was affected at all.
        if (g_texVer[i].snapped && !g_texVer[i].dirty) ++g_texRewrites;
        g_texVer[i].dirty = true;
        return;
    }
}

// Returns the content generation this draw is sampling. Snapshots first, if needed.
static unsigned noteTexVersioned(ID3D11DeviceContext* c, ID3D11Resource* r) {
    if (!r) return 0;
    int slot = -1;
    for (int i = 0; i < g_nTexVer; ++i) if (g_texVer[i].res == r) { slot = i; break; }
    if (slot < 0) {
        if (g_nTexVer >= 4096) {
            static bool warned = false;
            if (!warned) { warned = true; logf("[tex] ⚠ version table FULL (4096) -- textures dropped. "
                                               "Shorten the burst; a long one accumulates every texture the game touches."); }
            return 0;
        }
        ID3D11Texture2D* t = nullptr;
        if (FAILED(r->QueryInterface(__uuidof(ID3D11Texture2D), (void**)&t)) || !t) return 0;
        slot = g_nTexVer++;
        g_texVer[slot].res = r;          // the QI reference on `tex` keeps this pointer valid
        g_texVer[slot].tex = t;
        g_texVer[slot].ver = 0;
        g_texVer[slot].lastFrame = 0;
        g_texVer[slot].snapped = false;
        g_texVer[slot].dirty = true;     // never snapshotted, so it needs one
    }
    // The in-match gate counts textures THIS FRAME sampled. The table itself is session-wide now,
    // so its size is not that number and using it would let any frame past the gate.
    if (g_texVer[slot].lastFrame != g_frame) { g_texVer[slot].lastFrame = g_frame; ++g_frameTex; }
    if (!g_texVer[slot].dirty) return g_texVer[slot].ver;
    if (g_texVer[slot].snapped) ++g_texVer[slot].ver;   // a new generation of this texture's content

    ID3D11Texture2D* t = g_texVer[slot].tex;
    D3D11_TEXTURE2D_DESC d = {};
    t->GetDesc(&d);
    if (isDumpableTex(d.Format) && d.Width <= 4096 && d.Height <= 4096 && d.SampleDesc.Count == 1
        && g_nTexSnap < 768) {
        if (!g_texDev) c->GetDevice(&g_texDev);
        D3D11_TEXTURE2D_DESC sd = d;
        sd.Usage = D3D11_USAGE_STAGING;
        sd.BindFlags = 0;
        sd.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        sd.MiscFlags = 0;
        ID3D11Texture2D* stg = nullptr;
        if (g_texDev && SUCCEEDED(g_texDev->CreateTexture2D(&sd, nullptr, &stg)) && stg) {
            // GPU-side copy only. Mapping here would sync the CPU to the GPU 700 times a frame.
            c->CopyResource(stg, t);
            g_texSnap[g_nTexSnap].stg = stg;
            g_texSnap[g_nTexSnap].res = r;
            g_texSnap[g_nTexSnap].ver = g_texVer[slot].ver;
            ++g_nTexSnap;
        }
    } else if (g_nTexSnap >= 768) {
        static bool warned = false;
        if (!warned) { warned = true; logf("[tex] ⚠ snapshot queue FULL (768) -- content dropped"); }
    }
    g_texVer[slot].snapped = true;
    g_texVer[slot].dirty = false;
    return g_texVer[slot].ver;
}

// ⚠ CRASH FIX 2026-09-01: the first version assumed 4 bytes/pixel and walked y to Height. BC7/BC1
// are BLOCK compressed -- the mapped staging data has ceil(Height/4) rows and a RowPitch far smaller
// than Width*4 -- so that read ran ~4x past the end of the allocation and took the game down.
// Dump only uncompressed formats; never guess a pixel layout.
// ⚠⚠ 2026-09-01, mvc2-sprite-render-expert: an earlier comment here claimed "the sprite atlases we
// need are UNCOMPRESSED R8G8B8A8". THAT PREMISE WAS INVERTED. The 256x256 RGBA pages are the 3D
// STAGE. The CHARACTERS go through the palette path: t0 is a DXGI_FORMAT_R8_UNORM (61) index tile and
// t1 is the 256x1 palette. Of 189 textures bound in frame 4828, 144 are fmt 61 -- and the old filter
// skipped every one, so the capture contained ZERO character pixels. It also skipped the 256x128 HUD
// bank, which per mvc-hud-list0b-live-re cannot be obtained offline at all.
static bool isDumpableTex(DXGI_FORMAT f) {
    return f == DXGI_FORMAT_R8G8B8A8_UNORM || f == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB ||
           f == DXGI_FORMAT_B8G8R8A8_UNORM || f == DXGI_FORMAT_B8G8R8X8_UNORM ||
           f == DXGI_FORMAT_R8_UNORM;      // <- the character index tiles
}
static bool isRGBA32(DXGI_FORMAT f) {
    return f == DXGI_FORMAT_R8G8B8A8_UNORM || f == DXGI_FORMAT_R8G8B8A8_UNORM_SRGB ||
           f == DXGI_FORMAT_B8G8R8A8_UNORM || f == DXGI_FORMAT_B8G8R8X8_UNORM;
}
static UINT texBytesPerPixel(DXGI_FORMAT f) { return f == DXGI_FORMAT_R8_UNORM ? 1u : 4u; }

static void releaseCapTex() {
    for (int i = 0; i < g_nTexSnap; ++i) if (g_texSnap[i].stg) g_texSnap[i].stg->Release();
    g_nTexSnap = 0;
    for (int i = 0; i < g_nTexVer; ++i) if (g_texVer[i].tex) g_texVer[i].tex->Release();
    g_nTexVer = 0;
    g_texWrites = g_texRewrites = 0;
}

// End of a captured FRAME.
// ⚠⚠ THE VERSION TABLE SURVIVES THE WHOLE SESSION, not just a burst. It is what makes a texture get
// written to disk ONCE per content generation instead of once per captured frame, and that is not a
// nicety: a match frame samples ~230 textures, so re-dumping them every capture put tens of
// thousands of small files in one directory, each one a fresh create + antivirus scan on the RENDER
// THREAD. That is what degraded a 60 fps game to about 2 fps over the course of a run -- the cost
// grew with the number of files already there, which is why it got worse the longer it ran.
// Holding a reference to each texture is also what keeps its pointer a stable identity across
// frames: without it the game could free one and hand the same address to a different texture.
// ⚠⚠⚠ RE-SNAPSHOT EVERY TEXTURE EVERY CAPTURED FRAME. DO NOT "OPTIMISE" THIS AWAY AGAIN.
// The dirty flag is set from Map/Unmap and UpdateSubresource, and those are NOT the only ways this
// game writes a texture -- CopyResource, CopySubresourceRegion and a deferred context all bypass
// them. Trusting the flag ACROSS frames produced exactly 303 distinct sprite tiles for a 246-frame
// animation that needs thousands: the game cycles a pool of texture objects, we snapshotted each one
// the first time we saw it and never again, and every later frame was served a tile from whenever
// that pointer was first captured. Frame 0 was perfect and every frame after it was sprite shards.
// The measurement that catches it: consecutive frames sharing ~0% of their tile CONTENT while the
// distinct-tile count equals the size of the game's texture pool.
// Cost is bounded because the WRITE is deduplicated by content hash below -- re-snapshotting is a
// GPU-side copy, and only genuinely new pixels ever reach the disk.
// Content hashes already written this session. A capture of a real match sees a few thousand
// distinct sprite tiles; 1<<16 slots keeps the table sparse enough for linear probing to be free.
static uint64_t g_texHash[1 << 16];
static int g_nTexHash = 0;

/** true if these pixels have not been written before (and records them). */
static bool rememberTexHash(uint32_t h1, uint32_t h2) {
    const uint64_t key = ((uint64_t)h1 << 32) | h2;
    size_t i = (size_t)(key * 0x9E3779B97F4A7C15ull >> 48) & 0xFFFF;
    for (size_t probe = 0; probe < (1 << 16); ++probe) {
        uint64_t& slot = g_texHash[(i + probe) & 0xFFFF];
        if (slot == key) return false;
        if (slot == 0) { slot = key; ++g_nTexHash; return true; }
    }
    return true;   // table full: write it rather than lose it
}

// The frame's "which content did each binding point at" map, built as JSON while the frame's
// snapshots are written and flushed beside the inventory.
static char* g_texMap = nullptr;
static size_t g_texMapLen = 0, g_texMapCap = 0;

static void mapAppend(const char* fmt, ...) {
    char item[256];
    va_list ap; va_start(ap, fmt);
    int n = _vsnprintf_s(item, sizeof(item), _TRUNCATE, fmt, ap);
    va_end(ap);
    if (n <= 0) return;
    size_t need = g_texMapLen + (size_t)n + 2;
    if (need > g_texMapCap) {
        size_t cap = g_texMapCap ? g_texMapCap * 2 : (1 << 16);
        while (cap < need) cap *= 2;
        char* grown = (char*)realloc(g_texMap, cap);
        if (!grown) return;
        g_texMap = grown; g_texMapCap = cap;
    }
    if (g_texMapLen) g_texMap[g_texMapLen++] = ',';
    memcpy(g_texMap + g_texMapLen, item, (size_t)n);
    g_texMapLen += (size_t)n;
}

static void markAllTexDirty() {
    for (int i = 0; i < g_nTexVer; ++i) g_texVer[i].dirty = true;
}

static void endFrameTex() {
    for (int i = 0; i < g_nTexSnap; ++i) if (g_texSnap[i].stg) g_texSnap[i].stg->Release();
    g_nTexSnap = 0;
}

static void dumpCapturedTextures(ID3D11Device* dev, ID3D11DeviceContext* ctx, unsigned frame) {
    // Quiet unless something is actually being written: at one line per frame this is the log during
    // a 1200-frame burst.
    if (g_nTexSnap && !g_burstLeft)
        logf("[tex] frame %u: %d sampled, %d snapshots, %d distinct bitmaps on disk",
             frame, g_frameTex, g_nTexSnap, g_nTexHash);
    for (int i = 0; i < g_nTexSnap; ++i) {
        ID3D11Texture2D* stg = g_texSnap[i].stg;
        if (!stg) continue;
        D3D11_TEXTURE2D_DESC d = {};
        stg->GetDesc(&d);
        D3D11_MAPPED_SUBRESOURCE m = {};
        if (SUCCEEDED(ctx->Map(stg, 0, D3D11_MAP_READ, 0, &m))) {
            // Rows are repacked tightly at Width*bpp; RowPitch is the SOURCE stride and is >= that,
            // so this never over-reads. The decoder needs only w/h/format. Repacking happens here
            // because the mapped pointer is only valid until Unmap; the WRITE happens off-thread.
            const size_t rowBytes = (size_t)d.Width * texBytesPerPixel(d.Format);
            const size_t nbytes = rowBytes * d.Height ? rowBytes * d.Height : 1;
            uint8_t* buf = (uint8_t*)malloc(nbytes);
            if (buf) {
                for (UINT y = 0; y < d.Height; ++y)
                    memcpy(buf + (size_t)y * rowBytes,
                           (const uint8_t*)m.pData + (size_t)y * m.RowPitch, rowBytes);
                // ⚠ THE FILE IS NAMED BY ITS CONTENT, NOT BY WHO OR WHEN.
                // Re-snapshotting every frame would otherwise mean re-writing every texture every
                // frame. Naming by hash means identical pixels are written exactly once no matter
                // how many frames sample them, and the per-frame map below says which content each
                // draw's binding pointed at. A pointer is not an identity; content is.
                uint32_t h1 = fnv1a(buf, nbytes);
                uint32_t h2 = fnv1a(buf, nbytes < 4096 ? nbytes : 4096) ^ (uint32_t)nbytes;
                char path[MAX_PATH];
                _snprintf_s(path, sizeof(path), _TRUNCATE, "%s\\tex_%ux%u_f%d_%08X%08X.bin",
                            g_dir, d.Width, d.Height, (int)d.Format, h1, h2);
                if (rememberTexHash(h1, h2)) {
                    writeAsync(path, buf, nbytes);      // first sighting of these pixels
                } else {
                    free(buf);                          // already on disk under this name
                }
                mapAppend("\"%p#%u\":\"%ux%u_f%d_%08X%08X\"", (void*)g_texSnap[i].res,
                          g_texSnap[i].ver, d.Width, d.Height, (int)d.Format, h1, h2);
            }
            ctx->Unmap(stg, 0);
        }
    }
    if (g_texMapLen) {
        char path[MAX_PATH];
        _snprintf_s(path, sizeof(path), _TRUNCATE, "%s\\texmap_%u.json", g_dir, frame);
        uint8_t* body = (uint8_t*)malloc(g_texMapLen + 3);
        if (body) {
            body[0] = '{';
            memcpy(body + 1, g_texMap, g_texMapLen);
            body[g_texMapLen + 1] = '}';
            writeAsync(path, body, g_texMapLen + 2);
        }
        g_texMapLen = 0;
    }
    endFrameTex();
}


// -- BUFFER CAPTURE ------------------------------------------------------------------------------
// All ~650 sprite draws in a frame share ONE 2 MiB dynamic vertex buffer, so we do NOT copy per
// draw. Each draw records its vb pointer + stride + voff + start + count; we snapshot the WHOLE
// buffer once at end-of-frame and slice it offline. One 2 MiB copy per frame instead of 650.
// Dynamic buffers cannot be Mapped for READ, so each is copied into a STAGING buffer first.
// We also grab the index buffer and VS constant buffer 0 -- the latter is where a projection matrix
// would live, which is what tells us whether vertex positions are already in clip space.
struct CapBuf { ID3D11Buffer* buf; const char* tag; UINT used; };
static CapBuf g_capBufs[12];
static int    g_nCapBufs = 0;
static volatile LONG g_bufDumps = 0;
static LONG MAX_BUF_DUMPS = 6;   // per BURST, not per session; see D3DCAP_BURST

// `used` is the highest byte any draw this frame reads from the buffer. Dumping only that prefix is
// what keeps a burst on disk: the vertex buffer is 2 MiB and a frame touches ~220 KB of it.
static void noteBuf(ID3D11Buffer* b, const char* tag, UINT usedEnd) {
    if (!b || g_nCapBufs >= 12) return;
    for (int i = 0; i < g_nCapBufs; ++i)
        if (g_capBufs[i].buf == b) {
            if (usedEnd > g_capBufs[i].used) g_capBufs[i].used = usedEnd;
            return;
        }
    b->AddRef();
    g_capBufs[g_nCapBufs].buf = b;
    g_capBufs[g_nCapBufs].tag = tag;
    g_capBufs[g_nCapBufs].used = usedEnd;
    ++g_nCapBufs;
}

static void releaseCapBufs() {
    for (int i = 0; i < g_nCapBufs; ++i) if (g_capBufs[i].buf) g_capBufs[i].buf->Release();
    g_nCapBufs = 0;
}

static void dumpCapturedBuffers(IDXGISwapChain* sc, unsigned frame) {
    // ⚠ Every early return MUST release the textures noted this frame. They each hold a D3D
    // reference; leaking them once per frame exhausts the device and crashes the game (observed on
    // character select, which notes far more textures than a match does).
    if (!g_nCapBufs) { endFrameTex(); return; }
    if (InterlockedIncrement(&g_bufDumps) > MAX_BUF_DUMPS) {
        static bool warned = false;
        if (!warned) { warned = true;
            logf("[buf] ⚠ dump budget %ld exhausted -- later frames get an inventory with NO VERTEX "
                 "DATA and the packer will reject them", MAX_BUF_DUMPS); }
        releaseCapBufs(); endFrameTex(); return;
    }

    ID3D11Device* dev = nullptr;
    ID3D11DeviceContext* ctx = nullptr;
    if (SUCCEEDED(sc->GetDevice(__uuidof(ID3D11Device), (void**)&dev)) && dev)
        dev->GetImmediateContext(&ctx);

    if (dev && ctx) {
        for (int i = 0; i < g_nCapBufs; ++i) {
            ID3D11Buffer* b = g_capBufs[i].buf;
            if (!b) continue;
            D3D11_BUFFER_DESC bd = {};
            b->GetDesc(&bd);

            D3D11_BUFFER_DESC sdsc = bd;
            sdsc.Usage = D3D11_USAGE_STAGING;
            sdsc.BindFlags = 0;
            sdsc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
            sdsc.MiscFlags = 0;
            sdsc.StructureByteStride = 0;

            ID3D11Buffer* stg = nullptr;
            if (FAILED(dev->CreateBuffer(&sdsc, nullptr, &stg)) || !stg) {
                logf("[buf] staging create failed for %p (%u bytes)", (void*)b, bd.ByteWidth);
                continue;
            }
            ctx->CopyResource(stg, b);
            D3D11_MAPPED_SUBRESOURCE m = {};
            if (SUCCEEDED(ctx->Map(stg, 0, D3D11_MAP_READ, 0, &m))) {
                // filename carries the buffer POINTER so the offline decoder can match it to the
                // "vb"/"ib"/"cb0" field of each draw record.
                char path[MAX_PATH];
                _snprintf_s(path, sizeof(path), _TRUNCATE, "%s\\buf_%u_%s_%p.bin",
                            g_dir, frame, g_capBufs[i].tag, (void*)b);
                UINT n = g_capBufs[i].used ? g_capBufs[i].used : bd.ByteWidth;
                if (n > bd.ByteWidth) n = bd.ByteWidth;
                // Only the prefix any draw actually reads. The offline tools index this buffer by
                // absolute byte offset, so a PREFIX is safe where a slice would not be.
                writeAsyncCopy(path, m.pData, n);
                ctx->Unmap(stg, 0);
            } else {
                logf("[buf] Map failed for %p", (void*)b);
            }
            stg->Release();
        }
        dumpCapturedTextures(dev, ctx, frame);
    }
    if (ctx) ctx->Release();
    if (dev) dev->Release();
    releaseCapBufs();
}

// ── FRAMEBUFFER CAPTURE ──────────────────────────────────────────────────────────────────────────
// Uses only the swapchain (whose Present hook is proven stable). Grabs the finished frame BEFORE
// Present, since SwapEffect=DISCARD leaves the backbuffer undefined afterwards.
static void writeBMP(const char* path, const uint8_t* src, UINT w, UINT h, UINT pitch, bool bgraAlready) {
    FILE* f = nullptr;
    if (fopen_s(&f, path, "wb") != 0 || !f) return;
    const UINT rowBytes = w * 4;
    BITMAPFILEHEADER fh = {};
    BITMAPINFOHEADER ih = {};
    fh.bfType = 0x4D42;
    fh.bfOffBits = sizeof(fh) + sizeof(ih);
    fh.bfSize = fh.bfOffBits + rowBytes * h;
    ih.biSize = sizeof(ih);
    ih.biWidth = (LONG)w;
    ih.biHeight = -(LONG)h;      // negative = top-down, matching D3D row order
    ih.biPlanes = 1;
    ih.biBitCount = 32;
    ih.biCompression = BI_RGB;
    ih.biSizeImage = rowBytes * h;
    fwrite(&fh, sizeof(fh), 1, f);
    fwrite(&ih, sizeof(ih), 1, f);

    uint8_t* row = (uint8_t*)malloc(rowBytes);
    if (row) {
        for (UINT y = 0; y < h; ++y) {
            const uint8_t* s = src + (size_t)y * pitch;
            if (bgraAlready) {
                memcpy(row, s, rowBytes);
            } else {
                // backbuffer is R8G8B8A8; BMP wants B,G,R,A
                for (UINT x = 0; x < w; ++x) {
                    row[x * 4 + 0] = s[x * 4 + 2];
                    row[x * 4 + 1] = s[x * 4 + 1];
                    row[x * 4 + 2] = s[x * 4 + 0];
                    row[x * 4 + 3] = s[x * 4 + 3];
                }
            }
            fwrite(row, rowBytes, 1, f);
        }
        free(row);
    }
    fclose(f);
}

static void captureBackbuffer(IDXGISwapChain* sc, unsigned frame) {
    ID3D11Texture2D* back = nullptr;
    if (FAILED(sc->GetBuffer(0, __uuidof(ID3D11Texture2D), (void**)&back)) || !back) {
        logf("[shot] GetBuffer failed"); return;
    }
    D3D11_TEXTURE2D_DESC d = {};
    back->GetDesc(&d);

    ID3D11Device* dev = nullptr;
    back->GetDevice(&dev);
    ID3D11DeviceContext* ctx = nullptr;
    if (dev) dev->GetImmediateContext(&ctx);

    if (dev && ctx && d.SampleDesc.Count == 1) {
        D3D11_TEXTURE2D_DESC sd = d;
        sd.Usage = D3D11_USAGE_STAGING;
        sd.BindFlags = 0;
        sd.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        sd.MiscFlags = 0;
        ID3D11Texture2D* stg = nullptr;
        HRESULT hr = dev->CreateTexture2D(&sd, nullptr, &stg);
        if (SUCCEEDED(hr) && stg) {
            ctx->CopyResource(stg, back);
            D3D11_MAPPED_SUBRESOURCE m = {};
            if (SUCCEEDED(ctx->Map(stg, 0, D3D11_MAP_READ, 0, &m))) {
                char path[MAX_PATH];
                _snprintf_s(path, sizeof(path), _TRUNCATE, "%s\\shot_%u.bmp", g_dir, frame);
                bool bgra = (d.Format == DXGI_FORMAT_B8G8R8A8_UNORM ||
                             d.Format == DXGI_FORMAT_B8G8R8X8_UNORM);
                writeBMP(path, (const uint8_t*)m.pData, d.Width, d.Height, m.RowPitch, bgra);
                ctx->Unmap(stg, 0);
                logf("[shot] frame %u -> %s (%ux%u fmt=%d)", frame, path, d.Width, d.Height, (int)d.Format);
            } else {
                logf("[shot] Map failed");
            }
            stg->Release();
        } else {
            logf("[shot] CreateTexture2D(STAGING) failed hr=0x%08lX", (unsigned long)hr);
        }
    } else {
        logf("[shot] unsupported: dev=%p ctx=%p samples=%u", (void*)dev, (void*)ctx, d.SampleDesc.Count);
    }
    if (ctx) ctx->Release();
    if (dev) dev->Release();
    back->Release();
}


// -- SCENE RENDER TARGET SNAPSHOT ----------------------------------------------------------------
// The sprite pass renders into a 2048x1024 offscreen RT (viewport 384,32,1280,960) and only then runs
// a bloom/SMAA chain down to the backbuffer. Diffing a replay against the BACKBUFFER would only prove
// that bloom exists. The scene RT is bound for the whole sprite pass and never rebound in the frame,
// so it can be snapshotted at Present exactly like the backbuffer -- no pass-boundary hook needed.
static ID3D11Resource* g_rtSeen[16] = {};
static int g_rtCount[16] = {};
static int g_nRtSeen = 0;

static void noteRT(ID3D11Resource* r) {
    if (!r) return;
    for (int i = 0; i < g_nRtSeen; ++i) if (g_rtSeen[i] == r) { g_rtCount[i]++; return; }
    if (g_nRtSeen < 16) { g_rtSeen[g_nRtSeen] = r; g_rtCount[g_nRtSeen] = 1; g_nRtSeen++; }
}

static void captureSceneRT(ID3D11Device* dev, ID3D11DeviceContext* ctx, unsigned frame) {
    int best = -1;
    for (int i = 0; i < g_nRtSeen; ++i) if (best < 0 || g_rtCount[i] > g_rtCount[best]) best = i;
    if (best < 0 || g_rtCount[best] < 100) { g_nRtSeen = 0; return; }

    ID3D11Texture2D* t = nullptr;
    if (SUCCEEDED(g_rtSeen[best]->QueryInterface(__uuidof(ID3D11Texture2D), (void**)&t)) && t) {
        D3D11_TEXTURE2D_DESC d = {};
        t->GetDesc(&d);
        if (d.SampleDesc.Count == 1 && isRGBA32(d.Format)) {
            D3D11_TEXTURE2D_DESC sd = d;
            sd.Usage = D3D11_USAGE_STAGING; sd.BindFlags = 0;
            sd.CPUAccessFlags = D3D11_CPU_ACCESS_READ; sd.MiscFlags = 0;
            ID3D11Texture2D* stg = nullptr;
            if (SUCCEEDED(dev->CreateTexture2D(&sd, nullptr, &stg)) && stg) {
                ctx->CopyResource(stg, t);
                D3D11_MAPPED_SUBRESOURCE m = {};
                if (SUCCEEDED(ctx->Map(stg, 0, D3D11_MAP_READ, 0, &m))) {
                    char path[MAX_PATH];
                    _snprintf_s(path, sizeof(path), _TRUNCATE, "%s\\scene_%u_%ux%u_f%d.bmp",
                                g_dir, frame, d.Width, d.Height, (int)d.Format);
                    bool bgra = (d.Format == DXGI_FORMAT_B8G8R8A8_UNORM ||
                                 d.Format == DXGI_FORMAT_B8G8R8X8_UNORM);
                    writeBMP(path, (const uint8_t*)m.pData, d.Width, d.Height, m.RowPitch, bgra);
                    ctx->Unmap(stg, 0);
                    logf("[scene] RT %ux%u fmt=%d (%d draws) -> %s",
                         d.Width, d.Height, (int)d.Format, g_rtCount[best], path);
                }
                stg->Release();
            }
        }
        t->Release();
    }
    g_nRtSeen = 0;
}

// ── probes (read-only, SEH-guarded) ──────────────────────────────────────────────────────────────
static void probeOnce(IDXGISwapChain* sc) {
    if (InterlockedExchange(&pProbed, 1)) return;
    uintptr_t r = 0;
    if (!safeRead((const void*)RR_RVA(0x142EBD8F0ULL), &r, sizeof(r)) || !r) {
        logf("[probe1] renderer pointer unreadable (imgBase=%p)", (void*)g_imgBase); return;
    }
    g_renderer = r;
    void* ctx = nullptr; void* dev = nullptr; unsigned nd = 0; unsigned char gA = 0, gB = 0;
    safeRead((const void*)(r + 0xC0), &ctx, sizeof(ctx));
    safeRead((const void*)(r + 0xB8), &dev, sizeof(dev));
    safeRead((const void*)(r + 0x892EF8), &nd, sizeof(nd));
    safeRead((const void*)(r + 0x38), &gA, 1);
    safeRead((const void*)(r + 0x43), &gB, 1);
    logf("[probe1] renderer=%p ctx(+0xC0)=%p dev(+0xB8)=%p displays=%u gateA=%u gateB=%u",
         (void*)r, ctx, dev, nd, gA, gB);
    if (ctx) installDrawHooks((ID3D11DeviceContext*)ctx);
}

static void probeSample() {
    if (!g_renderer) return;
    unsigned char gA = 0, gB = 0;
    if (safeRead((const void*)(g_renderer + 0x38), &gA, 1) && gA) InterlockedIncrement(&pGateA);
    if (safeRead((const void*)(g_renderer + 0x43), &gB, 1) && gB) InterlockedIncrement(&pGateB);
    uintptr_t q = 0;
    if (safeRead((const void*)RR_RVA(0x142EF0AB0ULL), &q, sizeof(q)) && q) {
        unsigned bytes = 0;
        if (safeRead((const void*)(q + 0x1E0080), &bytes, sizeof(bytes))) {
            if (bytes) InterlockedIncrement(&pQnz);
            if ((LONG)bytes > pQmax) pQmax = (LONG)bytes;
        }
    }
    InterlockedIncrement(&pSamples);
}

// Open the inventory for one frame. Both the ARM path and the burst CONTINUATION path go through
// here, because when they were two copies they drifted and the burst silently stopped continuing.
static bool openFrame(unsigned frame) {
    char path[MAX_PATH];
    _snprintf_s(path, sizeof(path), _TRUNCATE, "%s\\frame_%u.ndjson", g_dir, frame);
    if (fopen_s(&g_out, path, "wb") != 0 || !g_out) {
        logf("[cap] could not open %s", path);
        return false;
    }
    // ⚠ A frame's inventory is ~1 MB written as thousands of small fprintf calls. Without a big
    // buffer that is thousands of write syscalls per frame ON THE RENDER THREAD, which is felt
    // directly as frame time during a burst.
    setvbuf(g_out, nullptr, _IOFBF, 1 << 20);
    g_drawIdx = 0;
    g_capturing = true;
    g_ncbWritten = 0;
    g_nRtSeen = 0;
    g_frameTex = 0;
    markAllTexDirty();
    return true;
}

// ── Present ──────────────────────────────────────────────────────────────────────────────────────
static HRESULT STDMETHODCALLTYPE hkPresent(IDXGISwapChain* sc, UINT si, UINT flags) {
    probeOnce(sc);

    // The draws for frame N happen between Present(N-1) and Present(N), and the backbuffer at
    // Present(N) holds frame N -- so closing the inventory and grabbing the shot here makes the
    // .ndjson and the .bmp describe the SAME frame.
    if (g_capturing) {
        // The heavy ground-truth grabs are worth one frame of a burst, not every frame: the scene RT
        // is an 8 MB BMP and the backbuffer another full copy. One is enough to prove the sequence
        // renders correctly, and the rest of the burst is what makes it a PLAYBACK.
        // ⚠ GROUND TRUTH AT THREE POINTS OF A BURST, NOT ONE.
        // With only the first frame's scene RT there is no way to tell a capture that goes stale
        // after frame 1 from one that does not -- and that is exactly the failure we then spent a
        // session chasing. Three 8 MB writes, off the frame path already, and any later drift shows
        // up as a number instead of as "the characters look wrong".
        const bool firstOfBurst = (g_frame == g_burstFirst);
        const bool midOfBurst   = (g_burst > 2 && g_burstGot == g_burst / 2);
        const bool lastOfBurst  = (g_burst > 2 && g_burstLeft == 0 && g_burstGot + 1 >= g_burst);
        const bool wantTruth    = firstOfBurst || midOfBurst || lastOfBurst;
        if (wantTruth) captureBackbuffer(sc, g_frame);
        g_capturing = false;
        if (g_out) { fclose(g_out); g_out = nullptr; }
        // Only spend a dump slot on a GAMEPLAY frame. Measured: menus/char-select run 13-266 draws
        // while in-match frames run ~650-1300, so this threshold cleanly separates them and stops the
        // 3-dump budget being burnt on UI frames that contain no fighter sprites.
        // Spend a dump slot only on a REAL MATCH frame. Draw count alone cannot tell gameplay from
        // character select (both render ~1200 draws into the same 2048x1024 offscreen RT), but the
        // distinct-texture count can: measured, menus 9-30, char select 21-24, in-match 96-298.
        // g_nTexVer IS that count -- one entry per DISTINCT texture object the frame's draws
        // sampled, independent of how many content generations each of them went through -- so the
        // in-process gate still matches the offline one exactly.
        if (g_drawIdx >= 300 && g_frameTex >= 50) {
            // The SCENE RT is the diff target. The backbuffer has been through a 9-pass bloom/SMAA
            // chain, so diffing against it would only prove that bloom exists. The scene RT is bound
            // for the whole sprite pass and never rebound in the frame, so Present is a valid
            // snapshot point -- no pass-boundary hook needed.
            if (wantTruth) {
                ID3D11Device* sdev = nullptr;
                ID3D11DeviceContext* sctx = nullptr;
                if (SUCCEEDED(sc->GetDevice(__uuidof(ID3D11Device), (void**)&sdev)) && sdev) {
                    sdev->GetImmediateContext(&sctx);
                    if (sctx) { captureSceneRT(sdev, sctx, g_frame); sctx->Release(); }
                    sdev->Release();
                }
            }
            dumpCapturedBuffers(sc, g_frame);
            ++g_burstGot;
            if (g_burst > 1 && g_burstGot >= g_burst) {
                g_burstLeft = 0;
                InterlockedExchange(&g_burstDone, 1);
                logf("[burst] COMPLETE: %u consecutive frames from %u", g_burstGot, g_burstFirst);
            }
        } else {
            releaseCapBufs();
            // A frame that fails the in-match gate ends the burst: whatever we were recording is not
            // a match any more, and half a burst of menu frames is not a playback. The arm thread
            // keeps trying, so an arm that lands on the title screen costs one wasted frame, not the
            // whole run.
            if (g_burstLeft || g_burstGot) {
                logf("[burst] abandoned at %u frame(s) -- frame %u is not a match (%u draws, %d textures)",
                     g_burstGot, g_frame, g_drawIdx, g_frameTex);
            }
            g_burstLeft = 0;
            g_burstGot = 0;
            releaseCapTex();
            g_nRtSeen = 0;
        }
        // ⚠ logf OPENS, WRITES AND CLOSES THE LOG FILE. That is one more filesystem round trip on
        // the render thread, and a burst would pay it 1200 times. Report progress once a second of
        // game time instead of once a frame.
        if (!g_burstLeft) {
            logf("[cap] frame %u inventory: %u draws", g_frame, g_drawIdx);
        if (g_nwsite) {
            logf("[emit] %d distinct geometry writers seen so far:", g_nwsite);
            for (int i = 0; i < g_nwsite; ++i)
                logf("[emit]   x%-6u flags=0x%X  0x%llX <- 0x%llX <- 0x%llX <- 0x%llX",
                     g_wsite[i].hits, g_wsite[i].kind,
                     (unsigned long long)g_wsite[i].ret[0], (unsigned long long)g_wsite[i].ret[1],
                     (unsigned long long)g_wsite[i].ret[2], (unsigned long long)g_wsite[i].ret[3]);
        }
        } else if ((g_burstGot % 60) == 0) {
            logf("[burst] %u/%u frames (%u draws, %d textures, %lld MB queued to disk)",
                 g_burstGot, g_burst, g_drawIdx, g_frameTex, (long long)(g_wqueued >> 20));
        }

        // Continue the burst IN THIS Present. The arm path below is an `else if`, so leaving it to
        // re-arm would record every OTHER frame -- and a playback of every other frame is not a
        // playback of the match.
        if (g_burstLeft) {
            --g_burstLeft;
            if (!openFrame(g_frame + 1)) g_burstLeft = 0;
        }
    } else if (InterlockedExchange(&g_armDraws, 0) && !(g_burst > 1 && g_burstDone)) {
        // ⚠⚠ THE BURST COUNTDOWN IS ARMED HERE AND NOWHERE ELSE.
        // An earlier edit put these three lines in the CONTINUATION branch above, inside
        // `if (g_burstLeft)`. That is circular: nothing else ever set g_burstLeft, so it stayed 0,
        // the continuation never ran, and every "burst" frame was actually a fresh once-a-second
        // arm. The capture looked like it was working -- frames kept appearing -- but they were
        // 60 apart at full speed and 2 apart once the game bogged down, and never consecutive.
        if (openFrame(g_frame + 1)) {
            g_burstFirst = g_frame + 1;
            g_burstGot = 0;
            g_burstLeft = g_burst > 1 ? g_burst - 1 : 0;
            // ⚠ THE DUMP BUDGET IS PER BURST, NOT PER SESSION.
            // It was a running total, so once a run had recorded MAX_BUF_DUMPS frames every later
            // frame wrote an inventory with NO VERTEX DATA -- 589 such frames in one run, and the
            // packer rejects every one of them. The budget exists to stop a runaway filling the
            // disk, which is a per-burst concern; reset it whenever a burst starts.
            if (g_burst > 1) InterlockedExchange(&g_bufDumps, 0);
        }
    }

    if ((g_frame % 600) == 0) {
        logf("[diag] frame=%u | DRAWS: DrawIndexed=%ld Draw=%ld DII=%ld DI=%ld",
             g_frame, cDrawIdx, cDraw, cDrawIdxI, cDrawI);
        logf("[diag]   captured at creation: inputLayouts=%ld VS=%ld PS=%ld", cIL, cVS, cPS);
        logf("[diag]   probes: samples=%ld gateA=%ld gateB=%ld nDrawQ nonzero=%ld (max=%ld)",
             pSamples, pGateA, pGateB, pQnz, pQmax);
    }
    g_frame++;
    return oPresent(sc, si, flags);
}

// ── init ─────────────────────────────────────────────────────────────────────────────────────────
// -- INIT: hook D3D11CreateDeviceAndSwapChain, do NOT make our own device ------------------------
// ⚠ 2026-09-01: the previous init created a throwaway D3D11 device + window from DllMain's thread so
// it could read dxgi's shared Present vtable. Combined with injecting the instant the process
// appeared, that CRASHED the game during startup -- heavy D3D/window work while the loader is still
// running is not safe, and neither is LoadLibraryW via CreateRemoteThread at that moment.
//
// Ghidra (FUN_1402B80F0) showed the game resolves D3D11 at RUNTIME: LoadLibraryA("d3d11.dll") then
// create-device through the export. So we wait for d3d11.dll to appear, MinHook the export, and take
// the REAL device/context/swapchain from the creation call itself. That is strictly better:
//   * no device, window or vtable work of our own -> the startup crash goes away
//   * we are installed AT creation, so CreateInputLayout / CreateVertexShader / CreatePixelShader
//     are hooked before the game can create a single one (the coverage problem)
//   * no dummy-vs-real vtable mismatch to reason about
static PFN_Present oPresentReal = nullptr;

typedef HRESULT (WINAPI *PFN_D3D11CreateDeviceAndSwapChain)(
    IDXGIAdapter*, D3D_DRIVER_TYPE, HMODULE, UINT, const D3D_FEATURE_LEVEL*, UINT, UINT,
    const DXGI_SWAP_CHAIN_DESC*, IDXGISwapChain**, ID3D11Device**, D3D_FEATURE_LEVEL*,
    ID3D11DeviceContext**);
static PFN_D3D11CreateDeviceAndSwapChain oCreateDevSwap = nullptr;
static volatile LONG g_installed = 0;

static void installAll(IDXGISwapChain* sc, ID3D11Device* dev, ID3D11DeviceContext* ctx) {
    if (InterlockedExchange(&g_installed, 1)) return;

    if (sc) {
        void** scVt = *(void***)sc;
        DWORD old = 0;
        if (VirtualProtect(&scVt[VT_SC_PRESENT], sizeof(void*), PAGE_EXECUTE_READWRITE, &old)) {
            oPresent = (PFN_Present)scVt[VT_SC_PRESENT];
            scVt[VT_SC_PRESENT] = (void*)&hkPresent;
            VirtualProtect(&scVt[VT_SC_PRESENT], sizeof(void*), old, &old);
            logf("[init] Present hooked=%d (swapchain vtable %p, dxgi .rdata: shared + stable)",
                 (int)(scVt[VT_SC_PRESENT] == (void*)&hkPresent), (void*)scVt);
        }
    }
    if (ctx) installDrawHooks(ctx);
    if (dev) installCreationHooks(dev);
    logf("[init] all hooks installed at device creation -- shader/layout coverage should be complete");
}

static HRESULT WINAPI hkCreateDevSwap(IDXGIAdapter* ad, D3D_DRIVER_TYPE dt, HMODULE sw, UINT flags,
                                      const D3D_FEATURE_LEVEL* fl, UINT nfl, UINT sdk,
                                      const DXGI_SWAP_CHAIN_DESC* scd, IDXGISwapChain** ppSC,
                                      ID3D11Device** ppDev, D3D_FEATURE_LEVEL* pfl,
                                      ID3D11DeviceContext** ppCtx) {
    HRESULT hr = oCreateDevSwap ? oCreateDevSwap(ad, dt, sw, flags, fl, nfl, sdk, scd, ppSC, ppDev, pfl, ppCtx)
                                : E_FAIL;
    if (SUCCEEDED(hr)) {
        IDXGISwapChain* sc = ppSC ? *ppSC : nullptr;
        ID3D11Device* dev = ppDev ? *ppDev : nullptr;
        ID3D11DeviceContext* ctx = ppCtx ? *ppCtx : nullptr;
        logf("[init] game created device=%p ctx=%p swapchain=%p", (void*)dev, (void*)ctx, (void*)sc);
        ID3D11DeviceContext* tmp = nullptr;
        if (!ctx && dev) { dev->GetImmediateContext(&tmp); ctx = tmp; }
        installAll(sc, dev, ctx);
        if (tmp) tmp->Release();
    }
    return hr;
}

static DWORD WINAPI worker(LPVOID) {
    // Wait for the game to load d3d11.dll (its own LoadLibraryA call). No D3D work of our own, so
    // nothing heavy happens while the loader is still busy.
    HMODULE d3d11 = nullptr;
    for (int i = 0; i < 2400 && !d3d11; ++i) {      // up to ~2 minutes
        d3d11 = GetModuleHandleA("d3d11.dll");
        if (!d3d11) Sleep(50);
    }
    if (!d3d11) { logf("[init] d3d11.dll never loaded"); return 1; }

    void* target = (void*)GetProcAddress(d3d11, "D3D11CreateDeviceAndSwapChain");
    if (!target) { logf("[init] D3D11CreateDeviceAndSwapChain not found"); return 1; }

    if (MH_Initialize() != MH_OK) { logf("[init] MH_Initialize failed"); return 1; }
    MH_STATUS a = MH_CreateHook(target, (void*)&hkCreateDevSwap, (void**)&oCreateDevSwap);
    MH_STATUS b = (a == MH_OK) ? MH_EnableHook(target) : a;
    logf("[init] D3D11CreateDeviceAndSwapChain @%p create=%d enable=%d", target, (int)a, (int)b);

    // Fallback: if the device already existed when we attached (late injection), the hook above will
    // never fire. Recover by walking the swapchain the game presents -- but only after giving the
    // creation hook a fair chance, and never by creating a device of our own.
    for (int i = 0; i < 200 && !g_installed; ++i) Sleep(50);
    if (!g_installed) logf("[init] ⚠ creation hook never fired -- injected AFTER device creation. "
                           "Shader/layout coverage will be incomplete; relaunch via collect.ps1.");

    {   // D3DCAP_MANUAL=1: never arm on a timer -- wait for the ARM file (or F9).
        // A capture makes the game crawl, so anything that wants the game at FULL SPEED first (the
        // RNG probe needs 600 sim frames, which is ten seconds at 60 fps and five minutes at 2)
        // has to be able to say WHEN. Without this the only way to get a quiet game was not to
        // inject at all, which meant a second launch.
        char mv[8] = {0};
        if (GetEnvironmentVariableA("D3DCAP_MANUAL", mv, sizeof(mv)) && mv[0] == '1') {
            g_manual = true;
            logf("[init] MANUAL arm: nothing is captured until the ARM file appears");
        }
    }
    {   // D3DCAP_BURST=<n>: record n CONSECUTIVE frames per arm instead of one.
        char env[32] = {0};
        DWORD n = GetEnvironmentVariableA("D3DCAP_BURST", env, sizeof(env));
        if (n && n < sizeof(env)) {
            int v = atoi(env);
            if (v > 1) g_burst = (unsigned)v;
        }
        // Every frame of a burst needs its buffers dumped, so the budget has to cover one whole
        // burst plus the usual singles. Without this the burst silently records draw lists whose
        // vertex data was never written.
        MAX_BUF_DUMPS = (LONG)g_burst + 6;
    }
    // ⚠ A BURST MUST KEEP RE-ARMING UNTIL IT LANDS IN A MATCH.
    // The first version armed once, 3 s after the hooks went in -- which is the Capcom logo. That
    // frame had 0 draws, failed the in-match gate, ended the burst, and with a one-shot budget
    // nothing ever armed again: the run sat there recording nothing while the player waited.
    // Arming is cheap (one frame, and a frame that fails the gate is discarded without a dump), so
    // retry every second until a burst completes.
    const ULONGLONG AUTO_MS = g_burst > 1 ? 1000 : 8000;
    const unsigned  MAX_SHOTS = g_burst > 1 ? 100000 : 60;
    char armPath[MAX_PATH];
    _snprintf_s(armPath, sizeof(armPath), _TRUNCATE, "%s\\ARM", g_dir);
    ULONGLONG last = GetTickCount64();
    unsigned shots = 0;
    if (g_burst > 1)
        logf("[init] ready -- BURST mode: %u consecutive frames per arm, buffer budget %ld frames",
             g_burst, MAX_BUF_DUMPS);
    else
        logf("[init] ready -- capture every %llus (max %u)", AUTO_MS / 1000, MAX_SHOTS);

    for (;;) {
        probeSample();
        const char* why = nullptr;
        if (GetAsyncKeyState(VK_F9) & 0x8000) {
            why = "F9";
            while (GetAsyncKeyState(VK_F9) & 0x8000) Sleep(20);
        } else if (GetFileAttributesA(armPath) != INVALID_FILE_ATTRIBUTES) {
            DeleteFileA(armPath); why = "ARM";
            InterlockedExchange(&g_wantBurst, 1);
        } else if ((!g_manual || g_wantBurst) && GetTickCount64() - last >= AUTO_MS
                   && shots < MAX_SHOTS && !g_burstDone) {
            // ⚠ ONE ARM IS NOT ENOUGH IN MANUAL MODE. The armed frame can easily land on a round
            // banner or a menu, which fails the in-match gate and abandons the burst -- and with
            // nothing on a timer, the run would strand there looking like it was still recording.
            // Once told to burst, keep retrying every second until one completes.
            why = "retry";
        }
        if (why) { last = GetTickCount64(); ++shots; InterlockedExchange(&g_armDraws, 1); }
        Sleep(4);
    }
}

BOOL APIENTRY DllMain(HMODULE hMod, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hMod);
        char tmp[MAX_PATH] = {0};
        GetTempPathA(sizeof(tmp), tmp);
        _snprintf_s(g_dir, sizeof(g_dir), _TRUNCATE, "%srrcap", tmp);
        CreateDirectoryA(g_dir, nullptr);
        InitializeCriticalSection(&g_wcs);
        g_wsem = CreateSemaphoreA(nullptr, 0, LONG_MAX, nullptr);
        CloseHandle(CreateThread(nullptr, 0, writerThread, nullptr, 0, nullptr));
        g_imgBase = (uintptr_t)GetModuleHandleW(nullptr);
        {   // SizeOfImage, so a return address can be range-checked against the game module
            const IMAGE_DOS_HEADER* dh = (const IMAGE_DOS_HEADER*)g_imgBase;
            if (dh && dh->e_magic == IMAGE_DOS_SIGNATURE) {
                const IMAGE_NT_HEADERS* nh = (const IMAGE_NT_HEADERS*)(g_imgBase + dh->e_lfanew);
                if (nh->Signature == IMAGE_NT_SIGNATURE) g_imgSize = nh->OptionalHeader.SizeOfImage;
            }
        }
        logf("[init] d3dcap attached pid=%lu base=%p", GetCurrentProcessId(), (void*)g_imgBase);
        CreateThread(nullptr, 0, worker, nullptr, 0, nullptr);
    }
    return TRUE;
}
