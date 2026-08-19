import { api } from '$lib/config';
import type { Profile } from './profile.svelte';

// Auth store — "Sign in through Steam" for the PWA. The server already runs the hardened OpenID 2.0 flow
// (skinsync openid.rs): GET /skinsync/auth/steam/login → Steam → /auth/steam/return mints the SAME
// SteamID-bound bearer token the desktop app uses, and 302s back to SKINSYNC_OPENID_SUCCESS (= /app/auth)
// with `#token=…&steamid=…` in the URL FRAGMENT. We capture that on the /auth route, persist it, and use
// the token as `Authorization: Bearer` for owner-scoped calls (profile private view now; skin control later).
//
// Storage: localStorage (standard SPA bearer pattern; Svelte auto-escapes so no injection sink). The token
// is a credential — we clear the fragment immediately (history.replaceState) so it never lingers in the URL,
// browser history, or a Referer header.

const TOKEN_KEY = 'metasync_token';
const SID_KEY = 'metasync_steamid';
const RETURN_KEY = 'metasync_return';

class AuthStore {
	token = $state<string | null>(null);
	steamid = $state<string | null>(null);
	me = $state<Profile | null>(null);
	ready = $state(false);
	authed = $derived(!!this.token && !!this.steamid);

	constructor() {
		// Client-only app (ssr=false) → the constructor runs in the browser; still guard for safety.
		if (typeof localStorage === 'undefined') return;
		try {
			this.token = localStorage.getItem(TOKEN_KEY);
			this.steamid = localStorage.getItem(SID_KEY);
		} catch {
			/* storage blocked (private mode) — stay signed out */
		}
		this.ready = true;
		if (this.token && this.steamid) void this.loadMe();
	}

	/** Bearer headers for owner-scoped fetches (empty when signed out). */
	headers(): Record<string, string> {
		return this.token ? { authorization: `Bearer ${this.token}` } : {};
	}

	/** Begin sign-in: remember where the user was, then hand off to the server's Steam redirect. */
	login(returnTo?: string): void {
		try {
			const here = returnTo ?? location.pathname + location.search;
			sessionStorage.setItem(RETURN_KEY, here);
		} catch {
			/* ignore */
		}
		window.location.href = api('/skinsync/auth/steam/login');
	}

	/**
	 * Consume the `#token=…&steamid=…` fragment on the /auth callback. Persists the session, strips the
	 * fragment from the URL, kicks off a profile load, and returns the client path to redirect to (or ''
	 * when the fragment carried no token — e.g. a direct visit or a cancelled login).
	 */
	captureFragment(): string {
		const raw = location.hash.startsWith('#') ? location.hash.slice(1) : location.hash;
		const p = new URLSearchParams(raw);
		const token = p.get('token');
		const steamid = p.get('steamid');
		const ok = !!token && !!steamid && /^\d{17}$/.test(steamid);
		if (ok) {
			this.token = token;
			this.steamid = steamid;
			try {
				localStorage.setItem(TOKEN_KEY, token!);
				localStorage.setItem(SID_KEY, steamid!);
			} catch {
				/* ignore */
			}
			void this.loadMe();
		}
		// scrub the credential from the URL/history immediately, regardless of outcome
		try {
			history.replaceState(null, '', location.pathname + location.search);
		} catch {
			/* ignore */
		}
		let ret = '/ranks';
		try {
			ret = sessionStorage.getItem(RETURN_KEY) || '/ranks';
			sessionStorage.removeItem(RETURN_KEY);
		} catch {
			/* ignore */
		}
		// never bounce back into /auth itself
		if (ret.startsWith('/auth')) ret = '/ranks';
		return ok ? ret : '';
	}

	logout(): void {
		this.token = null;
		this.steamid = null;
		this.me = null;
		try {
			localStorage.removeItem(TOKEN_KEY);
			localStorage.removeItem(SID_KEY);
		} catch {
			/* ignore */
		}
	}

	/** Load the signed-in user's own profile (bearer unlocks the owner-only view server-side). */
	async loadMe(): Promise<void> {
		if (!this.steamid) return;
		try {
			const res = await fetch(api(`/skinsync/profile?steamid=${encodeURIComponent(this.steamid)}`), {
				headers: { accept: 'application/json', ...this.headers() }
			});
			if (!res.ok) {
				if (res.status === 401) this.logout(); // token rejected → drop the dead session
				return;
			}
			this.me = (await res.json()) as Profile;
		} catch {
			/* keep last-good me on a transient blip */
		}
	}
}

export const auth = new AuthStore();
