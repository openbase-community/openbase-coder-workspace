import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

const buildScript = fileURLToPath(
  new URL("../install-tests/electron-macos/build-app.sh", import.meta.url),
);

function runWithWorkspace(workspace) {
  return spawnSync(
    "bash",
    [
      "-c",
      'cd() { return 0; }; pwd() { printf "%s\\n" "$REVIEW_WORKSPACE"; }; source "$1" --review-test-stop',
      "build-app-guard-test",
      buildScript,
    ],
    {
      encoding: "utf8",
      env: { ...process.env, REVIEW_WORKSPACE: workspace },
    },
  );
}

for (const workspace of [
  "/fixture/code/openbase-coder-workspace",
  "/fixture/code/openbase-coder-workspace-worktrees",
  "/fixture/code/openbase-coder-workspace-worktrees-other/task",
]) {
  test(`refuses builds outside a worktrees folder: ${workspace}`, () => {
    const result = runWithWorkspace(workspace);
    assert.ifError(result.error);
    assert.equal(result.status, 2);
    assert.match(result.stderr, /refusing to build in the trunk checkout/);
    assert.match(result.stderr, /multi worktree add <name>/);
    assert.match(result.stderr, /throwaway worktree under a \*-worktrees\/ folder/);
    assert.doesNotMatch(result.stderr, /unknown arg/);
  });
}

for (const workspace of [
  "/fixture/code/openbase-coder-workspace-worktrees/task",
  "/fixture/scratch-worktrees/throwaway build",
]) {
  test(`reaches argument parsing inside a worktrees folder: ${workspace}`, () => {
    const result = runWithWorkspace(workspace);
    assert.ifError(result.error);
    assert.equal(result.status, 2);
    assert.match(result.stderr, /unknown arg: --review-test-stop/);
    assert.doesNotMatch(result.stderr, /refusing to build/);
  });
}
