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

// [label, path-relative-to-repo-root, capture-regex, required?]
const targets = [
  ['PWA config.ts',     'app/src/lib/config.ts',                        /APP_VERSION\s*=\s*'([\d.]+)'/,   true],
  ['PWA package.json',  'app/package.json',                             /"version":\s*"([\d.]+)"/,        true],
  ['Tauri shell conf',  'src-tauri/tauri.conf.json',                    /"version":\s*"([\d.]+)"/,        true],
  ['Tauri shell Cargo', 'src-tauri/Cargo.toml',                         /^version\s*=\s*"([\d.]+)"/m,     true],
  ['Tray agent',        '../mvc-live-skins-tray/tray-agent/Cargo.toml', /^version\s*=\s*"([\d.]+)"/m,     false],
  ['Shipped Tauri app', '../mvc-live-skins/src-tauri/tauri.conf.json',  /"version":\s*"([\d.]+)"/,        false],
];

const rows = [];
let hardMissing = false;
for (const [label, rel, re, required] of targets) {
  let txt;
  try {
    txt = readFileSync(resolve(root, rel), 'utf8');
  } catch {
    if (required) { rows.push([label, 'MISSING', rel]); hardMissing = true; }
    continue; // optional sibling not present → skip silently
  }
  const m = txt.match(re);
  if (!m) { rows.push([label, 'UNPARSED', rel]); if (required) hardMissing = true; continue; }
  rows.push([label, m[1], rel]);
}

const versions = new Set(rows.map((r) => r[1]).filter((v) => /^\d+\.\d+\.\d+/.test(v)));
const aligned = versions.size === 1 && !hardMissing;
const target = versions.size === 1 ? [...versions][0] : null;

console.log('\nMetaSync version alignment:');
for (const [label, ver, rel] of rows) {
  const ok = target !== null && ver === target;
  console.log(`  ${ok ? '✓' : '✗'} ${label.padEnd(18)} ${String(ver).padEnd(9)} ${rel}`);
}
console.log('');
if (aligned) {
  console.log(`✅ all aligned at ${target}\n`);
  process.exit(0);
}
console.log(`❌ VERSION DRIFT: ${[...versions].join(' vs ')}${hardMissing ? ' (+ missing/unparsed)' : ''} — bump all to one version before releasing.\n`);
process.exit(1);
