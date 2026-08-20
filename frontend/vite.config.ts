import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  resolve: { conditions: ['browser'] },
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8767' }
  },
  test: { environment: 'jsdom' }
});
