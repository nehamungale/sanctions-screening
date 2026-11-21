// Run with: npm test  (node's built-in test runner + type stripping; no extra deps)
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

import {
  COMPARISON_STATUS_LABELS,
  DECIDING_DIMS,
  MISSING_TEXT,
  REASON_LABELS,
  STATUS_LABELS,
  comparisonStatusLabel,
  crossCheckText,
  missingSideText,
  reasonLabel,
  statusFromSlug,
  undecidedText,
} from '../src/lib/labels.ts'
import { parseAlerts, parseTraceJsonl } from '../src/lib/parse.ts'
import { HIT_NOT_DECIDED, REASON_CODES, ROLLUP_STATUSES } from '../src/lib/policy.ts'
import { alertsFromHits, crossCheckSummaries, overviewCounts, rollUpAlerts } from '../src/lib/rollup.ts'
import { factStatus, noComparisonReason, readComparison, readDecidingDims, readIdentity, unknownFacts } from '../src/lib/trace-view.ts'
import { buildModel, buildRepro, type Loaded } from '../src/lib/model.ts'
import {
  getUnstableHitIds, instabilityLabel, isDecisionFlip, isDecisionStable, isFlippedClear, isJudgesStable, isMissingOutput, isReasonOnlyChange, missingRuns, parseRepro, reproMetrics,
} from '../src/lib/repro.ts'
import { allHitRows, filterRows, NO_FILTERS, queueGroups, whatsMissingLine } from '../src/lib/worklist.ts'

const fixture = (name: string) => readFileSync(new URL(`../fixtures/${name}`, import.meta.url), 'utf8')
/** The alert summary lines stage4 appends to trace.jsonl, as a separate (legacy alerts.trace.jsonl) file. */
const summaryLines = (name = 'trace-crosscheck.sample.jsonl') =>
  fixture(name)
    .split('\n')
    .filter((l) => l.includes('"alert_status"'))
    .join('\n')

const rec = (hit_id: string, decision: string, reason_code: string, alert_id = 'A-1', extra: object = {}) => ({
  trace_schema: 1,
  hit_id,
  alert_id,
  verdict: { decision, reason_code, evidence: [] },
  ...extra,
})
const line = (...a: Parameters<typeof rec>) => JSON.stringify(rec(...a))

const roll = (lines: string[], hit_ids: string[], alertsVerified = true) => {
  const t = parseTraceJsonl(lines.join('\n'))
  return rollUpAlerts([{ alert_id: 'A-1', hit_ids }], t.hits, { alertsVerified, rejected: t.rejected })[0]
}

const INTERNAL = /ESCALATED|NEEDS_REVIEW|NOT_VERIFIED/

function loadFixtures(o: { alerts?: boolean; summaries?: boolean; crosscheck?: boolean }): Loaded {
  return {
    trace: { name: 't', result: parseTraceJsonl(fixture(o.crosscheck ? 'trace-crosscheck.sample.jsonl' : 'trace.sample.jsonl')) },
    alerts: o.alerts ? { name: 'a', result: parseAlerts(fixture('alerts.sample.jsonl')) } : null,
    summaries: o.summaries ? { name: 's', result: parseAlerts(summaryLines()) } : null,
    repro: null,
  }
}

// --- roll-up rule ---

test('all DIFFERENT_ENTITY -> CLEARED', () => {
  const s = roll([line('H-1', 'DIFFERENT_ENTITY', 'DOB_MISMATCH'), line('H-2', 'DIFFERENT_ENTITY', 'DECEASED')], ['H-1', 'H-2'])
  assert.equal(s.alert_status, 'CLEARED')
  assert.deepEqual(s.blocking_hit_ids, [])
})

test('SAME + REVIEW -> ESCALATED, both blocking', () => {
  const s = roll([line('H-1', 'SAME_ENTITY', 'NAME_DOB_MATCH'), line('H-2', 'REVIEW', 'INSUFFICIENT_DATA')], ['H-1', 'H-2'])
  assert.equal(s.alert_status, 'ESCALATED')
  assert.deepEqual(s.blocking_hit_ids, ['H-1', 'H-2'])
})

test('one REVIEW among clears -> NEEDS_REVIEW', () => {
  const s = roll([line('H-1', 'DIFFERENT_ENTITY', 'DOB_MISMATCH'), line('H-2', 'REVIEW', 'INSUFFICIENT_DATA')], ['H-1', 'H-2'])
  assert.equal(s.alert_status, 'NEEDS_REVIEW')
  assert.deepEqual(s.blocking_hit_ids, ['H-2'])
})

test('missing hit -> NEEDS_REVIEW, never CLEARED', () => {
  const s = roll([line('H-1', 'DIFFERENT_ENTITY', 'DOB_MISMATCH')], ['H-1', 'H-2'])
  assert.equal(s.alert_status, 'NEEDS_REVIEW')
  assert.deepEqual(s.undecided_hit_ids, ['H-2'])
  assert.deepEqual(s.hits[1].undecided, { kind: 'missing' })
})

test('missing hit + SAME -> ESCALATED', () => {
  assert.equal(roll([line('H-1', 'SAME_ENTITY', 'NAME_DOB_MATCH')], ['H-1', 'H-2']).alert_status, 'ESCALATED')
})

test('alert with no hit_ids is not vacuously CLEARED', () => {
  assert.equal(roll([], []).alert_status, 'NEEDS_REVIEW')
})

