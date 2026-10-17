import { ArrowRight, ChevronDown, Plus } from 'lucide-react'
import type { ReactNode } from 'react'
import { Key } from '../components/Controls'
import type { LightKind } from '../lib/types'
import { useStudio } from '../state/store'
import { LightGlyph, type LightForm } from '../visuals/LightGlyph'
import './guide.css'

/* ---------------------------------------------------------------- illustrations */

function ResetArt() {
  return (
    <svg viewBox="0 0 160 110" className="guide-art" aria-hidden="true">
      <rect x="38" y="16" width="84" height="74" rx="12" fill="#26272c" stroke="#4a4c53" />
      <rect x="50" y="28" width="60" height="34" rx="4" fill="#0f1012" stroke="#3a3b41" />
      <text x="80" y="42" textAnchor="middle" className="guide-art-screen">BLUETOOTH</text>
      <text x="80" y="55" textAnchor="middle" className="guide-art-screen guide-art-screen--hi">› RESET</text>
      <circle cx="64" cy="76" r="6" fill="#34353b" />
      <circle cx="96" cy="76" r="6" fill="#34353b" />
      <circle cx="80" cy="76" r="8" className="guide-art-press" />
      <path d="M146 44a14 14 0 1 1-4-10" className="guide-art-arrow" />
      <path d="M143 26l-1 8 8-1" className="guide-art-arrow" />
    </svg>
  )
}

function FindArt() {
  return (
    <svg viewBox="0 0 160 110" className="guide-art" aria-hidden="true">
      <circle cx="80" cy="56" r="44" className="guide-art-ring" />
      <circle cx="80" cy="56" r="30" className="guide-art-ring" />
      <circle cx="80" cy="56" r="16" className="guide-art-ring" />
      <path d="M80 56 L118 34 A44 44 0 0 1 124 56 Z" className="guide-art-sweep" />
      <circle cx="80" cy="56" r="4" fill="#ecedef" />
      <circle cx="112" cy="44" r="5" className="guide-art-blip" />
      <circle cx="56" cy="78" r="3.5" className="guide-art-blip guide-art-blip--dim" />
    </svg>
  )
}

function PairArt() {
  return (
    <svg viewBox="0 0 160 110" className="guide-art" aria-hidden="true">
      <rect x="14" y="34" width="52" height="38" rx="6" fill="#26272c" stroke="#4a4c53" />
      <rect x="20" y="40" width="40" height="24" rx="2" fill="#0f1012" />
      <rect x="8" y="72" width="64" height="5" rx="2" fill="#3a3b41" />
      <path d="M70 54 C 86 36, 96 72, 112 54" className="guide-art-link" />
      <circle cx="128" cy="54" r="18" fill="#26272c" stroke="#4a4c53" />
      <circle cx="128" cy="54" r="10" className="guide-art-emitter" />
      <path d="M86 86 l6 6 12 -12" className="guide-art-check" />
    </svg>
  )
}

/* ---------------------------------------------------------------- pieces */

function Step({ n, title, art, children }: { n: number; title: string; art: ReactNode; children: ReactNode }) {
  return (
    <article className="guide-step">
      <div className="guide-step-art">{art}<span className="guide-step-n">{n}</span></div>
      <h3>{title}</h3>
      <div className="guide-step-body">{children}</div>
    </article>
  )
}

function Faq({ q, children, open = false }: { q: string; children: ReactNode; open?: boolean }) {
  return (
    <details className="faq" open={open}>
      <summary><span>{q}</span><ChevronDown size={16} /></summary>
      <div className="faq-body">{children}</div>
    </details>
  )
}

const KINDS: { kind: LightKind; form: LightForm; rgb: [number, number, number]; title: string; gets: string; note: string }[] = [
  { kind: 'rgb', form: 'cob', rgb: [0.62, 0.45, 1], title: 'RGB + white', gets: 'Every tab: white, colour, channels, gels, effects, sync.', note: 'Gels run natively where the light has a gel mode, and are recreated from their colour where it does not.' },
  { kind: 'bicolour', form: 'panel', rgb: [1, 0.8, 0.55], title: 'Bi-colour', gets: 'White, correction gels, every effect, music and screen sync.', note: 'Colour effects play as warmth: red glows warm, blue cool, and green or magenta use the tint control where the light has one.' },
  { kind: 'daylight', form: 'cob', rgb: [0.95, 0.96, 1], title: 'Daylight', gets: 'Brightness, fine dimming, effects that move brightness.', note: 'One fixed colour temperature, so colour and white tabs that would do nothing are hidden.' },
  { kind: 'colour', form: 'tube', rgb: [0.3, 0.85, 0.9], title: 'Colour only', gets: 'Colour, gels, effects and sync.', note: 'No white mode: whites are shown as the hue of that temperature.' },
]

