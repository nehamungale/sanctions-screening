import { useRef, type ChangeEvent, type ReactNode } from 'react'

import { BarList, Donut, StackedBar, type BarRow, type Segment } from '@/components/charts'
import { ReproCard } from '@/components/ReproCard'
import { DECISION_TONE, DISPLAY_STATUSES, ReasonCode, StatusBadge, STATUS_TONE } from '@/components/verdict'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { buildRepro, Loaded, LoadedAlerts, Model } from '@/lib/data'
import { crossCheckText, reasonLabel, STATUS_LABELS } from '@/lib/labels'
import { parseAlerts, parseTraceJsonl, type TraceParseResult } from '@/lib/parse'
import { parseRepro } from '@/lib/repro'
import { DISPLAY_DECISIONS, HIT_NOT_DECIDED, type Decision, type RollupStatus } from '@/lib/policy'
import type { AlertSummary, ParseIssue } from '@/lib/types'
import { cn } from '@/lib/utils'
import { NO_FILTERS, type AuditFilters } from '@/lib/worklist'

/** Which data the page is showing. */
export type Origin = { kind: 'local' | 'sample' | 'files'; label: string } | null

interface Props {
  loaded: Loaded
  model: Model | null
  repro: ReturnType<typeof buildRepro>
  status: RollupStatus | null
  origin: Origin
  /** Null when the page is not served by the dev server (the built page cannot read the repo). */
  onLocalRun: (() => void) | null
  onLoad: (patch: Partial<Loaded>) => void
  onSample: () => void
  onClear: () => void
  onStatus: (s: RollupStatus | null) => void
  onAlert: (alertId: string) => void
  onReproHit: (hitId: string, alertId: string | null) => void
  onQueue: () => void
  onAudit: (f: AuditFilters) => void
}

const DECISION_WORDS: Record<Decision, string> = {
  SAME_ENTITY: 'Same entity · to compliance',
  REVIEW: 'Review · analyst decides',
  DIFFERENT_ENTITY: 'Different entity · cleared',
}

