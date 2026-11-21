import { useState } from 'react'

import { MissingHit } from '@/Audit'
import { HitWorkspace, rowKey } from '@/HitWorkspace'
import { BarList, StackedBar, type BarRow } from '@/components/charts'
import { DecisionBadge, DECISION_TONE, ReasonCode } from '@/components/verdict'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { Model } from '@/lib/data'
import { cn } from '@/lib/utils'
import { QUEUE_GROUPS, queueGroups, whatsMissingLine, whyTags, type HitRow, type QueueGroupId, type WhyTag } from '@/lib/worklist'

interface Props {
  model: Model
  alertId: string | null
  hitId: string | null
  onOpen: (r: HitRow | null) => void
}

const PAGE_SIZE = 15

const GROUP_TONE: Record<QueueGroupId, { bar: string; border: string }> = {
  review: { bar: DECISION_TONE.REVIEW.dot, border: 'border-l-4 border-l-amber-500' },
  undecided: { bar: 'bg-slate-400', border: 'border-l-4 border-l-slate-400' },
  same: { bar: DECISION_TONE.SAME_ENTITY.dot, border: 'border-l-4 border-l-red-600' },
}

const TAG_TONE: Record<WhyTag['kind'], string> = {
  held: 'bg-amber-500',
  missing: 'bg-sky-600',
  identity: 'bg-violet-500',
  confirm: 'bg-red-600',
}

