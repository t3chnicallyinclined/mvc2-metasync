// sprite-gpu.mjs — WebGPU 2D sprite renderer for the ROM-asset client (Option 6).
//
// Draws character sprites as instanced textured quads into the PostProcessor's
// offscreen target, then blits through the effect chain — so the sprite client
// gets the SAME bloom/CRT/scanline/etc. effects as the live TA render.
//
// Skin / hit-flash recolor (reuses the renderer's palette technique): each
// character's body-16 colors (the rip's default palette, per-char from the JSON)
// are match-replaced in the fragment shader with the LIVE palette — T._pal at PVR
// bank 256+128*slot, the very palette RAM pvr2-renderer reads. Default skin =>
// live==default => no-op; community skin / hit-flash => recolor for free.
//
// We still generate the quad geometry ourselves (the 253-byte state carries no
// draw commands) — that's the only "from scratch" part; everything downstream
// (effects, palette) reuses the renderer's machinery. Canvas2D is the fallback.

import { PostProcessor } from './post-process.mjs?v=2';

const SHADER = `
struct VSOut { @builtin(position) pos: vec4f, @location(0) uv: vec2f, @location(1) @interpolate(flat) palBase: u32, @location(2) @interpolate(flat) tint: vec3f };
struct U { canvas: vec2f, pad: vec2f };
@group(0) @binding(0) var atlasTex: texture_2d<f32>;
@group(0) @binding(1) var samp: sampler;
@group(0) @binding(2) var<uniform> u: U;
@group(0) @binding(3) var<storage, read> pal: array<vec4f>;   // per group: [0..15]=default body, [16..31]=live body

@vertex
fn vs(@builtin(vertex_index) vi: u32,
      @location(0) dest: vec4f,    // x,y,w,h canvas px
      @location(1) auv: vec4f,     // u0,v0,u1,v1 atlas UV
      @location(2) flip: f32,
      @location(3) palBase: f32,
      @location(4) tint: vec3f,     // additive fx tint (hit-flash / super-aura), 0 = none
      @location(5) flipY: f32) -> VSOut {
  var corners = array<vec2f,6>(
    vec2f(0.,0.), vec2f(1.,0.), vec2f(0.,1.),
    vec2f(0.,1.), vec2f(1.,0.), vec2f(1.,1.));
  let c = corners[vi];
  let px = dest.x + c.x * dest.z;
  let py = dest.y + c.y * dest.w;
  let clip = vec2f(px / u.canvas.x * 2. - 1., 1. - py / u.canvas.y * 2.);
  var ux = c.x; if (flip  > 0.5) { ux = 1. - c.x; }
  var vy = c.y; if (flipY > 0.5) { vy = 1. - c.y; }
  let uv = vec2f(mix(auv.x, auv.z, ux), mix(auv.y, auv.w, vy));
  var o: VSOut; o.pos = vec4f(clip, 0., 1.); o.uv = uv; o.palBase = u32(palBase + 0.5); o.tint = tint; return o;
}
@fragment
fn fs(i: VSOut) -> @location(0) vec4f {
  let col = textureSample(atlasTex, samp, i.uv);
  if (col.a < 0.5) { discard; }
  // full-palette recolor: nearest default color -> live color, but ONLY where the
  // live palette differs from default. So super-glow/auras tint everything, skins
  // leave unchanged sub-palettes alone, and color collisions keep the original.
  var bi = -1; var bd = 0.02;
  for (var k = 0u; k < 128u; k = k + 1u) {
    let d = distance(col.rgb, pal[i.palBase + k].rgb);
    if (d < bd) { bd = d; bi = i32(k); }
  }
  var rgb = col.rgb;
  if (bi >= 0) {
    let dcol = pal[i.palBase + u32(bi)].rgb;
    let lcol = pal[i.palBase + 128u + u32(bi)].rgb;
    if (distance(dcol, lcol) > 0.012) { rgb = lcol; }
  }
  // STEP-1 fx tint (approximate): additive boost from buildDrawList's hit-flash /
  // super-aura. 0 vector = no change, so chars without the field are untouched.
  rgb = clamp(rgb + i.tint, vec3f(0.), vec3f(1.));
  return vec4f(rgb, col.a);
}

// ---- hit-spark pass (additive; black contributes nothing) ----
struct SOut { @builtin(position) pos: vec4f, @location(0) uv: vec2f, @location(1) @interpolate(flat) a: f32 };
@vertex
fn vs_spark(@builtin(vertex_index) vi: u32,
            @location(0) dest: vec4f,   // x,y = CENTER, z,w = size
            @location(1) auv: vec4f, @location(2) alpha: f32) -> SOut {
  var corners = array<vec2f,6>(vec2f(0.,0.),vec2f(1.,0.),vec2f(0.,1.),vec2f(0.,1.),vec2f(1.,0.),vec2f(1.,1.));
  let c = corners[vi];
  let px = dest.x + (c.x - 0.5) * dest.z;
  let py = dest.y + (c.y - 0.5) * dest.w;
  let clip = vec2f(px / u.canvas.x * 2. - 1., 1. - py / u.canvas.y * 2.);
  let uv = vec2f(mix(auv.x, auv.z, c.x), mix(auv.y, auv.w, c.y));
  var o: SOut; o.pos = vec4f(clip, 0., 1.); o.uv = uv; o.a = alpha; return o;
}
@fragment
fn fs_spark(i: SOut) -> @location(0) vec4f {
  let col = textureSample(atlasTex, samp, i.uv);
  return vec4f(col.rgb * i.a, 1.0);
}`;