export function Overview(p: Props) {
  const { loaded, model, status } = p
  const traceInput = useRef<HTMLInputElement>(null)
  const alertsInput = useRef<HTMLInputElement>(null)
  const reproInput = useRef<HTMLInputElement>(null)

  const pick = async (e: ChangeEvent<HTMLInputElement>, kind: 'trace' | 'alerts' | 'repro') => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const text = await file.text()
    if (kind === 'trace') p.onLoad({ trace: { name: file.name, result: parseTraceJsonl(text) } })
    else if (kind === 'repro') p.onLoad({ repro: { name: file.name, result: parseRepro(text) } })
    else {
      // One picker for both: alerts.jsonl lines fill the alert list; a separate summaries file (legacy) the cross-check.
      const f: LoadedAlerts = { name: file.name, result: parseAlerts(text) }
      const patch: Partial<Loaded> = {}
      if (f.result.kind !== 'summaries') patch.alerts = f
      if (f.result.kind === 'summaries' || f.result.kind === 'mixed') patch.summaries = f
      p.onLoad(patch)
    }
  }

  const fileButtons = (
    <>
      <Button variant="outline" size="sm" onClick={() => traceInput.current?.click()}>
        Open output or trace…
      </Button>
      <Button variant="outline" size="sm" onClick={() => alertsInput.current?.click()}>
        Open alerts…
      </Button>
      <Button variant="outline" size="sm" onClick={() => reproInput.current?.click()}>
        Open repro…
      </Button>
      <input ref={traceInput} type="file" accept=".jsonl,.json,.txt,application/json" className="hidden" onChange={(e) => void pick(e, 'trace')} />
      <input ref={alertsInput} type="file" accept=".jsonl,.json,.txt,application/json" className="hidden" onChange={(e) => void pick(e, 'alerts')} />
      <input ref={reproInput} type="file" accept=".json,application/json" className="hidden" onChange={(e) => void pick(e, 'repro')} />
    </>
  )

  const counts = model?.counts
  const listed = model && status ? model.summaries.filter((s) => s.alert_status === status) : []

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
            <p className="mt-1 text-sm text-muted-foreground">What the screening run decided, and what still needs a person.</p>
          </div>
          <DataSwitch origin={p.origin} onLocalRun={p.onLocalRun} onSample={p.onSample} onClear={loaded.trace || loaded.alerts || loaded.repro ? p.onClear : null} />
        </div>
        {p.origin ? <OriginLine origin={p.origin} model={model} loaded={loaded} /> : null}
      </section>

      {!model || !counts ? (
        <EmptyState onLocalRun={p.onLocalRun} onSample={p.onSample} fileButtons={fileButtons} />
      ) : (
        <>
          <ActionBanner model={model} onQueue={p.onQueue} onStatus={p.onStatus} />

          <SummaryCard model={model} onStatus={p.onStatus} onAudit={p.onAudit} />

          <section className="flex flex-col gap-4">
            <div className="flex flex-wrap items-baseline gap-3">
              <h2 className="text-lg font-semibold">Alerts</h2>
              <span className="text-sm text-muted-foreground">{counts.alertsTotal} alerts · click a tile to list them</span>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              {DISPLAY_STATUSES(model.verified).map((s) => {
                const active = status === s
                const action = s === 'NEEDS_REVIEW' && counts.alerts[s] > 0
                return (
                  <button
                    key={s}
                    type="button"
                    onClick={() => p.onStatus(active ? null : s)}
                    aria-pressed={active}
                    className={cn(
                      'relative flex cursor-pointer flex-col gap-2 rounded-xl border border-l-4 bg-card px-6 py-5 text-left shadow-sm transition-shadow hover:shadow-md',
                      STATUS_TONE[s].border,
                      action && 'halo border-amber-300',
                      active && 'ring-2 ring-foreground/25',
                    )}
                  >
                    {action ? <ActionPill className="absolute top-3 right-3">Analyst action</ActionPill> : null}
                    <span className="text-sm font-medium">{STATUS_LABELS[s].label}</span>
                    <span className="text-4xl font-semibold tabular-nums">{counts.alerts[s]}</span>
                    <span className="text-xs text-muted-foreground">{STATUS_LABELS[s].sub}</span>
                    {s === 'NOT_VERIFIED' ? <span className="text-xs font-medium text-slate-700">{notVerifiedNote(model.badAlertLines)}</span> : null}
                  </button>
                )
              })}
            </div>
            <Warnings model={model} />
            {status ? <AlertList status={status} alerts={listed} onAlert={p.onAlert} unavailable={status === 'CLEARED' && !model.verified ? notVerifiedNote(model.badAlertLines) : null} /> : null}
          </section>

          <Breakdowns model={model} onAudit={p.onAudit} />

          {p.repro ? <ReproCard report={p.repro.report} metrics={p.repro.metrics} onHit={p.onReproHit} /> : null}
        </>
      )}

      <details className="group rounded-xl border bg-card px-5 py-3 text-sm" open={!model}>
        <summary className="cursor-pointer list-none font-medium text-muted-foreground select-none group-open:mb-3">
          <span className="mr-1 inline-block transition-transform group-open:rotate-90">›</span> Data sources and checks
        </summary>
        <div className="flex flex-col gap-3">
          <p className="text-xs text-muted-foreground">
            Files are read in your browser and never uploaded. <b>Output</b> is the submission file (<span className="font-mono">output/dev.jsonl</span>):
            decisions only. <b>Trace</b> (<span className="font-mono">trace.jsonl</span>) adds the comparison behind each decision. <b>Alerts</b> (
            <span className="font-mono">dev/alerts.jsonl</span>) proves no hit is missing, which is what lets an alert show as Cleared.
          </p>
          <div className="flex flex-wrap gap-2">{fileButtons}</div>
          <Sources loaded={loaded} />
          {model?.crossCheck && model.crossCheck.problems.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              Cross-check: the pipeline’s alert summaries ({model.crossCheck.checked}
              {model.summarySource === 'trace' ? ', from the trace' : ', from the summaries file'}) agree with this view.
            </p>
          ) : null}
        </div>
      </details>
    </div>
  )
}

