// Theme preference. Default is DARK (the brand look); a saved choice of 'light' or 'auto' overrides.
// The actual data-theme attribute is applied by an inline script in app.html BEFORE first paint (no flash);
// this store just persists the choice and re-applies it live when the user flips it on the Settings page.

export type ThemeChoice = 'dark' | 'light' | 'auto';
const KEY = 'metasync_theme';

class ThemeStore {
	choice = $state<ThemeChoice>('dark');

	init(): void {
		if (typeof localStorage === 'undefined') return;
		const saved = localStorage.getItem(KEY);
		this.choice = saved === 'light' || saved === 'auto' ? saved : 'dark';
	}

	set(next: ThemeChoice): void {
		this.choice = next;
		try {
			localStorage.setItem(KEY, next);
		} catch {
			/* ignore */
		}
		this.#apply(next);
	}

	// 'auto' → drop the attribute so prefers-color-scheme decides; otherwise pin dark/light.
	#apply(t: ThemeChoice): void {
		const el = document.documentElement;
		if (t === 'auto') el.removeAttribute('data-theme');
		else el.setAttribute('data-theme', t);
	}
}

export const theme = new ThemeStore();
