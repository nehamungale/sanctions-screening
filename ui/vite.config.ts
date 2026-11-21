import { existsSync, readFileSync } from 'node:fs'
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

/**
 * "Our run": the dev server (npm run dev) reads this repository's own run from disk, so the
 * reviewer can open it with one click. Local only: in a build the module is null, so no real
 * customer data can end up in dist/ (tests/check-ids.sh guards that too).
 *   trace:  $UI_TRACE, else $SANCTIONS_CACHE/trace.jsonl, else working/trace.jsonl, else output/dev.jsonl
 *   alerts: $UI_ALERTS, else dev/alerts.jsonl (lets alerts show as Cleared)
 */
function localRun(): Plugin {
  const id = 'virtual:local-run'
  const root = path.resolve(import.meta.dirname, '..')
  const first = (cands: (string | undefined)[]) => cands.filter((c): c is string => !!c).map((c) => path.resolve(root, c)).find((c) => existsSync(c)) ?? null
  let serve = false
  return {
    name: 'local-run',
    configResolved(c) {
      serve = c.command === 'serve'
    },
    resolveId(x) {
      return x === id ? `\0${id}` : null
    },
    load(x) {
      if (x !== `\0${id}`) return null
      if (!serve) return 'export default null'
      const cache = process.env.SANCTIONS_CACHE ?? 'working'
      const trace = first([process.env.UI_TRACE, path.join(cache, 'trace.jsonl'), 'output/dev.jsonl'])
      const alerts = first([process.env.UI_ALERTS, 'dev/alerts.jsonl'])
      const file = (f: string | null) => (f ? { name: path.relative(root, f), text: readFileSync(f, 'utf8') } : null)
      return `export default ${JSON.stringify({ trace: file(trace), alerts: file(alerts) })}`
    },
  }
}

export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss(), fileSafeHtml(), localRun()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  build: {
    modulePreload: false,
    cssCodeSplit: false,
    rolldownOptions: { output: { format: 'iife' } },
  },
})
