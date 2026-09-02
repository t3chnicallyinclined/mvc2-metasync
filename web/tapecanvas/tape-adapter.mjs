// tape-adapter.mjs — Steam MvC2 GGPO-tape (0.3.28 schema) -> SpriteClient state.
//
// This is the OBJS/GSTA adapter the OWNED-RENDER-BUILD-SPEC calls for: it converts a
// decoded 0.3.28 state tape frame into the EXACT SpriteClient.slot[0..5] + .objects[] +
// .hud shape that maplecast sprite-client.mjs's onGSTA/onOBJS produce from the live DC
// wire, so the proven buildEmitterDrawList/buildDrawList + SpriteGPU.render path runs
// VERBATIM off a Steam tape. No render-code changes; only a field-copy transport (the
// same role onGSTA plays — sprite-client.mjs:onGSTA is a byte-parse, we write the fields).
//
// GROUNDED (cited to the tape + the render code, not guessed):
//   • Slot layout is INTERLEAVED: slot 2i = P1 char i, slot 2i+1 = P2 char i. CONFIRMED by
//     (a) px[6] = [-213,+213,-213,+213,-213,+213] (even slots spawn LEFT = P1, odd RIGHT = P2),
//     (b) costume[6] = [1,2,1,2,1,2], (c) sprite-client.mjs drawHUD P1=[0,2,4] P2=[1,3,5].
//   • screen_x/y := tape sx/sy (H+0x124/128). sy == ground (433.4) for grounded chars, i.e.
//     the FOOT anchor — exactly the own-origin pen buildEmitterDrawList expects at owner.exx/eyy.
//   • scaleX/scaleY := zx/CpsX, zy/CpsY. zx (H+0x130) already = CpsX·sprite_scale, so dividing
//     by CpsX recovers sprite_scale; buildEmitterDrawList/​buildDrawList re-apply asmScaleX(5/3)=
//     CpsX, giving total = zx (NOT zx/CpsX² — that was the undersize bug; OWNED-RENDER §1).
//   • draw_layer := tape layer[6]. buildEmitterDrawList's `useLayer` groupKey (sprite-client.mjs)
//     reads sl.draw_layer ascending (lower = behind) — spec §4 layering with NO client re-sort.
//     Feed layer, DON'T set engZ (the tape has no node+0xE8), so the useLayer path is taken.
//   • sprite_id := sid & 0x7FFF (bit15 = xform flag, sprite-client masks it identically).
//   • EFFECTS (OWNED-RENDER §"0.3.29 CAPTURE DELTA"). On a 0.3.28 tape they stay DARK: the objs
//     carry owner=255 and gfx=H+0x1A8 (Dat_Pal, mislabelled — never resolves). On a 0.3.29 tape
//     the reader ships the CONFIRMED offsets: owner=H+0x28 (resolved to a slot u8), gfx1=H+0x1A0
//     (Dat_GFX1 pixel bank), gfx2=H+0x1A4 (Dat_GFX2 assembly bank), scale=H+0x130/134 ÷4096.
//     Sprite-class effects (cat 1-4) then render through the SAME emitter (GFX2, sel=sid) part-
//     assembly as a body — own-origin (obj sx/sy), additive — NOT a 0x0CED directory (that keys
//     only 3D-class cat 5-13, which are OUT OF SCOPE this release).

export const CPSX = 5 / 3;      // 1.6666666 — asmScaleX (work.asm:44); matches sprite-client
export const CPSY = 15 / 7;     // 2.1428570 — asmScaleY (work.asm:45)
export const HP_MAX = 144;      // loc_8C0F0FDC (life + meter both /144)

// Interleave: even slot = P1, odd slot = P2 (see header).
export const P1_SLOTS = [0, 2, 4];
export const P2_SLOTS = [1, 3, 5];

// 0.3.28 frame schema field indices. VERIFIED against the tape's own schema string in the
// constructor; a mismatch throws loudly rather than silently mis-reading a column.
// ⭐ INDICES ARE RESOLVED FROM THE TAPE'S OWN SCHEMA STRING, not hardcoded.
// They used to be a fixed map plus a SCHEMA_EXPECT assertion, which is correct but brittle: the
// moment a column is added or removed every index below it shifts and the map has to be re-cut by
// hand. Resolving by NAME makes a column drop a no-op here.
//
// ⚠ REQUIRED vs OPTIONAL is the whole point. `frame` and `hp` are required -- `hp` is what the
// server derives the objective winner from, so a tape without it is not a tape. Every PER-SLOT
// RENDER column is OPTIONAL, because tape v3 removes them: they are duplicated, at better
// precision, by the `nodes` stream (fsx/fsy are f32; the columns rounded to i16). If a render
// column is missing AND there is no `nodes` stream, that is a real error and we say so.
const F_REQUIRED = ['frame', 'hp'];
const F_NAMES = {
  frame: 'frame', hp: 'hp[6]', vx: 'vx[6]', vy: 'vy[6]', combo_dealt: 'combo_dealt[6]',
  p1_meter: 'p1_meter', p2_meter: 'p2_meter', meter_fill: 'meter_fill', red_hp: 'red_hp[6]',
  facing: 'facing[6]', hitstun: 'hitstun[6]', drawn: 'drawn[6]', sid: 'sid[6]',
  atimer: 'atimer[6]', sx: 'sx[6]', sy: 'sy[6]', zx: 'zx[6]', zy: 'zy[6]',
  flash: 'flash[6]', glow: 'glow[6]', layer: 'layer[6]', timer: 'timer',
  p2_meter_fill: 'p2_meter_fill', round_no: 'round_no',
};
// the per-slot columns tape v3 drops; absent is fine IFF the nodes stream is present
const F_RENDER = ['facing', 'drawn', 'sid', 'atimer', 'sx', 'sy', 'zx', 'zy', 'flash', 'glow', 'layer'];

