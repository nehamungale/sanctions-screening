import type { AlertsParseResult, TraceParseResult } from './parse.ts'
import { reproMetrics, type ReproMetrics, type ReproParseResult } from './repro.ts'
import {
  alertsFromHits,
  crossCheckSummaries,
  overviewCounts,
  rollUpAlerts,
  type CrossCheckProblem,
  type OverviewCounts,
} from './rollup.ts'
import type { AlertSummary, TraceHit } from './types.ts'

export interface LoadedTrace {
  name: string
  result: TraceParseResult
}
/** An alerts-style file. The same parser serves alerts.jsonl and a (legacy) separate summaries file. */
export interface LoadedAlerts {
  name: string
  result: AlertsParseResult
}
export interface LoadedRepro {
  name: string
  result: ReproParseResult
}

export interface Loaded {
  trace: LoadedTrace | null
  /** alerts.jsonl: the only source that makes an alert "Cleared". */
  alerts: LoadedAlerts | null
  /** Legacy separate summaries file (alerts.trace.jsonl). Optional: Stage 4 appends its summaries to trace.jsonl. Cross-check only. */
  summaries: LoadedAlerts | null
  repro: LoadedRepro | null
}

export const EMPTY: Loaded = { trace: null, alerts: null, summaries: null, repro: null }

export interface Model {
  verified: boolean
  /** Where the alert list came from. */
  alertSource: 'alerts' | 'summaries' | 'trace'
  /** Where the pipeline's alert summaries (cross-check only) came from: lines inside trace.jsonl or a separate file. */
  summarySource: 'trace' | 'file' | null
  /** Unreadable lines in alerts.jsonl. While above 0, clears are withheld (shown as Not verified). */
  badAlertLines: number
  /** Alerts whose alerts.jsonl lines conflict (hit lists combined; never cleared). */
  conflictingAlerts: { alert_id: string; lines: number[] }[]
  summaries: AlertSummary[]
  summariesById: Map<string, AlertSummary>
  hitsById: Map<string, TraceHit>
  counts: OverviewCounts
  crossCheck: { checked: number; problems: CrossCheckProblem[] } | null
}

export function buildModel(l: Loaded): Model | null {
  if (!l.trace) return null
  const hits = l.trace.result.hits
  const alertRefs = l.alerts?.result.alerts ?? []
  // A separately loaded summaries file (legacy) takes the place of the summary lines inside the trace.
  const fileSummaries = l.summaries?.result.summaries ?? []
  const traceSummaries = l.trace.result.summaries?.summaries ?? []
  const pipeline = fileSummaries.length ? fileSummaries : traceSummaries
  const summarySource = fileSummaries.length ? 'file' : traceSummaries.length ? 'trace' : null
  // Only alerts.jsonl verifies. Unreadable alert lines withhold every clear (an alert could be missing).
  const badAlertLines = l.alerts?.result.bad_lines ?? 0
  const verified = alertRefs.length > 0 && badAlertLines === 0
  const alertSource = alertRefs.length ? 'alerts' : pipeline.length ? 'summaries' : 'trace'
  const refs = alertRefs.length ? alertRefs : pipeline.length ? pipeline.map(({ alert_id, hit_ids, conflicting_lines }) => ({ alert_id, hit_ids, ...(conflicting_lines ? { conflicting_lines } : {}) })) : alertsFromHits(hits)
  const summaries = rollUpAlerts(refs, hits, { alertsVerified: verified, rejected: l.trace.result.rejected })
  return {
    verified,
    alertSource,
    summarySource,
    badAlertLines,
    conflictingAlerts: summaries.filter((s) => s.conflicting_lines).map((s) => ({ alert_id: s.alert_id, lines: s.conflicting_lines! })),
    summaries,
    summariesById: new Map(summaries.map((s) => [s.alert_id, s])),
    hitsById: new Map(hits.map((h) => [h.hit_id, h])),
    counts: overviewCounts(summaries, hits, verified),
    crossCheck: pipeline.length ? { checked: pipeline.length, problems: crossCheckSummaries(summaries, pipeline, verified) } : null,
  }
}

export function buildRepro(r: LoadedRepro | null): { report: NonNullable<ReproParseResult['report']>; metrics: ReproMetrics } | null {
  const report = r?.result.report
  return report ? { report, metrics: reproMetrics(report) } : null
}