// --- B1: not verified without an alerts file; alert_id mismatch ---

test('without an alerts file, an all-DIFFERENT alert is NOT_VERIFIED, never CLEARED', () => {
  const t = parseTraceJsonl([line('H-1', 'DIFFERENT_ENTITY', 'DOB_MISMATCH'), line('H-2', 'SAME_ENTITY', 'NAME_DOB_MATCH', 'A-2')].join('\n'))
  const sums = rollUpAlerts(alertsFromHits(t.hits), t.hits, { alertsVerified: false })
  assert.deepEqual(sums.map((s) => s.alert_status), ['NOT_VERIFIED', 'ESCALATED'])
  const c = overviewCounts(sums, t.hits, false)
  assert.equal(c.alerts.CLEARED, 0)
  assert.equal(c.alerts.NOT_VERIFIED, 1)
})

test('hit whose own alert_id differs from the listing alert is undecided', () => {
  const s = roll([line('H-1', 'DIFFERENT_ENTITY', 'DOB_MISMATCH'), line('H-2', 'DIFFERENT_ENTITY', 'DOB_MISMATCH', 'A-9')], ['H-1', 'H-2'])
  assert.equal(s.alert_status, 'NEEDS_REVIEW')
  assert.deepEqual(s.undecided_hit_ids, ['H-2'])
  assert.deepEqual(s.hits[1].undecided, { kind: 'alert_mismatch', trace_alert_id: 'A-9' })
  assert.equal(s.hits[1].decision, null)
})

test('hit with no alert_id in its record is undecided', () => {
  const noAlert = JSON.stringify({ trace_schema: 1, hit_id: 'H-1', verdict: { decision: 'DIFFERENT_ENTITY', reason_code: 'DOB_MISMATCH' } })
  assert.equal(roll([noAlert], ['H-1']).alert_status, 'NEEDS_REVIEW')
})

// --- B2: duplicates ---

test('conflicting duplicate hit_id -> undecided (not first-wins)', () => {
  const lines = [line('H-1', 'DIFFERENT_ENTITY', 'DOB_MISMATCH'), line('H-1', 'REVIEW', 'INSUFFICIENT_DATA')]
  const t = parseTraceJsonl(lines.join('\n'))
  assert.equal(t.hits.length, 0)
  assert.deepEqual(t.rejected.get('H-1'), { kind: 'conflict' })
  const s = roll(lines, ['H-1'])
  assert.equal(s.alert_status, 'NEEDS_REVIEW')
  assert.deepEqual(s.hits[0].undecided, { kind: 'conflict' })
})

test('identical duplicates (any key order) are deduplicated with an info note', () => {
  const a = rec('H-1', 'DIFFERENT_ENTITY', 'DOB_MISMATCH')
  const b = Object.fromEntries(Object.entries(a).reverse())
  const t = parseTraceJsonl([JSON.stringify(a), JSON.stringify(b)].join('\n'))
  assert.equal(t.hits.length, 1)
  assert.equal(t.issues.length, 1)
  assert.equal(t.issues[0].severity, 'info')
  assert.equal(roll([JSON.stringify(a), JSON.stringify(b)], ['H-1']).alert_status, 'CLEARED')
})

test('a valid and an invalid record for the same hit -> undecided', () => {
  const s = roll([line('H-1', 'DIFFERENT_ENTITY', 'DOB_MISMATCH'), line('H-1', 'DIFFERENT_ENTITY', 'NAME_DOB_MATCH')], ['H-1'])
  assert.deepEqual(s.hits[0].undecided, { kind: 'invalid' })
  assert.equal(s.alert_status, 'NEEDS_REVIEW')
})

test('bad lines are reported, not thrown', () => {
  const r = parseTraceJsonl(
    ['{oops', '[]', line('H-1', 'DIFFERENT_ENTITY', 'NAME_DOB_MATCH'), line('H-2', 'MAYBE', 'X'), line('H-3', 'REVIEW', 'INSUFFICIENT_DATA'), '{"alert_id":"A-1","alert_status":"CLEARED","hits":[]}', '{"run_id":"r1"}'].join('\n'),
  )
  assert.equal(r.hits.length, 1)
  assert.equal(r.issues.filter((i) => i.severity !== 'info').length, 4)
  assert.equal(r.skipped, 2)
  assert.deepEqual([...r.rejected.keys()].sort(), ['H-1', 'H-2'])
})

// --- B2: Stage 4 alert summaries (appended to trace.jsonl) ---

const A9_DISAGREES = [{ kind: 'status', alert_id: 'A-SYN009', pipeline: 'CLEARED', ui: 'NEEDS_REVIEW' }]

test('summary lines inside trace.jsonl are split from hit lines; hit list includes undecided ids', () => {
  const t = parseTraceJsonl(fixture('trace.sample.jsonl'))
  assert.deepEqual(t.issues, [])
  assert.equal(t.hits.length, 14)
  assert.equal(t.skipped, 9)
  const s = t.summaries!
  assert.equal(s.kind, 'summaries')
  assert.deepEqual([s.issues, s.alerts, s.bad_lines], [[], [], 0])
  assert.equal(s.summaries.length, 9)
  assert.deepEqual(s.summaries.find((x) => x.alert_id === 'A-SYN005')?.hit_ids.sort(), ['H-SYN008', 'H-SYN009'])
  // a bad summary line is reported with its real line number in the trace, and is not a hit
  const bad = parseTraceJsonl(`${line('H-1', 'DIFFERENT_ENTITY', 'DOB_MISMATCH')}\n{"alert_id":"A-1","alert_status":"WEIRD","hits":[]}\n`)
  assert.equal(bad.hits.length, 1)
  assert.equal(bad.summaries?.issues[0]?.line, 2)
})

