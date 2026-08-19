// The five arena tabs. Only Ranks is functional this phase; the rest are stub routes ("coming soon").
export interface NavItem {
	id: string;
	label: string;
	href: string;
	/** stroke-SVG path(s) on a 24×24 viewBox, drawn on currentColor. */
	d: string;
	live: boolean;
}

export const NAV: NavItem[] = [
	{
		id: 'match',
		label: 'Match',
		href: '/match',
		d: 'M4 20 L17 7 M17 7 h-3.6 M17 7 v3.6 M20 20 L7 7 M7 7 h3.6 M7 7 v3.6',
		live: false
	},
	{ id: 'ranks', label: 'Ranks', href: '/ranks', d: 'M5 21 V10 M12 21 V4 M19 21 V14', live: true },
	{
		id: 'tournament',
		label: 'Tournament',
		href: '/tournament',
		d: 'M6 3 v18 M6 4 h12 l-3 4 l3 4 H6',
		live: false
	},
	{
		id: 'regions',
		label: 'Regions',
		href: '/regions',
		d: 'M12 3 a9 9 0 1 0 0.001 0 M3 12 h18 M12 3 c-4 4 -4 14 0 18 c4 -4 4 -14 0 -18',
		live: false
	},
	{
		id: 'library',
		label: 'Library',
		href: '/library',
		d: 'M5 4 h6 v16 h-6 z M13 4 h6 v16 h-6 z',
		live: false
	}
];
