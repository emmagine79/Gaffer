import workletUrl from '../workers/bands.worklet.ts?worker&url'
import { socketUrl } from './socket'

/**
 * The page's handle on the stream worker. One worker for the whole app, made
 * on first use; audio and screen sync both feed it.
 */
let worker: Worker | null = null
const listeners = new Set<(m: { type: string; [k: string]: unknown }) => void>()

export function streamWorker(): Worker {
  if (!worker) {
    worker = new Worker(new URL('../workers/stream.worker.ts', import.meta.url), { type: 'module' })
    worker.onmessage = (e) => listeners.forEach((l) => l(e.data))
    worker.postMessage({ type: 'init', url: socketUrl() })
  }
  return worker
}

export function onWorkerMessage(l: (m: { type: string; [k: string]: unknown }) => void) {
  listeners.add(l)
  return () => { listeners.delete(l) }
}

export interface AudioSession { context: AudioContext; analyser: AnalyserNode; stop: () => void }

/** Route a captured audio stream through the band worklet into the stream worker. */
export async function startAudio(media: MediaStream, opts: { combo?: boolean } = {}): Promise<AudioSession> {
  const context = new AudioContext({ latencyHint: 'interactive' })
  let bands: AudioWorkletNode
  try {
    await context.audioWorklet.addModule(workletUrl)
    bands = new AudioWorkletNode(context, 'lumen-bands', { numberOfInputs: 1, numberOfOutputs: 1 })
  } catch (err) {
    media.getTracks().forEach((t) => t.stop())
    void context.close()
    throw err
  }
  const source = context.createMediaStreamSource(media)
  // The worklet only runs while the graph pulls it, so feed a silent sink.
  const silent = context.createGain()
  silent.gain.value = 0
  source.connect(bands).connect(silent).connect(context.destination)
  const analyser = context.createAnalyser()
  analyser.fftSize = 2048
  analyser.smoothingTimeConstant = 0.6
  source.connect(analyser) // for the on-screen spectrum only

  const channel = new MessageChannel()
  bands.port.postMessage({ port: channel.port1 }, [channel.port1])
  streamWorker().postMessage({ type: 'audio-port', port: channel.port2, combo: Boolean(opts.combo) }, [channel.port2])

  return {
    context,
    analyser,
    stop: () => {
      streamWorker().postMessage({ type: 'stop', what: 'audio' })
      media.getTracks().forEach((t) => t.stop())
      void context.close()
    },
  }
}

declare class MediaStreamTrackProcessor {
  constructor(init: { track: MediaStreamTrack })
  readonly readable: ReadableStream<VideoFrame>
}

export const canProcessTracks = typeof (globalThis as { MediaStreamTrackProcessor?: unknown }).MediaStreamTrackProcessor === 'function'

/** Hand a screen-capture track's frames to the stream worker. */
export function startScreen(media: MediaStream): () => void {
  const track = media.getVideoTracks()[0]
  const processor = new MediaStreamTrackProcessor({ track })
  streamWorker().postMessage({ type: 'video', readable: processor.readable }, [processor.readable as unknown as Transferable])
  return () => {
    streamWorker().postMessage({ type: 'stop', what: 'screen' })
    media.getTracks().forEach((t) => t.stop())
  }
}
