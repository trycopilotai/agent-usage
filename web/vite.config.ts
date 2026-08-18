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
        entryFileNames: 'assets/app.js',
        chunkFileNames: 'assets/[name].js',
        assetFileNames: 'assets/app.[ext]',
      },
    },
  },
  server: {
    proxy: { '/api': 'http://127.0.0.1:8787' },
  },
});
