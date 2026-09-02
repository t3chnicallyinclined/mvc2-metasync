// RETRO RECEIPTS — PATH B: D3D11 → WebGPU state translation.
//
// This file is the correctness surface of the replayer. Every table below was verified against the
// captured state in frame_4828 by steam-d3d11-capture-expert (2026-09-01); the counts in the
// comments are that frame's measured distribution, kept so a future capture that violates them is
// noticed rather than silently mistranslated.
//
// The whole frame uses only 4 D3D11_BLEND values, 2 comparison funcs, 3 cull modes and 4 distinct
// samplers, so these are exhaustive tables rather than a general translation layer. Anything outside
// them THROWS — a silent substitution here produces an image that is subtly wrong everywhere, which
// is far more expensive to debug than a hard failure at load time.

// ── blend ────────────────────────────────────────────────────────────────────────────────────────
// D3D11_BLEND. Only 1/2/5/6 appear. SRC1_* (16-19) would need the dual-source-blending feature;
// they do not appear and are deliberately absent from this table.
const BLEND_FACTOR = {
    1: 'zero',
    2: 'one',
    3: 'src',                  // SRC_COLOR
    4: 'one-minus-src',
    5: 'src-alpha',
    6: 'one-minus-src-alpha',
    7: 'dst-alpha',
    8: 'one-minus-dst-alpha',
    9: 'dst',                  // DEST_COLOR
    10: 'one-minus-dst',
    11: 'src-alpha-saturated',
    14: 'constant',            // BLEND_FACTOR — would require setBlendConstant()
    15: 'one-minus-constant',
};

// D3D11_BLEND_OP. Only 1 (ADD) appears in this frame.
const BLEND_OP = { 1: 'add', 2: 'subtract', 3: 'reverse-subtract', 4: 'min', 5: 'max' };

/**
 * Captured blend desc → GPUBlendState (or null when blending is disabled).
 *
 * ⚠ The alpha channel here is srcA=ONE, dstA=ZERO — destination alpha is REPLACED, not blended with
 * one-minus-src-alpha. The scene RT's alpha is sampled by the post chain, so getting this wrong
 * propagates downstream while looking correct on an opaque target.
 *
 * Measured distribution over the 1228 scene draws:
 *   1221 × src-alpha / one-minus-src-alpha   (normal)
 *      5 × src-alpha / one                   (additive)
 *      1 × disabled, writeMask 15
 *      1 × disabled, writeMask 0             (a depth-only prepass draw: ps is null)
 */
export function toBlendState(blend) {
    if (!blend || !blend.en) return null;          // null desc = D3D11 default = disabled
    const f = (v) => {
        const r = BLEND_FACTOR[v];
        if (!r) throw new Error(`unmapped D3D11_BLEND ${v}`);
        return r;
    };
    const o = (v) => {
        const r = BLEND_OP[v];
        if (!r) throw new Error(`unmapped D3D11_BLEND_OP ${v}`);
        return r;
    };
    return {
        color: { operation: o(blend.op), srcFactor: f(blend.src), dstFactor: f(blend.dst) },
        alpha: { operation: o(blend.opA), srcFactor: f(blend.srcA), dstFactor: f(blend.dstA) },
    };
}

// Write-mask bits are identical in both APIs: R=1 G=2 B=4 A=8. No remap needed.
export function toWriteMask(blend) {
    return blend && blend.mask !== undefined ? blend.mask : 0xF;
}

// True only if some state actually uses BLEND_FACTOR/INV_BLEND_FACTOR. None do in this frame, so
// setBlendConstant() should never be called — if this ever returns true, wire it up.
export function needsBlendConstant(blend) {
    if (!blend || !blend.en) return false;
    return [blend.src, blend.dst, blend.srcA, blend.dstA].some((v) => v === 14 || v === 15);
}

// ── depth / stencil ──────────────────────────────────────────────────────────────────────────────
// D3D11_COMPARISON_FUNC is 1-BASED and maps 1:1 to GPUCompareFunction.
// ⚠ Do not copy pvr2-renderer.mjs's DCM array — that is a 0-based PVR2 ISP DepthMode, not this.
const COMPARE = {
    1: 'never', 2: 'less', 3: 'equal', 4: 'less-equal',
    5: 'greater', 6: 'not-equal', 7: 'greater-equal', 8: 'always',
};

