import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

export type VoiceRouteState = {
  active_route?: string;
  active_target_label?: string | null;
  active_target_thread_id?: string | null;
  active_target_voice_name?: string | null;
  dispatcher_thread_id?: string | null;
};

const routeStatePath = resolve(process.env.HOME ?? ".", ".openbase/livekit-voice-route.json");

export function readVoiceRouteState(): VoiceRouteState {
  if (!existsSync(routeStatePath)) {
    return {};
  }

  const parsed = JSON.parse(readFileSync(routeStatePath, "utf8")) as unknown;
  if (typeof parsed !== "object" || parsed === null) {
    return {};
  }
  return parsed as VoiceRouteState;
}

export async function waitForVoiceRoute(
  expectedRoute: "dispatcher" | "target",
  timeoutMs: number,
  labelPattern?: RegExp,
): Promise<VoiceRouteState> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const state = readVoiceRouteState();
    const activeRoute = state.active_route ?? (state.active_target_thread_id ? "target" : "dispatcher");
    const label = state.active_target_label ?? "";
    if (activeRoute === expectedRoute && (!labelPattern || labelPattern.test(label))) {
      return state;
    }
    await new Promise(resolve => setTimeout(resolve, 500));
  }

  throw new Error(`Timed out waiting for voice route ${expectedRoute}`);
}
