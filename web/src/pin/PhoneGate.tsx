import { useEffect, useRef, useState, type ReactNode } from 'react'
import { SOCKET_CLOSED } from '../lib/socket'
import { PinScreen } from './PinScreen'

type Gate =
  | { kind: 'checking' }
  | { kind: 'in' }
  | { kind: 'pin' }
  | { kind: 'blocked'; text: string }

/**
 * Asks the service whether this browser is signed in before the studio opens (SPEC-015).
 * The Mac window always is. A phone that has not entered the PIN gets the PIN screen, and the
 * studio (and its light socket) is never loaded until it has: the studio is imported lazily by App.
 */
export function PhoneGate({ children }: { children: ReactNode }) {
  const [gate, setGate] = useState<Gate>({ kind: 'checking' })
  // Counts sign-ins. An answer to a question asked before a sign-in is out of date and is ignored.
  const signIns = useRef(0)

  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/session', { signal: controller.signal })
      .then(async (res) => {
        if (res.ok) return setGate({ kind: 'in' })
        const body = (await res.json().catch(() => ({}))) as { error?: string; message?: string }
        if (body.error === 'pin_required') return setGate({ kind: 'pin' })
        setGate({ kind: 'blocked', text: body.message ?? 'Gaffer is not available.' })
      })
      .catch((error: unknown) => {
        if ((error as { name?: string }).name !== 'AbortError') setGate({ kind: 'blocked', text: 'Cannot reach Gaffer. Check that the Mac is on and awake.' })
      })
    return () => controller.abort()
  }, [])

  // A phone that is signed out while the studio is open (New PIN, or access switched off) finds out
  // when its light socket closes: ask again, and act only on a clear answer from the service.
  useEffect(() => {
    const controller = new AbortController()
    const onClosed = () => {
      const asked = signIns.current
      fetch('/api/session', { signal: controller.signal })
        .then(async (res) => {
          if (res.ok) return
          const body = (await res.json().catch(() => ({}))) as { error?: string; message?: string }
          if (asked !== signIns.current) return
          if (body.error === 'pin_required') setGate({ kind: 'pin' })
          else if (body.error === 'phone_access_off') setGate({ kind: 'blocked', text: body.message ?? 'Phone access is off.' })
        })
        .catch(() => {}) // the service is not answering: the socket keeps retrying
    }
    window.addEventListener(SOCKET_CLOSED, onClosed)
    return () => {
      window.removeEventListener(SOCKET_CLOSED, onClosed)
      controller.abort()
    }
  }, [])

  if (gate.kind === 'in') return <>{children}</>
  if (gate.kind === 'pin') return <PinScreen onSignedIn={() => { signIns.current++; setGate({ kind: 'in' }) }} />
  if (gate.kind === 'blocked') {
    return (
      <main className="pin">
        <h1>Gaffer</h1>
        <p className="pin-note" role="alert">{gate.text}</p>
      </main>
    )
  }
  return null
}
