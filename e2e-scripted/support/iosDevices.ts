import { execFileSync } from "node:child_process";
import type { DeviceEnv } from "./deviceEnv.js";

export type ListedIosDevice = {
  name: string;
  udid: string;
  section: "devices" | "simulators";
  line: string;
};

export type ConfiguredIosDevice =
  | { kind: "physical"; device: ListedIosDevice }
  | { kind: "simulator"; device: ListedIosDevice }
  | { kind: "missing" };

export function assertConfiguredPhysicalIosDevice(env: DeviceEnv): ListedIosDevice {
  const output = execFileSync("xcrun", ["xctrace", "list", "devices"], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
  const configured = classifyConfiguredIosDevice(output, env.udid);

  if (configured.kind === "physical") {
    return configured.device;
  }

  if (configured.kind === "simulator") {
    throw new Error(
      `Refusing to start iOS E2E on simulator ${configured.device.name} (${env.udid}). `
        + "Set OPENBASE_IOS_UDID to a physical iPhone or iPad UDID.",
    );
  }

  throw new Error(
    `No physical iOS device found for OPENBASE_IOS_UDID=${env.udid}. `
      + "The iOS E2E runner will not select or fall back to an iOS simulator.",
  );
}

export function classifyConfiguredIosDevice(output: string, udid: string): ConfiguredIosDevice {
  const trimmedUdid = udid.trim();
  if (!trimmedUdid) {
    return { kind: "missing" };
  }

  const devices = parseXctraceIosDevices(output);
  const physical = devices.find(device => device.section === "devices" && device.udid === trimmedUdid);
  if (physical) {
    return { kind: "physical", device: physical };
  }

  const simulator = devices.find(device => device.section === "simulators" && device.udid === trimmedUdid);
  if (simulator) {
    return { kind: "simulator", device: simulator };
  }

  return { kind: "missing" };
}

export function parseXctraceIosDevices(output: string): ListedIosDevice[] {
  const devices: ListedIosDevice[] = [];
  let section: ListedIosDevice["section"] | undefined;

  for (const rawLine of output.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      continue;
    }

    const heading = /^==\s*(.+?)\s*==$/.exec(line);
    if (heading) {
      const title = heading[1].toLowerCase();
      section = title === "devices" || title === "simulators" ? title : undefined;
      continue;
    }

    if (!section) {
      continue;
    }

    const device = parseDeviceLine(line, section);
    if (device) {
      devices.push(device);
    }
  }

  return devices;
}

function parseDeviceLine(line: string, section: ListedIosDevice["section"]): ListedIosDevice | undefined {
  const match = /^(.*?)\s+\([^()]*\)\s+\(([0-9A-Fa-f-]{8,})\)(?:\s+\([^()]*\))?$/.exec(line);
  if (!match) {
    return undefined;
  }

  return {
    name: match[1],
    udid: match[2],
    section,
    line,
  };
}
