// Defensive parsers for local files. Bad lines are reported, never thrown.

import { isAlertStatus, isDecision, isReasonCodeFor } from './policy.ts'
import type { AlertRef, ParseIssue, TraceHit, UndecidedReason } from './types.ts'

export interface TraceParseResult {
  hits: TraceHit[]
  issues: ParseIssue[]
  /** Hits with no usable record: invalid line(s) or conflicting duplicates. */
  rejected: Map<string, UndecidedReason>
  /** Run headers and alert summaries are valid trace lines but not hits. */
  skipped: number
  lines: number
}

const isObj = (x: unknown): x is Record<string, unknown> =>
  typeof x === 'object' && x !== null && !Array.isArray(x)
const isStr = (x: unknown): x is string => typeof x === 'string' && x.length > 0
const short = (s: string) => (s.length > 80 ? `${s.slice(0, 80)}…` : s)

function splitLines(text: string): string[] {
  return text.replace(/^\uFEFF/, '').split(/\r?\n/)
}

/** JSON with object keys sorted, so key order does not make identical records differ. */
export function canonicalJson(x: unknown): string {
  if (Array.isArray(x)) return `[${x.map(canonicalJson).join(',')}]`
  if (isObj(x)) {
    return `{${Object.keys(x)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonicalJson(x[k])}`)
      .join(',')}}`
  }
  return JSON.stringify(x) ?? 'null'
}

export function isAlertSummaryRecord(rec: Record<string, unknown>): boolean {
  return 'alert_status' in rec && !('hit_id' in rec)
}

function validateHit(rec: Record<string, unknown>): string | TraceHit {
  if (rec.trace_schema !== 1) {
    return `unsupported trace_schema ${JSON.stringify(rec.trace_schema) ?? 'missing'} (expected 1)`
  }
  const v = rec.verdict
  if (!isObj(v)) return 'missing verdict'
  if (!isDecision(v.decision)) return `unknown decision ${JSON.stringify(v.decision)}`
  if (!isReasonCodeFor(v.decision, v.reason_code)) {
    return `reason_code ${JSON.stringify(v.reason_code)} does not belong to ${v.decision}`
  }
  const badges = isObj(rec.badges) ? rec.badges : null
  return {
    trace_schema: 1,
    hit_id: rec.hit_id as string,
    alert_id: isStr(rec.alert_id) ? rec.alert_id : null,
    verdict: {
      decision: v.decision,
      reason_code: v.reason_code,
      reason: typeof v.reason === 'string' ? v.reason : null,
      evidence: Array.isArray(v.evidence) ? v.evidence.filter(isStr) : [],
      customer_record_id: typeof v.customer_record_id === 'string' ? v.customer_record_id : null,
    },
    badges: badges && {
      fragility: typeof badges.fragility === 'string' ? badges.fragility : undefined,
      llm_used: typeof badges.llm_used === 'boolean' ? badges.llm_used : undefined,
      rules_version: typeof badges.rules_version === 'string' ? badges.rules_version : undefined,
    },
    raw: rec,
  }
}

/**
 * Duplicates: records for the same hit_id that are identical (canonical JSON) are
 * deduplicated with an info note. If they differ, or any of them is invalid, the hit
 * gets no decision (rejected), so it blocks its alert instead of "first wins".
 */
export function parseTraceJsonl(text: string): TraceParseResult {
  const issues: ParseIssue[] = []
  const groups = new Map<string, { firstLine: number; valid: TraceHit[]; invalid: number }>()
  let skipped = 0
  let lines = 0

  splitLines(text).forEach((rawLine, i) => {
    const line = i + 1
    if (rawLine.trim() === '') return
    lines++
    let rec: unknown
    try {
      rec = JSON.parse(rawLine)
    } catch {
      issues.push({ line, message: `not valid JSON: ${short(rawLine.trim())}` })
      return
    }
    if (!isObj(rec)) {
      issues.push({ line, message: 'not a JSON object' })
      return
    }
    if (isAlertSummaryRecord(rec) || (!('hit_id' in rec) && 'run_id' in rec)) {
      skipped++
      return
    }
    if (!isStr(rec.hit_id)) {
      issues.push({ line, message: 'missing hit_id' })
      return
    }
    const g = groups.get(rec.hit_id) ?? { firstLine: line, valid: [], invalid: 0 }
    groups.set(rec.hit_id, g)
    const res = validateHit(rec)
    if (typeof res === 'string') {
      g.invalid++
      issues.push({ line, message: `${rec.hit_id}: ${res}; hit has no decision` })
    } else {
      g.valid.push(res)
    }
  })

  const hits: TraceHit[] = []
  const rejected = new Map<string, UndecidedReason>()
  for (const [id, g] of groups) {
    const n = g.valid.length + g.invalid
    if (g.invalid > 0) {
      rejected.set(id, { kind: 'invalid' })
      if (g.valid.length > 0) issues.push({ line: g.firstLine, message: `${id}: ${n} records, some invalid; hit has no decision` })
      continue
    }
    const forms = new Set(g.valid.map((h) => canonicalJson(h.raw)))
    if (forms.size > 1) {
      rejected.set(id, { kind: 'conflict' })
      issues.push({ line: g.firstLine, message: `${id}: ${n} conflicting records; hit has no decision` })
      continue
    }
    if (n > 1) issues.push({ line: g.firstLine, message: `${id}: ${n} identical records, kept one`, severity: 'info' })
    hits.push(g.valid[0])
  }
  return { hits, issues, rejected, skipped, lines }
}

export interface AlertsParseResult {
  alerts: AlertRef[]
  issues: ParseIssue[]
  lines: number
  /** 'summaries' when the file is alerts.trace.jsonl (Stage 4 alert summaries). */
  kind: 'alerts' | 'summaries' | 'mixed' | 'empty'
}

function toAlert(rec: unknown, line: number, issues: ParseIssue[]): AlertRef | null {
  if (!isObj(rec)) {
    issues.push({ line, message: 'not a JSON object' })
    return null
  }
  if (!isStr(rec.alert_id)) {
    issues.push({ line, message: 'missing alert_id' })
    return null
  }
  // alerts.jsonl line: alert_id + hit_ids.
  if ('hit_ids' in rec) {
    if (!Array.isArray(rec.hit_ids) || !rec.hit_ids.every(isStr)) {
      issues.push({ line, message: `${rec.alert_id}: hit_ids must be a list of strings` })
      return null
    }
    return { alert_id: rec.alert_id, hit_ids: rec.hit_ids as string[] }
  }
  // alerts.trace.jsonl line: alert summary. Its hit list is hits[] plus any undecided ids.
  if ('alert_status' in rec) {
    if (!isAlertStatus(rec.alert_status) || !Array.isArray(rec.hits)) {
      issues.push({ line, message: `${rec.alert_id}: alert summary needs a known alert_status and hits[]` })
      return null
    }
    const ids = rec.hits.map((h) => (isObj(h) ? h.hit_id : undefined))
    const extra = [rec.undecided_hit_ids, rec.blocking_hit_ids].flatMap((x) => (Array.isArray(x) ? x : []))
    if (!ids.every(isStr) || !extra.every(isStr)) {
      issues.push({ line, message: `${rec.alert_id}: alert summary hit ids must be strings` })
      return null
    }
    return { alert_id: rec.alert_id, hit_ids: [...new Set([...ids, ...extra])], pipeline_status: rec.alert_status }
  }
  issues.push({ line, message: `${rec.alert_id}: neither hit_ids nor an alert summary` })
  return null
}

/** Accepts alerts.jsonl, alerts.trace.jsonl (alert summaries) or a JSON array of either. */
export function parseAlerts(text: string): AlertsParseResult {
  const issues: ParseIssue[] = []
  const alerts: AlertRef[] = []
  const seen = new Set<string>()
  const push = (a: AlertRef | null, line: number) => {
    if (!a) return
    if (seen.has(a.alert_id)) {
      issues.push({ line, message: `${a.alert_id}: duplicate alert_id, kept the first` })
      return
    }
    seen.add(a.alert_id)
    alerts.push(a)
  }
  const kindOf = (): AlertsParseResult['kind'] => {
    const s = alerts.filter((a) => a.pipeline_status).length
    if (alerts.length === 0) return 'empty'
    return s === 0 ? 'alerts' : s === alerts.length ? 'summaries' : 'mixed'
  }

  const trimmed = text.replace(/^\uFEFF/, '').trim()
  if (trimmed.startsWith('[')) {
    try {
      const arr = JSON.parse(trimmed) as unknown[]
      arr.forEach((rec, i) => push(toAlert(rec, i + 1, issues), i + 1))
      return { alerts, issues, lines: arr.length, kind: kindOf() }
    } catch {
      issues.push({ line: 1, message: 'file starts with [ but is not a valid JSON array' })
      return { alerts, issues, lines: 0, kind: 'empty' }
    }
  }
  let lines = 0
  splitLines(text).forEach((rawLine, i) => {
    if (rawLine.trim() === '') return
    lines++
    let rec: unknown
    try {
      rec = JSON.parse(rawLine)
    } catch {
      issues.push({ line: i + 1, message: `not valid JSON: ${short(rawLine.trim())}` })
      return
    }
    // A run header can sit at the top of a trace-style file.
    if (isObj(rec) && !('alert_id' in rec) && 'run_id' in rec) return
    push(toAlert(rec, i + 1, issues), i + 1)
  })
  return { alerts, issues, lines, kind: kindOf() }
}
