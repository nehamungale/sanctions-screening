// Shared two-pane layout for Queue and Audit: a list on the left, the shared HitPanel on the right.
import type { ReactNode } from 'react'

import { HitPanel } from '@/components/HitPanel'
import type { HitRow } from '@/lib/worklist'

export function rowKey(r: { hit_id: string; alert_id: string | null }) {
  return `${r.alert_id ?? ''}|${r.hit_id}`
}

export function HitWorkspace({ list, selected, onClose }: { list: ReactNode; selected: HitRow | null; onClose: () => void }) {
  if (!selected) return <>{list}</>
  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
      <div className="lg:sticky lg:top-6 lg:max-h-[calc(100vh-3rem)] lg:overflow-y-auto">{list}</div>
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>
            Alert <span className="font-mono text-foreground">{selected.alert_id ?? '—'}</span>
          </span>
          <button type="button" className="cursor-pointer hover:text-foreground" onClick={onClose}>
            Close ✕
          </button>
        </div>
        <HitPanel hitId={selected.hit_id} hit={selected.hit} undecided={selected.undecided} />
      </div>
    </div>
  )
}
