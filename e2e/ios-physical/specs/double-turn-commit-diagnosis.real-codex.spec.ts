import { browser, expect } from "@wdio/globals";
import { speakText } from "../support/audio/speakText.js";
import { loadDeviceEnv } from "../support/deviceEnv.js";
import {
  expectedDispatcherReasoning,
  readNormalDispatcherReasoning,
} from "../support/dispatcherSettings.js";
import {
  enableSpeakerIfAvailable,
  endCall,
  expectOpenbaseForeground,
  openCallSurface,
  relaunchOpenbaseApp,
  startCall,
} from "../support/phoneApp.js";
import {
  readLiveKitLogCursor,
  readRecentLiveKitLog,
  waitForLiveKitLogEvidence,
} from "../support/voice/livekitLogs.js";

// Phase 0 of the 2026-07-13 double-response diagnosis: confirm (or, after the
// STT fix lands, deny) that a single spoken utterance is committed twice —
// two near-identical user messages that each spawn an LLM generation
// (`livekit_llm_turn_start` pairs 2-200ms apart whose prompt lengths differ
// by a character or two). The spec speaks one prompt on a live call and then
// reads the turn-lifecycle evidence for that utterance from the LiveKit
// agent log.
//
// Default mode is diagnostic: it reports the verdict without failing on
// twins. Once the single-final-transcript fix is deployed, run with
// OPENBASE_E2E_EXPECT_SINGLE_TURN_COMMIT=1 to assert exactly one generation
// per utterance.

const spokenPrompt = "What is two plus two?";
const firstAudioPattern = /stage=tts_stream_first_audio role=direct/i;

// Twins are the same utterance transcribed twice, so they land close
// together and nearly identical in length.
const twinWindowMs = 1_500;
const twinMaxPromptLenDelta = 3;

const expectSingleTurnCommit =
  process.env.OPENBASE_E2E_EXPECT_SINGLE_TURN_COMMIT === "1";

type TurnStartEvent = {
  messageId: string;
  promptLen: number;
  timestampMs: number;
  timestamp: string;
};

function parseTurnStarts(logRegion: string): TurnStartEvent[] {
  const events: TurnStartEvent[] = [];
  for (const line of logRegion.split("\n")) {
    const message = line.match(
      /stage=livekit_llm_turn_start message_id=(\S+) prompt_len=(\d+)/,
    );
    if (!message) {
      continue;
    }
    const timestamp = line.match(/"timestamp": "([^"]+)"/);
    const timestampText = timestamp ? timestamp[1] : "";
    events.push({
      messageId: message[1],
      promptLen: Number(message[2]),
      timestampMs: timestampText ? Date.parse(timestampText) : Number.NaN,
      timestamp: timestampText,
    });
  }
  return events;
}

function countMatches(logRegion: string, pattern: RegExp): number {
  return logRegion.split("\n").filter(line => pattern.test(line)).length;
}

function findTwinPairs(events: TurnStartEvent[]): Array<[TurnStartEvent, TurnStartEvent]> {
  const pairs: Array<[TurnStartEvent, TurnStartEvent]> = [];
  for (let i = 0; i < events.length; i += 1) {
    for (let j = i + 1; j < events.length; j += 1) {
      const gapMs = Math.abs(events[j].timestampMs - events[i].timestampMs);
      const lenDelta = Math.abs(events[j].promptLen - events[i].promptLen);
      if (gapMs <= twinWindowMs && lenDelta <= twinMaxPromptLenDelta) {
        pairs.push([events[i], events[j]]);
      }
    }
  }
  return pairs;
}

