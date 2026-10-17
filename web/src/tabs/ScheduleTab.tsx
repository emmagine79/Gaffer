import { Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Field, Key, Panel, Segmented, Toggle } from '../components/Controls'
import type { Schedule } from '../lib/types'
import { EMPTY, useStudio } from '../state/store'
import './tabs.css'

type ScheduleDraft = {
  name: string
  enabled: boolean
  at: string
  days: number[]
  action: Schedule['action']
  target?: string
  minutes?: number
}

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const ACTIONS: { value: Schedule['action']; label: string }[] = [
  { value: 'sunrise', label: 'Sunrise' }, { value: 'scene', label: 'Scene' }, { value: 'effect', label: 'Effect' },
  { value: 'on', label: 'Switch on' }, { value: 'off', label: 'Switch off' },
]

function nextRun(s: Schedule): string {
  const [h, m] = s.at.split(':').map(Number)
  const now = new Date()
  for (let add = 0; add < 8; add++) {
    const d = new Date(now)
    d.setDate(now.getDate() + add)
    d.setHours(h, m, 0, 0)
    const weekday = (d.getDay() + 6) % 7
    if (d > now && (s.days.length === 0 || s.days.includes(weekday))) {
      const mins = Math.round((d.getTime() - now.getTime()) / 60000)
      if (mins < 60) return `in ${mins} min`
      if (mins < 24 * 60) return `in ${Math.floor(mins / 60)} h ${mins % 60} min`
      return d.toLocaleDateString([], { weekday: 'long' }) + ` at ${s.at}`
    }
  }
  return 'never'
}

export function ScheduleTab() {
  const schedules = useStudio((s) => (s.store?.schedules ?? EMPTY) as Schedule[])
  const scenes = useStudio((s) => s.store?.scenes ?? EMPTY)
  const effects = useStudio((s) => s.effects)
  const upsert = useStudio((s) => s.upsert)
  const remove = useStudio((s) => s.remove)
  const [draft, setDraft] = useState<ScheduleDraft>({
    name: 'Wake up', enabled: true, at: '07:00', days: [0, 1, 2, 3, 4], action: 'sunrise', minutes: 20,
  })

  const save = (s: ScheduleDraft & { id?: string }) => void upsert('schedules', s)
  const toggleDay = (days: number[], d: number) => (days.includes(d) ? days.filter((x) => x !== d) : [...days, d].sort())

  return (
    <div className="schedule">
      <Panel title="New schedule">
        <div className="sched-form">
          <Field label="Name"><input className="input" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></Field>
          <Field label="Time"><input className="input" type="time" value={draft.at} onChange={(e) => setDraft({ ...draft, at: e.target.value })} /></Field>
          <Field label="Do this">
            <Segmented size="sm" label="Action" value={draft.action} onChange={(action) => setDraft({ ...draft, action })} options={ACTIONS} />
          </Field>
          {draft.action === 'sunrise' && (
            <Field label="Sunrise length" hint="Starts at the set time and brightens over this long">
              <input className="input" type="number" min={1} max={90} value={draft.minutes ?? 20} onChange={(e) => setDraft({ ...draft, minutes: Number(e.target.value) })} />
            </Field>
          )}
          {draft.action === 'scene' && (
            <Field label="Scene">
              <select className="input" value={draft.target ?? ''} onChange={(e) => setDraft({ ...draft, target: e.target.value })}>
                <option value="">Choose a scene</option>
                {scenes.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </Field>
          )}
          {draft.action === 'effect' && (
            <Field label="Effect">
              <select className="input" value={draft.target ?? ''} onChange={(e) => setDraft({ ...draft, target: e.target.value })}>
                <option value="">Choose an effect</option>
                {effects.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
              </select>
            </Field>
          )}
          <Field label="Days">
            <div className="day-pills">
              {DAYS.map((d, i) => (
                <button key={d} type="button" className={draft.days.includes(i) ? 'is-on' : ''} aria-pressed={draft.days.includes(i)}
                  onClick={() => setDraft({ ...draft, days: toggleDay(draft.days, i) })}>{d}</button>
              ))}
            </div>
          </Field>
          <Key kind="primary" disabled={!draft.name.trim() || ((draft.action === 'scene' || draft.action === 'effect') && !draft.target)}
            onClick={() => save(draft)}><Plus /> Add schedule</Key>
        </div>
      </Panel>

      {schedules.length === 0 ? (
        <Panel tone="well"><p className="muted">Nothing scheduled. Schedules run while the studio is running on this computer.</p></Panel>
      ) : (
        <div className="sched-list">
          {schedules.map((s) => (
            <Panel key={s.id} className={`sched ${s.enabled ? '' : 'is-off'}`}>
              <div className="sched-row">
                <p className="readout sched-time">{s.at}</p>
                <div className="sched-info">
                  <h3>{s.name}</h3>
                  <p className="muted">
                    {ACTIONS.find((a) => a.value === s.action)?.label}
                    {s.action === 'sunrise' && ` over ${s.minutes} min`}
                    {s.action === 'scene' && `: ${scenes.find((x) => x.id === s.target)?.name ?? 'missing scene'}`}
                    {s.action === 'effect' && `: ${effects.find((x) => x.id === s.target)?.name ?? s.target}`}
                    {', '}{s.days.length === 7 || s.days.length === 0 ? 'every day' : s.days.map((d) => DAYS[d]).join(' ')}
                  </p>
                  <p className="sched-next">{s.enabled ? `Next ${nextRun(s)}` : 'Paused'}</p>
                </div>
                <Toggle label={`${s.name} enabled`} on={s.enabled} onChange={(enabled) => save({ ...s, enabled })} />
                <Key kind="ghost" onClick={() => remove('schedules', s.id)} title="Delete"><Trash2 /></Key>
              </div>
            </Panel>
          ))}
        </div>
      )}
    </div>
  )
}
