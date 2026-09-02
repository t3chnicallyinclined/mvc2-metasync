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
static void noteBuf(ID3D11Buffer* b, const char* tag);
static unsigned noteTexVersioned(ID3D11DeviceContext* c, ID3D11Resource* r);
static void markTexDirty(ID3D11Resource* r);
static void noteRT(ID3D11Resource* r);
static const char* moduleOf(void* p);

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
    if (r && src) markTexDirty(r);
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
    if (vb) { D3D11_BUFFER_DESC bd = {}; vb->GetDesc(&bd); vbBytes = bd.ByteWidth; noteBuf(vb, "vb"); }
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
    bool snapped;
    bool dirty;
};
static TexVer g_texVer[512];
static int g_nTexVer = 0;

struct TexSnap { ID3D11Texture2D* stg; ID3D11Resource* res; unsigned ver; };
static TexSnap g_texSnap[768];
static int g_nTexSnap = 0;
static unsigned g_texWrites = 0, g_texRewrites = 0;
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
        if (g_nTexVer >= 512) {
            static bool warned = false;
            if (!warned) { warned = true; logf("[tex] ⚠ version table FULL (512) -- textures dropped"); }
            return 0;
        }
        ID3D11Texture2D* t = nullptr;
        if (FAILED(r->QueryInterface(__uuidof(ID3D11Texture2D), (void**)&t)) || !t) return 0;
        slot = g_nTexVer++;
        g_texVer[slot].res = r;          // the QI reference on `tex` keeps this pointer valid
        g_texVer[slot].tex = t;
        g_texVer[slot].ver = 0;
        g_texVer[slot].snapped = false;
        g_texVer[slot].dirty = true;     // never snapshotted, so it needs one
    }
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

static void dumpCapturedTextures(ID3D11Device* dev, ID3D11DeviceContext* ctx, unsigned frame) {
    logf("[tex] %d distinct textures, %u writes seen this frame, %u of them rewrote a texture a draw "
         "had already sampled, %d snapshots to write",
         g_nTexVer, g_texWrites, g_texRewrites, g_nTexSnap);
    for (int i = 0; i < g_nTexSnap; ++i) {
        ID3D11Texture2D* stg = g_texSnap[i].stg;
        if (!stg) continue;
        D3D11_TEXTURE2D_DESC d = {};
        stg->GetDesc(&d);
        D3D11_MAPPED_SUBRESOURCE m = {};
        if (SUCCEEDED(ctx->Map(stg, 0, D3D11_MAP_READ, 0, &m))) {
            char path[MAX_PATH];
            _snprintf_s(path, sizeof(path), _TRUNCATE, "%s\\tex_%u_%ux%u_f%d_%p_v%u.bin",
                        g_dir, frame, d.Width, d.Height, (int)d.Format,
                        (void*)g_texSnap[i].res, g_texSnap[i].ver);
            FILE* f = nullptr;
            if (fopen_s(&f, path, "wb") == 0 && f) {
                // Rows are repacked tightly at Width*bpp; RowPitch is the SOURCE stride and is
                // >= that, so this never over-reads. The decoder needs only w/h/format.
                const size_t rowBytes = (size_t)d.Width * texBytesPerPixel(d.Format);
                for (UINT y = 0; y < d.Height; ++y)
                    fwrite((const uint8_t*)m.pData + (size_t)y * m.RowPitch, 1, rowBytes, f);
                fclose(f);
            }
            ctx->Unmap(stg, 0);
        }
    }
    releaseCapTex();
}


// -- BUFFER CAPTURE ------------------------------------------------------------------------------
// All ~650 sprite draws in a frame share ONE 2 MiB dynamic vertex buffer, so we do NOT copy per
// draw. Each draw records its vb pointer + stride + voff + start + count; we snapshot the WHOLE
// buffer once at end-of-frame and slice it offline. One 2 MiB copy per frame instead of 650.
// Dynamic buffers cannot be Mapped for READ, so each is copied into a STAGING buffer first.
// We also grab the index buffer and VS constant buffer 0 -- the latter is where a projection matrix
// would live, which is what tells us whether vertex positions are already in clip space.
struct CapBuf { ID3D11Buffer* buf; const char* tag; };
static CapBuf g_capBufs[12];
static int    g_nCapBufs = 0;
static volatile LONG g_bufDumps = 0;
static const LONG MAX_BUF_DUMPS = 6;   // 2 MiB a piece -- do not fill the disk

