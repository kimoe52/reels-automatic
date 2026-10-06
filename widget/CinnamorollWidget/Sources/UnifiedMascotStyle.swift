import AppKit

/// Optical sizing shared by the floating widgets. Transparent PNG padding must
/// never determine a character's apparent size.
struct MascotPresentation {
    static let referenceArea: CGFloat = 1103.3
    static let maximumSize = NSSize(width: 56, height: 52)
    static let cinnamorollOutlineOutset: CGFloat = 0.12
    static let kuromiOutlineOutset: CGFloat = 0.20
    static let cinnamorollVisualScale: CGFloat = 1.07

    let image: NSImage
    let silhouette: NSImage
    let size: NSSize
    let visibleArea: CGFloat

    static func prepare(_ image: NSImage) -> MascotPresentation? {
        guard let original = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return nil }
        let width = original.width, height = original.height
        guard let context = CGContext(
            data: nil, width: width, height: height, bitsPerComponent: 8,
            bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue
        ), let data = context.data else { return nil }
        context.draw(original, in: CGRect(x: 0, y: 0, width: width, height: height))
        let pixels = data.assumingMemoryBound(to: UInt8.self)
        var minX = width, minY = height, maxX = -1, maxY = -1
        var alphaArea: CGFloat = 0
        for y in 0..<height {
            for x in 0..<width {
                let alpha = pixels[(y * width + x) * 4 + 3]
                if alpha >= 16 { alphaArea += CGFloat(alpha) / 255 }
                if alpha >= 128 {
                    minX = min(minX, x); minY = min(minY, y)
                    maxX = max(maxX, x); maxY = max(maxY, y)
                }
            }
        }
        guard maxX >= minX, maxY >= minY, alphaArea > 0 else { return nil }
        minX = max(0, minX - 2); minY = max(0, minY - 2)
        maxX = min(width - 1, maxX + 2); maxY = min(height - 1, maxY + 2)
        let cropRect = CGRect(x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1)
        guard let canonical = context.makeImage(), let cropped = canonical.cropping(to: cropRect) else { return nil }
        let factor = min(
            sqrt(referenceArea / alphaArea),
            maximumSize.width / cropRect.width,
            maximumSize.height / cropRect.height
        )
        guard let black = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
                                    bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue),
              let blackData = black.data else { return nil }
        let blackPixels = blackData.assumingMemoryBound(to: UInt8.self)
        for index in 0..<(width * height) {
            blackPixels[index * 4 + 3] = pixels[index * 4 + 3] >= 128 ? 255 : 0
        }
        guard let blackImage = black.makeImage()?.cropping(to: cropRect) else { return nil }
        return MascotPresentation(
            image: NSImage(cgImage: cropped, size: cropRect.size),
            silhouette: NSImage(cgImage: blackImage, size: cropRect.size),
            size: NSSize(width: cropRect.width * factor, height: cropRect.height * factor),
            visibleArea: alphaArea * factor * factor
        )
    }

    func rasterized(outlineOutset: CGFloat, visualScale: CGFloat = 1) -> NSImage? {
        guard let context = CGContext(data: nil, width: 512, height: 512, bitsPerComponent: 8,
                                      bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return nil }
        context.scaleBy(x: 8, y: 8)
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(cgContext: context, flipped: false)
        drawContent(in: NSRect(x: 0, y: 0, width: 64, height: 64), outlineOutset: outlineOutset, visualScale: visualScale)
        NSGraphicsContext.restoreGraphicsState()
        guard let output = context.makeImage() else { return nil }
        return NSImage(cgImage: output, size: NSSize(width: 64, height: 64))
    }

    func draw(in bounds: NSRect, flipped: Bool = false, outlineOutset: CGFloat = 0, visualScale: CGFloat = 1) {
        rasterized(outlineOutset: outlineOutset, visualScale: visualScale)?.draw(in: bounds, from: .zero,
            operation: .sourceOver, fraction: 1, respectFlipped: flipped,
            hints: [.interpolation: NSImageInterpolation.high])
    }

    private func drawContent(in bounds: NSRect, outlineOutset: CGFloat, visualScale: CGFloat) {
        let available = bounds.insetBy(dx: 2, dy: 2)
        let fit = min(visualScale, available.width / size.width, available.height / size.height)
        let target = NSRect(
            x: bounds.midX - size.width * fit / 2,
            y: bounds.midY - size.height * fit / 2,
            width: size.width * fit, height: size.height * fit
        )
        if outlineOutset > 0 {
            for step in 0..<16 {
                let angle = CGFloat(step) * .pi / 8
                let shifted = target.offsetBy(dx: cos(angle) * outlineOutset * fit,
                                               dy: sin(angle) * outlineOutset * fit)
                silhouette.draw(in: shifted, from: NSRect(origin: .zero, size: silhouette.size),
                                operation: .sourceOver, fraction: 1, respectFlipped: false,
                                hints: [.interpolation: NSImageInterpolation.high])
            }
        }
        image.draw(in: target, from: NSRect(origin: .zero, size: image.size),
                   operation: .sourceOver, fraction: 1, respectFlipped: false,
                   hints: [.interpolation: NSImageInterpolation.high])
    }
}

final class UnifiedMascotImageView: NSView {
    var outlineOutset: CGFloat = 0 { didSet { cachePresentation() } }
    var visualScale: CGFloat = 1 { didSet { cachePresentation() } }
    var image: NSImage? {
        didSet {
            presentation = image.flatMap(MascotPresentation.prepare)
            cachePresentation()
        }
    }
    private var presentation: MascotPresentation?
    private var rendered: NSImage?

    private func cachePresentation() {
        rendered = presentation?.rasterized(outlineOutset: outlineOutset, visualScale: visualScale)
        needsDisplay = true
    }

    override var intrinsicContentSize: NSSize {
        NSSize(width: NSView.noIntrinsicMetric, height: NSView.noIntrinsicMetric)
    }

    override func draw(_ dirtyRect: NSRect) {
        rendered?.draw(in: bounds, from: .zero, operation: .sourceOver, fraction: 1,
                       respectFlipped: isFlipped, hints: [.interpolation: NSImageInterpolation.high])
    }
}
