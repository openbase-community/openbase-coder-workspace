import assert from "node:assert/strict";
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
