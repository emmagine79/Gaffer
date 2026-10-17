#!/usr/bin/env bash
# Draws every Gaffer mark and writes one contact sheet for review:
#   the app icon at 1024, 512, 128, 32 and 16 px (the same sips downsample build_app.sh uses),
#   the menu-bar mark on light and dark strips at 1x and 2x,
#   the favicon at 16, 32 and 64 px.
# Deterministic: same sources, same PNG. Prints the sheet's path as its last line.
# Usage: mac/Icon/preview.sh [output-folder]    (default: a new folder under $TMPDIR)
#        GAFFER_FAVICON_OUT=web/public/favicon.svg  also writes the favicon from the icon's geometry
#        GAFFER_DOC_OUT=docs/install/08-menu-bar.png  also writes the install-guide menu-bar picture
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${1:-$(mktemp -d "${TMPDIR:-/tmp}/gaffer-icon-preview.XXXXXX")}"
mkdir -p "$OUT"
TARGET="arm64-apple-macos14.0"

swiftc -O -target "$TARGET" "$ROOT/mac/Icon/make_icon.swift" -o "$OUT/make_icon"
"$OUT/make_icon" "$OUT/icon-1024.png"
"$OUT/make_icon" --svg "$OUT/favicon.svg"
for s in 512 128 32 16; do
    sips -z "$s" "$s" "$OUT/icon-1024.png" --out "$OUT/icon-$s.png" >/dev/null
done

mkdir -p "$OUT/sheet"
cat > "$OUT/sheet/main.swift" <<'SWIFT'
import AppKit

let a = CommandLine.arguments
let dir = a[1], docOut = a.count > 2 ? a[2] : ""

func bitmap(_ w: Int, _ h: Int, _ draw: () -> Void) -> NSBitmapImageRep {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: w, pixelsHigh: h, bitsPerSample: 8, samplesPerPixel: 4,
                               hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    NSColor.clear.setFill()
    NSRect(x: 0, y: 0, width: w, height: h).fill(using: .copy)
    draw()
    NSGraphicsContext.restoreGraphicsState()
    return rep
}
func hex(_ v: Int) -> NSColor { NSColor(red: CGFloat(v >> 16 & 255) / 255, green: CGFloat(v >> 8 & 255) / 255, blue: CGFloat(v & 255) / 255, alpha: 1) }
func label(_ s: String, _ x: CGFloat, _ y: CGFloat, color: NSColor = hex(0x333333), size: CGFloat = 20) {
    (s as NSString).draw(at: NSPoint(x: x, y: y), withAttributes: [.font: NSFont.systemFont(ofSize: size), .foregroundColor: color])
}
func load(_ n: String) -> NSImage { NSImage(contentsOfFile: "\(dir)/\(n)")! }

/// The template mark drawn the way macOS tints it: black on clear becomes the bar's ink.
func tinted(_ scale: Int, ink: NSColor) -> NSImage {
    let mark = GafferMark.menuBarImage()
    precondition(mark.isTemplate)
    let side = CGFloat(18 * scale)
    return NSImage(size: NSSize(width: side, height: side), flipped: false) { r in
        mark.draw(in: r)
        ink.setFill()
        r.fill(using: .sourceAtop)
        return true
    }
}
func strip(_ x: CGFloat, _ y: CGFloat, _ w: CGFloat, dark: Bool, name: String) {
    (dark ? hex(0x262626) : hex(0xE9E9E9)).setFill()
    NSRect(x: x, y: y, width: w, height: 40).fill()
    let ink = dark ? NSColor.white : NSColor.black
    // 1x is 18 px for 18 pt; 2x is 36 px for the same 18 pt, shown at its own pixel size.
    tinted(1, ink: ink).draw(in: NSRect(x: x + 14, y: y + 11, width: 18, height: 18))
    label(name, x + 40, y + 12, color: ink, size: 13)
    tinted(2, ink: ink).draw(in: NSRect(x: x + 140, y: y + 2, width: 36, height: 36))
    label("1x, 2x", x + 190, y + 12, color: ink, size: 13)
}

