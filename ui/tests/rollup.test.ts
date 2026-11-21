// Run with: npm test  (node's built-in test runner + type stripping; no extra deps)
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

import { DECIDING_DIMS, REASON_LABELS, STATUS_LABELS, reasonLabel, statusFromSlug, undecidedText } from '../src/lib/labels.ts'
import { parseAlerts, parseTraceJsonl } from '../src/lib/parse.ts'
import { HIT_NOT_DECIDED, REASON_CODES, ROLLUP_STATUSES } from '../src/lib/policy.ts'
import { alertsFromHits, overviewCounts, rollUpAlerts } from '../src/lib/rollup.ts'
import { readComparison, readIdentity, unknownFacts } from '../src/lib/trace-view.ts'

const fixture = (name: string) => readFileSync(new URL(`../fixtures/${name}`, import.meta.url), 'utf8')

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

// --- B2: alerts.trace.jsonl (Stage 4 alert summaries) ---

test('alerts.trace.jsonl is recognised; hit list includes undecided ids', () => {
  const a = parseAlerts(fixture('sample.alerts.trace.jsonl'))
  assert.equal(a.kind, 'summaries')
  assert.deepEqual(a.issues, [])
  const a5 = a.alerts.find((x) => x.alert_id === 'A-000005')
  assert.deepEqual(a5?.hit_ids.sort(), ['H-000008', 'H-000009'])
  const t = parseTraceJsonl(fixture('sample.trace.jsonl'))
  const sums = rollUpAlerts(a.alerts, t.hits, { alertsVerified: true, rejected: t.rejected })
  assert.deepEqual(overviewCounts(sums, t.hits, true).pipelineDisagreements, [])
})

test('pipeline summary that disagrees with the roll-up is flagged', () => {
  const a = parseAlerts('{"alert_id":"A-1","alert_status":"CLEARED","hits":[{"hit_id":"H-1"}],"undecided_hit_ids":["H-2"]}')
  const t = parseTraceJsonl(line('H-1', 'DIFFERENT_ENTITY', 'DOB_MISMATCH'))
  const sums = rollUpAlerts(a.alerts, t.hits, { alertsVerified: true })
  assert.equal(sums[0].alert_status, 'NEEDS_REVIEW')
  assert.deepEqual(overviewCounts(sums, t.hits, true).pipelineDisagreements, ['A-1'])
})

// --- A: on-screen language ---

const INTERNAL = /ESCALATED|NEEDS_REVIEW|NOT_VERIFIED/

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
  for (const k of [{ kind: 'missing' }, { kind: 'invalid' }, { kind: 'conflict' }, { kind: 'alert_mismatch', trace_alert_id: 'A-2' }] as const) {
    assert.doesNotMatch(undecidedText(k), INTERNAL)
  }
  for (const c of REASON_CODES.DIFFERENT_ENTITY) assert.ok(DECIDING_DIMS[c]?.length, c)
})

// --- fixtures + panel readers ---

test('sample fixtures roll up as documented', () => {
  const t = parseTraceJsonl(fixture('sample.trace.jsonl'))
  const a = parseAlerts(fixture('sample.alerts.jsonl'))
  assert.deepEqual([t.issues, a.issues], [[], []])
  const sums = rollUpAlerts(a.alerts, t.hits, { alertsVerified: true, rejected: t.rejected })
  assert.deepEqual(
    sums.map((s) => [s.alert_id, s.alert_status]),
    [
      ['A-000001', 'CLEARED'],
      ['A-000002', 'ESCALATED'],
      ['A-000003', 'NEEDS_REVIEW'],
      ['A-000004', 'NEEDS_REVIEW'],
      ['A-000005', 'NEEDS_REVIEW'],
      ['A-000006', 'CLEARED'],
      ['A-000007', 'ESCALATED'],
    ],
  )
  const c = overviewCounts(sums, t.hits, true)
  assert.deepEqual(c.hitsByDecision, { DIFFERENT_ENTITY: 6, SAME_ENTITY: 2, REVIEW: 3 })
  assert.equal(c.hitsUndecided, 1)
})

test('panel readers: comparison has 6 dims, AMBIGUOUS lists candidates, unknowns named', () => {
  const t = parseTraceJsonl(fixture('sample.trace.jsonl'))
  for (const h of t.hits) assert.equal(readComparison(h.raw).length, 6, h.hit_id)
  const amb = t.hits.find((h) => h.verdict.customer_record_id === 'AMBIGUOUS')!
  assert.equal(readIdentity(amb.raw).candidates.length, 2)
  const rev = t.hits.find((h) => h.hit_id === 'H-000004')!
  assert.deepEqual(unknownFacts(readComparison(rev.raw)).map((u) => `${u.dim}:${u.missing}`), [
    'dob:hit',
    'country:hit',
    'death:both sides',
    'earliest_report:both sides',
  ])
  // malformed optional parts never throw
  assert.deepEqual(readIdentity({ identity: 'x' }).candidates, [])
  assert.deepEqual(readComparison({ comparison: [1, null, { dim: 'dob' }] }).map((r) => r.status), ['unknown'])
})
