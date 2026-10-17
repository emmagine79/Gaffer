import { useStudio } from '../state/store'
import { backCue, goCue, startCue } from './cues'
import './cues.css'

/**
 * The cue's Go button, under Glass and under the desk, drawn only while a cue is active. It names the look
 * the next press applies, as the service worked it out (steps whose look is gone are passed over there);
 * at the end of the list it offers to start the cue again instead.
 */
export function CueBar() {
  const active = useStudio((s) => s.cue)
  if (!active) return null
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
            Go<span className="cue-next">{active.next ? ` ${active.next.name}` : ''}</span>
          </button>
        )}
      </div>
    </section>
  )
}
