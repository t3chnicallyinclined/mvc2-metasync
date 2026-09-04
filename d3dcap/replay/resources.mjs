// RETRO RECEIPTS — PATH B replayer: pack ingest + GPU resource creation.
//
// Everything here exploits the fact that we replay a FIXED, fully captured frame: nothing is
// discovered at runtime, so every resource uploads exactly once and every per-draw cost is a lookup.
//
// ⚠ The .pack embeds the game's own pixels. It is ROM-derived: never commit one, never serve one
// publicly. Captures live in %TEMP%\rrcap and packs are gitignored.

import { toSampler, textureDescriptor, toTextureFormat } from './state.mjs';

const UNIFORM_STRIDE = 256;   // WebGPU minUniformBufferOffsetAlignment; 490 draws = 125 KB

/** Parse the .pack container: "RRPK", u32 header length, JSON header, then concatenated payloads. */
export async function loadPack(url) {
    const buf = new Uint8Array(await (await fetch(url, { cache: 'no-store' })).arrayBuffer());
    const dv = new DataView(buf.buffer);
    if (String.fromCharCode(...buf.subarray(0, 4)) !== 'RRPK') throw new Error('not a .pack file');
    const headLen = dv.getUint32(4, true);
    const head = JSON.parse(new TextDecoder().decode(buf.subarray(8, 8 + headLen)));
    const base = 8 + headLen;
    const slice = (r) => buf.subarray(base + r.off, base + r.off + r.len);
    return { head, slice };
}

/**
 * Build every GPU resource the frame needs.
 *
 * Uploads once: the vertex buffer, the index buffer, every distinct texture, every distinct sampler,
 * and one uniform buffer holding a 256-byte-aligned slice per draw. After this, rendering a frame is
 * pure state-setting plus drawIndexed.
 */
/** Upload every texture record of `pack` that carries bytes into `textures` (keyed by the pack's texture key).
 *  A FrameRecord (tape-player.mjs) carries a texture's bytes ONLY in the frame that first uses it; later frames
 *  reference it meta-only. So records must be uploaded in ARRIVAL ORDER, whether or not they are ever shown --
 *  TapePlayer calls this on every decoded record (seek fix, 2026-09-03: jumping 0 -> 60 hit a meta-only texture and
 *  writeTexture failed on an undefined source). Meta-only entries are skipped here and resolved from `textures`. */
export function uploadTextures(device, pack, textures) {
    const { head, slice } = pack;
    let uploaded = 0;
    for (const [ptr, t] of Object.entries(head.textures)) {
        if (textures.has(ptr)) continue;
        const bytes = slice(t);
        if (!bytes) continue;                       // meta-only reference: uploaded by an earlier record
        const tex = device.createTexture(textureDescriptor(t));
        const bytesPerPixel = toTextureFormat(t.fmt) === 'r8unorm' ? 1 : 4;
        device.queue.writeTexture({ texture: tex }, bytes, { bytesPerRow: t.w * bytesPerPixel, rowsPerImage: t.h }, { width: t.w, height: t.h });
        textures.set(ptr, { tex, view: tex.createView(), ...t });
        uploaded++;
    }
    return uploaded;
}

/**
 * One frame's vertex or index buffer.
 *
 * A `.seq` frame carries the whole buffer ({off,len} into the pack). A FrameRecord v2 carries a LIST OF SEGMENTS
 * (rr-render/src/feed.rs): inline bytes this record brought, or a reference to a blob an earlier record sent —
 * the static stage deck is one blob for a whole match instead of ~464 KB re-sent 60 times a second. The
 * concatenation of the segments is byte-for-byte the buffer the old format sent whole, which is why nothing above
 * this function knows the difference: every `firstIndex` and `voff` still indexes the assembled buffer.
 *
 * Segments are written straight into the GPU buffer at their running offset, so sharing costs no CPU copy at all —
 * assembling a ~700 KB Uint8Array per frame on the main thread would have handed back most of what the worker saved.
 */
function geometryBuffer(device, rec, slice, usage, blobs) {
    if (!rec.segs) {                                  // .seq path: one whole buffer
        const bytes = slice(rec);
        const buf = device.createBuffer({ size: bytes.byteLength, usage: usage | GPUBufferUsage.COPY_DST });
        device.queue.writeBuffer(buf, 0, bytes);
        return buf;
    }
    const buf = device.createBuffer({ size: rec.len, usage: usage | GPUBufferUsage.COPY_DST });
    let at = 0, inlineAt = 0;
    for (const s of rec.segs) {
        if (s.blob < 0) { device.queue.writeBuffer(buf, at, rec.inline, inlineAt, s.len); inlineAt += s.len; }
        else {
            const b = blobs?.get(s.blob);
            if (!b) throw new Error(`FrameRecord references geometry blob ${s.blob} before it was sent`);
            device.queue.writeBuffer(buf, at, b);
        }
        at += s.len;
    }
    return buf;
}

