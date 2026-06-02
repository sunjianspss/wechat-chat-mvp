import Foundation
import Vision
import CoreGraphics
import CoreImage
import ImageIO

struct OCRLine: Codable {
    let text: String
    let confidence: Float
    let x: Double
    let y: Double
    let width: Double
    let height: Double
}

func fail(_ message: String) -> Never {
    FileHandle.standardError.write((message + "\n").data(using: .utf8)!)
    exit(1)
}

guard CommandLine.arguments.count >= 2 else {
    fail("Usage: ocr_vision <image-path> [zh-Hans,en-US] [scale] [raw|enhanced]")
}

let imagePath = CommandLine.arguments[1]
let languageArgument = CommandLine.arguments.count >= 3 ? CommandLine.arguments[2] : "auto"
let languages = languageArgument == "auto"
    ? []
    : languageArgument.split(separator: ",").map { String($0) }
let requestedScale = CommandLine.arguments.count >= 4 ? (Double(CommandLine.arguments[3]) ?? 1.5) : 1.5
let mode = CommandLine.arguments.count >= 5 ? CommandLine.arguments[4] : "enhanced"
let maxPixelSize = 2400.0

func scaledImage(_ image: CGImage, requestedScale: Double, maxPixelSize: Double) -> CGImage {
    let width = Double(image.width)
    let height = Double(image.height)
    let largest = max(width, height)
    let scale = max(1.0, min(requestedScale, maxPixelSize / largest))
    if scale <= 1.01 {
        return image
    }

    let newWidth = Int((width * scale).rounded())
    let newHeight = Int((height * scale).rounded())
    guard let context = CGContext(
        data: nil,
        width: newWidth,
        height: newHeight,
        bitsPerComponent: 8,
        bytesPerRow: 0,
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else {
        return image
    }
    context.interpolationQuality = .high
    context.draw(image, in: CGRect(x: 0, y: 0, width: newWidth, height: newHeight))
    return context.makeImage() ?? image
}

func enhancedImage(_ image: CGImage) -> CGImage {
    guard mode == "enhanced" else {
        return image
    }
    let ciImage = CIImage(cgImage: image)
    let color = CIFilter(name: "CIColorControls")
    color?.setValue(ciImage, forKey: kCIInputImageKey)
    color?.setValue(0.0, forKey: kCIInputSaturationKey)
    color?.setValue(1.28, forKey: kCIInputContrastKey)
    color?.setValue(0.02, forKey: kCIInputBrightnessKey)

    let sharpen = CIFilter(name: "CISharpenLuminance")
    sharpen?.setValue(color?.outputImage ?? ciImage, forKey: kCIInputImageKey)
    sharpen?.setValue(0.45, forKey: kCIInputSharpnessKey)

    let output = sharpen?.outputImage ?? color?.outputImage ?? ciImage
    let context = CIContext(options: [.useSoftwareRenderer: false])
    return context.createCGImage(output, from: output.extent) ?? image
}

let imageURL = URL(fileURLWithPath: imagePath)
guard let source = CGImageSourceCreateWithURL(imageURL as CFURL, nil),
      let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
        kCGImageSourceCreateThumbnailFromImageAlways: true,
        kCGImageSourceThumbnailMaxPixelSize: Int(maxPixelSize),
        kCGImageSourceCreateThumbnailWithTransform: true
      ] as CFDictionary) else {
    fail("Cannot load image: \(imagePath)")
}

let preparedImage = enhancedImage(scaledImage(image, requestedScale: requestedScale, maxPixelSize: maxPixelSize))

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
if !languages.isEmpty {
    request.recognitionLanguages = languages
}

let handler = VNImageRequestHandler(cgImage: preparedImage, orientation: .up, options: [:])

do {
    try handler.perform([request])
} catch {
    fail("OCR failed: \(error)")
}

let observations = request.results ?? []
let lines: [OCRLine] = observations.compactMap { observation in
    guard let candidate = observation.topCandidates(1).first else {
        return nil
    }
    let box = observation.boundingBox
    let text = candidate.string.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !text.isEmpty else {
        return nil
    }
    return OCRLine(
        text: text,
        confidence: candidate.confidence,
        x: box.origin.x,
        y: box.origin.y,
        width: box.width,
        height: box.height
    )
}
.sorted { left, right in
    let rowDelta = abs(left.y - right.y)
    if rowDelta > 0.015 {
        return left.y > right.y
    }
    return left.x < right.x
}

let encoder = JSONEncoder()
encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
let data = try encoder.encode(lines)
FileHandle.standardOutput.write(data)
