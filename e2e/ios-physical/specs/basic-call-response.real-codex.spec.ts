import { browser, expect } from "@wdio/globals";
import { loadDeviceEnv } from "../support/deviceEnv.js";
import {
  activateOpenbaseApp,
  endCall,
  expectOpenbaseForeground,
  openCallSurface,
  startCall,
} from "../support/phoneApp.js";
import { speakText } from "../support/audio/speakText.js";
import { expectedDispatcherReasoning, readNormalDispatcherReasoning } from "../support/dispatcherSettings.js";
import { readLiveKitLogCursor, waitForLiveKitLogEvidence } from "../support/voice/livekitLogs.js";

const spokenPrompt = "Hey are you there?";
const responsePattern =
  /stage=tts_(?:stream_flush|synthesize_start).*text_excerpt=.*\b(yes|yep|i['’]?m here|i am here)\b/i;

describe("Openbase iOS basic voice response via LiveKit logs", () => {
  const env = loadDeviceEnv({ requirePhysicalDevice: true });

  it("starts a call, asks if the agent is there, and verifies the TTS response from logs", async function (this: Mocha.Context) {
    if (!env.enableAudioStimulus) {
      throw new Error(
        "OPENBASE_E2E_ENABLE_AUDIO_STIMULUS=1 is required because this smoke test must speak the prompt into the physical iPhone.",
      );
    }

    let callStarted = false;
    let testError: unknown;

    try {
      const dispatcherReasoning = readNormalDispatcherReasoning();
      expect(dispatcherReasoning.reasoningEffort).toBe(expectedDispatcherReasoning);

      await activateOpenbaseApp(env);
      await expectOpenbaseForeground(env);

      await openCallSurface();
      await startCall();
      callStarted = true;
      await browser.pause(5_000);

      const responseLogCursor = readLiveKitLogCursor(env);
      await speakText(spokenPrompt, env);

      const evidence = await waitForLiveKitLogEvidence(env, responsePattern, 90_000, { after: responseLogCursor });
      expect(evidence.path).toBe(env.livekitLogPath);
    } catch (error) {
      testError = error;
      throw error;
    } finally {
      if (callStarted) {
        try {
          await endCall();
        } catch (error) {
          if (testError === undefined) {
            throw error;
          }
          console.warn(`Call cleanup failed after test failure: ${String(error)}`);
        }
      }
    }
  });
});
