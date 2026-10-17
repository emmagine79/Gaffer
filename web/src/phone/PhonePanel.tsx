import { useEffect, useRef, useState } from 'react'
import './phone.css'

interface Target { kind: 'wifi' | 'tailscale'; label: string; url: string; qr: string }
interface PhoneStatus { enabled: boolean; pin: string | null; locked: boolean; tailscale: boolean | null; targets: Target[] }

async function call(path: string, body?: unknown): Promise<PhoneStatus> {
  const res = await fetch(path, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error((data as { message?: string }).message ?? 'That did not work. Try again.')
  return data as PhoneStatus
}

/** The Mac window's phone access: switch it on, then show the QR code(s), the PIN and New PIN. */
export function PhonePanel() {
  const dialog = useRef<HTMLDialogElement>(null)
  const [status, setStatus] = useState<PhoneStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [problem, setProblem] = useState('')

  useEffect(() => {
    call('/api/phone').then(setStatus).catch(() => setStatus(null))
  }, [])

  async function act(path: string, body: unknown) {
    if (busy) return
    setBusy(true)
    setProblem('')
    try {
      setStatus(await call(path, body))
    } catch (error) {
      setProblem((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const open = () => {
    call('/api/phone').then(setStatus).catch(() => {})
    dialog.current?.showModal()
  }

  return (
    <>
      <button type="button" className="ph-open" onClick={open}>
        Phone{status?.enabled ? ' · on' : ''}
      </button>
      <dialog ref={dialog} className="ph" aria-labelledby="ph-title">
        <header className="ph-head">
          <h2 id="ph-title">Phone access</h2>
          <button type="button" className="ph-x" aria-label="Close" onClick={() => dialog.current?.close()}>Close</button>
        </header>
        {!status?.enabled ? (
          <>
            <p className="ph-note">Control your lights from a phone on the same Wi-Fi, or away from home with Tailscale. Anyone who scans the code also needs the PIN.</p>
            <button type="button" className="ph-main" disabled={busy} onClick={() => act('/api/phone', { enabled: true })}>Turn on phone access</button>
          </>
        ) : (
          <>
            <p className="ph-note">Scan a code with the phone camera, then type this PIN.</p>
            <p className="ph-pin" aria-label="PIN">{status.pin}</p>
            {status.locked && <p className="ph-warn" role="alert">Too many wrong PINs. Press New PIN to let phones try again.</p>}
            <div className="ph-codes">
              {status.targets.map((t) => (
                <figure key={t.kind} className="ph-code">
                  <img src={t.qr} alt={`QR code for ${t.label}`} />
                  <figcaption><strong>{t.label}</strong><span className="ph-url">{t.url}</span></figcaption>
                </figure>
              ))}
            </div>
            {status.targets.length === 0 && <p className="ph-note">This Mac has no network address to share. Connect it to Wi-Fi.</p>}
            {status.tailscale === false && <p className="ph-note">To reach Gaffer away from home, install Tailscale on this Mac and your phone.</p>}
            <div className="ph-row">
              <button type="button" disabled={busy} onClick={() => act('/api/phone/pin', {})}>New PIN</button>
              <button type="button" disabled={busy} onClick={() => act('/api/phone', { enabled: false })}>Turn off</button>
            </div>
          </>
        )}
        <p className="ph-warn" role="alert">{problem}</p>
      </dialog>
    </>
  )
}
