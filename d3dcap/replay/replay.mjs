// RETRO RECEIPTS — PATH B replayer: execute a captured Steam MvC2 frame on WebGPU.
//
// Feeds the renderer Steam's OWN captured data and renders into an offscreen target matching the
// game's scene render target. That isolates one question — "is our renderer correct?" — from the
// separate question of whether the agent's tape carries enough state to reconstruct a frame.
//
// ⚠ Reads back via copyTextureToBuffer, NEVER off a canvas. Canvas readback would reintroduce
// premultiplied-alpha and colour-space mangling by the compositor; the canvas here is for eyeballs.
//
// ⚠⚠ A pixel diff that improves is a MEASUREMENT, not a mechanism. A match shows our translation of
// the captured state reproduces the pixels; it establishes nothing about MvC2 itself.

import { loadPack, createResources, vertexLayoutFor } from './resources.mjs';
import { toBlendState, toWriteMask, toDepthStencil, applyDepthBias, toPrimitive, applyViewport,
         pipelineKey } from './state.mjs';

// Shader variants come from the pack, where classify_shaders.py put them after reading the actual
// DISASSEMBLY, keyed by CSO content hash (pointers are per-launch and would rot across captures).
//
// ⚠ An earlier version guessed the variant from the SHAPE of what a draw bound — "a texture in slot 1
// means this is a character". Measured on frame 4261 that captured 214 draws spanning FIVE pixel
// shaders and THREE vertex shaders, including the HUD bank and stage pages, and ran all of them
// through the indexed path with a pass-through vertex shader. Draws whose VS actually transforms by
// world x view-projection were treated as already in NDC, so their geometry landed nowhere near
// where it belonged. Never infer a shader from its bindings.
// The fragment entry point depends on BOTH the pixel shader's class and which vertex shader the draw
// pairs with: WebGPU requires the fragment input signature to match the vertex output signature, and
// the two vertex shaders emit different varying counts (vs_world 4, vs_flat 3). Pairing across them
// is a pipeline-creation error, not a subtle wrongness.
const FS_ENTRY = {
    'vs_world|opaque':   'fs_stage_opaque',
    'vs_world|texalpha': 'fs_stage_texalpha',
    'vs_flat|opaque':    'fs_flat_opaque',
    'vs_flat|texalpha':  'fs_hud',
    'vs_flat|indexed':   'fs_character',
};

function variantFor(d) {
    const vs = d.vsVariant || 'vs_world';
    const cls = d.psVariant || 'opaque';        // a null pixel shader = depth-only, writeMask 0
    const fs = FS_ENTRY[`${vs}|${cls}`];
    if (!fs) {
        // The flycast model says the indexed path never pairs with a transforming vertex shader.
        // If that ever happens, fail loudly rather than silently picking a plausible entry point.
        throw new Error(`no fragment entry for ${vs} + ${cls}`);
    }
    return { vs, fs };
}

/** Coarse class for the differential-reduction switches. */
function classOf(d) {
    return d.psVariant === 'indexed' ? 'character' : 'stage';
}

export class Replayer {
    constructor(device, format = 'bgra8unorm') {
        this.device = device;
        this.format = format;           // matches the captured scene RT (fmt 87 = B8G8R8A8_UNORM)
        this.pipelines = new Map();
        this.bindGroups = new Map();
        // INTERNAL RESOLUTION (2026-09-03): multiplies the captured scene RT and every per-draw viewport. The capture's
        // own RT is 2048x1024 with the game viewport at 1280x960 (= 2x of 640x480), so scale 1 == the capture, scale 2
        // == 4x of native. Vertex positions are already NDC on the sprite and world paths (sprite.wgsl), so a larger
        // viewport is a genuinely higher-resolution raster of the same draws. Set before attach().
        this.scale = 1;
    }

    async load(url) {
        return this.attach(await loadPack(url));
    }

    /**
     * Attach an already-parsed pack. A SEQUENCE uses this: one Replayer is built once and then
     * `setFrame` swaps only what differs per frame, so the shader module, the bind group layouts and
     * the pipeline cache are all built once for the whole playback.
     */
    async attach(pack, shared = null) {
        this.shared = shared;
        this.pack = pack;
        this.res = createResources(this.device, this.pack, shared);
        this.module = this.device.createShaderModule({
            // no-store: these files change between runs; a cached shader shows up as a bogus
            // "entry point doesn't exist" error rather than as a cache problem.
            code: await (await fetch(new URL('./sprite.wgsl', import.meta.url), { cache: 'no-store' })).text(),
        });

        // Fixed layouts: group 0 is the per-draw uniform slice (dynamic offset), group 1 the textures
        // and samplers. Keeping them constant is what lets the pipeline cache stay ~30 entries.
        this.bgl0 = this.device.createBindGroupLayout({
            entries: [{ binding: 0, visibility: GPUShaderStage.VERTEX | GPUShaderStage.FRAGMENT,
                        buffer: { type: 'uniform', hasDynamicOffset: true, minBindingSize: 160 } }],
        });
        this.bgl1 = this.device.createBindGroupLayout({
            entries: [
                { binding: 0, visibility: GPUShaderStage.FRAGMENT, sampler: {} },
                { binding: 1, visibility: GPUShaderStage.FRAGMENT, sampler: {} },
                { binding: 2, visibility: GPUShaderStage.FRAGMENT, texture: {} },
                { binding: 3, visibility: GPUShaderStage.FRAGMENT, texture: {} },
            ],
        });
        this.layout = this.device.createPipelineLayout({ bindGroupLayouts: [this.bgl0, this.bgl1] });
        this.bg0 = this.device.createBindGroup({
            layout: this.bgl0,
            entries: [{ binding: 0, resource: { buffer: this.res.uniformBuffer, size: 160 } }],
        });

        const rt = this.pack.head.sceneRT;
        this.width = Math.round(rt.w * this.scale);
        this.height = Math.round(rt.h * this.scale);
        return this;
    }