test('B1: the trace alone (with its summary lines) never shows Cleared (Not verified instead)', () => {
  for (const crosscheck of [false, true]) {
    const m = buildModel(loadFixtures({ crosscheck }))!
    assert.equal(m.verified, false)
    assert.equal(m.alertSource, 'summaries')
    assert.equal(m.summarySource, 'trace')
    assert.equal(m.counts.alerts.CLEARED, 0)
    assert.equal(m.counts.alerts.NOT_VERIFIED, 2)
    // pipeline CLEARED vs UI Not verified is not a disagreement; the broken A-SYN009 summary is
    assert.deepEqual(m.crossCheck?.problems, crosscheck ? A9_DISAGREES : [])
  }
})

test('B1: default sample: Cleared shows and the cross-check agrees; crosscheck sample flags only the broken summary', () => {
  const m = buildModel(loadFixtures({ alerts: true }))!
  assert.equal(m.counts.alerts.CLEARED, 2)
  assert.deepEqual(m.crossCheck?.problems, [])
  const x = buildModel(loadFixtures({ alerts: true, crosscheck: true }))!
  assert.equal(x.counts.alerts.CLEARED, 2)
  assert.deepEqual(x.crossCheck?.problems, A9_DISAGREES)
  // the two samples differ only in that one summary line
  const diff = fixture('trace.sample.jsonl').split('\n').filter((l, i) => l !== fixture('trace-crosscheck.sample.jsonl').split('\n')[i])
  assert.equal(diff.length, 1)
  assert.match(diff[0], /"alert_id":"A-SYN009","alert_status":"NEEDS_REVIEW"/)
})

test('MUST KEEP: a pipeline summary that says CLEARED never makes an alert Cleared', () => {
  for (const alerts of [false, true]) {
    const m = buildModel(loadFixtures({ alerts, crosscheck: true }))!
    assert.equal(m.summariesById.get('A-SYN009')!.alert_status, 'NEEDS_REVIEW')
    assert.deepEqual(m.summariesById.get('A-SYN009')!.undecided_hit_ids, ['H-SYN014'])
  }
  // summaries only, every hit missing from the trace: still not Cleared
  const t = parseTraceJsonl('{"alert_id":"A-1","alert_status":"CLEARED","blocking_hit_ids":[],"hits":[{"hit_id":"H-1","decision":"DIFFERENT_ENTITY"}],"undecided_hit_ids":[]}')
  const m = buildModel({ trace: { name: 't', result: t }, alerts: null, summaries: null, repro: null })!
  assert.equal(m.summariesById.get('A-1')!.alert_status, 'NEEDS_REVIEW')
  assert.equal(m.counts.alerts.CLEARED, 0)
})

test('back-compat: a separate summaries file takes the place of the trace’s summary lines', () => {
  const m = buildModel(loadFixtures({ alerts: true, summaries: true }))!
  assert.equal(m.summarySource, 'file')
  assert.equal(m.counts.alerts.CLEARED, 2)
  assert.deepEqual(m.crossCheck?.problems, A9_DISAGREES)
})

test('not_decided: true in a trace record counts as no decision, not as REVIEW', () => {
  const s = roll([line('H-1', 'DIFFERENT_ENTITY', 'DOB_MISMATCH'), line('H-2', 'REVIEW', 'INSUFFICIENT_DATA', 'A-1', { not_decided: true })], ['H-1', 'H-2'])
  assert.equal(s.alert_status, 'NEEDS_REVIEW')
  assert.deepEqual(s.undecided_hit_ids, ['H-2'])
  assert.deepEqual(s.hits[1].undecided, { kind: 'not_decided' })
})

test('cross-check flags a pipeline status or hit list that disagrees', () => {
  const pipeline = parseAlerts('{"alert_id":"A-1","alert_status":"CLEARED","hits":[{"hit_id":"H-1"}]}').summaries
  const t = parseTraceJsonl(line('H-1', 'DIFFERENT_ENTITY', 'DOB_MISMATCH'))
  const sums = rollUpAlerts([{ alert_id: 'A-1', hit_ids: ['H-1', 'H-2'] }], t.hits, { alertsVerified: true })
  const kinds = crossCheckSummaries(sums, pipeline, true).map((p) => p.kind).sort()
  assert.deepEqual(kinds, ['hit_ids', 'status'])
  for (const p of crossCheckSummaries(sums, pipeline, true)) assert.doesNotMatch(crossCheckText(p), INTERNAL)
})

test('B2: a hit filed under the wrong alert counts as undecided only, not in decision totals', () => {
  const t = parseTraceJsonl([line('H-1', 'DIFFERENT_ENTITY', 'DOB_MISMATCH'), line('H-2', 'SAME_ENTITY', 'NAME_DOB_MATCH', 'A-9')].join('\n'))
  const sums = rollUpAlerts([{ alert_id: 'A-1', hit_ids: ['H-1', 'H-2'] }], t.hits, { alertsVerified: true })
  const c = overviewCounts(sums, t.hits, true)
  assert.deepEqual(c.hitsByDecision, { DIFFERENT_ENTITY: 1, SAME_ENTITY: 0, REVIEW: 0 })
  assert.equal(c.hitsDecided, 1)
  assert.equal(c.hitsMisfiled, 1)
  assert.equal(c.hitsUndecided, 1)
  assert.equal(c.hitsByReason.find((r) => r.reason_code === 'NAME_DOB_MATCH')?.count, 0)
})