export function createResources(device, pack, shared = null) {
    const { head, slice } = pack;
    // A SEQUENCE hands the same `shared` object to every frame. Frames of one burst overwhelmingly
    // bind the same textures and samplers -- the stage art is uploaded once for the whole match
    // segment, and only the character tiles that actually changed are uploaded again. Without this,
    // 90 frames re-upload the same stage pages 90 times and the playback stalls on upload, not draw.
    // Keyed by the pack's own texture key ("pointer#generation"), which IS a content identity.
    const texShared = shared?.textures ?? null;
    const sampShared = shared?.samplers ?? null;

    // ── geometry ─────────────────────────────────────────────────────────────────────────────────
    // The captured VB is 2 MiB of which only ~91 KB is referenced, but uploading it whole keeps every
    // draw's firstIndex a direct index into the original buffer — no remapping, nothing to get wrong.
    const vertexBuffer = geometryBuffer(device, head.vb, slice, GPUBufferUsage.VERTEX, pack.blobs);
    const indexBuffer = geometryBuffer(device, head.ib, slice, GPUBufferUsage.INDEX, pack.blobs);

    // ── textures ─────────────────────────────────────────────────────────────────────────────────
    // ⚠ mipLevelCount is 1 and upload is raw writeTexture, deliberately. Auto-generating mips on an
    // r8unorm INDEX tile averages palette indices; since the palette is 16 banks of 16, an averaged
    // index lands in a different bank entirely. That looks like "wrong colours", not "wrong mip".
    // Going via copyExternalImageToTexture would also colour-manage data that is not a colour.
    const textures = texShared ?? new Map();
    const uploaded = uploadTextures(device, pack, textures);

    // A 1x1 opaque white stand-in for slots a draw does not bind. The bind group layout is fixed, so
    // every draw must supply both textures and both samplers even when the shader ignores one.
    const dummyTex = device.createTexture({
        size: { width: 1, height: 1 }, format: 'rgba8unorm',
        usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST,
    });
    device.queue.writeTexture({ texture: dummyTex }, new Uint8Array([255, 255, 255, 255]),
                              { bytesPerRow: 4 }, { width: 1, height: 1 });
    const dummyView = dummyTex.createView();

    // ── samplers ─────────────────────────────────────────────────────────────────────────────────
    // Sampler state is PER DRAW (measured: 1008 linear+clamp, 368 point+clamp, 22 point+repeat,
    // 3 linear+repeat). Deduped by the captured descriptor so we create ~4, not ~1000.
    const samplers = sampShared ?? new Map();
    const getSampler = (desc) => {
        const key = desc ? `${desc.filter}:${desc.u}:${desc.v}:${desc.w}` : 'null';
        let s = samplers.get(key);
        if (!s) { s = device.createSampler(toSampler(desc)); samplers.set(key, s); }
        return s;
    };

    // ── per-draw uniforms ────────────────────────────────────────────────────────────────────────
    // The game's four constant buffers packed into one 160-byte block per draw, padded to 256 for
    // dynamic-offset alignment. Content comes from the CB payloads the capture shadowed at
    // UpdateSubresource — NOT from a Present-time snapshot, which is stale.
    const cb = new Map();
    for (const [hash, r] of Object.entries(head.constantBuffers)) cb.set(hash.toUpperCase(), slice(r));

    const draws = head.draws;
    const uniformData = new Float32Array((draws.length * UNIFORM_STRIDE) / 4);
    const readF32 = (hash, byteOff, count, out, outOff, fallback) => {
        const src = hash && hash !== '00000000' ? cb.get(String(hash).toUpperCase()) : null;
        if (!src || src.byteLength < byteOff + count * 4) {
            for (let i = 0; i < count; i++) out[outOff + i] = fallback ? fallback[i] : 0;
            return false;
        }
        const dv = new DataView(src.buffer, src.byteOffset, src.byteLength);
        for (let i = 0; i < count; i++) out[outOff + i] = dv.getFloat32(byteOff + i * 4, true);
        return true;
    };

    const IDENT3x4 = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0];
    const missing = { world: 0, viewProj: 0 };
    draws.forEach((d, i) => {
        const f = (i * UNIFORM_STRIDE) / 4;
        // CBWorld = VS cb0 (48 B). Identity is CORRECT for the fullscreen-quad draws.
        // ⚠ Only a vs_world draw NEEDS these. vs_flat is a pass-through that declares no constant
        // buffer at all, so an absent matrix there is normal -- counting it produced a standing
        // "3 draws without a world matrix ... WILL be wrong" warning about three draws that were
        // perfectly fine, which is exactly the kind of noise that gets a real warning ignored.
        const needsMatrices = d.vsVariant === 'vs_world';
        if (!readF32(d.vscbHash?.[0], 0, 12, uniformData, f + 0, IDENT3x4) && needsMatrices) {
            missing.world++;
        }
        // CBViewProjection = VS cb1: fViewProj at +0 (64 B), fCameraPos at +64 (12 B)
        if (!readF32(d.vscbHash?.[1], 0, 16, uniformData, f + 12, null) && needsMatrices) {
            missing.viewProj++;
        }
        readF32(d.vscbHash?.[1], 64, 3, uniformData, f + 28, null);
        // CBFog = PS cb2: fFogColor +0 (12 B), fFogDensity +12, fFogStart +24, fFogInvRange +28
        readF32(d.pscbHash?.[2], 0, 4, uniformData, f + 32, null);
        readF32(d.pscbHash?.[2], 24, 2, uniformData, f + 36, null);
        // A shader that binds no fog constant buffer must not have fog applied. Forcing density to 0
        // makes the shared fog tail bit-exact inert rather than needing separate entry points.
        if (d.psFog === false) uniformData[f + 35] = 0;
        // CBROPTest = PS cb0: fAlphaRef +0
        readF32(d.pscbHash?.[0], 0, 1, uniformData, f + 38, null);
    });

    const uniformBuffer = device.createBuffer({
        size: uniformData.byteLength, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
    });
    device.queue.writeBuffer(uniformBuffer, 0, uniformData);

    return {
        head, vertexBuffer, indexBuffer, textures, dummyView, getSampler, uploaded,
        uniformBuffer, uniformStride: UNIFORM_STRIDE, missing,
        texFor: (ptr) => (ptr && textures.has(ptr) ? textures.get(ptr).view : dummyView),
    };
}

