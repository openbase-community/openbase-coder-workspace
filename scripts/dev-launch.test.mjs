import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const scripts = path.dirname(fileURLToPath(import.meta.url));
function fixture(t, { runtime = false, repair = false, signingFailure = false } = {}) {
  const root = mkdtempSync(path.join(os.tmpdir(), "dev-launch-test-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  for (const dir of ["scripts", "home/.openbase", "bin", "desktop/scripts", "desktop/assets", "desktop/dist", "desktop/src", "coder-react/src", "multi-react/src", "boilersync-react/src"]) {
    mkdirSync(path.join(root, dir), { recursive: true });
  }
  const destination = path.join(root, "Applications/Openbase.app");
  const resources = path.join(destination, "Contents/Resources");
  mkdirSync(resources, { recursive: true });
  writeFileSync(path.join(resources, ".openbase-dev-launcher"), "");
  writeFileSync(path.join(destination, "preserved"), "existing launcher");
  const source = readFileSync(path.join(scripts, "dev-launch"), "utf8");
  // Route the script's sole fixed installation destination into this disposable
  // tree; no test may write to /Applications or invoke the real open command.
  assert.equal(source.split('APP_DIR="/Applications/Openbase.app"').length, 2);
  writeFileSync(path.join(root, "scripts/dev-launch"), source.replace('APP_DIR="/Applications/Openbase.app"', `APP_DIR="${destination}"`), { mode: 0o755 });
  for (const name of ["ensure-electron-runtime.mjs", "electron-artifact.cjs", "brand-dev-runtime.mjs"]) {
    cpSync(path.join(scripts, name), path.join(root, "scripts", name));
  }
  writeFileSync(path.join(root, "scripts/check-renderer-freshness.cjs"), "process.exit(0)");
  for (const name of ["native-bundle-staging.mjs", "native-bundle-swap.c"]) {
    cpSync(path.join(scripts, "../desktop/scripts", name), path.join(root, "desktop/scripts", name));
  }
  writeFileSync(path.join(root, "home/.openbase/installation.json"), JSON.stringify({ standalone: false, workspace_path: root }));
  writeFileSync(path.join(root, "desktop/assets/openbase-coder-icon.icns"), "fixture");
  writeFileSync(path.join(root, "desktop/dist/index.html"), "fixture renderer");
  const packageDir = path.join(root, "desktop/node_modules/electron");
  mkdirSync(packageDir, { recursive: true });
  writeFileSync(path.join(packageDir, "package.json"), JSON.stringify({ version: "39.8.10" }));
  const install = `mkdir -p "$FIXTURE_ROOT/desktop/node_modules/electron/dist/Electron.app/Contents/MacOS"
printf '39.8.10' > "$FIXTURE_ROOT/desktop/node_modules/electron/dist/version"
printf 'Electron.app/Contents/MacOS/Electron' > "$FIXTURE_ROOT/desktop/node_modules/electron/path.txt"
printf '#!/bin/sh\\nprintf 39.8.10\\n' > "$FIXTURE_ROOT/desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron"
chmod +x "$FIXTURE_ROOT/desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron"
mkdir -p "$FIXTURE_ROOT/desktop/node_modules/electron/dist/Electron.app/Contents/Resources"
printf 'upstream icon' > "$FIXTURE_ROOT/desktop/node_modules/electron/dist/Electron.app/Contents/Resources/electron.icns"
printf '%s' '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>CFBundleName</key><string>Electron</string><key>CFBundleDisplayName</key><string>Electron</string><key>CFBundleExecutable</key><string>Electron</string><key>CFBundleIconFile</key><string>electron.icns</string><key>CFBundleIdentifier</key><string>com.github.Electron</string><key>CFBundlePackageType</key><string>APPL</string></dict></plist>' > "$FIXTURE_ROOT/desktop/node_modules/electron/dist/Electron.app/Contents/Info.plist"`;
  const env = { ...process.env, HOME: path.join(root, "home"), FIXTURE_ROOT: root, PATH: `${root}/bin:${process.env.PATH}` };
  delete env.ELECTRON_OVERRIDE_DIST_PATH;
  delete env.ELECTRON_SKIP_BINARY_DOWNLOAD;
  if (runtime) assert.equal(spawnSync("bash", ["-c", install], { env }).status, 0);
  writeFileSync(path.join(root, "bin/pnpm"), `#!/bin/bash
echo "$*" >> "$FIXTURE_ROOT/commands"
case "$*" in
  *"config get ignore-scripts"*) echo undefined;;
  *"rebuild electron@"*) ${repair ? install : "exit 7"};;
  *) exit 0;;
esac
`, { mode: 0o755 });
  writeFileSync(path.join(root, "bin/open"), '#!/bin/sh\necho "$*" >> "$FIXTURE_ROOT/opened"\n', { mode: 0o755 });
  if (signingFailure) writeFileSync(path.join(root, "bin/codesign"), "#!/bin/sh\nexit 9\n", { mode: 0o755 });
  return { root, destination, env, run: (flag) => spawnSync("bash", [path.join(root, "scripts/dev-launch"), flag], { env, encoding: "utf8" }) };
}

for (const flag of ["--electron", "--electron-dev", "--all", "--build-only"]) {
  test(`${flag}: failed repair preserves launcher and prevents visual-surface commands`, (t) => {
    const f = fixture(t);
    const result = f.run(flag);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Electron runtime check failed/);
    assert.equal(readFileSync(path.join(f.destination, "preserved"), "utf8"), "existing launcher");
    assert.equal(existsSync(path.join(f.root, "opened")), false);
    const commands = readFileSync(path.join(f.root, "commands"), "utf8");
    assert.doesNotMatch(commands, /companion:| build| dev| start/);
  });
}

