// Compiled by test_shell.py together with mac/Sources/GafferMark.swift (as main.swift here).
// Prints "<isTemplate> <width>x<height> <opaque pixel count>" for the menu-bar mark.
import AppKit

let image = GafferMark.menuBarImage()
let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: 18, pixelsHigh: 18, bitsPerSample: 8, samplesPerPixel: 4,
                           hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
image.draw(in: NSRect(x: 0, y: 0, width: 18, height: 18))
NSGraphicsContext.restoreGraphicsState()
var inked = 0
for y in 0..<18 { for x in 0..<18 where (rep.colorAt(x: x, y: y)?.alphaComponent ?? 0) > 0.5 { inked += 1 } }
print(image.isTemplate, "\(Int(image.size.width))x\(Int(image.size.height))", inked > 20 ? "drawn" : "blank")
