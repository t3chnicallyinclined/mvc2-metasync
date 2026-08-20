// PWA install + display-mode state. Captures the Android/Chrome `beforeinstallprompt` so the Settings
// page can offer a real "Install" button; detects iOS (no such event → show the Share→Add-to-Home-Screen
// hint) and whether we're already running standalone (installed). All client-only.

type BIPEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: string }> };

class PwaStore {
	/** The deferred install prompt (Android/Chromium). null until the browser offers it, or after use. */
	installEvent = $state<BIPEvent | null>(null);
	/** Running as an installed app (standalone / home-screen). */
	standalone = $state(false);
	/** iOS/iPadOS Safari — no beforeinstallprompt; install is a manual Share-sheet action. */
	isIOS = $state(false);
	#inited = false;

	/** Attach the window listeners once, from the root layout's onMount. */
	init(): void {
		if (this.#inited || typeof window === 'undefined') return;
		this.#inited = true;
		const nav = navigator as Navigator & { standalone?: boolean };
		this.standalone =
			window.matchMedia?.('(display-mode: standalone)').matches || nav.standalone === true;
		this.isIOS = /iphone|ipad|ipod/i.test(navigator.userAgent) && !(window as unknown as { MSStream?: unknown }).MSStream;

		window.addEventListener('beforeinstallprompt', (e) => {
			e.preventDefault(); // stop Chrome's mini-infobar; we surface our own button
			this.installEvent = e as BIPEvent;
		});
		window.addEventListener('appinstalled', () => {
			this.installEvent = null;
			this.standalone = true;
		});
	}

	/** Fire the native install dialog; clears the event afterward (it's single-use). */
	async promptInstall(): Promise<void> {
		const e = this.installEvent;
		if (!e) return;
		try {
			await e.prompt();
			await e.userChoice;
		} catch {
			/* user dismissed */
		}
		this.installEvent = null;
	}

	/** Can we offer a one-tap install right now? */
	get canInstall(): boolean {
		return !!this.installEvent && !this.standalone;
	}
}

export const pwa = new PwaStore();
