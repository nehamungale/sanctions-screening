// Defensive parsers for local files. Bad lines are reported, never thrown.

import { isAlertStatus, isDecision, isReasonCodeFor } from './policy.ts'
import type { AlertRef, ParseIssue, TraceHit, UndecidedReason } from './types.ts'

export interface TraceParseResult {
  hits: TraceHit[]
  issues: ParseIssue[]
  /** Hits with no usable record: invalid line(s) or conflicting duplicates. */
  rejected: Map<string, UndecidedReason>
  /** Alert summary lines (and any legacy run header) are valid trace lines but not hits. */
  skipped: number
  lines: number
  /**
   * Stage 4 appends its alert summaries to the same trace.jsonl. They are split off here and
   * parsed like a summaries file: a cross-check only, never a source of Cleared. Null if none.
   */
  summaries: AlertsParseResult | null
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
    not_decided: rec.not_decided === true,
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
  const all = splitLines(text)
  // Summary lines keep their line numbers: every other line is blanked before parsing them.
  const summaryText: string[] = all.map(() => '')
  let summaryLines = 0

  all.forEach((rawLine, i) => {
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
    if (isAlertSummaryRecord(rec)) {
      skipped++
      summaryLines++
      summaryText[i] = rawLine
      return
    }
    if (!('hit_id' in rec) && 'run_id' in rec) {
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
  const summaries = summaryLines ? parseAlerts(summaryText.join('\n')) : null
  return { hits, issues, rejected, skipped, lines, summaries }
}

interface Group {
  ref: AlertRef
  lines: number[]
  forms: Set<string>
  statuses: Set<string | undefined>
}

export interface AlertsParseResult {
  /** From alerts.jsonl lines (alert_id + hit_ids): the source of truth for which hits an alert has. */
  alerts: AlertRef[]
  /** From Stage 4 alert summary lines (with pipeline_status), e.g. split off trace.jsonl. A cross-check only. */
  summaries: AlertRef[]
  issues: ParseIssue[]
  lines: number
  /** Lines that could not be read as an alert or a summary. While above 0, nothing can show as Cleared. */
  bad_lines: number
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
  // Stage 4 alert summary line (appended to trace.jsonl). Its hit list is hits[] plus any undecided/blocking ids.
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

/** Accepts alerts.jsonl, a file of Stage 4 alert summaries (legacy alerts.trace.jsonl), or a JSON array of either. */
export function parseAlerts(text: string): AlertsParseResult {
  const issues: ParseIssue[] = []
  // Never drop a line. Lines for the same alert_id are merged: identical ones silently (with a note);
  // differing ones take the union of their hit_ids and mark the alert as conflicting, which the
  // roll-up turns into Needs review (never Cleared).
  const groups = { alerts: new Map<string, Group>(), summaries: new Map<string, Group>() }
  let bad = 0
  const push = (raw: unknown, a: AlertRef | null, line: number) => {
    if (!a) {
      bad++
      return
    }
    const key = a.pipeline_status ? 'summaries' : 'alerts'
    const g = groups[key].get(a.alert_id)
    if (!g) {
      groups[key].set(a.alert_id, { ref: { ...a, hit_ids: [...a.hit_ids] }, lines: [line], forms: new Set([canonicalJson(raw)]), statuses: new Set([a.pipeline_status]) })
      return
    }
    g.lines.push(line)
    g.forms.add(canonicalJson(raw))
    g.statuses.add(a.pipeline_status)
    g.ref.hit_ids = [...new Set([...g.ref.hit_ids, ...a.hit_ids])]
  }
  const finish = (m: Map<string, Group>): AlertRef[] =>
    [...m.values()].map((g) => {
      if (g.lines.length === 1) return g.ref
      if (g.forms.size === 1) {
        issues.push({ line: g.lines[0], message: `${g.ref.alert_id}: ${g.lines.length} identical lines (${g.lines.join(', ')}), merged`, severity: 'info' })
        return g.ref
      }
      issues.push({
        line: g.lines[0],
        message: `${g.ref.alert_id}: conflicting lines ${g.lines.join(', ')}; hit lists combined and the alert can't be cleared`,
      })
      const ref: AlertRef = { ...g.ref, conflicting_lines: g.lines }
      if (g.statuses.size > 1) delete ref.pipeline_status
      return ref
    })
  const result = () => {
    const alerts = finish(groups.alerts)
    const summaries = finish(groups.summaries)
    return { alerts, summaries }
  }
  const kindOf = (alerts: AlertRef[], summaries: AlertRef[]): AlertsParseResult['kind'] =>
    alerts.length && summaries.length ? 'mixed' : alerts.length ? 'alerts' : summaries.length ? 'summaries' : 'empty'

  const trimmed = text.replace(/^\uFEFF/, '').trim()
  if (trimmed.startsWith('[')) {
    try {
      const arr = JSON.parse(trimmed) as unknown[]
      arr.forEach((rec, i) => push(rec, toAlert(rec, i + 1, issues), i + 1))
      const { alerts, summaries } = result()
      return { alerts, summaries, issues, lines: arr.length, bad_lines: bad, kind: kindOf(alerts, summaries) }
    } catch {
      issues.push({ line: 1, message: 'file starts with [ but is not a valid JSON array' })
      return { alerts: [], summaries: [], issues, lines: 0, bad_lines: 1, kind: 'empty' }
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
      bad++
      return
    }
    // A run header can sit at the top of a trace-style file.
    if (isObj(rec) && !('alert_id' in rec) && 'run_id' in rec) return
    push(rec, toAlert(rec, i + 1, issues), i + 1)
  })
  const { alerts, summaries } = result()
  return { alerts, summaries, issues, lines, bad_lines: bad, kind: kindOf(alerts, summaries) }
}
