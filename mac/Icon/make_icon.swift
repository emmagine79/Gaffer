// Draws Gaffer's 1024 px app icon: a studio light on a dark glass tile, throwing a warm beam.
// Usage: make_icon <output.png>
import AppKit

let size: CGFloat = 1024
let out = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "icon.png"

let rep = NSBitmapImageRep(
    bitmapDataPlanes: nil, pixelsWide: Int(size), pixelsHigh: Int(size),
    bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
    colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
let ctx = NSGraphicsContext.current!.cgContext

// Tile: Apple's icon grid keeps about 100 px of margin on a 1024 canvas.
let tile = CGRect(x: 100, y: 100, width: 824, height: 824)
let tilePath = CGPath(roundedRect: tile, cornerWidth: 185, cornerHeight: 185, transform: nil)
ctx.addPath(tilePath)
ctx.clip()
let bg = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: [
    CGColor(red: 0.16, green: 0.15, blue: 0.14, alpha: 1),
    CGColor(red: 0.06, green: 0.06, blue: 0.06, alpha: 1),
] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(bg, start: CGPoint(x: 0, y: tile.maxY), end: CGPoint(x: 0, y: tile.minY), options: [])

// Beam: a warm cone from the light head down to the right.
let beam = CGMutablePath()
beam.move(to: CGPoint(x: 400, y: 640))
beam.addLine(to: CGPoint(x: 930, y: 330))
beam.addLine(to: CGPoint(x: 930, y: 60))
beam.addLine(to: CGPoint(x: 360, y: 560))
beam.closeSubpath()
ctx.saveGState()
ctx.addPath(beam)
ctx.clip()
let warm = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: [
    CGColor(red: 1.0, green: 0.78, blue: 0.42, alpha: 0.85),
    CGColor(red: 1.0, green: 0.66, blue: 0.25, alpha: 0.0),
] as CFArray, locations: [0, 1])!
ctx.drawLinearGradient(warm, start: CGPoint(x: 380, y: 600), end: CGPoint(x: 900, y: 200), options: [])
ctx.restoreGState()

// Light head: a rounded body tilted toward the beam, with a bright lens.
ctx.saveGState()
ctx.translateBy(x: 330, y: 640)
ctx.rotate(by: -0.52)
let body = CGPath(roundedRect: CGRect(x: -120, y: -90, width: 220, height: 180), cornerWidth: 40, cornerHeight: 40, transform: nil)
ctx.addPath(body)
ctx.setFillColor(CGColor(red: 0.85, green: 0.84, blue: 0.82, alpha: 1))
ctx.fillPath()
let lens = CGRect(x: 60, y: -80, width: 70, height: 160)
ctx.addPath(CGPath(roundedRect: lens, cornerWidth: 30, cornerHeight: 30, transform: nil))
ctx.setFillColor(CGColor(red: 1.0, green: 0.86, blue: 0.55, alpha: 1))
ctx.fillPath()
ctx.restoreGState()

// Stand: a thin pole and a foot.
ctx.setStrokeColor(CGColor(red: 0.85, green: 0.84, blue: 0.82, alpha: 1))
ctx.setLineWidth(26)
ctx.setLineCap(.round)
ctx.move(to: CGPoint(x: 300, y: 560))
ctx.addLine(to: CGPoint(x: 300, y: 230))
ctx.move(to: CGPoint(x: 200, y: 210))
ctx.addLine(to: CGPoint(x: 400, y: 210))
ctx.strokePath()

NSGraphicsContext.restoreGraphicsState()
let png = rep.representation(using: .png, properties: [:])!
try! png.write(to: URL(fileURLWithPath: out))
