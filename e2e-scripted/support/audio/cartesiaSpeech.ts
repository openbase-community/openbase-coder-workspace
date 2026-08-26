import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import type { DeviceEnv } from "../deviceEnv.js";
import { packageRoot } from "../deviceEnv.js";

const audioArtifactDir = resolve(packageRoot, "artifacts/audio");

export async function synthesizeCartesiaSpeech(env: DeviceEnv, text: string): Promise<string> {
  const apiKey = env.cartesiaApiKey?.trim();
  if (!apiKey) {
    throw new Error(
      "Cartesia speech stimulus requires OPENBASE_E2E_CARTESIA_API_KEY or CARTESIA_API_KEY. "
        + "Mac-side prompts must use realistic TTS for phone transcription tests.",
    );
  }

  const response = await fetch("https://api.cartesia.ai/tts/bytes", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "X-API-Key": apiKey,
      "Cartesia-Version": env.cartesiaVersion,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model_id: env.cartesiaModelId,
      transcript: text,
      voice: { id: env.cartesiaVoiceId },
      output_format: {
        container: "wav",
        encoding: "pcm_f32le",
        sample_rate: 44100,
      },
      language: "en",
      generation_config: {
        volume: 1,
        speed: 1,
      },
    }),
  });

  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(`Cartesia TTS request failed with ${response.status}: ${detail.slice(0, 500)}`);
  }

  mkdirSync(audioArtifactDir, { recursive: true });
  const path = resolve(audioArtifactDir, `cartesia-${Date.now()}.wav`);
  writeFileSync(path, Buffer.from(await response.arrayBuffer()));
  return path;
}