/** Analyst queue: hits needing a person. REVIEW first, then no decision, then SAME_ENTITY. 15 per page. */
export function Queue({ model, alertId, hitId, onOpen }: Props) {
  const groups = queueGroups(model)
  const all = groups.flatMap((g) => g.rows)
  const selected = hitId ? (all.find((r) => r.hit_id === hitId && (alertId === null || r.alert_id === alertId)) ?? null) : null
  const compact = selected !== null

  const [tag, setTag] = useState<string | null>(null)
  const [pages, setPages] = useState<Partial<Record<QueueGroupId, number>>>({})
  const pickTag = (t: string | null) => {
    setTag(t)
    setPages({})
  }

  const tagsByRow = new Map(all.map((r) => [rowKey(r), whyTags(r)]))
  const filtered = groups.map((g) => ({ ...g, rows: tag ? g.rows.filter((r) => tagsByRow.get(rowKey(r))!.some((t) => t.key === tag)) : g.rows }))
  const total = filtered.reduce((n, g) => n + g.rows.length, 0)

  // Count tags over REVIEW and undecided hits: why they could not be settled.
  const counts = new Map<string, { tag: WhyTag; n: number }>()
  for (const g of groups) {
    if (g.id === 'same') continue
    for (const r of g.rows) {
      for (const t of tagsByRow.get(rowKey(r))!) {
        const c = counts.get(t.key) ?? { tag: t, n: 0 }
        c.n++
        counts.set(t.key, c)
      }
    }
  }
  const tagRows: BarRow[] = [...counts.values()]
    .sort((a, b) => b.n - a.n || (a.tag.label < b.tag.label ? -1 : 1))
    .slice(0, 10)
    .map(({ tag: t, n }) => ({ key: t.key, label: t.label, sub: KIND_TEXT[t.kind], value: n, color: TAG_TONE[t.kind], onClick: () => pickTag(tag === t.key ? null : t.key) }))
  const activeTag = tag ? (counts.get(tag)?.tag ?? null) : null

  const pageOf = (id: QueueGroupId, rows: HitRow[]) => {
    const last = Math.max(0, Math.ceil(rows.length / PAGE_SIZE) - 1)
    const explicit = pages[id]
    if (explicit !== undefined) return Math.min(explicit, last)
    // Open on the page that holds the selected hit.
    const at = selected ? rows.findIndex((r) => rowKey(r) === rowKey(selected)) : -1
    return at >= 0 ? Math.floor(at / PAGE_SIZE) : 0
  }

  const list = (
    <div className="flex flex-col gap-8">
      {filtered.filter((g) => !tag || g.rows.length > 0).map((g) => {
        const meta = QUEUE_GROUPS.find((q) => q.id === g.id)!
        const page = pageOf(g.id, g.rows)
        const pageCount = Math.max(1, Math.ceil(g.rows.length / PAGE_SIZE))
        const shown = g.rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)
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
              <>
                <ul className={cn('flex flex-col divide-y rounded-xl border bg-card', GROUP_TONE[g.id].border)}>
                  {shown.map((r) => {
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
                {pageCount > 1 ? (
                  <Pager
                    page={page}
                    pageCount={pageCount}
                    from={page * PAGE_SIZE + 1}
                    to={Math.min((page + 1) * PAGE_SIZE, g.rows.length)}
                    total={g.rows.length}
                    onPage={(n) => setPages((p) => ({ ...p, [g.id]: n }))}
                  />
                ) : null}
              </>
            )}
          </section>
        )
      })}
    </div>
  )

  const unfilteredTotal = groups.reduce((n, g) => n + g.rows.length, 0)
  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Analyst queue</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {unfilteredTotal} hit{unfilteredTotal === 1 ? '' : 's'} need a person. REVIEW first (the analyst decides), then hits with no decision (they block
          their alert), then SAME_ENTITY (goes to the compliance team). {PAGE_SIZE} per page.
        </p>
      </div>

      {!compact ? (
        <div className="grid items-start gap-6 lg:grid-cols-5">
          <Card className="gap-4 lg:col-span-2">
            <CardHeader>
              <CardTitle>Workload</CardTitle>
              <CardDescription>What is waiting, by who acts on it.</CardDescription>
            </CardHeader>
            <CardContent>
              <StackedBar
                title="Hits in the queue"
                unit="hits"
                segments={groups.map((g) => ({
                  key: g.id,
                  label: g.id === 'review' ? 'Review · analyst' : g.id === 'same' ? 'Same entity · compliance' : 'No decision',
                  value: g.rows.length,
                  color: GROUP_TONE[g.id].bar,
                  halo: g.id === 'review',
                }))}
              />
              <p className="mt-4 text-xs text-muted-foreground">
                Alerts with a REVIEW hit: <b className="text-foreground tabular-nums">{new Set(groups[0].rows.map((r) => r.alert_id)).size}</b>. Clearing a
                hit wrongly costs 20× sending it to review, so these stay with a person until the evidence settles them.
              </p>
            </CardContent>
          </Card>
          <Card className="gap-4 lg:col-span-3">
            <CardHeader>
              <CardTitle>Why they need a person</CardTitle>
              <CardDescription>
                Top reasons across REVIEW and undecided hits (a hit can have several). Click one to show only those hits.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <BarList rows={tagRows} empty="No REVIEW hits." />
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
                {(['held', 'missing', 'identity'] as const).map((k) => (
                  <span key={k} className="inline-flex items-center gap-1.5">
                    <span className={cn('inline-block size-2 rounded-sm', TAG_TONE[k])} />
                    {KIND_TEXT[k]}
                  </span>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}

      {activeTag ? (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border bg-card px-4 py-2.5 text-sm">
          <span className="text-muted-foreground">Showing only</span>
          <span className="font-medium">{activeTag.label}</span>
          <span className="tabular-nums text-muted-foreground">
            {total} of {unfilteredTotal}
          </span>
          <Button variant="ghost" size="sm" onClick={() => pickTag(null)}>
            Show all ✕
          </Button>
        </div>
      ) : null}

      {hitId && !selected ? <MissingHit hitId={hitId} /> : null}
      <HitWorkspace list={list} selected={selected} onClose={() => onOpen(null)} />
    </div>
  )
}

const KIND_TEXT: Record<WhyTag['kind'], string> = {
  held: 'a contradiction was found, but a safety check held the clear',
  missing: 'a fact is missing on one side',
  identity: 'which customer it is is unclear',
  confirm: 'confirmed match',
}

function Pager({ page, pageCount, from, to, total, onPage }: { page: number; pageCount: number; from: number; to: number; total: number; onPage: (n: number) => void }) {
  return (
    <nav className="flex items-center justify-between gap-3 text-sm" aria-label="Pages">
      <span className="tabular-nums text-muted-foreground">
        {from}–{to} of {total}
      </span>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" disabled={page === 0} onClick={() => onPage(page - 1)}>
          ← Previous
        </Button>
        <span className="tabular-nums text-muted-foreground">
          Page {page + 1} of {pageCount}
        </span>
        <Button variant="outline" size="sm" disabled={page >= pageCount - 1} onClick={() => onPage(page + 1)}>
          Next →
        </Button>
      </div>
    </nav>
  )
}
