// capture_mirror_full.mjs — FULL-MATCH capture of a live ZCST mirror stream to a
// .zcst file that render_ta.mjs / render_ta_wire.mjs --mirror can replay headless.
//
// Supersedes maplecast-flycast/tools/render-replica-poc/capture_mirror.mjs, whose
// hard `setTimeout(finish, 15000)` (that file, line 62) terminated EVERY capture at
// ~15 s (~900 frames @60fps) regardless of match length. That 15 s cap was purely
// client-side: the maplecast_ws server (websocketpp) never pings a spectator
// (pingAllForRtt disabled, maplecast_ws_server.cpp:1878), sets no read/idle timer,
// and only idle-kicks PLAYER slots after 5 min (maplecast_ws_server.cpp:259) — a
// spectator/capture connection is never dropped. And flycast does NOT exit when
// MAPLECAST_MOVIE_IN is exhausted (getInputAtFrame returns sticky last input,
// replay_reader.cpp:522-530), so the WS never closes on its own either. Hence a
// full-match capture just needs the client to keep reading until the match ends.
//
// Wire format (unchanged, decoder-compatible): [u32 LE len][bytes] per BINARY
// message. The first binary message is the compressed SYNC (onOpen seeds full
// VRAM+PVR, maplecast_ws_server.cpp:1030-1048); every later binary message is a
// per-frame TA delta (+dirty pages). A mid-stream scene-change SYNC re-seeds VRAM
// and FrameDecoder handles it, so a single continuous capture (SYNC -> deltas ->
// ... -> KO) decodes clean with NO segment stitching. TEXT frames (JSON status /
// lobby / control) are side-channel: parsed for {"type":"match_end"} but NOT
// persisted (they would only add len=0 junk entries).
//
// Usage:
//   node capture_mirror_full.mjs --url ws://127.0.0.1:7300/ --out match.zcst
//   node capture_mirror_full.mjs --url ws://127.0.0.1:7300/ --out f.zcst --frames 8   (legacy fixed-count)
//
// Options:
//   --url URL            WebSocket to capture (default ws://127.0.0.1:7300/)
//   --out FILE           output .zcst (default match.zcst)
//   --frames N           HARD stop after N binary frames (legacy; disables match-end auto-stop)
//   --end-grace N        after match_end, capture N more binary frames then stop (default 300)
//   --no-match-end-stop  ignore match_end; run until --frames / --idle-ms / --max-seconds
//   --idle-ms MS         finish if no binary frame arrives for MS ms (default 30000)
//   --max-seconds S      hard wall-clock cap in seconds (default 0 = disabled)
//   --max-frames N       safety backstop on binary frames when not using --frames (default 20000)
//   --log-every N        log a progress line every N binary frames (default 300)
//   --keep-sidechannels  persist the GSTA/PALF/OBJS/OBJF/TXTR state side-channels too
//                        (default: DROP them — see note below)
// (Node 22 has a global WebSocket.)
//
// ── Why side-channels are dropped by default ──────────────────────────────────
// serverPublish broadcasts ~5 BINARY messages per game frame: the ZCST TA delta
// (the only one the pvr2/FrameDecoder render path consumes — it carries the full
// VRAM dirty pages incl. textures + PVR regs) PLUS state-only side-channels
// GSTA/PALF/OBJS/OBJF (and occasional TXTR) used by the OTHER (state-replica /
// OBJS-overlay / non-VRAM) clients. FrameDecoder.applyFrame ignores all of them
// (render_ta_wire.mjs: "non-TA side-channel skipped"), so persisting them only
// bloats the file ~5x AND makes a --frames / --max-frames budget (which counts
// messages) mismatch the game-frame count 5:1. Dropping them makes 1 persisted
// message == 1 game frame and shrinks the .zcst ~5x with zero render impact.
// TA-relevant envelopes (ZCST / ZCS2 / FSYN / SYNC / anything not in the drop
// set) are ALWAYS kept, so an unknown TA variant is never lost.

import { createWriteStream } from 'node:fs';

// State side-channels the ZCST/pvr2 render path does not use (drop unless --keep-sidechannels).
const SIDE_CHANNELS = new Set(['GSTA', 'PALF', 'OBJS', 'OBJF', 'TXTR']);
function magic4(u8) {
    let s = '';
    for (let i = 0; i < 4 && i < u8.length; i++) { const c = u8[i]; s += (c >= 32 && c < 127) ? String.fromCharCode(c) : '.'; }
    return s;
}

function arg(name, def) { const i = process.argv.indexOf(name); return i >= 0 ? process.argv[i + 1] : def; }
function has(name) { return process.argv.indexOf(name) >= 0; }

