// RETRO RECEIPTS — PATH B: Steam MvC2's own render pipeline, ported to WGSL.
//
// A LITERAL port of the game's shaders, disassembled (fxc /dumpbin) from bytecode captured at
// CreateVertexShader / CreatePixelShader time. Reviewed twice (steam-d3d11-capture-expert and
// mvc2-sprite-render-expert, 2026-09-01); the corrections are called out inline so they are not
// reintroduced.
//
// ⚠⚠ THE BIG ONE — MY FIRST DRAFT HAD THIS EXACTLY BACKWARDS:
//   the 975 direct-RGBA draws are the 3D STAGE (photographic 256x256 pages: pillars, chains, a
//   ship's wheel). The CHARACTERS are the 152 INDEXED draws — 32x32 R8_UNORM index tiles plus a
//   256x1 palette. Established three ways: every draw whose NDC bbox lands on Sentinel is an indexed
//   draw (41/41); the RGBA pages visibly are stage art; and the palettes are 4bpp MvC2 character
//   palettes (15 non-transparent entries, every channel a multiple of 0x11 = ARGB4444 bit-replicated,
//   one with 240 = 16 banks x 16, i.e. our PLxx_lut.json banks[] shape).
//
// ⚠ THIS IS FLYCAST'S SHADER FAMILY. All four pixel shaders are specialisations of the DX11 macro
//   matrix in maplecast-flycast/core/rend/dx11/dx11_shaders.cpp — Steam MvC2's renderer is a PVR2
//   emulator with flycast's shading semantics. Model these as (ShadInstr, IgnoreTexA, Offset, fog,
//   Palette) tuples, NOT as ad-hoc shaders. The replayer should be built on pvr2-renderer.mjs, whose
//   _pipe() cache is already keyed on exactly the (blend src, blend dst, depth func, depth write,
//   cull, topology) tuple this stream needs.
//
// SHADERS AND THEIR MANDATORY VS PAIRINGS (frame 4828, 1252 draws):
//   vs_0000000039E22A38 + ps_000000006420CEB8   975  opaque STAGE      IgnoreTexA=1, fog, depth write=1
//   vs_0000000039E22A38 + ps_00000000642D7078    69  translucent STAGE IgnoreTexA=0, fog, depth write=0
//   vs_0000000063F9C9F8 + ps_00000000642D7378   152  CHARACTERS        + pp_Palette,  depth write=0
//   vs_0000000063F9C9F8 + ps_00000000643231F8    23  HUD               no fog
//   ⚠ the pairings are NOT interchangeable: the two vertex shaders differ fundamentally (below).
//
// VERTEX LAYOUT (authoritative, from the captured D3D11_INPUT_ELEMENT_DESC[], stride 40):
//   +0 POSITION float4 (.xyz read) | +16 NORMAL float2 (NOT DECLARED — the VS inputs are v0,v2,v3,v4;
//   there is no v1, and the game leaves these 8 bytes uninitialised: real captures hold NaN)
//   | +24 TANGENT unorm4 = colour0 | +28 BINORMAL unorm4 = colour1 | +32 TEXCOORD float2
//   This is pvr2-renderer.mjs's stride-28 vertex plus an unread pos.w and the 8 dead bytes:
//     {shaderLocation:0, offset:0, format:'float32x4'}, {2, 24, 'unorm8x4'},
//     {3, 28, 'unorm8x4'},      {4, 32, 'float32x2'}      // location 1 deliberately absent
//   ✓ unorm8x4 needs NO swizzle: D3D byte0->R and WebGPU byte0->x agree. CONFIRMED.
//
// ── TRAPS, ALL MEASURED FROM THE CAPTURE ─────────────────────────────────────────────────────────
// * INTERPOLATION: DXBC `linear` means PERSPECTIVE-CORRECT; WGSL's `@interpolate(linear)` means
//   NOPERSPECTIVE — the opposite. WGSL's DEFAULT is the correct match, so these varyings carry no
//   interpolate attribute. ⚠ DO NOT "fix" this.
// * COLOUR SPACE: no _SRGB format anywhere (scene RT fmt 87, backbuffer fmt 28, textures fmt 28/61).
//   Linear throughout; a *-srgb canvas injects a gamma error that looks "close".
// * DEPTH: forward Z, clear 1.0, LESS_EQUAL, z straight from the vertex (characters sit ~0.979-0.9815,
//   and use only SEVEN distinct z values across all 152 draws — one z per body/layer, not per part).
//   ⚠ pvr2-renderer.mjs uses REVERSED-Z with a log-depth write; do NOT route this through it.
//   DSV is fmt 44 (R24G8_TYPELESS => D24_UNORM_S8_UINT) => use 'depth24plus-stencil8', NOT the
//   depth32float Path A settled on for DC semantics.
// * TEXTURE V: the flip is baked into the game's OWN UVs (measured: v decreases as screen y goes
//   down). Replaying this stream verbatim, flip NOTHING. Harvesting Steam textures into our atlases,
//   flip at atlas-build time — never at upload, never here. Our convention is atlas row 0 = sprite top.
// * SAMPLERS ARE PER-DRAW STATE. Measured: 933 stage draws filter 21 (LINEAR), 24 filter 0 (POINT),
//   16 address mode 1 (WRAP); all 152 character draws filter 0 (POINT) + address 3 (CLAMP) on BOTH
//   samplers. ⚠ WebGPU's default createSampler() is nearest+clamp — right for characters, wrong for
//   the stage. The replayer must build each sampler from the captured D3D11_SAMPLER_DESC.
// * BLEND ALPHA: srcA=ONE, dstA=ZERO — destination alpha is REPLACED. Not one/one-minus-src-alpha.
// * CULL is per-draw and varies (FRONT x870, BACK x183, NONE x172). Verify with a single quad first:
//   an inverted enum deletes 870 draws and looks identical to a broken replayer.

