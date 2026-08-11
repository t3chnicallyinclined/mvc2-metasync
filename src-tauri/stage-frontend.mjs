// Stage the web/ frontend for bundling, EXCLUDING ROM-derived assets (BYOR: ship no ROM/game data).
// Tauri bundles frontendDist wholesale and ignores .gitignore, so without this step the installer would
// embed 261MB of ROM-derived sprite PNGs (unused at runtime) + the test-atlas. We copy web/ -> src-tauri/frontend
// minus exactly the gitignored ROM assets. Non-destructive: the originals stay in web/ for the local pipeline.
import { cpSync, rmSync, existsSync, mkdirSync } from 'node:fs';
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
