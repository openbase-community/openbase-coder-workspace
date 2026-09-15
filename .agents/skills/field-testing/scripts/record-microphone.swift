#!/usr/bin/env swift

import AVFoundation
import Foundation

guard CommandLine.arguments.count == 3,
      let seconds = Double(CommandLine.arguments[2]),
      seconds > 0 else {
    FileHandle.standardError.write(Data("usage: record-microphone.swift OUTPUT_PATH SECONDS\n".utf8))
    exit(2)
}

let outputURL = URL(fileURLWithPath: CommandLine.arguments[1])
let engine = AVAudioEngine()
let input = engine.inputNode
let format = input.outputFormat(forBus: 0)
let file = try AVAudioFile(forWriting: outputURL, settings: format.settings)

input.installTap(onBus: 0, bufferSize: 4096, format: format) { buffer, _ in
    do {
        try file.write(from: buffer)
    } catch {
        FileHandle.standardError.write(Data("microphone write failed: \(error)\n".utf8))
    }
}

engine.prepare()
try engine.start()
print("READY")
fflush(stdout)
Thread.sleep(forTimeInterval: seconds)
engine.stop()
input.removeTap(onBus: 0)
