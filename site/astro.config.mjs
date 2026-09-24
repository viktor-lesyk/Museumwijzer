import { defineConfig } from 'astro/config';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  site: 'https://museumwijzer.vlesyk.com',
  output: 'static',
  server: {
    host: '0.0.0.0',
    port: 4321,
    allowedHosts: true,
  },
  preview: {
    host: '0.0.0.0',
    port: 4321,
    allowedHosts: true,
  },
  i18n: {
    defaultLocale: 'nl',
    locales: ['nl', 'en', 'uk'],
    routing: {
      prefixDefaultLocale: true,
      redirectToDefaultLocale: false,
    },
  },
  vite: {
    resolve: {
      alias: {
        '@data': path.resolve(__dirname, '../data'),
      },
    },
    preview: {
      allowedHosts: true,
    },
    server: {
      allowedHosts: true,
    },
  },
});
