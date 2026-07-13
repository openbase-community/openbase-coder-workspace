import { browser, expect } from "@wdio/globals";
import { synthesizeCartesiaSpeech } from "../support/audio/cartesiaSpeech.js";
import { playAudioFile } from "../support/audio/playFixture.js";
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
  readCallMuteState,
  relaunchOpenbaseApp,
  startCall,
  unmuteCallIfMuted,
  waitForCallMuteState,
} from "../support/phoneApp.js";
import {
  findLiveKitLogEvidence,
  readLiveKitLogCursor,
  waitForLiveKitLogEvidence,
} from "../support/voice/livekitLogs.js";

// Reproduces the 2026-07-13 voice-delivery incidents: a dispatcher turn whose
// waiting voice generation dies (here via a spoken interruption) must still
// deliver its finished answer, and a reply after a long idle pause must not
// fail its first TTS write on a stale pooled Cartesia websocket.

const slowPrompt =
  "Please check whether the openbase coder workspace git checkout is clean, and double check before you answer.";
const interruptionFragment = "hey, wait";
const idleWarmupPrompt = "Hey are you there?";
const idleFollowUpPrompt = "Are you still there?";
// Past the 30s pool idle expiry and inside the observed 40-90s window where
// Cartesia kills idle sockets server-side.
const idlePauseMs = 75_000;

const interruptionEvidencePattern =
  /stage=voice_turn_cancelled|speech not done in time after interruption/i;
// All three delivery paths count: orphan delivery, joining a completed
// turn, and a replacement dispatch rejoining the still-running turn (the
// interrupting utterance itself usually triggers this last one).
const deliveryEvidencePattern =
  /stage=orphaned_result_spoken|stage=voice_request_joined_completed_active_turn|stage=voice_request_joined_active_turn/i;
const firstAudioPattern = /stage=tts_stream_first_audio role=direct/i;
const thinkingHoldPattern = /stage=agent_state_held_thinking/i;
const ttsFailurePattern =
  /Cartesia connection error|failed to synthesize speech/i;
const presenceResponsePattern =
  /stage=tts_(?:stream_flush|synthesize_start).*text_excerpt=.*\b(yes|yep|still here|i['’]?m here, |i['’]?m here\.|i am here)\b/i;

const expectAutoMuteAssertions =
  process.env.OPENBASE_E2E_EXPECT_AUTO_MUTE === "1";

describe("Openbase iOS orphaned answer recovery via LiveKit logs", () => {
  const env = loadDeviceEnv({ requirePhysicalDevice: true });

  const requireAudioStimulus = () => {
    if (!env.enableAudioStimulus) {
      throw new Error(
        "OPENBASE_E2E_ENABLE_AUDIO_STIMULUS=1 is required because this test must speak prompts into the physical iPhone.",
      );
    }
  };

  it("still speaks the answer after the waiting generation is interrupted", async function (this: Mocha.Context) {
    requireAudioStimulus();

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

      // Pre-synthesize the interruption clip: with Auto-mute enabled, the
      // app re-mutes ~700ms after a manual unmute while the agent is still
      // thinking, so the clip must start playing immediately after the tap.
      const interruptionAudioPath = await synthesizeCartesiaSpeech(
        env,
        interruptionFragment,
      );

      const cursor = readLiveKitLogCursor(env);
      await speakText(slowPrompt, env);

      // Interrupt while the dispatcher is still thinking so the framework
      // cancels the voice generation that was waiting to speak the answer.
      // Auto-mute closes the mic during thinking, so unmute right before
      // each attempt and retry until the interruption registers.
      await browser.pause(2_000);
      for (let attempt = 1; attempt <= 3; attempt += 1) {
        if ((await readCallMuteState()) === "muted") {
          await unmuteCallIfMuted();
        }
        await playAudioFile(interruptionAudioPath);
        if (
          findLiveKitLogEvidence(env, interruptionEvidencePattern, {
            after: cursor,
          })
        ) {
          break;
        }
        console.log(
          `Interruption attempt ${attempt} not yet registered; retrying.`,
        );
        await browser.pause(1_000);
      }

      // Precondition: the stimulus must actually land as an interruption.
      // If this times out, the dispatcher answered before the interruption;
      // retune slowPrompt or the attempt loop instead of treating it as a
      // product regression.
      await waitForLiveKitLogEvidence(env, interruptionEvidencePattern, 30_000, {
        after: cursor,
      });

      if (expectAutoMuteAssertions) {
        // With Auto-mute/Auto-unmute enabled on the phone, the owed-answer
        // state hold must keep the mic muted instead of auto-unmuting into
        // silence.
        const muteState = await waitForCallMuteState("muted", 5_000);
        expect(muteState).toBe("muted");
      } else {
        console.log(
          `Call mute state after interruption (informational): ${await readCallMuteState()}`,
        );
      }

      // The finished answer must still be delivered: either the orphaned
      // result handler speaks it directly, or a rejoining dispatch consumes
      // it. Both paths share the per-turn speech claim, so double delivery
      // is impossible.
      const delivery = await waitForLiveKitLogEvidence(
        env,
        deliveryEvidencePattern,
        120_000,
        { after: cursor },
      );
      console.log(`Recovery delivery evidence: ${delivery.matchedText}`);

      // The answer must have been audibly synthesized, not just flushed.
      await waitForLiveKitLogEvidence(env, firstAudioPattern, 60_000, {
        after: cursor,
      });

      const holdEvidence = findLiveKitLogEvidence(env, thinkingHoldPattern, {
        after: cursor,
      });
      console.log(
        holdEvidence
          ? `Thinking hold engaged: ${holdEvidence.matchedText}`
          : "Thinking hold did not engage (delivery beat the state drop); acceptable.",
      );
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

  it("answers cleanly after a long idle pause without a stale TTS socket failure", async function (this: Mocha.Context) {
    requireAudioStimulus();

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

      const warmupCursor = readLiveKitLogCursor(env);
      await speakText(idleWarmupPrompt, env);
      await waitForLiveKitLogEvidence(env, presenceResponsePattern, 90_000, {
        after: warmupCursor,
      });

      // Idle long enough for Cartesia to kill an unused pooled socket
      // server-side. The Appium newCommandTimeout is 240s, so a silent pause
      // is safe.
      await browser.pause(idlePauseMs);

      const idleCursor = readLiveKitLogCursor(env);
      await speakText(idleFollowUpPrompt, env);
      await waitForLiveKitLogEvidence(env, presenceResponsePattern, 90_000, {
        after: idleCursor,
      });
      await waitForLiveKitLogEvidence(env, firstAudioPattern, 30_000, {
        after: idleCursor,
      });

      // Give any teardown error a moment to be logged, then require that the
      // post-idle reply never hit a dead pooled websocket.
      await browser.pause(2_000);
      const failure = findLiveKitLogEvidence(env, ttsFailurePattern, {
        after: idleCursor,
      });
      if (failure) {
        throw new Error(
          `Post-idle reply hit a TTS connection failure: ${failure.matchedText}`,
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
