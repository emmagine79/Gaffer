import { useState } from 'react'
import { useStudio } from '../state/store'
import { applyLook, useLooks } from './looks'
import type { Look } from '../lib/types'
import './looks.css'

/** The longest look name and fade the service takes (service/gaffer/looks.py). */
const MAX_NAME = 80
const MAX_FADE = 60

type Save = (look: Record<string, unknown>) => Promise<boolean>

/** A fade typed in a box as seconds, or null when the box is empty or holds no number (never 0). */
function parseFade(text: string): number | null {
  if (text.trim() === '') return null
  const seconds = Number(text)
  return Number.isFinite(seconds) ? seconds : null
}

const FADE_HINT = `The fade must be a number of seconds from 0 to ${MAX_FADE}.`

function useSave(): Save {
  const request = useStudio((s) => s.request)
  const toast = useStudio((s) => s.toast)
  return async (look) => {
    try {
      await request({ type: 'looks.save', look })
      return true
    } catch (err) {
      toast((err as Error).message, 'error')
      return false
    }
  }
}

/**
 * The look editor in the Gaffer window: name each look, set its fade, save what the lights
 * are doing now into it, and remove it. The list order is the slot order (keys 1 to 9).
 */
export function LookEditor() {
  const looks = useLooks()
  const save = useSave()
  return (
    <section className="looks-editor" aria-label="Looks">
      <h2 className="looks-title">Looks</h2>
      {looks.length === 0 && <p className="g-dim">No looks yet. Set your lights how you want them, name the look below and save it.</p>}
      <ol className="looks-list">
        {looks.map((look, i) => (
          <LookRow key={look.id} look={look} slot={i + 1} save={save} />
        ))}
      </ol>
      <NewLook save={save} />
    </section>
  )
}

function LookRow({ look, slot, save }: { look: Look; slot: number; save: Save }) {
  const remove = useStudio((s) => s.send)
  const toast = useStudio((s) => s.toast)
  // What is typed in a box until it is saved (null: the box shows the saved value). The row is keyed by
  // the look's id alone, so a save, ours or another window's, never remounts it and drops the focus.
  const [typedName, setTypedName] = useState<string | null>(null)
  const [typedFade, setTypedFade] = useState<string | null>(null)
  const name = typedName ?? look.name
  const fade = typedFade ?? String(look.fade_seconds)
  // Save when a box is left, but only if the value changed and makes sense. An empty fade box is not a
  // fade of 0: the saved fade stays.
  const commit = () => {
    let seconds = parseFade(fade)
    if (seconds === null) {
      if (typedFade !== null) toast(FADE_HINT, 'error')
      setTypedFade(null)
      seconds = look.fade_seconds
    }
    if (name.trim() === look.name && seconds === look.fade_seconds) { setTypedName(null); setTypedFade(null); return }
    const sent = { name, fade: typedFade }
    void save({ id: look.id, name, fade_seconds: seconds }).then(() => {
      // Saved or refused, the box shows the saved value again, unless the person has typed more since.
      setTypedName((now) => (now === sent.name ? null : now))
      setTypedFade((now) => (now === sent.fade ? null : now))
    })
  }
  return (
    <li className="looks-row">
      <span className="looks-slot" aria-hidden="true">{slot}</span>
      <input className="looks-input looks-name" aria-label={`Name of look ${slot}`} value={name} maxLength={MAX_NAME}
        onChange={(e) => setTypedName(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()} />
      <label className="looks-fade">
        <input className="looks-input" type="number" min={0} max={MAX_FADE} step={0.1} aria-label={`Fade of look ${slot} in seconds`}
          value={fade} onChange={(e) => setTypedFade(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()} />
        <span>s</span>
      </label>
      <div className="looks-buttons">
        <button type="button" onClick={() => applyLook(look.id)}>Try</button>
        <button type="button" title="Save what the lights are doing now into this look"
          onClick={() => void save({ id: look.id, name: look.name, capture: true })}>Use lights now</button>
        <button type="button" className="looks-delete" aria-label={`Delete look ${slot}`}
          onClick={() => remove({ type: 'looks.delete', id: look.id })}>Delete</button>
      </div>
    </li>
  )
}

function NewLook({ save }: { save: Save }) {
  const defaultFade = useStudio((s) => s.store?.settings.default_fade)
  const [name, setName] = useState('')
  const [fade, setFade] = useState(String(defaultFade ?? 0.6))
  const add = async () => {
    // An empty fade box leaves the fade out, so the service uses the default fade (not 0).
    const seconds = parseFade(fade)
    if (await save(seconds === null ? { name } : { name, fade_seconds: seconds })) setName('')
  }
  return (
    <form className="looks-row looks-new" onSubmit={(e) => { e.preventDefault(); void add() }}>
      <input className="looks-input looks-name" aria-label="Name for a new look" placeholder="New look name" value={name}
        maxLength={MAX_NAME} onChange={(e) => setName(e.target.value)} />
      <label className="looks-fade">
        <input className="looks-input" type="number" min={0} max={MAX_FADE} step={0.1} aria-label="Fade for a new look in seconds"
          value={fade} onChange={(e) => setFade(e.target.value)} />
        <span>s</span>
      </label>
      <div className="looks-buttons">
        <button type="submit" disabled={name.trim() === ''}>Save lights as look</button>
      </div>
    </form>
  )
}
