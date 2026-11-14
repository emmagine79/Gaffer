// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest'

class FakeSocket {
  static OPEN = 1
  static made: FakeSocket[] = []
  readyState = 0
  onopen: (() => void) | null = null
  onmessage: ((e: MessageEvent) => void) | null = null
  onclose: (() => void) | null = null
  sent: string[] = []
  constructor() { FakeSocket.made.push(this) }
  send(data: string) { this.sent.push(data) }
  close() {}
  open() { this.readyState = 1; this.onopen?.() }
  drop() { this.readyState = 3; this.onclose?.() }
}
vi.stubGlobal('WebSocket', FakeSocket)

const { Socket } = await import('./socket')

afterEach(() => { FakeSocket.made = [] })

it('a request made while the socket is closed fails at once, not at its timeout', async () => {
  const socket = new Socket('ws://x/ws')
  socket.connect()
  await expect(socket.request({ type: 'lights.scan' }, 60_000)).rejects.toThrow('Gaffer is not connected to the lights service')
  expect(FakeSocket.made[0].sent).toEqual([])
})

it('a request still waiting when the socket closes fails at once with the same message', async () => {
  const socket = new Socket('ws://x/ws')
  socket.connect()
  FakeSocket.made[0].open()
  const first = socket.request({ type: 'lights.scan' }, 60_000)
  const second = socket.request({ type: 'lights.pair' }, 60_000)
  FakeSocket.made[0].drop()
  await expect(first).rejects.toThrow('Gaffer is not connected to the lights service')
  await expect(second).rejects.toThrow('Gaffer is not connected to the lights service')
})

it('a reply that arrives on an open socket still resolves its request', async () => {
  const socket = new Socket('ws://x/ws')
  socket.connect()
  const ws = FakeSocket.made[0]
  ws.open()
  const pending = socket.request({ type: 'all.off' })
  const { rid } = JSON.parse(ws.sent[0]) as { rid: number }
  ws.onmessage?.({ data: JSON.stringify({ type: 'ack', rid }) } as MessageEvent)
  await expect(pending).resolves.toMatchObject({ type: 'ack' })
})
