import { AnimatePresence, motion } from 'motion/react'
import { ArrowRight, Check, FileKey2, LifeBuoy, Link2, RefreshCw, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Key } from '../components/Controls'
import { ModelPicker } from '../components/ModelPicker'
import { GodoxImport } from '../add/GodoxImport'
import type { Nearby } from '../lib/types'
import { useStudio } from '../state/store'
import { KIND_SHORT, LightGlyph, formOf } from '../visuals/LightGlyph'
import { SignalBars } from './MasterBar'
import './addlight.css'

const KIND_RGB = { rgb: [0.62, 0.45, 1], colour: [0.3, 0.85, 0.9], bicolour: [1, 0.8, 0.55], daylight: [0.95, 0.96, 1], unsupported: [0.5, 0.5, 0.5] } as const

const STEPS = [
  { id: 'provisioning', name: 'Give it the network keys', done: 'On your network' },
  { id: 'binding', name: 'Bind its control key', done: 'Ready for commands' },
] as const

const SECTIONS: { relation: Nearby['relation']; title: string; hint: string }[] = [
  { relation: 'unpaired', title: 'Ready to pair', hint: 'Factory-fresh or reset lights. Pairing takes about ten seconds.' },
  { relation: 'your-network', title: 'On your network', hint: 'Lights that already share your keys.' },
  { relation: 'elsewhere', title: 'Paired with something else', hint: 'The Godox app, Home Assistant or another computer holds their keys. Reset the light to pair it here, or import its keys file.' },
  { relation: 'saved', title: 'Already in the studio', hint: '' },
]

function readKeys(file: File): Promise<Record<string, unknown>> {
  return file.text().then((text) => {
    const data = JSON.parse(text) as unknown
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('That file is not a keys file')
    return data as Record<string, unknown>
  })
}

function NearbyRow({ n, onPair, onImport, busy }: { n: Nearby; onPair: () => void; onImport: () => void; busy: boolean }) {
  const kind = n.kind ?? 'unsupported'
  return (
    <li className={`nearby nearby--${n.relation}`}>
      <LightGlyph form={formOf(n.model ?? '')} rgb={[...KIND_RGB[kind]]} level={n.relation === 'unpaired' ? 0.7 : 0.25} size={38} />
      <span className="nearby-text">
        <strong>{n.model ?? 'Unknown model'}</strong>
        <small>{n.kind ? KIND_SHORT[n.kind] : 'Pick its model after pairing'} · {n.name ?? n.address}</small>
      </span>
      <span className="nearby-signal"><SignalBars rssi={n.rssi} /></span>
      {n.relation === 'unpaired' && <Key kind="primary" onClick={onPair} disabled={busy}><Link2 /> Pair</Key>}
      {n.relation === 'elsewhere' && <Key onClick={onImport}><FileKey2 /> Import keys</Key>}
      {(n.relation === 'saved' || n.relation === 'your-network') && <span className="nearby-saved"><Check size={14} /> Yours</span>}
    </li>
  )
}

