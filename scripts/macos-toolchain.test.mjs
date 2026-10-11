import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const scripts = path.dirname(fileURLToPath(import.meta.url));

function fixture(t, platform = "Darwin") {
  const root = mkdtempSync(path.join(os.tmpdir(), "macos toolchain test-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  for (const dir of ["scripts", "bin", "desktop", "home/.openbase", "tmp"]) {
    mkdirSync(path.join(root, dir), { recursive: true });
  }
  for (const name of ["setup", "dev-launch", "check-macos-toolchain"]) {
    cpSync(path.join(scripts, name), path.join(root, "scripts", name));
  }
  writeFileSync(path.join(root, "home/.openbase/installation.json"), JSON.stringify({ standalone: false, workspace_path: root }));
  const stub = (name, source) => writeFileSync(path.join(root, "bin", name), `#!/bin/sh\n${source}\n`, { mode: 0o755 });
  stub("uname", `echo ${platform}`);
  stub("xcrun", 'echo "$*" >> "$FIXTURE_ROOT/compiler-ran"\necho "fixture: macOS SDK is missing" >&2\nexit 7');
  for (const name of ["multi", "uv", "pnpm", "open"]) {
    stub(name, 'echo "$0 $*" >> "$FIXTURE_ROOT/expensive-work"\nexit 9');
  }
  // Let dev-launch validate the installation, but record any runtime repair.
  stub("node", 'if [ "$1" = - ]; then exit 0; fi\necho "$*" >> "$FIXTURE_ROOT/expensive-work"\nexit 9');
  const env = { HOME: path.join(root, "home"), PATH: `${root}/bin:/usr/bin:/bin`, TMPDIR: path.join(root, "tmp"), FIXTURE_ROOT: root };
  return { root, env, run: (name, args = []) => spawnSync("/bin/bash", [path.join(root, "scripts", name), ...args], { env, encoding: "utf8" }) };
}

for (const [entry, args] of [["setup", []], ["dev-launch", ["--build-only"]], ["dev-launch", ["--electron-dev"]], ["dev-launch", ["--menu-bar"]]]) {
  test(`${entry} ${args.join(" ")}: compiler failure stops before sync, runtime repair, or builds`, (t) => {
    const f = fixture(t);
    const result = f.run(entry, args);
    assert.equal(result.status, 1, result.stdout + result.stderr);
    assert.match(result.stderr, /fixture: macOS SDK is missing/);
    assert.match(result.stderr, /macOS C compiler\/SDK check failed/);
    assert.match(result.stderr, /xcode-select --install/);
    assert.match(result.stderr, /sudo xcode-select -s \/Library\/Developer\/CommandLineTools/);
    assert.match(readFileSync(path.join(f.root, "compiler-ran"), "utf8"), /^clang .*probe\.c -o .*probe\n$/);
    assert.equal(existsSync(path.join(f.root, "expensive-work")), false);
    assert.deepEqual(readdirSync(f.env.TMPDIR), []);
  });
}

test("non-macOS preflight does not invoke the compiler or create scratch files", (t) => {
  const f = fixture(t, "Linux");
  const result = f.run("check-macos-toolchain");
  assert.equal(result.status, 0, result.stderr);
  assert.equal(existsSync(path.join(f.root, "compiler-ran")), false);
  assert.deepEqual(readdirSync(f.env.TMPDIR), []);
});

test("dev-launch help works without a functioning compiler", (t) => {
  const f = fixture(t);
  const result = f.run("dev-launch", ["--help"]);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /Usage:/);
  assert.equal(existsSync(path.join(f.root, "compiler-ran")), false);
});

test("macOS preflight compiles with the real SDK and removes its output", { skip: process.platform !== "darwin" }, (t) => {
  const f = fixture(t);
  const result = spawnSync("/bin/bash", [path.join(scripts, "check-macos-toolchain")], {
    env: { ...process.env, TMPDIR: f.env.TMPDIR }, encoding: "utf8",
  });
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.deepEqual(readdirSync(f.env.TMPDIR), []);
});
