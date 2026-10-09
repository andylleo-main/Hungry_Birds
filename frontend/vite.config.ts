import { defineConfig, mergeConfig } from 'vite';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
import base from '../apps/web/vite.config';

// Preview-only wrapper so the Emergent supervisor can serve apps/web on :3000.
export default mergeConfig(
  base,
  defineConfig({
    root: path.resolve(__dirname, '../apps/web'),
    server: { host: '0.0.0.0', port: 3000, strictPort: true, allowedHosts: true },
  }),
);
