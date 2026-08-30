# PATCH — sprite-gpu.mjs: real TR-alpha (translucent) pipeline + per-instance alpha

**Target:** `maplecast-flycast/web/webgpu/sprite-gpu.mjs`
**Why:** OWNED-RENDER-BUILD-SPEC §5 "Compositing gap". sprite-gpu today draws every non-additive
body through `pipe`/`lutPipe` = **opaque + punch-through discard**. That is pixel-correct for
binary-alpha sprites but draws see-through bodies (translucent supers, hit-flash ghosts, afterimage
trails, drop shadows) **solid**. This adds a real translucent-alpha pipeline
`{src-alpha, one-minus-src-alpha}` + a per-instance alpha, and routes any sprite flagged `s.tr`
through it. `sparkPipe` (ONE/ONE) and `pipeAdd`/`lutPipeAdd` (src-alpha/ONE) are unchanged, so the
three blend classes (opaque · translucent · additive) are all distinct and routed by class.

**Backward-compat:** no existing caller sets `s.tr`/`s.trAlpha`, and the new instance lane defaults
to `1.0`, so the RGB/LUT/spark output is **byte-identical** until a caller opts in. Cite by function
name (line numbers drift). Anchors are the exact current text.

**NOT compile-tested here** (this session is worktree-isolated to `mvc-live-skins-quarters` and has no
WebGPU). Apply, bump the `?v=` in every importer (`replay.html`, `webgpu-test.html`, `king.html`,
`gpu.html`), then verify in the DIFF differ that a normal frame is unchanged and a `tr`-flagged quad
is see-through.

---

## 1. SHADER (RGB) — carry per-instance alpha, multiply into output

In `const SHADER`, add a flat `trA` to `VSOut`, take it as `@location(6)`, and multiply it into the
fragment alpha.

`struct VSOut` — add the field:
```wgsl
struct VSOut { @builtin(position) pos: vec4f, @location(0) uv: vec2f, @location(1) @interpolate(flat) palBase: u32, @location(2) @interpolate(flat) tint: vec3f, @location(3) @interpolate(flat) trA: f32 };
```
`fn vs(...)` signature — add the input and set the output (before `return o;`):
```wgsl
      @location(5) flipY: f32,
      @location(6) trA: f32) -> VSOut {
```
```wgsl
  var o: VSOut; o.pos = vec4f(clip, 0., 1.); o.uv = uv; o.palBase = u32(palBase + 0.5); o.tint = tint; o.trA = trA; return o;
```
`fn fs(...)` — final return:
```wgsl
  return vec4f(rgb, col.a * i.trA);
```

## 2. LUT_SHADER — same

`struct VSOut` (the LUT one) — add `@location(3) @interpolate(flat) trA: f32`.
`fn vs_lut(...)` — add `@location(6) trA: f32` param and `o.trA = trA;` before `return o;`.
`fn fs_lut(...)` — final return:
```wgsl
  return vec4f(rgb, col.a * i.trA);   // was: vec4f(rgb, 1.0)
```
(`col.a` is 1.0 after the two discards, so this equals `trA` — identical when trA=1.)

## 3. Instance stride: 14 → 15 floats

```js
const INST_FLOATS = 15;       // dest(4)+auv(4)+flip(1)+palBase(1)+tint(3)+flipY(1)+trA(1)
```
`INST_STRIDE = INST_FLOATS * 4` follows automatically. (`instData`/`idxInstData`/`inst`/`idxInst`
sizes all derive from `INST_FLOATS`/`INST_STRIDE`, so they resize with no other edit.)

## 4. Add attribute (location 6) to EVERY INST_STRIDE vertex layout

Append to the `attributes:[…]` array of **`this.pipe`**, **`this.pipeAdd`**, and the shared
**`lutVbuf`** (used by `lutPipe`/`lutPipeAdd`), and to the two new TR pipelines below:
```js
            { shaderLocation: 6, offset: 56, format: 'float32' },
```
(Do NOT touch `sparkPipe` — it keeps its own 3-attr, stride-36 layout.)

## 5. New pipelines — pipeTR (RGB) and lutPipeTR (LUT), src-alpha / inv-src-alpha

