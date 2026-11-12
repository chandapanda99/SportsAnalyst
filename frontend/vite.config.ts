import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import type { Plugin } from 'vite';
import http from 'node:http';

const apiTarget = 'http://127.0.0.1:8767';

function quietStartupReadiness(): Plugin {
  return {
    name: 'quiet-startup-readiness',
    configureServer(server) {
      server.middlewares.use('/api/health', (_request, response) => {
        const upstream = http.get(`${apiTarget}/api/health`, { timeout: 750 }, (upstreamResponse) => {
          response.statusCode = upstreamResponse.statusCode ?? 503;
          response.setHeader('content-type', upstreamResponse.headers['content-type'] ?? 'application/json');
          upstreamResponse.pipe(response);
        });
        const unavailable = () => {
          if (response.writableEnded) return;
          response.statusCode = 503;
          response.setHeader('content-type', 'application/json');
          response.end(JSON.stringify({ status: 'starting' }));
        };
        upstream.on('timeout', () => {
          upstream.destroy();
          unavailable();
        });
        upstream.on('error', unavailable);
      });
    }
  };
}

export default defineConfig({
  plugins: [quietStartupReadiness(), svelte()],
  resolve: { conditions: ['browser'] },
  server: {
    port: 5173,
    proxy: { '/api': apiTarget }
  },
  test: {
    environment: 'jsdom',
    // The jsdom + Svelte render suites are CPU-bound, and each file's first
    // test pays for cold component and lazy-module transforms. With the
    // default worker count (CPUs - 1) the workers starve each other: those
    // first tests ran 5-9s and tripped the 5s default timeout at random.
    // Half the cores finished faster (about 41s vs 54s on a 12-core machine)
    // with the slowest test near 5s; 20s leaves headroom for slower machines.
    maxWorkers: '50%',
    testTimeout: 20_000
  }
});
