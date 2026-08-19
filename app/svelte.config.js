import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

// Prod is served same-origin under nobd.net/app → set BASE_PATH=/app at build time.
// Dev + a bare build default to root ('') so `npm run dev` / `npm run build` work as-is.
const base = process.env.BASE_PATH ?? '';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		// SPA: single static app-shell, no per-route prerender. adapter-static + fallback
		// serves index.html for every path so client-side routing owns navigation.
		adapter: adapter({
			pages: 'build',
			assets: 'build',
			fallback: 'index.html',
			precompress: false,
			strict: false
		}),
		paths: { base, relative: false },
		// Trailing config kept minimal; SSR is disabled globally in the root +layout.
		alias: {
			$components: 'src/lib/components'
		}
	}
};

export default config;
