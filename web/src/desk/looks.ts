import { useCallback } from 'react'
import type { Scene } from '../lib/types'
import { EMPTY, useStudio } from '../state/store'

export interface DeskLook { id: string; name: string }

/**
 * The numbered look buttons on the desk, behind one small adapter.
 * SPEC-010 brings looks that set every light with their own fade; until then the desk
 * lists lumen's saved scenes and applies the chosen one to every light.
 * Swap this file's two functions for the looks service and the desk does not change.
 */
export function useDeskLooks(): { looks: DeskLook[]; apply: (id: string) => void; allOff: () => void } {
  const scenes = useStudio((s) => (s.store?.scenes as Scene[] | undefined) ?? EMPTY)
  const lights = useStudio((s) => s.lights)
  const send = useStudio((s) => s.send)
  const powerOf = useStudio((s) => s.powerOf)
  const apply = useCallback(
    (id: string) => lights.forEach((l) => send({ type: 'scene.apply', id, light: l.id })),
    [lights, send],
  )
  const allOff = useCallback(() => lights.forEach((l) => powerOf(l.id, false)), [lights, powerOf])
  return { looks: scenes.map((s) => ({ id: s.id, name: s.name })), apply, allOff }
}
