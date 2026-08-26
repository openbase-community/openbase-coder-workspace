import { existsSync } from "node:fs";
import { loadDeviceEnv } from "../deviceEnv.js";
import { readRecentLiveKitLog } from "./livekitLogs.js";

const env = loadDeviceEnv();
const logContent = readRecentLiveKitLog(env);

console.log(`TTS command: ${env.ttsCommand || "auto: .venv/bin/openbase-coder or openbase-coder"} user say ...`);
console.log(`LiveKit log path: ${env.livekitLogPath}`);
console.log(`LiveKit log exists: ${existsSync(env.livekitLogPath) ? "yes" : "no"}`);
console.log(`Recent LiveKit log bytes: ${Buffer.byteLength(logContent, "utf8")}`);
console.log(`STT assertions enabled: ${env.enableSttAssertions ? "yes" : "no"}`);
console.log(`Mac audio stimulus: Cartesia ${env.cartesiaModelId} voice ${env.cartesiaVoiceId}`);
console.log(`Cartesia API key available: ${env.cartesiaApiKey ? "yes" : "no"}`);
console.log("Default assertion policy: TTS command result + LiveKit log evidence; STT only for explicit pronunciation/audio-quality tests.");
