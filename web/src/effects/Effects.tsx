import type { BuiltinEffect, LightView, ParamSpec, SoftEffect } from '../lib/types'
import { useStudio } from '../state/store'
import { effectFit, usableEffects } from './fit'
import { OWN } from './own'
import './effects.css'

const NOTICE = 'These effects run from the Mac. They stop if the Mac sleeps, and may stutter over Bluetooth.'

const defaultsOf = (params: ParamSpec[]) =>
  Object.fromEntries(params.map((p) => [p.key, p.default])) as Record<string, number>

/**
 * The effects section of Glass. Built-in effects show only when the light's model file lists
 * some (they run inside the light). Gaffer's own effects always show.
 */
export function Effects({ light }: { light: LightView }) {
  const soft = useStudio((s) => s.effects)
  const engine = useStudio((s) => s.engine)
  const state = useStudio((s) => s.state) ?? light.state
  const send = useStudio((s) => s.send)
  const apply = useStudio((s) => s.apply)
  const { caps } = light

  const usable = usableEffects(soft, caps)
  const own = OWN.flatMap((o) => {
    const fx = usable.find((e) => e.id === o.id)
    return fx ? [{ ...o, fx }] : []
  })
  const playing = engine.kind === 'effect' ? engine.effect : null
  const builtinOn = state.mode === 'fx' ? state.fx?.symbol ?? null : null

  const runBuiltin = (e: BuiltinEffect) =>
    apply({ power: true, mode: 'fx', fx: { symbol: e.symbol, speed: e.params.length === 0 && e.speed_max > 0 ? 0 : null, params: defaultsOf(e.params) } })
  const stop = () => {
    if (playing) send({ type: 'engine.stop' })
    else apply({ mode: caps.features.white ? 'cct' : 'hsi' })
  }

  return (
    <section className="g-fx" aria-label="Effects" data-section="effects">
      <div className="g-lab"><span>Effects</span>
        {(playing || builtinOn !== null) && <button type="button" className="g-fx-stop" onClick={stop}>Stop effect</button>}
      </div>

      {caps.effects.length > 0 && (
        <div className="g-fx-group" data-fx-group="builtin" role="group" aria-label="Built into the light">
          <p className="g-fx-title">Built into the light</p>
          <div className="g-fx-chips">
            {caps.effects.map((e) => (
              <button key={e.symbol} type="button" className="g-fx-chip" aria-pressed={builtinOn === e.symbol} onClick={() => runBuiltin(e)}>
                {e.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {own.length > 0 && (
        <div className="g-fx-group" data-fx-group="gaffer" role="group" aria-label="Gaffer's effects">
          <p className="g-fx-title">Gaffer&apos;s effects</p>
          <div className="g-fx-chips">
            {own.map(({ id, label, fx }) => (
              <button key={id} type="button" className="g-fx-chip" aria-pressed={playing === id}
                onClick={() => send({ type: 'engine.start', effect: id, params: {} })}>
                {label}
                <Fit fx={fx} light={light} />
              </button>
            ))}
          </div>
          <p className="g-fx-note" role="note">{NOTICE}</p>
        </div>
      )}
    </section>
  )
}

function Fit({ fx, light }: { fx: SoftEffect; light: LightView }) {
  const fit = effectFit(fx, light.caps)
  return fit ? <small className="g-fx-fit">{fit}</small> : null
}
