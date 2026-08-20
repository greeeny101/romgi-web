import { writable } from 'svelte/store';
import { browser } from '$app/environment';

interface EntryReturn {
	/** Where an entry page's back link goes: '/?platform=snes', '/library?tab=recent'. */
	href: string;
	/** What that place is called, for the link's text: 'Browse', 'Library'. */
	label: string;
	/** The entry a user last opened, so the list it came from can scroll it back into view. */
	focusSlug: string | null;
}

const STORAGE_KEY = 'romgi.entryReturn.v1';
// Browse is the fallback because an entry reached by a pasted link or a reload
// has no recorded origin, and the catalog is the one place always worth offering.
const EMPTY: EntryReturn = { href: '/', label: 'Browse', focusSlug: null };

// Session-scoped rather than localStorage: this is navigation context for the
// current visit, not a setting worth restoring days later.
function loadInitial(): EntryReturn {
	if (!browser) return EMPTY;
	const raw = sessionStorage.getItem(STORAGE_KEY);
	if (!raw) return EMPTY;
	try {
		return { ...EMPTY, ...(JSON.parse(raw) as Partial<EntryReturn>) };
	} catch {
		return EMPTY;
	}
}

function createEntryReturnStore() {
	let current = loadInitial();
	const { subscribe, set } = writable<EntryReturn>(current);

	function commit(next: EntryReturn) {
		current = next;
		if (browser) sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
		set(next);
	}

	return {
		subscribe,
		/** Called by any list page that links to entries, with where to come back to. */
		rememberOrigin(href: string, label: string) {
			if (href === current.href && label === current.label) return;
			commit({ ...current, href, label });
		},
		rememberFocus(slug: string) {
			if (slug === current.focusSlug) return;
			commit({ ...current, focusSlug: slug });
		},
		/**
		 * Returns the slug for `pathname` to scroll to, clearing it so it only
		 * applies once. Pages other than the recorded origin get null: after
		 * Browse → entry → Library from the nav, the pending focus belongs to
		 * Browse, and Library must not consume it and highlight its own list.
		 */
		takeFocus(pathname: string): string | null {
			const slug = current.focusSlug;
			if (!slug || current.href.split('?')[0] !== pathname) return null;
			commit({ ...current, focusSlug: null });
			return slug;
		}
	};
}

export const entryReturn = createEntryReturnStore();
