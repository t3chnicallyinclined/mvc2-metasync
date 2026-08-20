import { PUBLIC_API_BASE } from '$env/static/public';

// Origin for the live server bus. '' = same-origin (prod at nobd.net/app; dev via Vite proxy).
// Overridable at build time with PUBLIC_API_BASE (e.g. https://nobd.net) — see vite.config.ts.
export const API_BASE: string = PUBLIC_API_BASE || '';

/** PWA build version (surfaced on the Settings/About page). Bump on notable releases. */
export const APP_VERSION = '0.1.0';

/** Build a URL against the skinsync API base. */
export function api(path: string): string {
	return `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;
}
