import { useState, type FormEvent } from 'react'
import './pin.css'

/** Digits in the PIN: the service's PIN_DIGITS (service/gaffer/phone.py). */
const PIN_DIGITS = 6

/** What a phone shows before it has entered the PIN the Mac displays. */
export function PinScreen({ onSignedIn }: { onSignedIn: () => void }) {
  const [pin, setPin] = useState('')
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (busy || pin.length !== PIN_DIGITS) return
    setBusy(true)
    setProblem('')
    try {
      const res = await fetch('/api/session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin }),
      })
      if (res.ok) return onSignedIn()
      const body = (await res.json().catch(() => ({}))) as { message?: string }
      setProblem(body.message ?? 'That did not work. Try again.')
      setPin('')
    } catch {
      setProblem('Cannot reach Gaffer. Check that the Mac is on and awake.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="pin">
      <h1>Gaffer</h1>
      <form className="pin-card" onSubmit={submit}>
        <label htmlFor="pin">Enter the PIN shown on the Mac</label>
        <input
          id="pin"
          className="pin-input"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]*"
          maxLength={PIN_DIGITS}
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, PIN_DIGITS))}
          autoFocus
        />
        <p className="pin-note" role="alert">{problem}</p>
        <button type="submit" className="pin-go" disabled={busy || pin.length !== PIN_DIGITS}>Connect</button>
      </form>
    </main>
  )
}
