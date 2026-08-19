/**
 * The region taxonomy, mirroring backend/apps/catalog/regions.py — keep the
 * two in sync. The catalog API applies the same widening server-side for
 * Browse; this exists because the Downloads page filters its queue store
 * client-side and has to behave identically.
 */

/**
 * Country regions that are also part of Europe/PAL. Picking one of these has
 * to include plain 'eu' too: a pan-European release is the same disc a German
 * user wants, it just isn't labelled Germany.
 */
export const REGION_PARENTS: Record<string, string> = {
	de: 'eu',
	fr: 'eu',
	au: 'eu',
	uk: 'eu'
};

export const REGION_CHILDREN: Record<string, string[]> = Object.entries(REGION_PARENTS).reduce(
	(acc, [child, parent]) => {
		(acc[parent] ??= []).push(child);
		return acc;
	},
	{} as Record<string, string[]>
);

/** A 'World' release carries no region lockout, so it belongs in the results
 * for every *real* region — but not for 'other', which means "none of the ones
 * we model" and would stop meaning anything if World landed in it. */
const WORLD_REGION = 'world';
const NO_WORLD = new Set(['other', WORLD_REGION]);

/** Display order, so an entry's flags always read the same way. */
export const REGION_ORDER = ['world', 'us', 'eu', 'uk', 'de', 'fr', 'au', 'jp', 'other'];

/** Region.name as seeded by the catalog migrations — used where a label is
 * rendered without the API's Region objects to hand. */
export const REGION_LABELS: Record<string, string> = {
	world: 'World',
	us: 'USA',
	eu: 'Europe',
	uk: 'United Kingdom',
	de: 'Germany',
	fr: 'France',
	au: 'Australia',
	jp: 'Japan',
	other: 'Other'
};

/** The set of region ids a filter on `regionId` should match. */
export function expandRegionFilter(regionId: string): string[] {
	const ids = new Set<string>([regionId]);

	const parent = REGION_PARENTS[regionId];
	if (parent) ids.add(parent);
	for (const child of REGION_CHILDREN[regionId] ?? []) ids.add(child);

	if (!NO_WORLD.has(regionId)) ids.add(WORLD_REGION);

	return [...ids].sort();
}