let faviconSVG = NSImage(contentsOfFile: "\(dir)/favicon.svg")!
func favicon(_ px: Int, at p: NSPoint) {
    NSGraphicsContext.current?.imageInterpolation = .high
    faviconSVG.draw(in: NSRect(x: p.x, y: p.y, width: CGFloat(px), height: CGFloat(px)))
}

let W = 1640, H = 1260
let sheet = bitmap(W, H) {
    hex(0xBEBEBE).setFill()
    NSRect(x: 0, y: 0, width: W, height: H).fill()
    // Top row (flipped: y grows up, so the top row is at the high end).
    let top = CGFloat(H) - 20
    label("App icon 1024", 20, top - 22)
    load("icon-1024.png").draw(in: NSRect(x: 20, y: top - 1050, width: 1024, height: 1024))
    label("512", 1090, top - 22)
    load("icon-512.png").draw(in: NSRect(x: 1090, y: top - 540, width: 512, height: 512))
    label("128", 1090, top - 580)
    load("icon-128.png").draw(in: NSRect(x: 1090, y: top - 720, width: 128, height: 128))
    label("32", 1250, top - 580)
    load("icon-32.png").draw(in: NSRect(x: 1250, y: top - 640, width: 32, height: 32))
    label("16", 1330, top - 580)
    load("icon-16.png").draw(in: NSRect(x: 1330, y: top - 640, width: 16, height: 16))
    label("32 and 16 shown 4x, pixels kept", 1090, top - 760, size: 15)
    NSGraphicsContext.current?.imageInterpolation = .none
    load("icon-32.png").draw(in: NSRect(x: 1090, y: top - 900, width: 128, height: 128))
    load("icon-16.png").draw(in: NSRect(x: 1250, y: top - 900, width: 64, height: 64))
    NSGraphicsContext.current?.imageInterpolation = .high
    // Menu bar and favicon.
    label("Menu-bar mark (template image, tinted by macOS): light and dark bars, 1x and 2x", 20, 210)
    strip(20, 160, 500, dark: false, name: "Evening")
    strip(540, 160, 500, dark: true, name: "Evening")
    label("Favicon 16, 32, 64 (from web/public/favicon.svg)", 20, 100)
    favicon(16, at: NSPoint(x: 20, y: 40))
    favicon(32, at: NSPoint(x: 70, y: 40))
    favicon(64, at: NSPoint(x: 140, y: 40))
}
try! sheet.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: "\(dir)/contact-sheet.png"))

if !docOut.isEmpty {
    // The install guide's menu-bar picture: the mark large on a light and a dark bar.
    let doc = bitmap(1200, 750) {
        hex(0xD9D9DE).setFill(); NSRect(x: 0, y: 0, width: 1200, height: 750).fill()
        for (i, dark) in [false, true].enumerated() {
            let y = CGFloat(560 - i * 300)
            (dark ? hex(0x262626) : hex(0xF2F2F2)).setFill()
            NSRect(x: 0, y: y, width: 1200, height: 190).fill()
            let ink = dark ? NSColor.white : NSColor.black
            tinted(8, ink: ink).draw(in: NSRect(x: 70, y: y + 23, width: 144, height: 144))
            label("Evening", 240, y + 62, color: ink, size: 60)
        }
        label("Gaffer's menu-bar mark on a light and a dark menu bar", 70, 60, color: hex(0x333333), size: 36)
    }
    try! doc.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: docOut))
}
SWIFT
swiftc -O -target "$TARGET" "$ROOT/mac/Sources/GafferMark.swift" "$OUT/sheet/main.swift" -o "$OUT/sheet/sheet"
"$OUT/sheet/sheet" "$OUT" ${GAFFER_DOC_OUT:+"$GAFFER_DOC_OUT"}
[[ -z "${GAFFER_FAVICON_OUT:-}" ]] || cp "$OUT/favicon.svg" "$GAFFER_FAVICON_OUT"
echo "$OUT/contact-sheet.png"