/* ---------------------------------------------------------------- the guide */

export function GuideTab() {
  const models = useStudio((s) => s.models)
  const setAddLight = useStudio((s) => s.setAddLight)
  const setTab = useStudio((s) => s.setTab)
  const count = (kind: LightKind) => models.filter((m) => m.kind === kind).length

  return (
    <div className="guide">
      <section className="guide-hero">
        <div className="guide-hero-text">
          <p className="guide-kicker">Getting started</p>
          <h2>From a light in the box to a light in the studio, in three steps.</h2>
          <p className="muted">Gaffer talks to Godox lights over Bluetooth Mesh, the same way the Godox app does. A light can belong to one mesh at a time, so it is paired once, here, and from then on the studio finds it by itself.</p>
          <Key kind="primary" onClick={() => setAddLight(true)}><Plus /> Add a light</Key>
        </div>
        <div className="guide-steps">
          <Step n={1} title="Reset the light" art={<ResetArt />}>
            <p>Only needed if the light was ever used with the Godox app, Home Assistant or another computer. Open the light's own menu, go to its Bluetooth settings and choose reset. That is how the ML100R this studio was built with was paired.</p>
          </Step>
          <Step n={2} title="Let the studio find it" art={<FindArt />}>
            <p>Open <b>Add a light</b>. Within a few seconds the light shows under <b>Ready to pair</b>, with its model read from its own broadcast.</p>
          </Step>
          <Step n={3} title="Pair it" art={<PairArt />}>
            <p>Press <b>Pair</b> and keep the light close for about ten seconds. It joins your mesh, takes its control key, and the studio connects to it.</p>
          </Step>
        </div>
      </section>

      <div className="guide-cols">
        <section className="guide-card">
          <h3>Resetting, light by light</h3>
          <ul className="guide-list">
            <li><b>Lights with a screen</b> (monolights such as the SL, ML and MS series): the reset lives in the menu, under Bluetooth. After a reset the light forgets every phone and network it knew.</li>
            <li><b>Lights without a screen</b> (tubes, small panels): the reset is usually a long press on a button, and the light flashes to confirm. The exact button is in its manual.</li>
            <li><b>Still not listed after a reset?</b> Switch the light off and on again. A light that is connected to a phone stays silent until the phone app is closed.</li>
          </ul>
        </section>
        <section className="guide-card">
          <h3>Paired with something else already?</h3>
          <p className="muted">You do not have to reset it. If you paired it with the <code>godox-mesh</code> command line tool or another copy of this studio, its <code>mesh_state.json</code> keys file brings it in as it is:</p>
          <ol className="guide-list guide-list--num">
            <li>Open <b>Add a light</b> and find the light under <b>Paired with something else</b>.</li>
            <li>Press <b>Import keys</b> and choose the file.</li>
          </ol>
          <p className="muted">From a terminal: <code>python -m gaffer --import-keys mesh_state.json --address AA:BB:CC:DD:EE:FF</code>. Imported keys get a source address of their own, so the other tool can keep using them too.</p>
        </section>
      </div>

      <section className="guide-section">
        <h3 className="guide-h">What your light can do</h3>
        <p className="muted guide-sub">The catalogue has {models.length} Godox mesh models. The studio reads which one you have and shows only what it can do.</p>
        <div className="guide-kinds">
          {KINDS.map((k) => (
            <article key={k.kind} className="guide-kind">
              <LightGlyph form={k.form} rgb={k.rgb} level={0.8} size={54} />
              <div>
                <h4>{k.title} <span>{count(k.kind)} {count(k.kind) === 1 ? 'model' : 'models'}</span></h4>
                <p>{k.gets}</p>
                <p className="muted">{k.note}</p>
              </div>
            </article>
          ))}
        </div>
        <p className="hint">If a light does not say which model it is, or says the wrong one, pick it yourself: <b>Mesh</b> → <b>Your lights</b> → click its model.</p>
      </section>

      <section className="guide-cols">
        <div className="guide-card">
          <h3>More than one light</h3>
          <ul className="guide-list">
            <li>Every light you pair here joins one mesh network. The studio connects to one of them and that light relays commands to the rest, so lights out of this computer's range still answer.</li>
            <li>The light picker at the top of the sidebar decides which light every tab controls. <kbd>L</kbd> moves to the next light.</li>
            <li><b>Mesh</b> shows them all on a floor plan: drag them to where they stand, switch them on and off, and copy one look to the others.</li>
            <li><b>Sync groups</b> link lights: pick which lights and what they share (on/off, brightness, white, colour, effects). Change any one, and the rest follow.</li>
          </ul>
          <Key onClick={() => setTab('mesh')}>Open Mesh <ArrowRight /></Key>
        </div>
        <div className="guide-card">
          <h3>Keyboard</h3>
          <dl className="guide-keys">
            <div><dt><kbd>Space</kbd></dt><dd>Switch the light on or off</dd></div>
            <div><dt><kbd>[</kbd> <kbd>]</kbd></dt><dd>Brightness down or up 5% (with Shift, 1%)</dd></div>
            <div><dt><kbd>1</kbd> to <kbd>9</kbd></dt><dd>Recall a scene</dd></div>
            <div><dt><kbd>L</kbd></dt><dd>Next light (Shift: previous)</dd></div>
            <div><dt><kbd>Esc</kbd></dt><dd>Stop the running effect</dd></div>
            <div><dt><kbd>Ctrl</kbd> <kbd>K</kbd></dt><dd>Find anything</dd></div>
          </dl>
        </div>
      </section>

      <section className="guide-section">
        <h3 className="guide-h">When something is off</h3>
        <div className="faqs">
          <Faq q="The light does not show up when I scan" open>
            <ul className="guide-list">
              <li>Is it switched on, and within a few metres? Bluetooth Mesh reaches about as far as a phone speaker does.</li>
              <li>Is Bluetooth on for this computer? On Windows: Settings → Bluetooth &amp; devices.</li>
              <li>Close the Godox app on any phone nearby. A light holds one connection at a time.</li>
              <li>A light that was paired before shows under <b>Paired with something else</b>, not <b>Ready to pair</b>. Reset it, or import its keys.</li>
            </ul>
          </Faq>
          <Faq q="Pairing stopped halfway">
            <p>The light may have joined the network but not taken its control key. Keep it close and press <b>Try again</b>. If it then shows as paired elsewhere, reset it from its menu and pair once more: the reset clears any half-finished pairing.</p>
          </Faq>
          <Faq q="It connects, then keeps dropping">
            <ul className="guide-list">
              <li>Move the computer closer, or the light: the studio sends up to 40 updates a second during effects and needs a steady signal. The signal strength is in <b>Device</b>.</li>
              <li>Lower the command rate in <b>Device</b> → Speed if the light is far away.</li>
              <li>With several lights, the studio connects through the one it hears best and relays to the rest, so one light out of range does not cut off the others.</li>
            </ul>
          </Faq>
          <Faq q="Another light on the mesh does not respond">
            <p>Other lights are reached by relay through the connected one. Make sure each light is within reach of at least one other. In <b>Device</b>, raising the relay hops helps lights that are far apart. A light shown as <b>Not answering</b> has missed its heartbeat for over half a minute: check that it is on.</p>
          </Faq>
          <Faq q="A gel or a built-in effect does nothing">
            <p>Some models, the ML100R among them, have a gel mode on their own panel but not over Bluetooth. The studio recreates gels from their real colour on those lights, and says so in the Gels tab. Built-in effect settings marked <i>inferred</i> have ranges guessed from the Godox app's defaults; the light ignores values it does not accept.</p>
          </Faq>
          <Faq q="Changes I make on the light itself do not show in the studio">
            <p>The studio asks the light what it is doing a few times a second while a page is open (<b>Device</b> → Watch for changes). Colour temperature and colour are read back; gels and effects started on the light's panel cannot be read over Bluetooth.</p>
          </Faq>
          <Faq q="Screen sync colours do not match the screen">
            <p>In <b>Sync</b>, set the zone to the part of the screen the light should follow, and turn on <b>Use true white for neutral scenes</b> so pale scenes give a clean white instead of a tinted one. On a bi-colour light the screen's colour becomes warmth, which is the nearest it can do.</p>
          </Faq>
          <Faq q="The page says the studio is offline">
            <p>The page is served by Gaffer on this computer. Open Gaffer again from the Applications folder; the page reconnects by itself. Quitting Gaffer frees the lights for other apps.</p>
          </Faq>
          <Faq q="Can I use it from my phone?">
            <p>Phone access with a PIN is not in this version yet. The Bluetooth stays on this computer; a phone would only drive the page.</p>
          </Faq>
        </div>
      </section>

      <footer className="guide-credits">
        <p>
          Gaffer builds on <a href="https://github.com/Rkcr7/lumen-studio" target="_blank" rel="noreferrer">lumen-studio</a> by Ritik (Rkcr7), which in turn builds on <a href="https://github.com/mattharrison/godox-ul60bi-bt" target="_blank" rel="noreferrer">godox-ul60bi-bt</a> by
          Matt Harrison, the library that first spoke this protocol, and Simon Cheng's <a href="https://github.com/binary-person/ha-godox-mesh" target="_blank" rel="noreferrer">ha-godox-mesh</a>,
          which extended it to the whole Godox range. Not affiliated with Godox.
        </p>
      </footer>
    </div>
  )
}
