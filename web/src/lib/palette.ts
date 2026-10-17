import { rgbToHex, rgbToHsv, type RGB } from './color'

/**
 * The dominant colours of an image: downsample to 64 px, drop near-black and
 * near-grey pixels (they make dull light), then k-means. Sorted by how much
 * of the image each colour covers.
 */
export async function extractPalette(file: Blob, k = 6): Promise<string[]> {
  const bitmap = await createImageBitmap(file)
  const scale = 64 / Math.max(bitmap.width, bitmap.height)
  const w = Math.max(1, Math.round(bitmap.width * scale))
  const h = Math.max(1, Math.round(bitmap.height * scale))
  const canvas = new OffscreenCanvas(w, h)
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('This browser cannot read images')
  ctx.drawImage(bitmap, 0, 0, w, h)
  const data = ctx.getImageData(0, 0, w, h).data

  const pixels: RGB[] = []
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 128) continue
    const p: RGB = [data[i] / 255, data[i + 1] / 255, data[i + 2] / 255]
    const [, s, v] = rgbToHsv(p)
    if (v > 12 && s > 12) pixels.push(p)
  }
  if (pixels.length < k) return []
  return kmeans(pixels, k).map(rgbToHex)
}

function kmeans(points: RGB[], k: number): RGB[] {
  // k-means++ seeding for stable, distinct clusters
  const centers: RGB[] = [points[Math.floor(points.length / 2)]]
  while (centers.length < k) {
    const d = points.map((p) => Math.min(...centers.map((c) => dist(p, c))))
    const total = d.reduce((a, b) => a + b, 0)
    let r = Math.random() * total
    let idx = 0
    while (r > d[idx] && idx < d.length - 1) r -= d[idx++]
    centers.push(points[idx])
  }
  let counts = new Array(k).fill(0)
  for (let iter = 0; iter < 12; iter++) {
    const sums = centers.map(() => [0, 0, 0])
    counts = new Array(k).fill(0)
    for (const p of points) {
      let best = 0
      let bestD = Infinity
      for (let c = 0; c < k; c++) {
        const dd = dist(p, centers[c])
        if (dd < bestD) { bestD = dd; best = c }
      }
      sums[best][0] += p[0]; sums[best][1] += p[1]; sums[best][2] += p[2]
      counts[best]++
    }
    for (let c = 0; c < k; c++) {
      if (counts[c]) centers[c] = [sums[c][0] / counts[c], sums[c][1] / counts[c], sums[c][2] / counts[c]]
    }
  }
  return centers.map((c, i) => ({ c, n: counts[i] })).filter((x) => x.n > 0).sort((a, b) => b.n - a.n).map((x) => x.c)
}

const dist = (a: RGB, b: RGB) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2

/** The average colour of each vertical strip, left to right: a picture as a timeline. */
export async function extractColumns(file: Blob, strips = 32): Promise<string[]> {
  const bitmap = await createImageBitmap(file)
  const h = 24
  const canvas = new OffscreenCanvas(strips, h)
  const ctx = canvas.getContext('2d')
  if (!ctx) throw new Error('This browser cannot read images')
  ctx.drawImage(bitmap, 0, 0, strips, h)
  const data = ctx.getImageData(0, 0, strips, h).data
  const out: string[] = []
  for (let x = 0; x < strips; x++) {
    let r = 0, g = 0, b = 0
    for (let y = 0; y < h; y++) {
      const i = (y * strips + x) * 4
      r += data[i]; g += data[i + 1]; b += data[i + 2]
    }
    out.push(rgbToHex([r / h / 255, g / h / 255, b / h / 255]))
  }
  return out
}
