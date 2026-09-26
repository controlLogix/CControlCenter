import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

/* The design system lives at the REPO ROOT, in design/, and is owned by another
 * agent. This app imports it; it never copies it. A copy is how two sources of
 * truth for a palette get created, and the copy is always the one that is stale.
 *
 * Two things are needed to import across the package boundary under Vite:
 *   1. the `@design` alias below, so no view ever writes ../../../design, and
 *   2. server.fs.allow, because the dev server refuses to serve a file outside
 *      its root by default and design/ is two levels above it.
 */
const repoRoot = fileURLToPath(new URL('../..', import.meta.url));
const designDir = fileURLToPath(new URL('../../design', import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@design': designDir,
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5273,
    fs: { allow: [repoRoot] },
  },
  build: {
    target: 'es2022',
    sourcemap: true,
  },
});
