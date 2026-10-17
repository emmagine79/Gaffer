import { AnimatePresence, motion } from 'motion/react'
import { ArrowRight, Check, FileKey2, Link2, Plus, RefreshCw, RotateCcw, X, Zap } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ModelPicker } from '../components/ModelPicker'
import type { ModelRow, Nearby } from '../lib/types'
import { useStudio } from '../state/store'
import { KIND_SHORT, LightGlyph, formOf } from '../visuals/LightGlyph'
import { GodoxImport } from './GodoxImport'
import './add.css'

const KIND_RGB = { rgb: [0.62, 0.45, 1], colour: [0.3, 0.85, 0.9], bicolour: [1, 0.8, 0.55], daylight: [0.95, 0.96, 1], unsupported: [0.5, 0.5, 0.5] } as const

/** Signal strength as four bars. */
function SignalBars({ rssi }: { rssi: number | null }) {
  const bars = rssi === null ? 0 : rssi > -55 ? 4 : rssi > -65 ? 3 : rssi > -75 ? 2 : 1
  return (
    <span className="ad-signal" role="img" aria-label={rssi === null ? 'No signal' : `Signal ${rssi} dBm`}>
      {[1, 2, 3, 4].map((b) => <i key={b} className={b <= bars ? 'on' : ''} style={{ height: 3 + b * 3 }} />)}
    </span>
  )
}

const STEPS = [
  { id: 'provisioning', name: 'Give it the network keys', done: 'On your network' },
  { id: 'binding', name: 'Bind its control key', done: 'Ready for commands' },
] as const

const SECTIONS: { relations: Nearby['relation'][]; title: string; hint: string }[] = [
  { relations: ['new', 'unpaired'], title: 'Ready to add', hint: 'Pick the model you have. Godox lights that were factory-reset pair in about ten seconds.' },
  { relations: ['elsewhere'], title: 'Paired with something else', hint: 'The Godox app, Home Assistant or another computer holds their keys. Reset the light, then pair it here. No Godox app needed.' },
  { relations: ['your-network', 'saved'], title: 'Already in the studio', hint: '' },
]

function readKeys(file: File): Promise<Record<string, unknown>> {
  return file.text().then((text) => {
    const data = JSON.parse(text) as unknown
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new Error('That file is not a keys file')
    return data as Record<string, unknown>
  })
}

/** Shown when no manufacturer source is known for a model: never invented steps. */
const GENERIC_RESET = "Reset the light's Bluetooth as its manual describes, then press Pair."

/** A model row as the service sends it: `reset_steps` is empty when no source is known. */
type ModelWithReset = ModelRow & { reset_steps?: string[] }

type Flash = 'idle' | 'flashing' | 'done' | 'failed'
/** `added` is true for a light saved with `lights.add` (Zhiyun, Yongnuo): only that can be undone with "Not this one". */
type Stage = { at: 'list' } | { at: 'godox' } | { at: 'reset'; n: Nearby } | { at: 'pick'; n: Nearby } | { at: 'pair'; n: Nearby } | { at: 'made'; id: string; added: boolean }

function Key({ children, onClick, disabled, kind = 'plain' }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; kind?: 'plain' | 'primary' | 'ghost'
}) {
  return <button type="button" className={`ad-key ad-key--${kind}`} onClick={onClick} disabled={disabled}>{children}</button>
}

function Glyph({ n, size = 38 }: { n: Nearby; size?: number }) {
  return <LightGlyph form={formOf(n.model ?? '')} rgb={[...KIND_RGB[n.kind ?? 'unsupported']]} level={n.relation === 'unpaired' || n.relation === 'new' ? 0.7 : 0.25} size={size} />
}

function RowBody({ n }: { n: Nearby }) {
  return (
    <>
      <Glyph n={n} />
      <span className="ad-text">
        <strong>{n.model ?? 'Unknown model'}</strong>
        <small>{[n.brand, n.kind ? KIND_SHORT[n.kind] : null, n.name ?? n.address].filter(Boolean).join(' · ')}</small>
      </span>
      <SignalBars rssi={n.rssi} />
    </>
  )
}

