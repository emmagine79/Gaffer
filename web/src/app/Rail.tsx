import { Search } from 'lucide-react'
import { useStudio } from '../state/store'
import { LightSwitcher } from './LightSwitcher'
import { TABS, tabAvailable } from './tabs'
import './shell.css'

export function Rail() {
  const tab = useStudio((s) => s.tab)
  const setTab = useStudio((s) => s.setTab)
  const setPalette = useStudio((s) => s.setPalette)
  const caps = useStudio((s) => s.caps)
  const demo = useStudio((s) => s.demo)
  const shown = TABS.filter((t) => tabAvailable(t, caps))
  const groups = [...new Set(shown.map((t) => t.group))]

  return (
    <nav className="rail" aria-label="Sections">
      <div className="rail-brand">
        <span className="rail-mark" aria-hidden="true" />
        <span className="rail-word">Gaffer</span>
        {demo && <span className="rail-demo" title="Simulated lights: started with --demo">Demo</span>}
      </div>

      <LightSwitcher />

      <button type="button" className="rail-search" onClick={() => setPalette(true)}>
        <Search size={15} />
        <span>Find anything</span>
        <kbd>Ctrl K</kbd>
      </button>

      {groups.map((group) => (
        <div key={group} className="rail-group">
          <span className="rail-group-name">{group}</span>
          {shown.filter((t) => t.group === group).map((t) => {
            const Icon = t.icon
            return (
              <button
                key={t.id}
                type="button"
                className={`rail-tab ${tab === t.id ? 'is-on' : ''}`}
                aria-current={tab === t.id ? 'page' : undefined}
                onClick={() => setTab(t.id)}
                title={t.blurb}
              >
                <Icon size={18} strokeWidth={1.9} />
                <span>{t.name}</span>
              </button>
            )
          })}
        </div>
      ))}
    </nav>
  )
}
