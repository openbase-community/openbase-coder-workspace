import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { browser, expect } from "@wdio/globals";
import { speakText } from "../support/audio/speakText.js";
import { loadDeviceEnv } from "../support/deviceEnv.js";
import { expectedSuperAgentsReasoning, readNormalSuperAgentsReasoning } from "../support/dispatcherSettings.js";
import {
  createCleanWorkspace,
  fileMtimeMs,
  waitForFileText,
  writeBriefing,
  writeTaskInstructions,
} from "../support/fileTasks.js";
import {
  activateOpenbaseApp,
  endCall,
  expectOpenbaseForeground,
  openCallSurface,
  startCall,
} from "../support/phoneApp.js";
import { readLiveKitLogCursor, waitForLiveKitLogEvidence } from "../support/voice/livekitLogs.js";
import { waitForVoiceRoute } from "../support/voice/voiceRoute.js";

const billAgentPattern = /\b(Bill|Bill Gates)\b/i;
const dispatcherPattern = /stage=tts_(?:stream_flush|synthesize_start).*text_excerpt=.*\bdispatch/i;

describe("Openbase iOS parallel Super Agents truth test", () => {
  const env = loadDeviceEnv({ requirePhysicalDevice: true });

  it("launches two live Super Agents, transfers to the Bill report agent, and exits to dispatch", async function (this: Mocha.Context) {
    if (!env.enableAudioStimulus) {
      throw new Error(
        "OPENBASE_E2E_ENABLE_AUDIO_STIMULUS=1 is required because this test must speak prompts into the physical iPhone.",
      );
    }

    const superAgentsReasoning = readNormalSuperAgentsReasoning();
    expect(superAgentsReasoning.reasoningEffort).toBe(expectedSuperAgentsReasoning);

    let callStarted = false;
    let testError: unknown;
    const testRoot = join(process.env.HOME ?? ".", "openbase-live-test");
    const workspace = createCleanWorkspace(testRoot);
    const elonDir = workspace.path("elon");
    const billDir = workspace.path("bill");
    const elonReport = join(elonDir, "report.md");
    const billReport = join(billDir, "report.md");
    mkdirSync(elonDir, { recursive: true });
    mkdirSync(billDir, { recursive: true });
    writeTaskInstructions(
      workspace.path("AGENTS.md"),
      [
        "This is a live no-mock Openbase E2E test.",
        "Read briefing.md in this folder and follow it exactly.",
        "Do not rely on the spoken prompt for paths, names, topics, or filenames.",
      ],
    );
    writeBriefing(
      workspace.path("briefing.md"),
      "Openbase Parallel Agents Truth Test Briefing",
      [
        "This is the live share-readiness truth test.",
        "Launch two real Super Agents in parallel, each in its own folder.",
        `Elon report folder: ${elonDir}`,
        `Elon report file: ${elonReport}`,
        "Elon report topic: Elon Musk",
        `Bill report folder: ${billDir}`,
        `Bill report file: ${billReport}`,
        "Bill report topic: Bill Gates",
        "Each agent should wait ten seconds before writing its report.",
        "After both report files exist, transfer the voice session to the Bill Gates report agent.",
        "After the transfer, the Bill Gates agent should say: Bill truth ready.",
        "When asked what happened, the Bill Gates report agent should summarize the two-agent work.",
        "When asked to exit to dispatch, return the voice session to dispatch.",
      ],
    );

    const launchPrompt = [
      "Hi Openbase.",
      "In my home folder, open the folder named openbase live test.",
      "Follow the briefing markdown file in that folder.",
      "It is the parallel agents truth test.",
      "Reply when the briefing is complete.",
    ].join(" ");
    const whatHappenedPrompt = "What did you just do?";
    const exitPrompt = "Exit to dispatch.";

    try {
      await activateOpenbaseApp(env);
      await expectOpenbaseForeground(env);

      await openCallSurface();
      await startCall();
      callStarted = true;
      await browser.pause(5_000);

      const responseLogCursor = readLiveKitLogCursor(env);
      await speakText(launchPrompt, env);

      const elonText = await waitForFileText(elonReport, /Elon Musk/i, 8 * 60 * 1000);
      const billText = await waitForFileText(billReport, /Bill Gates/i, 8 * 60 * 1000);
      expect(elonText).toMatch(/Elon Musk/i);
      expect(billText).toMatch(/Bill Gates/i);
      expect(billText).not.toBe(elonText);

      const writeSkewMs = Math.abs(fileMtimeMs(elonReport) - fileMtimeMs(billReport));
      expect(writeSkewMs).toBeLessThan(120_000);

      await waitForVoiceRoute("target", 180_000, billAgentPattern);
      await waitForLiveKitLogEvidence(
        env,
        /stage=tts_(?:stream_flush|synthesize_start).*text_excerpt=.*Bill truth ready/i,
        180_000,
        { after: responseLogCursor },
      );

      const billAnswerCursor = readLiveKitLogCursor(env);
      await speakText(whatHappenedPrompt, env);
      await waitForLiveKitLogEvidence(
        env,
        /stage=tts_(?:stream_flush|synthesize_start).*text_excerpt=.*\b(Bill|report|Gates)\b/i,
        180_000,
        { after: billAnswerCursor },
      );

      const exitCursor = readLiveKitLogCursor(env);
      await speakText(exitPrompt, env);
      await waitForVoiceRoute("dispatcher", 180_000);
      await waitForLiveKitLogEvidence(env, dispatcherPattern, 180_000, { after: exitCursor });
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
