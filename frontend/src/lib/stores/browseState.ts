import { writable } from 'svelte/store';
import { browser } from '$app/environment';

interface BrowseState {
	/** The browse page's query string, leading `?` included, or '' when unfiltered. */
	search: string;
	/** The entry a user last opened, so browse can scroll it back into view. */
	focusSlug: string | null;
}

const STORAGE_KEY = 'romgi.browse.v1';
const EMPTY: BrowseState = { search: '', focusSlug: null };

// Session-scoped rather than localStorage: this is navigation context for the
// current visit, not a setting worth restoring days later.
function loadInitial(): BrowseState {
	if (!browser) return EMPTY;
	const raw = sessionStorage.getItem(STORAGE_KEY);
	if (!raw) return EMPTY;
	try {
		return { ...EMPTY, ...(JSON.parse(raw) as Partial<BrowseState>) };
	} catch {
		return EMPTY;
	}
}

function createBrowseStateStore() {
	let current = loadInitial();
	const { subscribe, set } = writable<BrowseState>(current);

	function commit(next: BrowseState) {
		current = next;
		if (browser) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
		set(next);
	}

	return {
		subscribe,
		rememberSearch(search: string) {
			if (search === current.search) return;
			commit({ ...current, search });
		},
		rememberFocus(slug: string) {
			if (slug === current.focusSlug) return;
			commit({ ...current, focusSlug: slug });
		},
		/** Returns the slug to scroll to, clearing it so it only applies once. */
		takeFocus(): string | null {
			const slug = current.focusSlug;
			if (slug) commit({ ...current, focusSlug: null });
			return slug;
		}
	};
}

export const browseState = createBrowseStateStore();
