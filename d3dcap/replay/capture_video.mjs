// capture_video.mjs -- drive the WebGPU sequence player in headless Chrome (real GPU) and pipe every
// frame into ffmpeg -> one .mp4 per .seq chunk. Nothing is re-rendered here: the player draws Steam's
// own draw calls exactly as in the browser; this only captures the canvas.
//
//   node capture_video.mjs fullmatch/c00.seq fullmatch/c00.mp4 [--fps 60] [--crf 20]
//
// Needs: serve.py running on :8099 (python serve.py), Chrome installed, ffmpeg on PATH, puppeteer-core
// from maplecast-flycast/tools/render-replica-poc/node_modules.
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';
import path from 'node:path';
const require = createRequire('file:///C:/Users/trist/projects/maplecast-flycast/tools/render-replica-poc/node_modules/');
const puppeteer = require('puppeteer-core');

const [seqRel, outMp4] = process.argv.slice(2);
if (!seqRel || !outMp4) { console.error('usage: node capture_video.mjs <seq relative to replay dir> <out.mp4> [--fps 60] [--crf 20]'); process.exit(2); }
const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d; };
const FPS = +arg('--fps', 60), CRF = +arg('--crf', 20);
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const URL = `http://localhost:8099/player.html?seq=${encodeURIComponent(seqRel)}&auto=1`;

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: 'new',
  args: ['--enable-unsafe-webgpu', '--enable-features=Vulkan,WebGPU', '--ignore-gpu-blocklist', '--use-gl=angle', '--use-angle=d3d11',
         '--no-sandbox', '--window-size=700,700', '--disable-background-timer-throttling'],
});
const page = await browser.newPage();
await page.setViewport({ width: 700, height: 700, deviceScaleFactor: 1 });
page.on('console', (m) => { const t = m.text(); if (/error|GPU/i.test(t)) console.error('[page]', t); });
await page.goto(URL, { waitUntil: 'load' });
// the page's own Load flow (auto=1 clicks it); wait until the player reports ready
await page.waitForFunction(() => window.__rr && window.__rr.ready === true, { timeout: 600000, polling: 250 });
const count = await page.evaluate(() => window.__rr.count);
const first = await page.evaluate(() => window.__rr.first);
console.error(`[capture] ${seqRel}: ${count} frames (first ${first}) -> ${outMp4} @ ${FPS} fps crf ${CRF}`);

const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', String(FPS), '-vcodec', 'png', '-i', '-',
                            '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', String(CRF), '-preset', 'medium', '-movflags', '+faststart', outMp4],
                { stdio: ['pipe', 'inherit', 'inherit'] });
// the canvas is 640x480 logical but CSS-scaled in the page (670x503 screenshot -> odd height, h264 refuses):
// pin its CSS size to the logical size so every screenshot is exactly 640x480
await page.addStyleTag({ content: '#cv{width:640px!important;height:480px!important}' });
const cv = await page.$('#cv');
const t0 = Date.now();
for (let i = 0; i < count; i++) {
  await page.evaluate((k) => window.__rr.show(k), i);
  const png = await cv.screenshot({ type: 'png', omitBackground: false });
  if (!ff.stdin.write(png)) await new Promise((r) => ff.stdin.once('drain', r));
  if (i % 300 === 0) console.error(`[capture] ${i}/${count}  ${((Date.now() - t0) / 1000).toFixed(0)} s`);
}
ff.stdin.end();
await new Promise((r) => ff.on('close', r));
await browser.close();
console.error(`[capture] done ${outMp4} in ${((Date.now() - t0) / 1000).toFixed(0)} s`);