// --- A: on-screen language ---

test('status labels use the brief’s words and never internal names', () => {
  assert.equal(STATUS_LABELS.CLEARED.label, 'Cleared')
  assert.equal(STATUS_LABELS.ESCALATED.label, 'Goes to compliance team')
  assert.equal(STATUS_LABELS.NEEDS_REVIEW.label, 'Needs review')
  assert.equal(STATUS_LABELS.NOT_VERIFIED.label, 'Not verified')
  assert.equal(STATUS_LABELS.CLEARED.sub, 'every hit is DIFFERENT_ENTITY')
  assert.equal(STATUS_LABELS.ESCALATED.sub, 'at least one hit is SAME_ENTITY')
  assert.equal(STATUS_LABELS.NEEDS_REVIEW.sub, 'no SAME_ENTITY, at least one hit REVIEW or undecided')
  for (const s of ROLLUP_STATUSES) {
    const l = STATUS_LABELS[s]
    assert.doesNotMatch(`${l.label} ${l.sub} ${l.slug}`, INTERNAL, s)
    assert.equal(statusFromSlug(l.slug), s)
  }
})

test('every reason code has a plain-English label', () => {
  const codes = [...Object.values(REASON_CODES).flat(), HIT_NOT_DECIDED]
  for (const c of codes) assert.ok(REASON_LABELS[c] && REASON_LABELS[c].length > 5, c)
  assert.equal(reasonLabel(HIT_NOT_DECIDED), 'hit has no decision')
  for (const t of Object.values(REASON_LABELS)) assert.doesNotMatch(t, INTERNAL)
  for (const k of [{ kind: 'missing' }, { kind: 'invalid' }, { kind: 'conflict' }, { kind: 'alert_mismatch', trace_alert_id: 'A-2' }, { kind: 'not_decided' }] as const) {
    assert.doesNotMatch(undecidedText(k), INTERNAL)
  }
  for (const c of REASON_CODES.DIFFERENT_ENTITY) assert.ok(DECIDING_DIMS[c]?.length, c)
})

// --- fixtures + panel readers ---

test('sample fixtures roll up as documented', () => {
  const t = parseTraceJsonl(fixture('trace.sample.jsonl'))
  const a = parseAlerts(fixture('alerts.sample.jsonl'))
  assert.deepEqual([t.issues, a.issues], [[], []])
  const sums = rollUpAlerts(a.alerts, t.hits, { alertsVerified: true, rejected: t.rejected })
  assert.deepEqual(
    sums.map((s) => [s.alert_id, s.alert_status]),
    [
      ['A-SYN001', 'CLEARED'],
      ['A-SYN002', 'ESCALATED'],
      ['A-SYN003', 'NEEDS_REVIEW'],
      ['A-SYN004', 'NEEDS_REVIEW'],
      ['A-SYN005', 'NEEDS_REVIEW'],
      ['A-SYN006', 'CLEARED'],
      ['A-SYN007', 'ESCALATED'],
      ['A-SYN008', 'NEEDS_REVIEW'],
      ['A-SYN009', 'NEEDS_REVIEW'],
    ],
  )
  const c = overviewCounts(sums, t.hits, true)
  assert.deepEqual(c.hitsByDecision, { DIFFERENT_ENTITY: 7, SAME_ENTITY: 2, REVIEW: 4 })
  assert.equal(c.hitsDecided, 13)
  assert.equal(c.hitsUndecided, 2)
})

test('panel readers: comparison has 6 dims (or none, with a reason), AMBIGUOUS lists candidates, unknowns named', () => {
  const t = parseTraceJsonl(fixture('trace.sample.jsonl'))
  const noCmp = ['H-SYN013', 'H-SYN014']
  for (const h of t.hits) assert.equal(readComparison(h.raw).length, noCmp.includes(h.hit_id) ? 0 : 6, h.hit_id)
  const byId = (id: string) => t.hits.find((h) => h.hit_id === id)!
  assert.match(noComparisonReason(byId('H-SYN013').raw, null)!, /no matching customer record/)
  assert.match(noComparisonReason(byId('H-SYN014').raw, null)!, /has no decision/)
  assert.equal(noComparisonReason(byId('H-SYN001').raw, 'CUS-SYN001'), null)
  assert.deepEqual(readIdentity(byId('H-SYN013').raw).facts, [])
  const amb = t.hits.find((h) => h.verdict.customer_record_id === 'AMBIGUOUS')!
  const cands = readIdentity(amb.raw).candidates
  assert.equal(cands.length, 2)
  assert.deepEqual([cands[1].name, cands[1].dob, cands[1].country], [null, null, null])
  assert.equal(cands[0].country, 'GB, IE')
  const rev = t.hits.find((h) => h.hit_id === 'H-SYN004')!
  assert.deepEqual(unknownFacts(readComparison(rev.raw)).map((u) => `${u.dim}:${u.side}`), [
    'dob:hit',
    'country:hit',
    'death:both',
    'earliest_report:both',
  ])
  // malformed optional parts never throw
  assert.deepEqual(readIdentity({ identity: 'x' }).candidates, [])
  assert.deepEqual(readComparison({ comparison: [1, null, { dim: 'dob' }] }).map((r) => r.status), ['unknown'])
})

