#!/usr/bin/env node

import { existsSync, readFileSync, realpathSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export function detectInstallSet(workspaceRoot) {
  const config = JSON.parse(
    readFileSync(path.join(workspaceRoot, "multi.json"), "utf8"),
  );
  // "internal" is the members-only install set (formerly named "dev");
  // accept the legacy name so a stale multi.json still detects correctly.
  const hasCheckedOutInternalOnlyRepo = config.repos.some((repo) => {
    const sets = Array.isArray(repo.installSets) ? repo.installSets : [];
    const internal = sets.includes("internal") || sets.includes("dev");
    if (!internal || sets.includes("default")) {
      return false;
    }
    const repoRoot = path.join(workspaceRoot, repo.name);
    return existsSync(path.join(repoRoot, ".git"));
  });
  return hasCheckedOutInternalOnlyRepo ? "internal" : "default";
}

// Compare real paths: import.meta.url is symlink-resolved, so a checkout
// reached through a symlink (macOS /tmp is /private/tmp) would otherwise
// skip the CLI entry point and print nothing.
if (process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) {
  console.log(detectInstallSet(path.resolve(process.argv[2] ?? process.cwd())));
}
