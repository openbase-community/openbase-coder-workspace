import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const scripts = path.dirname(fileURLToPath(import.meta.url));
const pinned = readFileSync(path.join(scripts, "../.nvmrc"), "utf8").trim();

// Runs scripts/setup's prerequisite checks on a PATH that holds only stub
// tools, so the result does not depend on what the host has installed. The
// stub multi records that it ran and stops setup right after the checks.
function runSetup(t, { onPath = [], inToolBin = [], env: extraEnv = {} } = {}) {
  const root = mkdtempSync(path.join(os.tmpdir(), "setup-prereqs-test-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const home = path.join(root, "home");
  const bin = path.join(root, "bin");
  const toolBin = path.join(home, ".local/bin");
  for (const dir of [path.join(root, "scripts"), bin, toolBin]) mkdirSync(dir, { recursive: true });
  cpSync(path.join(scripts, "setup"), path.join(root, "scripts/setup"));
  cpSync(path.join(scripts, "check-macos-toolchain"), path.join(root, "scripts/check-macos-toolchain"));
  writeFileSync(path.join(root, "bin/uname"), "#!/bin/sh\necho Linux\n", { mode: 0o755 });
  cpSync(path.join(scripts, "../.nvmrc"), path.join(root, ".nvmrc"));
  const stubs = {
    node: `#!/bin/sh\nif [ "$1" = --version ]; then echo v${pinned}; else echo default; fi\n`,
    pnpm: "#!/bin/sh\nexit 0\n",
    go: "#!/bin/sh\nexit 0\n",
    uv: "#!/bin/sh\nexit 0\n",
    multi: `#!/bin/sh\necho "$0 $*" >> "${root}/multi-ran"\nexit 3\n`,
  };
  for (const name of ["node", "pnpm", ...onPath]) writeFileSync(path.join(bin, name), stubs[name], { mode: 0o755 });
  for (const name of inToolBin) writeFileSync(path.join(toolBin, name), stubs[name], { mode: 0o755 });
  const env = { HOME: home, PATH: `${bin}:/usr/bin:/bin`, ...extraEnv };
  const result = spawnSync("/bin/bash", [path.join(root, "scripts/setup"), "--non-interactive"], { env, encoding: "utf8" });
  const multiRan = path.join(root, "multi-ran");
  return { ...result, toolBin, multiRuns: existsSync(multiRan) ? readFileSync(multiRan, "utf8") : "" };
}

test("setup uses multi from ~/.local/bin when it is off PATH and prints the PATH fix", (t) => {
  const result = runSetup(t, { onPath: ["uv", "go"], inToolBin: ["multi"] });
  assert.doesNotMatch(result.stderr, /uv tool install multi-workspace/);
  assert.match(result.stderr, /found multi in .*\.local\/bin, which is not on your PATH/);
  assert.match(result.stderr, /uv tool update-shell/);
  assert.match(result.stderr, /export PATH=".*\.local\/bin:\$PATH"/);
  assert.match(result.multiRuns, new RegExp(`^${result.toolBin}/multi sync`));
});

test("setup also finds uv itself in the uv tool bin dir", (t) => {
  const result = runSetup(t, { onPath: ["go"], inToolBin: ["uv", "multi"] });
  assert.match(result.stderr, /found uv, multi in /);
  assert.doesNotMatch(result.stderr, /is required but was not found/);
  assert.notEqual(result.multiRuns, "");
});

test("setup honors UV_TOOL_BIN_DIR when looking for off-PATH tools", (t) => {
  const custom = mkdtempSync(path.join(os.tmpdir(), "setup-prereqs-toolbin-"));
  t.after(() => rmSync(custom, { recursive: true, force: true }));
  writeFileSync(path.join(custom, "multi"), "#!/bin/sh\nexit 3\n", { mode: 0o755 });
  const result = runSetup(t, { onPath: ["uv", "go"], env: { UV_TOOL_BIN_DIR: custom } });
  assert.match(result.stderr, new RegExp(`found multi in ${custom}`));
  assert.doesNotMatch(result.stderr, /is required but was not found/);
});

test("setup still reports the install command when multi is not installed anywhere", (t) => {
  const result = runSetup(t, { onPath: ["uv", "go"] });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /'multi' is required but was not found on PATH[\s\S]*uv tool install multi-workspace/);
  assert.doesNotMatch(result.stderr, /not on your PATH/);
  assert.equal(result.multiRuns, "");
});

test("setup prints no PATH note when every tool is already on PATH", (t) => {
  const result = runSetup(t, { onPath: ["uv", "go", "multi"] });
  assert.doesNotMatch(result.stderr, /not on your PATH|is required but was not found/);
  assert.notEqual(result.multiRuns, "");
});
