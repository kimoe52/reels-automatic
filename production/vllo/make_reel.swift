import AVFoundation
import CoreGraphics
import ImageIO

guard CommandLine.arguments.count >= 3 else {
    fputs("usage: make_reel.swift <frames_dir> <output_mp4> [fps]\n", stderr)
    exit(2)
}

let framesDirectory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let outputURL = URL(fileURLWithPath: CommandLine.arguments[2])
let fps = Int32(CommandLine.arguments.dropFirst(3).first ?? "24") ?? 24
let fm = FileManager.default
let frameURLs = (try? fm.contentsOfDirectory(at: framesDirectory, includingPropertiesForKeys: nil))?
    .filter { $0.pathExtension.lowercased() == "png" }
    .sorted { $0.lastPathComponent < $1.lastPathComponent } ?? []

guard !frameURLs.isEmpty else {
    fputs("no PNG frames found\n", stderr)
    exit(3)
}

try? fm.removeItem(at: outputURL)
let writer = try AVAssetWriter(outputURL: outputURL, fileType: .mp4)
let settings: [String: Any] = [
    AVVideoCodecKey: AVVideoCodecType.h264,
    AVVideoWidthKey: 1080,
    AVVideoHeightKey: 1920,
    AVVideoCompressionPropertiesKey: [AVVideoAverageBitRateKey: 8_000_000]
]
let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
input.expectsMediaDataInRealTime = false
let adaptor = AVAssetWriterInputPixelBufferAdaptor(
    assetWriterInput: input,
    sourcePixelBufferAttributes: [
        kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32ARGB,
        kCVPixelBufferWidthKey as String: 1080,
        kCVPixelBufferHeightKey as String: 1920
    ]
)
writer.add(input)
writer.startWriting()
writer.startSession(atSourceTime: .zero)

func pixelBuffer(from image: CGImage) -> CVPixelBuffer? {
    var buffer: CVPixelBuffer?
    let attributes = [
        kCVPixelBufferCGImageCompatibilityKey as String: true,
        kCVPixelBufferCGBitmapContextCompatibilityKey as String: true
    ] as CFDictionary
    guard CVPixelBufferCreate(kCFAllocatorDefault, 1080, 1920, kCVPixelFormatType_32ARGB, attributes, &buffer) == kCVReturnSuccess,
          let buffer else { return nil }
    CVPixelBufferLockBaseAddress(buffer, [])
    defer { CVPixelBufferUnlockBaseAddress(buffer, []) }
    guard let base = CVPixelBufferGetBaseAddress(buffer) else { return nil }
    let context = CGContext(
        data: base,
        width: 1080,
        height: 1920,
        bitsPerComponent: 8,
        bytesPerRow: CVPixelBufferGetBytesPerRow(buffer),
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.noneSkipFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue
    )
    context?.draw(image, in: CGRect(x: 0, y: 0, width: 1080, height: 1920))
    return buffer
}

var frameNumber: Int64 = 0
for frameURL in frameURLs {
    guard let source = CGImageSourceCreateWithURL(frameURL as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
          let buffer = pixelBuffer(from: image) else { continue }
    for _ in 0..<4 {
        while !input.isReadyForMoreMediaData {
            RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.005))
        }
        let time = CMTime(value: frameNumber, timescale: CMTimeScale(fps))
        adaptor.append(buffer, withPresentationTime: time)
        frameNumber += 1
    }
}

input.markAsFinished()
let semaphore = DispatchSemaphore(value: 0)
writer.finishWriting { semaphore.signal() }
semaphore.wait()
if writer.status != .completed {
    fputs("video encoding failed: \(writer.error?.localizedDescription ?? "unknown")\n", stderr)
    exit(4)
}
print(outputURL.path)
