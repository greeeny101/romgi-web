import { writable } from 'svelte/store';
import { romsetsApi, type EnqueueSetPayload, type RomSetDownload } from '$lib/api/romsets';
import { romsetsSocket } from './ws';

function createRomSetsStore() {
	const { subscribe, set, update } = writable<RomSetDownload[]>([]);
	let unsubscribeWs: (() => void) | null = null;

	function upsert(romset: RomSetDownload) {
		update((rows) => {
			const idx = rows.findIndex((r) => r.id === romset.id);
			if (idx === -1) return [romset, ...rows];
			const next = [...rows];
			next[idx] = romset;
			return next;
		});
	}

	function remove(id: number) {
		update((rows) => rows.filter((r) => r.id !== id));
	}

	async function load() {
		set(await romsetsApi.list());
	}

	function start() {
		romsetsSocket.connect();
		if (!unsubscribeWs) {
			unsubscribeWs = romsetsSocket.subscribe((type, data) => {
				if (type === 'romset.progress' || type === 'romset.completed' || type === 'romset.failed') {
					upsert(data as RomSetDownload);
				}
			});
		}
		load().catch(() => {});
	}

	function stop() {
		unsubscribeWs?.();
		unsubscribeWs = null;
		romsetsSocket.disconnect();
		set([]);
	}

	async function enqueue(payload: EnqueueSetPayload) {
		const romset = await romsetsApi.enqueue(payload);
		// Enqueuing replaces any previous attempt at the same identifier, so
		// resync rather than upserting — otherwise the displaced row lingers.
		await load();
		return romset;
	}

	async function pause(id: number) {
		upsert(await romsetsApi.pause(id));
	}

	async function resume(id: number) {
		upsert(await romsetsApi.resume(id));
	}

	async function cancel(id: number) {
		await romsetsApi.cancel(id);
		remove(id);
	}

	return { subscribe, start, stop, load, enqueue, pause, resume, cancel };
}

export const romsets = createRomSetsStore();
