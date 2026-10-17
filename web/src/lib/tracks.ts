import { hsvToRgb, kelvinToRgb, rgbCss } from './color'

/** A true blackbody gradient across a kelvin range. */
export function kelvinTrack(min = 1800, max = 10000, steps = 14) {
  const stops = Array.from({ length: steps + 1 }, (_, i) => {
    const k = min + ((max - min) * i) / steps
    return `${rgbCss(kelvinToRgb(k))} ${(i / steps) * 100}%`
  })
  return `linear-gradient(90deg, ${stops.join(', ')})`
}

export function hueTrack(sat = 100, vertical = false) {
  const stops = Array.from({ length: 13 }, (_, i) => `${rgbCss(hsvToRgb(i * 30, sat))} ${(i / 12) * 100}%`)
  return `linear-gradient(${vertical ? '0deg' : '90deg'}, ${stops.join(', ')})`
}

export function satTrack(hue: number) {
  return `linear-gradient(90deg, ${rgbCss(hsvToRgb(hue, 0))}, ${rgbCss(hsvToRgb(hue, 100))})`
}

export function levelTrack(rgb: [number, number, number]) {
  return `linear-gradient(90deg, #0d0d0f, ${rgbCss(rgb)})`
}

export const tintTrack = 'linear-gradient(90deg, #43d66b, #e9ecef 50%, #e34fd0)'

export function channelTrack(color: string, vertical = true) {
  return `linear-gradient(${vertical ? '0deg' : '90deg'}, #0d0d0f, ${color})`
}
