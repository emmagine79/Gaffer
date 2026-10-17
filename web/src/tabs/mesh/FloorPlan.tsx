import { Bluetooth } from 'lucide-react'
import { useRef, useState, type CSSProperties, type PointerEvent } from 'react'
import { emission, rgbCss } from '../../lib/color'
import type { Group, LightView } from '../../lib/types'
import { useStudio } from '../../state/store'
import { LightGlyph, formOf } from '../../visuals/LightGlyph'

/** Where the subject stands on the plan, and where lights with no place yet are put around it. */
const SUBJECT = { x: 0.5, y: 0.58 }

/** Spots around the subject, like lights set up for a portrait: front, sides, behind. */
const SPOTS = Array.from({ length: 16 }, (_, i) => {
  const angle = -Math.PI / 2 + ((i % 2 ? 1 : -1) * Math.ceil(i / 2) * Math.PI) / 8
  return { x: SUBJECT.x + Math.cos(angle) * 0.36, y: Math.min(0.8, Math.max(0.12, SUBJECT.y + Math.sin(angle) * 0.42)) }
})

/** Where each light stands: where it was put, or the free spot farthest from the others. */
export function placeAll(lights: LightView[]): Record<string, { x: number; y: number }> {
  const out: Record<string, { x: number; y: number }> = {}
  for (const l of lights) if (l.x != null && l.y != null) out[l.id] = { x: l.x, y: l.y }
  for (const l of lights) {
    if (out[l.id]) continue
    const taken = Object.values(out)
    const gap = (p: { x: number; y: number }) => Math.min(9, ...taken.map((t) => Math.hypot(p.x - t.x, (p.y - t.y) * 0.62)))
    out[l.id] = SPOTS.reduce((best, p) => (gap(p) > gap(best) + 1e-6 ? p : best), SPOTS[0])
  }
  return out
}

function Beam({ from, light }: { from: { x: number; y: number }; light: LightView }) {
  if (!light.state.power || !light.online) return null
  const { rgb, level } = emission(light.state)
  const dx = SUBJECT.x - from.x
  const dy = SUBJECT.y - from.y
  const length = Math.hypot(dx * 1000, dy * 625)
  const angle = (Math.atan2(dy * 625, dx * 1000) * 180) / Math.PI
  const reach = Math.max(0, length - 26)
  return (
    <g transform={`translate(${from.x * 1000} ${from.y * 625}) rotate(${angle})`}>
      <path d={`M 10 -7 L ${reach} -${reach * 0.24} Q ${reach + 16} 0 ${reach} ${reach * 0.24} L 10 7 Z`}
        fill={`url(#beam-${light.id})`} opacity={0.25 + level * 0.65} />
      <defs>
        <linearGradient id={`beam-${light.id}`} x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor={rgbCss(rgb)} stopOpacity="0.85" />
          <stop offset="1" stopColor={rgbCss(rgb)} stopOpacity="0" />
        </linearGradient>
      </defs>
    </g>
  )
}

/**
 * The studio from above. Each light stands where you put it, throws its beam
 * at the subject in its live colour, and is joined to the light the Bluetooth
 * link goes through, the way the mesh actually carries its commands.
 */