function bindSchema(schemaStr, hasNodes) {
  const toks = String(schemaStr || '').replace(/^\[|\]$/g, '').split(',').map(t => t.trim());
  const F = {};
  for (const [key, col] of Object.entries(F_NAMES)) F[key] = toks.indexOf(col);
  const missingReq = F_REQUIRED.filter(k => F[k] < 0);
  if (missingReq.length) {
    throw new Error(`tape-adapter: schema has no ${missingReq.map(k => F_NAMES[k]).join(', ')} — ` +
                    `this is not a usable tape (hp is what the winner is derived from).`);
  }
  if (!hasNodes) {
    const missingRender = F_RENDER.filter(k => F[k] < 0);
    if (missingRender.length) {
      throw new Error(`tape-adapter: schema is missing render columns ` +
        `[${missingRender.map(k => F_NAMES[k]).join(', ')}] and the tape carries no \`nodes\` stream. ` +
        `A v3 tape must ship one; a v2 tape must keep the columns.`);
    }
  }
  return F;
}

// ⭐ TAPE v3 — the engine's own draw list, fighters and pool objects INTERLEAVED, in paint order.
// The index of a record IS its z-order (back to front), exactly as FUN_140620F10 walks it. There is
// no sort to apply here on purpose: the engine's array is already sorted, and every ordering bug in
// this renderer came from trying to rebuild that order instead of recording it.
//   44 B: u8 kind, u8 slot, u8 cat, i8 sort, u8 layer, u8 face, u8 owner, u8 drawn,
//         u16 sid, u16 pal, u16 flash, u8 glow, u8 is_effect, u8 blend, u8 atimer,
//         u16 zx, u16 zy, u16 effect_key, f32 fsx, f32 fsy, f32 depth, u32 gfx1, u32 gfx2
// TAPE v4 (agent 0.3.34+): the same record with a 6 B tail -- u16 angle (H+0x148, 0x10000 = 360
// degrees, 0 = axis-aligned; the SH4 rotation path, NOT a flag), i16 hotx, i16 hoty (H+0x178, the
// rotation pivot). The tape says which via `nodes_stride` (44 = v3, 50 = v4).
export function decodeNodesBytes(bytes, stride = 44) {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const byFrame = new Map();
  let off = 0;
  while (off + 6 <= bytes.length) {
    const frame = dv.getUint32(off, true); off += 4;
    const count = dv.getUint16(off, true); off += 2;
    const out = [];
    for (let i = 0; i < count && off + stride <= bytes.length; i++) {
      out.push({
        kind: bytes[off], slot: bytes[off + 1], cat: bytes[off + 2],
        sort: dv.getInt8(off + 3), layer: bytes[off + 4], face: bytes[off + 5],
        owner: bytes[off + 6], drawn: bytes[off + 7],
        sid: dv.getUint16(off + 8, true), pal: dv.getUint16(off + 10, true),
        flash: dv.getUint16(off + 12, true), glow: bytes[off + 14],
        isEffect: bytes[off + 15], blend: bytes[off + 16], atimer: bytes[off + 17],
        zx: dv.getUint16(off + 18, true) / 4096, zy: dv.getUint16(off + 20, true) / 4096,
        effectKey: dv.getUint16(off + 22, true),
        sx: dv.getFloat32(off + 24, true), sy: dv.getFloat32(off + 28, true),
        depth: dv.getFloat32(off + 32, true),
        gfx1: dv.getUint32(off + 36, true), gfx2: dv.getUint32(off + 40, true),
        angle: stride >= 50 ? dv.getUint16(off + 44, true) : 0,
        hotx: stride >= 50 ? dv.getInt16(off + 46, true) : 0,
        hoty: stride >= 50 ? dv.getInt16(off + 48, true) : 0,
        z: i,                       // paint order, and the ONLY ordering input the renderer needs
      });
      off += stride;
    }
    byFrame.set(frame, out);
  }
  return byFrame;
}

// ⭐ TAPE v5 -- the SYSTEM-A (world-space) class: shadows, 1P/2P markers, super glows, hail chunks,
// HUD, stage props. Per frame: [u32 frame, u16 count, count x 96 B {u8 list, u8 pad[3], u32 flags,
// f32[16] matrix (column-major 4x4; its row-major 3x4 transpose is Steam's CBWorld, byte-exact),
// f32[3] colour, u16 obj (index into aobjs, 0xFFFF none), u16 pad, u64 model ptr}].
export function decodeANodes(bytes, stride = 96) {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const byFrame = new Map();
  let off = 0;
  while (off + 6 <= bytes.length) {
    const frame = dv.getUint32(off, true); off += 4;
    const count = dv.getUint16(off, true); off += 2;
    const out = [];
    for (let i = 0; i < count && off + stride <= bytes.length; i++) {
      const m = new Float32Array(16);
      for (let k = 0; k < 16; k++) m[k] = dv.getFloat32(off + 8 + k * 4, true);
      out.push({
        list: bytes[off], flags: dv.getUint32(off + 4, true), matrix: m,
        colour: [dv.getFloat32(off + 72, true), dv.getFloat32(off + 76, true), dv.getFloat32(off + 80, true)],
        obj: dv.getUint16(off + 84, true), model: dv.getBigUint64(off + 88, true),
      });
      off += stride;
    }
    byFrame.set(frame, out);
  }
  return byFrame;
}

// the interned polygon-list objects `obj` indexes: [u16 count, count x (u32 len, bytes)]. Each is
// the node's DC-TA list: 0x18 header, then records of a 0x50 header (u32 PCW, ISP, TSP, TCW --
// the TCW names the texture -- ..., i32 payload_size @+0x4C) and 32-byte vertices x y z nx ny nz u v.
export function decodeAObjs(bytes) {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const out = [];
  if (bytes.length < 2) return out;
  const n = dv.getUint16(0, true);
  let off = 2;
  for (let i = 0; i < n && off + 4 <= bytes.length; i++) {
    const len = dv.getUint32(off, true); off += 4;
    const body = bytes.subarray(off, off + len); off += len;
    const recs = [];
    let q = 0x18;
    while (q + 0x50 <= body.length) {
      const bv = new DataView(body.buffer, body.byteOffset + q, 0x50);
      const pcw = bv.getInt32(0, true);
      if (pcw >= 0) break;
      const size = bv.getInt32(0x4C, true);
      const pay = body.subarray(q + 0x50, q + 0x50 + size);
      const verts = [];
      for (let v = 8; v + 32 <= pay.length; v += 32) {
        const f = new Float32Array(pay.buffer.slice(pay.byteOffset + v, pay.byteOffset + v + 32));
        verts.push({ x: f[0], y: f[1], z: f[2], nx: f[3], ny: f[4], nz: f[5], u: f[6], v: f[7] });
      }
      recs.push({ pcw: bv.getUint32(0, true), isp: bv.getUint32(4, true), tsp: bv.getUint32(8, true),
                  tcw: bv.getUint32(12, true), verts });
      q += 0x50 + size;
    }
    out.push({ bytes: body, recs });
  }
  return out;
}