// ---- EXACT palette-LUT pass (single-bank indexed atlas, costume-selectable) ----
// The _idx.png atlas (tools/extract_gfx1_atlas.py) stores per pixel:
//   R = PALETTE INDEX 0..15   G = 0   B = 0   A = 0 (transparent) / 255 (opaque)
// i.e. the atlas is baked at ONE palette row (the body bank), so the per-pixel INDEX
// alone selects the color out of a 16-color palette supplied per draw group. The group's
// 16 colors are the character's COSTUME body bank (PALETTE_DATA bank = costume*8, verified
// against the engine-TA-grounded GSTA-FINDINGS doc: Cable pal-idx 1 -> bank 8 = purple).
// We sample NEAREST (R is a data byte, not a color), read index = R*255, and look up
// pal[group*16 + index] -> exact RGBA. This is the costume-swap path: one bake, all
// costumes (the idx bake never changes; the group palette selects the costume).
const LUT_PER_GROUP = 16;   // 16 colors uploaded per draw group (one costume body bank)
const LUT_SHADER = `
struct VSOut { @builtin(position) pos: vec4f, @location(0) uv: vec2f, @location(1) @interpolate(flat) g: u32, @location(2) @interpolate(flat) tint: vec3f };
struct U { canvas: vec2f, pad: vec2f };
@group(0) @binding(0) var idxTex: texture_2d<f32>;
@group(0) @binding(1) var samp: sampler;
@group(0) @binding(2) var<uniform> u: U;
@group(0) @binding(3) var<storage, read> pal: array<vec4f>;   // [group][index 0..15]
const PG: u32 = 16u;   // colors per group (one costume body bank)
@vertex
fn vs_lut(@builtin(vertex_index) vi: u32,
          @location(0) dest: vec4f, @location(1) auv: vec4f,
          @location(2) flip: f32, @location(3) grp: f32, @location(4) tint: vec3f,
          @location(5) flipY: f32) -> VSOut {
  var corners = array<vec2f,6>(vec2f(0.,0.),vec2f(1.,0.),vec2f(0.,1.),vec2f(0.,1.),vec2f(1.,0.),vec2f(1.,1.));
  let c = corners[vi];
  let px = dest.x + c.x * dest.z; let py = dest.y + c.y * dest.w;
  let clip = vec2f(px / u.canvas.x * 2. - 1., 1. - py / u.canvas.y * 2.);
  var ux = c.x; if (flip  > 0.5) { ux = 1. - c.x; }
  var vy = c.y; if (flipY > 0.5) { vy = 1. - c.y; }
  let uv = vec2f(mix(auv.x, auv.z, ux), mix(auv.y, auv.w, vy));
  var o: VSOut; o.pos = vec4f(clip,0.,1.); o.uv = uv; o.g = u32(grp + 0.5); o.tint = tint; return o;
}
@fragment
fn fs_lut(i: VSOut) -> @location(0) vec4f {
  let s = textureSample(idxTex, samp, i.uv);   // R=index/255, A = opacity
  if (s.a < 0.5) { discard; }                  // transparent atlas pixel
  let index = u32(s.r * 255. + 0.5);
  let col = pal[i.g * PG + index];
  if (col.a < 0.5) { discard; }                // idx0 / transparent palette entry
  let rgb = clamp(col.rgb + i.tint, vec3f(0.), vec3f(1.));
  return vec4f(rgb, 1.0);
}`;

const INST_FLOATS = 14;       // dest(4) + auv(4) + flip(1) + palBase(1) + tint(3) + flipY(1)
const INST_STRIDE = INST_FLOATS * 4;

export class SpriteGPU {
  constructor() {
    this.ok = false; this.chars = {}; this.charPal = {};
    // maxInst bumped 64 -> 512: the effect-heavy 0.3.29 tape emits up to 231 body/effect
    // parts per frame (avg ~61) — a 64-cap silently TRUNCATED most bodies. maxGroups 8 ->
    // 12 covers 6 distinct cids doubled for a mirror match + the fx pseudo-char.
    this.maxInst = 512; this.maxGroups = 12; this.recolor = true;
    // PERSIST-ON-EMPTY (tag-in anti-blank): when a frame would draw NOTHING
    // (empty draw list, or a draw list that only references not-yet-loaded
    // atlases — the transient tag-in gap), skip the whole GPU pass so the
    // swap-chain keeps its LAST presented frame instead of clearing to black.
    // The canvas is alphaMode:'opaque' and we never call getCurrentTexture()
    // on a skipped frame, so the browser preserves the prior present. Set
    // window._spritePersistEmpty=false (or sg.persistEmpty=false) to disable.
    this.persistEmpty = true;
  }

