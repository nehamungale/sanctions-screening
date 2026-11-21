import { useEffect, useMemo, useState } from 'react'

import { AlertView } from '@/AlertView'
import { Audit } from '@/Audit'
import { Overview, type Origin } from '@/Overview'
import { Queue } from '@/Queue'
import { Card, CardContent } from '@/components/ui/card'
import { buildModel, buildRepro, EMPTY, loadLocalRun, loadSample, LOCAL_RUN_AVAILABLE, type Loaded, type SampleKind } from '@/lib/data'
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

/** ?sample=1 (everything), ?sample=trace (trace only; alias summaries), ?sample=pipeline (real stage4 trace), ?sample=crosscheck (a wrong pipeline summary); &repro=flipped. */
type SampleMode = { mode: SampleKind | 'local'; repro: 'stable' | 'flipped' } | null

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
  if (q.get('run') === 'local' && LOCAL_RUN_AVAILABLE) return { mode: 'local', repro: 'stable' }
  const v = q.get('sample')
  const mode = v === '1' ? 'full' : v === 'trace' || v === 'summaries' || v === 'pipeline' || v === 'crosscheck' ? v : null
  return mode ? { mode, repro: q.get('repro') === 'flipped' ? 'flipped' : 'stable' } : null
}

function writeUrl(nav: Nav, sample: SampleMode) {
  const q = new URLSearchParams()
  if (sample?.mode === 'local') q.set('run', 'local')
  else if (sample) {
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
  const [initial] = useState(() => initialData(sample))
  const [loaded, setLoaded] = useState<Loaded>(initial.loaded)
  const [origin, setOrigin] = useState<Origin>(initial.origin)

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

  const needPerson = model ? model.counts.hitsByDecision.REVIEW + model.counts.hitsUndecided : 0
  const openLocal = LOCAL_RUN_AVAILABLE
    ? () => {
        const r = loadLocalRun()
        if (!r) return
        const s: SampleMode = { mode: 'local', repro: 'stable' }
        setLoaded(r.loaded)
        setOrigin({ kind: 'local', label: r.label })
        setSample(s)
        go(reset, s)
      }
    : null

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
                {s.id === 'queue' && needPerson > 0 ? (
                  <span
                    className={cn('halo ml-2 inline-flex min-w-5 justify-center rounded-full bg-amber-500 px-1.5 text-[11px] font-semibold text-white tabular-nums')}
                    title={`${needPerson} hits need an analyst decision`}
                  >
                    {needPerson}
                  </span>
                ) : null}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-8 sm:py-10">
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
              origin={origin}
              onLocalRun={openLocal}
              onLoad={(patch) => {
                const next = { ...loaded, ...patch }
                setLoaded(next)
                // Adding the alerts file to our dev run keeps it "our dev run"; anything else is opened files.
                const keep = origin?.kind === 'local' && !patch.trace
                setOrigin({ kind: keep ? 'local' : 'files', label: [next.trace?.name, next.alerts?.name, next.repro?.name].filter(Boolean).join(' + ') })
                setSample(null)
                go(reset, null)
              }}
              onSample={() => {
                const s: SampleMode = { mode: 'full', repro: 'stable' }
                setLoaded(loadSample())
                setOrigin({ kind: 'sample', label: 'bundled synthetic fixtures (invented customers)' })
                setSample(s)
                go(reset, s)
              }}
              onClear={() => {
                setLoaded(EMPTY)
                setOrigin(null)
                setSample(null)
                go(reset, null)
              }}
              onQueue={() => go({ screen: 'queue', ...reset, filters: NO_FILTERS })}
              onAudit={(filters) => go({ screen: 'audit', ...reset, filters })}
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

function initialData(sample: SampleMode): { loaded: Loaded; origin: Origin } {
  if (sample?.mode === 'local') {
    const r = loadLocalRun()
    if (r) return { loaded: r.loaded, origin: { kind: 'local', label: r.label } }
    return { loaded: EMPTY, origin: null }
  }
  if (sample) return { loaded: loadSample(sample.mode, sample.repro), origin: { kind: 'sample', label: 'bundled synthetic fixtures (invented customers)' } }
  return { loaded: EMPTY, origin: null }
}