// the palette table `pal` indexes into: N x 32 B ARGB4444 (16 colours), first-seen order.
export function decodePals(bytes) {
  const out = [];
  for (let o = 0; o + 32 <= bytes.length; o += 32) out.push(bytes.subarray(o, o + 32));
  return out;
}


// Decode the OBJS byte stream. Supports BOTH record layouts:
//   0.3.28 (16 B): {u16 sid, i16 sx, i16 sy, u16 zx_q, u8 face, u8 cat, u8 owner, u8 layer, u32 gfx}
//                  — gfx = H+0x1A8 (Dat_Pal, mislabelled; never resolves — effects were dark).
//   0.3.29 (20 B): {u16 sid, i16 sx, i16 sy, u16 zx_q, u8 face, u8 cat, u8 owner, u8 layer,
//                   u32 gfx1, u32 gfx2}
//                  — gfx1 = H+0x1A0 (Dat_GFX1 pixel bank, clusters by effect type),
//                    gfx2 = H+0x1A4 (Dat_GFX2 assembly bank = the atlas/sel selector),
//                    owner = H+0x28 already resolved to a slot u8 (0..5, else 0xFF),
//                    zx_q  = scale × 4096  (÷4096 on read; the 0.3.28 ÷16 gave the bogus 426.625).
// recBytes: 16 (0.3.28) or 20 (0.3.29). Pure; takes a Uint8Array (already gunzipped).
export function decodeObjsBytes(bytes, recBytes = 16) {
  const dv = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const byFrame = new Map();
  let off = 0;
  while (off + 6 <= bytes.length) {
    const frame = dv.getUint32(off, true); off += 4;
    const count = dv.getUint16(off, true); off += 2;
    const objs = [];
    for (let i = 0; i < count; i++) {
      const o = {
        sid: dv.getUint16(off, true),
        sx: dv.getInt16(off + 2, true),
        sy: dv.getInt16(off + 4, true),
        zx: dv.getUint16(off + 6, true),          // raw zx_q (÷4096 = scale)
        face: dv.getUint8(off + 8),
        cat: dv.getUint8(off + 9),
        owner: dv.getUint8(off + 10),
        layer: dv.getUint8(off + 11),
      };
      if (recBytes >= 20) {
        o.gfx1 = dv.getUint32(off + 12, true) >>> 0;   // Dat_GFX1 (pixel bank / effect-type cluster)
        o.gfx2 = dv.getUint32(off + 16, true) >>> 0;   // Dat_GFX2 (assembly bank = atlas selector)
        o.gfx = o.gfx1;                                  // back-compat alias
      } else {
        o.gfx = dv.getUint32(off + 12, true) >>> 0;     // 0.3.28 single (wrong) gfx = Dat_Pal
        o.gfx1 = o.gfx; o.gfx2 = 0;
      }
      if (recBytes >= 32) {                             // 0.3.32 FULL EFFECT WIRE tail (12 B)
        o.isEffect  = dv.getUint8(off + 20) ? 1 : 0;   // blk+0x6CE8 value-test (3D-class)
        o.blend     = dv.getUint8(off + 21);           // sprite-gpu nibble (0x11 add / 0x45 alpha / 0x00 opaque)
        o.drawn     = dv.getUint8(off + 22);           // H+0x170 draw gate
        o.atimer    = dv.getUint8(off + 23);           // H+0x186 anim-cell countdown
        o.zy        = dv.getUint16(off + 24, true);    // scaleY ×4096 (H+0x134)
        o.effect_key = dv.getUint16(off + 26, true);   // in-bank gfx low16 (else gfx1&0xffff)
        o.depth     = dv.getFloat32(off + 28, true);   // H+0x12C (DC node+0xE8) byte-exact z
      }
      objs.push(o);
      off += recBytes;
    }
    byFrame.set(frame, objs);
  }
  return byFrame;
}

export class TapeAdapter {
  // decoded = { schema:string, frames:Array<Array>, costume:number[6],
  //             p1_team:number[3], p2_team:number[3], objsByFrame:Map<frame,obj[]> }
  constructor(decoded) {
    this.schema = decoded.schema;
    this.frames = decoded.frames || [];
    this.costume = decoded.costume || [1, 2, 1, 2, 1, 2];
    this.p1_team = decoded.p1_team || [0, 0, 0];
    this.p2_team = decoded.p2_team || [0, 0, 0];
    // stage_id — tape header field for the STAGE backdrop (stage-client.mjs). Absent on
    // 0.3.28 AND on the current 0.3.29 tape (blocked — see stage-client.mjs HANDOFF).
    this.stage_id = (decoded.stage_id != null) ? (decoded.stage_id | 0) : null;
    this.objsByFrame = decoded.objsByFrame || new Map();
    this.frameCount = this.frames.length;
    // objs record size: 16 (0.3.28, gfx=Dat_Pal, effects dark) or 20 (0.3.29, gfx1+gfx2).
    this.objRecBytes = decoded.objRecBytes || 16;
    // Handle -> atlas calibration table: { gfx2_handle(number|"0x..") : char_id }. Populated
    // offline from the per-tape objs calibration blob (OWNED-RENDER §"0.3.29 CAPTURE DELTA"
    // item 4). Empty => the resolver falls back to the owner's char atlas.
    this.fxBankMap = decoded.fxBankMap || {};
    // EFFECTS GATE. On a 0.3.28 tape there is NO gfx2 (and owner=255) so effects stay dark
    // regardless. On a 0.3.29 tape, flip effectsOn to route cat 1-4 sprite-class effects
    // through the emitter (GFX2, sel=sid) part-assembly, own-origin, additive.
    this.effectsOn = false;
    // ⭐ TAPE v3. `nodesByFrame` is the engine's own draw list -- fighters AND pool objects,
    // interleaved, in paint order. When it is present it SUPERSEDES both objsByFrame and the
    // per-slot render columns: index is z-order, so there is nothing to sort and no layer
    // direction to choose. Must be set BEFORE _verifySchema, which uses its presence to decide
    // whether the (now optional) render columns are allowed to be missing.
    this.nodesByFrame = decoded.nodesByFrame || new Map();
    this.pals = decoded.pals || [];
    this.isV3 = this.nodesByFrame.size > 0;
    if (this.schema) this._verifySchema(this.schema);
  }