Right after `this.pipeAdd = …` create:
```js
      // TRANSLUCENT (see-through) variant — real alpha blend for non-additive bodies whose
      // TSP requests dst=inv-src-alpha (supers, hit-flash ghosts, afterimages, drop shadows).
      // Per-instance trA drives the transparency; punch-through discard still clips idx0.
      this.pipeTR = device.createRenderPipeline({
        layout: device.createPipelineLayout({ bindGroupLayouts: [this.bgl] }),
        vertex: { module: mod, entryPoint: 'vs', buffers: [{
          arrayStride: INST_STRIDE, stepMode: 'instance', attributes: [
            { shaderLocation: 0, offset: 0,  format: 'float32x4' },
            { shaderLocation: 1, offset: 16, format: 'float32x4' },
            { shaderLocation: 2, offset: 32, format: 'float32' },
            { shaderLocation: 3, offset: 36, format: 'float32' },
            { shaderLocation: 4, offset: 40, format: 'float32x3' },
            { shaderLocation: 5, offset: 52, format: 'float32' },
            { shaderLocation: 6, offset: 56, format: 'float32' },
          ]}]},
        fragment: { module: mod, entryPoint: 'fs', targets: [{ format: this.fmt,
          blend: { color: { srcFactor: 'src-alpha', dstFactor: 'one-minus-src-alpha', operation: 'add' },
                   alpha: { srcFactor: 'one',       dstFactor: 'one-minus-src-alpha', operation: 'add' } } }] },
        primitive: { topology: 'triangle-list' },
      });
```
And after `this.lutPipeAdd = …`:
```js
      this.lutPipeTR = device.createRenderPipeline({
        layout: device.createPipelineLayout({ bindGroupLayouts: [this.lutBgl] }),
        vertex: { module: lutMod, entryPoint: 'vs_lut', buffers: [lutVbuf] },
        fragment: { module: lutMod, entryPoint: 'fs_lut', targets: [{ format: this.fmt,
          blend: { color: { srcFactor: 'src-alpha', dstFactor: 'one-minus-src-alpha', operation: 'add' },
                   alpha: { srcFactor: 'one',       dstFactor: 'one-minus-src-alpha', operation: 'add' } } }] },
        primitive: { topology: 'triangle-list' },
      });
```
(Remember to add the `{shaderLocation:6,offset:56}` line to `lutVbuf` per §4 so both LUT pipelines see it.)

## 6. render(): 3-bucket ordering (normal → TR → additive) + write trA

Replace the RGB group build (the `isAdd`/`ordered`/`normCount` block inside
`for (const [cid, list] of byChar)`). A sprite is **TR** when `s.tr === true`
(or `s.trAlpha != null && s.trAlpha < 1`); **ADD** when the fx blend byte requests dst=ONE.
```js
      const first = n;
      const isAdd = (s) => s.blend != null && (s.blend & 0xf) === 1;
      const isTR  = (s) => !isAdd(s) && (s.tr === true || (s.trAlpha != null && s.trAlpha < 1));
      const rank  = (s) => isAdd(s) ? 2 : (isTR(s) ? 1 : 0);          // normal < TR < additive
      const ordered = list.slice().sort((a, b) => rank(a) - rank(b));
      let normCount = 0, trCount = 0;
      for (const s of ordered) {
        if (n >= this.maxInst) break;
        const c = this.chars[cid], o = n * INST_FLOATS;
        this.instData[o] = s.dx; this.instData[o + 1] = s.dy; this.instData[o + 2] = s.dw; this.instData[o + 3] = s.dh;
        this.instData[o + 4] = s.sx / c.w; this.instData[o + 5] = s.sy / c.h;
        this.instData[o + 6] = (s.sx + s.sw) / c.w; this.instData[o + 7] = (s.sy + s.sh) / c.h;
        this.instData[o + 8] = s.flip ? 1 : 0; this.instData[o + 9] = palBase;
        const t = s.tint;
        this.instData[o + 10] = t ? t[0] : 0; this.instData[o + 11] = t ? t[1] : 0; this.instData[o + 12] = t ? t[2] : 0;
        this.instData[o + 13] = s.flipY ? 1 : 0;
        this.instData[o + 14] = (s.trAlpha != null ? s.trAlpha : 1);   // per-instance alpha (1 = opaque)
        if (rank(s) === 0) normCount++; else if (rank(s) === 1) trCount++;
        n++;
      }
      groups.push({ cid, first, count: n - first, normCount, trCount }); gi++;
```
Do the **identical** change in the `byCharIdx` (LUT) loop: same `isAdd/isTR/rank/ordered`, write
`this.idxInstData[o + 14] = (s.trAlpha != null ? s.trAlpha : 1)`, and push
`idxGroups.push({ cid, first, count: ni - first, normCount, trCount })`.

## 7. render(): draw the TR bucket between normal and additive

In the encoder, for **both** the RGB (`if (n) { … }`) and LUT (`if (ni) { … }`) sections, add a TR
pass between the normal draw and the additive draw. RGB example:
```js
      // normal (opaque) — unchanged: pass.setPipeline(this.pipe); draw g.first .. +normCount
      // TRANSLUCENT pass (real alpha) — the g.trCount instances after the normal ones.
      let anyTR = false;
      for (const g of groups) if ((g.trCount | 0) > 0) { anyTR = true; break; }
      if (anyTR) {
        pass.setPipeline(this.pipeTR);
        for (const g of groups) {
          const tc = g.trCount | 0; if (!tc) continue;
          pass.setBindGroup(0, this.chars[g.cid].bg);
          pass.draw(6, tc, 0, g.first + (g.normCount | 0));
        }
      }
      // additive — SAME as today but its firstInstance base moves past the TR block:
      //   addCount = g.count - g.normCount - g.trCount ; base = g.first + g.normCount + g.trCount
```
Update the existing additive loop's `addCount`/base to subtract `trCount` as noted (RGB uses
`this.pipeAdd`, LUT uses `this.lutPipeAdd`; the TR LUT pass uses `this.lutPipeTR`).

---

## Caller hook (adapter / buildDrawList)

A body becomes translucent by setting `item.tr = true` and `item.trAlpha = <0..1>` on its draw-list
item. Natural drivers from the tape: a super-flash / afterimage state, or a drop-shadow quad. In
`tape-adapter.mjs` this is where a future `glow`/`flash`-driven ghost would light up; it is left
unset today so bodies stay opaque (matching the proof render).
