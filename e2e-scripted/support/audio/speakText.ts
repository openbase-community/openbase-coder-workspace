import type { DeviceEnv } from "../deviceEnv.js";
import { loadDeviceEnv } from "../deviceEnv.js";
import { synthesizeCartesiaSpeech } from "./cartesiaSpeech.js";
import { playAudioFile } from "./playFixture.js";

export async function speakText(text: string, env: DeviceEnv = loadDeviceEnv()): Promise<void> {
  const trimmed = text.trim();
  if (!trimmed) {
    throw new Error("Cannot speak an empty audio stimulus phrase.");
  }

  const audioPath = await synthesizeCartesiaSpeech(env, trimmed);
  await playAudioFile(audioPath);
}
