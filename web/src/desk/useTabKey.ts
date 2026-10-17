import { useEffect, useRef } from 'react'
import { useStudio } from '../state/store'

/**
 * Tab flips between Glass and the desk (SPEC: "Tab toggles the view").
 *
 * The rule, so that keyboard users are never stuck: Tab flips the view only while nothing
 * has focus (the page itself). Once focus is on any control, Tab moves focus as usual, and
 * so does Shift+Tab, which is also how a keyboard user gets into the controls from the page.
 * A mouse or touch press on a slider or button hands focus back to the page when it lifts, so
 * Tab flips the view for pointer users; focus given by the keyboard is left alone.
 * It stays out of the way while a sheet or the command palette is open.
 */
export function useTabKey(toggle: () => void) {
  const latest = useRef(toggle)
  useEffect(() => { latest.current = toggle })
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Tab' || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey || e.defaultPrevented) return
      const { addLight, connectionSheet, palette } = useStudio.getState()
      if (addLight || connectionSheet || palette) return
      const focus = document.activeElement
      if (focus && focus !== document.body && focus !== document.documentElement) return
      e.preventDefault()
      latest.current()
    }
    const onLift = () => {
      const focus = document.activeElement
      if (focus instanceof HTMLElement && focus.matches('button, [role="slider"]')) focus.blur()
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('pointerup', onLift)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('pointerup', onLift)
    }
  }, [])
}
