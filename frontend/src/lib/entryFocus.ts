import { tick } from 'svelte';

/** How long a returned-to card keeps its ring before fading back into the grid. */
const HIGHLIGHT_MS = 2000;

// Guards the clear-timeout: only the most recent call may switch the highlight
// off, so a second restore can't be cut short by the first one's timer.
let latest = 0;

/**
 * Bring the entry a user came back from into view and ring it briefly. The card
 * must render as `#entry-{slug}` — both Browse and Library pass that id to
 * RomGridCard/RomListTile.
 */
export async function restoreEntryFocus(
	slug: string,
	setHighlight: (slug: string | null) => void
): Promise<void> {
	const token = ++latest;

	// After a tick, so this runs once the card has actually rendered rather
	// than in the same frame the result set landed.
	await tick();
	const card = document.getElementById(`entry-${slug}`);
	if (!card) return;

	// Instant, not smooth — smooth scrolling fights SvelteKit's own scroll
	// restoration when arriving via the back button.
	card.scrollIntoView({ block: 'center' });
	setHighlight(slug);
	setTimeout(() => {
		if (token === latest) setHighlight(null);
	}, HIGHLIGHT_MS);
}
