import { useEffect, useMemo, useState } from 'react'

import { AlertView } from '@/AlertView'
import { Overview } from '@/Overview'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { buildModel, loadSample, type LoadedAlerts, type LoadedTrace } from '@/lib/data'
import { STATUS_LABELS, statusFromSlug } from '@/lib/labels'
import type { RollupStatus } from '@/lib/policy'
import { cn } from '@/lib/utils'

type Screen = 'overview' | 'queue' | 'audit'

const SCREENS: { id: Screen; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'queue', label: 'Analyst queue' },
  { id: 'audit', label: 'Audit' },
]

const PLACEHOLDERS: Record<Exclude<Screen, 'overview'>, { step: number; text: string }> = {
  queue: { step: 3, text: 'REVIEW hits grouped by alert, blocking hits first, opening the same hit panel.' },
  audit: { step: 4, text: 'Reproducibility card, run strips and the flip panel from repro.json.' },
}

/** Navigation lives in the URL (?screen, ?status, ?alert, ?hit) so views can be deep-linked. */
interface Nav {
  screen: Screen
  status: RollupStatus | null
  alert: string | null
  hit: string | null
}

function readNav(): Nav {
  const q = new URLSearchParams(window.location.search)
  const s = q.get('screen')
  return {
    screen: SCREENS.some((x) => x.id === s) ? (s as Screen) : 'overview',
    status: statusFromSlug(q.get('status')),
    alert: q.get('alert'),
    hit: q.get('hit'),
  }
}

type SampleMode = false | '1' | 'trace'

function writeUrl(nav: Nav, sample: SampleMode, push: boolean) {
  const q = new URLSearchParams()
  if (sample) q.set('sample', sample)
  if (nav.screen !== 'overview') q.set('screen', nav.screen)
  if (nav.status) q.set('status', STATUS_LABELS[nav.status].slug)
  if (nav.alert) q.set('alert', nav.alert)
  if (nav.hit) q.set('hit', nav.hit)
  const url = `${window.location.pathname}${q.size ? `?${q}` : ''}`
  try {
    if (push) window.history.pushState(null, '', url)
    else window.history.replaceState(null, '', url)
  } catch {
    // Some file:// setups refuse history changes; navigation still works in memory.
  }
}

export default function App() {
  const [nav, setNav] = useState<Nav>(readNav)
  // ?sample=1 loads both sample files; ?sample=trace loads only the trace (shows "Not verified").
  const [initialMode] = useState<SampleMode>(() => {
    const v = new URLSearchParams(window.location.search).get('sample')
    return v === '1' || v === 'trace' ? v : false
  })
  const [initial] = useState(() => (initialMode ? loadSample() : null))
  const [trace, setTrace] = useState<LoadedTrace | null>(initial?.trace ?? null)
  const [alerts, setAlerts] = useState<LoadedAlerts | null>(initialMode === '1' ? (initial?.alerts ?? null) : null)
  const [isSample, setIsSample] = useState<SampleMode>(initialMode)

  const model = useMemo(() => (trace ? buildModel(trace, alerts) : null), [trace, alerts])

  useEffect(() => {
    const onPop = () => setNav(readNav())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const go = (next: Partial<Nav>, sample: SampleMode = isSample) => {
    const n = { ...nav, ...next }
    setNav(n)
    writeUrl(n, sample, true)
  }

  const summary = model && nav.alert ? (model.summariesById.get(nav.alert) ?? null) : null

  return (
    <div className="min-h-screen">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-8 py-4">
          <div>
            <div className="text-base font-semibold">Screening reviewer</div>
            <div className="text-xs text-muted-foreground">Local files only · read-only</div>
          </div>
          <nav className="flex gap-1" aria-label="Screens">
            {SCREENS.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => go({ screen: s.id, status: null, alert: null, hit: null })}
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

      <main className="mx-auto max-w-6xl px-8 py-10">
        {nav.screen !== 'overview' ? (
          <Card className="mx-auto max-w-xl">
            <CardHeader>
              <CardTitle>{SCREENS.find((s) => s.id === nav.screen)?.label}</CardTitle>
              <CardDescription>Coming in step {PLACEHOLDERS[nav.screen].step}.</CardDescription>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">{PLACEHOLDERS[nav.screen].text}</CardContent>
          </Card>
        ) : model && summary ? (
          <AlertView
            model={model}
            summary={summary}
            hitId={nav.hit}
            onHit={(hit) => go({ hit })}
            onBack={() => go({ alert: null, hit: null, status: null })}
            onStatus={() => go({ alert: null, hit: null, status: summary.alert_status })}
          />
        ) : (
          <>
            {nav.alert && model ? (
              <p className="mb-6 text-sm text-amber-700">Alert {nav.alert} is not in the loaded files.</p>
            ) : null}
            <Overview
              trace={trace}
              alerts={alerts}
              model={model}
              status={nav.status}
              onTrace={(t) => {
                setTrace(t)
                setIsSample(false)
                go({ status: null, alert: null, hit: null }, false)
              }}
              onAlerts={(a) => {
                setAlerts(a)
                setIsSample(false)
                go({ status: null, alert: null, hit: null }, false)
              }}
              onSample={() => {
                const s = loadSample()
                setTrace(s.trace)
                setAlerts(s.alerts)
                setIsSample('1')
                go({ status: null, alert: null, hit: null }, '1')
              }}
              onClear={() => {
                setTrace(null)
                setAlerts(null)
                setIsSample(false)
                go({ status: null, alert: null, hit: null }, false)
              }}
              onStatus={(status) => go({ status })}
              onAlert={(alert) => go({ alert, hit: null })}
            />
          </>
        )}
      </main>
    </div>
  )
}