function ActionPill({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-900', className)}>
      <span className="relative inline-flex size-2">
        <span className="absolute inline-flex size-full rounded-full bg-amber-500 opacity-60 motion-safe:animate-ping" />
        <span className="relative inline-flex size-2 rounded-full bg-amber-500" />
      </span>
      {children}
    </span>
  )
}

function DataSwitch({ origin, onLocalRun, onSample, onClear }: { origin: Origin; onLocalRun: (() => void) | null; onSample: () => void; onClear: (() => void) | null }) {
  const seg = (active: boolean) =>
    cn('cursor-pointer rounded-md px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50', active ? 'bg-card shadow-sm' : 'text-muted-foreground hover:text-foreground')
  return (
    <div className="flex items-center gap-2">
      <div className="inline-flex rounded-lg bg-muted p-1" role="group" aria-label="Data shown">
        <button
          type="button"
          className={seg(origin?.kind === 'local')}
          onClick={onLocalRun ?? undefined}
          disabled={!onLocalRun}
          title={onLocalRun ? 'This repository’s own run: output/dev.jsonl (or working/trace.jsonl) and dev/alerts.jsonl' : 'Only with the dev server (npm run dev). In the built page, open output/dev.jsonl with “Open output or trace…”'}
        >
          Our dev run
        </button>
        <button type="button" className={seg(origin?.kind === 'sample')} onClick={onSample}>
          Synthetic sample
        </button>
      </div>
      {onClear ? (
        <Button variant="ghost" size="sm" onClick={onClear}>
          Clear
        </Button>
      ) : null}
    </div>
  )
}

function OriginLine({ origin, model, loaded }: { origin: NonNullable<Origin>; model: Model | null; loaded: Loaded }) {
  const outputOnly = loaded.trace?.result.format === 'output'
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <Badge variant="outline" className={cn(origin.kind === 'sample' ? 'border-violet-300 text-violet-800' : 'border-sky-300 text-sky-800')}>
        {origin.kind === 'sample' ? 'Synthetic data' : origin.kind === 'local' ? 'Our dev run' : 'Opened files'}
      </Badge>
      <span className="font-mono">{origin.label}</span>
      {outputOnly ? <span>· decisions only; open the trace to see each comparison</span> : null}
      {model && !model.verified ? <span>· no alerts file, so no alert can show as Cleared</span> : null}
    </div>
  )
}

function EmptyState({ onLocalRun, onSample, fileButtons }: { onLocalRun: (() => void) | null; onSample: () => void; fileButtons: ReactNode }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-5 py-12 text-center">
        <div>
          <div className="text-base font-semibold">Nothing loaded yet</div>
          <p className="mt-1 max-w-lg text-sm text-muted-foreground">
            Look at our own run on the development set, or at the synthetic sample. You can also open <span className="font-mono">output/dev.jsonl</span> from
            disk; add <span className="font-mono">dev/alerts.jsonl</span> so alerts can show as Cleared.
          </p>
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          {onLocalRun ? <Button onClick={onLocalRun}>Our dev run</Button> : null}
          <Button variant={onLocalRun ? 'outline' : 'default'} onClick={onSample}>
            Synthetic sample
          </Button>
          {fileButtons}
        </div>
      </CardContent>
    </Card>
  )
}

