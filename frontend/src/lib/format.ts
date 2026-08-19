/**
 * Display formatters shared by the downloads queue and the Library's
 * Downloaded tab. formatBytes started life inside DownloadQueueRow; it moved
 * here once the Library rows needed the same sizes to sort and label by.
 */

export function formatBytes(n: number): string {
	if (!n) return '0 B';
	const units = ['B', 'KB', 'MB', 'GB'];
	let value = n;
	let i = 0;
	while (value >= 1024 && i < units.length - 1) {
		value /= 1024;
		i++;
	}
	return `${value.toFixed(1)} ${units[i]}`;
}

/** Absolute local date *and* time — a Downloaded badge that only said the day
 *  couldn't tell two attempts at the same title apart. */
export function formatDateTime(iso: string): string {
	return new Date(iso).toLocaleString();
}

/**
 * How long a staged file has left, as "expires in 6h" / "expires in 3 days".
 * Null when there's no expiry recorded or the window has already passed — the
 * caller has `file_available` for the "it's gone" case and shouldn't be
 * rendering a countdown at all by then.
 */
export function formatExpiry(iso: string | null): string | null {
	if (!iso) return null;
	const ms = new Date(iso).getTime() - Date.now();
	if (!Number.isFinite(ms) || ms <= 0) return null;

	const hours = Math.round(ms / 3_600_000);
	if (hours < 1) return 'expires in under an hour';
	if (hours < 48) return `expires in ${hours}h`;
	return `expires in ${Math.round(hours / 24)} days`;
}
