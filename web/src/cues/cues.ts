import { useEffect } from 'react'
import type { Cue } from '../lib/types'
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

/** Make a cue the active one, at the top. Nothing is applied until Go. */
export function startCue(id: string) {
  const { request, toast } = useStudio.getState()
  request({ type: 'cue.start', id }).catch((err: Error) => toast(err.message, 'error'))
}

/**
 * Space is Go while a cue is active (the Mac's Next cue shortcut works in any app; this is the page's own).
 * Ignored while a control has focus, because Space presses a focused button and moves a slider, and with a
 * modifier held, so the browser's shortcuts still work.
 */
export function useCueKey() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== ' ' || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey || e.repeat) return
      if (e.target instanceof HTMLElement && e.target.closest('input, textarea, select, button, a, summary, [contenteditable], [role=switch]')) return
      if (!useStudio.getState().cue) return
      e.preventDefault()
      goCue()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}
