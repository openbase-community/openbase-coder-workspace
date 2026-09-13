#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

function repoUsesInstallSet(repo, installSet) {
  const sets = Array.isArray(repo.installSets) ? repo.installSets : [];
  if (sets.length === 0) return true;
  if (installSet === "internal") {
    return sets.includes("internal") || sets.includes("dev");
  }
  return sets.includes(installSet);
}

export function expectedBranches(config, rootBranch, installSet) {
  return config.repos
    .filter((repo) => repoUsesInstallSet(repo, installSet))
    .map((repo) => ({
      name: repo.name,
      expected: repo.fixedBranch ?? rootBranch,
    }));
}

export function branchMismatches(config, rootBranch, installSet, branchForRepo) {
  return expectedBranches(config, rootBranch, installSet)
    .map(({ name, expected }) => ({
      name,
      expected,
      actual: branchForRepo(name),
    }))
    .filter(({ actual, expected }) => actual !== expected);
}

function gitBranch(repoPath) {
  if (!existsSync(repoPath)) return "(missing)";
  const result = spawnSync("git", ["-C", repoPath, "branch", "--show-current"], {
    encoding: "utf8",
  });
  if (result.status !== 0) return "(not a git checkout)";
  return result.stdout.trim() || "(detached)";
}

export function checkWorkspaceBranches(workspaceRoot, installSet) {
  const config = JSON.parse(
    readFileSync(path.join(workspaceRoot, "multi.json"), "utf8"),
  );
  const rootBranch = gitBranch(workspaceRoot);
  const mismatches = branchMismatches(
    config,
    rootBranch,
    installSet,
    (name) => gitBranch(path.join(workspaceRoot, name)),
  );
  if (mismatches.length === 0) {
    console.log(
      `Verified '${installSet}' repositories against workspace branch ${rootBranch}.`,
    );
    return true;
  }
  for (const { name, actual, expected } of mismatches) {
    console.error(`${name}: ${actual}; expected ${expected}`);
  }
  return false;
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : "";
if (invokedPath === fileURLToPath(import.meta.url)) {
  const workspaceRoot = path.resolve(process.argv[2] ?? process.cwd());
  const installSet = process.argv[3] ?? "default";
  if (!checkWorkspaceBranches(workspaceRoot, installSet)) process.exit(1);
}