// --- 3 / 4: comparison wording ---

test('3: comparison statuses have plain-English labels; unknown raw values pass through', () => {
  assert.deepEqual(COMPARISON_STATUS_LABELS, { agree: 'agrees', contradict: 'contradicts', no_conflict: 'no conflict', unknown: 'can’t compare' })
  assert.equal(comparisonStatusLabel('no_conflict'), 'no conflict')
  assert.equal(comparisonStatusLabel('weird_value'), 'weird_value')
})

test('4: missing values are phrased plainly by side', () => {
  assert.equal(MISSING_TEXT.hit, 'not on list profile')
  assert.equal(MISSING_TEXT.customer, 'not in customer records')
  assert.equal(missingSideText('hit'), 'not on list profile')
  assert.equal(missingSideText('customer'), 'not in customer records')
  assert.match(missingSideText('both'), /not on list profile.*not in customer records/)
})

// --- 5: deciding dims ---

test('identity.facts: dob says verified/declared; name never says "verified" (it only means a comparison was computed)', () => {
  for (const name of ['trace.sample.jsonl', 'trace-pipeline.sample.jsonl']) {
    for (const h of parseTraceJsonl(fixture(name)).hits) {
      const facts = readIdentity(h.raw).facts
      for (const f of facts) {
        assert.ok(['dob', 'name', 'entity_type'].includes(f.name), `${h.hit_id} ${f.name}`)
        if (f.name === 'name') assert.doesNotMatch(factStatus(f), /verified/i, h.hit_id)
      }
    }
  }
  assert.equal(factStatus({ name: 'name', value: 'X', verified: true, source_id: null }), 'compared with the hit')
  assert.equal(factStatus({ name: 'dob', value: 'X', verified: true, source_id: null }), 'verified')
  assert.equal(factStatus({ name: 'dob', value: 'X', verified: false, source_id: null }), 'declared')
  assert.equal(factStatus({ name: 'entity_type', value: 'X', verified: null, source_id: null }), '—')
})

test('5: explicit deciding_dims wins; invalid falls back to the reason code; REVIEW has none', () => {
  // stage4 writes deciding_dims at the top level, [] for REVIEW codes
  for (const h of parseTraceJsonl(fixture('trace.sample.jsonl')).hits) {
    if (h.verdict.decision === 'REVIEW') assert.deepEqual(h.raw.deciding_dims, [], h.hit_id)
    else assert.equal(readDecidingDims(h.raw, h.verdict.reason_code).source, 'trace', h.hit_id)
  }
  assert.deepEqual(readDecidingDims({ deciding_dims: ['dob'] }, 'NAME_DOB_MATCH'), { dims: ['dob'], source: 'trace' })
  assert.deepEqual(readDecidingDims({ deciding_dims: ['nope'] }, 'NAME_DOB_MATCH'), { dims: ['name', 'dob'], source: 'derived' })
  assert.deepEqual(readDecidingDims({}, 'DOB_MISMATCH'), { dims: ['dob'], source: 'derived' })
  assert.deepEqual(readDecidingDims({}, 'INSUFFICIENT_DATA'), { dims: [], source: 'none' })
})

// --- 6: repro.json ---

test('repro sample: official 8/11, decision-stable 9/11, each case named, 0 flipped clears', () => {
  const r = parseRepro(fixture('repro.sample.json'))
  assert.deepEqual(r.issues, [])
  const m = reproMetrics(r.report!)
  assert.equal(m.n_hits, 11)
  assert.equal(m.official_stable, 8)
  assert.equal(m.decision_stable, 9)
  assert.deepEqual(m.flipped_clear_ids, [])
  assert.deepEqual(m.reason_only_ids, ['H-SYN002'])
  assert.deepEqual(m.decision_flip_ids, ['H-SYN006'])
  assert.deepEqual(m.missing_output_ids, ['H-SYN007'])
  assert.deepEqual(m.other_change_ids, ['H-SYN004'])
  assert.deepEqual(m.unstable_ids, ['H-SYN002', 'H-SYN006', 'H-SYN007'])
  assert.deepEqual(m.summary_mismatches, [])
  assert.equal(r.report!.summary.judges_stable_hits, m.official_stable)
  assert.deepEqual(getUnstableHitIds(r.report), ['H-SYN002', 'H-SYN006', 'H-SYN007'])
  assert.deepEqual(getUnstableHitIds(null), [])
  const byId = (id: string) => r.report!.hits.find((h) => h.hit_id === id)!
  assert.equal(instabilityLabel(byId('H-SYN007')), 'missing output: missing in run 3')
  assert.equal(instabilityLabel(byId('H-SYN002')), 'reason code changed (not a flip)')
  assert.equal(instabilityLabel(byId('H-SYN006')), 'verdict changed')
})

test('repro flipped variant: decision-flip clear (H-SYN008) and missing clear (H-SYN010)', () => {
  const r = parseRepro(fixture('repro-flipped.sample.json')).report!
  const m = reproMetrics(r)
  assert.deepEqual(m.flipped_clear_ids, ['H-SYN008', 'H-SYN010'])
  assert.deepEqual(m.missing_output_ids, ['H-SYN007'])
  assert.equal(m.official_stable, 6)
  assert.equal(m.decision_stable, 7)
  assert.equal(instabilityLabel(r.hits.find((h) => h.hit_id === 'H-SYN010')!), 'clear flipped: missing in run 4')
})

