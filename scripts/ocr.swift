// 课件素材 OCR：PDF 逐页渲染 + PPTX 内嵌图片 → macOS Vision 文字识别
// 编译：swiftc -O -o /tmp/ocrbin scripts/ocr.swift
// 用法：ocrbin out.txt <file.pdf|file.pptx|image.png> ...
import Foundation
import Vision
import AppKit
import PDFKit

func ocr(cgImage: CGImage) -> String {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    do { try handler.perform([request]) } catch { return "" }
    guard let obs = request.results else { return "" }
    return obs.compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
}

func ocrPDF(_ url: URL) -> String {
    guard let doc = PDFDocument(url: url) else { return "" }
    var out: [String] = []
    for i in 0..<doc.pageCount {
        guard let page = doc.page(at: i) else { continue }
        let rect = page.bounds(for: .mediaBox)
        let scale: CGFloat = 3.0
        let w = Int(rect.width * scale), h = Int(rect.height * scale)
        guard w > 0, h > 0,
              let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8,
                                  bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue)
        else { continue }
        ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
        ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
        ctx.scaleBy(x: scale, y: scale)
        ctx.translateBy(x: -rect.origin.x, y: -rect.origin.y)
        page.draw(with: .mediaBox, to: ctx)
        guard let img = ctx.makeImage() else { continue }
        let text = ocr(cgImage: img)
        if !text.isEmpty { out.append("[第\(i + 1)页]\n" + text) }
    }
    return out.joined(separator: "\n\n")
}

func ocrImageFile(_ url: URL) -> String {
    guard let src = CGImageSourceCreateWithURL(url as CFURL, nil),
          let img = CGImageSourceCreateImageAtIndex(src, 0, nil) else { return "" }
    return ocr(cgImage: img)
}

let args = Array(CommandLine.arguments.dropFirst())
guard args.count >= 2 else {
    FileHandle.standardError.write("usage: ocr <out.txt> <file...>\n".data(using: .utf8)!)
    exit(2)
}
let outPath = args[0]
var parts: [String] = []
for path in args.dropFirst() {
    let url = URL(fileURLWithPath: path)
    let ext = url.pathExtension.lowercased()
    var text = ""
    if ext == "pdf" { text = ocrPDF(url) }
    else if ["png", "jpg", "jpeg", "tiff", "heic", "bmp", "gif", "webp"].contains(ext) {
        text = ocrImageFile(url)
    } else { continue }
    if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        parts.append("===== \(url.lastPathComponent) =====\n" + text)
    }
}
try? parts.joined(separator: "\n\n").write(toFile: outPath, atomically: true, encoding: .utf8)
print("wrote \(outPath): \(parts.joined().count) chars")
