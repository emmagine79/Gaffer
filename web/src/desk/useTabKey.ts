import { useEffect } from 'react'
import { useStudio } from '../state/store'

/** Typing in these keeps Tab for moving between fields. */
const TEXT = 'input:not([type=range]):not([type=checkbox]):not([type=radio]):not([type=button]), textarea, select, [contenteditable]'

/**
 * Tab flips between Glass and the desk (SPEC: "Tab toggles the view").
 * Left alone: Shift+Tab and other chords, typing in a text field, and while the
 * Add a light sheet is open, so keyboard users can still move around those.
 */
export function useTabKey(toggle: () => void) {
  const sheetOpen = useStudio((s) => s.addLight)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Tab' || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey || e.defaultPrevented) return
      if (sheetOpen || (e.target instanceof Element && e.target.closest(TEXT))) return
      e.preventDefault()
      toggle()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [toggle, sheetOpen])
}