const url          = arg('--url', 'ws://127.0.0.1:7300/');
const out          = arg('--out', 'match.zcst');
const fixedFrames  = has('--frames') ? +arg('--frames', '0') : null;  // legacy fixed count
const endGrace     = +arg('--end-grace', '300');
const stopOnEnd    = !has('--no-match-end-stop') && fixedFrames === null;
const idleMs       = +arg('--idle-ms', '30000');
const maxSeconds   = +arg('--max-seconds', '0');
const maxFrames    = +arg('--max-frames', '20000');
const logEvery     = Math.max(1, +arg('--log-every', '300'));
const keepSide     = has('--keep-sidechannels');

// Length-prefixed writer: [u32 LE len][bytes] per binary message, streamed to
// disk so a full match (thousands of frames, hundreds of MB) never has to sit in
// memory or hit a giant final concat allocation.
const sink = createWriteStream(out);
let binFrames = 0;    // binary (ZCST) messages persisted
let textMsgs = 0;     // JSON side-channel messages seen (not persisted)
let bytesOut = 0;
let done = false;
let matchEnded = false;
let graceLeft = 0;
let stopReason = '';
let droppedSide = 0;   // side-channel binary messages dropped

function persist(u8) {
    const hdr = Buffer.allocUnsafe(4);
    hdr.writeUInt32LE(u8.length, 0);
    sink.write(hdr);
    sink.write(Buffer.from(u8.buffer, u8.byteOffset, u8.length));
    bytesOut += 4 + u8.length;
    binFrames++;
}

// Idle watchdog: reset on every binary frame; if it elapses the stream has gone
// silent (resim finished / stalled) — finish with what we have.
let idleTimer = null;
function armIdle() {
    if (idleMs <= 0) return;
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(() => finish(`idle ${idleMs}ms with no binary frame`), idleMs);
}

const ws = new WebSocket(url);
ws.binaryType = 'arraybuffer';
ws.onopen  = () => { console.error('[capture] connected', url); armIdle(); };
ws.onerror = (e) => { console.error('[capture] ws error', e.message || e); if (!binFrames) process.exit(1); finish('ws error'); };
ws.onclose = () => finish('ws closed by server');

ws.onmessage = (e) => {
    if (done) return;
    // TEXT frame (string) = JSON status / lobby / control. Parse for match_end;
    // do NOT persist (side-channel only).
    if (typeof e.data === 'string') {
        textMsgs++;
        if (stopOnEnd && !matchEnded) {
            try {
                const j = JSON.parse(e.data);
                if (j && j.type === 'match_end') {
                    matchEnded = true;
                    graceLeft = endGrace;
                    console.error(`[capture] match_end received (winner=${j.winner} "${j.winner_name}") — capturing ${endGrace} more frames`);
                    if (graceLeft <= 0) finish('match_end (no grace)');
                }
            } catch { /* non-JSON text — ignore */ }
        }
        return;
    }
    // BINARY frame. Drop the state-only side-channels (default) so 1 persisted
    // message == 1 game frame; keep the ZCST TA delta + any non-side-channel.
    const u8 = new Uint8Array(e.data);
    if (u8.length === 0) return;   // defensive: never persist an empty binary frame
    if (!keepSide && SIDE_CHANNELS.has(magic4(u8))) { droppedSide++; return; }
    persist(u8);
    armIdle();

    if (binFrames % logEvery === 0)
        console.error(`[capture] ${binFrames} frames, ${(bytesOut / (1024 * 1024)).toFixed(1)} MB${matchEnded ? ` (grace ${graceLeft})` : ''}`);

    if (fixedFrames !== null && binFrames >= fixedFrames) { finish(`--frames ${fixedFrames} reached`); return; }
    if (binFrames >= maxFrames)                            { finish(`--max-frames ${maxFrames} backstop`); return; }
    if (matchEnded) { if (--graceLeft <= 0) finish('match_end + grace'); }
};

if (maxSeconds > 0)
    setTimeout(() => finish(`--max-seconds ${maxSeconds} cap`), maxSeconds * 1000);

function finish(reason) {
    if (done) return;
    done = true;
    stopReason = reason || 'done';
    if (idleTimer) clearTimeout(idleTimer);
    try { ws.close(); } catch { /* noop */ }
    if (!binFrames) { console.error(`[capture] no binary frames (${textMsgs} text msgs); stop=${stopReason}`); process.exit(1); }
    sink.end(() => {
        console.error(`[capture] wrote ${out}: ${binFrames} frames kept, ${droppedSide} side-channel + ${textMsgs} text msgs dropped, ${bytesOut} bytes  (stop=${stopReason})`);
        process.exit(0);
    });
}

// Flush on Ctrl-C so an interrupted capture still yields a usable .zcst.
process.on('SIGINT',  () => finish('SIGINT'));
process.on('SIGTERM', () => finish('SIGTERM'));
