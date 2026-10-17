import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { LightKind } from '../lib/types'
import { useStudio } from '../state/store'
import { KIND_SHORT, LightGlyph, formOf } from '../visuals/LightGlyph'
import './picker.css'

const KIND_ORDER: LightKind[] = ['rgb', 'bicolour', 'daylight', 'colour', 'unsupported']
const KIND_LOOK: Record<LightKind, [number, number, number]> = {
  rgb: [0.62, 0.42, 1], bicolour: [1, 0.78, 0.52], daylight: [0.93, 0.95, 1], colour: [0.3, 0.85, 0.9], unsupported: [0.5, 0.5, 0.5],
}

/** Every model in the catalogue, searchable: for a light that did not say what it is. */
export function ModelPicker({ value, onPick }: { value?: string; onPick: (radioId: string) => void }) {
  const models = useStudio((s) => s.models)
  const [query, setQuery] = useState('')
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase()
    const hits = models.filter((m) => !q || m.name.toLowerCase().includes(q) || m.radio_id.toLowerCase() === q)
    return KIND_ORDER.map((kind) => ({ kind, rows: hits.filter((m) => m.kind === kind) })).filter((g) => g.rows.length)
  }, [models, query])

  return (
    <div className="picker">
      <label className="picker-search">
        <Search size={15} />
        <input className="input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Model name, like SL60 or TL60" aria-label="Search models" autoFocus />
      </label>
      <div className="picker-list" role="listbox" aria-label="Models">
        {groups.map((g) => (
          <div key={g.kind} className="picker-group">
            <p className="picker-group-name">{KIND_SHORT[g.kind]} <span>{g.rows.length}</span></p>
            <div className="picker-grid">
              {g.rows.map((m) => (
                <button key={m.radio_id} type="button" role="option" aria-selected={m.radio_id === value}
                  className={`picker-model ${m.radio_id === value ? 'is-on' : ''}`} onClick={() => onPick(m.radio_id)}
                  disabled={m.kind === 'unsupported'} title={m.kind === 'unsupported' ? 'The studio cannot drive this model' : m.kind_label}>
                  <LightGlyph form={formOf(m.name)} rgb={KIND_LOOK[m.kind]} level={0.6} size={26} />
                  <span>{m.name}</span>
                </button>
              ))}
            </div>
          </div>
        ))}
        {groups.length === 0 && <p className="muted picker-empty">No model matches “{query}”.</p>}
      </div>
    </div>
  )
}
