// Shared fixtures for the Android publish scripts' tests
// (bump-android-downloads-card.test.mjs, publish-android-apk.test.mjs).
import { execFileSync, spawnSync } from "node:child_process";
import { chmodSync, cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const scripts = path.dirname(fileURLToPath(import.meta.url));

export const LABEL_LINE = '            <span class="mc-meta">Direct APK · v0.2.5 · prefer the Google Play beta above</span>\n';

const gitEnv = {
  ...process.env,
  GIT_AUTHOR_NAME: "fixture",
  GIT_AUTHOR_EMAIL: "fixture@example.invalid",
  GIT_COMMITTER_NAME: "fixture",
  GIT_COMMITTER_EMAIL: "fixture@example.invalid",
  GIT_CONFIG_GLOBAL: "/dev/null",
  GIT_CONFIG_SYSTEM: "/dev/null",
};

export function git(cwd, ...args) {
  return execFileSync("git", args, { cwd, encoding: "utf8", env: gitEnv }).trim();
}

/** A git repo with one commit on `main`, pushed to a bare `origin` next to it. */
export function gitRepoWithOrigin(root, name, files) {
  const repo = path.join(root, name);
  const origin = path.join(root, `${name}.git`);
  mkdirSync(repo, { recursive: true });
  git(repo, "init", "-q", "-b", "main");
  for (const [rel, content] of Object.entries(files)) {
    mkdirSync(path.dirname(path.join(repo, rel)), { recursive: true });
    writeFileSync(path.join(repo, rel), content);
  }
  git(repo, "add", "-A");
  git(repo, "commit", "-q", "-m", "fixture");
  execFileSync("git", ["init", "-q", "--bare", origin], { env: gitEnv });
  git(repo, "remote", "add", "origin", origin);
  git(repo, "push", "-q", "origin", "main");
  return { repo, origin };
}

export function marketingFixture(root) {
  return gitRepoWithOrigin(root, "marketing", {
    "site-content/install.html": `<html>\n<p>Android beta · Direct APK download</p>\n${LABEL_LINE}</html>\n`,
  });
}

export function installHtml(marketing) {
  return readFileSync(path.join(marketing, "site-content/install.html"), "utf8");
}

export function originMainSubject(origin) {
  return execFileSync("git", ["--git-dir", origin, "log", "-1", "--format=%s", "main"], { encoding: "utf8", env: gitEnv }).trim();
}

export function tempRoot(t, prefix) {
  const root = mkdtempSync(path.join(os.tmpdir(), prefix));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  return root;
}

/**
 * A workspace checkout at `<root>/code/<dirname>` holding copies of the publish
 * scripts, an android repo stub whose build-and-upload script just records its
 * invocation, a netmesh-go checkout with an origin, and a fake JDK.
 */
export function workspaceFixture(root, dirname) {
  const workspace = path.join(root, "code", dirname);
  for (const dir of ["scripts", "android/app/libs", "android/scripts"]) {
    mkdirSync(path.join(workspace, dir), { recursive: true });
  }
  for (const name of ["publish-android-apk", "bump-android-downloads-card"]) {
    cpSync(path.join(scripts, name), path.join(workspace, "scripts", name));
    chmodSync(path.join(workspace, "scripts", name), 0o755);
  }
  writeFileSync(path.join(workspace, "android/app/build.gradle.kts"), '    versionCode = 7\n    versionName = "0.2.6"\n');
  writeFileSync(path.join(workspace, "android/app/libs/netmeshgo.aar"), "not really an aar");
  const buildLog = path.join(root, "build-and-upload.log");
  writeFileSync(
    path.join(workspace, "android/scripts/build-and-upload-apk.sh"),
    `#!/usr/bin/env bash\nprintf 'JAVA_HOME=%s\\n' "\${JAVA_HOME:-}" >> "${buildLog}"\n`,
    { mode: 0o755 },
  );
  const javaHome = path.join(root, "jdk");
  mkdirSync(path.join(javaHome, "bin"), { recursive: true });
  writeFileSync(path.join(javaHome, "bin/javac"), "#!/usr/bin/env bash\nexit 0\n", { mode: 0o755 });
  const netmesh = gitRepoWithOrigin(root, "netmesh-go", { "go.mod": "module netmesh\n" });
  const netmeshMainSha = git(netmesh.repo, "rev-parse", "HEAD");
  return { workspace, buildLog, javaHome, netmeshDir: netmesh.repo, netmeshMainSha };
}

export function writeAarSha(workspace, sha) {
  writeFileSync(path.join(workspace, "android/app/libs/netmeshgo.aar.netmesh-sha"), `${sha}\n`);
}

export function run(script, args, env) {
  return spawnSync("bash", [script, ...args], { encoding: "utf8", env: { ...gitEnv, ...env } });
}