  static fromDecoded(rawTape, objsBytes) {
    const recBytes = TapeAdapter.detectObjRecBytes(rawTape);
    return new TapeAdapter({
      schema: rawTape.schema, frames: rawTape.frames, costume: rawTape.costume,
      p1_team: rawTape.p1_team, p2_team: rawTape.p2_team, objRecBytes: recBytes,
      objsByFrame: objsBytes ? decodeObjsBytes(objsBytes, recBytes) : new Map(),
      // v3 streams, when the tape carries them. Both are gunzipped by the caller, like objs.
      nodesByFrame: rawTape.nodesBytes ? decodeNodesBytes(rawTape.nodesBytes, rawTape.nodesStride || 44) : new Map(),
      pals: rawTape.palsBytes ? decodePals(rawTape.palsBytes) : [],
      // v5: world-space nodes + their polygon-list objects (rendered through the vs_world path)
      anodesByFrame: rawTape.anodesBytes ? decodeANodes(rawTape.anodesBytes, rawTape.anodesStride || 96) : new Map(),
      aobjs: rawTape.aobjsBytes ? decodeAObjs(rawTape.aobjsBytes) : [],
      stage_id: rawTape.stage_id,
    });
  }

  // objs_enc descriptor names the record: 0.3.32 adds is_effect/blend (32 B), 0.3.29 gfx2 (20 B), else 16 B.
  static detectObjRecBytes(rawTape) {
    const enc = String(rawTape.objs_enc || '');
    if (/is_effect|32B/i.test(enc)) return 32;   // 0.3.32 FULL EFFECT WIRE
    return /gfx2/i.test(enc) ? 20 : 16;
  }

  // Sprite-class effect (cat 1-4) atlas resolution (OWNED-RENDER §"0.3.29 CAPTURE DELTA").
  // CLOSED against the REAL 0.3.29 tape (48,452 effect nodes):
  //   • gfx2 (H+0x1A4) is ALWAYS 0 -> it does NOT key the atlas. KEY ON gfx1 (H+0x1A0).
  //   • The atlas is the OWNER's char: every effect's masked sid resolves in the caster's
  //     assembly table 100% (cat1 39841/39841, cat3 4152/4152, cat4 1613/1613). The effect
  //     cell (its projectile/super/spark pose) lives in the SPAWNING fighter's GFX2 bank.
  //   • gfx1 is SHARED across owners (e.g. 0x1700 spawned by slots 0/1/5), so it is the effect-
  //     TYPE discriminator, not the atlas — owner is the atlas key. gfx1 stays available as the
  //     fxBankMap key for OWNERLESS nodes (owner=255, ~5.9%: global super-flash) which have no
  //     caster to borrow: gfx1 -> char_id from the calibration blob / a learned map.
  // Returns char_id or null (null = defer; ownerless without a gfx1 bankMap entry).
  resolveFxAtlas(o, sc, casters) {
    if (o.owner < 6) return this.charIdForSlot(o.owner);   // OWNER-char atlas (100% coverage)
    if (o.gfx1) {                                           // ownerless -> gfx1 bankMap (calibration)
      const m = this.fxBankMap[o.gfx1] ?? this.fxBankMap['0x' + (o.gfx1 >>> 0).toString(16)];
      if (m != null) return m & 0xff;
    }
    // OWNERLESS GLOBAL-EFFECT ATTRIBUTION (interim; the tape carries NO real owner/effect-key
    // for a global effect-poly node — owner ships 0xFF, server readAllDrawn: "global effects
    // have none"). The SPAWNER's GFX2 bank holds the effect cell (re_kb
    // finding:replica_live_satellite_gfx_residency), so attribute the node to the frame's
    // active effect-CASTER whose loaded assembly ACTUALLY CONTAINS the node's sel. This is not
    // a blind guess — the sel must resolve in that char's own bank; if ZERO or MULTIPLE casters
    // resolve it, we DEFER (return null) rather than draw a colliding cell (render-only-real
    // assets). Only a unique spawner is drawn. The correct general fix = the reader shipping the
    // resolved owner / an effect-poly content key (staged for reader.rs).
    if (sc && casters && casters.size && sc.asmChars) {
      const masked = o.sid & 0x7fff;
      let hit = null, nHit = 0;
      for (const cid of casters) {
        const c = sc.asmChars[cid];
        const recs = c && c.asm && (c.asm[masked] || c.asm[String(masked)]);
        if (recs && recs.length) { hit = cid; if (++nHit > 1) break; }
      }
      if (nHit === 1) return hit;                          // unambiguous spawner atlas
    }
    // PROOF-ONLY escape hatch (window._fxOwnerlessTo=<cid>): force every still-unattributed
    // global effect onto ONE atlas. NOT shipped behavior — it exists to preview what the demon
    // column looks like once the STAGED reader ships the resolved owner (the real fix). Only used
    // by the before/after proof harness; unset in production (null -> defer).
    if (typeof window !== 'undefined' && window._fxOwnerlessTo != null) {
      const cid = window._fxOwnerlessTo & 0xff;
      const c = sc && sc.asmChars && sc.asmChars[cid];
      const masked = o.sid & 0x7fff;
      const recs = c && c.asm && (c.asm[masked] || c.asm[String(masked)]);
      if (recs && recs.length) return cid;
    }
    return null;                                            // unattributable global flash -> defer
  }

