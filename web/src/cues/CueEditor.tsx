import { useState } from 'react'
import type { Cue } from '../lib/types'
import { useStudio } from '../state/store'
import { useLooks } from '../looks/looks'
import { startCue, useCues } from './cues'
import './cues.css'

/** The longest cue name, steps and fade the service takes (service/gaffer/cues.py). */
const MAX_NAME = 80
const MAX_STEPS = 200
const MAX_FADE = 60

interface Draft { look_id: string; fade: string }

/**
 * The cue editor in the Gaffer window: name a cue, pick the looks it steps through, give any step a fade
 * of its own (empty keeps the look's), start it, and remove it.
 */
export function CueEditor() {
  const cues = useCues()
  const looks = useLooks()
  const remove = useStudio((s) => s.send)
  return (
    <section className="cues-editor" aria-label="Cues">
      <h2 className="cues-title">Cues</h2>
      {looks.length === 0 && <p className="g-dim">Save some looks first. A cue steps through them in order.</p>}
      {looks.length > 0 && cues.length === 0 && <p className="g-dim">No cues yet. Name one below and add its steps.</p>}
      <ol className="cues-list">
        {cues.map((cue, i) => (
          <li key={`${cue.id}:${cue.updated ?? ''}`}>
            <CueForm cue={cue} label={`cue ${i + 1}`}>
              <button type="button" onClick={() => startCue(cue.id)}>Start</button>
              <button type="button" className="cues-delete" aria-label={`Delete cue ${i + 1}`}
                onClick={() => remove({ type: 'cues.delete', id: cue.id })}>Delete</button>
            </CueForm>
          </li>
        ))}
      </ol>
      {looks.length > 0 && <CueForm cue={null} label="a new cue" />}
    </section>
  )
}

function CueForm({ cue, label, children }: { cue: Cue | null; label: string; children?: React.ReactNode }) {
  const looks = useLooks()
  const request = useStudio((s) => s.request)
  const toast = useStudio((s) => s.toast)
  const [name, setName] = useState(cue?.name ?? '')
  const [steps, setSteps] = useState<Draft[]>(
    () => (cue?.steps ?? []).map((s) => ({ look_id: s.look_id, fade: s.fade_seconds === null ? '' : String(s.fade_seconds) })),
  )
  const [pick, setPick] = useState('')
  const lookName = (id: string) => looks.find((l) => l.id === id)?.name ?? 'A look that was deleted'
  const change = (i: number, patch: Partial<Draft>) => setSteps(steps.map((s, j) => (j === i ? { ...s, ...patch } : s)))
  const save = async () => {
    const body = { id: cue?.id, name, steps: steps.map((s) => ({ look_id: s.look_id, fade_seconds: s.fade.trim() === '' ? null : Number(s.fade) })) }
    try {
      await request({ type: 'cues.save', cue: body })
      if (!cue) { setName(''); setSteps([]) }
    } catch (err) {
      toast((err as Error).message, 'error')
    }
  }
  const add = () => {
    const id = pick || looks[0]?.id
    if (id) setSteps([...steps, { look_id: id, fade: '' }])
  }
  return (
    <div className="cue-edit">
      <input className="cues-input" aria-label={`Name of ${label}`} placeholder="New cue name" value={name} maxLength={MAX_NAME}
        onChange={(e) => setName(e.target.value)} />
      <ol className="cue-steps">
        {steps.map((s, i) => (
          <li key={i} className="cue-step">
            <span className="cue-slot" aria-hidden="true">{i + 1}</span>
            <span className="cue-look" title={lookName(s.look_id)}>{lookName(s.look_id)}</span>
            <input className="cues-input" type="number" min={0} max={MAX_FADE} step={0.1} placeholder="look's" value={s.fade}
              aria-label={`Fade of step ${i + 1} of ${label} in seconds`} onChange={(e) => change(i, { fade: e.target.value })} />
            <button type="button" aria-label={`Remove step ${i + 1} of ${label}`} onClick={() => setSteps(steps.filter((_, j) => j !== i))}>Remove</button>
          </li>
        ))}
      </ol>
      <div className="cues-buttons">
        <select className="cues-input" aria-label={`Look to add to ${label}`} value={pick || looks[0]?.id || ''} onChange={(e) => setPick(e.target.value)}>
          {looks.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </select>
        <button type="button" disabled={steps.length >= MAX_STEPS} onClick={add}>Add step</button>
        <button type="button" disabled={name.trim() === '' || steps.length === 0} onClick={() => void save()}>
          {cue ? 'Save cue' : 'Save as cue'}
        </button>
        {children}
      </div>
    </div>
  )
}
