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

import { loadPack, createResources, VERTEX_LAYOUT } from './resources.mjs';
import { toBlendState, toWriteMask, toDepthStencil, applyDepthBias, toPrimitive, applyViewport,
         pipelineKey } from './state.mjs';

// Which fragment entry a draw uses. Chosen by the SHAPE of what the draw binds rather than by a
// shader pointer, because pointers are per-launch and rot across captures.
//   a 256x1 texture in slot 1  -> the palette path (CHARACTERS)
//   otherwise, four varyings   -> the stage
function variantFor(d) {
    const t0 = d.tex?.[0], t1 = d.tex?.[1];
    if (t1) return 'character';           // indexed: R8 index tile + 256x1 palette
    return 'stage';
}

export class Replayer {
    constructor(device, format = 'bgra8unorm') {
        this.device = device;
        this.format = format;           // matches the captured scene RT (fmt 87 = B8G8R8A8_UNORM)
        this.pipelines = new Map();
        this.bindGroups = new Map();
    }

    async load(url) {
        this.pack = await loadPack(url);
        this.res = createResources(this.device, this.pack);
        this.module = this.device.createShaderModule({
            code: await (await fetch(new URL('./sprite.wgsl', import.meta.url))).text(),
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
        this.width = rt.w;
        this.height = rt.h;
        return this;
    }

    _pipeline(d, variant) {
        const key = pipelineKey(d, variant, 'triangle-list');
        let p = this.pipelines.get(key);
        if (p) return p;

        // The stage transforms through world x view-projection; characters and HUD use the
        // pass-through vertex shader, whose positions are already in NDC.
        const vsEntry = variant === 'character' ? 'vs_flat' : 'vs_world';
        const fsEntry = variant === 'character' ? 'fs_character' : 'fs_stage_opaque';

        const depthStencil = applyDepthBias(toDepthStencil(d.depth), d.raster);
        const blend = toBlendState(d.blend);

        p = this.device.createRenderPipeline({
            layout: this.layout,
            vertex: { module: this.module, entryPoint: vsEntry, buffers: [VERTEX_LAYOUT] },
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
        const target = this.device.createTexture({
            size: { width: this.width, height: this.height }, format: this.format,
            usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_SRC,
        });
        const depth = this.device.createTexture({
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

        pass.setVertexBuffer(0, this.res.vertexBuffer);
        pass.setIndexBuffer(this.res.indexBuffer, 'uint32');

        const stats = { drawn: 0, skipped: 0, byVariant: {} };
        head.draws.forEach((d, i) => {
            const variant = variantFor(d);
            if (opts.only && variant !== opts.only) { stats.skipped++; return; }

            const dd = opts.cullNone ? { ...d, raster: { ...(d.raster || {}), cull: 1 } } : d;
            pass.setPipeline(this._pipeline(dd, variant));
            pass.setBindGroup(0, this.bg0, [i * this.res.uniformStride]);
            pass.setBindGroup(1, this._bindGroup(d));
            applyViewport(pass, d.vp);
            pass.drawIndexed(d.indexCount, 1, d.firstIndex, 0, 0);

            stats.drawn++;
            stats.byVariant[variant] = (stats.byVariant[variant] || 0) + 1;
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
