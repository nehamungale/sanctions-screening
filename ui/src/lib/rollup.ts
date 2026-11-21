// Alert roll-up (docs/stage4-notes.md section 1). Pure and deterministic.
//
//   CLEARED       every hit in the alert is DIFFERENT_ENTITY (and every hit was decided)
//   ESCALATED     at least one hit is SAME_ENTITY (takes priority)
//   NEEDS_REVIEW  otherwise
//
// A hit counts as undecided (HIT_NOT_DECIDED, blocks the clear) when it is missing from
// the trace, its record was invalid or conflicting, or its own alert_id is not this alert.
// An alert with no hit_ids is NEEDS_REVIEW, not vacuously CLEARED.
// Without a verified alert list, a would-be CLEARED alert is NOT_VERIFIED instead.

import { DECISIONS, REASON_CODES, ROLLUP_STATUSES, type Decision, type RollupStatus } from './policy.ts'
import type { AlertRef, AlertSummary, RollupHit, TraceHit, UndecidedReason } from './types.ts'

const byString = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0)

export interface RollupOptions {
  /** True when the alert list came from an alerts file, so missing hits are detectable. */
  alertsVerified: boolean
  /** Hits the parser rejected (invalid or conflicting records). */
  rejected?: ReadonlyMap<string, UndecidedReason>
}

export function rollUpAlert(
  alert: AlertRef,
  hitsById: ReadonlyMap<string, TraceHit>,
  opts: RollupOptions,
): AlertSummary {
  const hitIds = [...new Set(alert.hit_ids)].sort(byString)
  const hits: RollupHit[] = hitIds.map((id) => {
    const h = hitsById.get(id)
    let undecided: UndecidedReason | null = null
    if (!h) undecided = opts.rejected?.get(id) ?? { kind: 'missing' }
    else if (h.alert_id !== alert.alert_id) undecided = { kind: 'alert_mismatch', trace_alert_id: h.alert_id }
    return h && !undecided
      ? {
          hit_id: id,
          decision: h.verdict.decision,
          reason_code: h.verdict.reason_code,
          fragility: h.badges?.fragility ?? null,
          undecided: null,
        }
      : { hit_id: id, decision: null, reason_code: null, fragility: null, undecided }
  })
  const undecidedIds = hits.filter((h) => h.undecided).map((h) => h.hit_id)
  const blocking = hits.filter((h) => h.decision !== 'DIFFERENT_ENTITY').map((h) => h.hit_id)

  let status: RollupStatus
  if (hits.some((h) => h.decision === 'SAME_ENTITY')) status = 'ESCALATED'
  else if (hits.length > 0 && blocking.length === 0) status = opts.alertsVerified ? 'CLEARED' : 'NOT_VERIFIED'
  else status = 'NEEDS_REVIEW'

  return {
    alert_id: alert.alert_id,
    alert_status: status,
    hits,
    blocking_hit_ids: blocking,
    undecided_hit_ids: undecidedIds,
    ...(alert.pipeline_status ? { pipeline_status: alert.pipeline_status } : {}),
  }
}

export function rollUpAlerts(
  alerts: readonly AlertRef[],
  hits: readonly TraceHit[],
  opts: RollupOptions,
): AlertSummary[] {
  const hitsById = new Map(hits.map((h) => [h.hit_id, h]))
  return [...alerts].sort((a, b) => byString(a.alert_id, b.alert_id)).map((a) => rollUpAlert(a, hitsById, opts))
}

/** Without an alerts file, group hits by their own alert_id. Missing hits cannot be detected. */
export function alertsFromHits(hits: readonly TraceHit[]): AlertRef[] {
  const m = new Map<string, string[]>()
  for (const h of hits) {
    if (!h.alert_id) continue
    const list = m.get(h.alert_id) ?? []
    list.push(h.hit_id)
    m.set(h.alert_id, list)
  }
  return [...m.entries()].map(([alert_id, hit_ids]) => ({ alert_id, hit_ids }))
}

export interface OverviewCounts {
  alerts: Record<RollupStatus, number>
  alertsTotal: number
  alertsWithUndecided: number
  hitsByDecision: Record<Decision, number>
  hitsDecided: number
  hitsUndecided: number
  /** Hits in the trace that no alert lists (only when an alerts file is loaded). */
  hitsUnlisted: number
  /** Alerts whose pipeline alert_status differs from this roll-up (alerts.trace.jsonl only). */
  pipelineDisagreements: string[]
  /** Every policy reason code in POLICY order, including zero counts. */
  hitsByReason: { decision: Decision; reason_code: string; count: number }[]
}

export function overviewCounts(
  summaries: readonly AlertSummary[],
  hits: readonly TraceHit[],
  alertsVerified: boolean,
): OverviewCounts {
  const alerts = Object.fromEntries(ROLLUP_STATUSES.map((s) => [s, 0])) as Record<RollupStatus, number>
  for (const s of summaries) alerts[s.alert_status]++

  const hitsByDecision: Record<Decision, number> = { DIFFERENT_ENTITY: 0, SAME_ENTITY: 0, REVIEW: 0 }
  const reason = new Map<string, number>()
  for (const h of hits) {
    hitsByDecision[h.verdict.decision]++
    const k = `${h.verdict.decision}|${h.verdict.reason_code}`
    reason.set(k, (reason.get(k) ?? 0) + 1)
  }

  const listed = new Set(summaries.flatMap((s) => s.hits.map((h) => h.hit_id)))
  const undecided = new Set(summaries.flatMap((s) => s.undecided_hit_ids))

  return {
    alerts,
    alertsTotal: summaries.length,
    alertsWithUndecided: summaries.filter((s) => s.undecided_hit_ids.length > 0).length,
    hitsByDecision,
    hitsDecided: hits.length,
    hitsUndecided: undecided.size,
    hitsUnlisted: alertsVerified ? hits.filter((h) => !listed.has(h.hit_id)).length : 0,
    pipelineDisagreements: summaries
      .filter((s) => s.pipeline_status && s.pipeline_status !== s.alert_status)
      .map((s) => s.alert_id),
    hitsByReason: DECISIONS.flatMap((d) =>
      REASON_CODES[d].map((c) => ({ decision: d, reason_code: c, count: reason.get(`${d}|${c}`) ?? 0 })),
    ),
  }
}
