import { existsSync, readFileSync, statSync } from "node:fs";
import type { DeviceEnv } from "../deviceEnv.js";

export type LogMatch = {
  path: string;
  matchedText: string;
};

export type LogCursor = {
  path: string;
  byteOffset: number;
};

type EvidenceOptions = {
  after?: LogCursor;
};

export function readLiveKitLogCursor(env: DeviceEnv): LogCursor {
  if (!existsSync(env.livekitLogPath)) {
    return { path: env.livekitLogPath, byteOffset: 0 };
  }

  const stats = statSync(env.livekitLogPath);
  return { path: env.livekitLogPath, byteOffset: stats.size };
}

export function readRecentLiveKitLog(env: DeviceEnv, after?: LogCursor): string {
  if (!existsSync(env.livekitLogPath)) {
    return "";
  }

  const stats = statSync(env.livekitLogPath);
  const ageMs = Date.now() - stats.mtimeMs;
  if (ageMs > env.livekitLogLookbackMs) {
    return "";
  }

  const content = readFileSync(env.livekitLogPath);
  if (!after || after.path !== env.livekitLogPath || after.byteOffset <= 0) {
    return content.toString("utf8");
  }

  const byteOffset = Math.min(after.byteOffset, content.length);
  return content.subarray(byteOffset).toString("utf8");
}

export function findLiveKitLogEvidence(
  env: DeviceEnv,
  pattern: string | RegExp,
  options: EvidenceOptions = {},
): LogMatch | null {
  const content = readRecentLiveKitLog(env, options.after);
  if (!content) {
    return null;
  }

  const expression = typeof pattern === "string" ? escapeRegExp(pattern) : pattern;
  const match = content.match(expression);
  if (!match) {
    return null;
  }

  return {
    path: env.livekitLogPath,
    matchedText: match[0],
  };
}

export function assertLiveKitLogEvidence(
  env: DeviceEnv,
  pattern: string | RegExp,
  options: EvidenceOptions = {},
): LogMatch {
  const match = findLiveKitLogEvidence(env, pattern, options);
  if (!match) {
    throw new Error(
      `Expected LiveKit log evidence for ${String(pattern)} in recent log ${env.livekitLogPath}. `
        + "Prefer this log assertion over STT unless this is specifically a pronunciation/audio-quality test.",
    );
  }
  return match;
}

export async function waitForLiveKitLogEvidence(
  env: DeviceEnv,
  pattern: string | RegExp,
  timeoutMs = 60_000,
  options: EvidenceOptions = {},
): Promise<LogMatch> {
  const startedAt = Date.now();
  let lastMatch: LogMatch | null = null;

  while (Date.now() - startedAt < timeoutMs) {
    lastMatch = findLiveKitLogEvidence(env, pattern, options);
    if (lastMatch) {
      return lastMatch;
    }
    await new Promise(resolve => setTimeout(resolve, 500));
  }

  throw new Error(
    `Timed out waiting for LiveKit log evidence for ${String(pattern)} in ${env.livekitLogPath}. `
      + "This assertion reads logs only; it does not invoke STT.",
  );
}

function escapeRegExp(value: string): RegExp {
  return new RegExp(value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
}
