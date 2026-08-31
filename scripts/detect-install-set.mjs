#!/usr/bin/env node

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export function detectInstallSet(workspaceRoot) {
  const config = JSON.parse(
    readFileSync(path.join(workspaceRoot, "multi.json"), "utf8"),
  );
  const hasCheckedOutDevOnlyRepo = config.repos.some((repo) => {
    const sets = Array.isArray(repo.installSets) ? repo.installSets : [];
    if (!sets.includes("dev") || sets.includes("default")) {
      return false;
    }
    const repoRoot = path.join(workspaceRoot, repo.name);
    return existsSync(path.join(repoRoot, ".git"));
  });
  return hasCheckedOutDevOnlyRepo ? "dev" : "default";
}

const invokedPath = process.argv[1] ? path.resolve(process.argv[1]) : "";
if (invokedPath === fileURLToPath(import.meta.url)) {
  console.log(detectInstallSet(path.resolve(process.argv[2] ?? process.cwd())));
}
