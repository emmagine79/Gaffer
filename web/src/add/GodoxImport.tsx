import { Check, FileKey2 } from 'lucide-react'
import { useRef, useState } from 'react'
import { Key } from '../components/Controls'
import { useStudio } from '../state/store'

/** How to get the Godox app's data onto this Mac, then where to put it. iPhone first. */
export const GODOX_STEPS = [
  'Connect your iPhone to this Mac with a cable, then open Finder and select the iPhone in the sidebar.',
  'Open the Files tab. The Godox app is listed there. Drag the Godox app folder onto your Mac.',
  'Inside that folder, find GodoxLight.db and choose it below. Or open it with any SQLite tool, copy the meshJson cell from the Project table, and paste it below.',
  'Gaffer saves every Godox light in the export. Your lights keep working in the Godox app, and nothing needs pairing again.',
]

/** Bytes to base64 in slices, so a large file does not overflow the call stack. */
function toBase64(bytes: Uint8Array): string {
  let out = ''
  for (let i = 0; i < bytes.length; i += 0x8000) out += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(out)
}

type Done = { lights: string[]; skipped: string[] }

export function GodoxImport({ onDone }: { onDone: () => void }) {
  const request = useStudio((s) => s.request)
  const toast = useStudio((s) => s.toast)
  const select = useStudio((s) => s.select)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState<Done | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const send = async (fields: Record<string, unknown>) => {
    setBusy(true)
    try {
      const reply = (await request({ type: 'lights.import', ...fields }, 30000)) as { light?: string; lights?: string[]; skipped?: string[] }
      if (reply.light) select(reply.light)
      setDone({ lights: reply.lights ?? [], skipped: reply.skipped ?? [] })
    } catch (err) {
      toast((err as Error).message, 'error')
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const chooseFile = async (file: File | undefined) => {
    if (!file) return
    await send({ db: toBase64(new Uint8Array(await file.arrayBuffer())) })
  }

  if (done) {
    return (
      <div className="godox-import" aria-label="Godox import">
        <h2 className="addlight-title"><Check size={18} /> {done.lights.length} {done.lights.length === 1 ? 'light' : 'lights'} imported</h2>
        <p className="muted">The studio is connecting to them now. Pick each light's model so it shows the right controls.</p>
        {done.skipped.length > 0 && <ul className="hint">{done.skipped.map((s) => <li key={s}>Skipped {s}</li>)}</ul>}
        <div className="conn-actions"><Key kind="primary" onClick={onDone}>Done</Key></div>
      </div>
    )
  }

  return (
    <div className="godox-import" aria-label="Godox import">
      <h2 className="addlight-title">Import from the Godox app</h2>
      <ol className="godox-steps">{GODOX_STEPS.map((s) => <li key={s}>{s}</li>)}</ol>
      <input ref={fileRef} type="file" accept=".db,application/octet-stream" hidden onChange={(e) => chooseFile(e.target.files?.[0])} />
      <Key kind="primary" disabled={busy} onClick={() => fileRef.current?.click()}><FileKey2 /> Choose GodoxLight.db</Key>
      <label className="field">
        <span className="field-label">Or paste the meshJson text</span>
        <textarea className="input" rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder='{"netKeys": [...], "appKeys": [...], "nodes": [...]}' />
      </label>
      <Key disabled={busy || !text.trim()} onClick={() => send({ meshJson: text })}>Import pasted text</Key>
    </div>
  )
}