describe("Openbase iOS double turn-commit diagnosis via LiveKit logs", () => {
  const env = loadDeviceEnv({ requirePhysicalDevice: true });

  it("measures how many LLM generations one spoken utterance produces", async function (this: Mocha.Context) {
    if (!env.enableAudioStimulus) {
      throw new Error(
        "OPENBASE_E2E_ENABLE_AUDIO_STIMULUS=1 is required because this diagnosis must speak a prompt into the physical iPhone.",
      );
    }

    const dispatcherReasoning = readNormalDispatcherReasoning();
    expect(dispatcherReasoning.reasoningEffort).toBe(expectedDispatcherReasoning);

    let callStarted = false;
    let testError: unknown;

    try {
      await relaunchOpenbaseApp(env);
      await expectOpenbaseForeground(env);
      await openCallSurface();
      await startCall();
      callStarted = true;
      await browser.pause(2_000);
      await enableSpeakerIfAvailable();
      await browser.pause(3_000);

      const cursor = readLiveKitLogCursor(env);
      await speakText(spokenPrompt, env);

      // The utterance must produce an audible answer before we read the
      // evidence; twins land within ~200ms of each other, well inside this.
      await waitForLiveKitLogEvidence(env, firstAudioPattern, 90_000, {
        after: cursor,
      });
      // Let stragglers (late formatted transcripts, cancellations, orphan
      // grace timers) reach the log before sampling it.
      await browser.pause(5_000);

      const logRegion = readRecentLiveKitLog(env, cursor);
      const turnStarts = parseTurnStarts(logRegion);
      const twinPairs = findTwinPairs(turnStarts);
      const cancelledCount = countMatches(logRegion, /stage=voice_turn_cancelled/);
      const joinedCount = countMatches(
        logRegion,
        /stage=voice_request_joined_(?:active|completed_active)_turn/,
      );
      const steerSkippedCount = countMatches(
        logRegion,
        /stage=livekit_llm_prompt_already_steered/,
      );
      const orphanSpokenCount = countMatches(logRegion, /stage=orphaned_result_spoken/);
      const alreadySpokenCount = countMatches(
        logRegion,
        /stage=voice_request_active_turn_already_spoken/,
      );
      const idleSttSessions = new Set(
        [...logRegion.matchAll(/AssemblyAI no messages received for \d+s session=(\S+)"/g)].map(
          match => match[1],
        ),
      );

      console.log("=== PHASE 0 DOUBLE TURN-COMMIT DIAGNOSIS ===");
      for (const event of turnStarts) {
        console.log(
          `turn_start ${event.timestamp} message_id=${event.messageId} prompt_len=${event.promptLen}`,
        );
      }
      for (const [first, second] of twinPairs) {
        console.log(
          `TWIN COMMIT: prompt_len ${first.promptLen} vs ${second.promptLen}, `
            + `${Math.abs(second.timestampMs - first.timestampMs)}ms apart`,
        );
      }
      console.log(
        `verdict: turn_starts=${turnStarts.length} twin_pairs=${twinPairs.length} `
          + `cancelled=${cancelledCount} joined=${joinedCount} steer_skipped=${steerSkippedCount} `
          + `orphan_spoken=${orphanSpokenCount} already_spoken=${alreadySpokenCount}`,
      );
      console.log(
        idleSttSessions.size > 0
          ? `idle STT sessions observed (possible zombie streams): ${[...idleSttSessions].join(", ")}`
          : "no idle STT session warnings in window",
      );
      console.log("=== END DIAGNOSIS ===");

      // The measurement must be conclusive: the utterance registered and
      // produced at least one generation.
      expect(turnStarts.length).toBeGreaterThanOrEqual(1);

      // A clean single utterance with no interruption must never take the
      // duplicate-speech paths, twins or not.
      expect(orphanSpokenCount).toBe(0);
      expect(alreadySpokenCount).toBe(0);

      if (expectSingleTurnCommit) {
        // Post-fix mode: one utterance, one generation, no churn.
        expect(turnStarts.length).toBe(1);
        expect(twinPairs.length).toBe(0);
        expect(cancelledCount).toBe(0);
      } else if (twinPairs.length > 0) {
        console.log(
          "Diagnosis CONFIRMS the double turn-commit: the utterance spawned "
            + "near-identical twin generations. See the RMOT fix plan Phase 1.",
        );
      } else {
        console.log(
          "Diagnosis did NOT observe twin generations for this utterance. "
            + "Either the fix is already active or the twin behavior is intermittent; rerun to confirm.",
        );
      }
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
