// RETRO RECEIPTS — PATH B: pixel diff against Steam's own scene render target.
//
// ⚠⚠ EPISTEMIC STATUS OF EVERY NUMBER THIS FILE PRODUCES.
// A pixel diff that improves is a MEASUREMENT, not a mechanism. A match here shows that our
// translation of the captured D3D11 state reproduces the pixels Steam produced from the SAME data.
// It establishes nothing about MvC2 itself, and it is not evidence for any claim about the game.
// Per the re_kb rules that is record_attempt(..., outcome='masks_only') — never a `finding`.
// `verdict()` prints this alongside the number so it cannot be quietly dropped.
//
// Protocol (steam-d3d11-capture-expert, 2026-09-01), each part deliberate:
//  * compare RAW UNORM BYTES, no gamma. No format in the chain is _SRGB (scene RT fmt 87, textures
//    fmt 28/61, backbuffer fmt 28), so it is linear in storage end to end. A *-srgb canvas or any
//    gamma step injects a global error that looks "close" and passes a sloppy eye.
//  * compare in BGRA, matching the RT exactly, rather than swizzling one side.
//  * INCLUDE ALPHA. The clear is [0,0,0,0] and the blend writes dstA = 1*srcA + 0*dstA, so RT alpha
//    is meaningful and the post chain samples it. An RGB-only diff hides a whole class of error.
//  * CROP to the viewport. Outside it the RT is untouched clear and would trivially match, which
//    flatters the number — 2048x1024 is mostly empty; the content is 1280x960 at (384,32).
//  * ±1 LSB is NOISE (mad fusion is undefined in both APIs). >1 LSB is signal.
//  * report the BOUNDING BOX of differing pixels: "3.1% differ" is not debuggable, "it is the
//    character on the left" is.

/** Decode a 32bpp BMP (as written by the capture tool: top-down, BGRA, uncompressed). */
export function decodeBMP(bytes) {
    const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    if (dv.getUint16(0, true) !== 0x4D42) throw new Error('not a BMP');
    const dataOff = dv.getUint32(10, true);
    const w = dv.getInt32(18, true);
    const hRaw = dv.getInt32(22, true);
    const bpp = dv.getUint16(28, true);
    if (bpp !== 32) throw new Error(`expected 32bpp BMP, got ${bpp}`);
    const h = Math.abs(hRaw);
    const topDown = hRaw < 0;
    const rowBytes = w * 4;
    const out = new Uint8Array(w * h * 4);
    for (let y = 0; y < h; y++) {
        // A positive biHeight means bottom-up; ours is written top-down, but handle both so a
        // hand-made reference image does not silently come out vertically mirrored.
        const src = dataOff + (topDown ? y : h - 1 - y) * rowBytes;
        out.set(bytes.subarray(src, src + rowBytes), y * rowBytes);
    }
    return { width: w, height: h, data: out };   // BGRA
}

/** Crop a BGRA buffer. */
export function crop(img, x, y, w, h) {
    const out = new Uint8Array(w * h * 4);
    for (let r = 0; r < h; r++) {
        const s = ((y + r) * img.width + x) * 4;
        out.set(img.data.subarray(s, s + w * 4), r * w * 4);
    }
    return { width: w, height: h, data: out };
}

/**
 * Compare two BGRA buffers of identical size.
 *
 * `threshold` is the per-channel delta ABOVE which a pixel counts as differing. Default 1 treats a
 * 1-LSB difference as noise, which is the documented tolerance for undefined mad fusion — not a
 * fudge factor, and it must not be raised to make a run pass.
 */
