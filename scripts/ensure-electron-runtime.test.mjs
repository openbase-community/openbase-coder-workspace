import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { electronRuntime, ensureElectronRuntime } from "./ensure-electron-runtime.mjs";

const helper = path.join(path.dirname(fileURLToPath(import.meta.url)), "electron-artifact.cjs");

function fixture(t) {
  const workspace = mkdtempSync(path.join(os.tmpdir(), "electron-readiness-"));
  t.after(() => rmSync(workspace, { recursive: true, force: true }));
  const packageDir = path.join(workspace, "desktop/node_modules/electron");
  mkdirSync(packageDir, { recursive: true });
  writeFileSync(path.join(packageDir, "package.json"), JSON.stringify({ version: "39.8.10" }));
  const executable = path.join(packageDir, "dist/Electron.app/Contents/MacOS/Electron");
  function install(version = "39.8.10") {
    mkdirSync(path.dirname(executable), { recursive: true });
    writeFileSync(executable, "runtime", { mode: 0o755 });
    writeFileSync(path.join(packageDir, "dist/version"), version);
    writeFileSync(path.join(packageDir, "path.txt"), "Electron.app/Contents/MacOS/Electron");
  }
  return { workspace, packageDir, executable, install };
}

test("missing dist is repaired by selected rebuild and the resulting executable is checked", (t) => {
  const f = fixture(t);
  const calls = [];
  const env = { policy: "unchanged" };
  const run = (command, args, options) => {
    calls.push([command, args]);
    if (args.includes("config")) return "undefined\n";
    if (args.includes("rebuild")) {
      assert.deepEqual(args, ["--dir", path.join(f.workspace, "desktop"), "rebuild", "electron@39.8.10"]);
      assert.equal(options.env, env);
      f.install();
      return;
    }
    assert.equal(command, f.executable);
    assert.deepEqual(args, ["-p", "process.versions.electron"]);
    assert.equal(options.env.ELECTRON_RUN_AS_NODE, "1");
    assert.equal(options.env.policy, "unchanged");
    return "39.8.10\n";
  };
  assert.equal(ensureElectronRuntime(f.workspace, { run, env, platform: "darwin", log() {} }), realpathSync(f.executable));
  assert.equal(calls.length, 3);
});

test("valid runtime is executed without rebuilding or consulting the network", (t) => {
  const f = fixture(t);
  f.install();
  let calls = 0;
  ensureElectronRuntime(f.workspace, {
    platform: "darwin", env: {}, log() {},
    run(command) { assert.equal(command, f.executable); calls++; return "39.8.10"; },
  });
  assert.equal(calls, 1);
});

for (const policy of ["ignore-scripts", "skip-download"]) {
  test(`missing runtime respects explicit ${policy}`, (t) => {
    const f = fixture(t);
    assert.throws(() => ensureElectronRuntime(f.workspace, {
      platform: "darwin", log() {},
      env: policy === "skip-download" ? { ELECTRON_SKIP_BINARY_DOWNLOAD: "1" } : {},
      run(command, args) { assert.ok(args.includes("config")); return "true"; },
    }), /ignore-scripts|ELECTRON_SKIP_BINARY_DOWNLOAD/);
    assert.equal(electronRuntime(path.join(f.workspace, "desktop"), "darwin").ready, false);
  });
}

test("a policy-blocked/no-op rebuild cannot count as success", (t) => {
  const f = fixture(t);
  assert.throws(() => ensureElectronRuntime(f.workspace, {
    platform: "darwin", env: {}, log() {},
    run(command, args) { return args.includes("config") ? "undefined" : ""; },
  }), /still missing.*approval/);
});

test("download failure is propagated without a second installer or policy bypass", (t) => {
  const f = fixture(t);
  let rebuilds = 0;
  assert.throws(() => ensureElectronRuntime(f.workspace, {
    platform: "darwin", env: {}, log() {},
    run(command, args) {
      if (args.includes("config")) return "undefined";
      rebuilds++;
      throw new Error("download unavailable");
    },
  }), /download unavailable/);
  assert.equal(rebuilds, 1);
});

test("stale dist metadata triggers repair and wrong executable version is rejected", (t) => {
  const f = fixture(t);
  f.install("38.0.0");
  assert.equal(electronRuntime(path.join(f.workspace, "desktop"), "darwin").ready, false);
  assert.throws(() => ensureElectronRuntime(f.workspace, {
    platform: "darwin", env: {}, log() {},
    run(command, args) {
      if (args.includes("config")) return "undefined";
      if (args.includes("rebuild")) { f.install(); return; }
      return "38.0.0";
    },
  }), /does not match installed package/);
});

