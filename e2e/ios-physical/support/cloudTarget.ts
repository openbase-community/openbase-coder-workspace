import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

type CloudTarget = {
  ok: boolean;
  detail: string;
};

const productionWebBackend = "https://app.openbase.cloud";

export function detectCloudTarget(): CloudTarget {
  const env = readOpenbaseEnv();
  const actualWebBackend = normalizeUrl(
    env.OPENBASE_CODER_CLI_WEB_BACKEND_URL || productionWebBackend,
  );
  const actualCodingBackend = normalizeCodingBackend(env.OPENBASE_CODING_BACKEND || "codex");
  const expectedWebBackend = normalizeUrl(process.env.OPENBASE_E2E_EXPECT_WEB_BACKEND || "");
  const expectedCodingBackend = normalizeCodingBackend(process.env.OPENBASE_E2E_EXPECT_CODING_BACKEND || "");

  const failures: string[] = [];
  if (expectedWebBackend && actualWebBackend !== expectedWebBackend) {
    failures.push(`web backend ${actualWebBackend || "(unset)"} != ${expectedWebBackend}`);
  }
  if (expectedCodingBackend && actualCodingBackend !== expectedCodingBackend) {
    failures.push(`coding backend ${actualCodingBackend || "(unset)"} != ${expectedCodingBackend}`);
  }

  const detail = [
    `web backend ${actualWebBackend || "(unset)"}`,
    `coding backend ${actualCodingBackend || "(unset)"}`,
    expectedWebBackend ? `expected web backend ${expectedWebBackend}` : "",
    expectedCodingBackend ? `expected coding backend ${expectedCodingBackend}` : "",
  ].filter(Boolean).join("; ");

  return {
    ok: failures.length === 0,
    detail: failures.length === 0 ? detail : `${detail}; ${failures.join("; ")}`,
  };
}

export function assertExpectedCloudTarget(): void {
  const target = detectCloudTarget();
  if (!target.ok) {
    throw new Error(`Openbase cloud target check failed: ${target.detail}`);
  }
}

function readOpenbaseEnv(): Record<string, string> {
  const home = process.env.HOME;
  if (!home) {
    return {};
  }

  const envPath = resolve(home, ".openbase/.env");
  if (!existsSync(envPath)) {
    return {};
  }

  const env: Record<string, string> = {};
  for (const line of readFileSync(envPath, "utf8").split(/\r?\n/)) {
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
    env[key] = value;
  }
  return env;
}

function normalizeUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

function normalizeCodingBackend(value: string): string {
  return value.trim().replace(/-/g, "_");
}
