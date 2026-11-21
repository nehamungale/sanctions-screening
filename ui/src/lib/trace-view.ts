import { DECIDING_DIMS, DIMS } from './labels.ts'

// Defensive readers for the optional parts of a trace record (design doc section 1).
// Anything malformed is dropped or shown as unknown; nothing here throws.

const isObj = (x: unknown): x is Record<string, unknown> =>
  typeof x === 'object' && x !== null && !Array.isArray(x)
const str = (x: unknown): string | null => (typeof x === 'string' ? x : null)
const strs = (x: unknown): string[] => (Array.isArray(x) ? x.filter((s): s is string => typeof s === 'string') : [])

/** Plain-text form of any JSON value, for display. */
export function formatValue(x: unknown): string {
  if (x === null || x === undefined || x === '') return '—'
  if (typeof x === 'string') return x
  if (typeof x === 'number' || typeof x === 'boolean') return String(x)
  if (Array.isArray(x)) return x.length ? x.map(formatValue).join('; ') : '—'
  return JSON.stringify(x)
}

export interface ComparisonRow {
  dim: string
  customer: unknown
  hit: unknown
  status: string
  src: string[]
  /** stage4: true when an input to this row was read by the model. */
  llm_used: boolean
}

export function readComparison(raw: Record<string, unknown>): ComparisonRow[] {
  if (!Array.isArray(raw.comparison)) return []
  return raw.comparison.filter(isObj).map((r) => ({
    dim: str(r.dim) ?? '?',
    customer: r.customer ?? null,
    hit: r.hit ?? null,
    status: str(r.status) ?? 'unknown',
    src: strs(r.src),
    llm_used: r.llm_used === true,
  }))
}

export interface Step {
  rule: string
  result: string
  llm_used: boolean
  why: string | null
}

export function readSteps(raw: Record<string, unknown>): Step[] {
  if (!Array.isArray(raw.steps)) return []
  return raw.steps.filter(isObj).map((s) => ({
    rule: str(s.rule) ?? '?',
    result: str(s.result) ?? '?',
    llm_used: s.llm_used === true,
    why: str(s.why),
  }))
}

export interface Candidate {
  customer_record_id: string
  person_id: string | null
  name: string | null
  dob: string | null
  country: string | null
  why_fits: string | null
  would_decide: { decision: string | null; reason_code: string | null } | null
}

/** identity.facts entry (stage4: dob, name, entity_type; `verified` only on dob and name; no source_kind). */
export interface Fact {
  name: string
  value: string
  verified: boolean | null
  source_id: string | null
}

/**
 * What the fact table says about `verified`. stage4 means different things per fact:
 * on dob it is a verified date (check or note); on name it only means a name comparison was
 * computed, NOT a KYC-verified legal name, so the word "verified" is never used for it.
 */
export function factStatus(f: Fact): string {
  if (f.verified === null) return '—'
  if (f.name === 'name') return f.verified ? 'compared with the hit' : 'not compared'
  if (f.name === 'dob') return f.verified ? 'verified' : 'declared'
  return f.verified ? 'yes' : 'no'
}

export interface Identity {
  person_id: string | null
  merged: { rule: string; records: string[]; extra: [string, string][] }[]
  facts: Fact[]
  flags: string[]
  ignored_checks: string[]
  candidates: Candidate[]
}

export function readIdentity(raw: Record<string, unknown>): Identity {
  const id = isObj(raw.identity) ? raw.identity : {}
  const merged = Array.isArray(id.merged)
    ? id.merged.filter(isObj).map((m) => ({
        rule: str(m.rule) ?? '?',
        records: strs(m.records),
        extra: Object.entries(m)
          .filter(([k]) => k !== 'rule' && k !== 'records')
          .map(([k, v]) => [k, formatValue(v)] as [string, string]),
      }))
    : []
  const facts = isObj(id.facts)
    ? Object.entries(id.facts).map(([name, f]) =>
        isObj(f)
          ? {
              name,
              value: formatValue(f.value),
              verified: typeof f.verified === 'boolean' ? f.verified : null,
              source_id: str(f.source_id),
            }
          : { name, value: formatValue(f), verified: null, source_id: null },
      )
    : []
  const candidates = Array.isArray(id.candidates)
    ? id.candidates.filter(isObj).flatMap((c) => {
        const cid = str(c.customer_record_id)
        if (!cid) return []
        const wd = isObj(c.would_decide) ? c.would_decide : null
        return [
          {
            customer_record_id: cid,
            person_id: str(c.person_id),
            name: str(c.name),
            dob: str(c.dob),
            country: str(c.country),
            why_fits: str(c.why_fits),
            would_decide: wd ? { decision: str(wd.decision), reason_code: str(wd.reason_code) } : null,
          },
        ]
      })
    : []
  return {
    person_id: str(id.person_id),
    merged,
    facts,
    flags: strs(id.flags),
    ignored_checks: strs(id.ignored_checks),
    candidates,
  }
}

export function readLlmCalls(raw: Record<string, unknown>): Record<string, unknown>[] {
  return Array.isArray(raw.llm_calls) ? raw.llm_calls.filter(isObj) : []
}

/**
 * Why a hit has no comparison rows (stage4 writes comparison [] and identity.facts {} when no
 * customer fits the alert, or when the hit was not decided). Null when there are rows.
 */
export function noComparisonReason(raw: Record<string, unknown>, customerRecordId: string | null): string | null {
  if (Array.isArray(raw.comparison) && raw.comparison.some(isObj)) return null
  if (raw.not_decided === true) return 'the hit has no decision, so it was never compared with a customer'
  if (raw.output_only === true) return 'this file is the submission output, which carries only the decision. Load trace.jsonl from the same run to see the comparison'
  if (!customerRecordId) return 'no matching customer record, so there is nothing to compare the hit with'
  if (customerRecordId === 'AMBIGUOUS') return 'more than one customer fits this alert and the trace has no comparison rows'
  return 'the trace has no comparison rows for this hit'
}

export function readTippingPoint(raw: Record<string, unknown>): string | null {
  return str(raw.tipping_point)
}

/** Facts the comparison marks unknown, naming which side has no value. */
export function unknownFacts(rows: readonly ComparisonRow[]): { dim: string; side: 'hit' | 'customer' | 'both' | 'neither' }[] {
  return rows
    .filter((r) => r.status === 'unknown')
    .map((r) => ({
      dim: r.dim,
      side: isEmpty(r.customer) && isEmpty(r.hit) ? 'both' : isEmpty(r.hit) ? 'hit' : isEmpty(r.customer) ? 'customer' : 'neither',
    }))
}

export function isEmpty(v: unknown): boolean {
  return v === null || v === undefined || v === '' || (Array.isArray(v) && v.length === 0)
}

/**
 * Which comparison rows the verdict rests on. Prefers the UI-proposed top-level
 * `deciding_dims` field (a list of comparison dims) when it is present and valid;
 * otherwise derives the rows from the reason code (labels.ts DECIDING_DIMS).
 */
export function readDecidingDims(
  raw: Record<string, unknown>,
  reasonCode: string,
): { dims: string[]; source: 'trace' | 'derived' | 'none' } {
  const d = raw.deciding_dims
  if (Array.isArray(d) && d.length > 0 && d.every((x) => typeof x === 'string' && (DIMS as readonly string[]).includes(x))) {
    return { dims: [...new Set(d as string[])], source: 'trace' }
  }
  const derived = DECIDING_DIMS[reasonCode] ?? []
  return { dims: [...derived], source: derived.length ? 'derived' : 'none' }
}