// ── uniforms ─────────────────────────────────────────────────────────────────────────────────────
// ⚠ THESE MUST BE THE PER-DRAW VALUES. A Present-time snapshot of the game's constant buffers is
// STALE: the post chain reuses the same buffer objects and overwrites them with an identity matrix
// and a camera at the origin. The capture shadows them at UpdateSubresource instead, and measured 55
// DISTINCT world matrices in one frame — so this genuinely varies per draw.
//
// All four of the game's constant buffers are packed into ONE uniform block, bound once with a
// dynamic offset per draw. One 256-byte-aligned slice per draw (490 draws = 125 KB) costs a single
// setBindGroup offset instead of four buffer bindings, and keeps the bind-group layout constant so
// the pipeline cache stays small.
struct DrawUniforms {
    // CBWorld: row_major float3x4 fWorld
    world0 : vec4f,
    world1 : vec4f,
    world2 : vec4f,
    // CBViewProjection: row_major float4x4 fViewProj (translation is in ROW 3, matching the shader's
    // r1.x*cb1[0] + r1.y*cb1[1] + r1.z*cb1[2] + cb1[3] accumulation)
    vp0 : vec4f,
    vp1 : vec4f,
    vp2 : vec4f,
    vp3 : vec4f,
    cameraPos : vec4f,          // fCameraPos at CBViewProjection +64, used by the fog term
    // CBFog: rgb = fFogColor, w = fFogDensity
    fogColor : vec4f,
    // x = fFogStart, y = fFogInvRange, z = CBROPTest.fAlphaRef, w = unused
    fogParams : vec4f,
};

@group(0) @binding(0) var<uniform> u : DrawUniforms;

// s0/s1 are BINDING SLOTS. The replayer supplies real sampler objects per draw, built from the
// captured D3D11_SAMPLER_DESC — sampler state is per-draw, not a shader constant.
@group(1) @binding(0) var samp0 : sampler;
@group(1) @binding(1) var samp1 : sampler;
@group(1) @binding(2) var tBase : texture_2d<f32>;   // t0 (RGBA page, or R8 index tile)
@group(1) @binding(3) var tPal  : texture_2d<f32>;   // t1, the 256x1 palette

