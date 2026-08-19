// ISO alpha-2 country code → flag emoji (regional-indicator pair). Mirrors flagEmoji() in index.html.
export function flagEmoji(cc?: string): string {
	if (!cc || cc.length !== 2) return '🏳️';
	try {
		return String.fromCodePoint(
			...[...cc.toUpperCase()].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65)
		);
	} catch {
		return '🏳️';
	}
}

/** Compact integer formatting for tabular stats. */
export function fmtNum(n: number | null | undefined): string {
	return String(n ?? 0);
}
