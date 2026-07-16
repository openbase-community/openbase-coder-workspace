import { $, browser, expect } from "@wdio/globals";
import type { DeviceEnv } from "./deviceEnv.js";

export async function activateOpenbaseApp(env: DeviceEnv): Promise<void> {
  await browser.activateApp(env.bundleId);
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

export async function openCallSurfaceIfAvailable(): Promise<boolean> {
  const selectors = ["~nav.call", "~Call", "~Open Call", "~Open call"];
  for (const selector of selectors) {
    const element = await $(selector);
    if (await element.isExisting()) {
      await element.click();
      return true;
    }
  }
  return false;
}

export async function openCallSurface(): Promise<void> {
  const opened = await openCallSurfaceIfAvailable();
  if (!opened) {
    const source = await browser.getPageSource();
    throw new Error(`Unable to open call surface. Expected nav.call or Call control. Page source excerpt: ${source.slice(0, 1000)}`);
  }
}

export async function startCallIfAvailable(): Promise<boolean> {
  const selectors = ["~call.start", "~Start", "~Start call", "~Call"];
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
