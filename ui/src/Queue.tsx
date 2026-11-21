import { MissingHit } from '@/Audit'
import { HitWorkspace, rowKey } from '@/HitWorkspace'
import { DecisionBadge, ReasonCode } from '@/components/verdict'
import type { Model } from '@/lib/data'
import { cn } from '@/lib/utils'
import { QUEUE_GROUPS, queueGroups, whatsMissingLine, type HitRow } from '@/lib/worklist'

interface Props {
  model: Model
  alertId: string | null
  hitId: string | null
  onOpen: (r: HitRow | null) => void
}

/** Analyst queue: hits needing a person. REVIEW first, then no decision, then SAME_ENTITY. */
export function Queue({ model, alertId, hitId, onOpen }: Props) {
  const groups = queueGroups(model)
  const total = groups.reduce((n, g) => n + g.rows.length, 0)
  const all = groups.flatMap((g) => g.rows)
  const selected = hitId ? (all.find((r) => r.hit_id === hitId && (alertId === null || r.alert_id === alertId)) ?? null) : null
  const compact = selected !== null

  const list = (
    <div className="flex flex-col gap-8">
      {groups.map((g) => {
        const meta = QUEUE_GROUPS.find((q) => q.id === g.id)!
        return (
          <section key={g.id} className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <h2 className={cn('text-base font-semibold', g.id !== 'undecided' && 'font-mono text-sm')}>{meta.title}</h2>
              <span className="text-sm tabular-nums text-muted-foreground">{g.rows.length}</span>
              {g.id === 'review' && g.rows.length > 0 ? (
                <span className="halo inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-900">Analyst action</span>
              ) : null}
              {!compact ? <span className="text-xs text-muted-foreground">{meta.note}</span> : null}
            </div>
            {g.rows.length === 0 ? (
              <p className="text-sm text-muted-foreground">None.</p>
            ) : (
              <ul className={cn('flex flex-col divide-y rounded-xl border bg-card', g.id === 'review' && 'border-l-4 border-l-amber-500', g.id === 'same' && 'border-l-4 border-l-red-600')}>
                {g.rows.map((r) => {
                  const active = selected && rowKey(selected) === rowKey(r)
                  return (
                    <li key={rowKey(r)}>
                      <button
                        type="button"
                        onClick={() => onOpen(r)}
                        aria-current={active ? 'true' : undefined}
                        className={cn(
                          'flex w-full cursor-pointer flex-col gap-1.5 px-4 py-3 text-left hover:bg-muted/50',
                          !compact && 'sm:grid sm:grid-cols-[7rem_7rem_minmax(0,16rem)_minmax(0,1fr)] sm:items-baseline sm:gap-4',
                          active && 'bg-muted',
                        )}
                      >
                        <span className="flex items-center gap-2">
                          <span className="font-mono text-sm whitespace-nowrap">{r.hit_id}</span>
                          {compact ? <DecisionBadge decision={r.decision} /> : null}
                        </span>
                        <span className="font-mono text-xs whitespace-nowrap text-muted-foreground">{r.alert_id ?? '—'}</span>
                        <ReasonCode code={r.reason_code} />
                        <span className="text-sm">{whatsMissingLine(r)}</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </section>
        )
      })}
    </div>
  )

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Analyst queue</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {total} hit{total === 1 ? '' : 's'} need a person. REVIEW first (the analyst decides), then hits with no decision (they block
          their alert), then SAME_ENTITY (goes to the compliance team). Within a group: by alert, then hit.
        </p>
      </div>
      {hitId && !selected ? <MissingHit hitId={hitId} /> : null}
      <HitWorkspace list={list} selected={selected} onClose={() => onOpen(null)} />
    </div>
  )
}
