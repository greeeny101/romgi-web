/**
 * A remembered "save my ROMs here" folder, on top of the File System Access
 * API. Picking a folder once means every later Save file writes straight into
 * it with no per-file browser dialog — the point being that you can sort the
 * Downloaded list by platform and work down it.
 *
 * Chromium only (Chrome/Edge). Firefox and Safari have no showDirectoryPicker,
 * so callers fall back to the blob-URL anchor download; isFolderPickerSupported
 * is what the UI hides itself behind.
 *
 * The handle lives in IndexedDB rather than localStorage: a
 * FileSystemDirectoryHandle is structured-cloneable but not JSON-serialisable,
 * so the localStorage pattern used by stores/auth.ts can't carry it.
 */

import { browser } from '$app/environment';

const DB_NAME = 'romgi';
const STORE = 'settings';
const HANDLE_KEY = 'download-folder';

export function isFolderPickerSupported(): boolean {
	return browser && 'showDirectoryPicker' in window;
}

function openDb(): Promise<IDBDatabase> {
	return new Promise((resolve, reject) => {
		const req = indexedDB.open(DB_NAME, 1);
		req.onupgradeneeded = () => {
			if (!req.result.objectStoreNames.contains(STORE)) req.result.createObjectStore(STORE);
		};
		req.onsuccess = () => resolve(req.result);
		req.onerror = () => reject(req.error);
	});
}

async function idbGet<T>(key: string): Promise<T | null> {
	const db = await openDb();
	try {
		return await new Promise<T | null>((resolve, reject) => {
			const req = db.transaction(STORE, 'readonly').objectStore(STORE).get(key);
			req.onsuccess = () => resolve((req.result as T) ?? null);
			req.onerror = () => reject(req.error);
		});
	} finally {
		db.close();
	}
}

async function idbSet(key: string, value: unknown): Promise<void> {
	const db = await openDb();
	try {
		await new Promise<void>((resolve, reject) => {
			const tx = db.transaction(STORE, 'readwrite');
			if (value === null) tx.objectStore(STORE).delete(key);
			else tx.objectStore(STORE).put(value, key);
			tx.oncomplete = () => resolve();
			tx.onerror = () => reject(tx.error);
		});
	} finally {
		db.close();
	}
}

/** The stored handle, or null if none was ever picked. Says nothing about
 *  whether permission still stands — see folderPermission. */
export async function getSavedFolder(): Promise<FileSystemDirectoryHandle | null> {
	if (!isFolderPickerSupported()) return null;
	try {
		return await idbGet<FileSystemDirectoryHandle>(HANDLE_KEY);
	} catch {
		return null;
	}
}

/** 'granted' | 'prompt' | 'denied'. Chrome drops a directory grant when the
 *  tab closes, so a handle that worked yesterday usually comes back 'prompt'
 *  and needs one click to restore. */
export async function folderPermission(
	handle: FileSystemDirectoryHandle
): Promise<PermissionState> {
	return handle.queryPermission({ mode: 'readwrite' });
}

/** Opens the picker and remembers the result. Returns null if the user
 *  cancelled — an AbortError here is a normal outcome, not a failure. */
export async function chooseFolder(): Promise<FileSystemDirectoryHandle | null> {
	if (!isFolderPickerSupported()) return null;
	try {
		const handle = await window.showDirectoryPicker({
			mode: 'readwrite',
			// Reopens where the user left off instead of at the default root.
			id: 'romgi-downloads',
			startIn: 'downloads'
		});
		await idbSet(HANDLE_KEY, handle);
		return handle;
	} catch (err) {
		if (err instanceof DOMException && err.name === 'AbortError') return null;
		throw err;
	}
}

/**
 * The saved folder, ready to write to — re-prompting for permission if the
 * grant lapsed. Never opens the picker itself; `promptIfMissing` is the
 * caller's job so a Save click can decide whether to ask.
 *
 * MUST be awaited before any network call in a click handler: requestPermission
 * needs transient user activation, and an intervening fetch consumes it.
 */
export async function ensureFolder(
	promptIfMissing = false
): Promise<FileSystemDirectoryHandle | null> {
	if (!isFolderPickerSupported()) return null;

	const handle = await getSavedFolder();
	if (!handle) return promptIfMissing ? chooseFolder() : null;

	const state = await folderPermission(handle);
	if (state === 'granted') return handle;
	if (state === 'prompt') {
		const granted = await handle.requestPermission({ mode: 'readwrite' });
		if (granted === 'granted') return handle;
	}
	// Denied, or the folder is gone — drop it so the UI stops claiming to
	// save there and offers the picker again.
	await clearFolder();
	return promptIfMissing ? chooseFolder() : null;
}

export async function clearFolder(): Promise<void> {
	try {
		await idbSet(HANDLE_KEY, null);
	} catch {
		// Nothing useful to do — worst case the stale handle is re-prompted for.
	}
}

/** Writes `blob` into the chosen folder. `create: true` truncates an existing
 *  file, so re-saving a ROM replaces it rather than piling up "file (1)" copies. */
export async function saveToFolder(
	handle: FileSystemDirectoryHandle,
	filename: string,
	blob: Blob
): Promise<void> {
	const fileHandle = await handle.getFileHandle(sanitizeFilename(filename), { create: true });
	const writable = await fileHandle.createWritable();
	try {
		await writable.write(blob);
	} finally {
		await writable.close();
	}
}

/** getFileHandle rejects on path separators and reserved characters, and
 *  link_filename is raw scraper output that has never been sanitized. Strips
 *  the same set as playlist.py::playlist_file_name so the two agree; spaces,
 *  brackets and hyphens that ROM names genuinely use are left alone. */
function sanitizeFilename(name: string): string {
	const cleaned = name.replace(/[<>:"/\\|?*]/g, '_').trim();
	return cleaned || 'download';
}

/** The universal fallback: hand the blob to the browser's own downloader. */
export function anchorDownload(blob: Blob, filename: string): void {
	const url = URL.createObjectURL(blob);
	const a = document.createElement('a');
	a.href = url;
	a.download = filename;
	document.body.appendChild(a);
	a.click();
	a.remove();
	URL.revokeObjectURL(url);
}
