import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

/** Strict CSP for the production build only (the dev server needs inline scripts and a websocket). */
export const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'none'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
].join('; ')

/**
 * Make dist/index.html work from file://.
 * Chrome refuses module scripts (and crossorigin stylesheets) over file:// because the
 * page origin is "null", so the bundle is emitted as one classic IIFE script and loaded
 * with a plain deferred <script src>. It stays an external file, so script-src 'self'
 * still holds (no inline script, no 'unsafe-inline').
 */
function fileSafeHtml(): Plugin {
  return {
    name: 'file-safe-html-and-csp',
    apply: 'build',
    transformIndexHtml: {
      order: 'post',
      handler(html) {
        return html
          .replace(/<script type="module" crossorigin src=/g, '<script defer src=')
          .replace(/ crossorigin(?=[ >])/g, '')
          .replace('<meta charset="UTF-8" />', `<meta charset="UTF-8" />\n    <meta http-equiv="Content-Security-Policy" content="${CSP}" />`)
      },
    },
  }
}

export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss(), fileSafeHtml()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  build: {
    modulePreload: false,
    cssCodeSplit: false,
    rolldownOptions: { output: { format: 'iife' } },
  },
})
