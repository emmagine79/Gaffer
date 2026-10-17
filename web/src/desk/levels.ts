/**
 * Where the service will put every picked light for a grouped drag. A copy of the rule in
 * service/gaffer/levels.py (scale_levels with start_levels), so the desk can show the result
 * before the service answers. The service stays the authority: its answer replaces these.
 */
export function scaleLevels(start: Record<string, number>, anchor: string, level: number): Record<string, number> {
  const clamp = (n: number) => Math.min(100, Math.max(0, n))
  const target = clamp(level)
  const old = start[anchor]
  return Object.fromEntries(
    Object.entries(start).map(([id, now]) => [id, id === anchor ? target : old > 0 ? clamp((now * target) / old) : clamp(now + (target - old))]),
  )
}
