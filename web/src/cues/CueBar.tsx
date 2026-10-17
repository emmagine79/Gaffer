import { useStudio } from '../state/store'
import { backCue, goCue, startCue, useCues } from './cues'
import { useLooks } from '../looks/looks'
import './cues.css'

/**
 * The cue's Go button, under Glass and under the desk, drawn only while a cue is active. It says which
 * look the next press applies; at the end of the list it offers to start the cue again instead.
 */
export function CueBar() {
  const active = useStudio((s) => s.cue)
  const cues = useCues()
  const looks = useLooks()
  if (!active) return null
  const steps = cues.find((c) => c.id === active.id)?.steps ?? []
  const next = steps[active.step]
  const nextName = next ? looks.find((l) => l.id === next.look_id)?.name : undefined
  const done = active.step >= active.steps
  return (
    <section className="cue-bar" aria-label={`Cue ${active.name}`} data-step={active.step}>
      <p className="cue-line">
        <span className="cue-name">{active.name}</span>
        <span className="cue-pos" role="status">{done ? 'Finished' : `Step ${active.step} of ${active.steps}`}</span>
      </p>
      <div className="cue-buttons">
        <button type="button" className="cue-back" disabled={active.step <= 1} onClick={backCue}>Back</button>
        {done ? (
          <button type="button" className="cue-go" onClick={() => startCue(active.id)}>Start again</button>
        ) : (
          <button type="button" className="cue-go" onClick={goCue}>
            Go<span className="cue-next">{nextName ? ` ${nextName}` : ''}</span>
          </button>
        )}
      </div>
    </section>
  )
}
