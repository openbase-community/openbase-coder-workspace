import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const scripts = path.dirname(fileURLToPath(import.meta.url));
const pinned = readFileSync(path.join(scripts, "../.nvmrc"), "utf8").trim();
const pinnedMajor = pinned.split(".")[0];

// Runs a copy of scripts/setup against stub prerequisites, so only the Node
// gate decides whether setup proceeds. `node` is a stub reporting nodeVersion
// (absent when null); every other stubbed command succeeds.
function runSetup(t, nodeVersion) {
  const root = mkdtempSync(path.join(os.tmpdir(), "setup-test-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  for (const dir of ["scripts", "cli", "home", "bin"]) mkdirSync(path.join(root, dir));
  cpSync(path.join(scripts, "setup"), path.join(root, "scripts/setup"));
  cpSync(path.join(scripts, "check-macos-toolchain"), path.join(root, "scripts/check-macos-toolchain"));
  writeFileSync(path.join(root, "bin/uname"), "#!/bin/sh\necho Linux\n", { mode: 0o755 });
  cpSync(path.join(scripts, "../.nvmrc"), path.join(root, ".nvmrc"));
  for (const name of ["uv", "multi", "go", "pnpm"]) {
    writeFileSync(path.join(root, "bin", name), "#!/bin/sh\nexit 0\n", { mode: 0o755 });
  }
  if (nodeVersion !== null) {
    writeFileSync(path.join(root, "bin/node"), `#!/bin/sh
case "$1" in
  --version) echo ${nodeVersion};;
  *detect-install-set.mjs) echo default;;
esac
exit 0
`, { mode: 0o755 });
  }
  return spawnSync("bash", [path.join(root, "scripts/setup"), "--backend", "codex"], {
    env: { HOME: path.join(root, "home"), PATH: `${root}/bin:/usr/bin:/bin` },
    encoding: "utf8",
  });
}

test(".nvmrc pins an exact Node version that package.json engines accept", () => {
  assert.match(pinned, /^\d+\.\d+\.\d+$/);
  for (const manifest of ["../package.json", "../desktop/package.json", "../console/package.json"]) {
    const file = path.join(scripts, manifest);
    let engines;
    try {
      engines = JSON.parse(readFileSync(file, "utf8")).engines;
    } catch (error) {
      if (error.code === "ENOENT") continue; // repo not in this install set
      throw error;
    }
    assert.equal(engines?.node, `>=${pinnedMajor} <${Number(pinnedMajor) + 1}`, manifest);
  }
});

test("setup stops with nvm commands when Node is another major", (t) => {
  const result = runSetup(t, "v26.7.0");
  assert.equal(result.status, 1);
  assert.match(result.stderr, new RegExp(`pins Node ${pinned.replaceAll(".", "\\.")} in \\.nvmrc, but 'node' on PATH is v26\\.7\\.0`));
  assert.match(result.stderr, /nvm install && nvm use/);
  assert.doesNotMatch(result.stdout, /Syncing the Multi/);
});

test("setup stops with nvm commands when Node is missing", (t) => {
  const result = runSetup(t, null);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /'node' .* is required but was not found on PATH/);
  assert.match(result.stderr, /nvm install && nvm use/);
});

test("setup proceeds on any patch release of the pinned major", (t) => {
  const result = runSetup(t, `v${pinnedMajor}.99.0`);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Setup complete/);
});

test("CI workflows that cannot read .nvmrc pin the same Node version", () => {
  for (const workflow of ["../desktop/.github/workflows/electron-rebuild.yml", "../cli/.github/workflows/release-standalone.yml"]) {
    let source;
    try {
      source = readFileSync(path.join(scripts, workflow), "utf8");
    } catch (error) {
      if (error.code === "ENOENT") continue; // repo not in this install set
      throw error;
    }
    const versions = [...source.matchAll(/node-version:\s*"?([^"\s]+)"?/g)].map((match) => match[1]);
    assert.ok(versions.length > 0, workflow);
    for (const version of versions) assert.equal(version, pinned, workflow);
  }
});