test("missing package fails with setup guidance before any command", (t) => {
  const f = fixture(t);
  rmSync(path.join(f.packageDir, "package.json"));
  assert.throws(() => ensureElectronRuntime(f.workspace, {
    env: {}, run() { assert.fail("unexpected command"); },
  }), /package is missing.*scripts\/setup/);
});

test("an override cannot validate one runtime and launch another", (t) => {
  const f = fixture(t);
  assert.throws(() => ensureElectronRuntime(f.workspace, {
    env: { ELECTRON_OVERRIDE_DIST_PATH: "alternate" },
    run() { assert.fail("unexpected command"); },
  }), /ELECTRON_OVERRIDE_DIST_PATH/);
});

// Node 26: electron's approved install.js exits 0 after extracting only the
// first zip entry, so dist/ exists but holds just LICENSES.chromium.html.
function truncatedInstall(f) {
  mkdirSync(path.join(f.packageDir, "dist"), { recursive: true });
  writeFileSync(path.join(f.packageDir, "dist/LICENSES.chromium.html"), "licenses");
}

test("a truncated install-script extraction is finished natively from the verified zip", { skip: process.platform !== "darwin" }, (t) => {
  const f = fixture(t);
  // A real zip, extracted by the real ditto, with the upstream archive layout.
  const source = path.join(f.workspace, "zip-source");
  mkdirSync(path.join(source, "Electron.app/Contents/MacOS"), { recursive: true });
  writeFileSync(path.join(source, "Electron.app/Contents/MacOS/Electron"), "#!/bin/sh\n", { mode: 0o755 });
  writeFileSync(path.join(source, "version"), "39.8.10");
  writeFileSync(path.join(source, "electron.d.ts"), "types");
  writeFileSync(path.join(source, "LICENSES.chromium.html"), "licenses");
  const zip = path.join(f.workspace, "electron-v39.8.10-darwin-arm64.zip");
  execFileSync("ditto", ["-c", "-k", source, zip]);
  const commands = [];
  const run = (command, args, options) => {
    commands.push(command);
    if (args.includes("config")) return "undefined";
    if (args.includes("rebuild")) return truncatedInstall(f);
    if (command === process.execPath) {
      assert.deepEqual(args, [helper, f.packageDir]);
      return `${zip}\n`;
    }
    if (command === "ditto") return execFileSync(command, args, options);
    assert.equal(command, f.executable);
    return "39.8.10";
  };
  assert.equal(ensureElectronRuntime(f.workspace, { run, env: {}, platform: "darwin", log() {} }), realpathSync(f.executable));
  assert.deepEqual(commands, ["pnpm", "pnpm", process.execPath, "ditto", f.executable]);
  assert.equal(readFileSync(path.join(f.packageDir, "path.txt"), "utf8"), "Electron.app/Contents/MacOS/Electron");
  assert.equal(readFileSync(path.join(f.packageDir, "electron.d.ts"), "utf8"), "types");
  assert.equal(existsSync(path.join(f.packageDir, "dist/electron.d.ts")), false);
  assert.deepEqual(readdirSync(f.packageDir).filter((name) => name.startsWith("dist.")), []);
});

test("a native extraction that yields no runtime still fails setup loudly", (t) => {
  const f = fixture(t);
  assert.throws(() => ensureElectronRuntime(f.workspace, {
    platform: "linux", env: {}, log() {},
    run(command, args) {
      if (args.includes("config")) return "undefined";
      if (args.includes("rebuild")) return truncatedInstall(f);
      if (command === process.execPath) return "/cache/electron.zip";
      assert.deepEqual([command, args.slice(0, 2)], ["unzip", ["-q", "-o"]]);
    },
  }), /still missing after pnpm rebuild/);
  assert.deepEqual(readdirSync(f.packageDir).filter((name) => name.startsWith("dist.")), []);
});

test("a failed artifact download is propagated, not reported as ready", (t) => {
  const f = fixture(t);
  assert.throws(() => ensureElectronRuntime(f.workspace, {
    platform: "darwin", env: {}, log() {},
    run(command, args) {
      if (args.includes("config")) return "undefined";
      if (args.includes("rebuild")) return truncatedInstall(f);
      throw new Error("checksum mismatch");
    },
  }), /checksum mismatch/);
});
