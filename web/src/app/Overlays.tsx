import { AnimatePresence, motion } from 'motion/react'
import { CornerDownLeft, Search } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { hexToRgb, kelvinToRgb, rgbCss } from '../lib/color'
import { EMPTY, useStudio, type TabId } from '../state/store'
import { TABS, tabAvailable } from './tabs'
import './shell.css'

export function Toasts() {
  const toasts = useStudio((s) => s.toasts)
  const dismiss = useStudio((s) => s.dismissToast)
  return (
    <div className="toasts" aria-live="polite">
      <AnimatePresence initial={false}>
        {toasts.map((t) => (
          <motion.button
            type="button"
            key={t.id}
            className={`toast toast--${t.kind}`}
            initial={{ opacity: 0, y: 12, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, x: 24 }}
            transition={{ duration: 0.18 }}
            onClick={() => dismiss(t.id)}
          >
            {t.text}
          </motion.button>
        ))}
      </AnimatePresence>
    </div>
  )
}

interface Item { id: string; group: string; name: string; hint?: string; swatch?: string; run: () => void }

export function CommandPalette() {
  const open = useStudio((s) => s.palette)
  const setOpen = useStudio((s) => s.setPalette)
  const effects = useStudio((s) => s.effects)
  const gels = useStudio((s) => s.gels)
  const caps = useStudio((s) => s.caps)
  const lights = useStudio((s) => s.lights)
  const scenes = useStudio((s) => s.store?.scenes ?? EMPTY)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const items = useMemo<Item[]>(() => {
    const { setTab, send, apply, power, select, setAddLight } = useStudio.getState()
    const white = caps?.features.white ?? false
    const out: Item[] = [
      { id: 'on', group: 'Actions', name: 'Switch on', run: () => power(true, 0.4) },
      { id: 'off', group: 'Actions', name: 'Switch off', run: () => power(false, 0.4) },
      ...(lights.length > 1 ? [
        { id: 'all-on', group: 'Actions', name: 'Switch every light on', run: () => send({ type: 'power.all', on: true, fade: 0.6 }) },
        { id: 'all-off', group: 'Actions', name: 'Switch every light off', run: () => send({ type: 'power.all', on: false, fade: 0.6 }) },
      ] : []),
      { id: 'add', group: 'Actions', name: 'Add a light', run: () => setAddLight(true) },
      ...lights.map((l) => ({ id: `light-${l.id}`, group: 'Lights', name: l.name, hint: l.model, run: () => select(l.id, { connect: true }) })),
      { id: 'stop', group: 'Actions', name: 'Stop the running effect', run: () => send({ type: 'engine.stop' }) },
      { id: 'read', group: 'Actions', name: 'Read the light now', run: () => send({ type: 'readback' }) },
      { id: 'reconnect', group: 'Actions', name: 'Reconnect', run: () => send({ type: 'link.reconnect' }) },
      ...TABS.filter((t) => tabAvailable(t, caps)).map((t) => ({ id: `tab-${t.id}`, group: 'Go to', name: t.name, hint: t.blurb, run: () => setTab(t.id as TabId) })),
      ...[1800, 2700, 3200, 4300, 5600, 6500, 8000, 10000].filter((k) => white && caps && k >= caps.min_kelvin && k <= caps.max_kelvin).map((k) => ({
        id: `k${k}`, group: 'White', name: `${k} K`, swatch: rgbCss(kelvinToRgb(k)),
        run: () => apply({ mode: 'cct', cct: { kelvin: k } }, { fade: 0.4 }),
      })),
      ...effects.map((e) => ({
        id: `fx-${e.id}`, group: 'Effects', name: e.name, hint: e.category, swatch: e.accent,
        run: () => send({ type: 'engine.start', effect: e.id, params: {} }),
      })),
      ...(caps?.effects ?? []).map((e) => ({
        id: `bfx-${e.symbol}`, group: 'Built-in effects', name: e.name,
        run: () => apply({ mode: 'fx', fx: { symbol: e.symbol, speed: null, params: {} } }),
      })),
      ...scenes.map((s) => ({ id: `scene-${s.id}`, group: 'Scenes', name: s.name, run: () => send({ type: 'scene.apply', id: s.id }) })),
      ...gels.map((g) => ({
        id: `gel-${g.label}`, group: 'Gels', name: g.label, swatch: rgbCss(hexToRgb(g.hex)),
        run: () => apply({ mode: 'gel', gel: { version: g.version, brand: g.brand, number: g.number, sub_brand: g.sub_brand, label: g.label, hex: g.hex } }),
      })),
    ]
    return out
  }, [effects, gels, caps, scenes, lights])

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    const pool = q ? items.filter((i) => `${i.name} ${i.group} ${i.hint ?? ''}`.toLowerCase().includes(q)) : items.filter((i) => i.group !== 'Gels')
    return pool.slice(0, 60)
  }, [items, query])

  useEffect(() => {
    if (open) {
      setQuery('')
      setActive(0)
      window.setTimeout(() => inputRef.current?.focus(), 10)
    }
  }, [open])

  const run = (item: Item | undefined) => {
    if (!item) return
    item.run()
    setOpen(false)
  }

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="palette-backdrop" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}>
          <motion.div className="palette" role="dialog" aria-label="Find anything" initial={{ y: -12, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: -8, opacity: 0 }}>
            <div className="palette-search">
              <Search size={18} />
              <input
                ref={inputRef}
                value={query}
                placeholder="Search tabs, effects, gels, scenes"
                aria-label="Search"
                onChange={(e) => { setQuery(e.target.value); setActive(0) }}
                onKeyDown={(e) => {
                  if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(results.length - 1, a + 1)) }
                  if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(0, a - 1)) }
                  if (e.key === 'Enter') run(results[active])
                  if (e.key === 'Escape') setOpen(false)
                }}
              />
            </div>
            <ul className="palette-list" role="listbox">
              {results.map((item, i) => (
                <li key={item.id} role="option" aria-selected={i === active}>
                  <button type="button" className={i === active ? 'is-on' : ''} onMouseEnter={() => setActive(i)} onClick={() => run(item)}>
                    {item.swatch ? <span className="palette-swatch" style={{ background: item.swatch }} /> : <span className="palette-swatch palette-swatch--empty" />}
                    <span className="palette-name">{item.name}</span>
                    <span className="palette-group">{item.hint ?? item.group}</span>
                    {i === active && <CornerDownLeft size={14} className="palette-enter" />}
                  </button>
                </li>
              ))}
              {results.length === 0 && <li className="palette-empty">Nothing matches "{query}". Try a colour, an effect name or a gel number.</li>}
            </ul>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

