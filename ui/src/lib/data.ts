import sampleAlertsText from '../../fixtures/sample.alerts.jsonl?raw'
import sampleTraceText from '../../fixtures/sample.trace.jsonl?raw'
import { parseAlerts, parseTraceJsonl, type AlertsParseResult, type TraceParseResult } from './parse.ts'
import { alertsFromHits, overviewCounts, rollUpAlerts, type OverviewCounts } from './rollup.ts'
import type { AlertSummary, TraceHit } from './types.ts'

export interface LoadedTrace {
  name: string
  result: TraceParseResult
}
export interface LoadedAlerts {
  name: string
  result: AlertsParseResult
}

/** Bundled synthetic fixtures. Static strings compiled into the app; no fetch. */
export function loadSample(): { trace: LoadedTrace; alerts: LoadedAlerts } {
  return {
    trace: { name: 'sample.trace.jsonl (bundled)', result: parseTraceJsonl(sampleTraceText) },
    alerts: { name: 'sample.alerts.jsonl (bundled)', result: parseAlerts(sampleAlertsText) },
  }
}

export interface Model {
  verified: boolean
  summaries: AlertSummary[]
  summariesById: Map<string, AlertSummary>
  hitsById: Map<string, TraceHit>
  counts: OverviewCounts
}

export function buildModel(trace: LoadedTrace, alerts: LoadedAlerts | null): Model {
  const hits = trace.result.hits
  const verified = alerts !== null && alerts.result.alerts.length > 0
  const refs = verified ? alerts.result.alerts : alertsFromHits(hits)
  const summaries = rollUpAlerts(refs, hits, { alertsVerified: verified, rejected: trace.result.rejected })
  return {
    verified,
    summaries,
    summariesById: new Map(summaries.map((s) => [s.alert_id, s])),
    hitsById: new Map(hits.map((h) => [h.hit_id, h])),
    counts: overviewCounts(summaries, hits, verified),
  }
}
