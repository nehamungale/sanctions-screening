// "Unstable only" filter over hit rows, driven by repro.json. Used by the Audit screen.
// Unstable = not officially reproducible (decision or reason code not identical in all runs, or missing
// from a run); see getUnstableHitIds.
// Pass `controlled` to keep the toggle in the URL; otherwise it keeps its own state.
import { useMemo, useState } from 'react'

import { getUnstableHitIds, type ReproReport } from './repro.ts'

export function useUnstableFilter(
  report: ReproReport | null,
  controlled?: { value: boolean; onChange: (v: boolean) => void },
) {
  const [own, setOwn] = useState(false)
  const unstableOnly = controlled ? controlled.value : own
  const setUnstableOnly = controlled ? controlled.onChange : setOwn
  const unstable = useMemo(() => new Set(getUnstableHitIds(report)), [report])
  const filter = <T extends { hit_id: string }>(rows: readonly T[]): T[] =>
    unstableOnly ? rows.filter((r) => unstable.has(r.hit_id)) : [...rows]
  return { unstableOnly, setUnstableOnly, unstable, available: report !== null, filter }
}
