import { useEffect, useMemo, useState } from 'react'

import { AlertView } from '@/AlertView'
import { Audit } from '@/Audit'
import { Overview } from '@/Overview'
import { Queue } from '@/Queue'
import { Card, CardContent } from '@/components/ui/card'
import { buildModel, buildRepro, EMPTY, loadSample, type Loaded } from '@/lib/data'
import { STATUS_LABELS, statusFromSlug } from '@/lib/labels'
import { isDecision, type RollupStatus } from '@/lib/policy'
import { cn } from '@/lib/utils'
import { NO_FILTERS, type AuditFilters, type HitRow } from '@/lib/worklist'

type Screen = 'overview' | 'queue' | 'audit'

const SCREENS: { id: Screen; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'queue', label: 'Analyst queue' },
  { id: 'audit', label: 'Audit' },
]

/**
 * Navigation lives in the URL so every view can be deep-linked:
 * ?screen=queue|audit  ?status=…  ?alert=A-…  ?hit=H-…  and Audit filters
 * ?verdict=…  ?code=…  ?fragility=…  ?unstable=1  ?llm=yes|no
 */
interface Nav {
  screen: Screen
  status: RollupStatus | null
  alert: string | null
  hit: string | null
  filters: AuditFilters
}

/** ?sample=1 (everything), ?sample=trace (trace only), ?sample=summaries (trace + alerts.trace.jsonl); &repro=flipped. */
type SampleMode = { mode: 'full' | 'trace' | 'summaries'; repro: 'stable' | 'flipped' } | null

function readNav(): Nav {
  const q = new URLSearchParams(window.location.search)
  const s = q.get('screen')
  const v = q.get('verdict')
  const llm = q.get('llm')
  return {
    screen: SCREENS.some((x) => x.id === s) ? (s as Screen) : 'overview',
    status: statusFromSlug(q.get('status')),
    alert: q.get('alert'),
    hit: q.get('hit'),
    filters: {
      verdict: v === 'none' || isDecision(v) ? v : null,
      code: q.get('code'),
      fragility: q.get('fragility'),
      unstable: q.get('unstable') === '1',
      llm: llm === 'yes' || llm === 'no' ? llm : null,
    },
  }
}

function readSample(): SampleMode {
  const q = new URLSearchParams(window.location.search)
  const v = q.get('sample')
  const mode = v === '1' ? 'full' : v === 'trace' || v === 'summaries' ? v : null
  return mode ? { mode, repro: q.get('repro') === 'flipped' ? 'flipped' : 'stable' } : null
}

function writeUrl(nav: Nav, sample: SampleMode) {
  const q = new URLSearchParams()
  if (sample) {
    q.set('sample', sample.mode === 'full' ? '1' : sample.mode)
    if (sample.repro === 'flipped') q.set('repro', 'flipped')
  }
  if (nav.screen !== 'overview') q.set('screen', nav.screen)
  if (nav.status) q.set('status', STATUS_LABELS[nav.status].slug)
  if (nav.alert) q.set('alert', nav.alert)
  if (nav.hit) q.set('hit', nav.hit)
  if (nav.screen === 'audit') {
    const f = nav.filters
    if (f.verdict) q.set('verdict', f.verdict)
    if (f.code) q.set('code', f.code)
    if (f.fragility) q.set('fragility', f.fragility)
    if (f.unstable) q.set('unstable', '1')
    if (f.llm) q.set('llm', f.llm)
  }
  const url = `${window.location.pathname}${q.size ? `?${q}` : ''}`
  try {
    window.history.pushState(null, '', url)
  } catch {
    // Some file:// setups refuse history changes; navigation still works in memory.
  }
}

export default function App() {
  const [nav, setNav] = useState<Nav>(readNav)
  const [sample, setSample] = useState<SampleMode>(readSample)
  const [loaded, setLoaded] = useState<Loaded>(() => (sample ? loadSample(sample.mode, sample.repro) : EMPTY))

  const model = useMemo(() => buildModel(loaded), [loaded])
  const repro = useMemo(() => buildRepro(loaded.repro), [loaded.repro])

  useEffect(() => {
    const onPop = () => setNav(readNav())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const go = (next: Partial<Nav>, s: SampleMode = sample) => {
    const n = { ...nav, ...next }
    setNav(n)
    writeUrl(n, s)
  }
  const openRow = (r: HitRow | null) => go({ alert: r?.alert_id ?? null, hit: r?.hit_id ?? null })
  const reset = { status: null, alert: null, hit: null }

  const summary = model && nav.alert ? (model.summariesById.get(nav.alert) ?? null) : null
  const noData = (
    <Card className="mx-auto max-w-xl">
      <CardContent className="py-10 text-center text-sm text-muted-foreground">No trace loaded. Load files or the sample on the Overview.</CardContent>
    </Card>
  )

  return (
    <div className="min-h-screen">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-8 py-4">
          <div>
            <div className="text-base font-semibold">Screening reviewer</div>
            <div className="text-xs text-muted-foreground">Local files only · read-only</div>
          </div>
          <nav className="flex gap-1" aria-label="Screens">
            {SCREENS.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => go({ screen: s.id, ...reset, filters: s.id === 'audit' ? nav.filters : NO_FILTERS })}
                aria-current={nav.screen === s.id ? 'page' : undefined}
                className={cn(
                  'cursor-pointer rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                  nav.screen === s.id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                )}
              >
                {s.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-8 py-10">
        {nav.screen === 'queue' ? (
          model ? <Queue model={model} alertId={nav.alert} hitId={nav.hit} onOpen={openRow} /> : noData
        ) : nav.screen === 'audit' ? (
          model ? (
            <Audit
              model={model}
              repro={repro}
              filters={nav.filters}
              alertId={nav.alert}
              hitId={nav.hit}
              onFilters={(filters) => go({ filters, alert: null, hit: null })}
              onOpen={openRow}
            />
          ) : (
            noData
          )
        ) : model && summary ? (
          <AlertView
            model={model}
            summary={summary}
            hitId={nav.hit}
            onHit={(hit) => go({ hit })}
            onBack={() => go(reset)}
            onStatus={() => go({ ...reset, status: summary.alert_status })}
          />
        ) : (
          <>
            {nav.alert && model ? <p className="mb-6 text-sm text-amber-700">Alert {nav.alert} is not in the loaded files.</p> : null}
            <Overview
              loaded={loaded}
              model={model}
              repro={repro}
              status={nav.status}
              onLoad={(patch) => {
                setLoaded((l) => ({ ...l, ...patch }))
                setSample(null)
                go(reset, null)
              }}
              onSample={() => {
                const s: SampleMode = { mode: 'full', repro: 'stable' }
                setLoaded(loadSample())
                setSample(s)
                go(reset, s)
              }}
              onClear={() => {
                setLoaded(EMPTY)
                setSample(null)
                go(reset, null)
              }}
              onStatus={(status) => go({ status })}
              onAlert={(alert) => go({ alert, hit: null })}
              onReproHit={(hit, alert) => go({ screen: 'audit', filters: { ...NO_FILTERS, unstable: true }, status: null, alert, hit })}
            />
          </>
        )}
      </main>
    </div>
  )
}
