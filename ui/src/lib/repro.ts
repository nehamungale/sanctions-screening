// repro.json reader (tools/repro/repro.schema.json, schema_version 1) and metrics.
// Defensive: a bad file is reported, a bad hit row is dropped with an issue; nothing throws.
// Metrics are recomputed from hits[].per_run and cross-checked against summary.

import { isDecision, type Decision } from './policy.ts'
import type { ParseIssue } from './types.ts'

export const FLIP_TYPES = ['none', 'decision', 'code', 'evidence', 'other'] as const
export type FlipType = (typeof FLIP_TYPES)[number]

/** One run's verdict for a hit, or null when that run has no line for it. */
export type RunCell = { decision: Decision | null; reason_code: string | null } | null

export interface ReproHit {
  hit_id: string
  alert_id: string | null
  per_run: RunCell[]
  stable: boolean
  flip_type: FlipType
  modal_decision: Decision | null
  modal_reason_code: string | null
  llm_used: boolean | null
  fragility: string | null
}

export interface ReproReport {
  run_labels: string[]
  n_runs: number
  generated_at: string | null
  summary: {
    n_hits: number | null
    judges_stable_hits: number | null
    judges_metric: number | null
    judges_flip_hits: number | null
    judges_flips_all_llm_used: boolean | null
  }
  /** config_check.all_identical: field -> true / false / null. Null object when unavailable. */
  config_identical: Record<string, boolean | null> | null
  llm_sensitive: number | null
  hits: ReproHit[]
}

export interface ReproParseResult {
  report: ReproReport | null
  issues: ParseIssue[]
}

const isObj = (x: unknown): x is Record<string, unknown> =>
  typeof x === 'object' && x !== null && !Array.isArray(x)
const num = (x: unknown): number | null => (typeof x === 'number' && Number.isFinite(x) ? x : null)
const strOrNull = (x: unknown): string | null => (typeof x === 'string' ? x : null)
const boolOrNull = (x: unknown): boolean | null => (typeof x === 'boolean' ? x : null)

function readCell(x: unknown): RunCell | undefined {
  if (x === null) return null
  if (!Array.isArray(x) || x.length !== 2) return undefined
  const [d, c] = x
  if (!(d === null || isDecision(d)) || !(c === null || typeof c === 'string')) return undefined
  return { decision: d, reason_code: c }
}

export function parseRepro(text: string): ReproParseResult {
  const issues: ParseIssue[] = []
  let doc: unknown
  try {
    doc = JSON.parse(text.replace(/^\uFEFF/, ''))
  } catch {
    return { report: null, issues: [{ line: 1, message: 'not valid JSON' }] }
  }
  if (!isObj(doc)) return { report: null, issues: [{ line: 1, message: 'not a JSON object' }] }
  if (doc.schema_version !== 1) {
    return { report: null, issues: [{ line: 1, message: `unsupported schema_version ${JSON.stringify(doc.schema_version) ?? 'missing'} (expected 1)` }] }
  }
  const meta = isObj(doc.meta) ? doc.meta : {}
  const summary = isObj(doc.summary) ? doc.summary : {}
  const labels = Array.isArray(meta.run_labels) && meta.run_labels.every((l) => typeof l === 'string') ? (meta.run_labels as string[]) : null
  const nRuns = num(summary.n_runs) ?? labels?.length ?? null
  if (nRuns === null || nRuns < 2) {
    return { report: null, issues: [{ line: 1, message: 'needs summary.n_runs (at least 2) or meta.run_labels' }] }
  }
  if (labels && labels.length !== nRuns) issues.push({ line: 1, message: `meta.run_labels has ${labels.length} entries, summary.n_runs is ${nRuns}` })
  if (!Array.isArray(doc.hits)) return { report: null, issues: [...issues, { line: 1, message: 'missing hits[]' }] }

  const hits: ReproHit[] = []
  const seen = new Set<string>()
  doc.hits.forEach((h, i) => {
    const where = `hits[${i}]`
    if (!isObj(h) || typeof h.hit_id !== 'string' || !h.hit_id) {
      issues.push({ line: i + 1, message: `${where}: missing hit_id` })
      return
    }
    if (seen.has(h.hit_id)) {
      issues.push({ line: i + 1, message: `${h.hit_id}: duplicate row, kept the first` })
      return
    }
    if (!Array.isArray(h.per_run) || h.per_run.length !== nRuns) {
      issues.push({ line: i + 1, message: `${h.hit_id}: per_run must have ${nRuns} entries` })
      return
    }
    const cells = h.per_run.map(readCell)
    if (cells.some((c) => c === undefined)) {
      issues.push({ line: i + 1, message: `${h.hit_id}: per_run entries must be [decision, reason_code] or null` })
      return
    }
    const flip = (FLIP_TYPES as readonly string[]).includes(h.flip_type as string) ? (h.flip_type as FlipType) : null
    if (!flip || typeof h.stable !== 'boolean') {
      issues.push({ line: i + 1, message: `${h.hit_id}: needs stable (boolean) and a known flip_type` })
      return
    }
    seen.add(h.hit_id)
    hits.push({
      hit_id: h.hit_id,
      alert_id: strOrNull(h.alert_id),
      per_run: cells as RunCell[],
      stable: h.stable,
      flip_type: flip,
      modal_decision: isDecision(h.modal_decision) ? h.modal_decision : null,
      modal_reason_code: strOrNull(h.modal_reason_code),
      llm_used: boolOrNull(h.llm_used),
      fragility: strOrNull(h.fragility),
    })
  })

  const cc = isObj(doc.config_check) ? doc.config_check : null
  const ident = cc && cc.available === true && isObj(cc.all_identical) ? cc.all_identical : null
  const llm = isObj(doc.llm_sensitivity) ? num(doc.llm_sensitivity.n_sensitive) : null

  return {
    report: {
      run_labels: labels ?? Array.from({ length: nRuns }, (_, i) => `run ${i + 1}`),
      n_runs: nRuns,
      generated_at: strOrNull(meta.generated_at),
      summary: {
        n_hits: num(summary.n_hits),
        judges_stable_hits: num(summary.judges_stable_hits),
        judges_metric: num(summary.judges_metric),
        judges_flip_hits: num(summary.judges_flip_hits),
        judges_flips_all_llm_used: boolOrNull(summary.judges_flips_all_llm_used),
      },
      config_identical: ident ? Object.fromEntries(Object.entries(ident).map(([k, v]) => [k, boolOrNull(v)])) : null,
      llm_sensitive: llm,
      hits,
    },
    issues,
  }
}

