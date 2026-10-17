import { useEffect } from 'react'
import type { Cue } from '../lib/types'
import type { Surface } from '../app/surface'
import { EMPTY, useStudio } from '../state/store'

/** The saved cues. */
export function useCues(): Cue[] {
  return useStudio((s) => s.store?.cues ?? EMPTY)
}

/** Run the active cue's next step. The service says why when it cannot (the end of the list). */
export function goCue() {
  const { request, toast } = useStudio.getState()
  request({ type: 'cue.go' }).catch((err: Error) => toast(err.message, 'error'))
}

/** Step back to the step before the one that ran last. */
export function backCue() {
  const { request, toast } = useStudio.getState()
  request({ type: 'cue.back' }).catch((err: Error) => toast(err.message, 'error'))
}

/** Move past the step Go could not run (its lights are out of reach) without applying it. */
export function skipCue() {
  const { request, toast } = useStudio.getState()
  request({ type: 'cue.skip' }).catch((err: Error) => toast(err.message, 'error'))
}

/** Make a cue the active one, at the top. Nothing is applied until Go. */
export function startCue(id: string) {
  const { request, toast } = useStudio.getState()
  request({ type: 'cue.start', id }).catch((err: Error) => toast(err.message, 'error'))
}

/** Anything the person can press, type in or drag: Space belongs to it, not to the cue. */
const CONTROL = 'input, textarea, select, button, a, summary, [contenteditable], [role=switch], [role=slider]'

/**
 * Space is Go while a cue is active and has a step left to run (the Mac's Next cue shortcut works in any
 * app; this is the page's own). Only the Gaffer window listens: the menu-bar panel is a popover people open
 * to glance at, and the card asks for no shortcut on the phone. Space is ignored
 *  - while a control has keyboard focus (it presses a focused button and a fader is a control too),
 *  - after the last pointer press landed on a control, until a pointer press lands outside every control or
 *    on the cue bar itself: dragging a fader or tapping a switch hands focus back to the page (useTabKey), so
 *    the focus check alone cannot tell that the person was just using a control,
 *  - with a modifier held, so the browser's shortcuts still work,
 *  - while a sheet or the command palette is open, so it never fires lights behind them.
 */
export function useCueKey(surface: Surface) {
  useEffect(() => {
    if (surface !== 'window') return
    let onControl = false
    const onPointer = (e: PointerEvent) => {
      const target = e.target instanceof Element ? e.target : null
      onControl = !!target?.closest(CONTROL) && !target.closest('.cue-bar')
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== ' ' || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey || e.repeat || onControl) return
      if (e.target instanceof HTMLElement && e.target.closest(CONTROL)) return
      const { cue, addLight, connectionSheet, palette } = useStudio.getState()
      if (!cue?.next || addLight || connectionSheet || palette) return
      e.preventDefault()
      goCue()
    }
    window.addEventListener('pointerdown', onPointer, true)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('pointerdown', onPointer, true)
      window.removeEventListener('keydown', onKey)
    }
  }, [surface])
}