  // alphaMode (optional, default 'opaque'): pass 'premultiplied' when SG draws on a
  // TRANSPARENT overlay canvas stacked over another renderer (e.g. the render-replica's
  // pvr2 STAGE canvas) — the body quads' transparent background then lets the layer
  // behind show through instead of clearing it to black. The body quads are punch-through
  // (index-0 transparent = alpha 0/1), so premultiplied == straight for the drawn pixels.
  init(device, canvas, alphaMode) {
    try {
      this.dev = device; this.canvas = canvas;
      this.ctx = canvas.getContext('webgpu');
      this.fmt = navigator.gpu.getPreferredCanvasFormat();
      this.ctx.configure({ device, format: this.fmt, alphaMode: alphaMode || 'opaque' });
      this.PP = new PostProcessor(); this.PP.init(device, this.fmt);
      this.sampler = device.createSampler({ minFilter: 'nearest', magFilter: 'nearest' });
      this.ubuf = device.createBuffer({ size: 16, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
      this.inst = device.createBuffer({ size: this.maxInst * INST_STRIDE, usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST });
      this.instData = new Float32Array(this.maxInst * INST_FLOATS);
      this.palBuf = device.createBuffer({ size: this.maxGroups * 256 * 16, usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST });
      this.palData = new Float32Array(this.maxGroups * 256 * 4);   // per group: 128 default + 128 live
      this.bgl = device.createBindGroupLayout({ entries: [
        { binding: 0, visibility: GPUShaderStage.FRAGMENT, texture: { sampleType: 'float' } },
        { binding: 1, visibility: GPUShaderStage.FRAGMENT, sampler: { type: 'filtering' } },
        { binding: 2, visibility: GPUShaderStage.VERTEX, buffer: { type: 'uniform' } },
        { binding: 3, visibility: GPUShaderStage.FRAGMENT, buffer: { type: 'read-only-storage' } },
      ]});
      const mod = device.createShaderModule({ code: SHADER });
      this.pipe = device.createRenderPipeline({
        layout: device.createPipelineLayout({ bindGroupLayouts: [this.bgl] }),
        vertex: { module: mod, entryPoint: 'vs', buffers: [{
          arrayStride: INST_STRIDE, stepMode: 'instance', attributes: [
            { shaderLocation: 0, offset: 0,  format: 'float32x4' },
            { shaderLocation: 1, offset: 16, format: 'float32x4' },
            { shaderLocation: 2, offset: 32, format: 'float32' },
            { shaderLocation: 3, offset: 36, format: 'float32' },
            { shaderLocation: 4, offset: 40, format: 'float32x3' },
            { shaderLocation: 5, offset: 52, format: 'float32' },
          ]}]},
        fragment: { module: mod, entryPoint: 'fs', targets: [{ format: this.fmt }] },
        primitive: { topology: 'triangle-list' },
      });
      // Additive variant of the SAME palette pipeline — for fx/super objects whose
      // wire blend byte requests dst=ONE (glow/energy). Same shader, same bind
      // group layout, additive blend so the part adds light instead of replacing.
      this.pipeAdd = device.createRenderPipeline({
        layout: device.createPipelineLayout({ bindGroupLayouts: [this.bgl] }),
        vertex: { module: mod, entryPoint: 'vs', buffers: [{
          arrayStride: INST_STRIDE, stepMode: 'instance', attributes: [
            { shaderLocation: 0, offset: 0,  format: 'float32x4' },
            { shaderLocation: 1, offset: 16, format: 'float32x4' },
            { shaderLocation: 2, offset: 32, format: 'float32' },
            { shaderLocation: 3, offset: 36, format: 'float32' },
            { shaderLocation: 4, offset: 40, format: 'float32x3' },
            { shaderLocation: 5, offset: 52, format: 'float32' },
          ]}]},
        fragment: { module: mod, entryPoint: 'fs', targets: [{ format: this.fmt,
          blend: { color: { srcFactor: 'src-alpha', dstFactor: 'one', operation: 'add' },
                   alpha: { srcFactor: 'one',       dstFactor: 'one', operation: 'add' } } }] },
        primitive: { topology: 'triangle-list' },
      });
      // REGULAR-ALPHA variant of the palette pipeline (src-a / 1-src-a) — the MISSING blend
      // (OWNED-RENDER-BUILD-SPEC "alphaPipe" build gap). MvC2's global fragment blend for
      // sprite-class objects (cat 1-4 effects) is MODE-2 = alpha/opaque (the SAME state the
      // bodies run), NOT pure-additive: blend is RUNTIME PVR state (sh4-re: the TSP SRC/DST
      // is set once per list, not a per-part field). Without this pipe the wire's 0x45 (alpha)
      // fell through to this.pipe (opaque REPLACE) and 0x01/0x41 went to pipeAdd (too bright) —
      // the "effects look too bright" bug. dst=1-src-a composites the effect OVER instead of
      // adding light.
      this.alphaPipe = device.createRenderPipeline({
        layout: device.createPipelineLayout({ bindGroupLayouts: [this.bgl] }),
        vertex: { module: mod, entryPoint: 'vs', buffers: [{
          arrayStride: INST_STRIDE, stepMode: 'instance', attributes: [
            { shaderLocation: 0, offset: 0,  format: 'float32x4' },
            { shaderLocation: 1, offset: 16, format: 'float32x4' },
            { shaderLocation: 2, offset: 32, format: 'float32' },
            { shaderLocation: 3, offset: 36, format: 'float32' },
            { shaderLocation: 4, offset: 40, format: 'float32x3' },
            { shaderLocation: 5, offset: 52, format: 'float32' },
          ]}]},
        fragment: { module: mod, entryPoint: 'fs', targets: [{ format: this.fmt,
          blend: { color: { srcFactor: 'src-alpha', dstFactor: 'one-minus-src-alpha', operation: 'add' },
                   alpha: { srcFactor: 'one',       dstFactor: 'one-minus-src-alpha', operation: 'add' } } }] },
        primitive: { topology: 'triangle-list' },
      });
      // hit-spark pipeline: additive blend, no palette (bindings 0,1,2)
      this.sparkBgl = device.createBindGroupLayout({ entries: [
        { binding: 0, visibility: GPUShaderStage.FRAGMENT, texture: { sampleType: 'float' } },
        { binding: 1, visibility: GPUShaderStage.FRAGMENT, sampler: { type: 'filtering' } },
        { binding: 2, visibility: GPUShaderStage.VERTEX, buffer: { type: 'uniform' } },
      ]});
      this.sparkPipe = device.createRenderPipeline({
        layout: device.createPipelineLayout({ bindGroupLayouts: [this.sparkBgl] }),
        vertex: { module: mod, entryPoint: 'vs_spark', buffers: [{
          arrayStride: 36, stepMode: 'instance', attributes: [
            { shaderLocation: 0, offset: 0,  format: 'float32x4' },
            { shaderLocation: 1, offset: 16, format: 'float32x4' },
            { shaderLocation: 2, offset: 32, format: 'float32' },
          ]}]},
        fragment: { module: mod, entryPoint: 'fs_spark', targets: [{ format: this.fmt,
          blend: { color: { srcFactor: 'one', dstFactor: 'one', operation: 'add' },
                   alpha: { srcFactor: 'one', dstFactor: 'one', operation: 'add' } } }] },
        primitive: { topology: 'triangle-list' },
      });
      this.sparkInst = device.createBuffer({ size: 32 * 36, usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST });
      this.sparkInstData = new Float32Array(32 * 9);
      this.fxInst = device.createBuffer({ size: 48 * 36, usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST });
      this.fxInstData = new Float32Array(48 * 9);   // live TA effect quads (per-quad texture)

      // ---- EXACT palette-LUT path (single-bank indexed atlases, costume-selectable) ----
      // Same bind-group layout shape as the RGB path (tex/sampler/uniform/storage), so
      // an indexed char registers its own bind group; non-indexed chars keep the RGB
      // pipeline untouched. LUT buffer: maxGroups × 16 colors (one costume body bank) × vec4f.
      this.LUT_PG = LUT_PER_GROUP;   // 16 colors/group; must match PG in LUT_SHADER
      this.idxChars = {};                 // cid -> { tex, bg, w, h } for indexed atlases
      this.charLUT  = {};                 // cid -> { bankList, bodyBank, banks:[[ [r,g,b,a]*16 ],...] }
      this.lutBgl = this.bgl;             // identical layout (tex2d, sampler, uniform, ro-storage)
      const lutMod = device.createShaderModule({ code: LUT_SHADER });
      const lutVbuf = { arrayStride: INST_STRIDE, stepMode: 'instance', attributes: [
        { shaderLocation: 0, offset: 0,  format: 'float32x4' },
        { shaderLocation: 1, offset: 16, format: 'float32x4' },
        { shaderLocation: 2, offset: 32, format: 'float32' },
        { shaderLocation: 3, offset: 36, format: 'float32' },
        { shaderLocation: 4, offset: 40, format: 'float32x3' },
        { shaderLocation: 5, offset: 52, format: 'float32' },
      ]};
      this.lutPipe = device.createRenderPipeline({
        layout: device.createPipelineLayout({ bindGroupLayouts: [this.lutBgl] }),
        vertex: { module: lutMod, entryPoint: 'vs_lut', buffers: [lutVbuf] },
        fragment: { module: lutMod, entryPoint: 'fs_lut', targets: [{ format: this.fmt }] },
        primitive: { topology: 'triangle-list' },
      });
      this.lutPipeAdd = device.createRenderPipeline({
        layout: device.createPipelineLayout({ bindGroupLayouts: [this.lutBgl] }),
        vertex: { module: lutMod, entryPoint: 'vs_lut', buffers: [lutVbuf] },
        fragment: { module: lutMod, entryPoint: 'fs_lut', targets: [{ format: this.fmt,
          blend: { color: { srcFactor: 'src-alpha', dstFactor: 'one', operation: 'add' },
                   alpha: { srcFactor: 'one', dstFactor: 'one', operation: 'add' } } }] },
        primitive: { topology: 'triangle-list' },
      });
      // REGULAR-ALPHA (src-a / 1-src-a) LUT variant — the exact-costume-palette twin of
      // alphaPipe (a LUT-routed effect part gets MODE-2 alpha, not additive). See alphaPipe.
      this.lutAlphaPipe = device.createRenderPipeline({
        layout: device.createPipelineLayout({ bindGroupLayouts: [this.lutBgl] }),
        vertex: { module: lutMod, entryPoint: 'vs_lut', buffers: [lutVbuf] },
        fragment: { module: lutMod, entryPoint: 'fs_lut', targets: [{ format: this.fmt,
          blend: { color: { srcFactor: 'src-alpha', dstFactor: 'one-minus-src-alpha', operation: 'add' },
                   alpha: { srcFactor: 'one', dstFactor: 'one-minus-src-alpha', operation: 'add' } } }] },
        primitive: { topology: 'triangle-list' },
      });
      this.lutBuf = device.createBuffer({ size: this.maxGroups * this.LUT_PG * 16,
        usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST });
      this.lutData = new Float32Array(this.maxGroups * this.LUT_PG * 4);
      this.idxInst = device.createBuffer({ size: this.maxInst * INST_STRIDE, usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST });
      this.idxInstData = new Float32Array(this.maxInst * INST_FLOATS);
      this.skinOverride = {};             // cid -> [[r,g,b,a]*16] body-bank override (skin)

      this.ok = true;
    } catch (e) { console.error('[sprite-gpu] init failed, Canvas2D fallback:', e); this.ok = false; }
    return this.ok;
  }

  // default body palette (rip palette[0..15]) for a char, [[r,g,b],...] 0-255
  setCharPalette(charId, pal128) {
    if (!pal128) return;
    this.charPal[charId] = pal128.map(c => [c[0] / 255, c[1] / 255, c[2] / 255]);
  }

  setAtlas(charId, imageBitmap) {
    if (!this.ok || !imageBitmap) return;
    const w = imageBitmap.width, h = imageBitmap.height;
    const maxDim = (this.dev.limits && this.dev.limits.maxTextureDimension2D) || 8192;
    if (w > maxDim || h > maxDim) {
      console.warn('[sprite-gpu] atlas', charId, w + 'x' + h, '> maxTextureDimension2D', maxDim, '— skipped (needs a wider rebuild)');
      const prev = this.chars[charId]; this.chars[charId] = { skip: true, _pal: prev && prev._pal }; return;
    }
    try {
      const tex = this.dev.createTexture({
        size: [w, h], format: 'rgba8unorm',
        usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST | GPUTextureUsage.RENDER_ATTACHMENT,
      });
      this.dev.queue.copyExternalImageToTexture({ source: imageBitmap }, { texture: tex }, [w, h]);
      const bg = this.dev.createBindGroup({ layout: this.bgl, entries: [
        { binding: 0, resource: tex.createView() },
        { binding: 1, resource: this.sampler },
        { binding: 2, resource: { buffer: this.ubuf } },
        { binding: 3, resource: { buffer: this.palBuf } },
      ]});
      this.chars[charId] = { tex, bg, w, h };
    } catch (e) { console.error('[sprite-gpu] setAtlas failed', charId, e); this.chars[charId] = { skip: true }; }
  }

  // ---- EXACT palette-LUT atlas registration ----
  // lut = { bankList:[0,1,3], bodyBank:0, banks:[[ [r,g,b,a]*16 ], ...] } from
  // PLxx_lut.json (tools/rgb_to_indexed.py). idxBitmap = the _idx.png data texture.
  // When a cid has BOTH an indexed atlas and a LUT, render() draws it through the
  // exact LUT path; otherwise the RGB path is used (unchanged fallback).
  setCharLUT(charId, lut) { if (lut && lut.banks) this.charLUT[charId] = lut; }

  // SKIN hook: override a char's body bank (bodyBank) with 16 [r,g,b,a] colors (0-255).
  // Pass null/undefined to clear (revert to the live PVR body palette / base). The
  // SurrealDB skin system stores palette_hex per char -> expand to 16 RGBA here.
  setSkin(charId, bodyColors16) {
    if (bodyColors16 && bodyColors16.length) this.skinOverride[charId] = bodyColors16;
    else delete this.skinOverride[charId];
  }

  setIndexedAtlas(charId, imageBitmap) {
    if (!this.ok || !imageBitmap) return;
    const w = imageBitmap.width, h = imageBitmap.height;
    const maxDim = (this.dev.limits && this.dev.limits.maxTextureDimension2D) || 8192;
    if (w > maxDim || h > maxDim) {
      console.warn('[sprite-gpu] idx atlas', charId, w + 'x' + h, '> max', maxDim, '— skipped');
      this.idxChars[charId] = { skip: true }; return;
    }
    try {
      // rgba8unorm, NEAREST sampling (the R/G channels are data bytes, not colors).
      const tex = this.dev.createTexture({ size: [w, h], format: 'rgba8unorm',
        usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST | GPUTextureUsage.RENDER_ATTACHMENT });
      this.dev.queue.copyExternalImageToTexture({ source: imageBitmap, flipY: false }, { texture: tex }, [w, h]);
      const bg = this.dev.createBindGroup({ layout: this.lutBgl, entries: [
        { binding: 0, resource: tex.createView() },
        { binding: 1, resource: this.sampler },
        { binding: 2, resource: { buffer: this.ubuf } },
        { binding: 3, resource: { buffer: this.lutBuf } },
      ]});
      this.idxChars[charId] = { tex, bg, w, h };
    } catch (e) { console.error('[sprite-gpu] setIndexedAtlas failed', charId, e); this.idxChars[charId] = { skip: true }; }
  }

  // The hit-spark strip (N frames of frameW wide, side by side).
  setSparkAtlas(imageBitmap, frameW) {
    if (!this.ok || !imageBitmap) return;
    const w = imageBitmap.width, h = imageBitmap.height;
    try {
      const tex = this.dev.createTexture({ size: [w, h], format: 'rgba8unorm',
        usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST | GPUTextureUsage.RENDER_ATTACHMENT });
      this.dev.queue.copyExternalImageToTexture({ source: imageBitmap }, { texture: tex }, [w, h]);
      this.sparkBg = this.dev.createBindGroup({ layout: this.sparkBgl, entries: [
        { binding: 0, resource: tex.createView() },
        { binding: 1, resource: this.sampler },
        { binding: 2, resource: { buffer: this.ubuf } },
      ]});
      this.sparkW = w; this.sparkH = h; this.sparkFrame = frameW || 64;
    } catch (e) { console.error('[sprite-gpu] setSparkAtlas failed', e); }
  }

  // Map a PVR blend byte (src<<4|dst) to the matching pipeline for a route (LUT vs RGB).
  // The 4 render states MvC2 uses for these lists (sh4-re: the global TSP SRC/DST word set
  // once per list, NOT a per-part field — so we can't bake it offline, we classify at draw):
  //   0x10 src=ONE  dst=ZERO      -> OPAQUE / replace   (pipe / lutPipe)          bodies, opaque props
  //   0x45 src=srcA dst=1-srcA    -> MODE-2 ALPHA       (alphaPipe / lutAlphaPipe) cat 1-4 effects DEFAULT
  //   0x41 src=srcA dst=ONE       -> ALPHA-ADD          (pipeAdd / lutPipeAdd)     true glow/energy
  //   0x11 src=ONE  dst=ONE       -> pure ADD           (pipeAdd / lutPipeAdd approx; genuine one/one
  //                                                       palette pipe deferred with the gfx1 BODYCAP pass)
  // Unknown/legacy dst==ONE -> ALPHA (safe default; corrects the old too-bright alpha-add).
  _pipeFor(lut, blend) {
    switch (blend & 0xff) {
      case 0x45: return lut ? this.lutAlphaPipe : this.alphaPipe;   // regular alpha
      case 0x41: return lut ? this.lutPipeAdd  : this.pipeAdd;      // alpha-add (src-a/one)
      case 0x11: return lut ? this.lutPipeAdd  : this.pipeAdd;      // pure-add -> alpha-add approx (deferred)
      case 0x10: case 0x00: return lut ? this.lutPipe : this.pipe;  // opaque / replace
      default:   return ((blend & 0xf) === 1) ? (lut ? this.lutAlphaPipe : this.alphaPipe)
                                              : (lut ? this.lutPipe : this.pipe);
    }
  }

  // sprites: [{charId, slot, sx,sy,sw,sh (atlas px), dx,dy,dw,dh (canvas px), flip}]
  // T: TextureManager (T._pal = live PVR palette RAM, RGBA, 1024 entries).
  render(sprites, dbg, T, sparks, effects) {
    if (!this.ok) return;
    const cw = this.canvas.width, ch = this.canvas.height;
    this.dev.queue.writeBuffer(this.ubuf, 0, new Float32Array([cw, ch, 0, 0]));
    this.PP.ensureTargets(cw, ch, (dbg && dbg.resScale) || 1);
    const rt = this.PP.getRenderTarget();
    const livePal = (this.recolor && T && T._pal) ? T._pal : null;

    // RUN-BASED SINGLE-ORDER DRAW (2026-08-29, audit defects #1+#2). The emitter
    // (sprite-client.buildEmitterDrawList) hands us `sprites` ALREADY in the game's global
    // draw order: per-object layer bucket (layer*1e5), then intra-assembly partZ (record 0
    // front-most). The OLD code split that order into two maps (byChar RGB / byCharIdx LUT)
    // drawn in PATH order, so every additive effect (RGB) landed BEHIND every opaque body
    // (LUT) and was ERASED by it. Instead we now walk `sprites` ONCE in the given order and
    // emit RUNS: a run = maximal consecutive sprites sharing (route ∈ {rgb,lut}, cid,
    // costume, isAdd). Each run draws with its own pipeline + bind group, so the global
    // z/layer order is preserved AND we still bind exactly one atlas per draw (more, cheap
    // draw calls). Cid-contiguity is NO LONGER required — that constraint only existed for
    // the old per-cid grouping. RGB and LUT keep SEPARATE instance buffers (this.inst /
    // this.idxInst), so each retains its full maxInst=512 capacity (no per-path regression).
    // BLEND BYTE (PVR src<<4|dst; codes 0=zero 1=one 4=srcA 5=invSrcA — the convention
    // sprite-client + the wire already use). Bodies carry no blend -> OPAQUE 0x10 (unchanged:
    // punch-through REPLACE). Effects carry the runtime PVR blend the sh4-re resolved
    // (cat 1-4 default 0x45 = MODE-2 alpha, per tape-adapter). This replaces the old 1-bit
    // isAdd: 0x45 (alpha) used to fall through to the OPAQUE pipe (no alphaPipe existed) and
    // 0x01/0x41 (dst=ONE) all mapped to the too-bright additive pipeAdd.
    const blendOf = (s) => (s.blend != null) ? (s.blend & 0xff) : 0x10;
    const routeOf = (s) => {
      const ic = this.idxChars[s.charId], lut = this.charLUT[s.charId];
      if (s.costume != null && ic && ic.bg && lut) return 'lut';   // exact costume-LUT body
      const c = this.chars[s.charId];
      return (c && c.bg) ? 'rgb' : null;                            // RGB effect/satellite/body; null = no atlas -> skip
    };

    // ── Pass A: assign a palette group slot per (route,cid[,costume]) in FIRST-APPEARANCE
    // order and fill its palette (RGB: 128 default + 128 live; LUT: one costume body bank).
    // Separate group counters/tables per route (unchanged from the old design), so gi/gj
    // each cap at maxGroups and palBuf/lutBuf are filled EXACTLY as before (first-appearance
    // slot/costume drive the palette — identical to the old list[0] behavior).
    const PG = this.LUT_PG;
    const rgbGroup = new Map();    // cid -> gi (palBase = gi*256)
    const lutGroup = new Map();    // "cid|costume" -> gj (LUT group index)
    let gi = 0, gj = 0;
    for (const s of sprites) {
      const r = routeOf(s);
      if (r === 'rgb') {
        if (rgbGroup.has(s.charId) || gi >= this.maxGroups) continue;
        const cid = s.charId, palBase = gi * 256, def = this.charPal[cid];
        const bankE = 256 + 128 * (s.slot | 0);
        for (let k = 0; k < 128; k++) {
          const od = (palBase + k) * 4, ol = (palBase + 128 + k) * 4;
          const dc = def && def[k]; const dr = dc ? dc[0] : 0, dg = dc ? dc[1] : 0, db = dc ? dc[2] : 0;
          this.palData[od] = dr; this.palData[od + 1] = dg; this.palData[od + 2] = db; this.palData[od + 3] = 1;
          if (livePal) {
            const pe = (bankE + k) * 4;
            this.palData[ol] = livePal[pe] / 255; this.palData[ol + 1] = livePal[pe + 1] / 255; this.palData[ol + 2] = livePal[pe + 2] / 255; this.palData[ol + 3] = 1;
          } else { this.palData[ol] = dr; this.palData[ol + 1] = dg; this.palData[ol + 2] = db; this.palData[ol + 3] = 1; }
        }
        rgbGroup.set(cid, gi); gi++;
      } else if (r === 'lut') {
        const key = s.charId + '|' + (s.costume | 0);
        if (lutGroup.has(key) || gj >= this.maxGroups) continue;
        const cid = s.charId, lut = this.charLUT[cid];
        const bankE = 256 + 128 * (s.slot | 0);
        const skin = this.skinOverride[cid];
        const costume = (s.costume | 0), bodyBank = (lut.bodyBank | 0);
        let bank = bodyBank + costume * 8; if (bank >= lut.banks.length) bank = bodyBank;
        const src16 = lut.banks[bank] || lut.banks[bodyBank] || lut.banks[0];
        for (let i = 0; i < PG; i++) {
          const o = (gj * PG + i) * 4;
          let r0 = 0, g0 = 0, bl = 0, a = 0;
          const src = src16 && src16[i];
          if (src) { r0 = src[0]/255; g0 = src[1]/255; bl = src[2]/255; a = src[3]/255; }
          if (skin && skin[i]) { r0 = skin[i][0]/255; g0 = skin[i][1]/255; bl = skin[i][2]/255; a = skin[i][3]/255; }
          else if (livePal && i > 0) {  // i0 stays transparent; live PVR body bank drives flash/skin
            const pe = (bankE + i) * 4;
            r0 = livePal[pe]/255; g0 = livePal[pe+1]/255; bl = livePal[pe+2]/255; a = 1;
          }
          this.lutData[o] = r0; this.lutData[o+1] = g0; this.lutData[o+2] = bl; this.lutData[o+3] = a;
        }
        lutGroup.set(key, gj); gj++;
      }
    }
    if (gi) this.dev.queue.writeBuffer(this.palBuf, 0, this.palData, 0, gi * 256 * 4);
    if (gj) this.dev.queue.writeBuffer(this.lutBuf, 0, this.lutData, 0, gj * PG * 4);

    // ── Pass B: write instances in GLOBAL ORDER into their route's own buffer (RGB ->
    // this.inst, LUT -> this.idxInst) and record the run list. NO additive-last reorder
    // (that was Defect #3 — it broke emitter z-order within a mixed group); the additive
    // pipeline is now selected per-run instead. location-3 = palBase (RGB) or LUT group
    // index (LUT); each shader reads its own storage buffer so the value matches the pipe.
    let n = 0, ni = 0; const runs = []; let cur = null;
    for (const s of sprites) {
      const r = routeOf(s); if (!r) continue;
      const lutRun = (r === 'lut');
      let grpVal, bufData, idx, c;
      if (lutRun) {
        const g = lutGroup.get(s.charId + '|' + (s.costume | 0));
        if (g == null || ni >= this.maxInst) continue;
        grpVal = g; bufData = this.idxInstData; idx = ni; c = this.idxChars[s.charId];
      } else {
        const g = rgbGroup.get(s.charId);
        if (g == null || n >= this.maxInst) continue;
        grpVal = g * 256; bufData = this.instData; idx = n; c = this.chars[s.charId];
      }
      const o = idx * INST_FLOATS;
      bufData[o] = s.dx; bufData[o + 1] = s.dy; bufData[o + 2] = s.dw; bufData[o + 3] = s.dh;
      bufData[o + 4] = s.sx / c.w; bufData[o + 5] = s.sy / c.h;
      bufData[o + 6] = (s.sx + s.sw) / c.w; bufData[o + 7] = (s.sy + s.sh) / c.h;
      bufData[o + 8] = s.flip ? 1 : 0; bufData[o + 9] = grpVal;
      const t = s.tint;
      bufData[o + 10] = t ? t[0] : 0; bufData[o + 11] = t ? t[1] : 0; bufData[o + 12] = t ? t[2] : 0;
      bufData[o + 13] = s.flipY ? 1 : 0;   // part Y-mirror (flags & 0x8000)
      const blend = blendOf(s), cost = lutRun ? (s.costume | 0) : -1;
      if (cur && cur.lut === lutRun && cur.cid === s.charId && cur.costume === cost && cur.blend === blend) {
        cur.count++;
      } else {
        cur = { lut: lutRun, cid: s.charId, costume: cost, blend, first: idx, count: 1 };
        runs.push(cur);
      }
      if (lutRun) ni++; else n++;
    }
    if (n)  this.dev.queue.writeBuffer(this.inst,    0, this.instData,    0, n  * INST_FLOATS);
    if (ni) this.dev.queue.writeBuffer(this.idxInst, 0, this.idxInstData, 0, ni * INST_FLOATS);

    // hit-spark instances (additive): dest center+size, atlas frame UV, alpha
    let sn = 0;
    if (sparks && sparks.length && this.sparkBg) {
      const nframes = Math.max(1, Math.floor(this.sparkW / this.sparkFrame));
      for (const sp of sparks) {
        if (sn >= 32) break;
        const o = sn * 9, f = Math.min(nframes - 1, sp.frame | 0);
        this.sparkInstData[o] = sp.x; this.sparkInstData[o+1] = sp.y; this.sparkInstData[o+2] = sp.size; this.sparkInstData[o+3] = sp.size;
        this.sparkInstData[o+4] = f * this.sparkFrame / this.sparkW; this.sparkInstData[o+5] = 0;
        this.sparkInstData[o+6] = (f + 1) * this.sparkFrame / this.sparkW; this.sparkInstData[o+7] = 1;
        this.sparkInstData[o+8] = sp.alpha;
        sn++;
      }
      if (sn) this.dev.queue.writeBuffer(this.sparkInst, 0, this.sparkInstData, 0, sn * 9);
    }

    // PERSIST-ON-EMPTY: nothing to draw this frame (no body/idx instances, no
    // sparks, no effect quads). Bail BEFORE the encoder/blit so we never touch
    // getCurrentTexture() — the opaque swap-chain then re-presents the last
    // good frame instead of a cleared (black) one. This is the tag-in fix:
    // the brief drawn==0 gap between the old pose closing and the new pose's
    // atlas/sprite_id arriving no longer blanks the canvas. Honors a live
    // override (window._spritePersistEmpty) for debugging without redeploy.
    const persist = (typeof window !== 'undefined' && window._spritePersistEmpty != null)
      ? !!window._spritePersistEmpty : this.persistEmpty;
    const willDraw = n + ni + sn + ((effects && effects.length) ? effects.length : 0);
    // OBSERVABILITY (2026-08-29): distinguish a TRANSIENT empty (tag-in gap — the case
    // the persist bail is for) from a PERMANENT one where we were HANDED a non-empty draw
    // list but NOTHING routed to a usable atlas (n==ni==0). The latter is silent BLACK from
    // frame 1 — e.g. a part atlas skipped for exceeding maxTextureDimension2D (setAtlas ->
    // {skip:true}, no .bg) or an unregistered cid -> routeOf()==null for every item. A
    // stubbed-WebGPU smoke test never trips it (the stub ignores the texture-size limit and
    // never runs routeOf against a skipped atlas), so it "passes" while real WebGPU shows a
    // blank canvas (the reported FALSE PASS). Log the per-cid atlas state so the true cause
    // is visible instead of a black screen. Does NOT change render behavior.
    if (!n && !ni && sprites && sprites.length) {
      this._noRoute = (this._noRoute | 0) + 1;
      if (this._noRoute <= 3 || this._noRoute % 300 === 0) {
        const seen = [...new Set(sprites.map(s => s.charId))];
        const st = seen.map(c => {
          const r = this.chars[c], ix = this.idxChars[c], lu = this.charLUT[c];
          const rs = !r ? 'none' : r.skip ? 'SKIP>maxTex' : r.bg ? 'ok' : 'no-bg';
          const is = !ix ? 'none' : ix.skip ? 'SKIP>maxTex' : ix.bg ? 'ok' : 'no-bg';
          return `cid${c}[rgb:${rs} idx:${is} lut:${lu ? 'y' : 'n'}]`;
        }).join(' ');
        console.warn(`[sprite-gpu] ${sprites.length} draw items but 0 routed to a usable atlas — NOTHING will draw (blank). ${st}`);
      }
    }
    if (persist && !willDraw) { this._skippedEmpty = (this._skippedEmpty | 0) + 1; return; }

    const enc = this.dev.createCommandEncoder();
    const pass = enc.beginRenderPass({
      colorAttachments: [{ view: rt.colorView, clearValue: { r:0,g:0,b:0,a:0 }, loadOp: 'clear', storeOp: 'store' }],
    });
    // Draw the RUNS IN ORDER (global z/layer from the emitter). Switch pipeline / vertex
    // buffer / bind group only when they change between runs. RGB runs read this.inst
    // (palBuf via chars[cid].bg); LUT runs read this.idxInst (lutBuf via idxChars[cid].bg);
    // _pipeFor(run.blend) -> the per-run blend pipeline (opaque / alpha / alpha-add). Because
    // runs are emitted in the emitter's global draw order, an effect now paints OVER a body it
    // overlaps (Defect #1) and a higher-layer object draws in front of a lower-layer one across
    // owners (Defect #2), while bodies keep punch-through REPLACE (blend 0x10 -> this.pipe).
    if (runs.length) {
      let curPipe = null, curBuf = null;
      for (const run of runs) {
        if (!run.count) continue;
        const pipe = this._pipeFor(run.lut, run.blend);
        if (pipe !== curPipe) { pass.setPipeline(pipe); curPipe = pipe; }
        const buf = run.lut ? this.idxInst : this.inst;
        if (buf !== curBuf) { pass.setVertexBuffer(0, buf); curBuf = buf; }
        pass.setBindGroup(0, (run.lut ? this.idxChars[run.cid] : this.chars[run.cid]).bg);
        pass.draw(6, run.count, 0, run.first);
      }
    }
    if (sn) {                                    // additive hit-spark pass, over the characters
      pass.setPipeline(this.sparkPipe);
      pass.setVertexBuffer(0, this.sparkInst);
      pass.setBindGroup(0, this.sparkBg);
      pass.draw(6, sn, 0, 0);
    }
    // live TA effect quads (beams / energy / lightning) — additive, per-quad texture
    if (effects && effects.length) {
      let m = 0;
      for (const ef of effects) { if (m >= 48) break; const o = m * 9;
        this.fxInstData[o]=ef.x; this.fxInstData[o+1]=ef.y; this.fxInstData[o+2]=ef.w; this.fxInstData[o+3]=ef.h;
        this.fxInstData[o+4]=0; this.fxInstData[o+5]=0; this.fxInstData[o+6]=1; this.fxInstData[o+7]=1;
        this.fxInstData[o+8]=ef.alpha != null ? ef.alpha : 1; m++; }
      if (m) {
        this.dev.queue.writeBuffer(this.fxInst, 0, this.fxInstData, 0, m * 9);
        pass.setPipeline(this.sparkPipe);
        pass.setVertexBuffer(0, this.fxInst);
        let i = 0;
        for (const ef of effects) { if (i >= 48) break;
          try {
            const bg = this.dev.createBindGroup({ layout: this.sparkBgl, entries: [
              { binding: 0, resource: ef.tex.createView() },
              { binding: 1, resource: ef.samp || this.sampler },
              { binding: 2, resource: { buffer: this.ubuf } } ]});
            pass.setBindGroup(0, bg); pass.draw(6, 1, 0, i);
          } catch (_e) {}
          i++;
        }
      }
    }
    pass.end();
    this.PP.blit(enc, this.ctx.getCurrentTexture().createView(), cw, ch, dbg || {});
    this.dev.queue.submit([enc.finish()]);
  }
}
