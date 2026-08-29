import { writable } from 'svelte/store';
import { biosApi, type BiosDownload, type EnqueueBiosPayload } from '$lib/api/bios';
import { biosSocket } from './ws';

function createBiosStore() {
	const { subscribe, set, update } = writable<BiosDownload[]>([]);
	let unsubscribeWs: (() => void) | null = null;

	function upsert(bios: BiosDownload) {
		update((rows) => {
			const idx = rows.findIndex((r) => r.id === bios.id);
			if (idx === -1) return [bios, ...rows];
			const next = [...rows];
			next[idx] = bios;
			return next;
		});
	}

	function remove(id: number) {
		update((rows) => rows.filter((r) => r.id !== id));
	}

	async function load() {
		set(await biosApi.list());
	}

	function start() {
		biosSocket.connect();
		if (!unsubscribeWs) {
			unsubscribeWs = biosSocket.subscribe((type, data) => {
				if (type === 'bios.progress' || type === 'bios.completed' || type === 'bios.failed') {
					upsert(data as BiosDownload);
				}
			});
		}
		load().catch(() => {});
	}

	function stop() {
		unsubscribeWs?.();
		unsubscribeWs = null;
		biosSocket.disconnect();
		set([]);
	}

	async function enqueue(payload: EnqueueBiosPayload) {
		const bios = await biosApi.enqueue(payload);
		// Enqueuing replaces any previous attempt at the same identifier, so
		// resync rather than upserting — otherwise the displaced row lingers.
		await load();
		return bios;
	}

	async function pause(id: number) {
		upsert(await biosApi.pause(id));
	}

	async function resume(id: number) {
		upsert(await biosApi.resume(id));
	}

	async function cancel(id: number) {
		await biosApi.cancel(id);
		remove(id);
	}

	return { subscribe, start, stop, load, enqueue, pause, resume, cancel };
}

export const bios = createBiosStore();
