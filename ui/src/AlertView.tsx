import { HitPanel } from '@/components/HitPanel'
import { DecisionBadge, ReasonCode, StatusBadge } from '@/components/verdict'
import type { Model } from '@/lib/data'
import { STATUS_LABELS, undecidedText } from '@/lib/labels'
import { HIT_NOT_DECIDED } from '@/lib/policy'
import type { AlertSummary } from '@/lib/types'
import { cn } from '@/lib/utils'

interface Props {
  model: Model
  summary: AlertSummary
  hitId: string | null
  onHit: (hitId: string) => void
  onBack: () => void
  onStatus: () => void
}

export function AlertView({ model, summary, hitId, onHit, onBack, onStatus }: Props) {
  // Default selection: first blocking hit, else the first hit. An unknown ?hit= opens nothing and says so.
  const badHit = hitId !== null && !summary.hits.some((h) => h.hit_id === hitId)
  const selected = badHit
    ? null
    : summary.hits.find((h) => h.hit_id === hitId) ??
    summary.hits.find((h) => summary.blocking_hit_ids.includes(h.hit_id)) ??
    summary.hits[0] ??
    null

  return (
    <div className="flex flex-col gap-8">
      <nav className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground" aria-label="Breadcrumb">
        <button type="button" className="cursor-pointer hover:text-foreground" onClick={onBack}>
          Overview
        </button>
        <span>›</span>
        <button type="button" className="cursor-pointer hover:text-foreground" onClick={onStatus}>
          {STATUS_LABELS[summary.alert_status].label}
        </button>
        <span>›</span>
        <span className="font-mono whitespace-nowrap text-foreground">{summary.alert_id}</span>
      </nav>

      <div className="flex flex-wrap items-center gap-3">
        <h1 className="font-mono text-2xl font-semibold tracking-tight whitespace-nowrap">{summary.alert_id}</h1>
        <StatusBadge status={summary.alert_status} />
        <span className="text-sm text-muted-foreground">
          {summary.hits.length} hit{summary.hits.length === 1 ? '' : 's'} · {STATUS_LABELS[summary.alert_status].sub}
        </span>
      </div>

      {summary.conflicting_lines ? (
        <p className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
          The alerts file has conflicting lines for this alert (lines {summary.conflicting_lines.join(', ')}). Their hit lists were combined;
          this alert can’t be cleared.
        </p>
      ) : null}

      {badHit ? (
        <p className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800" role="alert">
          Hit <span className="font-mono whitespace-nowrap">{hitId}</span> is not in alert{' '}
          <span className="font-mono whitespace-nowrap">{summary.alert_id}</span>. Pick a hit below.
        </p>
      ) : null}

      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
        <div className="flex min-w-0 flex-col gap-2 lg:sticky lg:top-6">
          <div className="px-1 text-xs font-medium text-muted-foreground">Hits</div>
          {summary.hits.length === 0 ? <p className="px-1 text-sm text-muted-foreground">This alert lists no hits.</p> : null}
          {summary.hits.map((h) => {
            const active = selected?.hit_id === h.hit_id
            const blocking = summary.blocking_hit_ids.includes(h.hit_id)
            return (
              <button
                key={h.hit_id}
                type="button"
                onClick={() => onHit(h.hit_id)}
                aria-current={active ? 'true' : undefined}
                className={cn(
                  'flex min-w-0 cursor-pointer flex-col gap-1.5 rounded-lg border bg-card p-3 text-left transition-colors hover:border-foreground/30',
                  h.decision === 'REVIEW' && 'halo border-amber-300 bg-amber-50/40',
                  active && 'border-foreground/60 ring-1 ring-foreground/20',
                )}
              >
                {h.decision === 'REVIEW' ? <span className="text-[11px] font-semibold text-amber-800">Analyst action: decide this hit</span> : null}
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-sm whitespace-nowrap">{h.hit_id}</span>
                  <DecisionBadge decision={h.decision} />
                </div>
                <ReasonCode code={h.reason_code ?? HIT_NOT_DECIDED} />
                {h.undecided ? <span className="text-xs text-amber-700">{undecidedText(h.undecided)}</span> : null}
                {blocking && summary.alert_status !== 'ESCALATED' ? <span className="text-[11px] text-amber-700">blocks the clear</span> : null}
              </button>
            )
          })}
        </div>

        {selected ? (
          <HitPanel hitId={selected.hit_id} hit={model.hitsById.get(selected.hit_id) ?? null} undecided={selected.undecided} />
        ) : (
          <div className="rounded-xl border bg-card p-6 text-sm text-muted-foreground">{badHit ? 'No hit selected.' : 'No hit to show.'}</div>
        )}
      </div>
    </div>
  )
}
