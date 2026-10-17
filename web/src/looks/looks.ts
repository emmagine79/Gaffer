import { useEffect } from 'react'
import type { Look } from '../lib/types'
import { EMPTY, useStudio } from '../state/store'

/** The saved looks in slot order: slot 1 is the first. */
export function useLooks(): Look[] {
  return useStudio((s) => s.store?.looks ?? EMPTY)
}

/** Run every light in the look to its values, over the look's own fade. */
export function applyLook(id: string) {
  useStudio.getState().send({ type: 'looks.apply', id })
}

/** Every light off at once. Says so when a light could not be reached and so stayed on. */
export async function allOff() {
  const { request, toast, lights } = useStudio.getState()
  try {
    const reply = (await request({ type: 'all.off' })) as { skipped?: string[] }
    const names = (reply.skipped ?? []).map((id) => lights.find((l) => l.id === id)?.name ?? 'A light')
    if (names.length > 0) {
      toast(`${names.join(', ')} could not be reached and ${names.length === 1 ? 'is' : 'are'} still on.`, 'error')
    }
  } catch (err) {
    toast((err as Error).message, 'error')
  }
}

/** A key press that belongs to a text box, not to the looks. */
function typing(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT') return true
  if (target.tagName !== 'INPUT') return false
  return !['range', 'checkbox', 'radio', 'button'].includes((target as HTMLInputElement).type)
}

/**
 * Keys 1 to 9 apply the looks in order and 0 turns every light off (the lighting desk's
 * numbered buttons, a-desk mockup). Ignored while typing and with a modifier held, so
 * the browser's and the Mac's own shortcuts still work.
 */
export function useLookKeys() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey || e.repeat || typing(e.target)) return
      if (!/^[0-9]$/.test(e.key)) return
      if (e.key === '0') {
        allOff()
      } else {
        const look = (useStudio.getState().store?.looks ?? EMPTY)[Number(e.key) - 1]
        if (!look) return
        applyLook(look.id)
      }
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}