/** Find lights in range and bring one in: pick it, flash it so you know which, name it. */
export function AddLight() {
  const open = useStudio((s) => s.addLight)
  const setOpen = useStudio((s) => s.setAddLight)
  const nearby = useStudio((s) => s.nearby)
  const scanning = useStudio((s) => s.scanning)
  const pairing = useStudio((s) => s.pairing)
  const lights = useStudio((s) => s.lights)
  const models = useStudio((s) => s.models) as ModelWithReset[]
  const request = useStudio((s) => s.request)
  const send = useStudio((s) => s.send)
  const toast = useStudio((s) => s.toast)
  const select = useStudio((s) => s.select)
  const [stage, setStage] = useState<Stage>({ at: 'list' })
  const [name, setName] = useState('')
  const [channel, setChannel] = useState('')
  const [flash, setFlash] = useState<Flash>('idle')
  const [working, setWorking] = useState(false)
  const [importFor, setImportFor] = useState<string | null>(null)
  const [manualAddress, setManualAddress] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  /** Bumped on every open, close and new choice, so a reply from an earlier one is ignored. */
  const attempt = useRef(0)

  const scan = () => {
    request({ type: 'lights.scan', seconds: 8 }, 20000).catch((err: Error) => toast(err.message, 'error'))
  }

  useEffect(() => {
    attempt.current++
    if (!open) return
    setStage({ at: 'list' }); setName(''); setChannel(''); setFlash('idle'); setWorking(false)
    scan()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const flashIt = async (id: string, mine: number) => {
    setFlash('flashing')
    try {
      await request({ type: 'lights.identify', light: id }, 45000)
      if (mine === attempt.current) setFlash('done')
    } catch (err) {
      if (mine !== attempt.current) return
      setFlash('failed')
      toast((err as Error).message, 'error')
    }
  }

  /** Reached with a saved light: show it, put its name in the field, and flash it. */
  const arrived = (id: string | null, mine: number, added: boolean) => {
    if (!id) return
    setStage({ at: 'made', id, added })
    setName(useStudio.getState().lights.find((l) => l.id === id)?.name ?? '')
    select(id)
    void flashIt(id, mine)
  }

  const add = async (n: Nearby) => {
    const mine = ++attempt.current
    setWorking(true)
    try {
      const reply = await request({ type: 'lights.add', address: n.address, ...(n.needs_channel ? { channel: Number(channel) } : {}) }, 20000)
      if (mine === attempt.current) arrived((reply as { light?: string }).light ?? null, mine, true)
    } catch (err) {
      if (mine === attempt.current) toast((err as Error).message, 'error')
    } finally {
      if (mine === attempt.current) setWorking(false)
    }
  }

  const pair = async (n: Nearby) => {
    const mine = ++attempt.current
    setStage({ at: 'pair', n })
    try {
      const reply = await request({ type: 'lights.pair', address: n.address, name: '' }, 90000)
      if (mine === attempt.current) arrived((reply as { light?: string }).light ?? null, mine, false)
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

  const resetSteps = (n: Nearby): string[] => {
    const steps = models.find((m) => m.radio_id === n.radio_id)?.reset_steps
    return steps && steps.length ? steps : [GENERIC_RESET]
  }

  const close = () => setOpen(false)
  const made = stage.at === 'made' ? lights.find((l) => l.id === stage.id) ?? null : null

  const finish = () => {
    if (!made) return
    const trimmed = name.trim()
    if (trimmed && trimmed !== made.name) send({ type: 'lights.rename', light: made.id, name: trimmed })
    select(made.id)
    close()
  }

  const notThisOne = () => {
    if (!made) return
    attempt.current++
    send({ type: 'lights.forget', light: made.id }) // answered in order: the scan below is read after it
    setStage({ at: 'list' }); setFlash('idle'); setName('')
    scan()
  }

  const pairStep = stage.at === 'pair' && pairing && pairing.address === stage.n.address ? pairing.step : null
  const failed = pairStep === 'failed'
  const doneIndex = pairStep === 'done' || pairStep === 'bound' ? 2 : pairStep === 'binding' ? 1 : 0
  const channelOk = channel.trim() !== '' && Number.isInteger(Number(channel)) && Number(channel) >= 0 && Number(channel) <= 255

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="ad-scrim" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onPointerDown={(e) => { if (e.target === e.currentTarget) close() }}>
          <motion.div className="ad-sheet" role="dialog" aria-modal="true" aria-label="Add a light"
            initial={{ y: 14, scale: 0.98 }} animate={{ y: 0, scale: 1 }} exit={{ y: -8 }}>
            <button type="button" className="ad-close" aria-label="Close" onClick={close}><X size={18} /></button>
            <input ref={fileRef} type="file" accept=".json,application/json" hidden
              onChange={(e) => importKeys(e.target.files?.[0], importFor ?? manualAddress)} />

            {stage.at === 'list' && (
              <>
                <header className="ad-head">
                  <div className="ad-head-text">
                    <h2>Add a light</h2>
                    <p role="status">{scanning ? 'Listening for lights nearby...' : `${nearby.length} found nearby`}</p>
                  </div>
                  <Key onClick={scan} disabled={scanning}><RefreshCw size={15} className={scanning ? 'ad-spin' : ''} /> {scanning ? 'Scanning' : 'Scan again'}</Key>
                </header>
                <div className="ad-body">
                  {SECTIONS.map((section) => {
                    const rows = nearby.filter((n) => section.relations.includes(n.relation))
                    if (!rows.length) return null
                    return (
                      <section key={section.title} className="ad-section">
                        <h3>{section.title}</h3>
                        {section.hint && <p className="ad-hint">{section.hint}</p>}
                        <ul className="ad-list">
                          {rows.map((n) => (
                            <li key={n.address} className={`ad-row ad-row--${n.relation}`}>
                              {n.relation === 'new' || n.relation === 'unpaired' || n.relation === 'elsewhere' ? (
                                <button type="button" className="ad-pick" disabled={Boolean(pairing && !['done', 'failed'].includes(pairing.step))}
                                  onClick={() => (n.relation === 'new' ? (setChannel(''), setStage({ at: 'pick', n }))
                                    : n.relation === 'elsewhere' ? setStage({ at: 'reset', n }) : pair(n))}>
                                  <RowBody n={n} />
                                  <span className="ad-act">
                                    {n.relation === 'new' ? <Plus size={14} /> : n.relation === 'elsewhere' ? <RotateCcw size={14} /> : <Link2 size={14} />}
                                    {n.relation === 'new' ? 'Add' : n.relation === 'elsewhere' ? 'Reset and pair' : 'Pair'}
                                  </span>
                                </button>
                              ) : (
                                <div className="ad-pick ad-pick--static">
                                  <RowBody n={n} />
                                  <span className="ad-yours"><Check size={14} /> Yours</span>
                                </div>
                              )}
                            </li>
                          ))}
                        </ul>
                      </section>
                    )
                  })}
                  {!scanning && nearby.length === 0 && (
                    <div className="ad-empty">
                      <p><strong>No lights heard.</strong></p>
                      <p>Switch the light on, keep it within a few metres, and make sure Bluetooth is on for this computer. A light that is connected to a phone right now stays silent until the phone lets go.</p>
                    </div>
                  )}
                </div>
                <footer className="ad-foot">
                  <Key onClick={() => setStage({ at: 'godox' })}><FileKey2 size={14} /> Import from the Godox app</Key>
                  <span className="ad-label">Have a keys file from the CLI or Home Assistant?</span>
                  <div className="ad-manual">
                    <input className="ad-input" value={manualAddress} onChange={(e) => setManualAddress(e.target.value)} placeholder="Light address, AA:BB:CC:DD:EE:FF" aria-label="Light address" />
                    <Key disabled={!/^([0-9a-f]{2}[:-]){5}[0-9a-f]{2}$/i.test(manualAddress.trim())}
                      onClick={() => { setImportFor(null); fileRef.current?.click() }}><FileKey2 size={14} /> Choose file</Key>
                  </div>
                  <details className="ad-help">
                    <summary>Light not listed? How to reset and pair</summary>
                    <p>Zhiyun and Yongnuo lights show up as soon as they are on and no phone app is connected to them. Godox lights show up under Ready to add only after their Bluetooth is reset. Pick the light under Paired with something else to see how to reset it.</p>
                  </details>
                </footer>
              </>
            )}

            {stage.at === 'godox' && (
              <GodoxImport onDone={close} onBack={() => setStage({ at: 'list' })} />
            )}

            {stage.at === 'reset' && (
              <div className="ad-step ad-reset">
                <div className="ad-art"><Glyph n={stage.n} size={96} /></div>
                <h2>Reset and pair the {stage.n.model ?? 'light'}</h2>
                <p className="ad-sub">It is paired with something else. Reset its Bluetooth, then pair it here.</p>
                <ol className="ad-reset-steps" aria-label="Reset steps">
                  {resetSteps(stage.n).map((text) => <li key={text}>{text}</li>)}
                </ol>
                <div className="ad-actions">
                  <Key kind="primary" onClick={() => pair(stage.n)}><Link2 size={15} /> Pair</Key>
                  <Key onClick={() => { setImportFor(stage.n.address); fileRef.current?.click() }}><FileKey2 size={14} /> Import keys</Key>
                  <Key kind="ghost" onClick={() => setStage({ at: 'list' })}>Back to the list</Key>
                </div>
                <p className="ad-hint">Import keys is only for people who have the Godox app.</p>
              </div>
            )}

            {stage.at === 'pick' && (
              <div className="ad-step">
                <div className="ad-art"><Glyph n={stage.n} size={96} /></div>
                <h2>{stage.n.model}</h2>
                <p className="ad-sub">{[stage.n.brand, stage.n.name ?? stage.n.address].join(' · ')}</p>
                {stage.n.needs_channel && (
                  <label className="ad-field">
                    <span className="ad-label">Channel</span>
                    <input className="ad-input" inputMode="numeric" value={channel} onChange={(e) => setChannel(e.target.value.replace(/\D/g, ''))}
                      placeholder="0 to 255" aria-label="Channel" />
                    <span className="ad-hint">The same channel the light is set to. Yongnuo lights only listen to their own.</span>
                  </label>
                )}
                <p className="ad-hint">The light will flash once it is added, so you can tell which one it is.</p>
                <div className="ad-actions">
                  <Key kind="primary" disabled={working || (stage.n.needs_channel === true && !channelOk)} onClick={() => add(stage.n)}><Zap size={15} /> Add and flash it</Key>
                  <Key kind="ghost" onClick={() => setStage({ at: 'list' })}>Back to the list</Key>
                </div>
              </div>
            )}

            {stage.at === 'pair' && (
              <div className="ad-step">
                <div className="ad-art"><Glyph n={stage.n} size={96} /></div>
                <h2>{failed ? 'Pairing stopped' : `Pairing the ${stage.n.model ?? 'light'}`}</h2>
                <p className="ad-sub">{failed ? pairing?.error : 'Keep the light on and close by. This takes about ten seconds.'}</p>
                <ol className="ad-steps">
                  {STEPS.map((s, i) => {
                    const state = i < doneIndex ? 'done' : i === doneIndex && !failed ? 'now' : 'todo'
                    return (
                      <li key={s.id} className={`is-${state}`}>
                        <span className="ad-dot">{state === 'done' ? <Check size={12} strokeWidth={3} /> : i + 1}</span>
                        <span>{state === 'done' ? s.done : s.name}</span>
                      </li>
                    )
                  })}
                </ol>
                {failed && (
                  <div className="ad-actions">
                    <Key kind="primary" onClick={() => pair(stage.n)}><RefreshCw size={15} /> Try again</Key>
                    <Key kind="ghost" onClick={() => setStage({ at: 'list' })}>Back to the list</Key>
                  </div>
                )}
              </div>
            )}

            {stage.at === 'made' && (made ? (
              <div className="ad-step">
                <div className={`ad-art ${flash === 'flashing' ? 'is-flashing' : ''}`}><LightGlyph form={formOf(made.model)} rgb={[1, 0.86, 0.66]} level={1} size={96} /></div>
                <h2>{made.model} added</h2>
                <p className="ad-sub" role="status">
                  {flash === 'flashing' ? 'Flashing it now. Look for the pulse.'
                    : flash === 'done' ? 'It flashed. Is this the light you meant?'
                      : flash === 'failed' ? 'It did not flash. Check it is on and close by.'
                        : 'Added.'}
                </p>
                <label className="ad-field">
                  <span className="ad-label">Name it</span>
                  <input className="ad-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Key light, Fill, Hair..." aria-label="Name" autoFocus
                    onKeyDown={(e) => { if (e.key === 'Enter') finish() }} />
                </label>
                {!made.known_model && (
                  <div className="ad-field">
                    <p className="ad-label">It did not say which model it is. Pick it, so the studio shows the right controls.</p>
                    <ModelPicker onPick={(radio_id) => send({ type: 'lights.model', light: made.id, radio_id })} />
                  </div>
                )}
                <div className="ad-actions">
                  <Key kind="primary" onClick={() => finish()}>Done <ArrowRight size={15} /></Key>
                  <Key onClick={() => void flashIt(made.id, attempt.current)} disabled={flash === 'flashing'}><Zap size={15} /> Flash again</Key>
                  {stage.at === 'made' && stage.added && <Key kind="ghost" onClick={() => notThisOne()}>Not this one</Key>}
                </div>
              </div>
            ) : <p className="ad-sub">Connecting...</p>)}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