test("signing failure leaves existing launcher intact", { skip: process.platform !== "darwin" }, (t) => {
  const f = fixture(t, { runtime: true, signingFailure: true });
  assert.notEqual(f.run("--electron").status, 0);
  assert.equal(readFileSync(path.join(f.destination, "preserved"), "utf8"), "existing launcher");
  assert.equal(existsSync(path.join(f.root, "opened")), false);
});

test("repaired runtime publishes a signed launcher atomically and retains the prior bundle", { skip: process.platform !== "darwin" }, (t) => {
  const f = fixture(t, { repair: true });
  const result = f.run("--electron");
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.equal(existsSync(path.join(f.destination, "Contents/MacOS/Openbase")), true);
  assert.equal(existsSync(path.join(f.destination, "preserved")), false);
  const retained = readdirSync(path.dirname(f.destination)).find((name) => name.startsWith(".native-stage-"));
  assert.equal(readFileSync(path.join(path.dirname(f.destination), retained, "Openbase.app/preserved"), "utf8"), "existing launcher");
  assert.equal(readFileSync(path.join(f.root, "opened"), "utf8").trim(), f.destination);
});

test("--build-only publishes the launcher without launching anything", { skip: process.platform !== "darwin" }, (t) => {
  const f = fixture(t, { runtime: true });
  rmSync(path.join(f.root, "desktop/dist/index.html"));
  const result = f.run("--build-only");
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.match(result.stdout, /Built the Openbase developer app/);
  assert.match(readFileSync(path.join(f.root, "commands"), "utf8"), / build\n/);
  assert.equal(existsSync(path.join(f.destination, "Contents/MacOS/Openbase")), true);
  assert.equal(existsSync(path.join(f.root, "opened")), false);
});

test("--build-only leaves a packaged app in place", { skip: process.platform !== "darwin" }, (t) => {
  const f = fixture(t, { runtime: true });
  rmSync(path.join(f.destination, "Contents/Resources/.openbase-dev-launcher"));
  const result = f.run("--build-only");
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.match(result.stdout, /without replacing it/);
  assert.equal(readFileSync(path.join(f.destination, "preserved"), "utf8"), "existing launcher");
  assert.equal(existsSync(path.join(f.root, "opened")), false);
});

