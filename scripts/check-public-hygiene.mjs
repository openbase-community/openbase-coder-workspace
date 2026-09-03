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
// removed; the .githooks/pre-push hook checks every commit in the pushed
// range. Verify the hook is installed so it cannot be silently skipped.
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
    'The pre-push private-path guard is not installed: run "git config core.hooksPath .githooks" (pnpm install does this via the prepare script).',
  );
  process.exitCode = 1;
}