test('flipped clear vs missing output vs reason-only change', () => {
  const h = (cells: ([string, string] | null)[]) => ({
    hit_id: 'H', alert_id: null, stable: false, flip_type: 'decision' as const, modal_decision: null, modal_reason_code: null, llm_used: null, fragility: null,
    per_run: cells.map((c) => (c ? { decision: c[0] as 'DIFFERENT_ENTITY', reason_code: c[1] } : null)),
  })
  const missingClear = h([['DIFFERENT_ENTITY', 'DOB_MISMATCH'], null])
  assert.equal(isFlippedClear(missingClear), true)
  assert.equal(isMissingOutput(missingClear), false)
  assert.deepEqual(missingRuns(missingClear), [1])
  const missingReview = h([['REVIEW', 'INSUFFICIENT_DATA'], null])
  assert.equal(isFlippedClear(missingReview), false)
  assert.equal(isMissingOutput(missingReview), true)
  assert.equal(isJudgesStable(missingReview), false)
  assert.equal(isDecisionStable(missingReview), false)
  assert.equal(isMissingOutput(h([['SAME_ENTITY', 'NAME_DOB_MATCH'], null, ['SAME_ENTITY', 'NAME_DOB_MATCH']])), true)
  assert.equal(isFlippedClear(h([null, null])), false)
  assert.equal(isFlippedClear(h([['DIFFERENT_ENTITY', 'DOB_MISMATCH'], ['REVIEW', 'INSUFFICIENT_DATA']])), true)
  assert.equal(isFlippedClear(h([['DIFFERENT_ENTITY', 'DOB_MISMATCH'], ['REVIEW', 'INSUFFICIENT_DATA'], null])), true)
  const reasonOnly = h([['DIFFERENT_ENTITY', 'DOB_MISMATCH'], ['DIFFERENT_ENTITY', 'LOCATION_MISMATCH']])
  assert.equal(isFlippedClear(reasonOnly), false)
  assert.equal(isReasonOnlyChange(reasonOnly), true)
  assert.equal(isJudgesStable(reasonOnly), false)
  assert.equal(isDecisionStable(reasonOnly), true)
  assert.equal(isFlippedClear(h([['REVIEW', 'INSUFFICIENT_DATA'], ['SAME_ENTITY', 'NAME_DOB_MATCH']])), false)
  assert.equal(isDecisionFlip(h([['REVIEW', 'INSUFFICIENT_DATA'], ['SAME_ENTITY', 'NAME_DOB_MATCH']])), true)
})

test('repro parsing is defensive: bad JSON, wrong version, bad rows', () => {
  assert.equal(parseRepro('{').report, null)
  assert.equal(parseRepro('{"schema_version":2}').report, null)
  const r = parseRepro(
    JSON.stringify({
      schema_version: 1,
      meta: { run_labels: ['a', 'b'] },
      summary: { n_runs: 2, n_hits: 3, judges_stable_hits: 1 },
      hits: [
        { hit_id: 'H-1', per_run: [['REVIEW', 'INSUFFICIENT_DATA'], ['REVIEW', 'INSUFFICIENT_DATA']], stable: true, flip_type: 'none' },
        { hit_id: 'H-2', per_run: [['MAYBE', 'X'], null], stable: false, flip_type: 'decision' },
        { hit_id: 'H-3', per_run: [null], stable: false, flip_type: 'other' },
        { per_run: [] },
      ],
    }),
  )
  assert.equal(r.report?.hits.length, 1)
  assert.equal(r.issues.length, 3)
  assert.deepEqual(reproMetrics(r.report!).summary_mismatches.length, 1)
  assert.ok(buildRepro({ name: 'x', result: r }))
})

// --- queue and audit ---

test('queue: REVIEW, then no decision, then SAME_ENTITY, each with a one-line what’s missing', () => {
  const m = buildModel(loadFixtures({ alerts: true }))!
  const g = queueGroups(m)
  assert.deepEqual(g.map((x) => [x.id, x.rows.map((r) => r.hit_id)]), [
    ['review', ['H-SYN004', 'H-SYN006', 'H-SYN007', 'H-SYN013']],
    ['undecided', ['H-SYN009', 'H-SYN014']],
    ['same', ['H-SYN003', 'H-SYN012']],
  ])
  const lines = Object.fromEntries(g.flatMap((x) => x.rows).map((r) => [r.hit_id, whatsMissingLine(r)]))
  assert.equal(lines['H-SYN004'], 'Not on list profile: date of birth, country, earliest report')
  assert.match(lines['H-SYN006'], /declared, not verified/)
  assert.match(lines['H-SYN007'], /2 customers fit \(CUS-SYN004, CUS-SYN005\)/)
  assert.equal(lines['H-SYN009'], 'No record for this hit in the trace')
  assert.match(lines['H-SYN013'], /^No comparison: no matching customer record/)
  assert.match(lines['H-SYN014'], /not decided/)
  assert.equal(lines['H-SYN003'], 'Confirmed on name, date of birth; nothing contradicts')
  for (const l of Object.values(lines)) assert.doesNotMatch(l, INTERNAL)
})

