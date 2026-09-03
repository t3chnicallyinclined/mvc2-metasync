// RETRO RECEIPTS -- TapePlayer: play a TAPE directly (no .seq on disk).
//
// The page fetches the tape and the asset pack, a Web Worker (tape-worker.mjs) runs the rr-render wasm emitter and
// posts one binary FrameRecord per frame; this class turns each record into the {head, slice} shape the existing
// Replayer / createResources consume and drives the SAME blit + ring as SequencePlayer. Textures, constant buffers
// and pipeline states arrive once (first use) and are cached by id; a texture uploads once per tape.
//
// Ring: 16 prepared GPU frames (review-render §3.2) and 16 decoded-ahead records.
import { uploadTextures } from './resources.mjs';
import { SequencePlayer } from './player.mjs';
import { Replayer } from './replay.mjs';

const DECODE_AHEAD = 16;
const PREPARED = 16;

/** Parse one FrameRecord (rr-render/src/feed.rs, "RRFR" v1) into a pack-shaped {head, slice}. */
function decodeFrameRecord(buf, tables, session) {
    const u8 = new Uint8Array(buf);
    const dv = new DataView(buf);
    let o = 0;
    const u32 = () => { const v = dv.getUint32(o, true); o += 4; return v; };
    const i32 = () => { const v = dv.getInt32(o, true); o += 4; return v; };
    if (String.fromCharCode(u8[0], u8[1], u8[2], u8[3]) !== 'RRFR') throw new Error('not a FrameRecord');
    o = 4;
    const ver = u32();
    if (ver !== 1) throw new Error(`FrameRecord v${ver} unsupported`);
    const frame = Number(dv.getBigInt64(o, true)); o += 8;
    const td = new TextDecoder();
    const nStates = u32();
    for (let k = 0; k < nStates; k++) {
        const id = u32(); const len = u32();
        tables.states.set(id, JSON.parse(td.decode(u8.subarray(o, o + len)))); o += len;
    }
    const nTex = u32();
    const textures = {};
    for (let k = 0; k < nTex; k++) {
        const id = u32(); const w = u32(); const h = u32(); const fmt = u32(); const len = u32();
        const rec = { w, h, fmt, bytes: u8.slice(o, o + len) }; o += len;
        tables.tex.set(id, { w, h, fmt });
        textures[`T${id}`] = rec;                       // new this frame: carries its bytes for the upload
    }
    const nCb = u32();
    for (let k = 0; k < nCb; k++) {
        const id = u32(); const len = u32();
        tables.cb.set(id, u8.slice(o, o + len)); o += len;
    }
    const vbLen = u32(); const vb = { bytes: u8.subarray(o, o + vbLen) }; o += vbLen;
    const ibLen = u32(); const ib = { bytes: u8.subarray(o, o + ibLen) }; o += ibLen;
    const nDraws = u32();
    const draws = new Array(nDraws);
    const constantBuffers = {};
    const cbKey = (id) => {
        if (id < 0) return null;
        const key = `C${id}`;
        if (!constantBuffers[key]) constantBuffers[key] = { bytes: tables.cb.get(id) };
        return key;
    };
    const texKey = (id) => {
        if (id < 0) return null;
        const key = `T${id}`;
        if (!textures[key]) textures[key] = tables.tex.get(id);   // already uploaded: meta only, no bytes
        return key;
    };
    for (let k = 0; k < nDraws; k++) {
        const st = i32(); const firstIndex = u32(); const indexCount = u32(); const stride = u32(); const voff = u32();
        const t0 = i32(); const t1 = i32();
        const vs = [i32(), i32(), i32(), i32()];
        const ps = [i32(), i32(), i32(), i32()];
        draws[k] = {
            ...tables.states.get(st), i: k, firstIndex, indexCount, stride, voff,
            tex: [texKey(t0), texKey(t1)], vscbHash: vs.map(cbKey), pscbHash: ps.map(cbKey),
        };
    }
    const head = { frame, viewport: session.viewport, sceneRT: session.sceneRT, inputLayouts: session.inputLayouts,
                   vb, ib, textures, constantBuffers, draws };
    return { head, slice: (r) => r.bytes, bytes: buf.byteLength };
}

