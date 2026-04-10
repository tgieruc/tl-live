import { writable } from 'svelte/store';

export const activeLines = writable<Set<string>>(new Set());
