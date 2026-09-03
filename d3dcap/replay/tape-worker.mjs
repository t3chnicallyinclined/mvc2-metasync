// RETRO RECEIPTS -- tape-worker: the rr-render wasm FrameFeed in a Web Worker.
//
// The main thread hands over the TAPE bytes (the agent's gz+base64 JSON envelope, as recorded) and the ASSET PACK
// (the exact files the emitter reads, fetched by the page from packs/<match>/; see rr-render/tools/pack_assets.py)
// once; from then on every `frame` request is answered with one binary FrameRecord (rr-render/src/feed.rs) posted
// as a transferable, so the main thread never copies and never JSON-parses a frame.
//
// Build the module (rr-render/src/web.rs):
//   cargo build --lib --release --target wasm32-unknown-unknown --features web
//   wasm-bindgen --target web --out-dir d3dcap/replay/wasm target/wasm32-unknown-unknown/release/rr_render.wasm
//
// ⚠ The pack is ROM-derived (game pixels); wasm/ and packs/ are gitignored.
import init, { WebFeed } from './wasm/rr_render.js';

const ready = init({ module_or_path: new URL('./wasm/rr_render_bg.wasm', import.meta.url) });
let feed = null;
let next = null;   // next frame index the feed has not yet emitted (set on open from opts.start)

self.onmessage = async (e) => {
    const m = e.data;
    try {
        if (m.type === 'open') {
            await ready;
            const t0 = performance.now();
            // pack: one blob + an index [{name, off, len}] (one copy into wasm memory instead of N)
            feed = new WebFeed(new Uint8Array(m.tape), JSON.stringify(m.packIndex), new Uint8Array(m.packBlob),
                               JSON.stringify(m.opts || {}));
            const info = JSON.parse(feed.info());
            self.postMessage({ type: 'opened', info, ms: performance.now() - t0 });
        } else if (m.type === 'frame') {
            if (!feed) throw new Error('frame before open');
            // FrameRecords carry first-use tables relative to what the feed has ALREADY emitted, so records must reach
            // the main thread in feed order. A seek past unserved frames first serves the gap (decode-only on the
            // main thread, ~25 ms each); a rewind re-serves the frame meta-only, which the main thread already holds.
            if (next === null) next = m.i;            // the first request defines where the feed starts emitting
            if (m.i > next) {
                for (let j = next; j < m.i; j++) {
                    const b = feed.frame(j);
                    self.postMessage({ type: 'frame', i: j, buf: b.buffer, ms: 0, fill: true }, [b.buffer]);
                }
            }
            const t0 = performance.now();
            const bytes = feed.frame(m.i);            // a fresh Uint8Array copied out of wasm memory
            const ms = performance.now() - t0;
            next = Math.max(next ?? 0, m.i + 1);
            self.postMessage({ type: 'frame', i: m.i, buf: bytes.buffer, ms }, [bytes.buffer]);
        } else if (m.type === 'close') {
            feed?.free(); feed = null;
            self.postMessage({ type: 'closed' });
        }
    } catch (err) {
        self.postMessage({ type: 'error', i: m.i, message: String(err?.message || err) });
    }
};