    /**
     * Point the replayer at another frame of the same capture.
     *
     * Only the per-frame resources change: the vertex/index buffers and the per-draw uniform slice.
     * The pipeline cache survives because its key is (shader hash, layout hash, blend/depth/raster
     * state) -- all content-derived, none of it per frame. The bind-group cache survives because its
     * key is the texture's "pointer#generation", which IS a content identity, and the shared texture
     * map guarantees one view per content.
     */
    setFrame(pack) {
        const entry = this.prepare(pack);
        this.use(entry);
        return entry.res.uploaded;
    }

    /**
     * Build one frame's per-frame resources WITHOUT switching to them.
     *
     * Playback builds every frame up front and then only switches. Building during playback means
     * three GPUBuffer allocations and a bind group every 16 ms, which is exactly the kind of steady
     * allocation that shows up as intermittent hitching rather than a lower frame rate.
     */
    prepare(pack) {
        const res = createResources(this.device, pack, this.shared);
        const bg0 = this.device.createBindGroup({
            layout: this.bgl0,
            entries: [{ binding: 0, resource: { buffer: res.uniformBuffer, size: 160 } }],
        });
        return { pack, res, bg0 };
    }

    /** Switch to a prepared frame. Nothing is allocated here. */
    use(entry) {
        this.pack = entry.pack;
        this.res = entry.res;
        this.bg0 = entry.bg0;
    }

    /** The draw's vertex layout, or null when its input layout cannot feed the shader. */
    _layout(d) {
        if (!this._layoutCache) this._layoutCache = new Map();
        const key = `${d.il}:${d.stride}`;
        if (!this._layoutCache.has(key)) {
            const elements = this.pack.head.inputLayouts?.[d.il];
            if (!elements) throw new Error(`pack has no input layout ${d.il} -- repack the frame`);
            this._layoutCache.set(key, vertexLayoutFor(d.stride, elements));
        }
        return this._layoutCache.get(key);
    }

    _pipeline(d, variant, layout) {
        // The vertex layout is part of the pipeline, so it must be part of the key. Leaving it out
        // lets the first draw's layout be reused for every later draw with the same states.
        const key = pipelineKey(d, `${variant.vs}|${variant.fs}`, 'triangle-list')
                  + `:${d.il}:${d.stride}`;
        let p = this.pipelines.get(key);
        if (p) return p;

        // Both entry points come from the disassembly, per draw. The pairing is NOT interchangeable:
        // vs_flat emits three varyings with uv at TEXCOORD2 and does no transform at all.
        const vsEntry = variant.vs;
        const fsEntry = variant.fs;

        const depthStencil = applyDepthBias(toDepthStencil(d.depth), d.raster);
        const blend = toBlendState(d.blend);

        p = this.device.createRenderPipeline({
            layout: this.layout,
            vertex: { module: this.module, entryPoint: vsEntry, buffers: [layout] },
            fragment: {
                module: this.module, entryPoint: fsEntry,
                targets: [{ format: this.format, writeMask: toWriteMask(d.blend),
                            ...(blend ? { blend } : {}) }],
            },
            primitive: toPrimitive(d.raster, 'triangle-list'),
            depthStencil,
        });
        this.pipelines.set(key, p);
        return p;
    }

    _bindGroup(d) {
        const t0 = d.tex?.[0] || 'none', t1 = d.tex?.[1] || 'none';
        const s0 = d.samp?.[0], s1 = d.samp?.[1];
        const key = `${t0}|${t1}|${s0 ? `${s0.filter}:${s0.u}` : 'n'}|${s1 ? `${s1.filter}:${s1.u}` : 'n'}`;
        let bg = this.bindGroups.get(key);
        if (bg) return bg;
        bg = this.device.createBindGroup({
            layout: this.bgl1,
            entries: [
                { binding: 0, resource: this.res.getSampler(s0) },
                { binding: 1, resource: this.res.getSampler(s1 || s0) },
                { binding: 2, resource: this.res.texFor(d.tex?.[0]) },
                { binding: 3, resource: this.res.texFor(d.tex?.[1]) },
            ],
        });
        this.bindGroups.set(key, bg);
        return bg;
    }

