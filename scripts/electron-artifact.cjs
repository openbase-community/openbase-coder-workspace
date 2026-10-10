// Print the path of the checksum-verified Electron zip for an installed
// electron package, downloading it into Electron's cache only if absent.
// Mirrors electron/install.js's downloadArtifact call (same cache, platform,
// arch and checksums) without its extract-zip step, which Node 26 silently
// truncates after the first entry.
const { execSync } = require("node:child_process");
const { realpathSync } = require("node:fs");
const { createRequire } = require("node:module");
const path = require("node:path");

// Resolve pnpm's symlink so @electron/get is found beside electron in .pnpm/.
const packageDir = realpathSync(process.argv[2]);
const electronRequire = createRequire(path.join(packageDir, "package.json"));
const { version } = electronRequire("./package.json");
const { downloadArtifact } = electronRequire("@electron/get");

const platform = process.env.npm_config_platform || process.platform;
let arch = process.env.npm_config_arch || process.arch;
if (platform === "darwin" && process.platform === "darwin" && arch === "x64" && process.env.npm_config_arch === undefined) {
  try {
    if (execSync("sysctl -in sysctl.proc_translated").toString().trim() === "1") arch = "arm64";
  } catch {
    // Not running under Rosetta.
  }
}

downloadArtifact({
  version,
  artifactName: "electron",
  cacheRoot: process.env.electron_config_cache,
  checksums: (process.env.electron_use_remote_checksums || process.env.npm_config_electron_use_remote_checksums)
    ? undefined : electronRequire("./checksums.json"),
  platform,
  arch,
}).then((zipPath) => {
  process.stdout.write(`${zipPath}\n`);
}, (error) => {
  console.error(error.stack);
  process.exitCode = 1;
});
