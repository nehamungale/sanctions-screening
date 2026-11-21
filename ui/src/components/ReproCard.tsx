import { DecisionBadge, DECISION_TONE, ReasonCode, RunStrip } from '@/components/verdict'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { instabilityLabel, isFlippedClear, isMissingOutput, type ReproMetrics, type ReproReport } from '@/lib/repro'
import { cn } from '@/lib/utils'

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

const pct = (x: number | null) => (x === null ? '—' : `${(Math.floor(x * 1000) / 10).toFixed(1)}%`)

/** Reproducibility card (design doc section 7), from repro.json. Metrics recomputed from hits[].per_run. */
export function ReproCard({ report, metrics: m, onHit }: Props) {
  const flipped = m.flipped_clear_ids.length
  const missing = m.missing_output_ids.length
  const n = report.n_runs
  const listed = report.hits.filter((h) => m.unstable_ids.includes(h.hit_id))

  return (
    <Card className={cn(flipped > 0 && 'border-red-400 ring-2 ring-red-200')}>
      <CardHeader>
        <CardTitle>Reproducibility</CardTitle>
        <CardDescription>
          {n} runs of the same input{report.generated_at ? ` · report generated ${report.generated_at}` : ''}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label={`Same decision and reason code in all ${n} runs`}
            value={pct(m.official_share)}
            sub={`${m.official_stable} of ${m.n_hits} hits · the brief’s reproducibility measure`}
            headline
          />
          <Stat label={`Same decision in all ${n} runs`} value={pct(m.decision_share)} sub={`${m.decision_stable} of ${m.n_hits} hits · reason code may differ`} />
          <Stat
            label="Clears that ever flipped"
            value={String(flipped)}
            sub={flipped === 0 ? 'must be 0' : `must be 0 · ${m.flipped_clear_ids.join(', ')}`}
            tone={flipped > 0 ? 'bad' : undefined}
          />
          <Stat
            label="Missing output"
            value={String(missing)}
            sub={missing === 0 ? 'every run produced every hit' : `a run produced no line · ${m.missing_output_ids.join(', ')}`}
            tone={missing > 0 ? 'bad' : undefined}
          />
        </div>

        {flipped > 0 ? (
          <p className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm font-medium text-red-800">
            Cleared in one run but not in another: {m.flipped_clear_ids.join(', ')}. A clear must hold in every run.
          </p>
        ) : null}
        {missing > 0 ? (
          <p className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
            Broken output: {m.missing_output_ids.join(', ')} {missing === 1 ? 'is' : 'are'} missing from at least one run. Not counted as a
            flip, but the hit is not reproducible.
          </p>
        ) : null}
        {m.summary_mismatches.length ? (
          <p className="text-xs text-amber-700">Report summary does not match its own rows: {m.summary_mismatches.join('; ')}.</p>
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
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-semibold">Not identical in all runs</h3>
            <Legend />
          </div>
          {listed.length === 0 ? (
            <p className="text-sm text-muted-foreground">Every hit had the same decision and reason code in every run.</p>
          ) : (
            <ul className="flex flex-col divide-y rounded-lg border">
              {listed.map((h) => {
                const bad = isFlippedClear(h) || isMissingOutput(h)
                return (
                  <li key={h.hit_id}>
                    <button
                      type="button"
                      onClick={() => onHit(h.hit_id, h.alert_id)}
                      className={cn(
                        'grid w-full cursor-pointer grid-cols-[6rem_auto_1fr_auto] items-center gap-4 px-4 py-3 text-left hover:bg-muted/50',
                        bad && 'bg-red-50',
                      )}
                    >
                      <span className="font-mono text-sm">{h.hit_id}</span>
                      <RunStrip cells={h.per_run} labels={report.run_labels} />
                      <span className="flex flex-wrap items-center gap-2">
                        <DecisionBadge decision={h.modal_decision} />
                        {h.modal_reason_code ? <ReasonCode code={h.modal_reason_code} /> : null}
                      </span>
                      <span className={cn('text-xs', bad ? 'font-medium text-red-700' : 'text-muted-foreground')}>{instabilityLabel(h)}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
          {m.other_change_ids.length ? (
            <p className="text-xs text-muted-foreground">
              Same verdict every run, but cited records or trace changed (not counted): {m.other_change_ids.join(', ')}.
            </p>
          ) : null}
        </div>
      </CardContent>
    </Card>
  )
}

function Legend() {
  const dot = (cls: string) => <span className={cn('inline-block size-2.5 rounded-full', cls)} />
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      <span>one dot per run:</span>
      <span className="inline-flex items-center gap-1">{dot(DECISION_TONE.DIFFERENT_ENTITY.dot)} DIFFERENT_ENTITY</span>
      <span className="inline-flex items-center gap-1">{dot(DECISION_TONE.SAME_ENTITY.dot)} SAME_ENTITY</span>
      <span className="inline-flex items-center gap-1">{dot(DECISION_TONE.REVIEW.dot)} REVIEW</span>
      <span className="inline-flex items-center gap-1">{dot('border border-muted-foreground/60')} missing in run</span>
    </span>
  )
}

function Stat({ label, value, sub, tone, headline }: { label: string; value: string; sub: string; tone?: 'bad'; headline?: boolean }) {
  return (
    <div className={cn('rounded-lg border px-5 py-4', tone === 'bad' && 'border-red-400 bg-red-50', headline && 'border-foreground/30')}>
      <div className={cn('text-xs', headline ? 'font-medium text-foreground' : 'text-muted-foreground')}>{label}</div>
      <div className={cn('mt-1 font-semibold tabular-nums', headline ? 'text-4xl' : 'text-3xl', tone === 'bad' && 'text-red-700')}>{value}</div>
      <div className={cn('mt-1 text-xs', tone === 'bad' ? 'text-red-700' : 'text-muted-foreground')}>{sub}</div>
    </div>
  )
}
