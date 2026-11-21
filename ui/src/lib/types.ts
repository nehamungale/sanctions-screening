import type { AlertStatus, Decision, RollupStatus } from './policy.ts'

/** The fields of a per-hit trace record (trace_schema 1) the UI reads. */
export interface TraceHit {
  trace_schema: number
  hit_id: string
  alert_id: string | null
  verdict: {
    decision: Decision
    reason_code: string
    reason: string | null
    evidence: string[]
    customer_record_id: string | null
  }
  badges: { fragility?: string; llm_used?: boolean; rules_version?: string } | null
  /** The full parsed record, for the hit panel and raw trace view. */
  raw: Record<string, unknown>
}

/** Why a hit listed on an alert has no usable decision (all count as HIT_NOT_DECIDED). */
export type UndecidedReason =
  | { kind: 'missing' }
  | { kind: 'invalid' }
  | { kind: 'conflict' }
  | { kind: 'alert_mismatch'; trace_alert_id: string | null }

/** One alert: from alerts.jsonl, or rebuilt from an alerts.trace.jsonl summary. */
export interface AlertRef {
  alert_id: string
  hit_ids: string[]
  /** alert_status as written by the pipeline, when loaded from alerts.trace.jsonl. */
  pipeline_status?: AlertStatus
}

export interface RollupHit {
  hit_id: string
  decision: Decision | null
  reason_code: string | null
  fragility: string | null
  undecided: UndecidedReason | null
}

/** Alert summary, shaped like the Stage 4 notes' trace sketch. */
export interface AlertSummary {
  alert_id: string
  alert_status: RollupStatus
  hits: RollupHit[]
  blocking_hit_ids: string[]
  undecided_hit_ids: string[]
  pipeline_status?: AlertStatus
}

export interface ParseIssue {
  line: number
  message: string
  /** 'info' is reported but does not drop anything (e.g. an identical duplicate). */
  severity?: 'error' | 'info'
}
