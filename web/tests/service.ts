/**
 * Starts the real light service in --demo for the rendered-page tests, signed in.
 *
 * The service reads its session secret from stdin and exits when stdin closes
 * (service/gaffer/__main__.py), so ending the pipe stops it; the process group is
 * killed as well in case it does not stop in time.
 */
import { spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { cpSync, mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url))
const SERVICE = resolve(HERE, '../../service')
const RESULTS = join(HERE, '../test-results')
export const STATE_FILE = join(RESULTS, '.auth/state.json')
/** Test model files, copied to <data>/models/ where the service loads extra model files (SPEC-003). */
const MODELS = join(HERE, 'models')

/** How long the service may take to print its ready line: uv may first sync the venv. */
const START_MS = 60_000
/** How long it may take to stop after stdin closes before its group is killed. */
const STOP_MS = 10_000

export default async function startService() {
  mkdirSync(RESULTS, { recursive: true })
  const data = mkdtempSync(join(RESULTS, 'service-data-'))
  cpSync(MODELS, join(data, 'models'), { recursive: true })
  const secret = randomBytes(24).toString('base64url')
  const child = spawn(
    'uv',
    ['run', '--project', SERVICE, '--frozen', 'python', '-m', 'gaffer', '--demo', '--port', '0', '--data', data, '--session-from-stdin'],
    { cwd: SERVICE, stdio: ['pipe', 'pipe', 'ignore'], detached: true },
  )
  child.stdin.write(`${secret}\n`)

  const port = await new Promise<number>((done, fail) => {
    const timer = setTimeout(() => fail(new Error('the service did not start')), START_MS)
    let out = ''
    child.stdout.on('data', (chunk: Buffer) => {
      out += chunk.toString()
      const match = /GAFFER_SERVICE_READY port=(\d+)/.exec(out)
      if (match) {
        clearTimeout(timer)
        done(Number(match[1]))
      }
    })
    child.on('exit', (code) => {
      clearTimeout(timer)
      fail(new Error(`the service exited (${code})`))
    })
  })
  child.stdout.resume()
  child.removeAllListeners('exit')

  process.env.GAFFER_URL = `http://127.0.0.1:${port}`
  mkdirSync(dirname(STATE_FILE), { recursive: true })
  // The cookie /session?key= would set (service/gaffer/session.py).
  writeFileSync(STATE_FILE, JSON.stringify({
    cookies: [{
      name: 'gaffer_session', value: secret, domain: '127.0.0.1', path: '/',
      expires: -1, httpOnly: true, secure: false, sameSite: 'Strict',
    }],
    origins: [],
  }))

  return async () => {
    const exited = new Promise<void>((done) => {
      if (child.exitCode !== null) done()
      else child.once('exit', () => done())
    })
    child.stdin.end()
    const timer = setTimeout(() => {
      try { process.kill(-child.pid!, 'SIGKILL') } catch { /* already gone */ }
    }, STOP_MS)
    await exited
    clearTimeout(timer)
  }
}
