import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { classifyConfiguredIosDevice, parseXctraceIosDevices } from "./iosDevices.js";

const physicalUdid = "00008110-0012345678901234";
const simulatorUdid = "11111111-2222-3333-4444-555555555555";

const xctraceOutput = `
== Devices ==
Developer MacBook Pro (16.0) (00006000-0000000000000000)
Developer iPhone (18.5) (${physicalUdid})

== Simulators ==
iPhone 16 Pro (18.5) (${simulatorUdid}) (Shutdown)
`;

describe("iOS E2E device selection", () => {
  it("selects a configured physical iOS device from the devices section", () => {
    const configured = classifyConfiguredIosDevice(xctraceOutput, physicalUdid);

    assert.equal(configured.kind, "physical");
    assert.equal(configured.device.udid, physicalUdid);
  });

  it("refuses a configured simulator UDID instead of treating it as a device", () => {
    const configured = classifyConfiguredIosDevice(xctraceOutput, simulatorUdid);

    assert.equal(configured.kind, "simulator");
    assert.equal(configured.device.udid, simulatorUdid);
  });

  it("does not fall back to a simulator when the configured physical device is missing", () => {
    assert.deepEqual(classifyConfiguredIosDevice(xctraceOutput, "missing-udid"), { kind: "missing" });
  });

  it("parses only devices and simulators from xctrace output", () => {
    const devices = parseXctraceIosDevices(xctraceOutput);

    assert.deepEqual(
      devices.map(device => [device.section, device.name, device.udid]),
      [
        ["devices", "Developer MacBook Pro", "00006000-0000000000000000"],
        ["devices", "Developer iPhone", physicalUdid],
        ["simulators", "iPhone 16 Pro", simulatorUdid],
      ],
    );
  });
});