test("the launcher opens a branded runtime clone and never edits node_modules' Electron", { skip: process.platform !== "darwin" }, (t) => {
  const f = fixture(t, { runtime: true });
  const upstream = path.join(f.root, "desktop/node_modules/electron/dist/Electron.app");
  const branded = path.join(f.root, "desktop/dev-runtime/Openbase.app");
  const plist = (app, key) => spawnSync("/usr/libexec/PlistBuddy", ["-c", `Print :${key}`, path.join(app, "Contents/Info.plist")], { encoding: "utf8" }).stdout.trim();
  const first = f.run("--build-only");
  assert.equal(first.status, 0, first.stdout + first.stderr);
  assert.match(first.stdout, /Branding the Electron 39\.8\.10 runtime as Openbase/);
  assert.equal(plist(branded, "CFBundleName"), "Openbase");
  assert.equal(plist(branded, "CFBundleDisplayName"), "Openbase");
  assert.equal(readFileSync(path.join(branded, "Contents/Resources/electron.icns"), "utf8"), "fixture");
  assert.equal(spawnSync("codesign", ["--verify", "--strict", "--deep", branded]).status, 0);
  assert.equal(plist(upstream, "CFBundleName"), "Electron");
  assert.equal(readFileSync(path.join(upstream, "Contents/Resources/electron.icns"), "utf8"), "upstream icon");
  assert.match(readFileSync(path.join(f.destination, "Contents/MacOS/Openbase"), "utf8"), /dev-runtime\/Openbase\.app/);
  const second = f.run("--build-only");
  assert.equal(second.status, 0, second.stdout + second.stderr);
  assert.doesNotMatch(second.stdout, /Branding/);
});

test("valid runtime in HMR mode uses the existing dev command without rebuilding", { skip: process.platform !== "darwin" }, (t) => {
  const f = fixture(t, { runtime: true });
  const result = f.run("--electron-dev");
  assert.equal(result.status, 0, result.stderr);
  const commands = readFileSync(path.join(f.root, "commands"), "utf8");
  assert.match(commands, / dev\n/);
  assert.doesNotMatch(commands, /rebuild/);
});

for (const repair of [false, true]) {
  test(`setup ${repair ? "repairs Electron before reporting completion" : "fails explicitly when Electron repair fails"}`, { skip: process.platform !== "darwin" }, (t) => {
    const f = fixture(t, { repair });
    mkdirSync(path.join(f.root, "cli"));
    cpSync(path.join(scripts, "setup"), path.join(f.root, "scripts/setup"));
    writeFileSync(path.join(f.root, "scripts/detect-install-set.mjs"), 'console.log("default")');
    writeFileSync(path.join(f.root, "scripts/check-workspace-branches.mjs"), "process.exit(0)");
    writeFileSync(path.join(f.root, "desktop/package.json"), "{}");
    for (const name of ["multi", "uv", "go"]) {
      writeFileSync(path.join(f.root, "bin", name), "#!/bin/sh\nexit 0\n", { mode: 0o755 });
    }
    const result = spawnSync("bash", [path.join(f.root, "scripts/setup"), "--non-interactive"], { env: f.env, encoding: "utf8" });
    if (repair) {
      assert.equal(result.status, 0, result.stdout + result.stderr);
      assert.match(result.stdout, /runtime is ready[\s\S]*Built the Openbase developer app[\s\S]*Setup complete/);
      assert.equal(existsSync(path.join(f.destination, "Contents/MacOS/Openbase")), true);
      assert.equal(existsSync(path.join(f.root, "opened")), false);
    } else {
      assert.notEqual(result.status, 0);
      assert.doesNotMatch(result.stdout, /Setup complete/);
      assert.match(result.stderr, /Electron runtime check failed/);
    }
  });
}
