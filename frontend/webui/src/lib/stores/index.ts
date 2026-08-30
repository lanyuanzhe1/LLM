import { writable } from 'svelte/store';

export type User = {
	token: string;
	token_type?: string;
	expires_at?: number | null;
	id: string;
	email: string;
	name?: string;
	role?: string;
	profile_image_url?: string;
	permissions?: Record<string, unknown>;
};

export const user = writable<User | null>(null);
export const config = writable<Record<string, unknown> | null>(null);
export const chatId = writable('');
