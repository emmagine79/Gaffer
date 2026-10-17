import {
  AlarmClock, Aperture, AudioWaveform, Bluetooth, Bookmark, Clapperboard, FlaskConical, Palette, Sun,
  LifeBuoy, SwatchBook, Waypoints, WandSparkles, type LucideIcon,
} from 'lucide-react'
import type { Caps } from '../lib/types'
import type { TabId } from '../state/store'

export interface TabDef {
  id: TabId
  name: string
  icon: LucideIcon
  group: string
  blurb: string
  /** Whether the selected light can use this tab at all. Absent: every light can. */
  available?: (caps: Caps) => boolean
  /** A blurb that depends on the light, where the plain one would mislead. */
  blurbFor?: (caps: Caps, gelCount: number) => string
}

export const TABS: TabDef[] = [
  { id: 'live', name: 'Live', icon: Aperture, group: 'Control', blurb: 'See the light on a set and change it fast' },
  {
    id: 'white', name: 'White', icon: Sun, group: 'Control', blurb: 'Colour temperature and tint',
    available: (c) => c.features.white,
    blurbFor: (c) => (c.features.daylight ? `Fixed ${c.min_kelvin} K daylight: brightness and fine dimming` : c.features.tint ? 'Colour temperature and tint' : 'Colour temperature'),
  },
  {
    id: 'colour', name: 'Colour', icon: Palette, group: 'Control', blurb: 'Hue wheel, channels, palettes from images',
    available: (c) => c.features.colour || c.features.channels,
  },
  {
    id: 'gels', name: 'Gels', icon: SwatchBook, group: 'Control', blurb: 'Lighting gels with their real colours',
    available: (c) => c.features.gels !== null,
    blurbFor: (c, n) => (c.features.gels === 'white' ? `${n} correction gels, recreated in white` : c.features.gels === 'native' ? `${n} gels, built into the light` : `${n} lighting gels with their real colours`),
  },
  { id: 'effects', name: 'Effects', icon: WandSparkles, group: 'Motion', blurb: 'Animated looks, rendered live or built in' },
  { id: 'timeline', name: 'Timeline', icon: Clapperboard, group: 'Motion', blurb: 'Keyframe your own light cues' },
  { id: 'sync', name: 'Sync', icon: AudioWaveform, group: 'Motion', blurb: 'Follow music or your screen' },
  { id: 'scenes', name: 'Scenes', icon: Bookmark, group: 'Library', blurb: 'Saved looks, one click away' },
  { id: 'schedule', name: 'Schedule', icon: AlarmClock, group: 'Library', blurb: 'Sunrise alarms and timed looks' },
  { id: 'mesh', name: 'Mesh', icon: Waypoints, group: 'Studio', blurb: 'Every light: place them, switch them, sync them' },
  { id: 'device', name: 'Device', icon: Bluetooth, group: 'Studio', blurb: 'This light: model, fan, battery and settings' },
  { id: 'lab', name: 'Lab', icon: FlaskConical, group: 'Studio', blurb: 'Raw frames and protocol experiments' },
  { id: 'guide', name: 'Guide', icon: LifeBuoy, group: 'Studio', blurb: 'Pairing, every kind of light, and fixes for when something is off' },
]

export function tabAvailable(def: TabDef, caps: Caps | null): boolean {
  if (!caps) return ['mesh', 'guide', 'scenes', 'schedule'].includes(def.id)
  if (caps.kind === 'unsupported') return ['mesh', 'device', 'lab', 'guide'].includes(def.id)
  return def.available ? def.available(caps) : true
}

export function tabBlurb(def: TabDef, caps: Caps | null, gelCount: number): string {
  return caps && def.blurbFor ? def.blurbFor(caps, gelCount) : def.blurb
}
