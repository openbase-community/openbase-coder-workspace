import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  branchMismatches,
  expectedBranches,
} from "./check-workspace-branches.mjs";

const config = {
  repos: [
    { name: "cli", installSets: ["default", "internal"] },
    { name: "ios", installSets: ["internal"] },
    {
      name: "multi-react",
      fixedBranch: "main",
      installSets: ["default", "internal"],
    },
    { name: "legacy-internal", installSets: ["dev"] },
  ],
};

test("default installs ignore intentionally absent internal repositories", () => {
  assert.deepEqual(expectedBranches(config, "develop", "default"), [
    { name: "cli", expected: "develop" },
    { name: "multi-react", expected: "main" },
  ]);
});

test("internal installs include current and legacy internal set names", () => {
  assert.deepEqual(expectedBranches(config, "develop", "internal"), [
    { name: "cli", expected: "develop" },
    { name: "ios", expected: "develop" },
    { name: "multi-react", expected: "main" },
    { name: "legacy-internal", expected: "develop" },
  ]);
});

test("existing unlocked repositories on main are rejected under develop", () => {
  const branches = new Map([
    ["cli", "main"],
    ["multi-react", "main"],
  ]);
  assert.deepEqual(
    branchMismatches(config, "develop", "default", (name) => branches.get(name)),
    [{ name: "cli", expected: "develop", actual: "main" }],
  );
});

test("the CLI still checks branches when run through a symlinked checkout path", (t) => {
  const root = mkdtempSync(path.join(os.tmpdir(), "openbase-branches-"));
  const link = `${root}-link`;
  t.after(() => rmSync(root, { force: true, recursive: true }));
  t.after(() => rmSync(link, { force: true }));
  mkdirSync(path.join(root, "scripts"));
  copyFileSync(new URL("./check-workspace-branches.mjs", import.meta.url), path.join(root, "scripts/check-workspace-branches.mjs"));
  writeFileSync(path.join(root, "multi.json"), JSON.stringify({ repos: [{ name: "cli", installSets: ["default"] }] }));
  symlinkSync(root, link);
  const result = spawnSync(process.execPath, [path.join(link, "scripts/check-workspace-branches.mjs"), link, "default"], { encoding: "utf8" });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /cli: \(missing\)/);
});