export class TapePlayer extends SequencePlayer {
    constructor(device, canvasFormat, opts = {}) {
        super(device, canvasFormat, opts);
        this.maxPrepared = PREPARED;
        this.decoded = new Map();          // tape row -> pack-shaped frame
        this.pending = new Map();          // tape row -> [resolve, reject]
        this.tables = { states: new Map(), tex: new Map(), cb: new Map() };
        this.timings = [];                 // worker ms per FrameRecord
        this.bytesTotal = 0;
    }

    /**
     * @param tapeUrl  the tape (gz+base64 JSON envelope, as the agent spools it)
     * @param packUrl  the asset pack directory (manifest.json + files; tools/pack_assets.py)
     * @param start/count  the tape rows to play (default: the whole tape)
     */
    async load(tapeUrl, packUrl, { start = 0, count = Infinity, onProgress, opts = {} } = {}) {
        const fetchBytes = async (url) => {
            const r = await fetch(url, { cache: 'no-store' });
            if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
            return new Uint8Array(await r.arrayBuffer());
        };
        const manifest = await (await fetch(`${packUrl}/manifest.json`, { cache: 'no-store' })).json();
        let got = 0;
        const total = manifest.files.reduce((a, f) => a + f.bytes, 0);
        const parts = await Promise.all(manifest.files.map(async (f) => {
            const b = await fetchBytes(`${packUrl}/${f.name}`);
            got += b.byteLength; onProgress?.(got, total, 'pack');
            return [f.name, b];
        }));
        const packBlob = new Uint8Array(parts.reduce((a, [, b]) => a + b.byteLength, 0));
        const packIndex = [];
        let at = 0;
        for (const [name, b] of parts) { packBlob.set(b, at); packIndex.push({ name, off: at, len: b.byteLength }); at += b.byteLength; }
        const tape = await fetchBytes(tapeUrl);
        onProgress?.(total, total, 'tape');

        this.worker = new Worker(new URL('./tape-worker.mjs', import.meta.url), { type: 'module' });
        this.worker.onmessage = (e) => this._onMessage(e.data);
        this.info = await new Promise((resolve, reject) => {
            this._opened = [resolve, reject];
            this.worker.postMessage({ type: 'open', tape: tape.buffer, packBlob: packBlob.buffer, packIndex, opts },
                                    [tape.buffer, packBlob.buffer]);
        });
        this.first = start;
        this._count = Math.max(0, Math.min(count, this.info.frames - start));
        if (!this._count) throw new Error(`no rows in that range (tape has ${this.info.frames})`);
        this.session = { viewport: this.info.viewport, sceneRT: this.info.sceneRT, inputLayouts: this.info.inputLayouts };

        const f0 = await this.decode(0);
        this.replayer = new Replayer(this.device, 'bgra8unorm');
        this.replayer.scale = this.opts.scale;
        await this.replayer.attach(f0, this.shared);
        this._initBlit(f0.head.viewport ?? [0, 0, this.replayer.width, this.replayer.height]);
        this.seq = { meta: { first: this.info.first_clock, count: this._count, worker: true }, frames: null, bytes: 0 };
        return this;
    }