export function compare(a, b, opts = {}) {
    const threshold = opts.threshold ?? 1;
    if (a.width !== b.width || a.height !== b.height) {
        throw new Error(`size mismatch: ${a.width}x${a.height} vs ${b.width}x${b.height}`);
    }

    // ⚠⚠ WHY THERE IS NO MASK OPTION ANY MORE, AND NO SUBSET COMPARISON.
    // Alpha blending is NOT decomposable: blend(A over B) at a pixel depends on every draw that
    // touched it and in what order. A subset of the draws replayed over a zero clear therefore
    // CANNOT equal the full composite, no matter how it is masked. Two earlier runs were invalid
    // for exactly this reason — a characters-only replay compared our character-over-nothing against
    // truth's character-over-stage, and since the mask spanned the whole quad footprint it also
    // compared our clear against truth's stage under the ~50% of texels that are transparent index 0.
    // The 91% it reported was the expected value of that mistake, not a signal.
    // ⟹ Only the FULL draw list in submission order is a valid comparison. Localise a failure by
    // looking at WHERE the full diff's error is, never by re-diffing a subset.
    //
    // The single fused percentage was also misleading: our target clears to [0,0,0,0] while truth
    // ends at alpha 255 almost everywhere, so every pixel we simply never covered differs by 255 in
    // ALPHA ALONE and trips the threshold. That inflated "differing" with a coverage problem wearing
    // a colour problem's clothes. Coverage and colour are now reported separately.
    const n = a.width * a.height;
    const maxAbs = [0, 0, 0, 0];
    const sumAbs = [0, 0, 0, 0];
    let bothCovered = 0, differing = 0;
    let oursOnly = 0, truthOnly = 0, neither = 0;
    let minX = a.width, minY = a.height, maxX = -1, maxY = -1;
    let mX0 = a.width, mY0 = a.height, mX1 = -1, mY1 = -1;   // bbox of MISSING coverage

    for (let i = 0; i < n; i++) {
        const o = i * 4;
        const ao = a.data[o + 3] > 0;
        const bo = b.data[o + 3] > 0;
        const x = i % a.width, y = (i / a.width) | 0;

        if (!ao && !bo) { neither++; continue; }
        if (ao && !bo) { oursOnly++; continue; }
        if (!ao && bo) {
            truthOnly++;                                    // geometry we FAILED TO DRAW
            if (x < mX0) mX0 = x;
            if (x > mX1) mX1 = x;
            if (y < mY0) mY0 = y;
            if (y > mY1) mY1 = y;
            continue;
        }

        // both covered: this is the only place a COLOUR comparison is meaningful
        bothCovered++;
        let hit = false;
        for (let c = 0; c < 4; c++) {
            const d = Math.abs(a.data[o + c] - b.data[o + c]);
            if (d > maxAbs[c]) maxAbs[c] = d;
            sumAbs[c] += d;
            if (d > threshold) hit = true;
        }
        if (hit) {
            differing++;
            if (x < minX) minX = x;
            if (x > maxX) maxX = x;
            if (y < minY) minY = y;
            if (y > maxY) maxY = y;
        }
    }

    const denom = bothCovered || 1;
    return {
        width: a.width, height: a.height, pixels: n, threshold,
        // coverage
        bothCovered, oursOnly, truthOnly, neither,
        coveragePct: (100 * (bothCovered + oursOnly)) / n,
        truthCoveragePct: (100 * (bothCovered + truthOnly)) / n,
        missingPct: (100 * truthOnly) / n,
        missingBbox: mX1 < 0 ? null : { x: mX0, y: mY0, w: mX1 - mX0 + 1, h: mY1 - mY0 + 1 },
        // colour, among covered pixels only
        maxAbs, meanAbs: sumAbs.map((v) => v / denom),
        differing, differingPct: (100 * differing) / denom,
        bbox: maxX < 0 ? null : { x: minX, y: minY, w: maxX - minX + 1, h: maxY - minY + 1 },
    };
}

/**
 * Coverage-only mask diff: pure geometry, no colour, no blending.
 * The cheapest decisive test for "are we losing draws" — where ours is empty and truth is not, we
 * failed to draw something, and that is independent of every shading question.
 */
export function coverageMask(img) {
    const n = img.width * img.height;
    const m = new Uint8Array(n);
    for (let i = 0; i < n; i++) m[i] = img.data[i * 4 + 3] > 0 ? 1 : 0;
    return m;
}

/**
 * Tint image for the human eye. Convention preserved from the existing DIFF OVERLAY v7 so
 * screenshots stay comparable across lanes: GREEN = truth only, RED = ours only, YELLOW = both.
 */
