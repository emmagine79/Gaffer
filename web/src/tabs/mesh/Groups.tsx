import { Link2, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Key, Panel, Toggle } from '../../components/Controls'
import type { Group, SyncProp } from '../../lib/types'
import { useStudio } from '../../state/store'
import { LightBadge } from '../../app/LightSwitcher'

const PROPS: { id: SyncProp; name: string; hint: string }[] = [
  { id: 'power', name: 'On / off', hint: 'Switch together' },
  { id: 'brightness', name: 'Brightness', hint: 'Same level' },
  { id: 'white', name: 'White', hint: 'Colour temperature and tint' },
  { id: 'colour', name: 'Colour', hint: 'Hue, gels; white-only lights follow as warmth' },
  { id: 'effects', name: 'Effects', hint: 'Animations, music and screen sync spread too' },
]

function GroupCard({ group }: { group: Group }) {
  const lights = useStudio((s) => s.lights)
  const groups = useStudio((s) => s.groups)
  const send = useStudio((s) => s.send)
  const [name, setName] = useState(group.name)
  // Build on the newest copy, not this render's, so two quick clicks both count.
  const save = (patch: Partial<Group>) => {
    const latest = useStudio.getState().groups.find((g) => g.id === group.id) ?? group
    send({ type: 'group.save', group: { ...latest, ...patch }, leader: useStudio.getState().selected })
  }
  const elsewhere = (id: string) => groups.find((g) => g.id !== group.id && g.members.includes(id))

  return (
    <article className={`group-card ${group.enabled && group.members.length > 1 ? 'is-live' : ''}`}>
      <header className="group-head">
        <Link2 size={16} className="group-icon" />
        <input className="group-name" value={name} onChange={(e) => setName(e.target.value)} aria-label="Group name"
          onBlur={() => name.trim() && name !== group.name && save({ name })} />
        <Toggle label={`Sync ${group.name}`} on={group.enabled} onChange={(enabled) => save({ enabled })} />
        <button type="button" className="group-delete" aria-label={`Delete ${group.name}`} onClick={() => send({ type: 'group.delete', id: group.id })}>
          <Trash2 size={15} />
        </button>
      </header>

      <p className="group-label">Lights</p>
      <div className="group-members">
        {lights.map((l) => {
          const member = group.members.includes(l.id)
          const other = !member ? elsewhere(l.id) : undefined
          return (
            <button key={l.id} type="button" className={`member-chip ${member ? 'is-on' : ''}`} aria-pressed={member}
              title={other ? `In ${other.name}; adding it here takes it out of there` : undefined}
              onClick={() => save({ members: member ? group.members.filter((m) => m !== l.id) : [...group.members, l.id] })}>
              <LightBadge light={l} size={22} />
              <span>{l.name}</span>
              {other && <small>in {other.name}</small>}
            </button>
          )
        })}
      </div>

      <p className="group-label">What they share</p>
      <div className="group-props">
        {PROPS.map((p) => {
          const on = group.props.includes(p.id)
          return (
            <button key={p.id} type="button" className={`prop-chip ${on ? 'is-on' : ''}`} aria-pressed={on} title={p.hint}
              onClick={() => save({ props: on ? group.props.filter((x) => x !== p.id) : [...group.props, p.id] })}>
              {p.name}
            </button>
          )
        })}
      </div>
      {group.members.length < 2 && <p className="hint">Add at least two lights for the group to do anything.</p>}
    </article>
  )
}

/** Lights that follow each other: change any one and the rest take the chosen properties. */
export function Groups() {
  const groups = useStudio((s) => s.groups)
  const lights = useStudio((s) => s.lights)
  const selected = useStudio((s) => s.selected)
  const send = useStudio((s) => s.send)

  const create = () => {
    const free = lights.filter((l) => !groups.some((g) => g.members.includes(l.id))).map((l) => l.id)
    const members = free.length >= 2 ? free : selected ? [selected] : []
    send({ type: 'group.save', group: { name: groups.length ? `Group ${groups.length + 1}` : 'All lights', members, props: ['power', 'brightness', 'white', 'colour'], enabled: true } })
  }

  return (
    <Panel title="Sync groups" aside={<Key onClick={create} disabled={lights.length < 2}><Plus /> New group</Key>} className="groups">
      <p className="hint groups-intro">
        Lights in a group follow each other: change any one of them, from any tab, and the others take the properties you
        pick, each in its own way. A light follows one group at a time.
      </p>
      {groups.length === 0 ? (
        <div className="groups-empty">
          <p>{lights.length < 2 ? 'Add a second light to sync lights together.' : 'No groups yet. Make one to link lights, for example a key and fill that always match.'}</p>
        </div>
      ) : (
        <div className="group-list">{groups.map((g) => <GroupCard key={`${g.id}:${g.name}`} group={g} />)}</div>
      )}
    </Panel>
  )
}
