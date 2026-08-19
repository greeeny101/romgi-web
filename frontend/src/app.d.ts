// See https://svelte.dev/docs/kit/types#app.d.ts
// for information about these interfaces
declare global {
	namespace App {
		// interface Error {}
		// interface Locals {}
		// interface PageData {}
		// interface PageState {}
		// interface Platform {}
	}

	// The File System Access API bits TypeScript's DOM lib still doesn't ship:
	// showDirectoryPicker and the per-handle permission methods. Used by
	// lib/downloadTarget.ts to remember where the user wants ROMs saved.
	// Declared here rather than pulling in @types/wicg-file-system-access for
	// three signatures. Chromium-only at runtime — every caller guards on
	// isFolderPickerSupported().
	interface FileSystemHandlePermissionDescriptor {
		mode?: 'read' | 'readwrite';
	}

	interface FileSystemDirectoryHandle {
		queryPermission(descriptor?: FileSystemHandlePermissionDescriptor): Promise<PermissionState>;
		requestPermission(descriptor?: FileSystemHandlePermissionDescriptor): Promise<PermissionState>;
	}

	interface Window {
		showDirectoryPicker(options?: {
			mode?: 'read' | 'readwrite';
			id?: string;
			startIn?: string | FileSystemHandle;
		}): Promise<FileSystemDirectoryHandle>;
	}
}

export {};
