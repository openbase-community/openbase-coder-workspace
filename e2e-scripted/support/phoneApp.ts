import { $, browser, expect } from "@wdio/globals";
import type { DeviceEnv } from "./deviceEnv.js";

export async function activateOpenbaseApp(env: DeviceEnv): Promise<void> {
  await browser.activateApp(env.bundleId);
}

export async function relaunchOpenbaseApp(env: DeviceEnv): Promise<void> {
  // A previous session can leave the app on a screen without the expected
  // call controls; terminate and relaunch so tests start from the root UI.
  await browser.terminateApp(env.bundleId);
  await browser.pause(1_000);
  await browser.activateApp(env.bundleId);
  await browser.pause(2_000);
}

export async function expectOpenbaseForeground(env: DeviceEnv): Promise<void> {
  const activeApp = await browser.execute("mobile: activeAppInfo");
  const bundleId = readBundleId(activeApp);
  expect(bundleId).toBe(env.bundleId);
}

export async function configureBackendIfUiIsAvailable(baseUrl: string): Promise<boolean> {
  const candidateFields = [
    "~settings.backend.host",
    "~Backend host",
    "~Server host",
    "~Tailscale DNS name, IP address, or hostname",
  ];
  const candidateButtons = ["~settings.backend.add", "~Save", "~Add", "~Connect"];

  for (const selector of candidateFields) {
    const field = await $(selector);
    if (!(await field.isExisting())) {
      continue;
    }

    await field.setValue(baseUrl);
    for (const buttonSelector of candidateButtons) {
      const button = await $(buttonSelector);
      if (await button.isExisting()) {
        await button.click();
        return true;
      }
    }
    return true;
  }

  return false;
}

// There is no separate Call page any more: calls start from the composer on
// the chat screen (call.start) and are controlled from the same composer
// (call.mute / call.unmute / call.end); speaker lives in the call settings
// sheet behind call.settings.
const CALL_SURFACE_MARKERS = ["~call.start", "~call.end", "~call.settings"];

async function anyExists(selectors: string[]): Promise<boolean> {
  for (const selector of selectors) {
    if (await (await $(selector)).isExisting()) {
      return true;
    }
  }
  return false;
}

export async function openCallSurfaceIfAvailable(): Promise<boolean> {
  if (await anyExists(CALL_SURFACE_MARKERS)) {
    return true;
  }
  // Elsewhere in the app: open the drawer and choose "New chat".
  for (const selector of ["~nav.open-sidebar", "~Open sidebar", "~Menu"]) {
    const menu = await $(selector);
    if (await menu.isExisting()) {
      await menu.click();
      break;
    }
  }
  for (const selector of ["~nav.home", "~New chat", 'android=new UiSelector().text("New chat")']) {
    const newChat = await $(selector);
    if (await newChat.isExisting()) {
      await newChat.click();
      await browser.pause(500);
      break;
    }
  }
  return anyExists(CALL_SURFACE_MARKERS);
}

export async function openCallSurface(): Promise<void> {
  const opened = await openCallSurfaceIfAvailable();
  if (!opened) {
    const source = await browser.getPageSource();
    throw new Error(`Unable to open the new-chat home. Expected call.start, call.end, nav.home, or New chat. Page source excerpt: ${source.slice(0, 1000)}`);
  }
}

export async function startCallIfAvailable(): Promise<boolean> {
  const selectors = ["~call.start", "~Start call", "~Start"];
  for (const selector of selectors) {
    const element = await $(selector);
    if (await element.isExisting()) {
      await element.click();
      return true;
    }
  }
  return false;
}

export async function startCall(): Promise<void> {
  const started = await startCallIfAvailable();
  if (!started) {
    const source = await browser.getPageSource();
    throw new Error(`Unable to start call. Expected call.start or Start control. Page source excerpt: ${source.slice(0, 1000)}`);
  }
}

export async function enableSpeakerIfAvailable(): Promise<boolean> {
  // Calls start in receiver mode; one tap of the speaker toggle routes call
  // audio to the loudspeaker so a human observer can follow the test. The
  // toggle sits in the call settings sheet, opened from the chat header.
  let speakerButton = await $("~call.speaker");
  let openedSettings = false;
  if (!(await speakerButton.isExisting())) {
    const settings = await $("~call.settings");
    if (!(await settings.isExisting())) {
      return false;
    }
    await settings.click();
    await browser.pause(500);
    openedSettings = true;
    speakerButton = await $("~call.speaker");
  }
  if (!(await speakerButton.isExisting())) {
    return false;
  }
  await speakerButton.click();
  if (openedSettings) {
    await closeCallSettingsIfOpen();
  }
  return true;
}

async function closeCallSettingsIfOpen(): Promise<void> {
  for (const selector of ["~call.settings-done", "~Done", "~Close"]) {
    const button = await $(selector);
    if (await button.isExisting()) {
      await button.click();
      await browser.pause(300);
      return;
    }
  }
}

export type CallMuteState = "muted" | "unmuted" | "unknown";

export async function readCallMuteState(): Promise<CallMuteState> {
  // The call surface exposes the mute toggle as call.unmute while muted and
  // call.mute while unmuted.
  const unmuteButton = await $("~call.unmute");
  if (await unmuteButton.isExisting()) {
    return "muted";
  }
  const muteButton = await $("~call.mute");
  if (await muteButton.isExisting()) {
    return "unmuted";
  }
  return "unknown";
}

export async function unmuteCallIfMuted(): Promise<boolean> {
  const unmuteButton = await $("~call.unmute");
  if (await unmuteButton.isExisting()) {
    await unmuteButton.click();
    return true;
  }
  return false;
}

export async function waitForCallMuteState(
  expected: CallMuteState,
  timeoutMs: number,
): Promise<CallMuteState> {
  const startedAt = Date.now();
  let lastState: CallMuteState = "unknown";
  while (Date.now() - startedAt < timeoutMs) {
    lastState = await readCallMuteState();
    if (lastState === expected) {
      return lastState;
    }
    await browser.pause(500);
  }
  return lastState;
}

export async function endCallIfAvailable(): Promise<boolean> {
  const selectors = ["~call.end", "~End", "~End call", "~Hang up", "~Hang Up", "~Disconnect"];
  for (const selector of selectors) {
    const element = await $(selector);
    if (await element.isExisting()) {
      await element.click();
      return true;
    }
  }
  return false;
}

export async function endCall(): Promise<void> {
  const ended = await endCallIfAvailable();
  if (!ended) {
    const source = await browser.getPageSource();
    throw new Error(`Unable to end call. Expected call.end, End, or Hang up control. Page source excerpt: ${source.slice(0, 1000)}`);
  }
}

function readBundleId(activeApp: unknown): string | undefined {
  if (typeof activeApp !== "object" || activeApp === null) {
    return undefined;
  }

  const record = activeApp as Record<string, unknown>;
  return typeof record.bundleId === "string" ? record.bundleId : undefined;
}
