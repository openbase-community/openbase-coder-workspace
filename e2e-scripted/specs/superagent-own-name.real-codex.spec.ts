import { join } from "node:path";
import { browser, expect } from "@wdio/globals";
import { speakText } from "../support/audio/speakText.js";
import { loadDeviceEnv } from "../support/deviceEnv.js";
import {
  expectedSuperAgentsReasoning,
  readNormalSuperAgentsReasoning,
} from "../support/dispatcherSettings.js";
import {
  activateOpenbaseApp,
  endCall,
  expectOpenbaseForeground,
  openCallSurface,
  startCall,
} from "../support/phoneApp.js";
import {
  createCleanWorkspace,
  readFileTrimmed,
  waitForFile,
  writeBriefing,
  writeTaskInstructions,
} from "../support/fileTasks.js";
import { readLiveKitLogCursor, waitForLiveKitLogEvidence } from "../support/voice/livekitLogs.js";

const threadName = "own-name-test";
const agentName = "Kenny";
const testSentence = "red blue green";
const testFileName = "kenny.txt";
const responsePattern = new RegExp(
  `stage=tts_(?:stream_flush|synthesize_start).*text_excerpt=.*\\b${agentName}\\b`,
  "i",
);

describe("Openbase iOS Super Agent own-name voice response", () => {
  const env = loadDeviceEnv({ requirePhysicalDevice: true });

  it("starts a named Super Agent and verifies Kenny completes a random tmp file task", async function (this: Mocha.Context) {
    if (!env.enableAudioStimulus) {
      throw new Error(
        "OPENBASE_E2E_ENABLE_AUDIO_STIMULUS=1 is required because this test must speak the prompt into the physical iPhone.",
      );
    }

    const superAgentsReasoning = readNormalSuperAgentsReasoning();
    expect(superAgentsReasoning.reasoningEffort).toBe(expectedSuperAgentsReasoning);

    let callStarted = false;
    let testError: unknown;
    const testRoot = join(process.env.HOME ?? ".", "openbase-live-test");
    const workspace = createCleanWorkspace(testRoot);
    const testFilePath = workspace.path(testFileName);
    const spokenPrompt = [
      "Hi Openbase.",
      "In my home folder, open the folder named openbase live test.",
      "Follow the briefing markdown file in that folder.",
      "Reply when the briefing is complete.",
    ].join(" ");

    try {
      writeTaskInstructions(
        join(testRoot, "AGENTS.md"),
        [
          "You are Kenny.",
          "For this live E2E test, read briefing.md in this folder and follow it exactly.",
          `After the file is written, reply with a short sentence that includes the name ${agentName}.`,
        ],
      );
      writeBriefing(
        workspace.path("briefing.md"),
        "Openbase Live E2E Own Name Briefing",
        [
          `Thread name: ${threadName}.`,
          `Working directory: ${testRoot}`,
          `Create this file: ${testFilePath}`,
          `Write exactly this text into the file, with no extra words: ${testSentence}`,
          `After writing the file, reply with a short sentence that includes the name ${agentName}.`,
        ],
      );

      await activateOpenbaseApp(env);
      await expectOpenbaseForeground(env);

      await openCallSurface();
      await startCall();
      callStarted = true;
      await browser.pause(5_000);

      const responseLogCursor = readLiveKitLogCursor(env);
      await speakText(spokenPrompt, env);

      const evidence = await waitForLiveKitLogEvidence(env, responsePattern, 240_000, { after: responseLogCursor });
      expect(evidence.path).toBe(env.livekitLogPath);

      await waitForFile(testFilePath, 30_000);
      expect(readFileTrimmed(testFilePath)).toBe(testSentence);
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
