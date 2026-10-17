import { Plus, Power, PowerOff } from 'lucide-react'
import { Key } from '../components/Controls'
import { useStudio } from '../state/store'
import { FloorPlan } from './mesh/FloorPlan'
import { Groups } from './mesh/Groups'
import { Inspector } from './mesh/Inspector'
import { LightsTable } from './mesh/LightsTable'
import './mesh/mesh.css'
import './tabs.css'

export function MeshTab() {
  const lights = useStudio((s) => s.lights)
  const light = useStudio((s) => s.light)
  const groups = useStudio((s) => s.groups)
  const link = useStudio((s) => s.link)
  const send = useStudio((s) => s.send)
  const setAddLight = useStudio((s) => s.setAddLight)
  const gatewayName = lights.find((l) => l.id === link?.gateway)?.name
  const online = lights.filter((l) => l.online)
  const lit = online.filter((l) => l.state.power).length

  if (lights.length === 0) {
    return (
      <div className="mesh-empty">
        <div className="mesh-empty-art" aria-hidden="true"><i /><i /><i /></div>
        <h2>No lights yet</h2>
        <p className="muted">Pair a light that is factory fresh or reset, or bring in one you paired with another tool by importing its keys.</p>
        <Key kind="primary" onClick={() => setAddLight(true)}><Plus /> Add your first light</Key>
      </div>
    )
  }

  return (
    <div className="mesh">
      <div className="mesh-bar">
        <p className="mesh-summary">
          <strong>{lit} of {online.length}</strong> on
          {link?.status === 'connected' && gatewayName ? <span className="muted"> · linked through {gatewayName}{online.length > 1 ? ', the rest by relay' : ''}</span> : <span className="muted"> · {link?.status === 'connected' ? 'connected' : 'not connected'}</span>}
        </p>
        <div className="mesh-bar-actions">
          <Key onClick={() => send({ type: 'power.all', on: true, fade: 0.6 })}><Power /> All on</Key>
          <Key onClick={() => send({ type: 'power.all', on: false, fade: 0.6 })}><PowerOff /> All off</Key>
          <Key kind="primary" onClick={() => setAddLight(true)}><Plus /> Add a light</Key>
        </div>
      </div>

      <div className="mesh-main">
        <FloorPlan groups={groups} />
        <Inspector light={light} />
      </div>

      <div className="mesh-lower">
        <Groups />
        <LightsTable />
      </div>
    </div>
  )
}
