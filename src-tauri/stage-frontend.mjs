// Stage the web/ frontend for bundling, EXCLUDING ROM-derived assets (BYOR: ship no ROM/game data).
// Tauri bundles frontendDist wholesale and ignores .gitignore, so without this step the installer would
// embed 261MB of ROM-derived sprite PNGs (unused at runtime) + the test-atlas. We copy web/ -> src-tauri/frontend
// minus exactly the gitignored ROM assets. Non-destructive: the originals stay in web/ for the local pipeline.
import { cpSync, rmSync, existsSync, mkdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const SRC = fileURLToPath(new URL('../web/', import.meta.url));
const DST = fileURLToPath(new URL('./frontend/', import.meta.url));

if (existsSync(DST)) rmSync(DST, { recursive: true, force: true });
mkdirSync(DST, { recursive: true });

let skipped = 0;
cpSync(SRC, DST, {
  recursive: true,
  filter: (src) => {
    const p = src.replace(/\\/g, '/');
    // ROM-derived sprite RENDERS: skins/<Char>/*.png  (skins/characters.json is metadata → KEPT)
    if (/\/skins\/[^/]+\/[^/]+\.(png|webp)$/i.test(p)) { skipped++; return false; }
    // ROM-derived atlas bundles
    if (/\/test-atlas(\/|$)/.test(p)) { skipped++; return false; }
    return true;
  },
});
console.log(`[stage-frontend] web/ -> src-tauri/frontend  (excluded ${skipped} ROM-derived assets: skins/*/*.png + test-atlas)`);

// GUARD (added after the 0.1.71 incident): the Rust build does NOT syntax-check inline HTML JS, so a broken
// string literal can bundle a non-functional app. Parse every inline <script> block of the STAGED index.html
// and FAIL the build (non-zero exit) on any syntax error, so a crash-on-launch build can never ship again.
{
  const html = readFileSync(fileURLToPath(new URL('./frontend/index.html', import.meta.url)), 'utf8');
  const re = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi;
  let m, i = 0, bad = 0;
  while ((m = re.exec(html))) {
    i++;
    try { new Function(m[1]); }
    catch (e) {
      bad++;
      const line = html.slice(0, m.index).split('\n').length;
      console.error(`[stage-frontend] ❌ inline <script> #${i} (~line ${line}) SYNTAX ERROR: ${e.message}`);
    }
  }
  if (bad) { console.error(`[stage-frontend] ❌ ${bad} broken inline script block(s) — REFUSING TO BUILD`); process.exit(1); }
  console.log(`[stage-frontend] ✅ ${i} inline script block(s) parse cleanly`);
}
