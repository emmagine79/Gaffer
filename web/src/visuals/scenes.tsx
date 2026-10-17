import type { ReactElement } from 'react'

/**
 * Subjects for the studio set, drawn in their true surface colours (albedo).
 * The set multiplies them by the light's colour, so a red book under blue
 * light goes near-black, exactly as it would on a real set.
 *
 * Coordinates are in the set's 1000 x 600 frame. `focus` is where the key
 * light lands; `beamTo` is the half-height of the beam at the subject.
 */
export interface Subject {
  id: string
  name: string
  focus: { x: number; y: number; rx: number; ry: number }
  beamTo: number
  draw: () => ReactElement
}

function rng(seed: number) {
  return () => {
    seed |= 0
    seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const BOOK_COLORS = ['#7a2e2a', '#2c3e63', '#b88a2c', '#2f5a43', '#d8cdb5', '#5e5e62', '#2d6b6e', '#5b2340', '#1f2024', '#9c5b2e', '#e3dccb', '#40507a']

function Bookshelf() {
  const r = rng(11)
  const shelves = [176, 262, 348, 434]
  const left = 520
  const right = 900
  const books: ReactElement[] = []
  shelves.forEach((floor, s) => {
    let x = left + 10
    let n = 0
    while (x < right - 30) {
      if (s === 0 && x > 760) break // room for the plant
      if (s === 2 && n === 5) {
        x += 70 // a gap with a lying stack
        books.push(
          <g key={`stack${s}`}>
            <rect x={x - 66} y={floor - 14} width="60" height="13" rx="1.5" fill="#d8cdb5" />
            <rect x={x - 62} y={floor - 26} width="54" height="12" rx="1.5" fill="#2c3e63" />
            <rect x={x - 64} y={floor - 37} width="57" height="11" rx="1.5" fill="#7a2e2a" />
          </g>,
        )
      }
      const w = 11 + Math.floor(r() * 16)
      const h = 50 + Math.floor(r() * 26)
      const color = BOOK_COLORS[Math.floor(r() * BOOK_COLORS.length)]
      const lean = n === 7 && s === 1 ? -9 : 0
      books.push(
        <g key={`${s}-${n}`} transform={lean ? `rotate(${lean} ${x + w} ${floor})` : undefined}>
          <rect x={x} y={floor - h} width={w} height={h} rx="1.5" fill={color} />
          <rect x={x + 2} y={floor - h + 9} width={w - 4} height="5" fill="rgb(255 255 255 / 0.22)" />
          <rect x={x + 2} y={floor - 16} width={w - 4} height="3" fill="rgb(0 0 0 / 0.25)" />
          <rect x={x + w - 2} y={floor - h} width="2" height={h} fill="rgb(0 0 0 / 0.18)" />
        </g>,
      )
      x += w + 1 + (r() < 0.12 ? 6 : 0)
      n++
    }
  })
  return (
    <g>
      <rect x="506" y="86" width="408" height="380" rx="4" fill="#6b4b33" />
      <rect x="518" y="96" width="384" height="360" fill="#3a2a1e" />
      {shelves.map((y) => <rect key={y} x="512" y={y} width="396" height="10" fill="#7d5a3e" />)}
      {books}
      {/* plant */}
      <path d="M790 176 L 798 136 L 846 136 L 854 176 Z" fill="#c9653b" />
      <rect x="794" y="132" width="56" height="8" rx="2" fill="#a9512d" />
      {[[-34, -60], [-14, -76], [6, -82], [26, -70], [42, -50], [-44, -36], [18, -52]].map(([dx, dy], i) => (
        <ellipse key={i} cx={822 + dx} cy={132 + dy} rx="11" ry="24" fill={i % 2 ? '#3f7d4a' : '#2f6a3b'}
          transform={`rotate(${dx * 0.9} ${822 + dx} ${132 + dy})`} />
      ))}
      {/* framed print leaning on the top */}
      <rect x="560" y="18" width="92" height="70" rx="2" fill="#1d1e21" transform="rotate(-4 606 88)" />
      <rect x="568" y="26" width="76" height="54" fill="#e9e3d5" transform="rotate(-4 606 88)" />
      <circle cx="606" cy="52" r="13" fill="#d06a3d" transform="rotate(-4 606 88)" />
      {/* armchair edge in the foreground */}
      <path d="M330 600 L 330 470 Q 330 420 380 420 L 470 420 Q 500 420 500 450 L 500 600 Z" fill="#8a3b34" />
      <path d="M318 600 L 318 500 Q 318 470 350 470 L 520 470 Q 540 470 540 500 L 540 600 Z" fill="#9c463e" />
    </g>
  )
}

function Portrait() {
  return (
    <g>
      {/* shoulders, a knit sweater */}
      <path d="M520 600 C 525 500, 580 455, 650 446 L 760 446 C 830 455, 885 500, 890 600 Z" fill="#c9c4b8" />
      <path d="M560 600 C 565 540, 600 505, 640 498" stroke="#b3ad9f" strokeWidth="6" fill="none" />
      <path d="M850 600 C 845 540, 810 505, 770 498" stroke="#b3ad9f" strokeWidth="6" fill="none" />
      {/* neck */}
      <path d="M672 452 L 676 386 L 738 386 L 742 452 C 724 470, 690 470, 672 452 Z" fill="#b8866a" />
      {/* head */}
      <ellipse cx="706" cy="300" rx="84" ry="104" fill="#c9987a" />
      <ellipse cx="624" cy="312" rx="14" ry="24" fill="#bb876b" />
      <ellipse cx="788" cy="312" rx="14" ry="24" fill="#bb876b" />
      {/* hair */}
      <path d="M618 290 C 606 190, 680 160, 724 168 C 790 176, 812 230, 796 296 C 786 250, 760 222, 712 220 C 670 220, 640 240, 618 290 Z" fill="#2a211c" />
      {/* features, quiet */}
      <path d="M664 296 q 14 -8 28 0" stroke="#3a2b23" strokeWidth="4" fill="none" strokeLinecap="round" />
      <path d="M722 296 q 14 -8 28 0" stroke="#3a2b23" strokeWidth="4" fill="none" strokeLinecap="round" />
      <path d="M706 300 L 698 344 Q 706 350 716 344" stroke="#a7745a" strokeWidth="4" fill="none" strokeLinecap="round" />
      <path d="M684 372 Q 706 384 730 372" stroke="#9a5a4a" strokeWidth="5" fill="none" strokeLinecap="round" />
    </g>
  )
}

function Product() {
  return (
    <g>
      {/* plinth */}
      <ellipse cx="710" cy="470" rx="150" ry="26" fill="#bdb7ab" />
      <rect x="560" y="470" width="300" height="130" fill="#d6d0c4" />
      <ellipse cx="710" cy="470" rx="150" ry="26" fill="#e8e3d8" />
      {/* box */}
      <rect x="760" y="340" width="86" height="130" fill="#20242c" />
      <rect x="846" y="352" width="14" height="118" fill="#151820" />
      <rect x="772" y="380" width="62" height="2" fill="#c8a75a" />
      {/* bottle */}
      <rect x="610" y="300" width="128" height="170" rx="16" fill="#e7e2d6" opacity="0.85" />
      <rect x="622" y="312" width="104" height="146" rx="10" fill="#d9a441" opacity="0.75" />
      <rect x="652" y="262" width="44" height="40" rx="4" fill="#1d1e21" />
      <rect x="664" y="248" width="20" height="16" rx="3" fill="#c8a75a" />
      <rect x="632" y="370" width="84" height="40" rx="2" fill="#f4efe4" />
      <rect x="644" y="384" width="60" height="4" fill="#3a3b40" />
      <rect x="652" y="394" width="44" height="3" fill="#8a8b90" />
      <path d="M624 318 L 624 450" stroke="#ffffff" strokeWidth="5" strokeLinecap="round" opacity="0.7" />
    </g>
  )
}

function Desk() {
  return (
    <g>
      {/* desk */}
      <rect x="430" y="430" width="530" height="18" fill="#8c6a4a" />
      <rect x="452" y="448" width="14" height="152" fill="#5e4632" />
      <rect x="926" y="448" width="14" height="152" fill="#5e4632" />
      {/* monitor */}
      <rect x="560" y="228" width="300" height="176" rx="8" fill="#16171a" />
      <rect x="572" y="240" width="276" height="152" rx="3" fill="#2a3a52" />
      <rect x="690" y="404" width="40" height="22" fill="#25262a" />
      <rect x="652" y="424" width="116" height="8" rx="3" fill="#25262a" />
      {/* keyboard, mug, notebook */}
      <rect x="610" y="416" width="200" height="14" rx="3" fill="#e1ddd4" transform="translate(0 0)" />
      <rect x="880" y="380" width="44" height="50" rx="6" fill="#d0583f" />
      <path d="M924 392 q 18 2 18 16 q 0 14 -18 14" stroke="#d0583f" strokeWidth="7" fill="none" />
      <rect x="470" y="414" width="96" height="16" rx="2" fill="#2f5a43" transform="rotate(-3 518 422)" />
      {/* poster */}
      <rect x="470" y="70" width="140" height="190" fill="#e9e2d2" />
      <circle cx="540" cy="140" r="40" fill="#e0703f" />
      <rect x="490" y="200" width="100" height="8" fill="#2c3e63" />
      <rect x="490" y="216" width="70" height="6" fill="#7c7f86" />
    </g>
  )
}

export const SUBJECTS: Subject[] = [
  { id: 'bookshelf', name: 'Bookshelf', focus: { x: 690, y: 290, rx: 330, ry: 300 }, beamTo: 230, draw: Bookshelf },
  { id: 'portrait', name: 'Portrait', focus: { x: 680, y: 330, rx: 260, ry: 300 }, beamTo: 190, draw: Portrait },
  { id: 'product', name: 'Product', focus: { x: 700, y: 390, rx: 260, ry: 230 }, beamTo: 170, draw: Product },
  { id: 'desk', name: 'Desk', focus: { x: 690, y: 320, rx: 320, ry: 280 }, beamTo: 220, draw: Desk },
]
