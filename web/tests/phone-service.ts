/**
 * Starts the real light service in --demo for the phone access tests (SPEC-015), with a fake
 * `tailscale` tool first on its PATH. The real Tailscale tool is never run.
 *
 * Like service.ts: the secret goes in on stdin and ending stdin stops the service; the process
 * group is killed as well in case it does not stop in time.
 */
import { spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const SERVICE = resolve(HERE, '../../service')
const RESULTS = join(HERE, '../test-results')

export const TAILNET_NAME = 'studio-mac.tail1234.ts.net'
const STATUS = {
  BackendState: 'Running',
  Self: { DNSName: `${TAILNET_NAME}.`, TailscaleIPs: ['100.64.0.9', 'fd7a:115c:a1e0::9'] },
}

/** How long the service may take to print its ready line: uv may first sync the venv. */
const START_MS = 60_000
/** How long it may take to stop after stdin closes before its group is killed. */
const STOP_MS = 10_000

export interface PhoneService { port: number; secret: string; stop: () => Promise<void> }

export async function startPhoneService(): Promise<PhoneService> {
  mkdirSync(RESULTS, { recursive: true })
  const folder = mkdtempSync(join(RESULTS, 'phone-'))
  const bin = join(folder, 'bin')
  mkdirSync(bin)
  const fake = join(bin, 'tailscale')
  writeFileSync(fake, `#!/bin/sh\ncat <<'JSON'\n${JSON.stringify(STATUS)}\nJSON\n`)
  chmodSync(fake, 0o755)

  const secret = randomBytes(24).toString('base64url')
  const child = spawn(
    'uv',
    ['run', '--project', SERVICE, '--frozen', 'python', '-m', 'gaffer', '--demo', '--port', '0', '--data', join(folder, 'data'), '--session-from-stdin'],
    { cwd: SERVICE, stdio: ['pipe', 'pipe', 'ignore'], detached: true, env: { ...process.env, PATH: `${bin}:${process.env.PATH}` } },
  )
  const killGroup = () => {
    try { process.kill(-child.pid!, 'SIGKILL') } catch { /* already gone */ }
  }
  let port: number
  try {
    port = await new Promise<number>((done, fail) => {
      const timer = setTimeout(() => fail(new Error('the service did not start')), START_MS)
      const failNow = (error: Error) => { clearTimeout(timer); fail(error) }
      child.on('error', failNow)
      child.stdin.on('error', failNow)
      child.stdin.write(`${secret}\n`)
      let out = ''
      child.stdout.on('data', (chunk: Buffer) => {
        out += chunk.toString()
        const match = /GAFFER_SERVICE_READY port=(\d+)/.exec(out)
        if (match) { clearTimeout(timer); done(Number(match[1])) }
      })
      child.on('exit', (code) => { clearTimeout(timer); fail(new Error(`the service exited (${code})`)) })
    })
  } catch (error) {
    killGroup()
    rmSync(folder, { recursive: true, force: true })
    throw error
  }
  child.stdout.resume()
  child.removeAllListeners('exit')

  return {
    port,
    secret,
    stop: async () => {
      const exited = new Promise<void>((done) => {
        if (child.exitCode !== null) done()
        else child.once('exit', () => done())
      })
      child.stdin.end()
      const timer = setTimeout(killGroup, STOP_MS)
      await exited
      clearTimeout(timer)
      rmSync(folder, { recursive: true, force: true })
    },
  }
}
