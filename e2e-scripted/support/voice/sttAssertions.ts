import type { DeviceEnv } from "../deviceEnv.js";

export function assertSttAssertionsEnabled(env: DeviceEnv, reason: string): void {
  if (!env.enableSttAssertions) {
    throw new Error(
      "STT assertions are disabled by default because they can spend money. "
        + "Set OPENBASE_E2E_ENABLE_STT_ASSERTIONS=1 only for tests that need real phone-heard speech, "
        + `such as pronunciation checks. Requested reason: ${reason}`,
    );
  }
}

export function shouldUseSttForPronunciation(env: DeviceEnv): boolean {
  return env.enableSttAssertions;
}

export function normalizeTranscript(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function assertTranscriptContains(transcript: string, expectedPhrase: string): void {
  const normalizedTranscript = normalizeTranscript(transcript);
  const normalizedExpected = normalizeTranscript(expectedPhrase);
  if (!normalizedTranscript.includes(normalizedExpected)) {
    throw new Error(
      `Expected STT transcript to contain "${expectedPhrase}". Transcript was: ${transcript}`,
    );
  }
}
