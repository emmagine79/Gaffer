import { Info, Search, Star } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Panel, Segmented } from '../components/Controls'
import { hexToRgb, inkOn } from '../lib/color'
import type { GelChip } from '../lib/types'
import { EMPTY, useStudio } from '../state/store'
import './tabs.css'

const FAMILY_NAMES: Record<string, string> = {
  'COR.': 'Colour correction',
  'CAL.': 'Calibration',
  'COLOR.': 'Colour',
  'SPC.': 'Special',
  '600': 'Arctic and pastel',
}

function parts(g: GelChip) {
  const tokens = g.label.split(' ')
  return { number: tokens[tokens.length - 1], family: g.family }
}

export function GelsTab() {
  const gels = useStudio((s) => s.gels)
  const state = useStudio((s) => s.state)
  const apply = useStudio((s) => s.apply)
  const send = useStudio((s) => s.send)
  const caps = useStudio((s) => s.caps)
  const favorites = useStudio((s) => s.store?.settings.favorites ?? EMPTY)
  const [query, setQuery] = useState('')
  const [series, setSeries] = useState('all')
  const [family, setFamily] = useState('all')
  const [onlyFav, setOnlyFav] = useState(false)

  const families = useMemo(() => [...new Set(gels.map((g) => g.family).filter(Boolean))].sort(), [gels])
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return gels.filter((g) =>
      (series === 'all' || g.series === series) &&
      (family === 'all' || g.family === family) &&
      (!onlyFav || favorites.includes(g.label)) &&
      (!q || g.label.toLowerCase().includes(q) || g.hex.includes(q)))
  }, [gels, query, series, family, onlyFav, favorites])

  if (!state) return null
  const current = state.mode === 'gel' ? state.gel?.label : null

  const toggleFav = (label: string) => {
    const next = favorites.includes(label) ? favorites.filter((f) => f !== label) : [...favorites, label]
    send({ type: 'settings', patch: { favorites: next } })
  }

  const support = caps?.features.gels ?? null

  return (
    <div className="gels">
      {support === 'emulated' && (
        <div className="adapt-note">
          <Info size={16} />
          <p>
            The <b>{caps?.name}</b> takes no gel commands over Bluetooth, so Lumen recreates each gel from its measured colour:
            correction gels such as CTO, CTB and plus or minus green become the light's own white at the matching temperature
            {caps?.features.tint ? ' and tint' : ''}, and coloured gels become that colour.
          </p>
        </div>
      )}
      {support === 'white' && (
        <div className="adapt-note">
          <Info size={16} />
          <p>
            The <b>{caps?.name}</b> has no colour, so these are the correction gels it can match: each becomes the light's own
            white at the gel's temperature{caps?.features.tint ? ', with its green or magenta on the tint control' : ''}.
            Coloured gels are left out because a white light cannot make them.
          </p>
        </div>
      )}
      <Panel className="gels-bar">
        <div className="gels-filters">
          <label className="gels-search">
            <Search size={16} />
            <input className="input" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Gel number or colour, like 223 or #ffb464" aria-label="Search gels" />
          </label>
          <Segmented size="sm" label="Series" value={series} onChange={setSeries}
            options={[{ value: 'all', label: 'All' }, { value: 'L-GEL', label: 'L-Gel' }, { value: 'R-GEL', label: 'R-Gel' }]} />
          <select className="input gels-family" value={family} onChange={(e) => setFamily(e.target.value)} aria-label="Family">
            <option value="all">Every family</option>
            {families.map((f) => <option key={f} value={f}>{FAMILY_NAMES[f] ? `${FAMILY_NAMES[f]} (${f})` : f}</option>)}
          </select>
          <button type="button" className={`fav-filter ${onlyFav ? 'is-on' : ''}`} onClick={() => setOnlyFav(!onlyFav)} aria-pressed={onlyFav}>
            <Star size={15} fill={onlyFav ? 'currentColor' : 'none'} /> Favourites
          </button>
          <span className="muted gels-count">{shown.length} of {gels.length}</span>
        </div>
      </Panel>

      {shown.length === 0 ? (
        <Panel tone="well"><p className="muted">No gel matches. Clear the search or switch off the favourites filter.</p></Panel>
      ) : (
        <div className="gel-book">
          {shown.map((g) => {
            const { number, family: fam } = parts(g)
            const fav = favorites.includes(g.label)
            return (
              <div key={g.label} className={`gel ${current === g.label ? 'is-on' : ''}`}>
                <button
                  type="button"
                  className="gel-face"
                  onClick={() => apply({ power: true, mode: 'gel', gel: { version: g.version, brand: g.brand, number: g.number, sub_brand: g.sub_brand, label: g.label, hex: g.hex } })}
                  title={`${g.label} (${g.hex})`}
                >
                  <span className="gel-colour" style={{ background: g.hex, color: inkOn(hexToRgb(g.hex)) }}>
                    {current === g.label && <span className="gel-live">On the light</span>}
                  </span>
                  <span className="gel-label">
                    <strong>{number}</strong>
                    <span>{g.series === 'L-GEL' ? 'L' : 'R'} {fam}</span>
                  </span>
                </button>
                <button type="button" className={`gel-star ${fav ? 'is-on' : ''}`} aria-label={fav ? `Unfavourite ${g.label}` : `Favourite ${g.label}`} onClick={() => toggleFav(g.label)}>
                  <Star size={13} fill={fav ? 'currentColor' : 'none'} />
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
