import AppKit
import Foundation

guard CommandLine.arguments.count == 2 else {
    fputs("Usage: generate_app_icon.swift output.png\n", stderr)
    exit(2)
}

let canvasSize = NSSize(width: 1024, height: 1024)
let image = NSImage(size: canvasSize)
image.lockFocus()

let background = NSBezierPath(roundedRect: NSRect(x: 32, y: 32, width: 960, height: 960), xRadius: 220, yRadius: 220)
NSColor(red: 0.035, green: 0.05, blue: 0.04, alpha: 1).setFill()
background.fill()

let glow = NSBezierPath(ovalIn: NSRect(x: 198, y: 198, width: 628, height: 628))
NSColor(red: 0.72, green: 1.0, blue: 0.29, alpha: 0.12).setFill()
glow.fill()

let ring = NSBezierPath(ovalIn: NSRect(x: 226, y: 226, width: 572, height: 572))
ring.lineWidth = 76
NSColor(red: 0.75, green: 1.0, blue: 0.31, alpha: 1).setStroke()
ring.stroke()

let aperture = NSBezierPath()
aperture.move(to: NSPoint(x: 492, y: 352))
aperture.line(to: NSPoint(x: 662, y: 512))
aperture.line(to: NSPoint(x: 492, y: 672))
aperture.close()
NSColor.white.setFill()
aperture.fill()

let highlight = NSBezierPath(roundedRect: NSRect(x: 316, y: 848, width: 392, height: 18), xRadius: 9, yRadius: 9)
NSColor(red: 0.75, green: 1.0, blue: 0.31, alpha: 0.85).setFill()
highlight.fill()

image.unlockFocus()

guard
    let tiff = image.tiffRepresentation,
    let bitmap = NSBitmapImageRep(data: tiff),
    let png = bitmap.representation(using: .png, properties: [:])
else {
    fputs("Unable to render app icon.\n", stderr)
    exit(1)
}

try png.write(to: URL(fileURLWithPath: CommandLine.arguments[1]), options: .atomic)
