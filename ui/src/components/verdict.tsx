import type { RunCell } from '@/lib/repro'
import { reasonLabel, STATUS_LABELS } from '@/lib/labels'
import { HIT_NOT_DECIDED, type Decision, type RollupStatus } from '@/lib/policy'
import { cn } from '@/lib/utils'

export const DECISION_TONE: Record<Decision, { dot: string; pill: string }> = {
  DIFFERENT_ENTITY: { dot: 'bg-emerald-600', pill: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  SAME_ENTITY: { dot: 'bg-red-600', pill: 'border-red-200 bg-red-50 text-red-800' },
  REVIEW: { dot: 'bg-amber-500', pill: 'border-amber-200 bg-amber-50 text-amber-900' },
}

export const STATUS_TONE: Record<RollupStatus, { border: string; pill: string }> = {
  CLEARED: { border: 'border-l-emerald-600', pill: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  NOT_VERIFIED: { border: 'border-l-slate-400', pill: 'border-slate-200 bg-slate-50 text-slate-700' },
  ESCALATED: { border: 'border-l-red-600', pill: 'border-red-200 bg-red-50 text-red-800' },
  NEEDS_REVIEW: { border: 'border-l-amber-500', pill: 'border-amber-200 bg-amber-50 text-amber-900' },
}

/** Verdict exactly as the brief writes it. */
export function DecisionBadge({ decision, className }: { decision: Decision | null; className?: string }) {
  if (!decision) {
    return (
      <span className={cn('inline-flex rounded-md border border-slate-200 bg-slate-50 px-2 py-0.5 font-mono text-xs whitespace-nowrap text-slate-700', className)}>
        no decision
      </span>
    )
  }
  return (
    <span className={cn('inline-flex rounded-md border px-2 py-0.5 font-mono text-xs font-medium whitespace-nowrap', DECISION_TONE[decision].pill, className)}>
      {decision}
    </span>
  )
}

export function DecisionDot({ decision, muted = false }: { decision: Decision | null; muted?: boolean }) {
  return (
    <span
      className={cn('inline-block size-2 shrink-0 rounded-full', muted || !decision ? 'bg-muted-foreground/40' : DECISION_TONE[decision].dot)}
    />
  )
}

export function StatusBadge({ status }: { status: RollupStatus }) {
  return (
    <span className={cn('inline-flex rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap', STATUS_TONE[status].pill)}>
      {STATUS_LABELS[status].label}
    </span>
  )
}

/** A reason code with its plain-English label beside it. */
export function ReasonCode({ code, className }: { code: string; className?: string }) {
  if (code === HIT_NOT_DECIDED) {
    // Never shown as a raw code on screen: plain words, the code only in the tooltip (and the raw trace).
    return (
      <span className={cn('inline-flex text-xs font-medium whitespace-nowrap text-slate-700', className)} title={code}>
        Hit has no decision
      </span>
    )
  }
  return (
    <span className={cn('inline-flex flex-wrap items-baseline gap-x-2', className)}>
      <span className="font-mono text-xs whitespace-nowrap" title={reasonLabel(code)}>
        {code}
      </span>
      <span className="reason-label text-xs text-muted-foreground">{reasonLabel(code)}</span>
    </span>
  )
}

/** One dot per run for a hit (repro.json hits[].per_run). Hollow dot: missing in that run. */
export function RunStrip({ cells, labels }: { cells: RunCell[]; labels: string[] }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap" aria-label="Verdict in each run">
      {cells.map((c, i) => (
        <span
          key={i}
          title={`run ${i + 1}${labels[i] ? ` (${labels[i]})` : ''}: ${c ? `${c.decision ?? '?'} · ${c.reason_code ?? '?'}` : `missing in run ${i + 1}`}`}
          className={cn(
            'inline-block size-2.5 rounded-full',
            c?.decision ? DECISION_TONE[c.decision].dot : 'border border-muted-foreground/60 bg-transparent',
          )}
        />
      ))}
    </span>
  )
}
