import { useEffect, useState, type ReactNode } from 'react'
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

  if (gate.kind === 'in') return <>{children}</>
  if (gate.kind === 'pin') return <PinScreen onSignedIn={() => setGate({ kind: 'in' })} />
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
