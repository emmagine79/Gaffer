// Draws Gaffer's marks: the 1024 px app icon (a Fresnel monolight on a dark glass tile) and
// the favicon SVG. One geometry, copied from web/src/glass/Lamp.tsx (viewBox 400 x 100).
// Usage: make_icon <output.png>        the app icon
//        make_icon --svg <output.svg>  the favicon, 64 x 64
import AppKit

// MARK GEOMETRY (Lamp.tsx units). mac/Sources/GafferMark.swift repeats the head numbers;
// mac/tests/test_shell.py fails if the two blocks drift apart.
let bodyRect = CGRect(x: 70, y: 27, width: 70, height: 46)
let bodyRadius: CGFloat = 8
let ribXs: [CGFloat] = [80, 90, 120, 130]          // gaps cut through the body
let ribWidth: CGFloat = 4
let cone: [CGPoint] = [CGPoint(x: 140, y: 33), CGPoint(x: 166, y: 23), CGPoint(x: 166, y: 77), CGPoint(x: 140, y: 67)]
let standX: CGFloat = 105, standTop: CGFloat = 73, standBottom: CGFloat = 112   // Lamp.tsx stops at 87; the mark's stand is a full stand
let footHalf: CGFloat = 30
let beamPath: [CGPoint] = [CGPoint(x: 166, y: 30), CGPoint(x: 400, y: -45), CGPoint(x: 400, y: 145), CGPoint(x: 166, y: 70)]
// END MARK GEOMETRY

// Colours (design tokens: chalk, and the panel's beam start).
let chalk = CGColor(red: 0xF3 / 255, green: 0xEE / 255, blue: 0xE6 / 255, alpha: 1)
let beamStart = CGColor(red: 0xFF / 255, green: 0xEF / 255, blue: 0xE1 / 255, alpha: 0.95)
let beamEnd = CGColor(red: 0xFF / 255, green: 0xEF / 255, blue: 0xE1 / 255, alpha: 0)

// Placement on the 1024 canvas: scale s puts the body at about 45 % of the tile width.
let canvas: CGFloat = 1024
let s: CGFloat = 5.4
let originX: CGFloat = 170     // canvas x of lamp x = 70
let originY: CGFloat = 262     // canvas y (from the top) of lamp y = 23
let standWidth: CGFloat = 10   // lamp units: 10 x 5.4 = 54 px, 6.6 % of the 824 px tile

func px(_ p: CGPoint) -> CGPoint { CGPoint(x: originX + (p.x - 70) * s, y: originY + (p.y - 23) * s) }

// The head as one silhouette: body, ribs cut out, then the cone.
func headPath(flipY: Bool) -> CGPath {
    func q(_ p: CGPoint) -> CGPoint { let c = px(p); return CGPoint(x: c.x, y: flipY ? canvas - c.y : c.y) }
    let path = CGMutablePath()
    let a = q(CGPoint(x: bodyRect.minX, y: bodyRect.minY)), b = q(CGPoint(x: bodyRect.maxX, y: bodyRect.maxY))
    path.addRoundedRect(in: CGRect(x: min(a.x, b.x), y: min(a.y, b.y), width: abs(b.x - a.x), height: abs(b.y - a.y)),
                        cornerWidth: bodyRadius * s, cornerHeight: bodyRadius * s)
    for x in ribXs {
        let r0 = q(CGPoint(x: x - ribWidth / 2, y: bodyRect.minY)), r1 = q(CGPoint(x: x + ribWidth / 2, y: bodyRect.maxY))
        path.addRect(CGRect(x: min(r0.x, r1.x), y: min(r0.y, r1.y), width: abs(r1.x - r0.x), height: abs(r1.y - r0.y)))
    }
    return path
}