/** Space: power. [ and ]: brightness. Esc: stop. 1-9: scenes. Ctrl+K: find. */
export function useShortcuts() {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const s = useStudio.getState()
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        s.setPalette(!s.palette)
        return
      }
      const target = e.target as HTMLElement
      if (s.palette || target.closest('input, textarea, select, [role="slider"], [contenteditable]')) return
      if ((e.key === 'l' || e.key === 'L') && !e.ctrlKey && !e.altKey && !e.metaKey) {
        // Next light (Shift: previous) among those reachable now; never moves the link.
        if (e.repeat) return
        const reachable = s.lights.filter((l) => l.online)
        if (reachable.length < 2) return
        const at = reachable.findIndex((l) => l.id === s.selected)
        const next = reachable[(at + (e.shiftKey ? -1 : 1) + reachable.length) % reachable.length]
        s.select(next.id)
        s.toast(`Controlling ${next.name}`, 'info')
        return
      }
      if (!s.state) return
      if (e.key === ' ' && !target.closest('button')) {
        e.preventDefault()
        s.power(!s.state.power, 0.3)
      } else if (e.key === '[' || e.key === ']') {
        const step = e.shiftKey ? 1 : 5
        const next = Math.max(0, Math.min(100, s.state.brightness + (e.key === ']' ? step : -step)))
        s.apply({ brightness: next })
      } else if (e.key === 'Escape' && s.engine.kind) {
        s.send({ type: 'engine.stop' })
      } else if (/^[1-9]$/.test(e.key) && !e.ctrlKey && !e.altKey) {
        const scene = s.store?.scenes[Number(e.key) - 1]
        if (scene) s.send({ type: 'scene.apply', id: scene.id })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
}
