import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [svelte(), tailwindcss()],

  // BASE_PATH set by GitHub Actions to /repo-name/ for project pages.
  // Leave unset (or '/') for local dev, Railway, and user/org pages.
  base: process.env.BASE_PATH ?? '/',

  server: {
    port: 5174,
    proxy: {
      '/api': 'http://localhost:8010',
    },
  },

  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
