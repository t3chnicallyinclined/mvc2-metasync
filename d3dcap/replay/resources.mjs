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
export function createResources(device, pack) {
    const { head, slice } = pack;

    // ── geometry ─────────────────────────────────────────────────────────────────────────────────
    // The captured VB is 2 MiB of which only ~91 KB is referenced, but uploading it whole keeps every
    // draw's firstIndex a direct index into the original buffer — no remapping, nothing to get wrong.
    const vbBytes = slice(head.vb);
    const vertexBuffer = device.createBuffer({
        size: vbBytes.byteLength, usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
    });
    device.queue.writeBuffer(vertexBuffer, 0, vbBytes);

    const ibBytes = slice(head.ib);
    const indexBuffer = device.createBuffer({
        size: ibBytes.byteLength, usage: GPUBufferUsage.INDEX | GPUBufferUsage.COPY_DST,
    });
    device.queue.writeBuffer(indexBuffer, 0, ibBytes);

    // ── textures ─────────────────────────────────────────────────────────────────────────────────
    // ⚠ mipLevelCount is 1 and upload is raw writeTexture, deliberately. Auto-generating mips on an
    // r8unorm INDEX tile averages palette indices; since the palette is 16 banks of 16, an averaged
    // index lands in a different bank entirely. That looks like "wrong colours", not "wrong mip".
    // Going via copyExternalImageToTexture would also colour-manage data that is not a colour.
    const textures = new Map();
    for (const [ptr, t] of Object.entries(head.textures)) {
        const tex = device.createTexture(textureDescriptor(t));
        const bytesPerPixel = toTextureFormat(t.fmt) === 'r8unorm' ? 1 : 4;
        device.queue.writeTexture(
            { texture: tex },
            slice(t),
            { bytesPerRow: t.w * bytesPerPixel, rowsPerImage: t.h },
            { width: t.w, height: t.h },
        );
        textures.set(ptr, { tex, view: tex.createView(), ...t });
    }

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
    const samplers = new Map();
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
        if (!readF32(d.vscbHash?.[0], 0, 12, uniformData, f + 0, IDENT3x4)) missing.world++;
        // CBViewProjection = VS cb1: fViewProj at +0 (64 B), fCameraPos at +64 (12 B)
        if (!readF32(d.vscbHash?.[1], 0, 16, uniformData, f + 12, null)) missing.viewProj++;
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
        head, vertexBuffer, indexBuffer, textures, dummyView, getSampler,
        uniformBuffer, uniformStride: UNIFORM_STRIDE, missing,
        texFor: (ptr) => (ptr && textures.has(ptr) ? textures.get(ptr).view : dummyView),
    };
}

/**
 * Vertex layout, straight from the captured D3D11_INPUT_ELEMENT_DESC[].
 * ⚠ shaderLocation 1 (NORMAL) is deliberately ABSENT: the vertex shader never declares it and the
 * game leaves those 8 bytes uninitialised, so real captures hold NaN there. Declaring it "for
 * debugging" would propagate NaN through interpolation.
 */
export const VERTEX_LAYOUT = {
    arrayStride: 40,
    attributes: [
        { shaderLocation: 0, offset: 0,  format: 'float32x4' },   // POSITION (.xyz read)
        { shaderLocation: 2, offset: 24, format: 'unorm8x4'  },   // TANGENT  = colour 0
        { shaderLocation: 3, offset: 28, format: 'unorm8x4'  },   // BINORMAL = colour 1
        { shaderLocation: 4, offset: 32, format: 'float32x2' },   // TEXCOORD
    ],
};
