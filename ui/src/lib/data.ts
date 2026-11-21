import samplePipelineAlertsText from '../../fixtures/alerts-pipeline.sample.jsonl?raw'
import sampleAlertsText from '../../fixtures/alerts.sample.jsonl?raw'
import sampleReproFlippedText from '../../fixtures/repro-flipped.sample.json?raw'
import sampleReproText from '../../fixtures/repro.sample.json?raw'
import sampleCrosscheckTraceText from '../../fixtures/trace-crosscheck.sample.jsonl?raw'
import samplePipelineTraceText from '../../fixtures/trace-pipeline.sample.jsonl?raw'
import sampleTraceText from '../../fixtures/trace.sample.jsonl?raw'
import { parseAlerts, parseTraceJsonl } from './parse.ts'
import { parseRepro } from './repro.ts'
import localRun from 'virtual:local-run'
import { EMPTY, type Loaded } from './model.ts'

export * from './model.ts'

export type SampleKind = 'full' | 'trace' | 'summaries' | 'pipeline' | 'crosscheck'

/**
 * Bundled synthetic fixtures (static strings compiled into the app; no fetch).
 * The sample trace carries its own Stage 4 alert summaries, as the real trace.jsonl does.
 * 'full': trace + alerts.jsonl + repro; 'trace' (alias 'summaries'): trace.jsonl only, so its
 * summary lines are the only alert list and nothing can show as Cleared;
 * 'pipeline': a trace written by the real stage4 code (tests/make-real-trace.py) + its alerts.jsonl.
 * 'crosscheck': the full sample, but one pipeline summary (A-SYN009) wrongly says Cleared, to show the cross-check.
 */
export function loadSample(mode: SampleKind = 'full', repro: 'stable' | 'flipped' = 'stable'): Loaded {
  if (mode === 'pipeline') {
    return {
      ...EMPTY,
      trace: { name: 'trace-pipeline.sample.jsonl (bundled, written by system/run)', result: parseTraceJsonl(samplePipelineTraceText) },
      alerts: { name: 'alerts-pipeline.sample.jsonl (bundled)', result: parseAlerts(samplePipelineAlertsText) },
    }
  }
  const trace =
    mode === 'crosscheck'
      ? { name: 'trace-crosscheck.sample.jsonl (bundled; A-SYN009 summary deliberately wrong)', result: parseTraceJsonl(sampleCrosscheckTraceText) }
      : { name: 'trace.sample.jsonl (bundled)', result: parseTraceJsonl(sampleTraceText) }
  if (mode === 'trace' || mode === 'summaries') return { ...EMPTY, trace }
  const reproFile =
    repro === 'flipped'
      ? { name: 'repro-flipped.sample.json (bundled)', result: parseRepro(sampleReproFlippedText) }
      : { name: 'repro.sample.json (bundled)', result: parseRepro(sampleReproText) }
  return { ...EMPTY, trace, alerts: { name: 'alerts.sample.jsonl (bundled)', result: parseAlerts(sampleAlertsText) }, repro: reproFile }
}

/** True when the dev server found this repository's own run on disk (never in a build). */
export const LOCAL_RUN_AVAILABLE = !!localRun?.trace

/** This repository's own run: output/dev.jsonl (or the trace), plus dev/alerts.jsonl when present. Dev server only. */
export function loadLocalRun(): { loaded: Loaded; label: string } | null {
  if (!localRun?.trace) return null
  const { trace, alerts } = localRun
  return {
    loaded: {
      ...EMPTY,
      trace: { name: trace.name, result: parseTraceJsonl(trace.text) },
      alerts: alerts ? { name: alerts.name, result: parseAlerts(alerts.text) } : null,
    },
    label: [trace.name, alerts?.name].filter(Boolean).join(' + '),
  }
}
