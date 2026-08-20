import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The built output is committed and served by the Python API,
// so the build is deterministic and unminified: a reader can
// diff what ships against what the source says.
export default defineConfig({
  plugins: [react()],
  // Relative, not absolute. A consumer that embeds this build
  // serves it from its own path, and an absolute base would
  // make the assets 404 there.
  base: './',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    minify: false,
    sourcemap: false,
    rollupOptions: {
      output: {
        // Content hashed. The filenames are the cache policy:
        // a build that changed is a URL that changed, so a
        // browser holding the old one has no way to serve it
        // for the new page, and a build that did not change
        // keeps its name and stays cached.
        entryFileNames: 'assets/app-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/app-[hash].[ext]',
      },
    },
  },
  server: {
    proxy: { '/api': 'http://127.0.0.1:8787' },
  },
});
