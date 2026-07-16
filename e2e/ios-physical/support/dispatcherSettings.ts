import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

export const expectedDispatcherReasoning = "low";
export const expectedSuperAgentsReasoning = "low";

export function assertNormalDispatcherReasoningIsLow(): void {
  const { path, reasoningEffort } = readNormalDispatcherReasoning();
  if (reasoningEffort !== expectedDispatcherReasoning) {
    throw new Error(
      `Refusing to start physical E2E: normal dispatcher reasoning is ${JSON.stringify(reasoningEffort)} in ${path}. `
        + `It must be "${expectedDispatcherReasoning}".`,
    );
  }
}

export function readNormalDispatcherReasoning(): { path: string; reasoningEffort: unknown } {
  const path = normalDispatcherConfigPath();
  if (!existsSync(path)) {
    throw new Error(
      `Refusing to start physical E2E: dispatcher config is missing at ${path}. `
        + `Set dispatcher_reasoning_effort to "${expectedDispatcherReasoning}" in the normal Openbase settings first.`,
    );
  }

  const config = readJsonObject(path);
  return { path, reasoningEffort: config.dispatcher_reasoning_effort };
}

export function assertNormalSuperAgentsReasoningIsLow(): void {
  const { path, reasoningEffort } = readNormalSuperAgentsReasoning();
  if (reasoningEffort !== expectedSuperAgentsReasoning) {
    throw new Error(
      `Refusing to start physical E2E: normal Super Agents reasoning is ${JSON.stringify(reasoningEffort)} in ${path}. `
        + `It must be "${expectedSuperAgentsReasoning}".`,
    );
  }
}

export function readNormalSuperAgentsReasoning(): { path: string; reasoningEffort: unknown } {
  const path = normalDispatcherConfigPath();
  if (!existsSync(path)) {
    throw new Error(
      `Refusing to start physical E2E: dispatcher config is missing at ${path}. `
        + `Set super_agents_reasoning_effort to "${expectedSuperAgentsReasoning}" in the normal Openbase settings first.`,
    );
  }

  const config = readJsonObject(path);
  return { path, reasoningEffort: config.super_agents_reasoning_effort };
}

export function normalDispatcherConfigPath(): string {
  return resolve(process.env.HOME ?? ".", ".openbase/dispatcher-config.json");
}

function readJsonObject(path: string): Record<string, unknown> {
  const value = JSON.parse(readFileSync(path, "utf8")) as unknown;
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`Refusing to start physical E2E: dispatcher config at ${path} is not a JSON object.`);
  }
  return value as Record<string, unknown>;
}
