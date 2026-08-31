import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { detectInstallSet } from "./detect-install-set.mjs";

async function workspaceWith(config) {
  const root = await mkdtemp(path.join(os.tmpdir(), "openbase-install-set-"));
  writeFileSync(path.join(root, "multi.json"), JSON.stringify(config));
  return root;
}

test("keeps a public checkout on the default install set", async (t) => {
  const root = await workspaceWith({
    repos: [
      { name: "cli", installSets: ["default", "dev"] },
      { name: "desktop", installSets: ["dev"] },
    ],
  });
  t.after(() => rm(root, { force: true, recursive: true }));
  mkdirSync(path.join(root, "cli", ".git"), { recursive: true });
  assert.equal(detectInstallSet(root), "default");
});

test("preserves dev when a dev-only repo is already checked out", async (t) => {
  const root = await workspaceWith({
    repos: [
      { name: "cli", installSets: ["default", "dev"] },
      { name: "desktop", installSets: ["dev"] },
    ],
  });
  t.after(() => rm(root, { force: true, recursive: true }));
  mkdirSync(path.join(root, "desktop"), { recursive: true });
  writeFileSync(path.join(root, "desktop", ".git"), "gitdir: elsewhere\n");
  assert.equal(detectInstallSet(root), "dev");
});
