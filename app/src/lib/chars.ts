// MvC2 char-id → name map. Ported from web/skins/characters.json (the roster the live server keys
// match-report team arrays by: my_team/opp_team = numeric char_id triples). Embedded as a static
// module so the profile can render tiny team glyphs with no runtime fetch (matches the old app's
// `nameById`). Unknown ids fall back to `#id` — never blocks the row.

export const CHAR_NAME: Record<number, string> = {
	0: 'Ryu',
	1: 'Zangief',
	2: 'Guile',
	3: 'Morrigan',
	4: 'Anakaris',
	5: 'Strider',
	6: 'Cyclops',
	7: 'Wolverine',
	8: 'Psylocke',
	9: 'Iceman',
	10: 'Rogue',
	11: 'Captain America',
	12: 'Spider-Man',
	13: 'Hulk',
	14: 'Venom',
	15: 'Doctor Doom',
	16: 'Tron Bonne',
	17: 'Jill',
	18: 'Hayato',
	19: 'Ruby Heart',
	20: 'SonSon',
	21: 'Amingo',
	22: 'Marrow',
	23: 'Cable',
	27: 'Chun-Li',
	28: 'Mega Man',
	29: 'Roll',
	30: 'Akuma',
	31: 'BB Hood',
	32: 'Felicia',
	33: 'Charlie Nash',
	34: 'Sakura',
	35: 'Dan',
	36: 'Cammy',
	37: 'Dhalsim',
	38: 'M Bison',
	39: 'Ken',
	40: 'Gambit',
	41: 'Juggernaut',
	42: 'Storm',
	43: 'Sabretooth',
	44: 'Magneto',
	45: 'Shuma-Gorath',
	46: 'War Machine',
	47: 'Silver Samurai',
	48: 'Omega Red',
	49: 'Spiral',
	50: 'Colossus',
	51: 'Iron Man',
	52: 'Sentinel',
	53: 'Blackheart',
	54: 'Thanos',
	55: 'Jin',
	56: 'Captain Commando',
	57: 'Wolverine Bone Claw',
	58: 'Servbot'
};

/** Full character name for a char id (or `#id` when unknown). */
export function charName(id: number): string {
	return CHAR_NAME[id] ?? `#${id}`;
}

/** Compact 3-letter glyph for a char id (e.g. 44 → "MAG"), for dense team strips. */
export function charAbbr(id: number): string {
	const n = CHAR_NAME[id];
	if (!n) return `#${id}`;
	return n.replace(/[^A-Za-z0-9]/g, '').slice(0, 3).toUpperCase();
}

/** A team array → "MAG / STO / SEN" (abbreviated). Empty/invalid → ''. */
export function teamAbbr(team: number[] | undefined | null): string {
	if (!Array.isArray(team) || !team.length) return '';
	return team.map(charAbbr).join(' / ');
}
