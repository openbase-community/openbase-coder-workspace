import { execFileSync } from "node:child_process";

const trackedPrivate = execFileSync(
  "git",
  ["ls-files", "-z", "--", ".reports", "netmesh-go"],
  { encoding: "utf8" },
)
  .split("\0")
  .filter(Boolean);

if (trackedPrivate.length > 0) {
  console.error("Private material must not be tracked in this public repository:");
  for (const path of trackedPrivate) {
    console.error(`- ${path}`);
  }
  process.exitCode = 1;
}

// The tip check above cannot catch content that was committed and later
// removed; the workspace .githooks/pre-push hook (with its root/pre-push
// guard) checks every commit in the pushed range. Verify the hook is installed so it cannot be silently skipped.
let hooksPath = "";
try {
  hooksPath = execFileSync("git", ["config", "core.hooksPath"], {
    encoding: "utf8",
  }).trim();
} catch {
  // unset
}
if (hooksPath !== ".githooks") {
  console.error(
    'The workspace git hooks are not installed: run "multi hooks install" (multi sync does this automatically).',
  );
  process.exitCode = 1;
}