/** Find lights in range and bring one into the studio: pair a fresh one, or import keys for one paired elsewhere. */
export function AddLight() {
  const open = useStudio((s) => s.addLight)
  const setOpen = useStudio((s) => s.setAddLight)
  const nearby = useStudio((s) => s.nearby)
  const scanning = useStudio((s) => s.scanning)
  const pairing = useStudio((s) => s.pairing)
  const lights = useStudio((s) => s.lights)
  const request = useStudio((s) => s.request)
  const send = useStudio((s) => s.send)
  const toast = useStudio((s) => s.toast)
  const select = useStudio((s) => s.select)
  const setTab = useStudio((s) => s.setTab)
  const [target, setTarget] = useState<Nearby | null>(null)
  const [newLight, setNewLight] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [importFor, setImportFor] = useState<string | null>(null)
  const [manualAddress, setManualAddress] = useState('')
  const [godox, setGodox] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  /** Bumped on every open, close and pairing, so a reply from an earlier one is ignored. */
  const attempt = useRef(0)

  const scan = () => {
    request({ type: 'lights.scan', seconds: 8 }, 20000).catch((err: Error) => toast(err.message, 'error'))
  }

  useEffect(() => {
    attempt.current++
    if (!open) return
    setTarget(null); setNewLight(null); setName(''); setGodox(false)
    scan()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const pair = async (n: Nearby) => {
    const mine = ++attempt.current
    setTarget(n)
    setNewLight(null)
    try {
      const reply = await request({ type: 'lights.pair', address: n.address, name: '' }, 90000)
      if (mine !== attempt.current) return // closed or restarted meanwhile: do not switch lights under the user
      const id = (reply as { light?: string }).light ?? null
      setNewLight(id)
      const made = useStudio.getState().lights.find((l) => l.id === id)
      setName(made?.name ?? '')
      if (id) select(id)
    } catch (err) {
      if (mine === attempt.current) toast((err as Error).message, 'error')
    }
  }

  const importKeys = async (file: File | undefined, address: string) => {
    if (!file) return
    try {
      const keys = await readKeys(file)
      const reply = await request({ type: 'lights.import', keys, address, name: '' }, 20000)
      const id = (reply as { light?: string }).light
      if (id) select(id)
      toast('Keys imported. Connecting to it now.', 'ok')
      setOpen(false)
    } catch (err) {
      toast((err as Error).message, 'error')
    } finally {
      setImportFor(null)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const close = () => setOpen(false)
  const made = lights.find((l) => l.id === newLight) ?? null
  const step = pairing && target && pairing.address === target.address ? pairing.step : null
  const failed = step === 'failed'
  const doneIndex = step === 'done' || step === 'bound' ? 2 : step === 'binding' ? 1 : 0

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="conn conn--sheet" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          role="dialog" aria-modal="true" aria-label="Add a light" onPointerDown={(e) => { if (e.target === e.currentTarget) close() }}>
          <motion.div className="addlight" initial={{ y: 18, scale: 0.98 }} animate={{ y: 0, scale: 1 }} exit={{ y: -10 }}>
            <button type="button" className="conn-close" aria-label="Close" onClick={close}><X size={18} /></button>
            <input ref={fileRef} type="file" accept=".json,application/json" hidden
              onChange={(e) => importKeys(e.target.files?.[0], importFor ?? manualAddress)} />

            {godox ? (
              <GodoxImport onDone={() => { setGodox(false); setOpen(false) }} />
            ) : target ? (
              <div className="pairing">
                <div className={`pairing-visual ${made ? 'is-done' : failed ? 'is-failed' : ''}`}>
                  <div className="conn-rings" aria-hidden="true"><i /><i /><i /></div>
                  <LightGlyph form={formOf(made?.model ?? target.model ?? '')} rgb={made ? [1, 0.86, 0.66] : [0.75, 0.78, 0.85]}
                    level={made ? 1 : 0.2} size={108} />
                </div>
                <h2 className="conn-title">{made ? `${made.model} is ready` : failed ? 'Pairing stopped' : `Pairing the ${target.model ?? 'light'}`}</h2>
                <p className="conn-body muted">
                  {made ? 'It is on your mesh and the studio is connecting to it.'
                    : failed ? pairing?.error
                      : 'Keep the light on and close by. This takes about ten seconds.'}
                </p>
                {!made && (
                  <ol className="conn-steps">
                    {STEPS.map((s, i) => {
                      const state = i < doneIndex ? 'done' : i === doneIndex && !failed ? 'now' : 'todo'
                      return (
                        <li key={s.id} className={`is-${state}`}>
                          <span className="conn-step-dot">{state === 'done' ? <Check size={13} strokeWidth={3} /> : i + 1}</span>
                          <span>{state === 'done' ? s.done : s.name}</span>
                        </li>
                      )
                    })}
                  </ol>
                )}
                {made && (
                  <div className="pairing-done">
                    <label className="field">
                      <span className="field-label">Name it</span>
                      <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Key light, Fill, Hair..."
                        onBlur={() => name.trim() && name !== made.name && send({ type: 'lights.rename', light: made.id, name })} />
                    </label>
                    {!made.known_model && (
                      <div className="pairing-model">
                        <p className="field-label">It did not say which model it is. Pick it, so the studio shows the right controls.</p>
                        <ModelPicker onPick={(radio_id) => send({ type: 'lights.model', light: made.id, radio_id })} />
                      </div>
                    )}
                  </div>
                )}
                <div className="conn-actions">
                  {made && <Key kind="primary" onClick={() => { if (name.trim() && name !== made.name) send({ type: 'lights.rename', light: made.id, name }); setTab('live'); close() }}>Start using it <ArrowRight /></Key>}
                  {made && <Key onClick={() => { setTarget(null); setNewLight(null); scan() }}>Add another</Key>}
                  {failed && <Key kind="primary" onClick={() => pair(target)}><RefreshCw /> Try again</Key>}
                  {failed && <Key kind="ghost" onClick={() => { setTab('guide'); close() }}><LifeBuoy /> Pairing help</Key>}
                  {failed && <Key kind="ghost" onClick={() => setTarget(null)}>Back to the list</Key>}
                </div>
              </div>
            ) : (
              <>
                <header className="addlight-head">
                  <div className={`addlight-radar ${scanning ? 'is-scanning' : ''}`} aria-hidden="true"><i /><b /></div>
                  <div>
                    <h2 className="addlight-title">Add a light</h2>
                    <p className="muted">{scanning ? 'Listening for Godox lights nearby...' : `${nearby.length} found nearby`}</p>
                  </div>
                  <Key onClick={scan} disabled={scanning}><RefreshCw className={scanning ? 'spin-slow' : ''} /> {scanning ? 'Scanning' : 'Scan again'}</Key>
                </header>

                <div className="addlight-body">
                  {SECTIONS.map((section) => {
                    const rows = nearby.filter((n) => n.relation === section.relation)
                    if (!rows.length) return null
                    return (
                      <section key={section.relation} className="addlight-section">
                        <h3>{section.title}</h3>
                        {section.hint && <p className="hint">{section.hint}</p>}
                        <ul className="nearby-list">
                          {rows.map((n) => (
                            <NearbyRow key={n.address} n={n} onPair={() => pair(n)}
                              busy={Boolean(pairing && !['done', 'failed'].includes(pairing.step))}
                              onImport={() => { setImportFor(n.address); fileRef.current?.click() }} />
                          ))}
                        </ul>
                      </section>
                    )
                  })}
                  {!scanning && nearby.length === 0 && (
                    <div className="addlight-empty">
                      <p><strong>No Godox lights heard.</strong></p>
                      <p className="muted">Switch the light on, keep it within a few metres, and make sure Bluetooth is on for this computer. A light that is connected to a phone right now stays silent until the phone lets go.</p>
                    </div>
                  )}
                </div>

                <footer className="addlight-foot">
                  <div className="addlight-manual">
                    <span className="field-label">Have a keys file from the CLI or Home Assistant?</span>
                    <div className="addlight-manual-row">
                      <input className="input" value={manualAddress} onChange={(e) => setManualAddress(e.target.value)} placeholder="Light address, AA:BB:CC:DD:EE:FF" aria-label="Light address" />
                      <Key disabled={!/^([0-9a-f]{2}[:-]){5}[0-9a-f]{2}$/i.test(manualAddress.trim())}
                        onClick={() => { setImportFor(null); fileRef.current?.click() }}><FileKey2 /> Choose file</Key>
                    </div>
                  </div>
                  <button type="button" className="addlight-help" onClick={() => setGodox(true)}>
                    <FileKey2 size={15} /> Import from the Godox app
                  </button>
                  <button type="button" className="addlight-help" onClick={() => { setTab('guide'); close() }}>
                    <LifeBuoy size={15} /> Light not listed? How to reset and pair
                  </button>
                </footer>
              </>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
