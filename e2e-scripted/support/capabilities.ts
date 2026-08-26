import type { DeviceEnv } from "./deviceEnv.js";

export function buildCapabilities(env: DeviceEnv): Record<string, unknown> {
  return {
    platformName: "iOS",
    "appium:automationName": "XCUITest",
    "appium:udid": env.udid,
    "appium:deviceName": env.deviceName,
    "appium:platformVersion": env.platformVersion,
    "appium:noReset": true,
    "appium:newCommandTimeout": 240,
    "appium:xcodeSigningId": env.xcodeSigningId,
    ...(env.xcodeOrgId ? { "appium:xcodeOrgId": env.xcodeOrgId } : {}),
    ...(env.wdaBundleId ? { "appium:updatedWDABundleId": env.wdaBundleId } : {}),
    ...(env.appPath ? { "appium:app": env.appPath } : { "appium:bundleId": env.bundleId }),
  };
}