test('audit: all hits incl. undecided; filters combine; unstable uses the repro set', () => {
  const m = buildModel(loadFixtures({ alerts: true }))!
  const rows = allHitRows(m)
  assert.equal(rows.length, 15)
  const unstable = new Set(getUnstableHitIds(parseRepro(fixture('repro.sample.json')).report))
  assert.equal(filterRows(rows, NO_FILTERS, unstable).length, 15)
  assert.deepEqual(filterRows(rows, { ...NO_FILTERS, verdict: 'REVIEW' }, unstable).map((r) => r.hit_id), ['H-SYN004', 'H-SYN006', 'H-SYN007', 'H-SYN013'])
  assert.deepEqual(filterRows(rows, { ...NO_FILTERS, verdict: 'none' }, unstable).map((r) => r.hit_id), ['H-SYN009', 'H-SYN014'])
  assert.deepEqual(filterRows(rows, { ...NO_FILTERS, code: 'DOB_MISMATCH' }, unstable).map((r) => r.hit_id), ['H-SYN001'])
  assert.deepEqual(filterRows(rows, { ...NO_FILTERS, unstable: true }, unstable).map((r) => r.hit_id), ['H-SYN002', 'H-SYN006', 'H-SYN007'])
  assert.deepEqual(filterRows(rows, { ...NO_FILTERS, llm: 'yes' }, unstable).map((r) => r.hit_id), ['H-SYN006'])
  assert.equal(filterRows(rows, { ...NO_FILTERS, fragility: 'thin', verdict: 'DIFFERENT_ENTITY' }, unstable).length, 4)
})

// --- security review fixes ---

test('duplicate alert lines: union of hit_ids, never Cleared, warning names the lines', () => {
  const a = parseAlerts(fixture('alerts-duplicate.sample.jsonl'))
  const a1 = a.alerts.find((x) => x.alert_id === 'A-SYN001')!
  assert.deepEqual([...a1.hit_ids].sort(), ['H-SYN001', 'H-SYN002', 'H-SYN099'])
  assert.deepEqual(a1.conflicting_lines, [1, 2])
  assert.ok(a.issues.some((i) => i.severity !== 'info' && /A-SYN001: conflicting lines 1, 2/.test(i.message)))
  // identical duplicates merge quietly
  assert.equal(a.alerts.find((x) => x.alert_id === 'A-SYN006')?.conflicting_lines, undefined)
  assert.ok(a.issues.some((i) => i.severity === 'info' && /A-SYN006/.test(i.message)))
  const m = buildModel({ ...loadFixtures({}), alerts: { name: 'dup', result: a } })!
  const s1 = m.summariesById.get('A-SYN001')!
  assert.equal(s1.alert_status, 'NEEDS_REVIEW')
  assert.deepEqual(s1.undecided_hit_ids, ['H-SYN099'])
  assert.deepEqual(m.conflictingAlerts, [{ alert_id: 'A-SYN001', lines: [1, 2] }])
  assert.equal(m.summariesById.get('A-SYN006')!.alert_status, 'CLEARED')
})

test('conflicting lines block a clear even when every listed hit is DIFFERENT_ENTITY', () => {
  const a = parseAlerts(['{"alert_id":"A-1","hit_ids":["H-1"]}', '{"alert_id":"A-1","hit_ids":["H-1"],"note":"x"}'].join('\n'))
  const t = parseTraceJsonl(line('H-1', 'DIFFERENT_ENTITY', 'DOB_MISMATCH'))
  assert.equal(rollUpAlerts(a.alerts, t.hits, { alertsVerified: true })[0].alert_status, 'NEEDS_REVIEW')
})

test('duplicate summary lines are flagged in the cross-check', () => {
  const p = parseAlerts(['{"alert_id":"A-1","alert_status":"CLEARED","hits":[{"hit_id":"H-1"}]}', '{"alert_id":"A-1","alert_status":"NEEDS_REVIEW","hits":[{"hit_id":"H-1"}]}'].join('\n'))
  assert.deepEqual(p.summaries[0].conflicting_lines, [1, 2])
  const t = parseTraceJsonl(line('H-1', 'DIFFERENT_ENTITY', 'DOB_MISMATCH'))
  const sums = rollUpAlerts(p.summaries, t.hits, { alertsVerified: false })
  assert.equal(sums[0].alert_status, 'NEEDS_REVIEW')
  assert.ok(crossCheckSummaries(sums, p.summaries, false).some((x) => x.kind === 'duplicate'))
})

test('Q1: conflicting duplicate lines + a SAME_ENTITY hit stay "Goes to compliance team", warning kept', () => {
  const a = parseAlerts(['{"alert_id":"A-1","hit_ids":["H-1","H-2"]}', '{"alert_id":"A-1","hit_ids":["H-1"]}'].join('\n'))
  const t = parseTraceJsonl([line('H-1', 'SAME_ENTITY', 'NAME_DOB_MATCH'), line('H-2', 'DIFFERENT_ENTITY', 'DOB_MISMATCH')].join('\n'))
  const [s1] = rollUpAlerts(a.alerts, t.hits, { alertsVerified: true })
  assert.equal(s1.alert_status, 'ESCALATED')
  assert.equal(STATUS_LABELS[s1.alert_status].label, 'Goes to compliance team')
  assert.deepEqual(s1.conflicting_lines, [1, 2])
  const m = buildModel({ trace: { name: 't', result: t }, alerts: { name: 'alerts.jsonl', result: a }, summaries: null, repro: null } as Loaded)!
  assert.deepEqual(m.conflictingAlerts, [{ alert_id: 'A-1', lines: [1, 2] }])
  assert.equal(m.summariesById.get('A-1')!.alert_status, 'ESCALATED')
  assert.equal(m.counts.alerts.ESCALATED, 1)
})

