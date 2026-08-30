# PATCH — sprite-client.mjs: faithful sprite-class effect draw (own-origin, obj-scale, additive)

**Target:** `maplecast-flycast/web/webgpu/sprite-client.mjs`, function **`buildEmitterDrawList`**, the
pool-object loop `if (!force && this.objectsOn !== false && satMode !== 'off') for (const o of (this.objects || []))`.
**Why:** OWNED-RENDER §"0.3.29 CAPTURE DELTA". Sprite-class effects (cat 1-4) render through the SAME
`(GFX2, sel=sid)` part-assembly as a body, but anchored at their **OWN origin** (`obj sx/sy`), at their
**own scale** (`zx_q/4096`), **additive**. The current pool loop mis-handles them three ways:
1. the `far` proximity heuristic (`|o.x-ox|+|o.y-oy| > 130`) draws a *close* effect at the OWNER's foot,
   not its own origin — wrong for a spark/aura next to the caster;
2. it applies the OWNER's scale (`osl.scaleX`), ignoring the effect's own `objScale`;
3. it requires an ACTIVE owner body of the same cid, so a `fxBankMap`-resolved shared-bank effect
   (super-flash whose atlas ≠ the caster's) is skipped.

The tape-adapter already ships each effect with `{ isEffect:0, blend:0x1, additive:true, objScale,
gfx1, owner }` and the resolved `cid`. This patch consumes those fields.

**Resolution CLOSED on the real 0.3.29 tape (48,452 effect nodes):** the atlas is the **OWNER's char**
— every effect's masked sel resolves in the caster's assembly (cat1 39841/39841, cat3 4152/4152,
cat4 1613/1613 = 100%), and it renders as the right sprite (verified: a Magneto super's shards are
PL2C cells 21/25 drawn additive at their own-origins). `gfx2` (H+0x1A4) is ALWAYS 0 (dead), so the
resolver keys on `gfx1` (H+0x1A0) ONLY for the 5.9% ownerless super-flash nodes (a `fxBankMap`
`gfx1 -> char_id`). This patch is atlas-agnostic; it just draws the adapter-resolved `o.cid`.

**Backward-compat:** the new branch fires ONLY for `o.additive === true` (a field no existing wire sets).
Every non-additive satellite keeps the exact current path. **Not compile-tested here** (worktree-isolated,
no WebGPU) — apply, bump `?v=`, verify in the DIFF differ against a live super/projectile frame.

---

## The change

Insert at the TOP of the pool-object loop body, immediately after
`for (const o of (this.objects || [])) {` and BEFORE the existing `if (o.isEffect) { … }`:

```js
      // SPRITE-CLASS EFFECT (0.3.29, cat 1-4) — own-origin, own-scale, additive part-assembly.
      // The adapter resolved the atlas cid (gfx2 bankMap -> owner fallback) and set additive.
      // Own origin (o.x/o.y) ALWAYS (no `far` heuristic); the effect's OWN scale (o.objScale =
      // zx_q/4096, /CPS to recover the magnifier); facing from the owner slot (side); blend 0x1
      // -> sprite-gpu isAdd -> pipeAdd (src-alpha/ONE). No active-owner gate: a shared-bank
      // effect (super-flash) whose atlas isn't a live body still draws once its atlas is loaded.
      if (o.additive) {
        const ec = this.asmChars[o.cid];
        if (!ec) { this.loadAsmChar(o.cid); skipSel++; continue; }
        if (!ec.img) { skipSel++; continue; }
        const erecs = ec.asm && (ec.asm[o.sid] || ec.asm[o.sid & 0xffff] || ec.asm[String(o.sid)]);
        if (!erecs || !erecs.length) { skipSel++; continue; }   // sel not in this bank's assembly
        if (o.x < -64 || o.x > 704 || o.y < -64 || o.y > 544) continue;
        // owner slot (side/facing) — optional; ownerless super-flash uses the obj's own face.
        let efac = o.xflip ? 1 : 0;
        if (o.owner != null && o.owner < 6 && this.slot[o.owner]) efac = this.slot[o.owner].facing;
        const eScl = (o.objScale && o.objScale > 0.02) ? (o.objScale / (this.asmScaleX || 1)) : 1;
        // zBase from the draw layer keeps effects in slot-table order (§4, no re-sort). engZ
        // absent on the tape -> layer/zBase path. type carries the obj layer (adapter).
        emitAssembly({ cid: o.cid, exx: o.x, eyy: o.y, facing: efac, slot: 0,
                       zBase: (o.type != null ? o.type : 6),
                       sclX: eScl, sclY: eScl, pal12d: 0, pal12e: 0,
                       blend: 0x1, fx: false }, o.sid);
        continue;
      }
```

(The adapter sends sprite-class effects with `isEffect:0`, so they would otherwise fall into the
non-effect satellite path below; this branch intercepts them first via `o.additive`.)

## Notes
- **Blend:** `blend:0x1` routes to `pipeAdd` (src-alpha/ONE) — the correct alpha-weighted-add for
  auras/supers/projectiles. Pure-add (ONE/ONE) hit-sparks are 3D-class (cat 5-13), OUT OF SCOPE this
  release. Effects do **NOT** need the TR-alpha patch (that is for *translucent non-additive* bodies).
- **Layer order:** `zBase = o.type (=obj layer)` feeds the same `useLayer` group sort the bodies use;
  effects interleave with bodies by the engine's authored layer, no client re-sort (§4).
- **Anchor:** pure `o.x/o.y` (own origin) — the own-origin rule (marvelous2 `loc_8c030af8` writes the
  satellite's own `+0xE0/+0xE4`), NOT the caster's foot.