export function tint(ours, truth) {
    const n = ours.width * ours.height;
    const out = new Uint8ClampedArray(n * 4);
    for (let i = 0; i < n; i++) {
        const o = i * 4;
        const a = ours.data[o + 3] > 8;
        const b = truth.data[o + 3] > 8;
        out[o + 0] = b ? 255 : 0;        // R channel of the RGBA canvas image
        out[o + 1] = a ? 255 : 0;
        out[o + 2] = 0;
        out[o + 3] = a || b ? 255 : 255;
        if (a && b) { out[o] = 255; out[o + 1] = 255; }     // yellow
        else if (b) { out[o] = 0; out[o + 1] = 255; }       // green: truth only  (we are MISSING it)
        else if (a) { out[o] = 255; out[o + 1] = 0; }       // red:   ours only   (we drew EXTRA)
        else { out[o] = 16; out[o + 1] = 16; out[o + 2] = 16; }
    }
    return new ImageData(out, ours.width, ours.height);
}

/** Human-readable verdict, with the epistemic label attached to the number. */
export function verdict(m, label = '') {
    const pct = (v) => `${v.toFixed(3)}%`;
    const L = [];
    L.push(`=== PIXEL DIFF ${label} ===`);
    L.push(`region        : ${m.width}x${m.height} (${m.pixels.toLocaleString()} px)`);
    L.push('');
    L.push('COVERAGE  (geometry — independent of every shading question)');
    L.push(`  we cover    : ${(m.bothCovered + m.oursOnly).toLocaleString()} px (${pct(m.coveragePct)})`);
    L.push(`  truth covers: ${(m.bothCovered + m.truthOnly).toLocaleString()} px (${pct(m.truthCoveragePct)})`);
    L.push(`  MISSING     : ${m.truthOnly.toLocaleString()} px (${pct(m.missingPct)}) — truth drew, we did not`);
    L.push(`  spurious    : ${m.oursOnly.toLocaleString()} px — we drew, truth did not`);
    L.push(`  missing bbox: ${m.missingBbox ? `x=${m.missingBbox.x} y=${m.missingBbox.y} ` +
           `${m.missingBbox.w}x${m.missingBbox.h}` : 'none'}`);
    L.push('');
    L.push(`COLOUR  (only the ${m.bothCovered.toLocaleString()} px BOTH cover — the only place it means anything)`);
    L.push(`  max |delta| : B=${m.maxAbs[0]} G=${m.maxAbs[1]} R=${m.maxAbs[2]} A=${m.maxAbs[3]}`);
    L.push(`  mean |delta|: B=${m.meanAbs[0].toFixed(3)} G=${m.meanAbs[1].toFixed(3)} ` +
           `R=${m.meanAbs[2].toFixed(3)} A=${m.meanAbs[3].toFixed(3)}`);
    L.push(`  differing   : ${m.differing.toLocaleString()} px (${pct(m.differingPct)}) at >${m.threshold} LSB`);
    L.push(`  bbox        : ${m.bbox ? `x=${m.bbox.x} y=${m.bbox.y} ${m.bbox.w}x${m.bbox.h}` : 'none'}`);
    L.push('');
    if (m.missingPct > 1) {
        L.push(`⇒ COVERAGE problem dominates: ${pct(m.missingPct)} of the frame was never drawn.`);
        L.push('  Find which captured draw covers the missing bbox and replay that draw alone.');
        L.push('  Chasing colour before coverage is fixed is wasted effort.');
    } else if (m.differing === 0) {
        L.push('EXACT within tolerance.');
    } else if (m.differingPct < 0.1) {
        L.push('Coverage is right; near match on colour — inspect the bbox.');
    } else {
        L.push('Coverage is right; COLOUR is wrong. Now a shading question, not a geometry one.');
    }
    L.push('');
    L.push('⚠ THIS NUMBER IS A MEASUREMENT, NOT A MECHANISM. It shows our translation of the captured');
    L.push('  state reproduces the pixels; it establishes nothing about MvC2. Record it as');
    L.push("  record_attempt(..., outcome='masks_only'), never as a finding.");
    L.push('⚠ Only the FULL draw list is a valid comparison — alpha blending is not decomposable.');
    return L.join('\n');
}
