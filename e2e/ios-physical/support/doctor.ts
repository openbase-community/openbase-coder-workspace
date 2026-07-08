import { accessSync, constants } from "node:fs";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { detectCloudTarget } from "./cloudTarget.js";
import { loadDeviceEnv, workspaceRoot } from "./deviceEnv.js";
import { readNormalDispatcherReasoning, readNormalSuperAgentsReasoning } from "./dispatcherSettings.js";
import { assertConfiguredPhysicalIosDevice } from "./iosDevices.js";
import { detectRuntimeTarget } from "./runtimeTarget.js";

type Check = {
  name: string;
  ok: boolean;
  detail: string;
};

const checks: Check[] = [];
const env = loadDeviceEnv();

checks.push(commandCheck("node", ["--version"]));
checks.push(commandCheck("pnpm", ["--version"]));
checks.push(commandCheck("xcodebuild", ["-version"]));
checks.push(commandCheck("xcrun", ["xctrace", "list", "devices"]));
checks.push(commandCheck("appium", ["--version"]));
checks.push(commandCheck("tailscale", ["status"], { optional: true }));
checks.push(fileCheck("workspace root", workspaceRoot));
checks.push(fileCheck("iOS Tuist project", resolve(workspaceRoot, "ios/Project.swift")));
checks.push(envCheck("OPENBASE_IOS_UDID", env.udid, true));
checks.push(envCheck("OPENBASE_IOS_DEVICE_NAME", env.deviceName, true));
checks.push(envCheck("OPENBASE_IOS_BUNDLE_ID", env.bundleId, true));
checks.push(envCheck("OPENBASE_IOS_XCODE_ORG_ID", env.xcodeOrgId ?? "", false));
checks.push(physicalIosDeviceCheck());
checks.push(runtimeTargetCheck());
checks.push(cloudTargetCheck());

if (env.appPath) {
  checks.push(fileCheck("OPENBASE_IOS_APP_PATH", env.appPath));
}

checks.push({
  name: "real Codex home mode",
  ok: true,
  detail: "using normal Codex/Openbase homes from the current shell and installed services",
});
checks.push(dispatcherReasoningCheck());
checks.push(superAgentsReasoningCheck());
checks.push({
  name: "Mac audio stimulus provider",
  ok: !env.enableAudioStimulus || Boolean(env.cartesiaApiKey),
  detail: env.cartesiaApiKey
    ? `Cartesia ${env.cartesiaModelId} voice ${env.cartesiaVoiceId}`
    : "Cartesia key missing; required only when OPENBASE_E2E_ENABLE_AUDIO_STIMULUS=1",
});

const failures = checks.filter(check => !check.ok);
for (const check of checks) {
  console.log(`${check.ok ? "OK " : "ERR"} ${check.name}: ${check.detail}`);
}

if (failures.length > 0) {
  console.error(`\n${failures.length} E2E doctor check(s) failed.`);
  process.exitCode = 1;
}

function commandCheck(name: string, args: string[], options: { optional?: boolean } = {}): Check {
  const result = spawnSync(name, args, { encoding: "utf8" });
  if (result.status === 0) {
    return { name, ok: true, detail: firstLine(result.stdout || result.stderr) };
  }

  return {
    name,
    ok: Boolean(options.optional),
    detail: options.optional ? "not available; optional for local runs" : firstLine(result.stderr || result.stdout || "command failed"),
  };
}

function fileCheck(name: string, path: string): Check {
  try {
    accessSync(path, constants.R_OK);
    return { name, ok: true, detail: path };
  } catch {
    return { name, ok: false, detail: `${path} is not readable` };
  }
}

function envCheck(name: string, value: string, required: boolean): Check {
  if (value.trim()) {
    return { name, ok: true, detail: "set" };
  }

  return {
    name,
    ok: !required,
    detail: required ? "missing" : "not set; may be required for physical WebDriverAgent signing",
  };
}

function dispatcherReasoningCheck(): Check {
  try {
    const { path, reasoningEffort } = readNormalDispatcherReasoning();
    return {
      name: "normal dispatcher reasoning",
      ok: reasoningEffort === "low",
      detail: `${String(reasoningEffort)} in ${path}`,
    };
  } catch (error) {
    return {
      name: "normal dispatcher reasoning",
      ok: false,
      detail: error instanceof Error ? error.message : String(error),
    };
  }
}

function superAgentsReasoningCheck(): Check {
  try {
    const { path, reasoningEffort } = readNormalSuperAgentsReasoning();
    return {
      name: "normal Super Agents reasoning",
      ok: reasoningEffort === "low",
      detail: `${String(reasoningEffort)} in ${path}`,
    };
  } catch (error) {
    return {
      name: "normal Super Agents reasoning",
      ok: false,
      detail: error instanceof Error ? error.message : String(error),
    };
  }
}

function physicalIosDeviceCheck(): Check {
  try {
    const device = assertConfiguredPhysicalIosDevice(env);
    return {
      name: "physical iOS device",
      ok: true,
      detail: `${device.name} (${device.udid})`,
    };
  } catch (error) {
    return {
      name: "physical iOS device",
      ok: false,
      detail: error instanceof Error ? error.message : String(error),
    };
  }
}

function runtimeTargetCheck(): Check {
  try {
    const target = detectRuntimeTarget();
    return {
      name: "Openbase runtime target",
      ok: target.ok,
      detail: target.detail,
    };
  } catch (error) {
    return {
      name: "Openbase runtime target",
      ok: false,
      detail: error instanceof Error ? error.message : String(error),
    };
  }
}

function cloudTargetCheck(): Check {
  try {
    const target = detectCloudTarget();
    return {
      name: "Openbase cloud target",
      ok: target.ok,
      detail: target.detail,
    };
  } catch (error) {
    return {
      name: "Openbase cloud target",
      ok: false,
      detail: error instanceof Error ? error.message : String(error),
    };
  }
}

function firstLine(value: string): string {
  return value.trim().split(/\r?\n/)[0] || "ok";
}