struct VSIn {
    @location(0) position : vec4f,
    @location(2) color0   : vec4f,
    @location(3) color1   : vec4f,
    @location(4) uv       : vec2f,
};

struct VSOutWorld {          // vs_0000000039E22A38: four varyings (o1..o4)
    @builtin(position) pos : vec4f,
    @location(0) color0 : vec4f,
    @location(1) color1 : vec3f,
    @location(2) worldPos : vec3f,
    @location(3) uv : vec2f,
};

struct VSOutFlat {           // vs_0000000063F9C9F8: THREE varyings, uv arrives at TEXCOORD2
    @builtin(position) pos : vec4f,
    @location(0) color0 : vec4f,
    @location(1) color1 : vec3f,
    @location(2) uv : vec2f,
};

// ── vertex: the STAGE transform (vs_0000000039E22A38, 1044 draws) ────────────────────────────────
//   world = { dot(cb0[0],p), dot(cb0[1],p), dot(cb0[2],p) },  p = float4(POSITION.xyz, 1)
//   clip  = world.x*cb1[0] + world.y*cb1[1] + world.z*cb1[2] + cb1[3]
// Left-to-right accumulation order preserved deliberately (float addition is not associative).
@vertex
fn vs_world(in : VSIn) -> VSOutWorld {
    let p = vec4f(in.position.xyz, 1.0);
    let world = vec3f(dot(u.world0, p), dot(u.world1, p), dot(u.world2, p));

    var out : VSOutWorld;
    out.pos = world.x * u.vp0
            + world.y * u.vp1
            + world.z * u.vp2
            + u.vp3;
    out.color0   = in.color0;
    out.color1   = in.color1.rgb;
    out.worldPos = world;
    out.uv       = in.uv;
    return out;
}

// ── vertex: CHARACTERS + HUD (vs_0000000063F9C9F8, 175 draws) ────────────────────────────────────
// The entire shader is `mov o0.xyz, v0.xyzx; mov o0.w, l(1.0)` plus three pass-throughs. NO constant
// buffers: these positions are ALREADY IN NDC (measured: -0.4042, -0.6375, z 0.98153).
// ⚠ BUG FIX: the first draft ran these through the world/view-proj matrices, which would transform
// already-transformed positions off-screen.
@vertex
fn vs_flat(in : VSIn) -> VSOutFlat {
    var out : VSOutFlat;
    out.pos    = vec4f(in.position.xyz, 1.0);
    out.color0 = in.color0;
    out.color1 = in.color1.rgb;
    out.uv     = in.uv;
    return out;
}

// Fog tail of the stage shaders. Kept, not folded away: the earlier decision to drop it rested on
// fFogDensity == 0 read from a STALE constant buffer. It is a bit-exact no-op when density really is
// 0, so keeping it costs nothing and removes a failure mode we cannot yet rule out.
// ⚠ config-conditional (HDR=DEFAULT), not structurally absent — unlike the HUD shader, which has no
// fog instructions at all.
fn apply_fog(rgb : vec3f, worldPos : vec3f) -> vec3f {
    let d = length(worldPos - u.cameraPos.xyz);
    var f = saturate((d - u.fogParams.x) * u.fogParams.y) * u.fogColor.w;
    f = sqrt(f);
    return rgb * (1.0 - f) + u.fogColor.rgb * f;
}

// ── fragment: OPAQUE STAGE (ps_000000006420CEB8, 975 draws) ──────────────────────────────────────
// flycast tuple: ShadInstr=3 (MODULATE_ALPHA), IgnoreTexA=1, Offset=1, fog on.
// ⚠ The bytecode's `sample r0.xyz` + `mov r0.w, l(1.0)` is pp_IgnoreTexA forcing texcol.a := 1 —
// it is NOT a general "alpha comes from the vertex" rule. Its sibling below is the same shader with
// IgnoreTexA=0. (These 256x256 pages are opaque stage art: alpha is uniformly 255.)
@fragment
fn fs_stage_opaque(in : VSOutWorld) -> @location(0) vec4f {
    let tex = textureSample(tBase, samp0, in.uv).rgb;   // texcol.a forced to 1

    let a = in.color0.a;                                // = 1.0 * colour0.a
    if (u.fogParams.z >= a) { discard; }

    return vec4f(apply_fog(tex * in.color0.rgb + in.color1, in.worldPos), a);
}

