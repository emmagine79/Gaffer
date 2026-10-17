import AppKit

// The menu-bar mark: the Fresnel monolight from web/src/glass/Lamp.tsx as a template image,
// drawn in code (no asset catalog). Black on clear, so macOS tints it for light and dark bars
// and for the selected state. Head and cone are one filled silhouette; two short beam strokes;
// no stand, because a 1 pt stand vanishes at 16 px.
//
// The numbers repeat the head block in mac/Icon/make_icon.swift (Lamp.tsx units).
enum GafferMark {
    // MARK GEOMETRY
    static let bodyRect = CGRect(x: 70, y: 27, width: 70, height: 46)
    static let bodyRadius: CGFloat = 8
    static let cone: [CGPoint] = [CGPoint(x: 140, y: 33), CGPoint(x: 166, y: 23), CGPoint(x: 166, y: 77), CGPoint(x: 140, y: 67)]
    // END MARK GEOMETRY

    /// 18 x 18 pt canvas. Lamp units map to points by `scale`, with the head's left edge 1 pt in.
    static func menuBarImage() -> NSImage {
        let scale: CGFloat = 0.12
        let image = NSImage(size: NSSize(width: 18, height: 18), flipped: true) { _ in
            func pt(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: 1 + (x - 70) * scale, y: 9 + (y - 50) * scale) }
            let path = NSBezierPath()
            let a = pt(bodyRect.minX, bodyRect.minY), b = pt(bodyRect.maxX, bodyRect.maxY)
            path.append(NSBezierPath(roundedRect: NSRect(x: a.x, y: a.y, width: b.x - a.x, height: b.y - a.y),
                                     xRadius: bodyRadius * scale, yRadius: bodyRadius * scale))
            // One rib gap, 1.5 pt wide, so the body still reads as a ribbed cylinder.
            let r0 = pt(90, bodyRect.minY), r1 = pt(90, bodyRect.maxY)
            path.append(NSBezierPath(rect: NSRect(x: r0.x - 0.75, y: r0.y, width: 1.5, height: r1.y - r0.y)))
            path.windingRule = .evenOdd
            NSColor.black.setFill()
            path.fill()
            let conePath = NSBezierPath()
            conePath.move(to: pt(cone[0].x, cone[0].y))
            for p in cone.dropFirst() { conePath.line(to: pt(p.x, p.y)) }
            conePath.close()
            conePath.fill()
            NSColor.black.setStroke()
            for (y0, y1) in [(35.0, 25.0), (65.0, 75.0)] {
                let beam = NSBezierPath()
                beam.lineWidth = 1.5
                beam.lineCapStyle = .round
                beam.move(to: pt(180, CGFloat(y0)))
                beam.line(to: pt(206, CGFloat(y1)))
                beam.stroke()
            }
            return true
        }
        image.isTemplate = true
        image.accessibilityDescription = "Gaffer"
        return image
    }
}
