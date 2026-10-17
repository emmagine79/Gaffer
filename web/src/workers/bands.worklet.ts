/// <reference lib="webworker" />
/**
 * Runs on the audio rendering thread, which the browser never throttles: it
 * keeps going while the studio tab is hidden behind the music player.
 *
 * Splits the signal into bass, mid and treble with biquad filters, and every
 * ~21 ms posts the RMS of each band through a MessagePort straight to the
 * stream worker, so the main thread is never on the path.
 */

declare const sampleRate: number
declare function registerProcessor(name: string, ctor: unknown): void
declare class AudioWorkletProcessor {
  readonly port: MessagePort
}

class Biquad {
  private b0 = 0; private b1 = 0; private b2 = 0; private a1 = 0; private a2 = 0
  private x1 = 0; private x2 = 0; private y1 = 0; private y2 = 0

  constructor(kind: 'lowpass' | 'highpass' | 'bandpass', freq: number, q: number) {
    const w = (2 * Math.PI * freq) / sampleRate
    const alpha = Math.sin(w) / (2 * q)
    const cos = Math.cos(w)
    let b0: number, b1: number, b2: number
    if (kind === 'lowpass') { b0 = (1 - cos) / 2; b1 = 1 - cos; b2 = (1 - cos) / 2 }
    else if (kind === 'highpass') { b0 = (1 + cos) / 2; b1 = -(1 + cos); b2 = (1 + cos) / 2 }
    else { b0 = alpha; b1 = 0; b2 = -alpha }
    const a0 = 1 + alpha
    this.b0 = b0 / a0; this.b1 = b1 / a0; this.b2 = b2 / a0
    this.a1 = (-2 * cos) / a0; this.a2 = (1 - alpha) / a0
  }

  step(x: number) {
    const y = this.b0 * x + this.b1 * this.x1 + this.b2 * this.x2 - this.a1 * this.y1 - this.a2 * this.y2
    this.x2 = this.x1; this.x1 = x; this.y2 = this.y1; this.y1 = y
    return y
  }
}

class BandsProcessor extends AudioWorkletProcessor {
  private out: MessagePort | null = null
  private bass = new Biquad('lowpass', 150, 0.8)
  private mid = new Biquad('bandpass', 700, 0.6)
  private treble = new Biquad('highpass', 3000, 0.7)
  private sums = [0, 0, 0, 0]
  private count = 0
  private readonly window = Math.round(sampleRate / 48) // ~21 ms

  constructor() {
    super()
    this.port.onmessage = (e: MessageEvent) => {
      if (e.data?.port) this.out = e.data.port as MessagePort
    }
  }

  process(inputs: Float32Array[][]): boolean {
    const channels = inputs[0]
    if (!channels || channels.length === 0) return true
    const left = channels[0]
    const right = channels[1] ?? left
    for (let i = 0; i < left.length; i++) {
      const x = (left[i] + right[i]) * 0.5
      const b = this.bass.step(x)
      const m = this.mid.step(x)
      const t = this.treble.step(x)
      this.sums[0] += b * b
      this.sums[1] += m * m
      this.sums[2] += t * t
      this.sums[3] += x * x
    }
    this.count += left.length
    if (this.count >= this.window) {
      const n = this.count
      this.out?.postMessage({
        bass: Math.sqrt(this.sums[0] / n),
        mid: Math.sqrt(this.sums[1] / n),
        treble: Math.sqrt(this.sums[2] / n),
        rms: Math.sqrt(this.sums[3] / n),
      })
      this.sums = [0, 0, 0, 0]
      this.count = 0
    }
    return true
  }
}

registerProcessor('lumen-bands', BandsProcessor)