export function FloorPlan({ groups }: { groups: Group[] }) {
  const lights = useStudio((s) => s.lights)
  const selected = useStudio((s) => s.selected)
  const gateway = useStudio((s) => s.link?.gateway)
  const select = useStudio((s) => s.select)
  const moveLight = useStudio((s) => s.moveLight)
  const setTab = useStudio((s) => s.setTab)
  const area = useRef<HTMLDivElement>(null)
  // The gesture lives in a ref (every event sees the latest), the picture in state.
  const gesture = useRef<{ id: string; pointer: number; startX: number; startY: number; dx: number; dy: number; moved: boolean } | null>(null)
  const [drag, setDrag] = useState<{ id: string; x: number; y: number } | null>(null)

  const places = placeAll(lights)
  if (drag) places[drag.id] = { x: drag.x, y: drag.y }
  const gatewayPlace = gateway ? places[gateway] : null
  const groupOf = (id: string) => groups.find((g) => g.enabled && g.members.includes(id) && g.members.length > 1)

  const point = (e: PointerEvent) => {
    const rect = area.current?.getBoundingClientRect()
    if (!rect) return { x: 0.5, y: 0.5 }
    return { x: (e.clientX - rect.left) / rect.width, y: (e.clientY - rect.top) / rect.height }
  }
  const clampPlace = (x: number, y: number) => ({ x: Math.min(0.97, Math.max(0.03, x)), y: Math.min(0.95, Math.max(0.05, y)) })
  const endGesture = () => { gesture.current = null; setDrag(null) }

  return (
    <div className="plan" ref={area}>
      <svg className="plan-art" viewBox="0 0 1000 625" preserveAspectRatio="none" aria-hidden="true">
        <defs>
          <linearGradient id="plan-paper" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="#d9d5cc" stopOpacity="0.22" />
            <stop offset="1" stopColor="#d9d5cc" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {/* the backdrop roll and its sweep onto the floor */}
        <rect x="170" y="20" width="660" height="18" rx="9" fill="#3b3c42" />
        <path d="M 182 38 L 818 38 L 840 150 L 160 150 Z" fill="url(#plan-paper)" />
        <text x="182" y="62" className="plan-label">BACKDROP</text>
        {lights.map((l) => <Beam key={l.id} from={places[l.id]} light={l} />)}
        {gatewayPlace && lights.filter((l) => l.id !== gateway && l.online).map((l) => (
          <line key={l.id} className="plan-relay" x1={gatewayPlace.x * 1000} y1={gatewayPlace.y * 625}
            x2={places[l.id].x * 1000} y2={places[l.id].y * 625} />
        ))}
        {/* the subject, from above: shoulders and head */}
        <g transform={`translate(${SUBJECT.x * 1000} ${SUBJECT.y * 625})`} className="plan-subject">
          <ellipse rx="44" ry="20" />
          <circle r="15" cy="-2" />
          <text y="48" textAnchor="middle" className="plan-label">SUBJECT</text>
        </g>
        <g transform="translate(500 600)" className="plan-camera">
          <rect x="-26" y="-14" width="52" height="24" rx="5" />
          <circle r="9" cy="-16" />
          <text y="-34" textAnchor="middle" className="plan-label">CAMERA</text>
        </g>
      </svg>

      {lights.map((l) => {
        const at = places[l.id]
        const { rgb, level } = emission(l.state)
        const group = groupOf(l.id)
        return (
          <button
            key={l.id}
            type="button"
            className={`puck ${l.id === selected ? 'is-selected' : ''} ${l.online ? '' : 'is-away'} ${drag?.id === l.id ? 'is-dragging' : ''}`}
            style={{ left: `${at.x * 100}%`, top: `${at.y * 100}%`, '--puck': rgbCss(rgb) } as CSSProperties}
            onPointerDown={(e) => {
              if (e.button !== 0) return
              e.currentTarget.setPointerCapture(e.pointerId)
              const p = point(e)
              // Keep the grab offset, so the light does not jump to the pointer.
              gesture.current = { id: l.id, pointer: e.pointerId, startX: e.clientX, startY: e.clientY, dx: at.x - p.x, dy: at.y - p.y, moved: false }
            }}
            onPointerMove={(e) => {
              const g = gesture.current
              if (!g || g.pointer !== e.pointerId) return
              // A few pixels of jitter is still a click.
              if (!g.moved && Math.hypot(e.clientX - g.startX, e.clientY - g.startY) < 4) return
              g.moved = true
              const p = point(e)
              setDrag({ id: g.id, ...clampPlace(p.x + g.dx, p.y + g.dy) })
            }}
            onPointerUp={(e) => {
              const g = gesture.current
              if (!g || g.pointer !== e.pointerId) return
              if (g.moved) {
                const p = point(e)
                const to = clampPlace(p.x + g.dx, p.y + g.dy)
                moveLight(g.id, Math.round(to.x * 1e4) / 1e4, Math.round(to.y * 1e4) / 1e4)
              } else {
                select(g.id)
              }
              endGesture()
            }}
            onPointerCancel={endGesture}
            onLostPointerCapture={() => { if (gesture.current) endGesture() }}
            onDoubleClick={() => { select(l.id); setTab('live') }}
            title={`${l.name}: click to control, drag to place, double-click to open`}
          >
            <span className="puck-glyph">
              <LightGlyph form={formOf(l.model)} rgb={rgb} level={level} off={!l.state.power} size={58} />
              {gateway === l.id && <span className="puck-link" title="The Bluetooth link goes through this light"><Bluetooth size={11} /></span>}
            </span>
            <span className="puck-name">{l.name}</span>
            <span className="puck-meta">{l.online ? (l.state.power ? `${Math.round(l.state.brightness)}%` : 'Off') : 'Other network'}{group ? ` · ${group.name}` : ''}</span>
          </button>
        )
      })}
      <p className="plan-hint">Drag lights to where they stand. Click one to control it, double-click to open all its controls.</p>
    </div>
  )
}
