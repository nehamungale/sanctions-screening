import { DecisionBadge, ReasonCode, RunStrip } from '@/components/verdict'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { ReproMetrics, ReproReport } from '@/lib/repro'
import { cn } from '@/lib/utils'

const FLIP_TEXT: Record<string, string> = {
  none: 'same every run',
  decision: 'verdict changed',
  code: 'reason code changed',
  evidence: 'cited records changed',
  other: 'trace or presence changed',
}

const CONFIG_LABELS: Record<string, string> = {
  git_sha: 'git SHA',
  rules_version: 'rules_version',
  policy_hash: 'policy',
  name_variants_hash: 'name variants',
  prompt_hashes: 'prompts',
  input_hash: 'input',
  model: 'model',
  provider: 'provider',
  python_version: 'Python',
}

interface Props {
  report: ReproReport
  metrics: ReproMetrics
  onHit: (hitId: string, alertId: string | null) => void
}

/** Reproducibility card (design doc section 7), from repro.json. */
export function ReproCard({ report, metrics, onHit }: Props) {
  const flipped = metrics.flipped_clear_ids.length
  const unstable = report.hits.filter((h) => metrics.unstable_ids.includes(h.hit_id))
  const pct = metrics.share === null ? '—' : `${(Math.floor(metrics.share * 1000) / 10).toFixed(1)}%`

  return (
    <Card className={cn(flipped > 0 && 'border-red-400 ring-2 ring-red-200')}>
      <CardHeader>
        <CardTitle>Reproducibility</CardTitle>
        <CardDescription>
          {report.n_runs} runs of the same input{report.generated_at ? ` · report generated ${report.generated_at}` : ''}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <div className="grid gap-4 sm:grid-cols-3">
          <Stat
            label="Same verdict and reason code in every run"
            value={`${metrics.judges_stable} of ${metrics.n_hits}`}
            sub={`${pct} of hits`}
          />
          <Stat
            label="Clears that ever flipped"
            value={String(flipped)}
            sub={flipped === 0 ? 'must be 0 · no DIFFERENT_ENTITY changed in any run' : `must be 0 · ${metrics.flipped_clear_ids.join(', ')}`}
            tone={flipped > 0 ? 'bad' : 'good'}
          />
          <Stat label="Unstable hits" value={String(unstable.length)} sub="anything that changed between runs" />
        </div>

        {flipped > 0 ? (
          <p className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm font-medium text-red-800">
            A hit was cleared in one run and not in another: {metrics.flipped_clear_ids.join(', ')}. A clear must hold in every run.
          </p>
        ) : null}

        {metrics.summary_mismatches.length ? (
          <p className="text-xs text-amber-700">Report summary does not match its own rows: {metrics.summary_mismatches.join('; ')}.</p>
        ) : null}

        {report.config_identical ? (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
            <span className="text-muted-foreground">Identical across runs</span>
            {Object.entries(report.config_identical).map(([k, v]) => (
              <span key={k} className={cn(v === false ? 'text-red-700' : v === null ? 'text-muted-foreground' : '')}>
                {v === true ? '✓' : v === false ? '✗' : '–'} {CONFIG_LABELS[k] ?? k}
              </span>
            ))}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">No run headers in the report, so config cannot be compared.</p>
        )}

        <div className="flex flex-col gap-2">
          <div className="flex items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold">Unstable hits</h3>
            <span className="text-xs text-muted-foreground">one dot per run · hover a dot for its verdict</span>
          </div>
          {unstable.length === 0 ? (
            <p className="text-sm text-muted-foreground">Every hit had the same result in every run.</p>
          ) : (
            <ul className="flex flex-col divide-y rounded-lg border">
              {unstable.map((h) => (
                <li key={h.hit_id}>
                  <button
                    type="button"
                    onClick={() => onHit(h.hit_id, h.alert_id)}
                    className={cn(
                      'grid w-full cursor-pointer grid-cols-[6rem_auto_1fr_auto] items-center gap-4 px-4 py-3 text-left hover:bg-muted/50',
                      flippedRow(metrics, h.hit_id) && 'bg-red-50',
                    )}
                  >
                    <span className="font-mono text-sm">{h.hit_id}</span>
                    <RunStrip cells={h.per_run} labels={report.run_labels} />
                    <span className="flex flex-wrap items-center gap-2">
                      <DecisionBadge decision={h.modal_decision} />
                      {h.modal_reason_code ? <ReasonCode code={h.modal_reason_code} /> : null}
                    </span>
                    <span className={cn('text-xs', flippedRow(metrics, h.hit_id) ? 'font-medium text-red-700' : 'text-muted-foreground')}>
                      {flippedRow(metrics, h.hit_id) ? 'clear flipped' : FLIP_TEXT[h.flip_type]}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

const flippedRow = (m: ReproMetrics, id: string) => m.flipped_clear_ids.includes(id)

function Stat({ label, value, sub, tone }: { label: string; value: string; sub: string; tone?: 'good' | 'bad' }) {
  return (
    <div className={cn('rounded-lg border px-5 py-4', tone === 'bad' && 'border-red-400 bg-red-50')}>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn('mt-1 text-3xl font-semibold tabular-nums', tone === 'bad' && 'text-red-700')}>{value}</div>
      <div className={cn('mt-1 text-xs', tone === 'bad' ? 'text-red-700' : 'text-muted-foreground')}>{sub}</div>
    </div>
  )
}