/** The one thing an analyst should do next, with a pulsing halo. */
function ActionBanner({ model, onQueue, onStatus }: { model: Model; onQueue: () => void; onStatus: (s: RollupStatus) => void }) {
  const c = model.counts
  const review = c.hitsByDecision.REVIEW + c.hitsUndecided
  const same = c.hitsByDecision.SAME_ENTITY
  if (review === 0 && same === 0) {
    return <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-5 py-4 text-sm text-emerald-900">Nothing needs a person: every alert is cleared.</div>
  }
  return (
    <div className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-amber-300 bg-amber-50 px-5 py-4">
      <div className="flex items-start gap-3">
        <ActionPill className="mt-0.5">Action</ActionPill>
        <div className="text-sm text-amber-950">
          <div className="font-semibold">
            {review} hit{review === 1 ? '' : 's'} on {c.alerts.NEEDS_REVIEW} alert{c.alerts.NEEDS_REVIEW === 1 ? '' : 's'} need an analyst decision
          </div>
          <div className="text-amber-900/80">
            The evidence could not settle them, so they were not cleared. {same > 0 ? `${same} confirmed match${same === 1 ? '' : 'es'} on ${c.alerts.ESCALATED} alert${c.alerts.ESCALATED === 1 ? '' : 's'} go${same === 1 ? 'es' : ''} to the compliance team.` : ''}
          </div>
        </div>
      </div>
      <div className="flex gap-2">
        {same > 0 ? (
          <Button variant="outline" size="sm" className="border-red-200 bg-white text-red-800 hover:bg-red-50" onClick={() => onStatus('ESCALATED')}>
            See escalations
          </Button>
        ) : null}
        <Button size="sm" className="halo bg-amber-600 text-white hover:bg-amber-700" onClick={onQueue}>
          Open analyst queue →
        </Button>
      </div>
    </div>
  )
}

