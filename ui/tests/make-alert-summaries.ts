// Regenerates fixtures/alerts-trace.sample.jsonl (Stage 4 alert summaries) from the sample fixtures.
// Run: node tests/make-alert-summaries.ts
import { readFileSync, writeFileSync } from 'node:fs'

import { parseAlerts, parseTraceJsonl } from '../src/lib/parse.ts'
import { rollUpAlerts } from '../src/lib/rollup.ts'
import { reasonLabel } from '../src/lib/labels.ts'

const f = (n: string) => new URL(`../fixtures/${n}`, import.meta.url)
const t = parseTraceJsonl(readFileSync(f('trace.sample.jsonl'), 'utf8'))
const a = parseAlerts(readFileSync(f('alerts.sample.jsonl'), 'utf8'))
const out = rollUpAlerts(a.alerts, t.hits, { alertsVerified: true, rejected: t.rejected }).map((s) => ({
  alert_id: s.alert_id,
  alert_status: s.alert_status,
  hits: s.hits
    .filter((h) => h.decision)
    .map((h) => ({ hit_id: h.hit_id, decision: h.decision, reason_code: h.reason_code, fragility: h.fragility })),
  blocking_hit_ids: s.blocking_hit_ids,
  undecided_hit_ids: s.undecided_hit_ids,
  ...(s.undecided_hit_ids.length ? { undecided_reason: s.undecided_hit_ids.map((id) => ({ hit_id: id, reason: 'HIT_NOT_DECIDED', missing: reasonLabel('HIT_NOT_DECIDED') })) } : {}),
}))
writeFileSync(f('alerts-trace.sample.jsonl'), out.map((o) => JSON.stringify(o)).join('\n') + '\n')
console.log(`wrote ${out.length} alert summaries`)
