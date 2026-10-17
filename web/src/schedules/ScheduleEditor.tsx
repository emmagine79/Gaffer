import { useState } from 'react'
import { useLooks } from '../looks/looks'
import type { Schedule } from '../lib/types'
import { EMPTY, useStudio } from '../state/store'
import '../looks/looks.css'
import './schedules.css'

/** The longest schedule name the service takes (service/gaffer/looks.py MAX_NAME, used by schedules.py). */
const MAX_NAME = 80
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function describeDays(days: number[]): string {
  return days.length === 7 ? 'every day' : days.map((d) => DAYS[d]).join(' ')
}

/**
 * The schedule editor in the Gaffer window: pick a time, the days and what happens (a look, or
 * everything off), and see the saved schedules. They run while the Mac is awake and Gaffer is open.
 */
export function ScheduleEditor() {
  const schedules = useStudio((s) => (s.store?.schedules ?? EMPTY) as Schedule[])
  const looks = useLooks()
  const request = useStudio((s) => s.request)
  const send = useStudio((s) => s.send)
  const toast = useStudio((s) => s.toast)
  const [name, setName] = useState('')
  const [at, setAt] = useState('22:00')
  const [days, setDays] = useState<number[]>([0, 1, 2, 3, 4])
  const [action, setAction] = useState<'look' | 'off'>('look')
  const [target, setTarget] = useState('')

  const save = async (schedule: Record<string, unknown>) => {
    try {
      await request({ type: 'schedules.save', schedule })
      return true
    } catch (err) {
      toast((err as Error).message, 'error')
      return false
    }
  }
  const chosenLook = target || looks[0]?.id || ''
  const canAdd = name.trim() !== '' && days.length > 0 && (action === 'off' || chosenLook !== '')
  const add = async () => {
    const ok = await save({ name, at, days, action, ...(action === 'look' ? { target: chosenLook } : {}) })
    if (ok) setName('')
  }
  const toggleDay = (d: number) => setDays((now) => (now.includes(d) ? now.filter((x) => x !== d) : [...now, d].sort()))

  return (
    <section className="looks-editor sched-editor" aria-label="Schedules">
      <h2 className="looks-title">Schedules</h2>
      {schedules.length === 0 && <p className="g-dim">Nothing scheduled. Schedules run while Gaffer is open and the Mac is awake.</p>}
      <ul className="sched-list">
        {schedules.map((s) => (
          <li key={s.id} className={`sched-row ${s.enabled ? '' : 'is-off'}`}>
            <span className="sched-time">{s.at}</span>
            <div className="sched-info">
              <strong className="sched-name">{s.name}</strong>
              <span className="g-dim sched-what">
                {s.action === 'off' ? 'All off' : `Look: ${looks.find((l) => l.id === s.target)?.name ?? 'missing look'}`}
                {', '}{describeDays(s.days)}
              </span>
            </div>
            <div className="looks-buttons">
              <button type="button" aria-pressed={s.enabled} aria-label={`${s.name} on or off`}
                onClick={() => void save({ ...s, enabled: !s.enabled })}>{s.enabled ? 'On' : 'Paused'}</button>
              <button type="button" className="looks-delete" aria-label={`Delete schedule ${s.name}`}
                onClick={() => send({ type: 'schedules.delete', id: s.id })}>Delete</button>
            </div>
          </li>
        ))}
      </ul>
      <form className="sched-new" onSubmit={(e) => { e.preventDefault(); void add() }}>
        <input className="looks-input" aria-label="Name for a new schedule" placeholder="New schedule name" value={name}
          maxLength={MAX_NAME} onChange={(e) => setName(e.target.value)} />
        <input className="looks-input" type="time" aria-label="Time" value={at} onChange={(e) => setAt(e.target.value)} />
        <select className="looks-input" aria-label="What happens" value={action} onChange={(e) => setAction(e.target.value as 'look' | 'off')}>
          <option value="look">Apply a look</option>
          <option value="off">Turn everything off</option>
        </select>
        {action === 'look' && (
          <select className="looks-input" aria-label="Look to apply" value={chosenLook} onChange={(e) => setTarget(e.target.value)}>
            {looks.length === 0 && <option value="">No looks saved yet</option>}
            {looks.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
        )}
        <div className="sched-days" role="group" aria-label="Days">
          {DAYS.map((d, i) => (
            <button key={d} type="button" className={days.includes(i) ? 'is-on' : ''} aria-pressed={days.includes(i)}
              onClick={() => toggleDay(i)}>{d}</button>
          ))}
        </div>
        <div className="looks-buttons">
          <button type="submit" disabled={!canAdd}>Add schedule</button>
        </div>
      </form>
    </section>
  )
}
