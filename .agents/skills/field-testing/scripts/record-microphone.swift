#!/usr/bin/env swift

import AVFoundation
import Foundation

guard (3...4).contains(CommandLine.arguments.count),
      let seconds = Double(CommandLine.arguments[2]),
      seconds > 0 else {
    FileHandle.standardError.write(Data("usage: record-microphone.swift OUTPUT_PATH SECONDS [CLOCK_JSON]\n".utf8))
    exit(2)
}

let outputURL = URL(fileURLWithPath: CommandLine.arguments[1])
let engine = AVAudioEngine()
let input = engine.inputNode
let format = input.outputFormat(forBus: 0)
let file = try AVAudioFile(forWriting: outputURL, settings: format.settings)
let lock = NSLock()
var firstSampleUnixMs: Double?
var firstHostTime: Double?
var frames: Int64 = 0
var discontinuities: [[String: Double]] = []
var writeFailure: String?

input.installTap(onBus: 0, bufferSize: 4096, format: format) { buffer, when in
    lock.lock()
    defer { lock.unlock() }
    do {
        try file.write(from: buffer)
        if when.isHostTimeValid {
            let hostSeconds = AVAudioTime.seconds(forHostTime: when.hostTime)
            if let origin = firstHostTime {
                let gapMs = (hostSeconds - origin - Double(frames) / format.sampleRate) * 1000
                if abs(gapMs) > 5 {
                    discontinuities.append(["frame": Double(frames), "gap_ms": gapMs])
                }
            } else {
                firstHostTime = hostSeconds
                firstSampleUnixMs = (Date().timeIntervalSince1970 - ProcessInfo.processInfo.systemUptime + hostSeconds) * 1000
            }
        }
        frames += Int64(buffer.frameLength)
    } catch {
        writeFailure = String(describing: error)
    }
}

engine.prepare()
try engine.start()
print("READY")
fflush(stdout)
Thread.sleep(forTimeInterval: seconds)
engine.stop()
input.removeTap(onBus: 0)
lock.lock()
defer { lock.unlock() }
if let failure = writeFailure {
    FileHandle.standardError.write(Data("microphone write failed: \(failure)\n".utf8))
    exit(1)
}
if CommandLine.arguments.count == 4 {
    var clock: [String: Any] = ["sample_rate": format.sampleRate, "frames": frames, "duration_ms": Double(frames) / format.sampleRate * 1000, "discontinuities": discontinuities, "clock": "coreaudio_host_time", "wall_mapping": "host uptime sampled in first tap; not acoustic latency calibration"]
    if let origin = firstSampleUnixMs { clock["first_sample_unix_ms"] = origin }
    try JSONSerialization.data(withJSONObject: clock, options: [.prettyPrinted, .sortedKeys]).write(to: URL(fileURLWithPath: CommandLine.arguments[3]), options: .atomic)
}
