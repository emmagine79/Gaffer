/**
 * Gaffer's own effects, by the name people see and the id of lumen's effect behind it.
 * They run on the Mac and work on any light; lumen's engine adapts each to what the light can show.
 * lumen names the same effects "Candle" and "Rainbow", so every place that names a playing effect
 * goes through `ownLabel` to keep the chip, the hero and the sentence saying the same word.
 */
export const OWN: { id: string; label: string }[] = [
  { id: 'breathe', label: 'Breathe' },
  { id: 'candle', label: 'Flicker' },
  { id: 'rainbow', label: 'Colour cycle' },
]

export const ownLabel = (id: string | null | undefined): string | null => OWN.find((o) => o.id === id)?.label ?? null
