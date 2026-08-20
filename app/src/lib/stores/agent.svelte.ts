import { api } from '$lib/config';
import { auth } from '$lib/stores/auth.svelte';

// Desktop-agent status store — the signed-in user's OWN tray/Tauri agent (GET /skinsync/agent, token-auth →
// you only ever see your own). One cheap authed GET, keep last-good on a blip. This is the single home of the
// agent figures: the top-bar AgentChip owns the load lifecycle app-wide (mirrors WalletChip) and the Settings
// "Desktop companion" card reads the same fields. `ver` is empty until the agent first reports on heartbeat.
// Types are local (types.ts is off-limits) and mirror the live handler (metasync-srv/skinsync/src/routes.rs).

export interface AgentStatus {
	ver?: string;
	platform?: string; // windows | linux
	client?: string; // tray | tauri
	last_seen?: number;
}

export class AgentStore {
	/** null = not yet loaded; an object (with `ver` possibly empty = "not detected") once fetched. */
	status = $state<AgentStatus | null>(null);

	#sid = '';
	#reqId = 0;

	/** True once an agent has actually reported a build — drives the chip's visibility. */
	get reporting(): boolean {
		return !!this.status?.ver;
	}

	/** Load (or refresh) the agent status for the signed-in user. A user switch / sign-out clears it. */
	async load(steamid: string | null | undefined): Promise<void> {
		const sid = String(steamid || '');
		if (sid !== this.#sid) {
			// switched user (or signed out) → drop the previous status so one account's agent never shows
			// under another's identity.
			this.#sid = sid;
			this.status = null;
		}
		if (!sid || !auth.token) return;
		const myReq = ++this.#reqId;
		try {
			const res = await fetch(api('/skinsync/agent'), {
				headers: { accept: 'application/json', ...auth.headers() }
			});
			if (!res.ok) return; // keep last-good (a 401 is handled app-wide by the auth store)
			const j = (await res.json()) as AgentStatus & { ok?: boolean };
			if (myReq !== this.#reqId) return; // superseded
			this.status = j;
		} catch {
			/* keep last-good on a transient blip */
		}
	}
}

export const agent = new AgentStore();