/**
 * Captured depth desc → the depthStencil half of a GPURenderPipelineDescriptor.
 *
 * Steam is FORWARD Z: clear 1.0, LESS_EQUAL, z straight out of the vertex.
 * ⚠ pvr2-renderer.mjs uses REVERSED Z with a log-depth write (clear 0.0, greater-equal). Do not
 * route this stream through it.
 *
 * DSV format is fmt 44 = R24G8_TYPELESS ⇒ the view is D24_UNORM_S8_UINT ⇒ depth24plus-stencil8.
 * WebGPU is stricter than D3D here: a stencil-containing format REQUIRES stencilClearValue plus
 * stencilLoadOp/stencilStoreOp on the render pass, even when stencil is unused.
 *
 * Stencil is safe to leave at defaults for the scene pass. Proof by elimination rather than by
 * reading the ops: every scene draw is either sten:0, or sten:1 with StencilReadMask = 0. With a zero
 * read mask both comparison operands are the constant 0 for every pixel, so the result is
 * content-independent — and since those 982 draws visibly render, that constant result is PASS.
 * Stencil therefore cannot cull or vary any fragment in this pass.
 * ⚠ Re-check before diffing the POST chain, where a draw could read stencil with a non-zero mask.
 */
export function toDepthStencil(depth, format = 'depth24plus-stencil8') {
    if (!depth) {
        return { format, depthWriteEnabled: false, depthCompare: 'always' };
    }
    const cmp = COMPARE[depth.func];
    if (!cmp) throw new Error(`unmapped D3D11_COMPARISON_FUNC ${depth.func}`);
    return {
        format,
        // D3D11_DEPTH_WRITE_MASK: ZERO = 0, ALL = 1
        depthWriteEnabled: !!depth.write,
        // DepthEnable=false in D3D means "always pass, never write"; WebGPU expresses that as
        // depthCompare:'always' + depthWriteEnabled:false rather than a disable flag.
        depthCompare: depth.en ? cmp : 'always',
    };
}

// ── rasterizer ───────────────────────────────────────────────────────────────────────────────────
// D3D11_CULL_MODE: 1 NONE, 2 FRONT, 3 BACK.
// Measured: cull FRONT ×870, NONE ×172, BACK ×183; ccw:1 on 1225 of 1228.
// ⚠ There is NO correct prior art to copy — pvr2-renderer.mjs hardcodes cullMode:'none',
// frontFace:'cw'. An inverted mapping silently deletes 870 stage draws.
// Useful triage fact: all 152 CHARACTER draws are cull:NONE, so a winding error cannot delete the
// characters. Characters but no stage ⇒ look at culling. Neither ⇒ look elsewhere.
const CULL = { 1: 'none', 2: 'front', 3: 'back' };

export function toPrimitive(raster, topology = 'triangle-list') {
    const cull = raster ? CULL[raster.cull] : 'none';
    if (raster && !cull) throw new Error(`unmapped D3D11_CULL_MODE ${raster.cull}`);
    if (raster && raster.fill === 2) throw new Error('WIREFRAME fill mode has no WebGPU equivalent');
    return {
        topology,
        cullMode: cull || 'none',
        // D3D11_RASTERIZER_DESC.FrontCounterClockwise
        frontFace: raster && raster.ccw ? 'ccw' : 'cw',
    };
}

// DepthBias / DepthBiasClamp / SlopeScaledDepthBias belong on depthStencil, not primitive. A non-zero
// bias offsets every sprite and reorders coplanar geometry, which is exactly the class of error that
// looks like "our sort is wrong".
export function applyDepthBias(depthStencil, raster) {
    if (!raster) return depthStencil;
    if (raster.dbias) depthStencil.depthBias = raster.dbias;
    if (raster.dbiasclamp) depthStencil.depthBiasClamp = raster.dbiasclamp;
    if (raster.dbiasslope) depthStencil.depthBiasSlopeScale = raster.dbiasslope;
    return depthStencil;
}

// ── samplers ─────────────────────────────────────────────────────────────────────────────────────
// D3D11_FILTER is a bit layout: bit0 = mip linear, bit2 = mag linear, bit4 = min linear.
// 0  = MIN_MAG_MIP_POINT ; 21 (0x15) = MIN_MAG_MIP_LINEAR ; 0x55 = ANISOTROPIC (never appears).
// D3D11_TEXTURE_ADDRESS_MODE: 1 WRAP, 2 MIRROR, 3 CLAMP, 4 BORDER, 5 MIRROR_ONCE.
// ⚠ WebGPU cannot express BORDER or MIRROR_ONCE. Exactly one draw in the whole frame uses BORDER and
// it is in the POST chain, never the scene — so throw rather than silently substituting clamp.
const ADDRESS = { 1: 'repeat', 2: 'mirror-repeat', 3: 'clamp-to-edge' };

/**
 * Captured D3D11_SAMPLER_DESC → GPUSamplerDescriptor.
 *
 * Measured: 4 distinct samplers. filter 21 + clamp ×1008, filter 0 + clamp ×368,
 * filter 0 + repeat ×22, filter 21 + repeat ×3.
 * All 152 character draws use filter 0 (POINT) on BOTH the index texture and the palette.
 *
 * ⚠ WebGPU's default createSampler() is nearest + clamp-to-edge — correct for characters and WRONG
 * for the 1008 linear draws, so nothing may rely on defaults.
 * ⚠ Never set `compare`. D3D ignores ComparisonFunc unless the filter carries the 0x80 comparison
 * bit (it never does here); setting it in WebGPU converts the binding to a comparison sampler and
 * requires sampler_comparison/textureSampleCompare in the shader.
 */
