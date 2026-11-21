// Small dependency-free charts. Widths are set through React's style prop (CSSOM), which the
// build's CSP (style-src 'self') allows; no inline <style> or style="" attributes are emitted.
import { cn } from '@/lib/utils'

export interface Segment {
  key: string
  label: string
  value: number
  /** Tailwind background class, e.g. bg-red-600 */
  color: string
  /** Tailwind stroke class for the donut, e.g. stroke-red-600 */
  stroke?: string
  onClick?: () => void
  /** Draw a pulsing ring around this segment's legend entry. */
  halo?: boolean
}

const pct = (v: number, total: number) => (total > 0 ? Math.round((v / total) * 1000) / 10 : 0)

/** One horizontal 100% bar split into segments, with a clickable legend underneath. */
export function StackedBar({ title, segments, unit }: { title: string; segments: Segment[]; unit: string }) {
  const total = segments.reduce((n, s) => n + s.value, 0)
  const shown = segments.filter((s) => s.value > 0)
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium">{title}</span>
        <span className="text-xs tabular-nums text-muted-foreground">
          {total} {unit}
        </span>
      </div>
      <div className="flex h-4 w-full overflow-hidden rounded-full bg-muted" role="img" aria-label={`${title}: ${shown.map((s) => `${s.label} ${s.value}`).join(', ')}`}>
        {shown.map((s) => (
          <span key={s.key} className={cn('h-full first:rounded-l-full last:rounded-r-full', s.color)} style={{ width: `${(s.value / total) * 100}%` }} title={`${s.label}: ${s.value} (${pct(s.value, total)}%)`} />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-1 gap-y-1">
        {segments.map((s) => (
          <button
            key={s.key}
            type="button"
            disabled={!s.onClick}
            onClick={s.onClick}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-xs',
              s.onClick && 'cursor-pointer hover:bg-muted',
              s.halo && s.value > 0 && 'halo ring-1 ring-amber-400',
            )}
          >
            <span className={cn('inline-block size-2.5 rounded-sm', s.color)} />
            <span>{s.label}</span>
            <span className="font-semibold tabular-nums">{s.value}</span>
            <span className="tabular-nums text-muted-foreground">{pct(s.value, total)}%</span>
          </button>
        ))}
      </div>
    </div>
  )
}

export interface BarRow {
  key: string
  label: string
  sub?: string
  value: number
  color: string
  onClick?: () => void
}

/** Horizontal bars, one per row, scaled to the largest value. */
export function BarList({ rows, empty = 'Nothing to show.' }: { rows: BarRow[]; empty?: string }) {
  const max = Math.max(0, ...rows.map((r) => r.value))
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>
  return (
    <ul className="flex flex-col gap-1">
      {rows.map((r) => {
        const body = (
          <>
            <span className="flex min-w-0 flex-col">
              <span className={cn('truncate font-mono text-xs', r.value === 0 && 'text-muted-foreground')}>{r.label}</span>
              {r.sub ? <span className="truncate text-[11px] text-muted-foreground">{r.sub}</span> : null}
            </span>
            <span className="relative h-2.5 w-full overflow-hidden rounded-full bg-muted">
              <span className={cn('absolute inset-y-0 left-0 rounded-full', r.color)} style={{ width: max ? `${(r.value / max) * 100}%` : '0%' }} />
            </span>
            <span className={cn('text-right text-sm tabular-nums', r.value === 0 && 'text-muted-foreground')}>{r.value}</span>
          </>
        )
        const cls = 'grid w-full grid-cols-[minmax(0,15rem)_minmax(0,1fr)_3rem] items-center gap-3 rounded-md px-2 py-1.5 text-left'
        return (
          <li key={r.key}>
            {r.onClick ? (
              <button type="button" onClick={r.onClick} className={cn(cls, 'cursor-pointer hover:bg-muted/60')}>
                {body}
              </button>
            ) : (
              <div className={cls}>{body}</div>
            )}
          </li>
        )
      })}
    </ul>
  )
}

/** Donut chart drawn with SVG stroke dashes. */
export function Donut({ segments, center, sub }: { segments: Segment[]; center: string; sub: string }) {
  const total = segments.reduce((n, s) => n + s.value, 0)
  const r = 42
  const c = 2 * Math.PI * r
  let offset = 0
  return (
    <svg viewBox="0 0 120 120" className="size-36 shrink-0" role="img" aria-label={segments.map((s) => `${s.label} ${s.value}`).join(', ')}>
      <circle cx="60" cy="60" r={r} fill="none" strokeWidth="14" className="stroke-muted" />
      {total > 0
        ? segments
            .filter((s) => s.value > 0)
            .map((s) => {
              const len = (s.value / total) * c
              const el = (
                <circle
                  key={s.key}
                  cx="60"
                  cy="60"
                  r={r}
                  fill="none"
                  strokeWidth="14"
                  strokeDasharray={`${len} ${c - len}`}
                  strokeDashoffset={-offset}
                  transform="rotate(-90 60 60)"
                  className={s.stroke ?? 'stroke-slate-400'}
                >
                  <title>{`${s.label}: ${s.value}`}</title>
                </circle>
              )
              offset += len
              return el
            })
        : null}
      <text x="60" y="58" textAnchor="middle" className="fill-foreground text-[22px] font-semibold">
        {center}
      </text>
      <text x="60" y="76" textAnchor="middle" className="fill-muted-foreground text-[9px]">
        {sub}
      </text>
    </svg>
  )
}
