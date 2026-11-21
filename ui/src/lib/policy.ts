// Decisions and reason codes, exactly as in the track brief / POLICY table order.
// Order matters: reason-code priority is "first in POLICY table order".

export const DECISIONS = ['DIFFERENT_ENTITY', 'SAME_ENTITY', 'REVIEW'] as const
export type Decision = (typeof DECISIONS)[number]

/** On-screen order, most urgent first: confirmed matches (to compliance), then analyst review, then clears. */
export const DISPLAY_DECISIONS: readonly Decision[] = ['SAME_ENTITY', 'REVIEW', 'DIFFERENT_ENTITY']

export const REASON_CODES: Record<Decision, readonly string[]> = {
  DIFFERENT_ENTITY: [
    'TEMPORAL_IMPOSSIBILITY',
    'DOB_MISMATCH',
    'LOCATION_MISMATCH',
    'NAME_MISMATCH_VERIFIED',
    'ENTITY_TYPE_MISMATCH',
    'DECEASED',
  ],
  SAME_ENTITY: ['NAME_DOB_LOCATION_MATCH', 'NAME_DOB_MATCH', 'NAME_LOCATION_MATCH'],
  REVIEW: ['INSUFFICIENT_DATA', 'AMBIGUOUS_CUSTOMER_RECORD'],
}

/** Stage 4 alert_status values. Internal: never rendered; see labels.ts for on-screen wording. */
export const ALERT_STATUSES = ['CLEARED', 'ESCALATED', 'NEEDS_REVIEW'] as const
export type AlertStatus = (typeof ALERT_STATUSES)[number]

/**
 * UI-only status: every decided hit is DIFFERENT_ENTITY, but no alerts file was loaded,
 * so we cannot prove no hit is missing. Shown in place of CLEARED.
 */
export type RollupStatus = AlertStatus | 'NOT_VERIFIED'
export const ROLLUP_STATUSES: readonly RollupStatus[] = ['CLEARED', 'NOT_VERIFIED', 'ESCALATED', 'NEEDS_REVIEW']

/** Blocking reason for a hit listed on an alert but without a usable decision. */
export const HIT_NOT_DECIDED = 'HIT_NOT_DECIDED'

export function isDecision(x: unknown): x is Decision {
  return typeof x === 'string' && (DECISIONS as readonly string[]).includes(x)
}

export function isReasonCodeFor(decision: Decision, code: unknown): code is string {
  return typeof code === 'string' && REASON_CODES[decision].includes(code)
}

export function isAlertStatus(x: unknown): x is AlertStatus {
  return typeof x === 'string' && (ALERT_STATUSES as readonly string[]).includes(x)
}