    /**
     * Render the frame into a fresh offscreen texture and return it.
     * @param {object} opts
     *   opts.only      - 'character' | 'stage' | null. Differential reduction: render one class of
     *                    draws at a time so a failure names its own cause.
     *   opts.cullNone  - force cullMode 'none'. For the first run: with culling off a draw can never
     *                    be LOST, so a failure is unambiguously not a winding-mapping error.
     */
    render(opts = {}) {
        const { head } = this.pack;
        // Reused across calls. Playback renders 60 of these a second; allocating a 2048x1024 colour
        // target and a depth buffer per frame hands the GC 16 MB every 16 ms.
        // TEXTURE_BINDING is here so a player can BLIT this to a canvas instead of reading it back --
        // readback is right for a diff and far too slow for playback.
        const target = this._target ??= this.device.createTexture({
            size: { width: this.width, height: this.height }, format: this.format,
            usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_SRC
                 | GPUTextureUsage.TEXTURE_BINDING,
        });
        const depth = this._depth ??= this.device.createTexture({
            size: { width: this.width, height: this.height }, format: 'depth24plus-stencil8',
            usage: GPUTextureUsage.RENDER_ATTACHMENT,
        });

        // The captured scene-RT clear is [0,0,0,0] and the depth clear is 1.0 (forward Z).
        // WebGPU requires stencil load/store ops whenever the format carries stencil, even unused.
        const enc = this.device.createCommandEncoder();
        const pass = enc.beginRenderPass({
            colorAttachments: [{
                view: target.createView(), loadOp: 'clear', storeOp: 'store',
                clearValue: { r: 0, g: 0, b: 0, a: 0 },
            }],
            depthStencilAttachment: {
                view: depth.createView(),
                depthLoadOp: 'clear', depthStoreOp: 'store', depthClearValue: 1.0,
                stencilLoadOp: 'clear', stencilStoreOp: 'discard', stencilClearValue: 0,
            },
        });

        pass.setIndexBuffer(this.res.indexBuffer, 'uint32');

        const stats = { drawn: 0, skipped: 0, noLayout: 0, byVariant: {} };
        head.draws.forEach((d, i) => {
            const variant = variantFor(d);
            const cls = classOf(d);
            if (opts.only && cls !== opts.only) { stats.skipped++; return; }

            const layout = this._layout(d);
            if (!layout) { stats.noLayout++; return; }

            const dd = opts.cullNone ? { ...d, raster: { ...(d.raster || {}), cull: 1 } } : d;
            pass.setPipeline(this._pipeline(dd, variant, layout));
            // THE VERTEX OFFSET IS A BYTE OFFSET AND MUST BE BOUND AS ONE. Half the draws in a frame
            // start part-way through a vertex (voff % stride != 0), so it cannot be folded into the
            // first index -- doing that silently fetched POSITION out of the middle of the previous
            // vertex for 382 of 760 draws and cost a quarter of the frame's coverage.
            pass.setVertexBuffer(0, this.res.vertexBuffer, d.voff);
            pass.setBindGroup(0, this.bg0, [i * this.res.uniformStride]);
            pass.setBindGroup(1, this._bindGroup(d));
            applyViewport(pass, this.scale === 1 || !d.vp ? d.vp
                : [d.vp[0] * this.scale, d.vp[1] * this.scale, d.vp[2] * this.scale, d.vp[3] * this.scale, ...d.vp.slice(4)]);
            pass.drawIndexed(d.indexCount, 1, d.firstIndex, 0, 0);

            stats.drawn++;
            const tag = `${variant.vs}+${variant.fs}`;
            stats.byVariant[tag] = (stats.byVariant[tag] || 0) + 1;
        });

        pass.end();
        this.device.queue.submit([enc.finish()]);
        return { target, depth, stats, pipelines: this.pipelines.size };
    }

    /** Read a rendered texture back as raw bytes. Rows are unpadded (bytesPerRow is 256-aligned). */
    async readback(texture) {
        const bpr = Math.ceil(this.width * 4 / 256) * 256;
        const buf = this.device.createBuffer({
            size: bpr * this.height, usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ,
        });
        const enc = this.device.createCommandEncoder();
        enc.copyTextureToBuffer({ texture }, { buffer: buf, bytesPerRow: bpr, rowsPerImage: this.height },
                                { width: this.width, height: this.height });
        this.device.queue.submit([enc.finish()]);
        await buf.mapAsync(GPUMapMode.READ);
        const padded = new Uint8Array(buf.getMappedRange()).slice();
        buf.unmap(); buf.destroy();

        // strip row padding
        const out = new Uint8Array(this.width * this.height * 4);
        for (let y = 0; y < this.height; y++) {
            out.set(padded.subarray(y * bpr, y * bpr + this.width * 4), y * this.width * 4);
        }
        return out;
    }
}
