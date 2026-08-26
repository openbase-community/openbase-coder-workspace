import { loadDeviceEnv } from "../deviceEnv.js";
import { speakText } from "./speakText.js";

export async function playCalibrationPhrase(): Promise<void> {
  await speakText("openbase e2e audio check", loadDeviceEnv());
}

export function describeAudioRouting(): string {
  return [
    "Cartesia-generated Mac speaker audio is used as an acoustic input to the physical iPhone microphone.",
    "Before running audio specs, select the intended Mac output device, disable headphones, place the iPhone near the speaker, and grant microphone permission in the app.",
  ].join(" ");
}
