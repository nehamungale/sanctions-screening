// Pure row builders for the Analyst queue and Audit screens.

import type { Model } from './model.ts'
import { DIM_LABELS, MISSING_TEXT, undecidedText } from './labels.ts'
import { HIT_NOT_DECIDED, type Decision } from './policy.ts'
import { noComparisonReason, readComparison, readDecidingDims, readIdentity, readSteps, unknownFacts } from './trace-view.ts'
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
    const nd = hit.not_decided
    rows.push({
      hit_id: hit.hit_id,
      alert_id: hit.alert_id,
      decision: nd ? null : hit.verdict.decision,
      reason_code: nd ? HIT_NOT_DECIDED : hit.verdict.reason_code,
      undecided: nd ? { kind: 'not_decided' } : null,
      fragility: nd ? null : (hit.badges?.fragility ?? null),
      llm_used: nd ? null : (hit.badges?.llm_used ?? null),
      hit,
    })
  }
  return rows.sort((a, b) => cmp(a.hit_id, b.hit_id) || cmp(a.alert_id ?? '', b.alert_id ?? ''))
}

export const QUEUE_GROUPS = [
  { id: 'review', title: 'REVIEW', note: 'The evidence cannot settle it. An analyst decides.' },
  { id: 'undecided', title: 'Hit has no decision', note: 'Missing, not decided by the pipeline, conflicting or filed under another alert. Blocks the alert; fix the run or decide by hand.' },
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
    const none = noComparisonReason(raw, row.hit.verdict.customer_record_id)
    if (none) return capital(`no comparison: ${none}`)
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

/** Plain words for the safety checks (system/stage4/gate.py) that hold a clear back. */
export const GATE_LABELS: Record<string, string> = {
  NON_LATIN_ALIAS: 'hit has a name in a script we do not compare',
  NON_EXHAUSTIVE_NAME: 'name comparison not exhaustive',
  joint_account_tiebreak: 'customer picked from a joint account by tie-break',
  candidate_kept_on_missing_field: 'alert lacked a field the clear needs',
  name_match_fuzzy_only: 'customer matched only through a spelling variant',
  dob_partial_only: 'screened date of birth matched only in part',
  LINK_SUSPECT: 'alert link contradicts the screened details',
  DANGLING_LINK: 'alert link points at no customer record',
  resolved_via_note_country: 'customer reached only through a note country',
  BLOCK_NAME_MISMATCH_VERIFIED: 'no customer date of birth, so name cannot clear',
  UNVERIFIED: 'no customer date of birth, so name cannot clear',
  BLOCK_NAME_CLEAR: 'customer name too short to compare',
  SCREENED_NAME_TOO_SHORT: 'screened name too short to compare',
  BLOCK_DOB_AGE_NAME_CLEAR: 'a verification note could not be fully read',
  DOB_MAY_NOT_CLEAR: 'customer date of birth not safe to clear on',
  NAME_MAY_NOT_CLEAR: 'customer name not safe to clear on',
  WEAK_DOB_RULE: 'hit birth year from a weak age sentence',
  BORN_CUE_SEARCH_DOB: 'profile birth cue the search result may miss',
  MULTI_SR_CONFLICT: 'search results disagree on birth year',
  NOTE_DOB_UNRESOLVED: 'birth cue in profile could not be read',
  HIT_UNPARSED_DATE: 'a date on the hit could not be read',
  DECLARED_DOB_AGREES: 'a declared date of birth agrees with the hit',
  HIT_UNMAPPED_COUNTRY: 'a hit country could not be mapped',
  NON_EXHAUSTIVE_BLOCKS_LOCATION: 'name not fully compared, so location cannot clear',
  SCREENED_TYPE_DISAGREES: 'screened entity type disagrees with the customer',
  MULTI_VERIFICATION_CONFLICT: 'identity checks disagree',
  TYPE_CONFLICT: 'customer records disagree on entity type',
  BLOCK_LOCATION_MISMATCH: 'customer countries not safe to clear on',
  LLM_DOB_UNKNOWN: 'model could not read the hit’s birth date',
}

export interface WhyTag {
  key: string
  label: string
  /** 'held': a contradiction was found but a safety check held the clear back. */
  kind: 'held' | 'missing' | 'identity' | 'confirm'
}

/** Why a hit needs a person, as tags that can be counted and filtered on. */
export function whyTags(row: HitRow): WhyTag[] {
  if (row.decision === null || !row.hit) return [{ key: 'undecided', label: 'no decision from the pipeline', kind: 'identity' }]
  const raw = row.hit.raw
  if (row.decision === 'SAME_ENTITY') return [{ key: `confirm:${row.reason_code}`, label: `confirmed: ${row.reason_code}`, kind: 'confirm' }]
  const tags: WhyTag[] = []
  if (row.reason_code === 'AMBIGUOUS_CUSTOMER_RECORD') tags.push({ key: 'ambiguous', label: 'more than one customer fits', kind: 'identity' })
  const cid = row.hit.verdict.customer_record_id
  if (!cid) tags.push({ key: 'no-customer', label: 'no customer record found', kind: 'identity' })
  for (const s of readSteps(raw)) {
    if (s.result === 'blocked' && s.why) tags.push({ key: `held:${s.why}`, label: GATE_LABELS[s.why] ?? s.why.replace(/_/g, ' ').toLowerCase(), kind: 'held' })
  }
  for (const u of unknownFacts(readComparison(raw))) {
    if (u.dim === 'death' || u.dim === 'earliest_report') continue
    const dim = (DIM_LABELS[u.dim] ?? u.dim).toLowerCase()
    if (u.side === 'hit' || u.side === 'both') tags.push({ key: `missing-hit:${u.dim}`, label: `${dim} not on list profile`, kind: 'missing' })
    if (u.side === 'customer' || u.side === 'both') tags.push({ key: `missing-cust:${u.dim}`, label: `${dim} not in customer records`, kind: 'missing' })
  }
  if (readIdentity(raw).flags.includes('UNVERIFIED')) tags.push({ key: 'declared-only', label: 'customer facts declared, not verified', kind: 'missing' })
  if (row.hit.raw.output_only === true) tags.push({ key: 'output-only', label: 'decision only (load the trace for why)', kind: 'missing' })
  const seen = new Set<string>()
  return tags.filter((t) => (seen.has(t.key) ? false : (seen.add(t.key), true)))
}
