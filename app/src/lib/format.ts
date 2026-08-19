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

/**
 * Relative "time ago" from an epoch-ms timestamp (e.g. 1787112524875 → "3m", "5h", "2d").
 * Mirrors the old app's lrAgo(): <45s = "just now", then m / h / d. Empty/invalid → ''.
 */
export function timeAgo(ms: number | null | undefined): string {
	const t = Number(ms);
	if (!t || !isFinite(t)) return '';
	const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
	if (s < 45) return 'just now';
	const m = Math.floor(s / 60);
	if (m < 60) return `${m || 1}m`;
	const h = Math.floor(m / 60);
	if (h < 24) return `${h}h`;
	const d = Math.floor(h / 24);
	if (d < 30) return `${d}d`;
	const mo = Math.floor(d / 30);
	if (mo < 12) return `${mo}mo`;
	return `${Math.floor(d / 365)}y`;
}
