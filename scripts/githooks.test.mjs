// Tests for the workspace git hooks in .githooks/. Each test copies the hooks
// into a throwaway workspace (root repo + sub-repos + bare remotes) and wires
// core.hooksPath the way `multi hooks install` does: relative in the root,
// absolute in sub-repos.
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { chmodSync, cpSync, mkdirSync, realpathSync, writeFileSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const HOOKS_SOURCE = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", ".githooks");
const HAS_GITLEAKS = spawnSync("sh", ["-c", "command -v gitleaks || test -x /opt/homebrew/bin/gitleaks"]).status === 0;
const IDENTITY = ["-c", "user.name=Hook Test", "-c", "user.email=hook-test@example.invalid"];

// Built at runtime so this file never contains a scannable secret.
const FAKE_AWS_KEY = ["AKIA", "QYLPMN5HHHFPZAM2"].join("");
const SECRET_FILE = `aws_access_key_id = "${FAKE_AWS_KEY}"\n`;

function git(cwd, args, env = {}) {
  return spawnSync("git", [...IDENTITY, ...args], {
    cwd,
    encoding: "utf8",
    env: { ...process.env, OPENBASE_SKIP_SECRET_HOOKS: "", ...env },
  });
}

function gitOk(cwd, args) {
  const result = git(cwd, args);
  assert.equal(result.status, 0, `git ${args.join(" ")} failed:\n${result.stderr}`);
  return result.stdout.trim();
}

function initRepo(dir, remotes, name, origin) {
  mkdirSync(dir, { recursive: true });
  gitOk(dir, ["init", "-q", "-b", "main"]);
  writeFileSync(path.join(dir, "README.md"), `# ${name}\n`);
  gitOk(dir, ["add", "README.md"]);
  gitOk(dir, ["commit", "-q", "--no-verify", "-m", "init"]);
  const bare = path.join(remotes, `${name}.git`);
  execFileSync("git", ["init", "-q", "--bare", bare]);
  gitOk(dir, ["remote", "add", "origin", bare]);
  gitOk(dir, ["push", "-q", "--no-verify", "origin", "main"]);
  // Hooks identify repos by origin owner/name; point the fetch URL at the
  // bare remote and the reported URL at a GitHub-style slug.
  gitOk(dir, ["config", "remote.origin.pushurl", bare]);
  gitOk(dir, ["remote", "set-url", "origin", `https://github.com/${origin}`]);
  gitOk(dir, ["config", "remote.origin.pushurl", bare]);
}

async function workspace(t) {
  const base = realpathSync(await mkdtemp(path.join(os.tmpdir(), "openbase-githooks-")));
  t.after(() => rm(base, { force: true, recursive: true }));
  const root = path.join(base, "workspace");
  const remotes = path.join(base, "remotes");
  mkdirSync(remotes);
  initRepo(root, remotes, "root", "openbase-community/openbase-coder-workspace");
  cpSync(HOOKS_SOURCE, path.join(root, ".githooks"), { recursive: true });
  writeFileSync(path.join(root, ".githooks", "private-repos"), "# test\nexample/private-repo\n");
  writeFileSync(path.join(root, ".gitignore"), "public/\nprivate/\n");
  gitOk(root, ["add", ".githooks", ".gitignore"]);
  gitOk(root, ["commit", "-q", "--no-verify", "-m", "hooks"]);
  gitOk(root, ["push", "-q", "--no-verify", "origin", "main"]);
  gitOk(root, ["config", "core.hooksPath", ".githooks"]);

  const repos = {};
  for (const [name, origin] of [
    ["public", "example/public-repo"],
    ["private", "example/private-repo"],
  ]) {
    repos[name] = path.join(root, name);
    initRepo(repos[name], remotes, name, origin);
    gitOk(repos[name], ["config", "core.hooksPath", path.join(root, ".githooks")]);
  }
  return { root, ...repos };
}

function stageFile(repo, relPath, content) {
  mkdirSync(path.dirname(path.join(repo, relPath)), { recursive: true });
  writeFileSync(path.join(repo, relPath), content);
  gitOk(repo, ["add", "-f", relPath]);
}

function commit(repo, env) {
  return git(repo, ["commit", "-q", "-m", "change"], env);
}

function push(repo, env) {
  return git(repo, ["push", "-q", "origin", "HEAD:main"], env);
}

function prePush(repo, input, env = {}) {
  return spawnSync(path.join(repo, ".githooks", "pre-push"), ["origin", "unused"], {
    cwd: repo,
    encoding: "utf8",
    input,
    env: { ...process.env, OPENBASE_SKIP_SECRET_HOOKS: "1", ...env },
  });
}

const scanTest = HAS_GITLEAKS ? test : test.skip;

scanTest("pre-commit refuses a staged secret in a sub-repo and in the root", async (t) => {
  const ws = await workspace(t);
  for (const repo of [ws.public, ws.root]) {
    stageFile(repo, "creds.py", SECRET_FILE);
    const result = commit(repo);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /pre-commit: BLOCKED - gitleaks found a likely secret/);
    assert.match(result.stderr, /aws-access-token/);
    assert.doesNotMatch(result.stderr + result.stdout, new RegExp(FAKE_AWS_KEY));
  }
});

scanTest("pre-commit allows a clean change", async (t) => {
  const ws = await workspace(t);
  stageFile(ws.public, "clean.txt", "nothing to see\n");
  assert.equal(commit(ws.public).status, 0);
});

