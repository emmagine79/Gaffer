import { ArrowDown, ArrowUp, Download, Pencil, Play, Trash2, Upload } from 'lucide-react'
import { useState } from 'react'
import { Key, Panel, Segmented } from '../components/Controls'
import { emission, rgbCss } from '../lib/color'
import type { LightState, Scene } from '../lib/types'
import { describe } from '../app/describe'
import { EMPTY, useStudio } from '../state/store'
import './tabs.css'

const idle = { kind: null, effect: null, label: '', params: {}, elapsed: 0, duration: null } as const

export function ScenesTab() {
  const scenes = useStudio((s) => (s.store?.scenes ?? EMPTY) as Scene[])
  const caps = useStudio((s) => s.caps)
  const effects = useStudio((s) => s.effects)
  const send = useStudio((s) => s.send)
  const remove = useStudio((s) => s.remove)
  const upsert = useStudio((s) => s.upsert)
  const toast = useStudio((s) => s.toast)
  const [fade, setFade] = useState(0.6)
  const [renaming, setRenaming] = useState<string | null>(null)

  const move = (index: number, delta: number) => {
    const ids = scenes.map((s) => s.id)
    const j = index + delta
    if (j < 0 || j >= ids.length) return
    ;[ids[index], ids[j]] = [ids[j], ids[index]]
    send({ type: 'store.reorder', collection: 'scenes', ids })
  }

  const exportAll = () => {
    const blob = new Blob([JSON.stringify({ lumen: 1, scenes }, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'gaffer-scenes.json'
    a.click()
    URL.revokeObjectURL(a.href)
  }
  const importFile = async (file: File | undefined) => {
    if (!file) return
    try {
      const data = JSON.parse(await file.text()) as { scenes?: Scene[] }
      const list = Array.isArray(data.scenes) ? data.scenes : []
      for (const s of list) await upsert('scenes', { name: s.name, state: s.state, effect: s.effect, params: s.params })
      toast(`Imported ${list.length} scene${list.length === 1 ? '' : 's'}`, 'ok')
    } catch {
      toast('That file is not a Gaffer scenes export', 'error')
    }
  }

  return (
    <div className="scenes">
      <Panel className="scenes-bar">
        <div className="scenes-toolbar">
          <span className="muted">Recall with</span>
          <Segmented size="sm" label="Fade" value={fade} onChange={setFade}
            options={[{ value: 0, label: 'Cut' }, { value: 0.6, label: '0.6s' }, { value: 2, label: '2s' }, { value: 8, label: '8s' }]} />
          <span className="tl-spacer" />
          <Key kind="ghost" onClick={exportAll} disabled={!scenes.length}><Download /> Export</Key>
          <label className="key key--ghost">
            <Upload /> Import
            <input type="file" accept="application/json" className="sr-only" onChange={(e) => void importFile(e.target.files?.[0])} />
          </label>
        </div>
      </Panel>

      {scenes.length === 0 ? (
        <Panel tone="well" className="empty">
          <h3>No scenes yet</h3>
          <p className="muted">Set up a look anywhere in the studio, then use "Save this look" on the Live tab. The first nine scenes get keys 1 to 9.</p>
        </Panel>
      ) : (
        <div className="scene-grid">
          {scenes.map((scene, i) => {
            const state = scene.state as LightState | undefined
            const { rgb, level } = state ? emission(state) : { rgb: [0.6, 0.6, 0.6] as [number, number, number], level: 0.5 }
            const text = state ? describe(state, idle, caps, effects) : { title: scene.effect ?? 'Effect', detail: 'Effect preset' }
            return (
              <article key={scene.id} className="scene-card">
                <button type="button" className="scene-light" onClick={() => send({ type: 'scene.apply', id: scene.id, fade })}
                  style={{ ['--c' as string]: rgbCss(rgb), ['--a' as string]: String(0.25 + level * 0.75) }} aria-label={`Recall ${scene.name}`}>
                  {i < 9 && <span className="scene-key">{i + 1}</span>}
                  <span className="scene-play"><Play size={18} fill="currentColor" /></span>
                </button>
                <div className="scene-meta">
                  {renaming === scene.id ? (
                    <input className="input" autoFocus defaultValue={scene.name} aria-label="Scene name"
                      onBlur={(e) => { const name = e.target.value.trim(); if (name) void upsert('scenes', { ...scene, name }); setRenaming(null) }}
                      onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); if (e.key === 'Escape') setRenaming(null) }} />
                  ) : (
                    <h3>{scene.name}</h3>
                  )}
                  <p className="muted">{text.title}. {text.detail}</p>
                </div>
                <div className="scene-tools">
                  <button type="button" aria-label="Rename" onClick={() => setRenaming(scene.id)}><Pencil size={14} /></button>
                  <button type="button" aria-label="Move earlier" disabled={i === 0} onClick={() => move(i, -1)}><ArrowUp size={14} /></button>
                  <button type="button" aria-label="Move later" disabled={i === scenes.length - 1} onClick={() => move(i, 1)}><ArrowDown size={14} /></button>
                  <button type="button" aria-label="Delete" className="danger" onClick={() => remove('scenes', scene.id)}><Trash2 size={14} /></button>
                </div>
              </article>
            )
          })}
        </div>
      )}
    </div>
  )
}
