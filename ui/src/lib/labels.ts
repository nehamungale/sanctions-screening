// Everything the UI says about statuses, decisions and reason codes, in the brief's words.
// The internal status names (ESCALATED, NEEDS_REVIEW, NOT_VERIFIED) are never shown.

import { HIT_NOT_DECIDED, type Decision, type RollupStatus } from './policy.ts'
import type { UndecidedReason } from './types.ts'

export const STATUS_LABELS: Record<RollupStatus, { label: string; sub: string; slug: string }> = {
  CLEARED: { label: 'Cleared', sub: 'every hit is DIFFERENT_ENTITY', slug: 'cleared' },
  NOT_VERIFIED: {
    label: 'Not verified',
    sub: 'every decided hit is DIFFERENT_ENTITY, but no alerts file shows that no hit is missing',
    slug: 'not-verified',
  },
  ESCALATED: { label: 'Goes to compliance team', sub: 'at least one hit is SAME_ENTITY', slug: 'compliance' },
  NEEDS_REVIEW: {
    label: 'Needs review',
    sub: 'no SAME_ENTITY, at least one hit REVIEW or undecided',
    slug: 'review',
  },
}

export function statusFromSlug(slug: string | null): RollupStatus | null {
  const hit = (Object.keys(STATUS_LABELS) as RollupStatus[]).find((s) => STATUS_LABELS[s].slug === slug)
  return hit ?? null
}

/** Decisions are shown exactly as the brief writes them. */
export const DECISION_MEANING: Record<Decision, string> = {
  DIFFERENT_ENTITY: 'the hit is a different person or company',
  SAME_ENTITY: 'the hit is the customer',
  REVIEW: 'the evidence cannot settle it',
}

/** Plain-English reason labels, from the track brief's "Use it when" column. */
export const REASON_LABELS: Record<string, string> = {
  TEMPORAL_IMPOSSIBILITY: 'customer too young, or not yet incorporated, at the earliest dated report',
  DOB_MISMATCH: 'date of birth contradicts every birth date the hit gives',
  LOCATION_MISMATCH: 'every customer country differs from every hit country',
  NAME_MISMATCH_VERIFIED: 'verified legal name agrees with none of the hit’s names',
  ENTITY_TYPE_MISMATCH: 'one is a person and the other a company',
  DECEASED: 'hit’s date of death is before the customer was screened',
  NAME_DOB_LOCATION_MATCH: 'name, date of birth and country all agree',
  NAME_DOB_MATCH: 'name and date of birth agree',
  NAME_LOCATION_MATCH: 'company name and country agree',
  INSUFFICIENT_DATA: 'nothing settles it: no contradiction, not enough agreement',
  AMBIGUOUS_CUSTOMER_RECORD: 'more than one customer fits, leading to different decisions',
  [HIT_NOT_DECIDED]: 'hit has no decision',
}

export function reasonLabel(code: string): string {
  return REASON_LABELS[code] ?? 'unknown reason code'
}

export function undecidedText(r: UndecidedReason): string {
  switch (r.kind) {
    case 'missing':
      return 'no record for this hit in the trace'
    case 'invalid':
      return 'the trace record for this hit is invalid'
    case 'conflict':
      return 'the trace has conflicting records for this hit'
    case 'alert_mismatch':
      return r.trace_alert_id
        ? `the trace record belongs to alert ${r.trace_alert_id}, not this one`
        : 'the trace record has no alert_id'
  }
}

/** Comparison dimensions from the design doc, section 1, in display order. */
export const DIMS = ['name', 'dob', 'country', 'type', 'death', 'earliest_report'] as const
export const DIM_LABELS: Record<string, string> = {
  name: 'Name',
  dob: 'Date of birth',
  country: 'Country',
  type: 'Type',
  death: 'Date of death',
  earliest_report: 'Earliest report',
}

/**
 * Which comparison rows a reason code rests on. Derived from the policy, because the
 * trace has no explicit "deciding dimension" field yet. REVIEW codes rest on no row.
 */
export const DECIDING_DIMS: Record<string, readonly string[]> = {
  TEMPORAL_IMPOSSIBILITY: ['earliest_report'],
  DOB_MISMATCH: ['dob'],
  LOCATION_MISMATCH: ['country'],
  NAME_MISMATCH_VERIFIED: ['name'],
  ENTITY_TYPE_MISMATCH: ['type'],
  DECEASED: ['death'],
  NAME_DOB_LOCATION_MATCH: ['name', 'dob', 'country'],
  NAME_DOB_MATCH: ['name', 'dob'],
  NAME_LOCATION_MATCH: ['name', 'country'],
}
