import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [sveltekit(), tailwindcss()],
	server: {
		proxy: {
			'/tl/api': {
				target: 'http://localhost:3000',
				rewrite: (path: string) => path.replace(/^\/tl/, '')
			}
		}
	}
});
