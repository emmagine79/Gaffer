import { useState } from 'react'
import type { Group, SyncProp } from '../lib/types'
import { useStudio } from '../state/store'
import './groups.css'

/** What a group can share; the ids are the service's SYNC_PROPS (service/gaffer/hub.py). */
const PROPS: { id: SyncProp; name: string; hint: string }[] = [
  { id: 'power', name: 'On / off', hint: 'Switch together' },
  { id: 'brightness', name: 'Brightness', hint: 'Same level' },
  { id: 'white', name: 'White', hint: 'Colour temperature and tint' },
  { id: 'colour', name: 'Colour', hint: 'Hue and gels; white-only lights follow as warmth' },
  { id: 'effects', name: 'Effects', hint: 'Animations spread too' },
]

/** The service keeps a group name to 40 characters (Hub.save_group). */
const NAME_MAX = 40

function GroupCard({ group }: { group: Group }) {
  const lights = useStudio((s) => s.lights)
  const groups = useStudio((s) => s.groups)
  const send = useStudio((s) => s.send)
  const [name, setName] = useState(group.name)
  // Work from the newest copy of the group, and show the change at once, so a second quick click
  // builds on the first instead of undoing it. The service's broadcast then replaces the guess.
  const save = (change: (latest: Group) => Partial<Group>) => {
    const { groups: current, selected } = useStudio.getState()
    const latest = current.find((g) => g.id === group.id) ?? group
    const next = { ...latest, ...change(latest) }
    useStudio.setState({ groups: current.map((g) => (g.id === group.id ? next : g)) })
    send({ type: 'group.save', group: next, leader: selected })
  }
  const elsewhere = (id: string) => groups.find((g) => g.id !== group.id && g.members.includes(id))
  const live = group.enabled && group.members.length > 1

  return (
    <article className={`grp ${live ? 'is-live' : ''}`} data-group={group.id}>
      <header className="grp-head">
        <input
          className="grp-name"
          value={name}
          maxLength={NAME_MAX}
          aria-label="Group name"
          onChange={(e) => setName(e.target.value)}
          onBlur={() => {
            const trimmed = name.trim()
            setName(trimmed || group.name) // a blank name goes back to the saved one
            if (trimmed && trimmed !== group.name) save(() => ({ name: trimmed }))
          }}
        />
        <button
          type="button"
          role="switch"
          className={`g-toggle ${group.enabled ? 'on' : ''}`}
          aria-checked={group.enabled}
          aria-label={`Sync ${group.name}`}
          onClick={() => save((g) => ({ enabled: !g.enabled }))}
        />
        <button type="button" className="grp-delete" aria-label={`Delete ${group.name}`} onClick={() => send({ type: 'group.delete', id: group.id })}>
          Delete
        </button>
      </header>

      <p className="grp-label">Lights</p>
      <div className="grp-chips" data-part="members">
        {lights.map((l) => {
          const member = group.members.includes(l.id)
          const other = !member ? elsewhere(l.id) : undefined
          return (
            <button
              key={l.id}
              type="button"
              className={`grp-chip ${member ? 'sel' : ''}`}
              aria-pressed={member}
              title={other ? `In ${other.name}; adding it here takes it out of there` : l.name}
              onClick={() => save((g) => ({ members: g.members.includes(l.id) ? g.members.filter((m) => m !== l.id) : [...g.members, l.id] }))}
            >
              {l.name}
              {other && <small> in {other.name}</small>}
            </button>
          )
        })}
      </div>

      <p className="grp-label">What they share</p>
      <div className="grp-chips" data-part="props">
        {PROPS.map((p) => {
          const on = group.props.includes(p.id)
          return (
            <button
              key={p.id}
              type="button"
              className={`grp-chip ${on ? 'sel' : ''}`}
              aria-pressed={on}
              title={p.hint}
              onClick={() => save((g) => ({ props: g.props.includes(p.id) ? g.props.filter((x) => x !== p.id) : [...g.props, p.id] }))}
            >
              {p.name}
            </button>
          )
        })}
      </div>
      {group.members.length < 2 && <p className="g-dim">Add at least two lights for the group to do anything.</p>}
    </article>
  )
}

/** The first "Group N" no group already uses, so deleting Group 1 never makes a second Group 2. */
function newName(groups: Group[]) {
  const used = new Set(groups.map((g) => g.name))
  let n = 1
  while (used.has(`Group ${n}`)) n++
  return `Group ${n}`
}

const NEW_GROUP_PROPS: SyncProp[] = ['power', 'brightness', 'white', 'colour']

/**
 * The members and name for a new group, or null when it cannot be made. A light follows one group,
 * so a new group takes only lights that are in none: the light on screen if it is free, plus the next free one.
 */
export function planNewGroup(lights: { id: string }[], groups: Group[], selected: string | null) {
  const free = lights.filter((l) => !groups.some((g) => g.members.includes(l.id))).map((l) => l.id)
  if (free.length < 2) return null
  const first = selected && free.includes(selected) ? selected : free[0]
  const second = free.find((id) => id !== first)!
  return { members: [first, second], name: newName(groups) }
}

/** Lights that follow each other: move any one and the rest take the properties the group shares. */
export function Groups() {
  const groups = useStudio((s) => s.groups)
  const lights = useStudio((s) => s.lights)
  const selected = useStudio((s) => s.selected)
  const send = useStudio((s) => s.send)

  const plan = planNewGroup(lights, groups, selected)
  const create = () => {
    if (!plan) return
    send({ type: 'group.save', group: { name: plan.name, members: plan.members, props: NEW_GROUP_PROPS, enabled: true }, leader: selected })
  }

  return (
    <section className="grps" aria-label="Groups">
      <div className="grps-head">
        <h2 className="grps-title">Groups</h2>
        <button type="button" className="g-tab" onClick={create} disabled={!plan}>+ New group</button>
      </div>
      {lights.length >= 2 && !plan && <p className="g-dim">A new group needs two lights that are in no group yet.</p>}
      {groups.length === 0 ? (
        <p className="g-dim">
          {lights.length < 2
            ? 'Add a second light to sync lights together.'
            : 'No groups yet. Make one and its lights follow each other: change one and the rest take the same setting.'}
        </p>
      ) : (
        groups.map((g) => <GroupCard key={`${g.id}:${g.name}`} group={g} />)
      )}
    </section>
  )
}
