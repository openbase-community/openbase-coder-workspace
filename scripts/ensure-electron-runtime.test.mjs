import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { electronRuntime, ensureElectronRuntime } from "./ensure-electron-runtime.mjs";

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