export function toSampler(s) {
    if (!s) return { magFilter: 'nearest', minFilter: 'nearest', mipmapFilter: 'nearest' };
    for (const m of [s.u, s.v, s.w]) {
        if (m === 4) throw new Error('D3D11_TEXTURE_ADDRESS_BORDER has no WebGPU equivalent');
        if (m === 5) throw new Error('D3D11_TEXTURE_ADDRESS_MIRROR_ONCE has no WebGPU equivalent');
        if (m !== undefined && !ADDRESS[m]) throw new Error(`unmapped address mode ${m}`);
    }
    const f = s.filter | 0;
    if (f === 0x55) throw new Error('ANISOTROPIC filter: set maxAnisotropy instead');
    return {
        minFilter: (f & 0x10) ? 'linear' : 'nearest',
        magFilter: (f & 0x04) ? 'linear' : 'nearest',
        mipmapFilter: (f & 0x01) ? 'linear' : 'nearest',
        addressModeU: ADDRESS[s.u] || 'clamp-to-edge',
        addressModeV: ADDRESS[s.v] || 'clamp-to-edge',
        addressModeW: ADDRESS[s.w] || 'clamp-to-edge',
        lodMinClamp: Number.isFinite(s.minlod) && s.minlod > 0 ? s.minlod : 0,
        // D3D's MaxLOD is FLT_MAX; that is not a usable lodMaxClamp. Every texture here is mips:1 so
        // LOD clamping is inert either way.
        lodMaxClamp: 32,
        // D3D ignores MaxAnisotropy unless the filter is ANISOTROPIC; WebGPU requires >= 1.
        maxAnisotropy: 1,
        // MipLODBias has NO WebGPU equivalent. Captured 0 everywhere; if it is ever non-zero it must
        // be baked in with textureSampleBias/textureSampleLevel instead of ignored.
        ...(s.bias ? { _unsupportedMipLODBias: s.bias } : {}),
    };
}

// ── textures ─────────────────────────────────────────────────────────────────────────────────────
// Measured formats: 28 (stage pages, palettes), 61 (character index tiles), 87 (scene RT),
// 44 (the DSV). None is an _SRGB variant, so the whole chain is linear in storage — apply no gamma,
// and keep getPreferredCanvasFormat() out of the compare path.
const TEX_FORMAT = {
    28: 'rgba8unorm',
    29: 'rgba8unorm-srgb',
    61: 'r8unorm',        // character index tiles; WGSL texture_2d<f32> returns vec4(r,0,0,1)
    87: 'bgra8unorm',
    88: 'bgra8unorm',
};

export function toTextureFormat(dxgi) {
    const f = TEX_FORMAT[dxgi];
    if (!f) throw new Error(`unmapped DXGI_FORMAT ${dxgi}`);
    return f;
}

/**
 * ⚠ Index tiles MUST be uploaded with mipLevelCount 1 and via writeTexture with raw bytes.
 * Auto-generating mips averages palette INDICES, and since the palette is 16 banks of 16 an averaged
 * index lands in a completely different bank — it looks like "wrong colours", not "wrong mip".
 * Going through copyExternalImageToTexture or a canvas can also colour-manage an r8unorm that is not
 * a colour at all.
 */
export function textureDescriptor(t) {
    return {
        size: { width: t.w, height: t.h },
        format: toTextureFormat(t.fmt),
        mipLevelCount: 1,
        usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST,
    };
}

// ── viewport ─────────────────────────────────────────────────────────────────────────────────────
// D3D11_VIEWPORT is top-left origin in RT pixels; setViewport is top-left origin in attachment
// pixels. Both APIs have NDC y-up and both flip y in the viewport transform, and clip-space clipping
// is identical (|x|<=w, |y|<=w, 0<=z<=w). Nothing to invert; do not "fix" partially offscreen sprites.
export function applyViewport(pass, vp) {
    if (!vp || vp.length < 4) return;
    const minDepth = vp.length > 4 ? vp[4] : 0;
    const maxDepth = vp.length > 5 ? vp[5] : 1;
    pass.setViewport(vp[0], vp[1], vp[2], vp[3], minDepth, maxDepth);
}

// A stable key for the pipeline cache. Must include every field that affects the pipeline object and
// nothing that does not — a key that is too coarse silently reuses the wrong pipeline.
export function pipelineKey(d, shaderVariant, topology) {
    const b = d.blend || {};
    const z = d.depth || {};
    const r = d.raster || {};
    return [
        shaderVariant, topology,
        b.en | 0, b.src | 0, b.dst | 0, b.op | 0, b.srcA | 0, b.dstA | 0, b.opA | 0,
        toWriteMask(d.blend),
        z.en | 0, z.write | 0, z.func | 0,
        r.cull | 0, r.ccw | 0, r.dbias | 0, r.dbiasslope || 0,
    ].join(':');
}
