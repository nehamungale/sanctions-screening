import sampleSummariesText from '../../fixtures/alerts-trace.sample.jsonl?raw'
import sampleAlertsText from '../../fixtures/alerts.sample.jsonl?raw'
import sampleReproFlippedText from '../../fixtures/repro-flipped.sample.json?raw'
import sampleReproText from '../../fixtures/repro.sample.json?raw'
import sampleTraceText from '../../fixtures/trace.sample.jsonl?raw'
import { parseAlerts, parseTraceJsonl } from './parse.ts'
import { parseRepro } from './repro.ts'
import { EMPTY, type Loaded } from './model.ts'

export * from './model.ts'

/**
 * Bundled synthetic fixtures (static strings compiled into the app; no fetch).
 * mode 'full': trace + alerts + summaries + repro; 'trace': trace only; 'summaries': trace + summaries only.
 */
export function loadSample(mode: 'full' | 'trace' | 'summaries' = 'full', repro: 'stable' | 'flipped' = 'stable'): Loaded {
  const trace = { name: 'trace.sample.jsonl (bundled)', result: parseTraceJsonl(sampleTraceText) }
  const summaries = { name: 'alerts-trace.sample.jsonl (bundled)', result: parseAlerts(sampleSummariesText) }
  const reproFile =
    repro === 'flipped'
      ? { name: 'repro-flipped.sample.json (bundled)', result: parseRepro(sampleReproFlippedText) }
      : { name: 'repro.sample.json (bundled)', result: parseRepro(sampleReproText) }
  if (mode === 'trace') return { ...EMPTY, trace }
  if (mode === 'summaries') return { ...EMPTY, trace, summaries }
  return { trace, alerts: { name: 'alerts.sample.jsonl (bundled)', result: parseAlerts(sampleAlertsText) }, summaries, repro: reproFile }
}