    _onMessage(m) {
        if (m.type === 'opened') { this.openMs = m.ms; this._opened[0](m.info); }
        else if (m.type === 'frame') {
            this.timings.push(m.ms);
            this.bytesTotal += m.buf.byteLength;
            const i = m.i - this.first;
            let pack;
            try { pack = decodeFrameRecord(m.buf, this.tables, this.session); }
            catch (err) { this.pending.get(i)?.[1](err); this.pending.delete(i); return; }
            this.decoded.set(i, pack);
            // seek fix: first-use texture bytes ride in whichever record first uses them -- upload on arrival so a
            // later frame shown out of order finds them in the shared map (the worker serves records in feed order).
            if (this.replayer && this.shared?.textures) uploadTextures(this.replayer.device, pack, this.shared.textures);
            this.pending.get(i)?.[0](pack);
            this.pending.delete(i);
        } else if (m.type === 'error') {
            const i = (m.i ?? this.first) - this.first;
            const err = new Error(m.message);
            if (this._opened && !this.info) this._opened[1](err);
            this.pending.get(i)?.[1](err); this.pending.delete(i);
        }
    }

    /** Decode frame `i` (0-based within the clip) through the worker; cached. */
    decode(i) {
        if (this.decoded.has(i)) return Promise.resolve(this.decoded.get(i));
        if (this.pending.has(i)) return new Promise((res, rej) => { const p = this.pending.get(i); const [r0, j0] = p; p[0] = (v) => { r0(v); res(v); }; p[1] = (e) => { j0(e); rej(e); }; });
        return new Promise((resolve, reject) => {
            this.pending.set(i, [resolve, reject]);
            this.worker.postMessage({ type: 'frame', i: this.first + i });
        });
    }

    /** Await frame `i` and keep the decode window ahead of it. */
    async ready(i) {
        i = Math.max(0, Math.min(this.count - 1, i));
        const p = this.decode(i);
        for (let k = 1; k <= DECODE_AHEAD; k++) {
            const j = i + k;
            if (j < this.count && !this.decoded.has(j) && !this.pending.has(j)) this.decode(j);
        }
        await p;
        return i;
    }

    frameBytes(i) { const f = this.decoded.get(i); return f ? f.bytes : 0; }

    ensure(i) {
        let e = this.cache.get(i);
        if (!e) {
            const pack = this.decoded.get(i);
            if (!pack) throw new Error(`frame ${i} not decoded yet -- await player.ready(${i}) first`);
            e = this.replayer.prepare(pack);
            this.cache.set(i, e);
        }
        return e;
    }

    prepareAhead(from, n) {
        let did = 0;
        for (let k = 0; k < n && this.cache.size < this.maxPrepared; k++) {
            const i = from + k;
            if (i >= this.count || this.cache.has(i) || !this.decoded.has(i)) continue;
            this.cache.set(i, this.replayer.prepare(this.decoded.get(i)));
            did++;
        }
        return did;
    }

    evict(i) {
        super.evict(i);
        // decoded records far behind the play head go too (a record is ~0.7 MB; the window is bounded)
        for (const k of [...this.decoded.keys()]) {
            if (k < i - DECODE_AHEAD || k > i + 2 * DECODE_AHEAD) this.decoded.delete(k);
        }
    }

    async prepareAll(onProgress) {
        this.cache = new Map();
        this.maxPrepared = Math.min(this.count, PREPARED);
        let bytes = 0;
        for (let i = 0; i < this.maxPrepared; i++) {
            await this.ready(i);
            this.ensure(i);
            bytes += this.frameBytes(i);
            onProgress?.(i + 1, this.maxPrepared);
        }
        return { bytes, textures: this.shared.textures.size, prepared: this.maxPrepared, windowed: this.maxPrepared < this.count, totalBytes: 0 };
    }

    get count() { return this._count; }
    get frameNumber() { return this.decoded.get(this.index)?.head.frame ?? 0; }

    /** Worker timing: ms per FrameRecord (avg / max) and bytes per frame so far. */
    stats() {
        const t = this.timings;
        const avg = t.length ? t.reduce((a, b) => a + b, 0) / t.length : 0;
        return { frames: t.length, avgMs: avg, maxMs: t.length ? Math.max(...t) : 0, openMs: this.openMs,
                 bytesPerFrame: t.length ? this.bytesTotal / t.length : 0, textures: this.shared.textures.size };
    }
}
