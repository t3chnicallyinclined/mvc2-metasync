#!/usr/bin/env node
// MetaSync version lockstep guard. One version number per release across every artifact — agent, PWA,
// Tauri shell. Run from the metasync-rewrite repo root BEFORE cutting a release (or in CI):
//     node scripts/check-versions.mjs
// Exits 0 when all present artifacts share one version; exits 1 on any drift (and lists the offenders).
// Sibling-worktree artifacts (tray agent, shipped Tauri app) are OPTIONAL — skipped if their worktree
// isn't checked out here, so the guard never fails just because a sibling repo is absent.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');

// [label, path-relative-to-repo-root, capture-regex, required?, frozen?]
// `frozen` = an artifact intentionally left behind on an OLD version (the retiring Tauri app is frozen at
// 0.2.6 until the 0.3.0 tray cutover retires it). Frozen rows are printed for visibility but excluded from
// the drift check, so the guard stays green on the ACTIVE release line and still catches accidental drift.
const targets = [
  ['PWA config.ts',     'app/src/lib/config.ts',                        /APP_VERSION\s*=\s*'([\d.]+)'/,   true,  false],
  ['PWA package.json',  'app/package.json',                             /"version":\s*"([\d.]+)"/,        true,  false],
  ['Tauri shell conf',  'src-tauri/tauri.conf.json',                    /"version":\s*"([\d.]+)"/,        true,  false],
  ['Tauri shell Cargo', 'src-tauri/Cargo.toml',                         /^version\s*=\s*"([\d.]+)"/m,     true,  false],
  ['Tray agent',        '../mvc-live-skins-tray/tray-agent/Cargo.toml', /^version\s*=\s*"([\d.]+)"/m,     false, false],
  // FROZEN at 0.2.6 — the retiring desktop app; the tray + PWA are the forward clients (see 0.3.0 cutover).
  ['Shipped Tauri app', '../mvc-live-skins/src-tauri/tauri.conf.json',  /"version":\s*"([\d.]+)"/,        false, true],
];

const rows = [];
let hardMissing = false;
for (const [label, rel, re, required, frozen] of targets) {
  let txt;
  try {
    txt = readFileSync(resolve(root, rel), 'utf8');
  } catch {
    if (required) { rows.push([label, 'MISSING', rel, frozen]); hardMissing = true; }
    continue; // optional sibling not present → skip silently
  }
  const m = txt.match(re);
  if (!m) { rows.push([label, 'UNPARSED', rel, frozen]); if (required) hardMissing = true; continue; }
  rows.push([label, m[1], rel, frozen]);
}

// Alignment is judged over the ACTIVE (non-frozen) artifacts only.
const versions = new Set(
  rows.filter((r) => !r[3]).map((r) => r[1]).filter((v) => /^\d+\.\d+\.\d+/.test(v))
);
const aligned = versions.size === 1 && !hardMissing;
const target = versions.size === 1 ? [...versions][0] : null;

console.log('\nMetaSync version alignment:');
for (const [label, ver, rel, frozen] of rows) {
  const ok = frozen || (target !== null && ver === target);
  const mark = frozen ? '❄' : ok ? '✓' : '✗';
  const suffix = frozen ? '  (frozen)' : '';
  console.log(`  ${mark} ${label.padEnd(18)} ${String(ver).padEnd(9)} ${rel}${suffix}`);
}
console.log('');
if (aligned) {
  console.log(`✅ active artifacts aligned at ${target}\n`);
  process.exit(0);
}
console.log(`❌ VERSION DRIFT: ${[...versions].join(' vs ')}${hardMissing ? ' (+ missing/unparsed)' : ''} — bump all ACTIVE artifacts to one version before releasing.\n`);
process.exit(1);
