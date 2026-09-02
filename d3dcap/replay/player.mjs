// RETRO RECEIPTS — PATH B: play back a captured SEQUENCE of Steam MvC2 frames on WebGPU.
//
// Every frame is re-rendered from Steam's own draw calls, not decoded from a video. That is the whole
// point of Path B: the picture is reconstructed, so it stays re-composable — a skin swap is still
// just a palette write, on any frame of the playback.
//
// ⚠ A .seq embeds the game's own pixels. ROM-derived: never commit one, never serve it publicly.

import { Replayer } from './replay.mjs';

/** Parse the .seq container: "RRSQ", u32 header length, JSON header, then one shared blob pool. */
export async function loadSequence(url, onProgress) {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
    const total = Number(res.headers.get('content-length')) || 0;

    // Read progressively: a burst is tens of megabytes and a silent multi-second wait reads as a hang.
    const chunks = [];
    let got = 0;
    const reader = res.body.getReader();
    for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
        got += value.length;
        onProgress?.(got, total);
    }
    const buf = new Uint8Array(got);
    let at = 0;
    for (const c of chunks) { buf.set(c, at); at += c.length; }

    const dv = new DataView(buf.buffer);
    if (String.fromCharCode(...buf.subarray(0, 4)) !== 'RRSQ') throw new Error('not a .seq file');
    const headLen = dv.getUint32(4, true);
    const head = JSON.parse(new TextDecoder().decode(buf.subarray(8, 8 + headLen)));
    const base = 8 + headLen;
    const slice = (r) => buf.subarray(base + r.off, base + r.off + r.len);

    // Every frame is a pack-shaped {head, slice} over the SHARED pool, so the same createResources()
    // the single-frame viewer uses works unchanged.
    return {
        meta: head,
        frames: head.frames.map((h) => ({ head: h, slice })),
        bytes: got,
    };
}

// Blit the scene render target's viewport region to the canvas. Playback must NOT go through
// copyTextureToBuffer — that is the diff path, it stalls on a GPU sync, and at 60 fps it turns a
// 2 ms render into a 30 ms frame.
const BLIT_WGSL = `
struct VSOut { @builtin(position) pos : vec4f, @location(0) uv : vec2f };
struct Crop { origin : vec2f, size : vec2f };
@group(0) @binding(0) var samp : sampler;
@group(0) @binding(1) var src  : texture_2d<f32>;
@group(0) @binding(2) var<uniform> crop : Crop;

@vertex
fn vs(@builtin(vertex_index) i : u32) -> VSOut {
    // One oversized triangle, not a quad: no seam down the diagonal, one fewer vertex.
    var p = array(vec2f(-1.0, -1.0), vec2f(3.0, -1.0), vec2f(-1.0, 3.0));
    var t = array(vec2f(0.0, 1.0), vec2f(2.0, 1.0), vec2f(0.0, -1.0));
    var o : VSOut;
    o.pos = vec4f(p[i], 0.0, 1.0);
    o.uv  = t[i];
    return o;
}

@fragment
fn fs(in : VSOut) -> @location(0) vec4f {
    // The scene RT is 2048x1024 and only (384,32)+1280x960 of it is the game's viewport.
    let uv = crop.origin + in.uv * crop.size;
    // Alpha in the scene RT is the game's own last-writer alpha and is meaningless on screen;
    // forcing 1 stops the canvas compositing the page background through the picture.
    return vec4f(textureSample(src, samp, uv).rgb, 1.0);
}`;

export class SequencePlayer {
    constructor(device, canvasFormat) {
        this.device = device;
        this.canvasFormat = canvasFormat;
        this.shared = { textures: new Map(), samplers: new Map() };
        this.index = 0;
    }

    async load(url, onProgress) {
        this.seq = await loadSequence(url, onProgress);
        this.replayer = new Replayer(this.device, 'bgra8unorm');
        await this.replayer.attach(this.seq.frames[0], this.shared);

        const vp = this.seq.frames[0].head.viewport ?? [0, 0, this.replayer.width, this.replayer.height];
        this.viewport = vp;
        const mod = this.device.createShaderModule({ code: BLIT_WGSL });
        this.blitPipeline = this.device.createRenderPipeline({
            layout: 'auto',
            vertex: { module: mod, entryPoint: 'vs' },
            fragment: { module: mod, entryPoint: 'fs', targets: [{ format: this.canvasFormat }] },
            primitive: { topology: 'triangle-list' },
        });
        this.cropBuffer = this.device.createBuffer({
            size: 16, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
        });
        this.device.queue.writeBuffer(this.cropBuffer, 0, new Float32Array([
            vp[0] / this.replayer.width, vp[1] / this.replayer.height,
            vp[2] / this.replayer.width, vp[3] / this.replayer.height,
        ]));
        this.blitSampler = this.device.createSampler({ magFilter: 'nearest', minFilter: 'nearest' });
        return this;
    }

    /**
     * Build every frame's GPU resources up front.
     *
     * A sequence is a fixed, fully known set of frames, so there is nothing to discover during
     * playback: uploading here turns each played frame into state-setting plus draw calls. The cost
     * is bounded and small -- the vertex buffer is dumped as a used-range prefix (~230 KB), the index
     * buffer is ~25 KB, and the uniform slice is 256 B per draw -- so ~0.5 MB per frame, and the
     * textures are shared across the whole sequence rather than per frame.
     */
    async prepareAll(onProgress) {
        this.prepared = [];
        let bytes = 0;
        for (let i = 0; i < this.seq.frames.length; i++) {
            const e = this.replayer.prepare(this.seq.frames[i]);
            this.prepared.push(e);
            const h = this.seq.frames[i].head;
            bytes += h.vb.len + h.ib.len + h.draws.length * 256;
            if ((i & 7) === 0) {
                onProgress?.(i + 1, this.seq.frames.length);
                await new Promise((r) => setTimeout(r, 0));   // keep the page responsive
            }
        }
        onProgress?.(this.seq.frames.length, this.seq.frames.length);
        return { bytes, textures: this.shared.textures.size };
    }

    get count() { return this.seq.frames.length; }
    get frameNumber() { return this.seq.frames[this.index].head.frame; }

    /** Render frame `i` and blit it to the canvas. Returns per-frame stats for the readout. */
    draw(i, canvasView) {
        this.index = Math.max(0, Math.min(this.count - 1, i));
        const t0 = performance.now();
        const entry = this.prepared?.[this.index];
        const uploaded = entry ? (this.replayer.use(entry), 0)
                               : this.replayer.setFrame(this.seq.frames[this.index]);
        const { target, stats } = this.replayer.render({});

        if (!this.blitBind || this.blitSrc !== target) {
            this.blitSrc = target;
            this.blitBind = this.device.createBindGroup({
                layout: this.blitPipeline.getBindGroupLayout(0),
                entries: [
                    { binding: 0, resource: this.blitSampler },
                    { binding: 1, resource: target.createView() },
                    { binding: 2, resource: { buffer: this.cropBuffer } },
                ],
            });
        }
        const enc = this.device.createCommandEncoder();
        const pass = enc.beginRenderPass({
            colorAttachments: [{
                view: canvasView, loadOp: 'clear', storeOp: 'store',
                clearValue: { r: 0, g: 0, b: 0, a: 1 },
            }],
        });
        pass.setPipeline(this.blitPipeline);
        pass.setBindGroup(0, this.blitBind);
        pass.draw(3);
        pass.end();
        this.device.queue.submit([enc.finish()]);

        return { ms: performance.now() - t0, drawn: stats.drawn, uploaded };
    }
}
