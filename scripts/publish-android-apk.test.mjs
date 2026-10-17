import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { installHtml, marketingFixture, originMainSubject, run, tempRoot, workspaceFixture, writeAarSha } from "./android-publish-fixture.mjs";

function publish(fx, marketing, ...args) {
  return run(path.join(fx.workspace, "scripts/publish-android-apk"), args, {
    MARKETING_REPO: marketing,
    NETMESH_GO_DIR: fx.netmeshDir,
    JAVA_HOME: fx.javaHome,
    PATH: process.env.PATH,
  });
}

test("refuses to build in a trunk checkout, before any other check", (t) => {
  const root = tempRoot(t, "publish-apk-");
  const fx = workspaceFixture(root, "openbase-coder-workspace");
  const { repo } = marketingFixture(root);
  const result = publish(fx, repo, "--dry-run");
  assert.equal(result.status, 2);
  assert.match(result.stderr, /refusing to build in the trunk checkout/);
  assert.match(result.stderr, /multi worktree add <name>/);
  assert.doesNotMatch(result.stderr, /netmesh/);
});

test("refuses when the AAR has no recorded netmesh-go commit", (t) => {
  const root = tempRoot(t, "publish-apk-");
  const fx = workspaceFixture(root, "openbase-coder-workspace-worktrees/task");
  const { repo } = marketingFixture(root);
  const result = publish(fx, repo, "--dry-run");
  assert.equal(result.status, 1);
  assert.match(result.stderr, /netmeshgo\.aar\.netmesh-sha is missing/);
  assert.match(result.stderr, /build-netmeshgo-aar\.sh/);
  assert.equal(existsSync(fx.buildLog), false);
});

test("refuses a stale AAR built from a commit other than netmesh-go main", (t) => {
  const root = tempRoot(t, "publish-apk-");
  const fx = workspaceFixture(root, "openbase-coder-workspace-worktrees/task");
  const { repo, origin } = marketingFixture(root);
  writeAarSha(fx.workspace, "0123456789abcdef0123456789abcdef01234567");
  const result = publish(fx, repo);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /stale VPN engine/);
  assert.match(result.stderr, /netmesh-go main is/);
  assert.equal(existsSync(fx.buildLog), false);
  assert.equal(originMainSubject(origin), "fixture");
});

test("refuses a sidecar that is not a full commit SHA", (t) => {
  const root = tempRoot(t, "publish-apk-");
  const fx = workspaceFixture(root, "openbase-coder-workspace-worktrees/task");
  const { repo } = marketingFixture(root);
  writeAarSha(fx.workspace, "abc123");
  const result = publish(fx, repo, "--dry-run");
  assert.equal(result.status, 1);
  assert.match(result.stderr, /does not contain a full commit SHA/);
});

test("--dry-run with a current AAR passes the guards and touches nothing", (t) => {
  const root = tempRoot(t, "publish-apk-");
  const fx = workspaceFixture(root, "openbase-coder-workspace-worktrees/task");
  const { repo, origin } = marketingFixture(root);
  writeAarSha(fx.workspace, fx.netmeshMainSha);
  const result = publish(fx, repo, "--dry-run");
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /VPN engine OK: netmeshgo\.aar built from netmesh-go main/);
  assert.match(result.stdout, /versionName: 0\.2\.6/);
  assert.match(result.stdout, /\[dry-run\] would run: JAVA_HOME=.*build-and-upload-apk\.sh/);
  assert.match(result.stdout, /'Direct APK · v0\.2\.5' -> 'Direct APK · v0\.2\.6'/);
  assert.match(result.stdout, /\[dry-run\] would: git push origin main/);
  assert.equal(existsSync(fx.buildLog), false);
  assert.equal(originMainSubject(origin), "fixture");
});

test("with a current AAR builds via the android script under the detected JDK, then bumps the card", (t) => {
  const root = tempRoot(t, "publish-apk-");
  const fx = workspaceFixture(root, "openbase-coder-workspace-worktrees/task");
  const { repo, origin } = marketingFixture(root);
  writeAarSha(fx.workspace, fx.netmeshMainSha);
  const result = publish(fx, repo);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(readFileSync(fx.buildLog, "utf8"), `JAVA_HOME=${fx.javaHome}\n`);
  assert.equal(installHtml(repo).includes("Direct APK · v0.2.6 · prefer the Google Play beta above"), true);
  assert.equal(originMainSubject(origin), "Downloads page: bump Android APK card to v0.2.6");
});
