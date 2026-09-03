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

    // Rebuild the full draw records the rest of the renderer expects. pack_sequence.py factors the
    // parts that repeat -- 167k draws carried only 13 distinct pipeline states, at 482 bytes of JSON
    // each -- and asserts the compaction round-trips before writing. This is the other half of that
    // contract, and it must stay in step: a draw that comes back subtly different renders subtly
    // wrong rather than failing.
    const T = head.tables;
    if (T) {
        for (const h of head.frames) {
            h.draws = h.draws.map((c) => ({
                i: c.i, firstIndex: c.f, indexCount: c.n, stride: c.s, voff: c.o,
                ...T.states[c.st],
                ...T.shaders[c.sh],
                samp: T.samplers[c.sm],
                tex: c.t.map((x) => (x >= 0 ? T.texKeys[x] : null)),
                vscbHash: c.v.map((x) => T.hashes[x]),
                pscbHash: c.p.map((x) => T.hashes[x]),
            }));
        }
    }

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
struct Crop { origin : vec2f, size : vec2f, taps : vec2f, mode : f32, pad : f32 };
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
    // The scene RT is 2048x1024 (x internal scale) and only the game viewport region of it is shown.
    let uv = crop.origin + in.uv * crop.size;
    // Alpha in the scene RT is the game's own last-writer alpha and is meaningless on screen;
    // forcing 1 stops the canvas compositing the page background through the picture.
    if (crop.mode < 0.5) {
        return vec4f(textureSample(src, samp, uv).rgb, 1.0);
    }
    // BOX FILTER: average the taps.x by taps.y RT texels that map onto this canvas pixel (supersampling).
    // Integer taps only (the caller rounds); textureLoad so no sampler filtering is mixed in.
    let dims = vec2f(textureDimensions(src));
    let base = vec2i(floor(uv * dims - crop.taps * 0.5 + vec2f(0.5)));
    var acc = vec3f(0.0);
    let nx = i32(crop.taps.x); let ny = i32(crop.taps.y);
    for (var y = 0; y < ny; y++) {
        for (var x = 0; x < nx; x++) {
            acc += textureLoad(src, base + vec2i(x, y), 0).rgb;
        }
    }
    return vec4f(acc / f32(nx * ny), 1.0);
}`;

export class SequencePlayer {
    constructor(device, canvasFormat, opts = {}) {
        this.device = device;
        this.canvasFormat = canvasFormat;
        // display options (2026-09-03): scale = internal-resolution multiplier on the captured RT (1 = the capture's
        // own 2x of native); filter = 'nearest' (one RT texel per canvas pixel, the historical blit) or 'box'
        // (average every RT texel under the canvas pixel -- true supersampling); canvas = {w,h} of the output.
        this.opts = { scale: 1, filter: 'nearest', canvas: null, ...opts };
        this.shared = { textures: new Map(), samplers: new Map() };
        this.cache = new Map();
        this.maxPrepared = 300;
        this.index = 0;
    }

    async load(url, onProgress) {
        this.seq = await loadSequence(url, onProgress);
        this.replayer = new Replayer(this.device, 'bgra8unorm');
        this.replayer.scale = this.opts.scale;
        await this.replayer.attach(this.seq.frames[0], this.shared);

        const vp = this.seq.frames[0].head.viewport ?? [0, 0, this.replayer.width, this.replayer.height];
        this._initBlit(vp);
        return this;
    }

    /** The blit pipeline + crop for a viewport (shared with TapePlayer, which feeds frames from a worker). */
    _initBlit(vp) {
        this.viewport = vp;
        const mod = this.device.createShaderModule({ code: BLIT_WGSL });
        this.blitPipeline = this.device.createRenderPipeline({
            layout: 'auto',
            vertex: { module: mod, entryPoint: 'vs' },
            fragment: { module: mod, entryPoint: 'fs', targets: [{ format: this.canvasFormat }] },
            primitive: { topology: 'triangle-list' },
        });
        this.cropBuffer = this.device.createBuffer({
            size: 32, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
        });
        const s = this.replayer.scale;
        const cw = this.opts.canvas?.w ?? vp[2] * s, ch = this.opts.canvas?.h ?? vp[3] * s;   // canvas pixels
        const tx = Math.max(1, Math.round(vp[2] * s / cw)), ty = Math.max(1, Math.round(vp[3] * s / ch));
        this.device.queue.writeBuffer(this.cropBuffer, 0, new Float32Array([
            vp[0] * s / this.replayer.width, vp[1] * s / this.replayer.height,
            vp[2] * s / this.replayer.width, vp[3] * s / this.replayer.height,
            tx, ty, this.opts.filter === 'box' ? 1 : 0, 0,
        ]));
        this.blitTaps = [tx, ty];
        this.blitSampler = this.device.createSampler({ magFilter: 'nearest', minFilter: 'nearest' });
    }

    /** Raw BGRA bytes of the last rendered scene target (copyTextureToBuffer, never the canvas). */
    async readback() {
        if (!this.blitSrc) throw new Error('nothing rendered yet');
        return this.replayer.readback(this.blitSrc);
    }

    /**
     * Build frames' GPU resources ahead of playback, as a WINDOW rather than all at once.
     *
     * Per frame this is the vertex buffer (a used-range prefix, ~230 KB), the index buffer (~25 KB)
     * and a 256 B uniform slice per draw -- about 0.5 MB. For a 1.5 s burst that is 45 MB and
     * prebuilding everything is right. For 20 s of match it is 1200 frames and ~580 MB of GPU
     * buffers, which is not. So the window is capped and topped up during playback: preparing is
     * pure buffer creation, so a couple of frames per displayed frame keeps well ahead of a 60 fps
     * read-out without ever allocating in the critical path for the frame being shown.
     *
     * Textures are NOT part of this. They are shared across the whole sequence and uploaded once.
     */
    frameBytes(i) {
        const h = this.seq.frames[i].head;
        return h.vb.len + h.ib.len + h.draws.length * 256;
    }

    /** Guarantee frame `i` is ready. Synchronous, because the frame being drawn cannot wait. */
    ensure(i) {
        let e = this.cache.get(i);
        if (!e) {
            e = this.replayer.prepare(this.seq.frames[i]);
            this.cache.set(i, e);
        }
        return e;
    }

    /** Prepare up to `n` not-yet-ready frames starting at `from`, wrapping at the end. */
    prepareAhead(from, n) {
        let did = 0;
        for (let k = 0; k < n && this.cache.size < this.maxPrepared; k++) {
            const i = (from + k) % this.count;
            if (this.cache.has(i)) continue;
            this.cache.set(i, this.replayer.prepare(this.seq.frames[i]));
            did++;
        }
        return did;
    }

    /** Drop frames far from `i`. Buffers are destroyed explicitly, not left to the GC. */
    evict(i) {
        if (this.cache.size <= this.maxPrepared) return;
        for (const [k, e] of this.cache) {
            const d = Math.min(Math.abs(k - i), this.count - Math.abs(k - i));
            if (d < this.maxPrepared / 2) continue;
            e.res.vertexBuffer.destroy();
            e.res.indexBuffer.destroy();
            e.res.uniformBuffer.destroy();
            this.cache.delete(k);
            if (this.cache.size <= this.maxPrepared) break;
        }
    }

    async prepareAll(onProgress) {
        this.cache = new Map();
        // ~145 MB of per-frame buffers. Short sequences fit entirely and never evict.
        this.maxPrepared = Math.min(this.count, 300);
        let bytes = 0;
        for (let i = 0; i < this.maxPrepared; i++) {
            this.ensure(i);
            bytes += this.frameBytes(i);
            if ((i & 7) === 0) {
                onProgress?.(i + 1, this.maxPrepared);
                await new Promise((r) => setTimeout(r, 0));   // keep the page responsive
            }
        }
        onProgress?.(this.maxPrepared, this.maxPrepared);
        return {
            bytes, textures: this.shared.textures.size,
            prepared: this.maxPrepared, windowed: this.maxPrepared < this.count,
            totalBytes: [...Array(this.count).keys()].reduce((a, i) => a + this.frameBytes(i), 0),
        };
    }

    get count() { return this.seq.frames.length; }
    get frameNumber() { return this.seq.frames[this.index].head.frame; }

    /** Render frame `i` and blit it to the canvas. Returns per-frame stats for the readout. */
    draw(i, canvasView) {
        this.index = Math.max(0, Math.min(this.count - 1, i));
        const t0 = performance.now();
        this.replayer.use(this.ensure(this.index));
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

        // Stay ahead of the read-out without ever allocating for the frame being shown, and keep the
        // window from growing past its cap.
        this.prepareAhead(this.index + 1, 2);
        this.evict(this.index);
        return { ms: performance.now() - t0, drawn: stats.drawn, ready: this.cache.size };
    }
}
