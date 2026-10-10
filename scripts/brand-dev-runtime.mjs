import { execFileSync } from "node:child_process";
import { constants, copyFileSync, cpSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const STAMP = "Contents/Resources/.openbase-dev-runtime";
const PLIST_BUDDY = "/usr/libexec/PlistBuddy";

// macOS takes the menu-bar app name from the running bundle's Info.plist before
// any app code runs, so app.setName cannot rename an unpackaged Electron. The
// upstream node_modules bundle stays untouched: this publishes a separate
// branded clone beside the desktop build output, re-signed as a whole, and
// rebuilds it only when the source runtime changes.
export function brandedRuntimeStamp(source, version) {
  return `${realpathSync(source)}\n${version}\n`;
}

export function prepareBrandedRuntime(source, incoming, { icon, version, run = execFileSync }) {
  // Clone on APFS (no extra disk), copy elsewhere; keep framework symlinks.
  cpSync(source, incoming, { recursive: true, verbatimSymlinks: true, mode: constants.COPYFILE_FICLONE });
  const plist = path.join(incoming, "Contents/Info.plist");
  run(PLIST_BUDDY, ["-c", "Set :CFBundleName Openbase", "-c", "Set :CFBundleDisplayName Openbase", plist]);
  const iconFile = run(PLIST_BUDDY, ["-c", "Print :CFBundleIconFile", plist], { encoding: "utf8" }).trim();
  copyFileSync(icon, path.join(incoming, "Contents/Resources", iconFile));
  writeFileSync(path.join(incoming, STAMP), brandedRuntimeStamp(source, version));
  // Upstream nested frameworks are only linker-signed; --deep reseals the copy.
  run("codesign", ["--force", "--deep", "--sign", "-", incoming], { stdio: ["ignore", "ignore", "inherit"] });
}

export async function ensureBrandedRuntime(desktop, destination, { run = execFileSync, log = console.log } = {}) {
  const source = path.join(desktop, "node_modules/electron/dist/Electron.app");
  const { version } = JSON.parse(readFileSync(path.join(desktop, "node_modules/electron/package.json"), "utf8"));
  let current;
  try {
    current = readFileSync(path.join(destination, STAMP), "utf8");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  if (current !== brandedRuntimeStamp(source, version)) {
    log(`Branding the Electron ${version} runtime as Openbase…`);
    const icon = path.join(desktop, "assets/openbase-coder-icon.icns");
    const { stageNativeBundle } = await import(pathToFileURL(path.join(desktop, "scripts/native-bundle-staging.mjs")));
    // Atomic swap; a running dev app keeps its retained previous bundle.
    stageNativeBundle(destination, (incoming) => prepareBrandedRuntime(source, incoming, { icon, version, run }));
  }
  return destination;
}

if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [desktop, destination] = process.argv.slice(2).map((arg) => path.resolve(arg));
  await ensureBrandedRuntime(desktop, destination);
  const executable = path.join(destination, "Contents/MacOS/Electron");
  const actual = execFileSync(executable, ["-p", "process.versions.electron"], {
    env: { ...process.env, ELECTRON_RUN_AS_NODE: "1" }, encoding: "utf8", timeout: 30_000,
  }).trim();
  const { version } = JSON.parse(readFileSync(path.join(desktop, "node_modules/electron/package.json"), "utf8"));
  if (actual !== version) throw new Error(`Branded runtime runs Electron ${actual}, expected ${version}.`);
}
