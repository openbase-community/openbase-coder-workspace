import { buildCapabilities } from "./support/capabilities.js";
import { assertExpectedCloudTarget, detectCloudTarget } from "./support/cloudTarget.js";
import { loadDeviceEnv } from "./support/deviceEnv.js";
import { assertNormalDispatcherReasoningIsLow } from "./support/dispatcherSettings.js";
import { assertConfiguredPhysicalIosDevice } from "./support/iosDevices.js";
import { assertExpectedRuntimeTarget, detectRuntimeTarget } from "./support/runtimeTarget.js";

const env = loadDeviceEnv({ requirePhysicalDevice: true });
if (!env.allowRealCodex || !env.confirmRealCodex) {
  throw new Error(
    "Refusing to start physical E2E: set OPENBASE_E2E_ALLOW_REAL_CODEX=1 and "
      + "OPENBASE_E2E_CONFIRM_REAL_CODEX=1. This test uses real Openbase/Codex/LiveKit services.",
  );
}
assertConfiguredPhysicalIosDevice(env);
assertExpectedRuntimeTarget();
assertExpectedCloudTarget();
assertNormalDispatcherReasoningIsLow();
const cloudTarget = detectCloudTarget();
const runtimeTarget = detectRuntimeTarget();

console.warn(
  [
    "",
    "[manual-only] Openbase iOS physical E2E is running.",
    "This spec drives Gabe's physical iPhone and uses real Openbase/Codex/LiveKit services.",
    `Openbase runtime target: ${runtimeTarget.detail}.`,
    `Openbase cloud target: ${cloudTarget.detail}.`,
    "The runner refuses to start unless the normal dispatcher reasoning setting is low.",
    "Run only when explicitly instructed.",
    "",
  ].join("\n"),
);

export const config = {
  runner: "local",
  specs: [
    "./specs/basic-call-response.real-codex.spec.ts",
    "./specs/superagent-own-name.real-codex.spec.ts",
    "./specs/parallel-agents-truth.real-codex.spec.ts",
    "./specs/orphaned-answer-recovery.real-codex.spec.ts",
    "./specs/double-turn-commit-diagnosis.real-codex.spec.ts",
  ],
  suites: {
    basicCallResponse: ["./specs/basic-call-response.real-codex.spec.ts"],
    superagentOwnName: ["./specs/superagent-own-name.real-codex.spec.ts"],
    parallelAgentsTruth: ["./specs/parallel-agents-truth.real-codex.spec.ts"],
    orphanedAnswerRecovery: ["./specs/orphaned-answer-recovery.real-codex.spec.ts"],
    doubleTurnCommitDiagnosis: ["./specs/double-turn-commit-diagnosis.real-codex.spec.ts"],
  },
  maxInstances: 1,
  logLevel: env.appiumLogLevel,
  bail: 0,
  waitforTimeout: 30_000,
  connectionRetryTimeout: 180_000,
  connectionRetryCount: 1,
  hostname: env.appiumHost,
  port: env.appiumPort,
  path: "/",
  framework: "mocha",
  reporters: ["spec"],
  mochaOpts: {
    ui: "bdd",
    timeout: 10 * 60 * 1000,
  },
  services: [
    [
      "appium",
      {
        command: "appium",
        args: {
          address: env.appiumHost,
          port: env.appiumPort,
          logLevel: env.appiumLogLevel,
        },
      },
    ],
  ],
  capabilities: [buildCapabilities(env)],
};
