import { writable } from 'svelte/store';
import { downloadsApi, type DownloadTask, type EnqueuePayload } from '$lib/api/downloads';
import { downloadsSocket } from './ws';

function createDownloadsStore() {
	const { subscribe, set, update } = writable<DownloadTask[]>([]);
	let unsubscribeWs: (() => void) | null = null;

	function upsert(task: DownloadTask) {
		update((tasks) => {
			const idx = tasks.findIndex((t) => t.id === task.id);
			if (idx === -1) return [...tasks, task];
			const next = [...tasks];
			next[idx] = task;
			return next;
		});
	}

	function remove(id: number) {
		update((tasks) => tasks.filter((t) => t.id !== id));
	}

	async function load() {
		set(await downloadsApi.list());
	}

	function start() {
		downloadsSocket.connect();
		if (!unsubscribeWs) {
			unsubscribeWs = downloadsSocket.subscribe((type, data) => {
				if (type === 'download.progress' || type === 'download.completed' || type === 'download.failed') {
					upsert(data as DownloadTask);
				}
			});
		}
		load().catch(() => {});
	}

	function stop() {
		unsubscribeWs?.();
		unsubscribeWs = null;
		downloadsSocket.disconnect();
		set([]);
	}

	async function enqueue(payload: EnqueuePayload) {
		const task = await downloadsApi.enqueue(payload);
		// Enqueuing replaces whatever task the slug already had (and a group
		// enqueue creates more rows than the one returned), so resync rather
		// than upserting — otherwise the rows it displaced linger in the list.
		await load();
		return task;
	}

	async function pause(id: number) {
		upsert(await downloadsApi.pause(id));
	}

	async function resume(id: number) {
		upsert(await downloadsApi.resume(id));
	}

	async function retry(id: number) {
		upsert(await downloadsApi.retry(id));
	}

	async function cancel(id: number) {
		await downloadsApi.cancel(id);
		remove(id);
	}

	return { subscribe, start, stop, load, enqueue, pause, resume, retry, cancel };
}

export const downloads = createDownloadsStore();
