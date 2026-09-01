import { existsSync, readFileSync } from "node:fs";
import { dirname, isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const supportDir = dirname(fileURLToPath(import.meta.url));
export const packageRoot = resolve(supportDir, "..");
export const workspaceRoot = resolve(packageRoot, "../..");

export type DeviceEnv = {
  udid: string;
  deviceName: string;
  platformVersion?: string;
  bundleId: string;
  appPath?: string;
  xcodeOrgId?: string;
  xcodeSigningId: string;
  wdaBundleId?: string;
  appiumHost: string;
  appiumPort: number;
  appiumLogLevel: "trace" | "debug" | "info" | "warn" | "error" | "silent";
  enableAudioStimulus: boolean;
  audioPhrase: string;
  cartesiaApiKey?: string;
  cartesiaVoiceId: string;
  cartesiaModelId: string;
  cartesiaVersion: string;
  allowRealCodex: boolean;
  confirmRealCodex: boolean;
  ttsCommand?: string;
  livekitLogPath: string;
  livekitLogLookbackMs: number;
  enableSttAssertions: boolean;
};

type LoadOptions = {
  requirePhysicalDevice?: boolean;
};

export function loadDeviceEnv(options: LoadOptions = {}): DeviceEnv {
  loadDotenv(resolve(packageRoot, ".env"));

  const env: DeviceEnv = {
    udid: readEnv("OPENBASE_IOS_UDID", ""),
    deviceName: readEnv("OPENBASE_IOS_DEVICE_NAME", "iPhone"),
    platformVersion: optionalEnv("OPENBASE_IOS_PLATFORM_VERSION"),
    bundleId: readEnv("OPENBASE_IOS_BUNDLE_ID", "com.openbase.coder.field-test"),
    appPath: optionalPathEnv("OPENBASE_IOS_APP_PATH"),
    xcodeOrgId: optionalEnv("OPENBASE_IOS_XCODE_ORG_ID"),
    xcodeSigningId: readEnv("OPENBASE_IOS_XCODE_SIGNING_ID", "iPhone Developer"),
    wdaBundleId: optionalEnv("OPENBASE_IOS_WDA_BUNDLE_ID"),
    appiumHost: readEnv("OPENBASE_E2E_APPIUM_HOST", "127.0.0.1"),
    appiumPort: readIntegerEnv("OPENBASE_E2E_APPIUM_PORT", 4723),
    appiumLogLevel: readLogLevel("OPENBASE_E2E_APPIUM_LOG_LEVEL", "info"),
    enableAudioStimulus: readBooleanEnv("OPENBASE_E2E_ENABLE_AUDIO_STIMULUS", false),
    audioPhrase: readEnv("OPENBASE_E2E_AUDIO_PHRASE", "hello openbase"),
    cartesiaApiKey: optionalEnv("OPENBASE_E2E_CARTESIA_API_KEY") ?? optionalEnv("CARTESIA_API_KEY"),
    cartesiaVoiceId: readEnv(
      "OPENBASE_E2E_CARTESIA_VOICE_ID",
      readEnv("CARTESIA_VOICE_ID", "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"),
    ),
    cartesiaModelId: readEnv("OPENBASE_E2E_CARTESIA_MODEL_ID", "sonic-3.5"),
    cartesiaVersion: readEnv("OPENBASE_E2E_CARTESIA_VERSION", "2026-03-01"),
    allowRealCodex: readBooleanEnv("OPENBASE_E2E_ALLOW_REAL_CODEX", false),
    confirmRealCodex: readBooleanEnv("OPENBASE_E2E_CONFIRM_REAL_CODEX", false),
    ttsCommand: optionalEnv("OPENBASE_E2E_TTS_COMMAND"),
    livekitLogPath: resolveGeneralPath(readEnv("OPENBASE_E2E_LIVEKIT_LOG_PATH", "~/.openbase/logs/livekit-agent.log")),
    livekitLogLookbackMs: readIntegerEnv("OPENBASE_E2E_LIVEKIT_LOG_LOOKBACK_MS", 120_000),
    enableSttAssertions: readBooleanEnv("OPENBASE_E2E_ENABLE_STT_ASSERTIONS", false),
  };

  if (options.requirePhysicalDevice && !env.udid.trim()) {
    throw new Error("OPENBASE_IOS_UDID is required for physical iPhone E2E runs.");
  }

  return env;
}

function loadDotenv(path: string): void {
  if (!existsSync(path)) {
    return;
  }

  const content = readFileSync(path, "utf8");
  for (const line of content.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) {
      continue;
    }

    const equalsAt = trimmed.indexOf("=");
    if (equalsAt === -1) {
      continue;
    }

    const key = trimmed.slice(0, equalsAt).trim();
    const value = trimmed.slice(equalsAt + 1).trim().replace(/^["']|["']$/g, "");
    if (key && process.env[key] === undefined) {
      process.env[key] = value;
    }
  }
}

function readEnv(name: string, fallback: string): string {
  const value = process.env[name];
  return value === undefined || value === "" ? fallback : value;
}

function optionalEnv(name: string): string | undefined {
  const value = process.env[name];
  return value === undefined || value === "" ? undefined : value;
}

function optionalPathEnv(name: string): string | undefined {
  const value = optionalEnv(name);
  if (!value) {
    return undefined;
  }
  return isAbsolute(value) ? value : resolve(packageRoot, value);
}

function readIntegerEnv(name: string, fallback: number): number {
  const raw = readEnv(name, String(fallback));
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed) || parsed < 0) {
    throw new Error(`${name} must be a non-negative integer.`);
  }
  return parsed;
}

function readBooleanEnv(name: string, fallback: boolean): boolean {
  const raw = optionalEnv(name);
  if (raw === undefined) {
    return fallback;
  }
  return ["1", "true", "yes", "on"].includes(raw.toLowerCase());
}

function readLogLevel(name: string, fallback: DeviceEnv["appiumLogLevel"]): DeviceEnv["appiumLogLevel"] {
  const value = readEnv(name, fallback);
  const allowed = ["trace", "debug", "info", "warn", "error", "silent"] as const;
  if (!allowed.includes(value as DeviceEnv["appiumLogLevel"])) {
    throw new Error(`${name} must be one of ${allowed.join(", ")}.`);
  }
  return value as DeviceEnv["appiumLogLevel"];
}

function resolveGeneralPath(value: string): string {
  if (value === "~") {
    return process.env.HOME ?? value;
  }
  if (value.startsWith("~/")) {
    return resolve(process.env.HOME ?? ".", value.slice(2));
  }
  return isAbsolute(value) ? value : resolve(packageRoot, value);
}