  // PER-OBJECT PVR BLEND for a sprite-class effect node (0=opaque/PT, 1=alpha, 2=additive on
  // the listType scale; returned here as the sprite-gpu nibble byte 0x00/0x45/0x11). Ports the
  // live server computeObjectBlend (maplecast_gamestate.cpp): is_effect => additive, else alpha
  // for a projectile/effect. PRIORITY:
  //   (1) o.blend  — the REAL per-object blend byte, IF a future reader ships it (computeObjectBlend
  //       or the captured bank12 TSP). Wins outright. -> pass straight through.
  //   (2) o.isEffect — the reader's node+0x15c-in-Effect-Poly bit, IF shipped -> additive.
  //   (3) INTERIM (today's tape carries neither): the objs stream is 100% sprite-class EFFECT
  //       nodes (cat 1-4; ~0 cat-0 bodies across 86 tapes), i.e. projectiles / supers / auras /
  //       energy / hitsparks — the effect-poly draws computeObjectBlend routes ADDITIVE. Verified
  //       empirically: keying additive on owner==255 alone lit ZERO nodes at the Inferno peak
  //       (Blackheart's energy is owner-ATTRIBUTED, owner=3) — so the interim promotes the whole
  //       sprite-class effect stream to additive (0x11 -> sprite-gpu pipeAdd). ⚠ INTERIM COST: the
  //       caster's own body-cell effect poses (e.g. Blackheart's opaque summon FIGURE, a cape) also
  //       glow, because the tape has no per-node is_effect to split them — that split is exactly
  //       what the STAGED reader.rs is_effect bit / real blend byte restores (then (1)/(2) win and
  //       this heuristic is bypassed). window._fxAdditive=false forces the pre-fix all-alpha
  //       behavior (the DIM render) for A/B stills.
  // Returns the sprite-gpu blend byte {0x00 opaque, 0x45 alpha, 0x11 additive}.
  //
  // ⚠ ADDITIVE IS UNDERIVABLE FROM STEAM RAM. Measured on the real 0.3.32 wire (tape.json, 18,647
  //   effect nodes): is_effect=1 is 0.0% (the blk+0x6CE8 value-test catches only 3D-class polys, and
  //   Steam sprite-class effects carry a recompile handle, not a 0x0CED ptr) AND the reader's
  //   computeObjectBlend byte is 80% opaque(0x00)/20% alpha(0x45)/**0% additive** — because
  //   computeObjectBlend only returns additive when is_effect=1, and the TRUE additive is a runtime PVR
  //   register (0x8C2AA4C4, finding:emitter_blend_is_runtime_state) that Steam (D3D11) can't capture.
  //   ⟹ the reader byte gives the OPAQUE-vs-ALPHA axis but never additive; the gfx1-bank allowlist stays
  //   the best ADDITIVE signal and must OVERRIDE the reader's opaque/alpha for known energy banks, else
  //   supers render flat/opaque (bank 0x17 Lightning Storm ships blend 0x00 = opaque on the real wire).
  effectBlendByte(o) {
    if (o.isEffect) return 0x11;                                    // (1) reader 3D-class effect-poly -> additive
    const bank = (o.gfx1 >>> 8) & 0xff;                             // high byte of the Dat_GFX1 handle
    const realOnly = (typeof window !== 'undefined' && window._fxRealBlendOnly);
    if (o.blend != null) {
      // (2) TRUST the reader's OPAQUE (0x00). A reader-opaque node is a SOLID object (Sentinel's
      //     DRONES, projectile bodies) — NOT an additive glow. Forcing it additive both mis-blends it
      //     AND drops it onto the additive emit path (which loses the owner's costume palette -> the
      //     "drones purple, body black" bug). Only promote a reader-ALPHA (0x45) in a known energy bank
      //     to additive (a dim-alpha there is a mis-rendered glow; additive is not a reader field on
      //     Steam). realOnly disables the promotion for A/B.
      if (!realOnly && (o.blend & 0xff) === 0x45 && TapeAdapter.FX_ADDITIVE_BANKS.has(bank)) return 0x11;
      return o.blend & 0xff;                                        // opaque 0x00 / alpha 0x45 as the reader classified
    }
    // (3) INTERIM (no reader byte, 20B tapes): blanket A/B or the gfx1-bank additive allowlist.
    if (typeof window !== 'undefined' && window._fxAdditive !== undefined)
      return window._fxAdditive ? 0x11 : 0x45;
    return (!realOnly && TapeAdapter.FX_ADDITIVE_BANKS.has(bank)) ? 0x11 : 0x45;
  }

  // kept as a method name for callers; it now BINDS indices instead of asserting fixed ones.
  _verifySchema(schemaStr) {
    this.F = bindSchema(schemaStr, !!(this.nodesByFrame && this.nodesByFrame.size));
  }

  charIdForSlot(s) {
    return (s % 2 === 0) ? (this.p1_team[s >> 1] | 0) : (this.p2_team[s >> 1] | 0);
  }

  _pointCombo(row, sideSlots) {
    let best = 0;
    const cd = row[this.F.combo_dealt] || [];
    for (const s of sideSlots) { const c = cd[s] | 0; if (c > best) best = c; }
    return best;
  }

  // ROLLBACK-SMEAR DE-JITTER (INTERIM, window._deJitter DEFAULT ON). A rollback-heavy online tape
  // stores some PREDICTED frames whose per-slot screen pos SPIKES one frame then REVERSES the next
  // (the catch-up teleport the render replays as stutter). Detect a one-frame outlier — a jump
  // beyond one-frame world motion (tape vx/vy at this.F.vx/this.F.vy) that reverses on the next frame — and
  // interpolate across it. A REAL move continues same-direction (dPrev and dNext share sign) so it
  // is never touched. Stateless (uses fi-1/fi/fi+1) => scrub-safe. The EXACT fix is reader 0.3.33
  // confirmed-only capture; this is the on-existing-tapes interim. Returns [sx,sy] for slot s.
  _deJitterPos(fi, s, sx0, sy0) {
    if (typeof window !== 'undefined' && window._deJitter === false) return [sx0, sy0];
    const prev = this.frames[fi - 1], next = this.frames[fi + 1], cur = this.frames[fi];
    if (!prev || !next || !cur) return [sx0, sy0];
    const psx = prev[this.F.sx], psy = prev[this.F.sy], nsx = next[this.F.sx], nsy = next[this.F.sy];
    const vx = cur[this.F.vx], vy = cur[this.F.vy];
    if (!psx || !psy || !nsx || !nsy) return [sx0, sy0];
    const fix = (c, p, n, v) => {
      const dP = c - p, dN = n - c, thr = 3 * Math.abs(v || 0) + 8;   // world motion + camera/round slack
      return (Math.abs(dP) > thr && Math.abs(dN) > thr && (dP > 0) !== (dN > 0)) ? (p + n) / 2 : c;
    };
    return [fix(sx0, psx[s], nsx[s], vx ? vx[s] : 0), fix(sy0, psy[s], nsy[s], vy ? vy[s] : 0)];
  }