/** Donut of alert outcomes, stacked bar of hit decisions, and the headline numbers. */
function SummaryCard({ model, onStatus, onAudit }: { model: Model; onStatus: (s: RollupStatus) => void; onAudit: (f: AuditFilters) => void }) {
  const c = model.counts
  const statuses = DISPLAY_STATUSES(model.verified)
  const alertSegs: Segment[] = statuses.map((s) => ({
    key: s,
    label: STATUS_LABELS[s].label,
    value: c.alerts[s],
    color: STATUS_TONE[s].bar,
    stroke: STATUS_TONE[s].stroke,
    onClick: () => onStatus(s),
    halo: s === 'NEEDS_REVIEW',
  }))
  const hitSegs: Segment[] = [
    ...DISPLAY_DECISIONS.map((d) => ({
      key: d,
      label: DECISION_WORDS[d],
      value: c.hitsByDecision[d],
      color: DECISION_TONE[d].dot,
      onClick: () => onAudit({ ...NO_FILTERS, verdict: d }),
      halo: d === 'REVIEW',
    })),
    ...(c.hitsUndecided > 0 ? [{ key: 'none', label: 'No decision', value: c.hitsUndecided, color: 'bg-slate-400', onClick: () => onAudit({ ...NO_FILTERS, verdict: 'none' as const }) }] : []),
  ]
  const closed = model.verified ? c.alerts.CLEARED : c.alerts.NOT_VERIFIED
  const totalHits = c.hitsDecided + c.hitsUndecided
  const toPerson = c.hitsByDecision.REVIEW + c.hitsUndecided + c.hitsByDecision.SAME_ENTITY
  const kpi = (label: string, value: string, sub: string, tone?: string) => (
    <div className="flex flex-col gap-0.5 rounded-lg bg-muted/50 px-4 py-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={cn('text-2xl font-semibold tabular-nums', tone)}>{value}</span>
      <span className="text-[11px] text-muted-foreground">{sub}</span>
    </div>
  )
  const share = (n: number, d: number) => (d ? `${Math.round((n / d) * 100)}%` : '—')
  return (
    <Card className="gap-5">
      <CardHeader>
        <CardTitle>Summary</CardTitle>
        <CardDescription>An alert closes only when every one of its hits is a different entity.</CardDescription>
      </CardHeader>
      <CardContent className="grid items-center gap-8 lg:grid-cols-[auto_minmax(0,1fr)]">
        <div className="flex items-center gap-5">
          <Donut segments={alertSegs} center={String(c.alertsTotal)} sub="alerts" />
          <ul className="flex flex-col gap-1.5 text-sm">
            {alertSegs.map((s) => (
              <li key={s.key}>
                <button type="button" onClick={s.onClick} className={cn('inline-flex cursor-pointer items-center gap-2 rounded-md px-1.5 py-0.5 hover:bg-muted', s.halo && s.value > 0 && 'halo ring-1 ring-amber-400')}>
                  <span className={cn('inline-block size-2.5 rounded-sm', s.color)} />
                  <span>{s.label}</span>
                  <span className="font-semibold tabular-nums">{s.value}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex flex-col gap-5">
          <StackedBar title="Hits by decision" segments={hitSegs} unit="hits" />
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {kpi('Alerts closed automatically', share(closed, c.alertsTotal), `${closed} of ${c.alertsTotal}${model.verified ? '' : ' (not verified)'}`, 'text-emerald-700')}
            {kpi('Hits cleared', share(c.hitsByDecision.DIFFERENT_ENTITY, totalHits), `${c.hitsByDecision.DIFFERENT_ENTITY} of ${totalHits}`, 'text-emerald-700')}
            {kpi('Hits needing a person', String(toPerson), `${c.hitsByDecision.REVIEW + c.hitsUndecided} review · ${c.hitsByDecision.SAME_ENTITY} compliance`, 'text-amber-700')}
            {kpi('Confirmed matches', String(c.hitsByDecision.SAME_ENTITY), `on ${c.alerts.ESCALATED} alerts`, 'text-red-700')}
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function Warnings({ model }: { model: Model }) {
  const counts = model.counts
  return (
    <>
      {model.badAlertLines > 0 ? (
        <p className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm font-medium text-red-800">
          {model.badAlertLines} line{model.badAlertLines === 1 ? '' : 's'} in the alerts file could not be read, so an alert may be missing. Clears are
          withheld (shown as Not verified) until the file is fixed.
        </p>
      ) : null}
      {model.conflictingAlerts.length > 0 ? (
        <p className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
          Conflicting lines in the alerts file: {model.conflictingAlerts.map((c) => `${c.alert_id} (lines ${c.lines.join(', ')})`).join('; ')}. Their hit lists
          were combined and these alerts can’t be cleared.
        </p>
      ) : null}
      {counts.alertsWithUndecided > 0 ? (
        <p className="text-sm text-amber-700">
          {counts.alertsWithUndecided} alert{counts.alertsWithUndecided === 1 ? '' : 's'} with {counts.hitsUndecided} hit{counts.hitsUndecided === 1 ? '' : 's'} that{' '}
          {counts.hitsUndecided === 1 ? 'has' : 'have'} no decision; never cleared.
        </p>
      ) : null}
      {counts.hitsMisfiled > 0 ? (
        <p className="text-sm text-amber-700">
          {counts.hitsMisfiled} hit{counts.hitsMisfiled === 1 ? ' is' : 's are'} filed under a different alert in the trace, so they count only as “hit has no
          decision”.
        </p>
      ) : null}
      {counts.hitsUnlisted > 0 ? <p className="text-sm text-amber-700">{counts.hitsUnlisted} hit{counts.hitsUnlisted === 1 ? '' : 's'} in the trace not listed on any alert.</p> : null}
      {model.crossCheck && model.crossCheck.problems.length > 0 ? (
        <div className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
          <div className="font-medium">The pipeline’s alert summaries disagree with this view:</div>
          <ul className="mt-1 list-disc pl-5">
            {model.crossCheck.problems.map((x) => (
              <li key={`${x.kind}-${x.alert_id}`}>{crossCheckText(x)}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </>
  )
}

const bucket = (n: number, top: number) => (n >= top ? `${top}+` : String(n))

/** Breakdowns the brief asks about: reason codes, customer resolution, evidence cited, alert size, and how firm the clears are. */
function Breakdowns({ model, onAudit }: { model: Model; onAudit: (f: AuditFilters) => void }) {
  const c = model.counts
  const hits = [...model.hitsById.values()].filter((h) => !h.not_decided)
  const reasonRows: BarRow[] = DISPLAY_DECISIONS.flatMap((d) =>
    c.hitsByReason
      .filter((r) => r.decision === d)
      .map((r) => ({
        key: `${d}|${r.reason_code}`,
        label: r.reason_code,
        sub: reasonLabel(r.reason_code),
        value: r.count,
        color: DECISION_TONE[d].dot,
        onClick: r.count ? () => onAudit({ ...NO_FILTERS, verdict: d, code: r.reason_code }) : undefined,
      })),
  )

  const resolved = { one: 0, ambiguous: 0, none: 0 }
  for (const h of hits) {
    const id = h.verdict.customer_record_id
    if (!id) resolved.none++
    else if (id === 'AMBIGUOUS') resolved.ambiguous++
    else resolved.one++
  }
  const resolutionRows: BarRow[] = [
    { key: 'one', label: 'One customer', sub: 'customer_record_id is a CUS- record', value: resolved.one, color: 'bg-sky-600' },
    { key: 'amb', label: 'AMBIGUOUS', sub: 'more than one person fits the alert', value: resolved.ambiguous, color: 'bg-violet-500' },
    { key: 'none', label: 'Not found', sub: 'no customer record fits (null)', value: resolved.none, color: 'bg-slate-400' },
  ]

  const evidence = new Map<string, Record<Decision, number>>()
  const evKeys = ['0', '1', '2', '3+']
  for (const k of evKeys) evidence.set(k, { SAME_ENTITY: 0, REVIEW: 0, DIFFERENT_ENTITY: 0 })
  for (const h of hits) evidence.get(bucket(h.verdict.evidence.length, 3))![h.verdict.decision]++

  const sizes = new Map<string, number>()
  for (const s of model.summaries) {
    const k = bucket(s.hits.length, 4)
    sizes.set(k, (sizes.get(k) ?? 0) + 1)
  }
  const sizeRows: BarRow[] = ['1', '2', '3', '4+'].map((k) => ({ key: k, label: `${k} hit${k === '1' ? '' : 's'}`, value: sizes.get(k) ?? 0, color: 'bg-slate-500' }))

  const clears = hits.filter((h) => h.verdict.decision === 'DIFFERENT_ENTITY')
  const frag = new Map<string, number>()
  for (const h of clears) {
    const f = h.badges?.fragility ?? 'unknown'
    frag.set(f, (frag.get(f) ?? 0) + 1)
  }
  const hasFragility = clears.some((h) => h.badges?.fragility)
  const FRAG: { key: string; sub: string; color: string }[] = [
    { key: 'solid', sub: 'the deciding fact rests on more than one record', color: 'bg-emerald-600' },
    { key: 'thin', sub: 'the deciding fact rests on one record', color: 'bg-amber-500' },
    { key: 'borderline', sub: 'near the line: dates just over a year apart, or a fuzzy name', color: 'bg-red-500' },
    { key: 'unknown', sub: 'not in the file', color: 'bg-slate-400' },
  ]
  const fragRows: BarRow[] = FRAG.filter((f) => f.key !== 'unknown' || frag.get('unknown')).map((f) => ({
    key: f.key,
    label: f.key,
    sub: f.sub,
    value: frag.get(f.key) ?? 0,
    color: f.color,
    onClick: frag.get(f.key) ? () => onAudit({ ...NO_FILTERS, verdict: 'DIFFERENT_ENTITY', fragility: f.key }) : undefined,
  }))

  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-lg font-semibold">Breakdowns</h2>
      <div className="grid items-start gap-6 lg:grid-cols-5">
        <Card className="gap-4 lg:col-span-3">
          <CardHeader>
            <CardTitle>Hits by reason code</CardTitle>
            <CardDescription>Every POLICY reason code, grouped by decision. Click a bar to audit those hits.</CardDescription>
          </CardHeader>
          <CardContent>
            <BarList rows={reasonRows} />
          </CardContent>
        </Card>
        <div className="flex flex-col gap-6 lg:col-span-2">
          <Card className="gap-4">
            <CardHeader>
              <CardTitle>Customer record resolved</CardTitle>
              <CardDescription>Which customer each hit was compared with.</CardDescription>
            </CardHeader>
            <CardContent>
              <BarList rows={resolutionRows} />
            </CardContent>
          </Card>
          {hasFragility ? (
            <Card className="gap-4">
              <CardHeader>
                <CardTitle>How firm are the clears?</CardTitle>
                <CardDescription>{clears.length} hits cleared. A wrong clear costs 20× a review, so thin and borderline clears are the ones to spot-check.</CardDescription>
              </CardHeader>
              <CardContent>
                <BarList rows={fragRows} />
              </CardContent>
            </Card>
          ) : null}
          <Card className="gap-4">
            <CardHeader>
              <CardTitle>Alerts by number of hits</CardTitle>
              <CardDescription>An alert with more hits needs every one of them cleared to close.</CardDescription>
            </CardHeader>
            <CardContent>
              <BarList rows={sizeRows} />
            </CardContent>
          </Card>
        </div>
        <Card className="gap-4 lg:col-span-5">
          <CardHeader>
            <CardTitle>Evidence cited per hit</CardTitle>
            <CardDescription>The brief asks for the decisive records only. A clear or a confirmation with no evidence is worth a look.</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Records cited</TableHead>
                  {DISPLAY_DECISIONS.map((d) => (
                    <TableHead key={d} className="text-right">
                      <span className="inline-flex items-center gap-1.5 font-mono text-[11px]">
                        <span className={cn('inline-block size-2 rounded-full', DECISION_TONE[d].dot)} />
                        {d}
                      </span>
                    </TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {evKeys.map((k) => (
                  <TableRow key={k}>
                    <TableCell className="py-2 tabular-nums">{k}</TableCell>
                    {DISPLAY_DECISIONS.map((d) => {
                      const v = evidence.get(k)![d]
                      const odd = k === '0' && d !== 'REVIEW' && v > 0
                      return (
                        <TableCell key={d} className={cn('py-2 text-right tabular-nums', v === 0 && 'text-muted-foreground', odd && 'font-semibold text-red-700')}>
                          {v}
                        </TableCell>
                      )
                    })}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </section>
  )
}

/** One line under the Not verified tile; the same text whatever the hit lists came from. */
function notVerifiedNote(badLines: number): string {
  return badLines > 0
    ? 'The alerts file has unreadable lines, so nothing can be shown as Cleared'
    : 'No original alerts file loaded, so nothing can be shown as Cleared'
}

function AlertList({
  status,
  alerts,
  onAlert,
  unavailable,
}: {
  status: RollupStatus
  alerts: AlertSummary[]
  onAlert: (id: string) => void
  unavailable: string | null
}) {
  if (unavailable) {
    return (
      <Card className="gap-3 py-5">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <StatusBadge status={status} />
            <span className="font-normal text-muted-foreground">Not available until the alerts file is loaded</span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">{unavailable}.</p>
        </CardContent>
      </Card>
    )
  }
  return (
    <Card className="gap-3 py-5">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <StatusBadge status={status} />
          <span className="font-normal text-muted-foreground">
            {alerts.length} alert{alerts.length === 1 ? '' : 's'}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent>
        {alerts.length === 0 ? (
          <p className="text-sm text-muted-foreground">None.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Alert</TableHead>
                <TableHead>Hits</TableHead>
                <TableHead>Blocking or deciding hits</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {alerts.map((a) => {
                const shown = a.alert_status === 'ESCALATED' ? a.hits.filter((h) => h.decision === 'SAME_ENTITY') : a.blocking_hit_ids.length ? a.hits.filter((h) => a.blocking_hit_ids.includes(h.hit_id)) : a.hits
                return (
                  <TableRow key={a.alert_id} className="cursor-pointer hover:bg-muted/50" onClick={() => onAlert(a.alert_id)}>
                    <TableCell className="py-3">
                      <button type="button" className="cursor-pointer font-mono text-sm whitespace-nowrap underline-offset-4 hover:underline" onClick={() => onAlert(a.alert_id)}>
                        {a.alert_id}
                      </button>
                    </TableCell>
                    <TableCell className="tabular-nums">{a.hits.length}</TableCell>
                    <TableCell className="whitespace-normal">
                      <div className="flex flex-col gap-1">
                        {shown.map((h) => (
                          <span key={h.hit_id} className="flex items-baseline gap-2">
                            <span className="font-mono text-xs whitespace-nowrap">{h.hit_id}</span>
                            <ReasonCode code={h.reason_code ?? HIT_NOT_DECIDED} />
                          </span>
                        ))}
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}

function traceSummary(r: TraceParseResult): string {
  const n = r.summaries?.summaries.length ?? 0
  const other = r.skipped - (r.summaries?.lines ?? 0)
  return [
    `${r.hits.length} hits`,
    n ? `${n} pipeline alert summaries (cross-check only)` : 'no alert summaries',
    other > 0 ? `${other} other non-hit records skipped` : '',
  ]
    .filter(Boolean)
    .join(', ')
}

function Sources({ loaded }: { loaded: Loaded }) {
  const { trace, alerts, summaries, repro } = loaded
  if (!trace && !alerts && !summaries && !repro) return null
  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-card px-4 py-3 text-sm">
      <SourceLine
        kind="Trace"
        name={trace?.name ?? 'not loaded'}
        summary={trace ? traceSummary(trace.result) : ''}
        issues={trace ? [...trace.result.issues, ...(trace.result.summaries?.issues ?? [])] : []}
      />
      <SourceLine
        kind="Alerts"
        name={alerts?.name ?? 'not loaded'}
        summary={alerts ? `${alerts.result.alerts.length} alerts` : 'without alerts.jsonl no alert can show as cleared'}
        issues={alerts?.result.issues ?? []}
      />
      {summaries ? (
        <SourceLine
          kind="Summaries"
          name={summaries.name}
          summary={`${summaries.result.summaries.length} pipeline alert summaries (cross-check only)`}
          issues={summaries === alerts ? [] : summaries.result.issues}
        />
      ) : null}
      {repro ? (
        <SourceLine
          kind="Repro"
          name={repro.name}
          summary={repro.result.report ? `${repro.result.report.n_runs} runs, ${repro.result.report.hits.length} hits` : 'could not be read'}
          issues={repro.result.issues}
        />
      ) : null}
    </div>
  )
}

const MAX_ISSUES = 20

function SourceLine({ kind, name, summary, issues }: { kind: string; name: string; summary: string; issues: ParseIssue[] }) {
  const errors = issues.filter((i) => i.severity !== 'info').length
  const notes = issues.length - errors
  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="w-20 text-muted-foreground">{kind}</span>
        <span className="font-mono text-xs">{name}</span>
        {summary ? <span className="text-muted-foreground">{summary}</span> : null}
        {errors > 0 ? (
          <Badge variant="outline" className="border-red-300 text-red-700">
            {errors} problem{errors === 1 ? '' : 's'}
          </Badge>
        ) : null}
        {notes > 0 ? (
          <Badge variant="outline" className="text-muted-foreground">
            {notes} note{notes === 1 ? '' : 's'}
          </Badge>
        ) : null}
      </div>
      {issues.length > 0 ? (
        <ul className="mt-2 ml-23 list-disc space-y-0.5 pl-4 text-xs">
          {issues.slice(0, MAX_ISSUES).map((i) => (
            <li key={`${i.line}-${i.message}`} className={i.severity === 'info' ? 'text-muted-foreground' : 'text-red-700'}>
              line {i.line}: {i.message}
            </li>
          ))}
          {issues.length > MAX_ISSUES ? <li>…and {issues.length - MAX_ISSUES} more</li> : null}
        </ul>
      ) : null}
    </div>
  )
}
