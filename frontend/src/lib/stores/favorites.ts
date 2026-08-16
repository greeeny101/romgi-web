import { writable } from 'svelte/store';
import { libraryApi, type FavoriteEntry } from '$lib/api/library';

function createFavoritesStore() {
	const { subscribe, set, update } = writable<Map<string, FavoriteEntry>>(new Map());

	return {
		subscribe,
		async load() {
			const favorites = await libraryApi.favorites();
			set(new Map(favorites.map((f) => [f.slug, f])));
		},
		async toggle(slug: string) {
			let isFavorited = false;
			update((map) => {
				isFavorited = map.has(slug);
				return map;
			});
			if (isFavorited) {
				await libraryApi.removeFavorite(slug);
				update((map) => {
					const next = new Map(map);
					next.delete(slug);
					return next;
				});
			} else {
				const favorite = await libraryApi.addFavorite(slug);
				update((map) => new Map(map).set(slug, favorite));
			}
		},
		clear() {
			set(new Map());
		}
	};
}

export const favorites = createFavoritesStore();