scanTest("pre-commit honours the repo's .gitleaks.toml allowlist", async (t) => {
  const ws = await workspace(t);
  stageFile(
    ws.public,
    ".gitleaks.toml",
    `[extend]\nuseDefault = true\n[[allowlists]]\npaths = ['''^fixtures/creds\\.py$''']\n`,
  );
  stageFile(ws.public, "fixtures/creds.py", SECRET_FILE);
  const result = commit(ws.public);
  assert.equal(result.status, 0, result.stderr);
});

scanTest("the bypass variable skips only the secret scan, loudly", async (t) => {
  const ws = await workspace(t);
  stageFile(ws.public, "creds.py", SECRET_FILE);
  const result = commit(ws.public, { OPENBASE_SKIP_SECRET_HOOKS: "1" });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stderr, /OPENBASE_SKIP_SECRET_HOOKS=1: the gitleaks secret scan is SKIPPED/);

  stageFile(ws.public, ".reports/r.md", "# report\n");
  const reports = commit(ws.public, { OPENBASE_SKIP_SECRET_HOOKS: "1" });
  assert.notEqual(reports.status, 0);
  assert.match(reports.stderr, /\.reports\/ is private/);
});

test("a missing gitleaks blocks with install instructions", async (t) => {
  const ws = await workspace(t);
  stageFile(ws.public, "clean.txt", "fine\n");
  const result = commit(ws.public, { OPENBASE_GITLEAKS: "/nonexistent/gitleaks" });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /gitleaks is not installed/);
  assert.match(result.stderr, /brew install gitleaks/);
  assert.match(result.stderr, /OPENBASE_SKIP_SECRET_HOOKS=1/);
});

scanTest("pre-commit refuses tracked .reports in public repos only", async (t) => {
  const ws = await workspace(t);
  stageFile(ws.public, ".reports/r.md", "# report\n");
  const blocked = commit(ws.public);
  assert.notEqual(blocked.status, 0);
  assert.match(blocked.stderr, /\.reports\/ is private and must never be tracked/);
  assert.match(blocked.stderr, /\.reports\/r\.md/);

  stageFile(ws.private, ".reports/r.md", "# report\n");
  assert.equal(commit(ws.private).status, 0);
});

scanTest("pre-push refuses commits containing a secret", async (t) => {
  const ws = await workspace(t);
  stageFile(ws.public, "creds.py", SECRET_FILE);
  gitOk(ws.public, ["commit", "-q", "--no-verify", "-m", "sneak"]);
  const result = push(ws.public);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /pre-push: BLOCKED - gitleaks found a likely secret/);
});

scanTest("pre-push scans a new branch only for commits not on the remote", async (t) => {
  const ws = await workspace(t);
  stageFile(ws.public, "clean.txt", "fine\n");
  gitOk(ws.public, ["commit", "-q", "-m", "clean"]);
  const result = git(ws.public, ["push", "-q", "origin", "HEAD:refs/heads/feature"]);
  assert.equal(result.status, 0, result.stderr);
});

scanTest("pre-push refuses .reports commits in public repos", async (t) => {
  const ws = await workspace(t);
  stageFile(ws.public, ".reports/r.md", "# report\n");
  gitOk(ws.public, ["commit", "-q", "--no-verify", "-m", "report"]);
  const result = push(ws.public);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /commits add or change private \.reports\/ paths/);
});

scanTest("pre-push chains a sub-repo's own .githooks/pre-push guard", async (t) => {
  const ws = await workspace(t);
  const guard = path.join(ws.public, ".githooks", "pre-push");
  mkdirSync(path.dirname(guard), { recursive: true });
  writeFileSync(guard, "#!/bin/sh\nread -r _ sha _ _\necho \"repo guard saw $sha\" >&2\nexit 1\n");
  chmodSync(guard, 0o755);
  stageFile(ws.public, "clean.txt", "fine\n");
  gitOk(ws.public, ["commit", "-q", "-m", "clean"]);
  const head = gitOk(ws.public, ["rev-parse", "HEAD"]);
  const result = push(ws.public);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, new RegExp(`repo guard saw ${head}`));
});

scanTest("pre-push chains the root repo's own guard from .githooks/root/", async (t) => {
  const ws = await workspace(t);
  const guard = path.join(ws.root, ".githooks", "root", "pre-push");
  mkdirSync(path.dirname(guard), { recursive: true });
  writeFileSync(guard, "#!/bin/sh\necho 'root guard ran' >&2\nexit 1\n");
  chmodSync(guard, 0o755);
  stageFile(ws.root, "clean.txt", "fine\n");
  gitOk(ws.root, ["commit", "-q", "-m", "clean"]);
  const result = push(ws.root);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /root guard ran/);
});

test("root pre-push guard scans when the remote sha is unknown locally", async (t) => {
  const ws = await workspace(t);
  stageFile(ws.root, "netmesh-go/private.txt", "private\n");
  gitOk(ws.root, ["commit", "-q", "--no-verify", "-m", "private"]);
  const head = gitOk(ws.root, ["rev-parse", "HEAD"]);
  const unknownRemote = "f".repeat(40);
  const result = prePush(ws.root, `refs/heads/main ${head} refs/heads/main ${unknownRemote}\n`);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /commit [0-9a-f]{40} touches a private path/);
  assert.match(result.stderr, /netmesh-go\/private\.txt/);
});
