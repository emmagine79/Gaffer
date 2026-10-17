import type { ServerMessage } from './types'

/**
 * Fired on `window` each time the light socket closes. A phone that was signed out (New PIN, or
 * phone access switched off) cannot tell from the close alone: a refused reconnect looks like any
 * dropped connection to a browser. The PIN gate listens and asks the service.
 */
export const SOCKET_CLOSED = 'gaffer:socket-closed'

type Listener = (m: ServerMessage) => void
type StatusListener = (open: boolean) => void

/**
 * One WebSocket to the studio server, reconnecting with backoff.
 *
 * While closed, outgoing messages are dropped except the newest `set`, which is
 * replayed on reconnect: a stale slider position is worthless, the latest one
 * is the whole point.
 */
export class Socket {
  private ws: WebSocket | null = null
  private retry = 0
  private listeners = new Set<Listener>()
  private statusListeners = new Set<StatusListener>()
  private pendingSet: Record<string, unknown> | null = null
  private pendingPower: Record<string, unknown> | null = null
  private rid = 0
  private waiters = new Map<number, (m: ServerMessage) => void>()

  private url: string

  constructor(url: string) {
    this.url = url
  }

  connect() {
    const ws = new WebSocket(this.url)
    this.ws = ws
    ws.onopen = () => {
      this.retry = 0
      this.statusListeners.forEach((l) => l(true))
      if (this.pendingSet) {
        ws.send(JSON.stringify(this.pendingSet))
        this.pendingSet = null
      }
      if (this.pendingPower) {
        ws.send(JSON.stringify(this.pendingPower))
        this.pendingPower = null
      }
    }
    ws.onmessage = (event) => {
      let message: ServerMessage
      try {
        message = JSON.parse(event.data as string) as ServerMessage
      } catch {
        return
      }
      const rid = (message as { rid?: number }).rid
      if (rid !== undefined && this.waiters.has(rid)) {
        this.waiters.get(rid)?.(message)
        this.waiters.delete(rid)
      }
      this.listeners.forEach((l) => l(message))
    }
    ws.onclose = () => {
      this.statusListeners.forEach((l) => l(false))
      window.dispatchEvent(new Event(SOCKET_CLOSED))
      const delay = Math.min(8000, 400 * 2 ** this.retry++)
      window.setTimeout(() => this.connect(), delay)
    }
  }

  send(message: Record<string, unknown>) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message))
    } else if (message.type === 'set') {
      // Merge rather than replace: brightness then kelvin while offline must both arrive
      // (for the same light; a change to another light replaces it).
      const same = this.pendingSet?.light === message.light
      const patch = deepMerge(same ? (this.pendingSet?.patch as Record<string, unknown>) ?? {} : {}, message.patch as Record<string, unknown>)
      this.pendingSet = { ...message, patch }
    } else if (message.type === 'power') {
      this.pendingPower = message
    }
  }

  /** Send and wait for the reply carrying the same request id. */
  request(message: Record<string, unknown>, timeoutMs = 6000): Promise<ServerMessage> {
    const rid = ++this.rid
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.waiters.delete(rid)
        reject(new Error('The studio did not answer in time'))
      }, timeoutMs)
      this.waiters.set(rid, (m) => {
        window.clearTimeout(timer)
        if (m.type === 'error') reject(new Error(m.text))
        else resolve(m)
      })
      this.send({ ...message, rid })
    })
  }

  onMessage(l: Listener) {
    this.listeners.add(l)
    return () => this.listeners.delete(l)
  }

  onStatus(l: StatusListener) {
    this.statusListeners.add(l)
    return () => this.statusListeners.delete(l)
  }
}

function deepMerge(a: Record<string, unknown>, b: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = { ...a }
  for (const [k, v] of Object.entries(b ?? {})) {
    const cur = out[k]
    out[k] = v && typeof v === 'object' && !Array.isArray(v) && cur && typeof cur === 'object' && k !== 'params'
      ? deepMerge(cur as Record<string, unknown>, v as Record<string, unknown>)
      : v
  }
  return out
}

export function socketUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const token = new URLSearchParams(location.search).get('t')
  return `${proto}://${location.host}/ws${token ? `?t=${encodeURIComponent(token)}` : ''}`
}