test('MUST-FIX 2: only alerts.jsonl lines verify; a summaries file in the alerts slot does not', () => {
  const summariesFile = { name: 'alerts.trace.jsonl', result: parseAlerts(summaryLines()) }
  const m = buildModel({ ...loadFixtures({}), alerts: summariesFile })!
  assert.equal(m.verified, false)
  assert.equal(m.counts.alerts.CLEARED, 0)
})

test('unreadable alert lines withhold every clear', () => {
  const text = fixture('alerts.sample.jsonl') + '{broken\n{"alert_id":"A-SYN099"}\n'
  const a = parseAlerts(text)
  assert.equal(a.bad_lines, 2)
  const m = buildModel({ ...loadFixtures({}), alerts: { name: 'a', result: a } })!
  assert.equal(m.verified, false)
  assert.equal(m.badAlertLines, 2)
  assert.equal(m.counts.alerts.CLEARED, 0)
  assert.equal(m.counts.alerts.NOT_VERIFIED, 2)
})

// --- real stage4 trace shape ---

const keys = (o: unknown) => Object.keys(o as object).sort().join(',')

test('real pipeline trace (written by system/run on synthetic data) loads cleanly and agrees with its own summaries', () => {
  const t = parseTraceJsonl(fixture('trace-pipeline.sample.jsonl'))
  const a = parseAlerts(fixture('alerts-pipeline.sample.jsonl'))
  assert.deepEqual([t.issues, a.issues, t.summaries?.issues], [[], [], []])
  assert.equal(t.hits.length, 8)
  assert.equal(t.summaries?.summaries.length, 5)
  const m = buildModel({ trace: { name: 't', result: t }, alerts: { name: 'a', result: a }, summaries: null, repro: null })!
  assert.deepEqual(
    m.summaries.map((s) => [s.alert_id, s.alert_status]),
    [['A-SYN101', 'CLEARED'], ['A-SYN102', 'ESCALATED'], ['A-SYN103', 'NEEDS_REVIEW'], ['A-SYN104', 'NEEDS_REVIEW'], ['A-SYN105', 'NEEDS_REVIEW']],
  )
  assert.deepEqual(m.crossCheck?.problems, [])
  assert.deepEqual(m.summariesById.get('A-SYN105')!.undecided_hit_ids, ['H-SYN109'])
  const h7 = m.hitsById.get('H-SYN107')!
  assert.match(noComparisonReason(h7.raw, h7.verdict.customer_record_id)!, /no matching customer record/)
  assert.deepEqual(m.hitsById.get('H-SYN105')!.raw.deciding_dims, [])
  for (const h of t.hits) assert.equal(h.badges?.rules_version, 'stage4-r1')
})

test('hand-written sample hits use exactly the field names the stage4 emitter writes', () => {
  const real = parseTraceJsonl(fixture('trace-pipeline.sample.jsonl')).hits[0].raw as Record<string, any>
  const sample = parseTraceJsonl(fixture('trace.sample.jsonl')).hits.map((h) => h.raw as Record<string, any>)
  for (const h of sample) {
    assert.equal(keys(h), keys(real), h.hit_id)
    for (const k of ['verdict', 'badges', 'identity']) assert.equal(keys(h[k]), keys(real[k]), `${h.hit_id} ${k}`)
    for (const r of h.comparison) assert.equal(keys(r), keys(real.comparison[0]), h.hit_id)
    for (const s of h.steps) assert.equal(keys(s), keys(real.steps[0]), h.hit_id)
    for (const c of h.identity.candidates) assert.equal(keys(c), keys(real.identity.candidates[0]), h.hit_id)
    for (const r of h.comparison) assert.ok(['agree', 'contradict', 'unknown'].includes(r.status), h.hit_id)
    assert.deepEqual(h.llm_calls, [])
  }
})

test('live: system/run output loads (set STAGE4_REPO to a checkout to run the pipeline)', { skip: !process.env.STAGE4_REPO }, async () => {
  const { execFileSync } = await import('node:child_process')
  const { mkdtempSync, rmSync } = await import('node:fs')
  const { tmpdir } = await import('node:os')
  const { join } = await import('node:path')
  const dir = mkdtempSync(join(tmpdir(), 'stage4-trace-'))
  try {
    execFileSync('python3', [new URL('./make-real-trace.py', import.meta.url).pathname, process.env.STAGE4_REPO!, dir])
    const raw = parseTraceJsonl(readFileSync(join(dir, 'trace.raw.jsonl'), 'utf8'))
    const a = parseAlerts(readFileSync(join(dir, 'data', 'alerts.jsonl'), 'utf8'))
    assert.deepEqual([raw.issues, a.issues], [[], []])
    const m = buildModel({ trace: { name: 't', result: raw }, alerts: { name: 'a', result: a }, summaries: null, repro: null })!
    assert.deepEqual(m.crossCheck?.problems, [])
    assert.equal(m.counts.alerts.CLEARED, 1)
    // the committed fixture is this run with the IDs rewritten
    assert.equal(readFileSync(join(dir, 'trace.jsonl'), 'utf8'), fixture('trace-pipeline.sample.jsonl'))
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})