  // Write frame `fi` into a SpriteClient (or a SpriteClient-shaped object with slot[6]).
  //   opts.load(sc, charId) — lazy atlas loader (sc.loadAsmChar emitter / sc.loadChar whole-sprite).
  //   opts.now             — timestamp for sl.t (default performance.now()/0).
  // Returns the game-frame number applied.
  applyFrame(sc, fi, opts = {}) {
    const row = this.frames[fi];
    if (!row) return -1;
    const now = (opts.now != null) ? opts.now
      : ((typeof performance !== 'undefined') ? performance.now() : 0);
    sc.inMatch = 1; sc.screenW = 640; sc.screenH = 480;

    const hp = row[this.F.hp], red = row[this.F.red_hp], face = row[this.F.facing], drawn = row[this.F.drawn];
    const sid = row[this.F.sid], sx = row[this.F.sx], sy = row[this.F.sy], zx = row[this.F.zx], zy = row[this.F.zy];
    const layer = row[this.F.layer], glow = row[this.F.glow], flash = row[this.F.flash];

    for (let s = 0; s < 6; s++) {
      const sl = sc.slot[s];
      const cid = this.charIdForSlot(s);
      sl.vx = 0; sl.vy = 0; sl.t = now;               // frozen frame — no extrapolation
      sl.active = drawn[s] ? 1 : 0;
      sl.char_id = cid;
      sl.facing = face[s] | 0;
      sl.palette = 0;
      const [djx, djy] = this._deJitterPos(fi, s, sx[s], sy[s]);   // rollback-smear de-jitter (INTERIM)
      sl.screen_x = djx; sl.screen_y = djy; sl.pos_x = djx;
      const rawSid = sid[s] | 0;
      sl.sprite_id = rawSid & 0x7fff;                 // GFX2[sid & 0x7FFF]
      sl.sid_xform = (rawSid & 0x8000) ? 1 : 0;
      sl.scaleX = (zx[s] || CPSX) / CPSX;             // recover sprite_scale; renderer re-applies CpsX
      sl.scaleY = (zy[s] || CPSY) / CPSY;
      sl.draw_layer = (layer[s] === 0xFF) ? 0xFF : (layer[s] | 0);
      sl.engZ = undefined;                            // no node+0xE8 on the tape -> useLayer path
      sl.health = hp[s] | 0; sl.red_health = red[s] | 0; sl._maxhp = HP_MAX;
      sl.pal12d = 0; sl.pal12e = 0; sl.overlay1a4 = 0;
      sl.glow = glow[s] | 0; sl.flash = flash[s] | 0;
      // VICTIM HIT-FLASH (render-only, sh4-re 0.3.29). The H+0x172 hit-flash word is the
      // engine's true trigger, but on THIS tape the `flash` column is CONSTANT per slot
      // (16 + slot*8, never varies over 10,592 frames — a mis-wired capture offset), so it
      // cannot drive the flash. `hitstun` (H, schema idx 16) DOES vary and marks the victim.
      // The real hit-flash is BRIEF (~2 frames at impact), NOT the whole hitstun, so fire on
      // the hitstun RISING EDGE (a fresh hit: this frame's hitstun > the previous frame's) —
      // one flash per hit, matching the engine. buildEmitterDrawList tints the body white when
      // sl.hitFx is set. A later capture that ships a varying `flash` word should override this.
      sl.hitstun = (row[this.F.hitstun] ? (row[this.F.hitstun][s] | 0) : 0);
      const prevRow = (fi > 0) ? this.frames[fi - 1] : null;
      const prevHs = (prevRow && prevRow[this.F.hitstun]) ? (prevRow[this.F.hitstun][s] | 0) : 0;
      sl.hitFx = (sl.hitstun > prevHs) ? 1 : 0;
      // costume (H+0x6C1, 0=LP/1=LK/… confirm-button color index). 0 is a VALID costume
      // (LP/default), so DON'T `|| 1`-coerce it — that mapped every costume-0 fighter (all
      // of P2 in the 59598719 tape) onto costume 1. Drives the body-bank LUT (bank=costume*8).
      sl.costume = (this.costume[s] != null) ? (this.costume[s] | 0) : 0;
      if (sl.active && cid && typeof opts.load === 'function') opts.load(sc, cid);
    }

    sc.hud = {
      timer: row[this.F.timer] | 0,
      p1lvl: row[this.F.p1_meter] | 0, p2lvl: row[this.F.p2_meter] | 0,
      // meter_fill (idx 9) is P1's lifetime METER ACCUMULATOR, p2_meter_fill (idx 32) is P2's
      // — NOT a within-level 0..144 fill (confirmed: both rise monotonically 0->496 / 0->3526
      // over the match while the LEVEL goes up/down as levels are spent). So the LEVEL (0..5)
      // is the reliable meter readout; the fine fill is shown as the fractional shimmer only.
      p1fill: row[this.F.meter_fill] | 0, p2fill: row[this.F.p2_meter_fill] | 0,
      p1combo: this._pointCombo(row, P1_SLOTS), p2combo: this._pointCombo(row, P2_SLOTS),
    };

    const gframe = row[this.F.frame] | 0;
    const raw = this.objsByFrame.get(gframe) || [];
    const objects = [];
    const diag = { total: raw.length, effect: 0, satellite: 0, drawn: 0, gated: 0, threeD: 0, ownerless: 0, additive: 0 };
    // Active effect-CASTERS this frame = the char_ids of every owner-attributed (owner<6) node in
    // the objs list, plus every active body slot. Used to attribute an OWNERLESS global effect to
    // the char whose GFX2 bank holds its cell (resolveFxAtlas — unique-spawner only).
    const casters = new Set();
    for (const o of raw) if (o.owner < 6) casters.add(this.charIdForSlot(o.owner));
    for (let s = 0; s < 6; s++) if (sc.slot[s] && sc.slot[s].active) casters.add(this.charIdForSlot(s));
    for (const o of raw) {
      const masked = o.sid & 0x7fff;
      if (masked === 0 || masked === 0x7fff) continue;
      // Per-object DRAWN flag (reader-shipped, if present). The engine culls a parked pool node
      // (node+0x12C==0 / OOB); the tape has no such flag today, so the emitter's own sx/sy>544
      // cull stands in. Honor an explicit o.drawn==0 when a future reader ships it.
      if (o.drawn === 0) continue;
      const objScale = (o.zx || 0) / 4096;                 // ÷4096 (0.3.29 fix; 0.3.28 read ÷16 -> 426.625 garbage)
      // 3D-class effects (cat 5-13: drop shadows, 3D sparks, 3D stage) are a SEPARATE NaomiLib
      // list walk — NOT captured this release. OUT OF SCOPE (spec) -> skip.
      if (o.cat >= 5) { diag.threeD++; continue; }
      if (o.cat === 0) {
        // body-class satellite (cape / projectile drawn as a body) with a known owner.
        if (o.owner >= 6) continue;
        diag.satellite++;
        objects.push({
          cid: this.charIdForSlot(o.owner), sid: masked, type: o.layer, x: o.sx, y: o.sy,
          xflip: o.face ? 1 : 0, isEffect: 0, blend: null, objScale,
          gfx1: o.gfx1 >>> 0, gfx2: o.gfx2 >>> 0, hotDx: 0, hotDy: 0, hasHot: false, engZ: undefined,
        });
        diag.drawn++;
        continue;
      }
      // SPRITE-CLASS EFFECT (cat 1-4). Renders through the SAME emitter (GFX2, sel=sid)
      // part-assembly as a body (NOT the FX_CID whole-quad, NOT a 0x0CED directory), own-origin
      // (obj sx/sy). Resolve the atlas from gfx2 (bankMap) else the owner's char.
      diag.effect++;
      if (!this.effectsOn || this.objRecBytes < 20) { diag.gated++; continue; }   // dark on 0.3.28 / when off
      const cid = this.resolveFxAtlas(o, sc, casters);
      if (cid == null) { diag.ownerless++; continue; }     // unattributable global flash -> defer
      // PER-OBJECT BLEND (Inferno pillar fix). effectBlendByte() ports the live computeObjectBlend:
      // is_effect/global => additive (0x11 -> sprite-gpu pipeAdd), owner-attributed caster sprite
      // => alpha (0x45). Honors a reader-shipped o.blend/o.isEffect when present. `additive` routes
      // the emitter's ADDITIVE branch (buildEmitterDrawList) so the glow accumulates.
      const blend = this.effectBlendByte(o);
      // is_effect (reader 0.3.32, shared-Effect-Poly node) routes to the FX_CID whole-quad
      // (_emitEffectQuad), NOT the caster-atlas emitAssembly path — so `additive` must be FALSE for
      // it (buildEmitterDrawList checks o.additive BEFORE o.isEffect). On a 20B tape o.isEffect is
      // undefined -> !undefined = true -> additive unchanged (no 20B regression).
      const additive = !(o.isEffect) && ((blend & 0x0f) === 1);   // dst==ONE nibble => additive pipe
      if (additive) diag.additive++;
      objects.push({
        // isEffect:0 -> the emitter renders it as a part-assembly (sprite-class path), keyed by cid's
        // atlas + sel=sid. isEffect:1 (reader 0.3.32) -> _emitEffectQuad(FX_CID) via effect_key. Prefer
        // the reader's real effect_key/depth when present (0.3.32), else gfx1 low-16 / undefined (20B).
        cid, sid: masked, type: o.layer, x: o.sx, y: o.sy,
        xflip: (o.owner < 6 ? (sc.slot[o.owner].facing ? 1 : 0) : (o.face ? 1 : 0)),
        isEffect: (o.isEffect ? 1 : 0), blend, additive, objScale,
        effect_key: (o.effect_key != null ? (o.effect_key & 0xffff) : ((o.gfx1 >>> 0) & 0xffff)),
        gfx1: o.gfx1 >>> 0, gfx2: o.gfx2 >>> 0, owner: o.owner,
        hotDx: 0, hotDy: 0, hasHot: false, engZ: (o.engZ != null ? o.engZ : undefined),
      });
      diag.drawn++;
    }
    sc.objects = objects;
    this._lastObjs = diag;
    return gframe;
  }

