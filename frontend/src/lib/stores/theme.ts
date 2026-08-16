import { writable } from 'svelte/store';
import { browser } from '$app/environment';

export type Theme = 'system' | 'light' | 'dark';

export const theme = writable<Theme>('system');

function apply(value: Theme) {
	if (!browser) return;
	const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
	const isDark = value === 'dark' || (value === 'system' && prefersDark);
	document.documentElement.classList.toggle('dark', isDark);
}

if (browser) {
	theme.subscribe(apply);
	window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
		let current: Theme = 'system';
		theme.subscribe((v) => (current = v))();
		if (current === 'system') apply('system');
	});
}
