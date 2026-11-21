// Pure row builders for the Analyst queue and Audit screens.

import type { Model } from './model.ts'
import { DIM_LABELS, MISSING_TEXT, undecidedText } from './labels.ts'
import { HIT_NOT_DECIDED, type Decision } from './policy.ts'
import { readComparison, readDecidingDims, readIdentity, unknownFacts } from './trace-view.ts'
import type { TraceHit, UndecidedReason } from './types.ts'

export interface HitRow {
  hit_id: string
  alert_id: string | null
  decision: Decision | null
  /** The verdict's reason code, or HIT_NOT_DECIDED. */
  reason_code: string
  undecided: UndecidedReason | null
  fragility: string | null
  llm_used: boolean | null
  hit: TraceHit | null
}

const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0)

/** Every hit: each (alert, hit) pair from the roll-up, plus trace hits no alert lists. Sorted by hit, then alert. */
export function allHitRows(model: Model): HitRow[] {
  const rows: HitRow[] = []
  const listed = new Set<string>()
  for (const s of model.summaries) {
    for (const h of s.hits) {
      listed.add(h.hit_id)
      const hit = model.hitsById.get(h.hit_id) ?? null
      rows.push({
        hit_id: h.hit_id,
        alert_id: s.alert_id,
        decision: h.decision,
        reason_code: h.reason_code ?? HIT_NOT_DECIDED,
        undecided: h.undecided,
        fragility: h.decision ? (hit?.badges?.fragility ?? null) : null,
        llm_used: h.decision ? (hit?.badges?.llm_used ?? null) : null,
        hit,
      })
    }
  }
  for (const hit of model.hitsById.values()) {
    if (listed.has(hit.hit_id)) continue
    rows.push({
      hit_id: hit.hit_id,
      alert_id: hit.alert_id,
      decision: hit.verdict.decision,
      reason_code: hit.verdict.reason_code,
      undecided: null,
      fragility: hit.badges?.fragility ?? null,
      llm_used: hit.badges?.llm_used ?? null,
      hit,
    })
  }
  return rows.sort((a, b) => cmp(a.hit_id, b.hit_id) || cmp(a.alert_id ?? '', b.alert_id ?? ''))
}

export const QUEUE_GROUPS = [
  { id: 'review', title: 'REVIEW', note: 'The evidence cannot settle it. An analyst decides.' },
  { id: 'undecided', title: 'Hit has no decision', note: 'Missing, conflicting or filed under another alert. Blocks the alert; fix the run or decide by hand.' },
  { id: 'same', title: 'SAME_ENTITY', note: 'Goes to the compliance team. Check the confirmation before it is passed on.' },
] as const
export type QueueGroupId = (typeof QUEUE_GROUPS)[number]['id']

/** Hits that need a person, grouped REVIEW, then no decision, then SAME_ENTITY; each group by alert, then hit. */
export function queueGroups(model: Model): { id: QueueGroupId; rows: HitRow[] }[] {
  const rows = allHitRows(model).sort((a, b) => cmp(a.alert_id ?? '', b.alert_id ?? '') || cmp(a.hit_id, b.hit_id))
  return [
    { id: 'review', rows: rows.filter((r) => r.decision === 'REVIEW') },
    { id: 'undecided', rows: rows.filter((r) => r.decision === null) },
    { id: 'same', rows: rows.filter((r) => r.decision === 'SAME_ENTITY') },
  ]
}

const dimList = (dims: string[]) => dims.map((d) => (DIM_LABELS[d] ?? d).toLowerCase()).join(', ')

/** One plain-English line: what is missing (REVIEW), why there is no decision, or what a confirm rests on. */
export function whatsMissingLine(row: HitRow): string {
  if (row.decision === null || !row.hit) {
    const t = row.undecided ? undecidedText(row.undecided) : 'no record for this hit in the trace'
    return t.charAt(0).toUpperCase() + t.slice(1)
  }
  const raw = row.hit.raw
  if (row.reason_code === 'AMBIGUOUS_CUSTOMER_RECORD') {
    const c = readIdentity(raw).candidates.map((x) => x.customer_record_id)
    return c.length ? `${c.length} customers fit (${c.join(', ')}); need a link to one of them` : 'More than one customer fits; need a link to one of them'
  }
  if (row.decision === 'REVIEW') {
    const u = unknownFacts(readComparison(raw))
    const hitSide = u.filter((x) => x.side === 'hit' || x.side === 'both').map((x) => x.dim).filter((d) => d !== 'death')
    const custSide = u.filter((x) => x.side === 'customer').map((x) => x.dim)
    const parts: string[] = []
    if (hitSide.length) parts.push(`${MISSING_TEXT.hit}: ${dimList(hitSide)}`)
    if (custSide.length) parts.push(`${MISSING_TEXT.customer}: ${dimList(custSide)}`)
    const flags = readIdentity(raw).flags
    if (flags.includes('UNVERIFIED')) parts.push('customer facts are declared, not verified')
    return parts.length ? capital(parts.join('; ')) : 'Nothing contradicts and not enough agrees to confirm'
  }
  const d = readDecidingDims(raw, row.reason_code).dims
  if (row.decision === 'SAME_ENTITY') return d.length ? `Confirmed on ${dimList(d)}; nothing contradicts` : 'Confirmed; nothing contradicts'
  return d.length ? `Cleared on ${dimList(d)}` : 'Cleared'
}

const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

export interface AuditFilters {
  verdict: Decision | 'none' | null
  code: string | null
  fragility: string | null
  unstable: boolean
  llm: 'yes' | 'no' | null
}

export const NO_FILTERS: AuditFilters = { verdict: null, code: null, fragility: null, unstable: false, llm: null }

export function filterRows(rows: readonly HitRow[], f: AuditFilters, unstable: ReadonlySet<string>): HitRow[] {
  return rows.filter(
    (r) =>
      (f.verdict === null || (f.verdict === 'none' ? r.decision === null : r.decision === f.verdict)) &&
      (f.code === null || r.reason_code === f.code) &&
      (f.fragility === null || (f.fragility === 'unknown' ? r.fragility === null : r.fragility === f.fragility)) &&
      (!f.unstable || unstable.has(r.hit_id)) &&
      (f.llm === null || (f.llm === 'yes' ? r.llm_used === true : r.llm_used !== true)),
  )
}
