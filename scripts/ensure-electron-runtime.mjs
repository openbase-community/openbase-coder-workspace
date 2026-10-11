import { execFileSync } from "node:child_process";
import { accessSync, constants, existsSync, mkdirSync, readFileSync, realpathSync, renameSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const executablePaths = {
  darwin: "Electron.app/Contents/MacOS/Electron",
  linux: "electron",
  win32: "electron.exe",
};

function readIfPresent(filename) {
  try {
    return readFileSync(filename, "utf8").trim();
  } catch (error) {
    if (error.code === "ENOENT") return undefined;
    throw error;
  }
}

// Check the package's runtime, not just package.json or pnpm's pending-build list.
export function electronRuntime(desktop, platform = process.platform) {
  const packageDir = path.join(desktop, "node_modules/electron");
  const manifest = readIfPresent(path.join(packageDir, "package.json"));
  if (!manifest) throw new Error("Electron's package is missing. Run ./scripts/setup to install workspace dependencies.");
  const { version } = JSON.parse(manifest);
  const relativeExecutable = executablePaths[platform];
  if (!relativeExecutable) throw new Error(`Unsupported Electron platform: ${platform}`);
  const executable = path.join(packageDir, "dist", relativeExecutable);
  let ready = readIfPresent(path.join(packageDir, "path.txt")) === relativeExecutable
    && readIfPresent(path.join(packageDir, "dist/version"))?.replace(/^v/, "") === version;
  if (ready) {
    try {
      accessSync(executable, platform === "win32" ? constants.F_OK : constants.X_OK);
    } catch (error) {
      if (!["ENOENT", "EACCES"].includes(error.code)) throw error;
      ready = false;
    }
  }
  return { version, executable, ready };
}

// electron's install.js unzips with extract-zip 2 / yauzl 2, whose entry
// stream never settles on Node 26: the process drains its event loop and exits
// 0 after the first entry, leaving dist/ with only LICENSES.chromium.html and
// no path.txt. Extract the same checksum-verified cached zip with the
// platform's own unzip instead, staged beside dist/ and renamed into place.
export function extractElectronRuntime(desktop, platform = process.platform, { run = execFileSync, env = process.env } = {}) {
  const packageDir = path.join(desktop, "node_modules/electron");
  const helper = path.join(path.dirname(fileURLToPath(import.meta.url)), "electron-artifact.cjs");
  const zipPath = run(process.execPath, [helper, packageDir], {
    env, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"],
  }).trim();
  const staging = path.join(packageDir, `dist.extracting-${process.pid}`);
  rmSync(staging, { recursive: true, force: true });
  mkdirSync(staging);
  try {
    const [command, args] = {
      // ditto preserves the app bundle's symlinks, modes and framework layout.
      darwin: ["ditto", ["-x", "-k", zipPath, staging]],
      linux: ["unzip", ["-q", "-o", zipPath, "-d", staging]],
      win32: ["tar", ["-x", "-f", zipPath, "-C", staging]],
    }[platform];
    run(command, args, { env, stdio: "inherit" });
    const typeDefinitions = path.join(staging, "electron.d.ts");
    if (existsSync(typeDefinitions)) renameSync(typeDefinitions, path.join(packageDir, "electron.d.ts"));
    rmSync(path.join(packageDir, "dist"), { recursive: true, force: true });
    renameSync(staging, path.join(packageDir, "dist"));
  } finally {
    rmSync(staging, { recursive: true, force: true });
  }
  writeFileSync(path.join(packageDir, "path.txt"), executablePaths[platform]);
}

export function ensureElectronRuntime(workspace, {
  run = execFileSync,
  env = process.env,
  platform = process.platform,
  log = console.log,
} = {}) {
  const desktop = path.join(workspace, "desktop");
  if (env.ELECTRON_OVERRIDE_DIST_PATH) {
    throw new Error("Unset ELECTRON_OVERRIDE_DIST_PATH to use the workspace Electron runtime.");
  }
  let runtime = electronRuntime(desktop, platform);
  if (!runtime.ready) {
    if (env.ELECTRON_SKIP_BINARY_DOWNLOAD) {
      throw new Error("Electron runtime is missing and ELECTRON_SKIP_BINARY_DOWNLOAD is set. Unset it and retry.");
    }
    const ignored = run("pnpm", ["--dir", desktop, "config", "get", "ignore-scripts"], {
      env, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"],
    }).trim();
    if (["true", "1"].includes(ignored)) {
      throw new Error("Electron runtime is missing, but pnpm ignore-scripts is enabled. Resolve that policy before retrying.");
    }
    log(`Repairing the installed Electron ${runtime.version} runtime with pnpm…`);
    // A selected rebuild works even when pendingBuilds is empty. pnpm retains
    // its existing build allowlist; this neither approves scripts nor resolves
    // new dependency versions or changes package-age settings/lockfiles.
    run("pnpm", ["--dir", desktop, "rebuild", `electron@${runtime.version}`], {
      env, stdio: "inherit",
    });
    runtime = electronRuntime(desktop, platform);
    if (!runtime.ready && existsSync(path.join(desktop, "node_modules/electron/dist"))) {
      // The approved install script ran but left a partial dist/ (see
      // extractElectronRuntime): finish its job from the same verified zip.
      log(`Electron's installer left an incomplete runtime under Node ${process.versions.node}; extracting it natively…`);
      extractElectronRuntime(desktop, platform, { run, env });
      runtime = electronRuntime(desktop, platform);
    }
    if (!runtime.ready) {
      throw new Error("Electron runtime is still missing after pnpm rebuild. Check pnpm's Electron build approval and download output, then retry; no launcher was replaced.");
    }
  }
  // Run without loading the desktop app, its profile, services or UI. This
  // catches corrupt/wrong-architecture executables before launcher publication.
  const actualVersion = run(runtime.executable, ["-p", "process.versions.electron"], {
    env: { ...env, ELECTRON_RUN_AS_NODE: "1" }, encoding: "utf8", timeout: 30_000,
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
  if (actualVersion !== runtime.version) {
    throw new Error(`Electron executable version ${actualVersion} does not match installed package ${runtime.version}.`);
  }
  log(`Electron ${runtime.version} runtime is ready.`);
  return realpathSync(runtime.executable);
}

if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    ensureElectronRuntime(path.resolve(process.argv[2] || path.join(path.dirname(fileURLToPath(import.meta.url)), "..")));
  } catch (error) {
    console.error(`Electron runtime check failed: ${error.message}`);
    process.exitCode = 1;
  }
}
