import samplePipelineAlertsText from '../../fixtures/alerts-pipeline.sample.jsonl?raw'
import sampleAlertsText from '../../fixtures/alerts.sample.jsonl?raw'
import sampleReproFlippedText from '../../fixtures/repro-flipped.sample.json?raw'
import sampleReproText from '../../fixtures/repro.sample.json?raw'
import samplePipelineTraceText from '../../fixtures/trace-pipeline.sample.jsonl?raw'
import sampleTraceText from '../../fixtures/trace.sample.jsonl?raw'
import { parseAlerts, parseTraceJsonl } from './parse.ts'
import { parseRepro } from './repro.ts'
import { EMPTY, type Loaded } from './model.ts'

export * from './model.ts'

export type SampleKind = 'full' | 'trace' | 'summaries' | 'pipeline'

/**
 * Bundled synthetic fixtures (static strings compiled into the app; no fetch).
 * The sample trace carries its own Stage 4 alert summaries, as the real trace.jsonl does.
 * 'full': trace + alerts.jsonl + repro; 'trace' (alias 'summaries'): trace.jsonl only, so its
 * summary lines are the only alert list and nothing can show as Cleared;
 * 'pipeline': a trace written by the real stage4 code (tests/make-real-trace.py) + its alerts.jsonl.
 */
export function loadSample(mode: SampleKind = 'full', repro: 'stable' | 'flipped' = 'stable'): Loaded {
  if (mode === 'pipeline') {
    return {
      ...EMPTY,
      trace: { name: 'trace-pipeline.sample.jsonl (bundled, written by system/run)', result: parseTraceJsonl(samplePipelineTraceText) },
      alerts: { name: 'alerts-pipeline.sample.jsonl (bundled)', result: parseAlerts(samplePipelineAlertsText) },
    }
  }
  const trace = { name: 'trace.sample.jsonl (bundled)', result: parseTraceJsonl(sampleTraceText) }
  if (mode === 'trace' || mode === 'summaries') return { ...EMPTY, trace }
  const reproFile =
    repro === 'flipped'
      ? { name: 'repro-flipped.sample.json (bundled)', result: parseRepro(sampleReproFlippedText) }
      : { name: 'repro.sample.json (bundled)', result: parseRepro(sampleReproText) }
  return { ...EMPTY, trace, alerts: { name: 'alerts.sample.jsonl (bundled)', result: parseAlerts(sampleAlertsText) }, repro: reproFile }
}