/**
 * Vertex layout, built from the captured D3D11_INPUT_ELEMENT_DESC[] rather than hardcoded.
 *
 * ⚠ shaderLocation 1 (NORMAL) is deliberately DROPPED: the vertex shader never declares it and the
 * 40-byte layouts leave those bytes uninitialised, so real captures hold NaN there. Declaring it
 * "for debugging" would propagate NaN through interpolation.
 *
 * ⚠ There is no single layout to hardcode. Frame 4261 has four input layouts: three 40-byte ones
 * that happen to be byte-identical, and one 28-byte POSITION+NORMAL layout with no colours and no
 * texture coordinates at all. A hardcoded arrayStride of 40 reads that fourth layout at the wrong
 * pitch and its colours out of thin air.
 */
const SEMANTIC_LOCATION = { POSITION: 0, NORMAL: 1, TANGENT: 2, BINORMAL: 3, TEXCOORD: 4 };

// DXGI_FORMAT -> GPUVertexFormat, for the formats this capture actually uses. Anything else must
// throw: silently substituting a same-width format would put plausible garbage in a varying.
const VERTEX_FORMAT = {
    2:  'float32x4',   // R32G32B32A32_FLOAT
    6:  'float32x3',   // R32G32B32_FLOAT
    16: 'float32x2',   // R32G32_FLOAT
    28: 'unorm8x4',    // R8G8B8A8_UNORM  (RGBA, NOT BGRA -- no swizzle needed)
};

// The attributes the WGSL actually declares. A layout that cannot supply all of them cannot feed the
// shader, and WebGPU rejects such a pipeline outright -- so those draws are skipped and counted
// rather than rendered from invented data.
export const REQUIRED_LOCATIONS = [0, 2, 3, 4];

export function vertexLayoutFor(stride, elements) {
    const attributes = [];
    for (const e of elements || []) {
        const shaderLocation = SEMANTIC_LOCATION[e.semantic];
        if (shaderLocation === undefined || shaderLocation === 1) continue;
        const format = VERTEX_FORMAT[e.format];
        if (!format) throw new Error(`unmapped DXGI vertex format ${e.format} on ${e.semantic}`);
        attributes.push({ shaderLocation, offset: e.offset, format });
    }
    const have = new Set(attributes.map((a) => a.shaderLocation));
    if (!REQUIRED_LOCATIONS.every((l) => have.has(l))) return null;
    return { arrayStride: stride, attributes };
}