static void noteBuf(ID3D11Buffer* b, const char* tag) {
    if (!b || g_nCapBufs >= 12) return;
    for (int i = 0; i < g_nCapBufs; ++i) if (g_capBufs[i].buf == b) return;
    b->AddRef();
    g_capBufs[g_nCapBufs].buf = b;
    g_capBufs[g_nCapBufs].tag = tag;
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
    if (!g_nCapBufs) { releaseCapTex(); return; }
    if (InterlockedIncrement(&g_bufDumps) > MAX_BUF_DUMPS) { releaseCapBufs(); releaseCapTex(); return; }

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
                FILE* f = nullptr;
                if (fopen_s(&f, path, "wb") == 0 && f) {
                    fwrite(m.pData, 1, bd.ByteWidth, f);
                    fclose(f);
                    logf("[buf] %s %p -> %u bytes", g_capBufs[i].tag, (void*)b, bd.ByteWidth);
                }
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

// ── Present ──────────────────────────────────────────────────────────────────────────────────────
static HRESULT STDMETHODCALLTYPE hkPresent(IDXGISwapChain* sc, UINT si, UINT flags) {
    probeOnce(sc);

    // The draws for frame N happen between Present(N-1) and Present(N), and the backbuffer at
    // Present(N) holds frame N -- so closing the inventory and grabbing the shot here makes the
    // .ndjson and the .bmp describe the SAME frame.
    if (g_capturing) {
        captureBackbuffer(sc, g_frame);
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
        if (g_drawIdx >= 300 && g_nTexVer >= 50) {
            // The SCENE RT is the diff target. The backbuffer has been through a 9-pass bloom/SMAA
            // chain, so diffing against it would only prove that bloom exists. The scene RT is bound
            // for the whole sprite pass and never rebound in the frame, so Present is a valid
            // snapshot point -- no pass-boundary hook needed.
            ID3D11Device* sdev = nullptr;
            ID3D11DeviceContext* sctx = nullptr;
            if (SUCCEEDED(sc->GetDevice(__uuidof(ID3D11Device), (void**)&sdev)) && sdev) {
                sdev->GetImmediateContext(&sctx);
                if (sctx) { captureSceneRT(sdev, sctx, g_frame); sctx->Release(); }
                sdev->Release();
            }
            dumpCapturedBuffers(sc, g_frame);
        } else {
            releaseCapBufs();
            releaseCapTex();
            g_nRtSeen = 0;
        }
        logf("[cap] frame %u inventory: %u draws", g_frame, g_drawIdx);
    } else if (InterlockedExchange(&g_armDraws, 0)) {
        char path[MAX_PATH];
        _snprintf_s(path, sizeof(path), _TRUNCATE, "%s\\frame_%u.ndjson", g_dir, g_frame + 1);
        if (fopen_s(&g_out, path, "w") == 0 && g_out) {
            g_drawIdx = 0; g_capturing = true; g_ncbWritten = 0; g_nRtSeen = 0;
        }
        else logf("[cap] could not open %s", path);
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

    const ULONGLONG AUTO_MS = 8000;
    const unsigned  MAX_SHOTS = 60;
    char armPath[MAX_PATH];
    _snprintf_s(armPath, sizeof(armPath), _TRUNCATE, "%s\\ARM", g_dir);
    ULONGLONG last = GetTickCount64();
    unsigned shots = 0;
    logf("[init] ready -- capture every %llus (max %u)", AUTO_MS / 1000, MAX_SHOTS);

    for (;;) {
        probeSample();
        const char* why = nullptr;
        if (GetAsyncKeyState(VK_F9) & 0x8000) {
            why = "F9";
            while (GetAsyncKeyState(VK_F9) & 0x8000) Sleep(20);
        } else if (GetFileAttributesA(armPath) != INVALID_FILE_ATTRIBUTES) {
            DeleteFileA(armPath); why = "ARM";
        } else if (GetTickCount64() - last >= AUTO_MS && shots < MAX_SHOTS) {
            why = "auto";
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
