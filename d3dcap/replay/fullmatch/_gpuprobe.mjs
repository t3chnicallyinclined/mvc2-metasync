import { createRequire } from 'node:module';
const require = createRequire('file:///C:/Users/trist/projects/maplecast-flycast/tools/render-replica-poc/node_modules/');
const puppeteer = require('puppeteer-core');
const b = await puppeteer.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: 'new',
  args: ['--enable-unsafe-webgpu', '--enable-features=Vulkan,WebGPU', '--ignore-gpu-blocklist', '--use-gl=angle', '--use-angle=d3d11', '--no-sandbox'] });
const p = await b.newPage();
p.on('console', m => console.log('[console]', m.text().slice(0, 200)));
await p.goto('http://localhost:8099/player.html?seq=fullmatch/c01.seq&auto=1', { waitUntil: 'load' });
for (let i = 0; i < 12; i++) {
  await new Promise(r => setTimeout(r, 5000));
  const s = await p.evaluate(async () => ({ gpu: !!navigator.gpu, adapter: navigator.gpu ? !!(await navigator.gpu.requestAdapter()) : null,
     rr: window.__rr && window.__rr.ready, readout: document.getElementById('readout')?.textContent, log: document.getElementById('log')?.textContent.slice(-300) }));
  console.log(i*5+5, 's', JSON.stringify(s));
  if (s.rr) break;
}
await b.close();