// ── fragment: TRANSLUCENT STAGE (ps_00000000642D7078, 69 draws) ──────────────────────────────────
// Byte-for-byte the shader above with IgnoreTexA=0: it samples r0.xyzw and keeps the texture alpha.
@fragment
fn fs_stage_texalpha(in : VSOutWorld) -> @location(0) vec4f {
    let tex = textureSample(tBase, samp0, in.uv);

    let a = tex.a * in.color0.a;
    if (u.fogParams.z >= a) { discard; }

    return vec4f(apply_fog(tex.rgb * in.color0.rgb + in.color1, in.worldPos), a);
}

// ── fragment: THE CHARACTERS (ps_00000000642D7378, 152 draws) ────────────────────────────────────
// flycast tuple: ShadInstr=3 + pp_Palette.
//   idx = sample(t0 /* 32x32 R8_UNORM index tile */, uv, s0).x
//   pal = sample(t1 /* 256x1 palette */, float2(idx, 0), s1)
// ⚠ BUG FIX: both samplers must be POINT (measured filter:0 on s0 AND s1 for all 152 draws). The
// first draft linear-filtered the index texture, which blends palette INDICES into arbitrary colours.
// The palette is 4bpp: index 0 transparent, 16 entries per bank — idx>>4 selects the bank, idx&15 the
// entry, which is exactly the encoding our _idx.png / PLxx_lut.json already use. A SKIN SWAP IS
// WRITING 16 RGBA VALUES HERE, matching sprite-gpu.mjs setSkin().
@fragment
fn fs_character(in : VSOutFlat) -> @location(0) vec4f {
    let idx = textureSample(tBase, samp0, in.uv).r;
    let pal = textureSample(tPal, samp1, vec2f(idx, 0.0));

    let a = pal.a * in.color0.a;
    if (u.fogParams.z >= a) { discard; }

    return vec4f(pal.rgb * in.color0.rgb + in.color1, a);
}

// ── fragment: HUD (ps_00000000643231F8, 23 draws) ────────────────────────────────────────────────
// ShadInstr=3, texture alpha kept, and NO fog instructions at all — a structural difference from the
// stage shaders, not a constant-driven one. Bound texture is a 256x128 RGBA bank.
// Worth noting for the other lane: per mvc-hud-list0b-live-re the UI sprite bank cannot be obtained
// offline, and this path hands it over as flat RGBA.
@fragment
fn fs_hud(in : VSOutFlat) -> @location(0) vec4f {
    let tex = textureSample(tBase, samp0, in.uv);

    let a = tex.a * in.color0.a;
    if (u.fogParams.z >= a) { discard; }

    return vec4f(tex.rgb * in.color0.rgb + in.color1, a);
}

// ── fragment: OPAQUE on the FLAT varyings (pass-through VS) ──────────────────────────────────────
// Same maths as fs_stage_opaque, but taking VSOutFlat. WebGPU requires the fragment input signature
// to match the vertex output signature exactly — a vs_flat (3 varyings, uv at location 2) paired with
// a VSOutWorld fragment entry is a pipeline-creation error:
//   "component count (2) of the vertex output at location 2 differs from (3) of the fragment input".
// The game pairs IgnoreTexA shaders with BOTH vertex shaders, so both varying layouts need one.
// No fog term: shaders on the pass-through VS have no worldPos to compute distance from, and the
// ones measured here bind no fog constant buffer at all.
@fragment
fn fs_flat_opaque(in : VSOutFlat) -> @location(0) vec4f {
    let tex = textureSample(tBase, samp0, in.uv).rgb;   // texcol.a forced to 1 by pp_IgnoreTexA

    let a = in.color0.a;
    if (u.fogParams.z >= a) { discard; }

    return vec4f(tex * in.color0.rgb + in.color1, a);
}