  // Build the full-HUD state the vendored HudClient.renderState() consumes from a tape
  // frame. Slots are INTERLEAVED (even=P1, odd=P2). LEVEL (0..5) is the reliable meter
  // readout; fine fill is the fractional shimmer (see sc.hud note). Per-side wins are NOT
  // on the tape (round_no idx 33 is a global round COUNTER 0..15, not a per-side W/L), so
  // wins=0 -> no fabricated stars (matches maplecast hud-client [hud:no-bogus-stars]).
  buildHudState(fi) {
    const row = this.frames[fi];
    if (!row) return { inMatch: false };
    const hp = row[this.F.hp], red = row[this.F.red_hp], drawn = row[this.F.drawn];
    // STATELESS HUD HIT-FLASH (spec §6). The engine flashes the victim's LIFE BAR white on a fresh
    // hit. Fire on the `hitstun` RISING EDGE (this frame's hitstun > prev — one flash per hit; the
    // constant `flash` column is a mis-wired capture, see applyFrame). We compute it STATELESSLY:
    // for frame fi, scan back ≤HUD_FLASH_LEN frames for the latest rising edge and map its age to
    // an intensity. Recomputed from the tape each frame -> survives arbitrary scrubbing (no mutable
    // flashStart carried across renders). FLAG: HUD_FLASH_LEN is a placeholder for the real ROM
    // duration H+0x172 (a one-time sh4-re read) — swap the confirmed value in; nothing else changes.
    const HUD_FLASH_LEN = 6;
    const hitFlashFor = (s) => {
      if (!row[this.F.hitstun]) return 0;
      for (let age = 0; age < HUD_FLASH_LEN; age++) {
        const f = fi - age; if (f <= 0) break;
        const cur = this.frames[f] && this.frames[f][this.F.hitstun] ? (this.frames[f][this.F.hitstun][s] | 0) : 0;
        const prv = this.frames[f - 1] && this.frames[f - 1][this.F.hitstun] ? (this.frames[f - 1][this.F.hitstun][s] | 0) : 0;
        if (cur > prv) return 1 - age / HUD_FLASH_LEN;   // latest rising edge within the window
      }
      return 0;
    };
    const slots = [];
    for (let s = 0; s < 6; s++) {
      slots.push({
        active: drawn[s] ? 1 : 0,
        cid: this.charIdForSlot(s) & 0xff,
        hp: hp[s] | 0, red: red[s] | 0, wins: 0,
        hitFlash: hitFlashFor(s),
      });
    }
    return {
      inMatch: true, infinite: false,
      // frameIdx = the REPLAY index (this function's argument). The HUD's 32-frame life-bar
      // glide (hud-client HudAnim) is a forward function of it: replaying frames in order and
      // running the glide reproduces the engine bar. Pure render field — no reader/tape change.
      frameIdx: fi,
      timer: row[this.F.timer] | 0, round: row[this.F.round_no] | 0,
      slots,
      p1: { fill: row[this.F.meter_fill] | 0, lvl: row[this.F.p1_meter] | 0, combo: this._pointCombo(row, P1_SLOTS) },
      p2: { fill: row[this.F.p2_meter_fill] | 0, lvl: row[this.F.p2_meter] | 0, combo: this._pointCombo(row, P2_SLOTS) },
    };
  }

