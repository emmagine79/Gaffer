import { Plus, X } from 'lucide-react'
import { hexToRgb, hsvToRgb, isValidHex, rgbToHex } from '../lib/color'
import { hueTrack, kelvinTrack } from '../lib/tracks'
import type { ParamSpec } from '../lib/types'
import { Field, Segmented, Toggle } from './Controls'
import { Slider } from './Slider'

interface Props {
  spec: ParamSpec
  value: unknown
  onChange: (value: unknown) => void
  /** All current values, for parameters whose meaning depends on another (option_value). */
  siblings?: Record<string, unknown>
  kelvinRange?: [number, number]
}

const fmt = (n: number, unit?: string, step?: number) => {
  const digits = step && step < 1 ? (step < 0.1 ? 2 : 1) : 0
  return `${n.toFixed(digits)}${unit ? (unit === '%' || unit === '°' ? unit : ` ${unit}`) : ''}`
}

export function ParamField({ spec, value, onChange, siblings = {}, kelvinRange = [1800, 10000] }: Props) {
  const label = (
    <>
      <span>{spec.label}</span>
      {spec.inferred && <span className="dim" title="Range inferred from the vendor app's defaults; the light may clamp it">inferred range</span>}
    </>
  )

  switch (spec.kind) {
    case 'number':
      return (
        <Field label={label} hint={spec.hint}>
          <Slider
            label={spec.label}
            value={Number(value ?? spec.default)}
            min={spec.min ?? 0}
            max={spec.max ?? 100}
            step={spec.step ?? 1}
            onChange={onChange}
            format={(v) => fmt(v, spec.unit, spec.step)}
          />
        </Field>
      )
    case 'kelvin':
      return (
        <Field label={label}>
          <Slider
            label={spec.label}
            value={Number(value ?? spec.default)}
            min={kelvinRange[0]}
            max={kelvinRange[1]}
            step={50}
            track={kelvinTrack(kelvinRange[0], kelvinRange[1])}
            onChange={onChange}
            format={(v) => `${v} K`}
          />
        </Field>
      )
    case 'kelvin100':
      return (
        <Field label={label}>
          <Slider
            label={spec.label}
            value={Number(value ?? spec.default)}
            min={kelvinRange[0] / 100}
            max={kelvinRange[1] / 100}
            step={1}
            track={kelvinTrack(kelvinRange[0], kelvinRange[1])}
            onChange={onChange}
            format={(v) => `${v * 100} K`}
          />
        </Field>
      )
    case 'option_value': {
      const hue = Number(siblings.option ?? 0) === 1
      return hue ? (
        <Field label="Hue">
          <Slider label="Hue" value={Number(value ?? 0) % 361} min={0} max={360} step={1}
            track={hueTrack()} onChange={onChange} format={(v) => `${v}°`} />
        </Field>
      ) : (
        <Field label="Colour temperature">
          <Slider label="Colour temperature" value={Number(value ?? 56)} min={kelvinRange[0] / 100} max={kelvinRange[1] / 100}
            step={1} track={kelvinTrack(kelvinRange[0], kelvinRange[1])} onChange={onChange} format={(v) => `${v * 100} K`} />
        </Field>
      )
    }
    case 'bool':
      return (
        <div className="field field--row">
          <span className="field-label">{label}</span>
          <Toggle label={spec.label} on={Boolean(value ?? spec.default)} onChange={(on) => onChange(on ? 1 : 0)} />
        </div>
      )
    case 'choice': {
      const options = spec.options ?? []
      return (
        <Field label={label}>
          {options.length <= 4 ? (
            <Segmented size="sm" label={spec.label} value={value as string | number} onChange={onChange}
              options={options.map((o) => ({ value: o.value, label: o.label }))} />
          ) : (
            <select className="input" value={String(value)} onChange={(e) => onChange(e.target.value)}>
              {options.map((o) => <option key={String(o.value)} value={String(o.value)}>{o.label}</option>)}
            </select>
          )}
        </Field>
      )
    }
    case 'text':
      return (
        <Field label={label} hint={spec.hint}>
          <input className="input" defaultValue={String(value ?? spec.default ?? '')} key={String(value)} maxLength={80}
            onBlur={(e) => onChange(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && onChange(e.currentTarget.value)} />
        </Field>
      )
    case 'color':
      return (
        <Field label={label}>
          <ColorInput value={String(value ?? spec.default)} onChange={onChange} />
        </Field>
      )
    case 'palette': {
      const colors = (Array.isArray(value) ? value : (spec.default as string[])) as string[]
      if (colors.length > 12) {
        return (
          <Field label={label} hint={`${colors.length} colours, loaded from an image`}>
            <div className="palette-strip" style={{ background: `linear-gradient(90deg, ${colors.join(', ')})` }} />
          </Field>
        )
      }
      return (
        <Field label={label}>
          <div className="palette-edit">
            {colors.map((c, i) => (
              <div key={i} className="palette-chip">
                <input type="color" value={c} aria-label={`Colour ${i + 1}`}
                  onChange={(e) => onChange(colors.map((x, j) => (j === i ? e.target.value : x)))} />
                {colors.length > 1 && (
                  <button type="button" aria-label={`Remove colour ${i + 1}`} onClick={() => onChange(colors.filter((_, j) => j !== i))}>
                    <X size={12} />
                  </button>
                )}
              </div>
            ))}
            {colors.length < (spec.max ?? 12) && (
              <button type="button" className="palette-add" aria-label="Add a colour"
                onClick={() => onChange([...colors, rgbToHex(hsvToRgb(Math.random() * 360, 90))])}>
                <Plus size={16} />
              </button>
            )}
          </div>
        </Field>
      )
    }
    default:
      return null
  }
}

export function ColorInput({ value, onChange }: { value: string; onChange: (hex: string) => void }) {
  return (
    <div className="color-input">
      <input type="color" value={isValidHex(value) ? rgbToHex(hexToRgb(value)) : '#ffffff'} onChange={(e) => onChange(e.target.value)} aria-label="Pick a colour" />
      <input
        className="input"
        defaultValue={value}
        key={value}
        spellCheck={false}
        aria-label="Hex colour"
        onBlur={(e) => isValidHex(e.target.value) && onChange(rgbToHex(hexToRgb(e.target.value)))}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && isValidHex(e.currentTarget.value)) onChange(rgbToHex(hexToRgb(e.currentTarget.value)))
        }}
      />
    </div>
  )
}
