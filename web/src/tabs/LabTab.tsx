import { Send, TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { Field, Key, Panel } from '../components/Controls'
import { useStudio } from '../state/store'
import './tabs.css'

const KNOWN = [
  { sub: 'F0', name: 'Brightness, colour temperature, tint' },
  { sub: 'F1', name: 'Hue, saturation, intensity' },
  { sub: 'F2', name: 'RGBW channels, one byte each' },
  { sub: 'F3', name: 'Effect, older generation' },
  { sub: 'F5', name: 'Fan mode' },
  { sub: 'F7', name: 'Effect with parameters (V3)' },
  { sub: 'F9', name: 'Wide RGB channels (V3)' },
  { sub: 'FD', name: 'Status request; end byte picks the record' },
  { sub: 'FE', name: 'Power: 00 on, 01 off' },
]

const RECORDS = ['A0', 'A1', 'A2', 'A3', 'A4', 'A5', 'A6', 'A7', 'A8', 'A9', 'AA']
const RECORD_NOTES: Record<string, string> = {
  A0: 'white: live on the ML100R', A1: 'colour: live on the ML100R', A2: 'RGB: flash default', A3: 'effect: flash default',
  A4: 'gel: flash default', A5: 'empty', A6: 'battery',
}

const hexByte = (s: string) => {
  const n = parseInt(s.replace(/^0x/i, ''), 16)
  return Number.isNaN(n) ? null : n & 0xff
}

export function LabTab() {
  const request = useStudio((s) => s.request)
  const toast = useStudio((s) => s.toast)
  const log = useStudio((s) => s.log)
  const [sub, setSub] = useState('F1')
  const [data, setData] = useState(['32', 'C8', '00', '50', '00'])
  const [end, setEnd] = useState('00')
  const [raw, setRaw] = useState('')
  const [sent, setSent] = useState<string | null>(null)

  const sendFrame = async () => {
    const bytes = data.map(hexByte)
    const s = hexByte(sub)
    const e = hexByte(end)
    if (s === null || e === null || bytes.some((b) => b === null)) {
      toast('Every field needs a hex byte, 00 to FF', 'error')
      return
    }
    try {
      const reply = await request({ type: 'lab.frame', sub: s, data: bytes, end: e }) as { hex?: string }
      setSent(reply.hex ?? null)
    } catch (err) { toast((err as Error).message, 'error') }
  }
  const sendRaw = async () => {
    try {
      const reply = await request({ type: 'raw', hex: raw }) as { hex?: string }
      setSent(reply.hex ?? null)
    } catch (err) { toast((err as Error).message, 'error') }
  }
  const ask = async (record: string) => {
    try { await request({ type: 'lab.record', record: parseInt(record, 16) }) } catch (err) { toast((err as Error).message, 'error') }
  }

  const traffic = log.filter((e) => e.kind === 'rx' || e.kind === 'tx' || e.kind === 'sync').slice(-60).reverse()

  return (
    <div className="lab">
      <Panel tone="well" className="lab-warning">
        <TriangleAlert size={18} />
        <p>Frames here go straight to the light. A wrong sub-command is still a valid command to something: the research behind this app once set an unwanted effect by sweeping unknown ones. Stick to the known list unless you mean it.</p>
      </Panel>

      <div className="lab-grid">
        <Panel title="Build a frame" aside={<span>8 bytes, checksum added for you</span>}>
          <div className="frame-builder">
            <Field label="Command"><input className="input mono-ish" value={sub} maxLength={2} onChange={(e) => setSub(e.target.value)} /></Field>
            {data.map((b, i) => (
              <Field key={i} label={`Byte ${i + 1}`}>
                <input className="input mono-ish" value={b} maxLength={2} onChange={(e) => setData(data.map((x, j) => (j === i ? e.target.value : x)))} />
              </Field>
            ))}
            <Field label="End"><input className="input mono-ish" value={end} maxLength={2} onChange={(e) => setEnd(e.target.value)} /></Field>
          </div>
          <div className="lab-actions">
            <Key kind="primary" onClick={() => void sendFrame()}><Send /> Send frame</Key>
            {sent && <code className="lab-sent">{sent.match(/../g)?.join(' ')}</code>}
          </div>
          <Field label="Or paste a complete frame">
            <div className="lab-raw">
              <input className="input mono-ish" value={raw} onChange={(e) => setRaw(e.target.value)} placeholder="f1 32 c8 00 50 00 00 xx" />
              <Key onClick={() => void sendRaw()} disabled={!raw.trim()}>Send</Key>
            </div>
          </Field>
          <table className="known">
            <tbody>
              {KNOWN.map((k) => (
                <tr key={k.sub} onClick={() => setSub(k.sub)}>
                  <td><code>{k.sub}</code></td><td>{k.name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <div className="stack">
          <Panel title="Status records" aside={<span>Replies appear below</span>}>
            <div className="record-grid">
              {RECORDS.map((r) => (
                <button key={r} type="button" className="record-btn" onClick={() => void ask(r)} title={RECORD_NOTES[r] ?? 'no reply seen so far'}>
                  <strong>{r}</strong>
                  <span>{RECORD_NOTES[r] ?? 'unexplored'}</span>
                </button>
              ))}
            </div>
          </Panel>
          <Panel title="Traffic">
            <ol className="log log--lab">
              {traffic.map((e, i) => (
                <li key={`${e.t}-${i}`} className={`log-${e.kind}`}>
                  <time>{new Date(e.t * 1000).toLocaleTimeString()}</time>
                  <span className="log-kind">{e.kind === 'tx' ? 'sent' : e.kind === 'rx' ? 'heard' : e.kind}</span>
                  <span>{e.text}</span>
                </li>
              ))}
              {traffic.length === 0 && <li className="muted">Send a frame or ask for a record to see traffic here.</li>}
            </ol>
          </Panel>
        </div>
      </div>
    </div>
  )
}