  objGating(fi) {
    const row = this.frames[fi]; if (!row) return null;
    const raw = this.objsByFrame.get(row[this.F.frame] | 0) || [];
    const cat = {}; let sprite = 0, owned = 0;
    for (const o of raw) {
      cat[o.cat] = (cat[o.cat] | 0) + 1;
      if (o.cat >= 1 && o.cat <= 4) sprite++;
      if (o.owner < 6) owned++;
    }
    return { gameFrame: row[this.F.frame], objs: raw.length, spriteClass: sprite, owned,
             recBytes: this.objRecBytes, byCat: cat };
  }
}

// INTERIM gfx1-bank additive allowlist (effectBlendByte step 3). The high byte of the
// node's Dat_GFX1 handle (gfx1>>8) identifies the effect bank; these three are the
// genuinely-additive energy/beam/demon banks CONFIRMED in tape 59601369's Inferno frame.
// Extend by capturing more supers (each real glow-bank's gfx1>>8). Superseded by the
// reader's exact per-object blend byte (0.3.32); this only fires when o.blend is absent.
TapeAdapter.FX_ADDITIVE_BANKS = new Set([0x15, 0x17, 0x1b]);

// ── Browser loaders ─────────────────────────────────────────────────────────────
// (A) Gzipped raw tape (.json.gz) decoded fully via the platform DecompressionStream.
export async function loadTapeBrowser(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`tape fetch ${resp.status}: ${url}`);
  let text;
  if (/\.gz(\?|$)/.test(url) && typeof DecompressionStream !== 'undefined') {
    text = await new Response(resp.body.pipeThrough(new DecompressionStream('gzip'))).text();
  } else { text = await resp.text(); }
  const tape = JSON.parse(text);
  let objsBytes = null;
  if (tape.objs && typeof tape.objs === 'string' && typeof DecompressionStream !== 'undefined') {
    const bin = Uint8Array.from(atob(tape.objs), c => c.charCodeAt(0));
    const buf = await new Response(new Blob([bin]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
    objsBytes = new Uint8Array(buf);
  }
  return TapeAdapter.fromDecoded(tape, objsBytes);
}

// (B) PRE-DECODED tape.json ({schema, frames, costume, p1_team, p2_team,
// objs:[[frame,[[sid,sx,sy,zx,face,cat,owner,layer,gfx]]]]}) from tools/tape_to_gpujson.py —
// the simplest harness path (no gzip in the browser).
export async function loadTapeJson(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`tape.json fetch ${resp.status}: ${url}`);
  return TapeAdapter.fromJsonObject(await resp.json());
}

// Build from a pre-decoded tape.json object. objs entries are arrays of 9 (0.3.28), 10
// (0.3.29, +gfx2) or 11..13 (+ the staged effect wire) elements:
//   [sid,sx,sy,zx,face,cat,owner,layer,gfx1(,gfx2(,blend(,is_effect(,drawn))))]
// The optional trailing elements are the LIVE effect wire the reader currently DROPS
// (RetroReceipts-agent/agent/src/reader.rs harvest_objs) — staged for a non-isolated session:
//   [10] blend     = the PVR blend byte (server computeObjectBlend / captured bank12 TSP) — wins.
//   [11] is_effect = node+0x15c in the Effect Poly bank [0x0CED0000,0x0CEE0000) (=> additive).
//   [12] drawn     = the engine's per-node visibility gate (node+0x12C!=0 && in-bounds).
// Absent -> undefined -> tape-adapter's INTERIM classifier (effectBlendByte: global effect =>
// additive). Optional t.fxBankMap { "0x..gfx2": char_id } supplies the ownerless-effect
// handle->atlas calibration.
TapeAdapter.fromJsonObject = function (t) {
  const byFrame = new Map();
  let recBytes = 16;
  for (const [frame, objs] of (t.objs || [])) {
    byFrame.set(frame, objs.map(a => {
      if (a.length >= 13) recBytes = 32; else if (a.length >= 10) recBytes = 20;
      return {
        sid: a[0], sx: a[1], sy: a[2], zx: a[3], face: a[4], cat: a[5], owner: a[6], layer: a[7],
        gfx1: (a[8] >>> 0), gfx2: ((a[9] || 0) >>> 0), gfx: (a[8] >>> 0),
        // 0.3.32 FULL EFFECT WIRE: [10]=blend [11]=is_effect [12]=drawn, then extras
        // [13]=zy [14]=effect_key [15]=depth. Absent on 16/20B -> undefined -> interim classifier.
        blend: (a.length >= 11 && a[10] != null) ? (a[10] & 0xff) : undefined,
        isEffect: (a.length >= 12 && a[11] != null) ? (a[11] ? 1 : 0) : undefined,
        drawn: (a.length >= 13 && a[12] != null) ? (a[12] | 0) : undefined,
        zy: (a.length >= 14 && a[13] != null) ? (a[13] | 0) : undefined,
        effect_key: (a.length >= 15 && a[14] != null) ? (a[14] & 0xffff) : undefined,
        engZ: (a.length >= 16 && a[15] != null) ? +a[15] : undefined,
      };
    }));
  }
  return new TapeAdapter({
    schema: t.schema, frames: t.frames, costume: t.costume, p1_team: t.p1_team, p2_team: t.p2_team,
    objsByFrame: byFrame, objRecBytes: recBytes, fxBankMap: t.fxBankMap || {},
    stage_id: t.stage_id,
  });
};
