import { AnimatePresence, motion } from 'motion/react'
import { Check, LifeBuoy, Plus, RefreshCw, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Key } from '../components/Controls'
import { useStudio } from '../state/store'
import { LightRender } from '../visuals/LightRender'
import { SignalBars } from './MasterBar'
import './shell.css'

const STEPS = [
  { id: 'scanning', name: 'Look for your lights', done: 'Found one' },
  { id: 'connecting', name: 'Open a Bluetooth link', done: 'Linked' },
  { id: 'connected', name: 'Join its mesh network', done: 'Ready' },
] as const

function stepIndex(status: string | undefined) {
  if (status === 'connected') return 3
  if (status === 'connecting') return 1
  return 0
}

function since(ts: number | null) {
  if (!ts) return ''
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)} min`
  return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`
}

/**
 * Full-screen while the light is not connected on first load; afterwards a
 * sheet opened from the master bar. Dismissable: everything except sending
 * works without the light (scenes, timelines, settings).
 */
export function ConnectionScreen() {
  const link = useStudio((s) => s.link)
  const socketOpen = useStudio((s) => s.socketOpen)
  const ready = useStudio((s) => s.ready)
  const sheet = useStudio((s) => s.connectionSheet)
  const setSheet = useStudio((s) => s.setConnectionSheet)
  const send = useStudio((s) => s.send)
  const light = useStudio((s) => s.light)
  const setAddLight = useStudio((s) => s.setAddLight)
  const setTab = useStudio((s) => s.setTab)
  const [dismissed, setDismissed] = useState(false)
  const [celebrate, setCelebrate] = useState(false)

  const connected = socketOpen && link?.status === 'connected'
  useEffect(() => {
    if (!connected || dismissed) return
    setCelebrate(true)
    const t = window.setTimeout(() => setDismissed(true), 1100)
    return () => window.clearTimeout(t)
  }, [connected, dismissed])

  const blocking = !dismissed && (!connected || celebrate)
  const open = sheet || blocking
  const step = stepIndex(link?.status)

  const noLight = socketOpen && ready && link?.status === 'no-light'
  let headline = 'Finding your lights'
  let body = 'Make sure they are switched on and within a few metres of this computer.'
  if (noLight) {
    headline = 'Welcome to Gaffer'
    body = 'Add your first Godox light: pair one that is factory fresh or reset, or bring in one you paired with another tool.'
  } else if (!socketOpen) {
    headline = 'The studio is not running'
    body = 'Open Gaffer from the menu bar, then this page reconnects by itself.'
  } else if (!ready) {
    headline = 'Opening the studio'
    body = ''
  } else if (connected) {
    headline = sheet && !celebrate ? `${light?.name ?? 'Your light'} is connected` : 'Connected'
    body = sheet ? `Linked for ${since(link?.connected_since ?? null)}.` : ''
  } else if (link?.status === 'backoff') {
    headline = 'Still looking'
    body = link.detail
  } else if (link?.status === 'connecting') {
    headline = 'Connecting'
    body = 'Opening the link and joining the light’s mesh network.'
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className={`conn ${sheet ? 'conn--sheet' : ''}`}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0, transition: { duration: 0.45 } }}
          role="dialog"
          aria-modal="true"
          aria-label="Connection"
        >
          <motion.div className="conn-card" initial={{ y: 18, scale: 0.98 }} animate={{ y: 0, scale: 1 }} exit={{ y: -10 }}>
            {(sheet || connected) && (
              <button type="button" className="conn-close" aria-label="Close" onClick={() => { setSheet(false); setDismissed(true); setCelebrate(false) }}>
                <X size={18} />
              </button>
            )}
            <div className={`conn-visual ${connected ? 'is-connected' : ''}`}>
              <div className="conn-rings" aria-hidden="true"><i /><i /><i /></div>
              <LightRender size={170} light={connected ? undefined : { rgb: [0.7, 0.72, 0.78], level: 0.08 }} />
            </div>

            <h2 className="conn-title">{headline}</h2>
            {body && <p className="conn-body muted">{body}</p>}

            {socketOpen && ready && !noLight && (
              <ol className="conn-steps">
                {STEPS.map((s, i) => {
                  const state = i < step ? 'done' : i === step && !connected ? 'now' : 'todo'
                  return (
                    <li key={s.id} className={`is-${state}`}>
                      <span className="conn-step-dot">{state === 'done' ? <Check size={13} strokeWidth={3} /> : i + 1}</span>
                      <span>{state === 'done' ? s.done : s.name}</span>
                      {s.id === 'scanning' && link?.rssi != null && i < step && (
                        <span className="conn-step-extra"><SignalBars rssi={link.rssi} /> {link.rssi} dBm</span>
                      )}
                    </li>
                  )
                })}
              </ol>
            )}

            {link && socketOpen && !noLight && (
              <dl className="conn-facts">
                <div><dt>Address</dt><dd>{link.address}</dd></div>
                {link.latency_ms != null && <div><dt>Round trip</dt><dd>{Math.round(link.latency_ms)} ms</dd></div>}
                {link.interval_ms != null && <div><dt>Radio interval</dt><dd>{link.interval_ms} ms</dd></div>}
                {link.firmware?.mcu && <div><dt>Firmware</dt><dd>MCU {link.firmware.mcu}, mesh {link.firmware.mesh}</dd></div>}
              </dl>
            )}

            <div className="conn-actions">
              {noLight && (
                <>
                  <Key kind="primary" onClick={() => { setDismissed(true); setSheet(false); setAddLight(true) }}><Plus /> Add a light</Key>
                  <Key onClick={() => { setDismissed(true); setSheet(false); setTab('guide') }}><LifeBuoy /> How pairing works</Key>
                </>
              )}
              {socketOpen && !connected && !noLight && (
                <Key kind="primary" onClick={() => send({ type: 'link.reconnect' })}>
                  <RefreshCw /> Try again now
                </Key>
              )}
              {socketOpen && connected && sheet && (
                <Key onClick={() => send({ type: 'link.reconnect' })}><RefreshCw /> Reconnect</Key>
              )}
              {!connected && (
                <Key kind="ghost" onClick={() => { setDismissed(true); setSheet(false) }}>
                  {noLight ? 'Look around first' : 'Continue without the light'}
                </Key>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