let svgMode = CommandLine.arguments.count > 2 && CommandLine.arguments[1] == "--svg"
if svgMode {
    // The favicon: the same drawing in a 64 unit box, tile 6..58 like Apple's grid (824 of 1024).
    func f(_ v: CGFloat) -> String { String(format: "%.2f", v).replacingOccurrences(of: #"\.?0+$"#, with: "", options: .regularExpression) }
    func pt(_ p: CGPoint) -> String { let c = px(p); return "\(f(c.x)) \(f(c.y))" }
    var d = ""
    let rx = bodyRect
    let r = bodyRadius, x0 = rx.minX, y0 = rx.minY, x1 = rx.maxX, y1 = rx.maxY
    func rounded() -> String {
        func a(_ x: CGFloat, _ y: CGFloat) -> String { pt(CGPoint(x: x, y: y)) }
        return "M\(a(x0 + r, y0)) L\(a(x1 - r, y0)) Q\(a(x1, y0)) \(a(x1, y0 + r)) L\(a(x1, y1 - r)) Q\(a(x1, y1)) \(a(x1 - r, y1)) L\(a(x0 + r, y1)) Q\(a(x0, y1)) \(a(x0, y1 - r)) L\(a(x0, y0 + r)) Q\(a(x0, y0)) \(a(x0 + r, y0))Z"
    }
    d += rounded()
    for x in ribXs {
        d += "M\(pt(CGPoint(x: x - ribWidth / 2, y: y0))) L\(pt(CGPoint(x: x + ribWidth / 2, y: y0))) L\(pt(CGPoint(x: x + ribWidth / 2, y: y1))) L\(pt(CGPoint(x: x - ribWidth / 2, y: y1)))Z"
    }
    let conePts = cone.map(pt).joined(separator: " L")
    let beamPts = beamPath.map(pt).joined(separator: " L")
    let svg = """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
      <defs>
        <linearGradient id="t" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#292624"/>
          <stop offset="1" stop-color="#0f0f0f"/>
        </linearGradient>
        <linearGradient id="b" gradientUnits="userSpaceOnUse" x1="\(pt(CGPoint(x: 166, y: 50)))" x2="\(pt(CGPoint(x: 215, y: 50)))">
          <stop offset="0" stop-color="#FFEFE1" stop-opacity=".95"/>
          <stop offset="1" stop-color="#FFEFE1" stop-opacity="0"/>
        </linearGradient>
        <clipPath id="c"><rect x="100" y="100" width="824" height="824" rx="185"/></clipPath>
      </defs>
      <g transform="scale(.0625)">
        <rect x="100" y="100" width="824" height="824" rx="185" fill="url(#t)"/>
        <g clip-path="url(#c)">
          <path d="M\(beamPts)Z" fill="url(#b)"/>
        </g>
        <g fill="#F3EEE6">
          <path d="\(d)" fill-rule="evenodd"/>
          <path d="M\(conePts)Z"/>
          <path d="M\(pt(CGPoint(x: standX, y: standTop))) V\(f(px(CGPoint(x: 0, y: standBottom)).y))" stroke="#F3EEE6" stroke-width="\(f(standWidth * s))" fill="none"/>
          <path d="M\(pt(CGPoint(x: standX - footHalf, y: standBottom))) H\(f(px(CGPoint(x: standX + footHalf, y: 0)).x))" stroke="#F3EEE6" stroke-width="\(f(standWidth * s))" stroke-linecap="round" fill="none"/>
        </g>
      </g>
    </svg>

    """
    try! svg.write(toFile: CommandLine.arguments[2], atomically: true, encoding: .utf8)
    exit(0)
}

let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "icon.png"
let rep = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: Int(canvas), pixelsHigh: Int(canvas),
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let ctx = NSGraphicsContext.current!.cgContext

// Tile: Apple's icon grid keeps 100 px of margin on a 1024 canvas.
let tile = CGRect(x: 100, y: 100, width: 824, height: 824)
ctx.saveGState()
ctx.addPath(CGPath(roundedRect: tile, cornerWidth: 185, cornerHeight: 185, transform: nil))
ctx.clip()
let bg = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: [
    CGColor(red: 0.16, green: 0.15, blue: 0.14, alpha: 1),
    CGColor(red: 0.06, green: 0.06, blue: 0.06, alpha: 1),
] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(bg, start: CGPoint(x: 0, y: tile.maxY), end: CGPoint(x: 0, y: tile.minY), options: [])

// Beam: Lamp.tsx's cone, from the lens, warm at the lens and clear at the far end.
let beam = CGMutablePath()
for (i, p) in beamPath.enumerated() {
    let c = px(p), y = canvas - c.y
    if i == 0 { beam.move(to: CGPoint(x: c.x, y: y)) } else { beam.addLine(to: CGPoint(x: c.x, y: y)) }
}
beam.closeSubpath()
ctx.saveGState()
ctx.addPath(beam)
ctx.clip()
let warm = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: [beamStart, beamEnd] as CFArray, locations: [0, 1])!
let g0 = px(CGPoint(x: 166, y: 50)), g1 = px(CGPoint(x: 215, y: 50))
ctx.drawLinearGradient(warm, start: CGPoint(x: g0.x, y: canvas - g0.y), end: CGPoint(x: g1.x, y: canvas - g1.y), options: [])
ctx.restoreGState()
ctx.restoreGState()

// Head, stand and foot in chalk.
ctx.setFillColor(chalk)
ctx.addPath(headPath(flipY: true))
ctx.drawPath(using: .eoFill)
let coneCG = CGMutablePath()
for (i, p) in cone.enumerated() {
    let c = px(p), y = canvas - c.y
    if i == 0 { coneCG.move(to: CGPoint(x: c.x, y: y)) } else { coneCG.addLine(to: CGPoint(x: c.x, y: y)) }
}
coneCG.closeSubpath()
ctx.addPath(coneCG)
ctx.fillPath()
ctx.setStrokeColor(chalk)
ctx.setLineWidth(standWidth * s)
ctx.setLineCap(.butt)
let sTop = px(CGPoint(x: standX, y: standTop)), sBot = px(CGPoint(x: standX, y: standBottom))
ctx.move(to: CGPoint(x: sTop.x, y: canvas - sTop.y))
ctx.addLine(to: CGPoint(x: sBot.x, y: canvas - sBot.y))
ctx.strokePath()
ctx.setLineCap(.round)
let fl = px(CGPoint(x: standX - footHalf, y: standBottom)), fr = px(CGPoint(x: standX + footHalf, y: standBottom))
ctx.move(to: CGPoint(x: fl.x, y: canvas - fl.y))
ctx.addLine(to: CGPoint(x: fr.x, y: canvas - fr.y))
ctx.strokePath()

NSGraphicsContext.restoreGraphicsState()
try! rep.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: out))
