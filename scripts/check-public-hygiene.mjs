import { execFileSync } from "node:child_process";

const trackedReports = execFileSync(
  "git",
  ["ls-files", "-z", "--", ".reports"],
  { encoding: "utf8" },
)
  .split("\0")
  .filter(Boolean);

if (trackedReports.length > 0) {
  console.error("Workspace-local reports must not be tracked in this public repository:");
  for (const report of trackedReports) {
    console.error(`- ${report}`);
  }
  process.exitCode = 1;
}
