import { AnimatePresence, motion } from 'motion/react'
import { Pencil, Plus, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { Key, Panel } from '../../components/Controls'
import { ModelPicker } from '../../components/ModelPicker'
import type { LightView } from '../../lib/types'
import { useStudio } from '../../state/store'
import { LightBadge, statusOf } from '../../app/LightSwitcher'
import { KIND_SHORT } from '../../visuals/LightGlyph'

const SOURCE: Record<LightView['model_source'], string> = {
  advert: 'recognised',
  manual: 'set by you',
  unknown: 'not recognised',
}

/** Change a light's model when it did not say, or said wrong. */
export function ModelDialog({ light, onClose }: { light: LightView; onClose: () => void }) {
  const send = useStudio((s) => s.send)
  return (
    <motion.div className="conn conn--sheet" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      role="dialog" aria-modal="true" aria-label={`Model of ${light.name}`} onPointerDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <motion.div className="addlight model-dialog" initial={{ y: 14 }} animate={{ y: 0 }}>
        <button type="button" className="conn-close" aria-label="Close" onClick={onClose}><X size={18} /></button>
        <h2 className="addlight-title">Which model is {light.name}?</h2>
        <p className="muted model-dialog-sub">
          {light.known_model ? `It reports itself as ${light.model}. ` : 'It did not say. '}
          The studio shows the controls that model has: its temperature range, colour, gels, effects, fan and battery.
        </p>
        <ModelPicker value={light.radio_id} onPick={(radio_id) => { send({ type: 'lights.model', light: light.id, radio_id }); onClose() }} />
      </motion.div>
    </motion.div>
  )
}

function Row({ light, onModel }: { light: LightView; onModel: () => void }) {
  const linkUp = useStudio((s) => s.link?.status === 'connected')
  const send = useStudio((s) => s.send)
  const select = useStudio((s) => s.select)
  const setTab = useStudio((s) => s.setTab)
  const [name, setName] = useState(light.name)
  const [confirm, setConfirm] = useState(false)
  const status = statusOf(light, linkUp)

  return (
    <tr>
      <td><LightBadge light={light} size={32} /></td>
      <td>
        <label className="lt-name">
          <input className="lt-input" value={name} onChange={(e) => setName(e.target.value)} aria-label={`Name of ${light.name}`}
            onBlur={() => name.trim() && name !== light.name && send({ type: 'lights.rename', light: light.id, name })}
            onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
          <Pencil size={12} />
        </label>
      </td>
      <td>
        <button type="button" className="lt-model" onClick={onModel} title="Change the model">
          <strong>{light.model}</strong>
          <small className={light.model_source === 'unknown' || !light.known_model ? 'is-warn' : ''}>{light.known_model ? `${KIND_SHORT[light.kind]} · ${SOURCE[light.model_source]}` : 'Pick its model'}</small>
        </button>
      </td>
      <td className="lt-dim"><code>{light.address}</code><small>node 0x{light.node_address.toString(16).padStart(4, '0')}</small></td>
      <td><span className="lt-status"><i className={`dot dot--${status.tone}`} />{status.text}</span></td>
      <td className="lt-actions">
        {confirm ? (
          <span className="lt-confirm">
            <span>Forget it?</span>
            <Key kind="danger" onClick={() => send({ type: 'lights.forget', light: light.id })}>Forget</Key>
            <Key kind="ghost" onClick={() => setConfirm(false)}>Keep</Key>
          </span>
        ) : (
          <>
            <Key kind="ghost" onClick={() => { select(light.id); setTab('live') }}>Control</Key>
            <button type="button" className="lt-forget" aria-label={`Forget ${light.name}`} onClick={() => setConfirm(true)}
              title="Remove it from the studio. The light keeps its pairing until you reset it."><Trash2 size={15} /></button>
          </>
        )}
      </td>
    </tr>
  )
}

export function LightsTable() {
  const lights = useStudio((s) => s.lights)
  const setAddLight = useStudio((s) => s.setAddLight)
  const [modelFor, setModelFor] = useState<LightView | null>(null)

  return (
    <Panel title={`Your lights (${lights.length})`} aside={<Key onClick={() => setAddLight(true)}><Plus /> Add a light</Key>} className="lights-table">
      {lights.length === 0 ? (
        <p className="muted">No lights yet.</p>
      ) : (
        <div className="lt-scroll">
          <table className="lt">
            <thead><tr><th /><th>Name</th><th>Model</th><th>Address</th><th>Status</th><th /></tr></thead>
            <tbody>{lights.map((l) => <Row key={`${l.id}:${l.name}`} light={l} onModel={() => setModelFor(l)} />)}</tbody>
          </table>
        </div>
      )}
      <p className="hint">Forgetting a light only removes it from this studio. To pair it with something else later, reset it from its own menu.</p>
      <AnimatePresence>{modelFor && <ModelDialog light={lights.find((l) => l.id === modelFor.id) ?? modelFor} onClose={() => setModelFor(null)} />}</AnimatePresence>
    </Panel>
  )
}
