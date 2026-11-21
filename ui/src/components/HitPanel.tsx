// Shared hit panel: Overview drill-down now, Analyst queue and Audit later.
// Four layers (design doc section 2): verdict line, comparison card, who is who, raw trace.
// All free text is rendered as React text nodes.

import type { ReactNode } from 'react'

import { DecisionBadge, ReasonCode } from '@/components/verdict'
import { DECIDING_DIMS, DIM_LABELS, DIMS, undecidedText } from '@/lib/labels'
import { HIT_NOT_DECIDED, isDecision } from '@/lib/policy'
import {
  formatValue,
  readComparison,
  readIdentity,
  readLlmCalls,
  readSteps,
  readTippingPoint,
  unknownFacts,
  type ComparisonRow,
} from '@/lib/trace-view'
import type { TraceHit, UndecidedReason } from '@/lib/types'
import { cn } from '@/lib/utils'

interface Props {
  hitId: string
  hit: TraceHit | null
  /** Set when the roll-up treats this hit as undecided for the alert being viewed. */
  undecided: UndecidedReason | null
}

export function HitPanel({ hitId, hit, undecided }: Props) {
  if (undecided || !hit) {
    return (
      <PanelShell>
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-mono text-sm font-semibold">{hitId}</span>
          <DecisionBadge decision={null} />
        </div>
        <Section title="Verdict">
          <ReasonCode code={HIT_NOT_DECIDED} />
          <p className="mt-2 text-sm">{capitalise(undecided ? undecidedText(undecided) : 'no record for this hit in the trace')}.</p>
          <p className="mt-1 text-sm text-muted-foreground">This hit blocks the alert from being cleared.</p>
        </Section>
        {hit ? <Collapsed title="Raw trace (record found under another alert)">{<RawJson value={hit.raw} />}</Collapsed> : null}
      </PanelShell>
    )
  }

  const v = hit.verdict
  const comparison = readComparison(hit.raw)
  const identity = readIdentity(hit.raw)
  const steps = readSteps(hit.raw)
  const llmCalls = readLlmCalls(hit.raw)
  const tipping = readTippingPoint(hit.raw)
  const deciding = new Set(DECIDING_DIMS[v.reason_code] ?? [])
  const isReview = v.decision === 'REVIEW'
  const ambiguous = v.customer_record_id === 'AMBIGUOUS'
  const byDim = new Map(comparison.map((r) => [r.dim, r]))
  const rows: ComparisonRow[] = [
    ...DIMS.map((d) => byDim.get(d) ?? { dim: d, customer: null, hit: null, status: 'unknown', src: [] }),
    ...comparison.filter((r) => !(DIMS as readonly string[]).includes(r.dim)),
  ]
  const unknown = unknownFacts(rows)

  return (
    <PanelShell>
      {/* 1. Verdict line + badges */}
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-mono text-sm font-semibold">{hit.hit_id}</span>
          <DecisionBadge decision={v.decision} />
          <ReasonCode code={v.reason_code} />
        </div>
        {v.reason ? <p className="text-[15px] leading-relaxed">{v.reason}</p> : <p className="text-sm text-muted-foreground">No reason text.</p>}
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <Chip label="fragility" value={hit.badges?.fragility ?? 'unknown'} tone={fragilityTone(hit.badges?.fragility)} />
          <Chip
            label="llm_used"
            value={hit.badges?.llm_used === undefined ? 'unknown' : String(hit.badges.llm_used)}
            tone={hit.badges?.llm_used ? 'border-violet-200 bg-violet-50 text-violet-800' : undefined}
          />
          <Chip label="rules_version" value={hit.badges?.rules_version ?? 'unknown'} />
        </div>
        {v.evidence.length ? (
          <div className="flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-muted-foreground">Evidence</span>
            {v.evidence.map((e) => (
              <Id key={e}>{e}</Id>
            ))}
          </div>
        ) : null}
      </div>

      {/* 2. Who is compared */}
      <Section title="Who’s compared">
        {ambiguous ? (
          <div className="flex flex-col gap-3">
            <p className="text-sm text-muted-foreground">
              More than one customer fits this alert. Each candidate below would lead to a different decision.
            </p>
            {identity.candidates.length === 0 ? (
              <p className="text-sm text-amber-700">The trace does not list the candidates (identity.candidates).</p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {identity.candidates.map((c) => (
                  <div key={c.customer_record_id} className="rounded-lg border p-4 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <Id>{c.customer_record_id}</Id>
                      {c.would_decide?.decision && isDecision(c.would_decide.decision) ? (
                        <DecisionBadge decision={c.would_decide.decision} />
                      ) : null}
                    </div>
                    <div className="mt-2 font-medium">{c.name ?? '—'}</div>
                    <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
                      <dt className="text-muted-foreground">Date of birth</dt>
                      <dd>{c.dob ?? '—'}</dd>
                      <dt className="text-muted-foreground">Country</dt>
                      <dd>{c.country ?? '—'}</dd>
                    </dl>
                    {c.why_fits ? <p className="mt-2 text-xs text-muted-foreground">{c.why_fits}</p> : null}
                    {c.would_decide?.reason_code ? (
                      <div className="mt-2 text-xs">
                        <span className="text-muted-foreground">Would be: </span>
                        <ReasonCode code={c.would_decide.reason_code} />
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            <Party
              title="Customer"
              name={formatValue(byDim.get('name')?.customer)}
              ids={[v.customer_record_id ?? 'no customer record found', identity.person_id].filter((x): x is string => !!x)}
              type={formatValue(byDim.get('type')?.customer)}
            />
            <Party
              title="Hit"
              name={formatValue(byDim.get('name')?.hit)}
              ids={[hit.hit_id]}
              type={formatValue(byDim.get('type')?.hit)}
            />
          </div>
        )}
      </Section>

      {/* 3. Comparison card */}
      <Section title="Comparison" aside={deciding.size ? 'Highlighted: the row(s) this reason code rests on' : undefined}>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Fact</th>
                <th className="px-3 py-2 font-medium">Customer</th>
                <th className="px-3 py-2 font-medium">Hit</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Records cited</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const isDeciding = deciding.has(r.dim)
                return (
                  <tr key={r.dim} className={cn('border-t align-top', isDeciding && 'bg-sky-50')}>
                    <td className={cn('px-3 py-2.5 whitespace-nowrap', isDeciding && 'border-l-4 border-l-sky-500 font-medium')}>
                      {DIM_LABELS[r.dim] ?? r.dim}
                      {isDeciding ? <span className="ml-2 text-[11px] font-normal text-sky-700">deciding</span> : null}
                    </td>
                    <td className={cn('min-w-36 px-3 py-2.5', r.customer == null && 'text-muted-foreground')}>{formatValue(r.customer)}</td>
                    <td className={cn('min-w-36 px-3 py-2.5', r.hit == null && 'text-muted-foreground')}>{formatValue(r.hit)}</td>
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <StatusText status={r.status} />
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex flex-wrap gap-1">
                        {r.src.length ? r.src.map((s) => <Id key={s}>{s}</Id>) : <span className="text-muted-foreground">—</span>}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Section>

      {/* 4. What would change it / What's missing */}
      <Section title={isReview ? 'What’s missing' : 'What would change it'}>
        {tipping ? <p className="text-sm leading-relaxed">{tipping}</p> : <p className="text-sm text-muted-foreground">No tipping point recorded in the trace.</p>}
        {isReview && unknown.length ? (
          <ul className="mt-3 flex flex-col gap-1 text-sm">
            {unknown.map((u) => (
              <li key={u.dim} className="flex gap-2">
                <span className="text-muted-foreground">Unknown:</span>
                <span>
                  {DIM_LABELS[u.dim] ?? u.dim} <span className="text-muted-foreground">(missing on {u.missing})</span>
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        {isReview && identity.flags.length ? (
          <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
            <span className="text-muted-foreground">Flags</span>
            {identity.flags.map((f) => (
              <Id key={f}>{f}</Id>
            ))}
          </div>
        ) : null}
      </Section>

      {/* 5. Collapsed layers */}
      <div className="flex flex-col gap-2">
        <Collapsed title="Who is who" count={identity.merged.length + identity.facts.length}>
          <dl className="grid grid-cols-[10rem_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">person_id</dt>
            <dd>{identity.person_id ? <Id>{identity.person_id}</Id> : '—'}</dd>
            <dt className="text-muted-foreground">Merged records</dt>
            <dd className="flex flex-col gap-1">
              {identity.merged.length
                ? identity.merged.map((m, i) => (
                    <div key={i} className="flex flex-wrap items-center gap-1.5">
                      <span>{m.rule}</span>
                      {m.records.map((r) => (
                        <Id key={r}>{r}</Id>
                      ))}
                      {m.extra.map(([k, val]) => (
                        <span key={k} className="text-xs text-muted-foreground">
                          {k}: {val}
                        </span>
                      ))}
                    </div>
                  ))
                : 'none'}
            </dd>
            <dt className="text-muted-foreground">Flags</dt>
            <dd>{identity.flags.length ? identity.flags.join(', ') : 'none'}</dd>
            <dt className="text-muted-foreground">Ignored checks</dt>
            <dd>{identity.ignored_checks.length ? identity.ignored_checks.join(', ') : 'none'}</dd>
          </dl>
          {identity.facts.length ? (
            <table className="mt-4 w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th className="py-1 pr-3 font-medium">Fact</th>
                  <th className="py-1 pr-3 font-medium">Value</th>
                  <th className="py-1 pr-3 font-medium">Verified</th>
                  <th className="py-1 pr-3 font-medium">Source</th>
                </tr>
              </thead>
              <tbody>
                {identity.facts.map((f) => (
                  <tr key={f.name} className="border-t">
                    <td className="py-1.5 pr-3 font-mono text-xs">{f.name}</td>
                    <td className="py-1.5 pr-3">{f.value}</td>
                    <td className="py-1.5 pr-3">{f.verified === null ? '—' : f.verified ? 'verified' : 'declared'}</td>
                    <td className="py-1.5 pr-3">
                      {f.source_id ? <Id>{f.source_id}</Id> : '—'}
                      {f.source_kind ? <span className="ml-2 text-xs text-muted-foreground">{f.source_kind}</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </Collapsed>

        <Collapsed title="Raw trace" count={steps.length}>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th className="py-1 pr-3 font-medium">Rule</th>
                <th className="py-1 pr-3 font-medium">Result</th>
                <th className="py-1 pr-3 font-medium">LLM</th>
                <th className="py-1 pr-3 font-medium">Why</th>
              </tr>
            </thead>
            <tbody>
              {steps.map((s, i) => (
                <tr key={i} className={cn('border-t', s.result === 'fired' && 'bg-muted/60')}>
                  <td className="py-1.5 pr-3 font-mono text-xs">{s.rule}</td>
                  <td className="py-1.5 pr-3">{s.result}</td>
                  <td className="py-1.5 pr-3">{s.llm_used ? 'yes' : 'no'}</td>
                  <td className="py-1.5 pr-3 text-muted-foreground">{s.why ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="mt-4 text-xs text-muted-foreground">Full record</div>
          <RawJson value={hit.raw} />
        </Collapsed>

        <Collapsed title="LLM calls" count={llmCalls.length}>
          {llmCalls.length === 0 ? (
            <p className="text-sm text-muted-foreground">No LLM calls for this hit.</p>
          ) : (
            <div className="flex flex-col gap-3">
              {llmCalls.map((c, i) => (
                <dl key={i} className="grid grid-cols-[10rem_1fr] gap-x-4 gap-y-1 rounded-lg border p-3 text-sm">
                  {Object.entries(c).map(([k, val]) => (
                    <div key={k} className="contents">
                      <dt className="font-mono text-xs text-muted-foreground">{k}</dt>
                      <dd className="break-words">{formatValue(val)}</dd>
                    </div>
                  ))}
                </dl>
              ))}
            </div>
          )}
        </Collapsed>
      </div>
    </PanelShell>
  )
}

function PanelShell({ children }: { children: ReactNode }) {
  return <div className="flex flex-col gap-8 rounded-xl border bg-card p-6 shadow-sm">{children}</div>
}

function Section({ title, aside, children }: { title: string; aside?: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        {aside ? <span className="text-xs text-muted-foreground">{aside}</span> : null}
      </div>
      <div>{children}</div>
    </section>
  )
}

function Collapsed({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return (
    <details className="group rounded-lg border">
      <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-medium select-none">
        <span>
          {title}
          {count !== undefined ? <span className="ml-2 text-xs font-normal text-muted-foreground">{count}</span> : null}
        </span>
        <span className="text-muted-foreground transition-transform group-open:rotate-90">›</span>
      </summary>
      <div className="border-t px-4 py-4">{children}</div>
    </details>
  )
}

function RawJson({ value }: { value: unknown }) {
  return (
    <pre className="mt-2 max-h-96 overflow-auto rounded-md bg-muted/60 p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap break-words">
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

function Id({ children }: { children: ReactNode }) {
  return <span className="rounded border bg-muted/40 px-1.5 py-0.5 font-mono text-[11px]">{children}</span>
}

function Chip({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5', tone)}>
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium">{value}</span>
    </span>
  )
}

function fragilityTone(f: string | undefined): string | undefined {
  if (f === 'solid') return 'border-emerald-200 bg-emerald-50 text-emerald-800'
  if (f === 'thin') return 'border-amber-200 bg-amber-50 text-amber-900'
  if (f === 'borderline') return 'border-orange-300 bg-orange-50 text-orange-900'
  return undefined
}

function StatusText({ status }: { status: string }) {
  const tone =
    status === 'agree'
      ? 'text-emerald-700'
      : status === 'contradict'
        ? 'text-red-700'
        : status === 'no_conflict'
          ? 'text-slate-600'
          : 'text-muted-foreground'
  return <span className={cn('font-mono text-xs', tone)}>{status}</span>
}

function Party({ title, name, ids, type }: { title: string; name: string; ids: string[]; type: string }) {
  return (
    <div className="rounded-lg border p-4">
      <div className="text-xs text-muted-foreground">{title}</div>
      <div className="mt-1 font-medium">{name}</div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        {ids.map((i) => (
          <Id key={i}>{i}</Id>
        ))}
        <span className="text-xs text-muted-foreground">{type}</span>
      </div>
    </div>
  )
}

function capitalise(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1)
}
