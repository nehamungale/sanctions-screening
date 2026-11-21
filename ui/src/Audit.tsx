import type { ReactNode } from 'react'

import { HitWorkspace, rowKey } from '@/HitWorkspace'
import { DecisionBadge, ReasonCode, RunStrip } from '@/components/verdict'
import type { buildRepro, Model } from '@/lib/data'
import { reasonLabel } from '@/lib/labels'
import { DECISIONS, HIT_NOT_DECIDED, REASON_CODES } from '@/lib/policy'
import { useUnstableFilter } from '@/lib/useUnstableFilter'
import { cn } from '@/lib/utils'
import { allHitRows, filterRows, NO_FILTERS, type AuditFilters, type HitRow } from '@/lib/worklist'

interface Props {
  model: Model
  repro: ReturnType<typeof buildRepro>
  filters: AuditFilters
  alertId: string | null
  hitId: string | null
  onFilters: (f: AuditFilters) => void
  onOpen: (r: HitRow | null) => void
}

/** Audit: every hit, filterable; filters live in the URL. */
export function Audit({ model, repro, filters, alertId, hitId, onFilters, onOpen }: Props) {
  const report = repro?.report ?? null
  const unstable = useUnstableFilter(report, { value: filters.unstable, onChange: (v) => onFilters({ ...filters, unstable: v }) })
  const rows = allHitRows(model)
  const shown = filterRows(rows, { ...filters, unstable: false }, unstable.unstable)
  const visible = unstable.filter(shown)
  const selected = hitId ? (rows.find((r) => r.hit_id === hitId && (alertId === null || r.alert_id === alertId)) ?? null) : null
  const compact = selected !== null
  const strips = new Map(report?.hits.map((h) => [h.hit_id, h.per_run]) ?? [])
  const active = filters.verdict || filters.code || filters.fragility || filters.unstable || filters.llm
  const set = (patch: Partial<AuditFilters>) => onFilters({ ...filters, ...patch })

  const list = (
    <div className="flex flex-col gap-3">
      {visible.length === 0 ? (
        <p className="rounded-xl border bg-card px-4 py-6 text-center text-sm text-muted-foreground">No hits match these filters.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border bg-card">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground">
              <tr className="border-b">
                <th className="px-4 py-2.5 font-medium">Hit</th>
                {!compact ? <th className="px-4 py-2.5 font-medium">Alert</th> : null}
                <th className="px-4 py-2.5 font-medium">Verdict</th>
                {!compact ? (
                  <>
                    <th className="px-4 py-2.5 font-medium">Reason code</th>
                    <th className="px-4 py-2.5 font-medium">Fragility</th>
                    {report ? <th className="px-4 py-2.5 font-medium">Runs</th> : null}
                    <th className="px-4 py-2.5 font-medium">LLM</th>
                  </>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => {
                const isActive = selected && rowKey(selected) === rowKey(r)
                const strip = strips.get(r.hit_id)
                return (
                  <tr
                    key={rowKey(r)}
                    onClick={() => onOpen(r)}
                    className={cn('cursor-pointer border-b last:border-0 hover:bg-muted/50', isActive && 'bg-muted', unstable.unstable.has(r.hit_id) && !compact && 'bg-amber-50/60')}
                  >
                    <td className="px-4 py-2.5 font-mono">
                      <button type="button" className="cursor-pointer underline-offset-4 hover:underline" onClick={() => onOpen(r)}>
                        {r.hit_id}
                      </button>
                    </td>
                    {!compact ? <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">{r.alert_id ?? '—'}</td> : null}
                    <td className="px-4 py-2.5">
                      <DecisionBadge decision={r.decision} />
                    </td>
                    {!compact ? (
                      <>
                        <td className="px-4 py-2.5">
                          <ReasonCode code={r.reason_code} />
                        </td>
                        <td className="px-4 py-2.5 text-xs">{r.fragility ?? '—'}</td>
                        {report ? (
                          <td className="px-4 py-2.5">{strip ? <RunStrip cells={strip} labels={report.run_labels} /> : <span className="text-xs text-muted-foreground">not in report</span>}</td>
                        ) : null}
                        <td className="px-4 py-2.5 text-xs text-muted-foreground">{r.llm_used === true ? 'used' : r.llm_used === false ? '—' : 'unknown'}</td>
                      </>
                    ) : null}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Audit</h1>
        <p className="mt-1 text-sm text-muted-foreground">Every hit, with its verdict, reason code and the records it rests on.</p>
      </div>

      <div className="flex flex-wrap items-end gap-4 rounded-xl border bg-card px-5 py-4">
        <Filter label="Verdict">
          <select className={SELECT} value={filters.verdict ?? ''} onChange={(e) => set({ verdict: (e.target.value || null) as AuditFilters['verdict'] })}>
            <option value="">All</option>
            {DECISIONS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
            <option value="none">no decision</option>
          </select>
        </Filter>
        <Filter label="Reason code">
          <select className={cn(SELECT, 'max-w-72')} value={filters.code ?? ''} onChange={(e) => set({ code: e.target.value || null })}>
            <option value="">All</option>
            {[...Object.values(REASON_CODES).flat(), HIT_NOT_DECIDED].map((c) => (
              <option key={c} value={c}>
                {c} · {reasonLabel(c)}
              </option>
            ))}
          </select>
        </Filter>
        <Filter label="Fragility">
          <select className={SELECT} value={filters.fragility ?? ''} onChange={(e) => set({ fragility: e.target.value || null })}>
            <option value="">All</option>
            <option value="solid">solid</option>
            <option value="thin">thin</option>
            <option value="borderline">borderline</option>
            <option value="unknown">unknown</option>
          </select>
        </Filter>
        <Filter label="LLM">
          <select className={SELECT} value={filters.llm ?? ''} onChange={(e) => set({ llm: (e.target.value || null) as AuditFilters['llm'] })}>
            <option value="">All</option>
            <option value="no">not used</option>
            <option value="yes">used</option>
          </select>
        </Filter>
        <label className={cn('flex h-9 items-center gap-2 text-sm', !unstable.available && 'text-muted-foreground')}>
          <input
            type="checkbox"
            className="size-4"
            checked={unstable.unstableOnly}
            disabled={!unstable.available}
            onChange={(e) => unstable.setUnstableOnly(e.target.checked)}
          />
          Unstable across runs only{!unstable.available ? ' (load repro.json)' : ''}
        </label>
        <div className="ml-auto flex items-center gap-3 text-sm">
          <span className="tabular-nums">
            Showing <span className="font-semibold">{visible.length}</span> of {rows.length} hits
          </span>
          {active ? (
            <button type="button" className="cursor-pointer text-muted-foreground hover:text-foreground" onClick={() => onFilters(NO_FILTERS)}>
              Reset
            </button>
          ) : null}
        </div>
      </div>

      <HitWorkspace list={list} selected={selected} onClose={() => onOpen(null)} />
    </div>
  )
}

const SELECT = 'h-9 rounded-md border bg-background px-2 text-sm'

function Filter({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
      {label}
      {children}
    </label>
  )
}