/** Present in every run with one decision and one reason code (the judges' rule). */
export function isJudgesStable(h: ReproHit): boolean {
  const first = h.per_run[0]
  return h.per_run.every((c) => c !== null && first !== null && c.decision === first.decision && c.reason_code === first.reason_code)
}

/**
 * A clear that ever flipped: DIFFERENT_ENTITY in at least one run, and in some run the
 * hit is not DIFFERENT_ENTITY (another decision, or missing). A change of reason code
 * between two clears is not counted here (it is still a judges flip). Must be 0.
 */
export function isFlippedClear(h: ReproHit): boolean {
  const cleared = h.per_run.some((c) => c?.decision === 'DIFFERENT_ENTITY')
  return cleared && h.per_run.some((c) => c === null || c.decision !== 'DIFFERENT_ENTITY')
}

/**
 * Unstable = anything the report does not mark stable (flip_type other than none: decision,
 * code, evidence or other), plus anything that fails the judges' rule on per_run.
 * Exported for the Audit screen's filter. Sorted.
 */
export function getUnstableHitIds(report: ReproReport | null): string[] {
  if (!report) return []
  return report.hits
    .filter((h) => !h.stable || !isJudgesStable(h))
    .map((h) => h.hit_id)
    .sort()
}

export interface ReproMetrics {
  n_hits: number
  judges_stable: number
  /** judges_stable / n_hits, or null with no hits. */
  share: number | null
  flipped_clear_ids: string[]
  unstable_ids: string[]
  /** Where summary disagrees with the numbers recomputed from hits[]. */
  summary_mismatches: string[]
}

export function reproMetrics(r: ReproReport): ReproMetrics {
  const n = r.hits.length
  const stable = r.hits.filter(isJudgesStable).length
  const mismatches: string[] = []
  if (r.summary.n_hits !== null && r.summary.n_hits !== n) mismatches.push(`summary.n_hits is ${r.summary.n_hits}, hits[] has ${n}`)
  if (r.summary.judges_stable_hits !== null && r.summary.judges_stable_hits !== stable) {
    mismatches.push(`summary.judges_stable_hits is ${r.summary.judges_stable_hits}, recomputed ${stable}`)
  }
  return {
    n_hits: n,
    judges_stable: stable,
    share: n ? stable / n : null,
    flipped_clear_ids: r.hits.filter(isFlippedClear).map((h) => h.hit_id).sort(),
    unstable_ids: getUnstableHitIds(r),
    summary_mismatches: mismatches,
  }
}
