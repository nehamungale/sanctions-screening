import { useRef, type ChangeEvent } from 'react'

import { DecisionDot, ReasonCode, StatusBadge, STATUS_TONE } from '@/components/verdict'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { LoadedAlerts, LoadedTrace, Model } from '@/lib/data'
import { STATUS_LABELS } from '@/lib/labels'
import { parseAlerts, parseTraceJsonl } from '@/lib/parse'
import { DECISIONS, HIT_NOT_DECIDED, type RollupStatus } from '@/lib/policy'
import type { AlertSummary, ParseIssue } from '@/lib/types'
import { cn } from '@/lib/utils'

interface Props {
  trace: LoadedTrace | null
  alerts: LoadedAlerts | null
  model: Model | null
  status: RollupStatus | null
  onTrace: (t: LoadedTrace) => void
  onAlerts: (a: LoadedAlerts) => void
  onSample: () => void
  onClear: () => void
  onStatus: (s: RollupStatus | null) => void
  onAlert: (alertId: string) => void
}

export function Overview(p: Props) {
  const { trace, alerts, model, status } = p
  const traceInput = useRef<HTMLInputElement>(null)
  const alertsInput = useRef<HTMLInputElement>(null)

  const pick = async (e: ChangeEvent<HTMLInputElement>, kind: 'trace' | 'alerts') => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const text = await file.text()
    if (kind === 'trace') p.onTrace({ name: file.name, result: parseTraceJsonl(text) })
    else p.onAlerts({ name: file.name, result: parseAlerts(text) })
  }

  const counts = model?.counts
  // Without a verified alert list, "Not verified" takes the place of "Cleared".
  const tiles: RollupStatus[] = model?.verified === false ? ['NOT_VERIFIED', 'ESCALATED', 'NEEDS_REVIEW'] : ['CLEARED', 'ESCALATED', 'NEEDS_REVIEW']
  const listed = model && status ? model.summaries.filter((s) => s.alert_status === status) : []

  return (
    <div className="flex flex-col gap-10">
      <section className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Load a trace (trace.jsonl) and the alert list (alerts.jsonl or alerts.trace.jsonl) to check for missing hits.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => traceInput.current?.click()}>
              Open trace…
            </Button>
            <Button variant="outline" onClick={() => alertsInput.current?.click()}>
              Open alerts…
            </Button>
            <Button onClick={p.onSample}>Load sample</Button>
            {trace || alerts ? (
              <Button variant="ghost" onClick={p.onClear}>
                Clear
              </Button>
            ) : null}
          </div>
          <input ref={traceInput} type="file" accept=".jsonl,.json,.txt,application/json" className="hidden" onChange={(e) => void pick(e, 'trace')} />
          <input ref={alertsInput} type="file" accept=".jsonl,.json,.txt,application/json" className="hidden" onChange={(e) => void pick(e, 'alerts')} />
        </div>
        <Sources trace={trace} alerts={alerts} />
      </section>

      {!model || !counts ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">No trace loaded. Use “Open trace…” or “Load sample”.</CardContent>
        </Card>
      ) : (
        <>
          <section className="flex flex-col gap-4">
            <div className="flex flex-wrap items-baseline gap-3">
              <h2 className="text-lg font-semibold">Alerts</h2>
              <span className="text-sm text-muted-foreground">
                {counts.alertsTotal} alerts · click a tile to list them
                {model.verified ? '' : ' · grouped from the trace, no alerts file loaded'}
              </span>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              {tiles.map((s) => {
                const active = status === s
                return (
                  <button
                    key={s}
                    type="button"
                    onClick={() => p.onStatus(active ? null : s)}
                    aria-pressed={active}
                    className={cn(
                      'flex cursor-pointer flex-col gap-2 rounded-xl border border-l-4 bg-card px-6 py-5 text-left shadow-sm transition-shadow hover:shadow-md',
                      STATUS_TONE[s].border,
                      active && 'ring-2 ring-foreground/25',
                    )}
                  >
                    <span className="text-sm font-medium">{STATUS_LABELS[s].label}</span>
                    <span className="text-4xl font-semibold tabular-nums">{counts.alerts[s]}</span>
                    <span className="text-xs text-muted-foreground">{STATUS_LABELS[s].sub}</span>
                  </button>
                )
              })}
            </div>
            {counts.alertsWithUndecided > 0 ? (
              <p className="text-sm text-amber-700">
                {counts.alertsWithUndecided} alert{counts.alertsWithUndecided === 1 ? '' : 's'} with {counts.hitsUndecided} hit
                {counts.hitsUndecided === 1 ? '' : 's'} that {counts.hitsUndecided === 1 ? 'has' : 'have'} no decision; never cleared.
              </p>
            ) : null}
            {counts.pipelineDisagreements.length > 0 ? (
              <p className="text-sm text-red-700">
                The pipeline’s alert summary differs from this roll-up for: {counts.pipelineDisagreements.join(', ')}.
              </p>
            ) : null}
            {status ? <AlertList status={status} alerts={listed} onAlert={p.onAlert} /> : null}
          </section>

          <div className="grid items-start gap-6 lg:grid-cols-5">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle>Hits by decision</CardTitle>
                <CardDescription>{counts.hitsDecided} decided hits in the trace</CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Decision</TableHead>
                      <TableHead className="text-right">Hits</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {DECISIONS.map((d) => (
                      <TableRow key={d}>
                        <TableCell className="py-3">
                          <span className="inline-flex items-center gap-2 font-mono text-xs">
                            <DecisionDot decision={d} />
                            {d}
                          </span>
                        </TableCell>
                        <TableCell className="text-right tabular-nums">{counts.hitsByDecision[d]}</TableCell>
                      </TableRow>
                    ))}
                    <TableRow className="text-muted-foreground">
                      <TableCell className="py-3">
                        <span className="inline-flex items-center gap-2">
                          <DecisionDot decision={null} />
                          <ReasonCode code={HIT_NOT_DECIDED} />
                        </span>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{model.verified ? counts.hitsUndecided : '—'}</TableCell>
                    </TableRow>
                  </TableBody>
                </Table>
                {counts.hitsUnlisted > 0 ? (
                  <p className="mt-3 text-xs text-amber-700">
                    {counts.hitsUnlisted} hit{counts.hitsUnlisted === 1 ? '' : 's'} in the trace not listed on any alert.
                  </p>
                ) : null}
              </CardContent>
            </Card>

            <Card className="lg:col-span-3">
              <CardHeader>
                <CardTitle>Hits by reason code</CardTitle>
                <CardDescription>All policy codes, in POLICY order</CardDescription>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Reason code</TableHead>
                      <TableHead className="text-right">Hits</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {counts.hitsByReason.map((r) => (
                      <TableRow key={`${r.decision}|${r.reason_code}`} className={r.count === 0 ? 'text-muted-foreground' : ''}>
                        <TableCell className="py-2.5 whitespace-normal">
                          <span className="flex items-start gap-2">
                            <span className="mt-1">
                              <DecisionDot decision={r.decision} muted={r.count === 0} />
                            </span>
                            <ReasonCode code={r.reason_code} />
                          </span>
                        </TableCell>
                        <TableCell className="text-right align-top tabular-nums">{r.count}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}

function AlertList({ status, alerts, onAlert }: { status: RollupStatus; alerts: AlertSummary[]; onAlert: (id: string) => void }) {
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
                      <button type="button" className="cursor-pointer font-mono text-sm underline-offset-4 hover:underline" onClick={() => onAlert(a.alert_id)}>
                        {a.alert_id}
                      </button>
                    </TableCell>
                    <TableCell className="tabular-nums">{a.hits.length}</TableCell>
                    <TableCell className="whitespace-normal">
                      <div className="flex flex-col gap-1">
                        {shown.map((h) => (
                          <span key={h.hit_id} className="flex items-baseline gap-2">
                            <span className="font-mono text-xs">{h.hit_id}</span>
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

function Sources({ trace, alerts }: { trace: LoadedTrace | null; alerts: LoadedAlerts | null }) {
  if (!trace && !alerts) return null
  const alertsKind = alerts?.result.kind === 'summaries' ? 'alert summaries' : alerts?.result.kind === 'mixed' ? 'alerts + summaries' : 'alerts'
  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-card px-4 py-3 text-sm">
      {trace ? (
        <SourceLine
          kind="Trace"
          name={trace.name}
          summary={`${trace.result.hits.length} hits${trace.result.skipped ? `, ${trace.result.skipped} non-hit records skipped` : ''}`}
          issues={trace.result.issues}
        />
      ) : (
        <SourceLine kind="Trace" name="not loaded" summary="" issues={[]} />
      )}
      {alerts ? (
        <SourceLine kind="Alerts" name={alerts.name} summary={`${alerts.result.alerts.length} ${alertsKind}`} issues={alerts.result.issues} />
      ) : (
        <SourceLine kind="Alerts" name="not loaded" summary="missing hits cannot be detected, so no alert shows as cleared" issues={[]} />
      )}
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
        <span className="w-14 text-muted-foreground">{kind}</span>
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
        <ul className="mt-2 ml-17 list-disc space-y-0.5 pl-4 text-xs">
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
