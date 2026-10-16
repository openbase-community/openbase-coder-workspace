import assert from "node:assert/strict";
import { writeFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

import { LABEL_LINE, git, installHtml, marketingFixture, originMainSubject, run, scripts, tempRoot } from "./android-publish-fixture.mjs";

const script = path.join(scripts, "bump-android-downloads-card");

function bump(marketing, ...args) {
  return run(script, args, { MARKETING_REPO: marketing });
}

test("requires a version argument", (t) => {
  const { repo } = marketingFixture(tempRoot(t, "bump-card-"));
  const result = bump(repo);
  assert.equal(result.status, 2);
  assert.match(result.stderr, /Usage: bump-android-downloads-card VERSION/);
});

test("rejects a value that is not a versionName", (t) => {
  const { repo } = marketingFixture(tempRoot(t, "bump-card-"));
  const result = bump(repo, "latest");
  assert.equal(result.status, 1);
  assert.match(result.stderr, /does not look like an Android versionName/);
});

test("--dry-run reports the label change without writing or pushing", (t) => {
  const { repo, origin } = marketingFixture(tempRoot(t, "bump-card-"));
  const result = bump(repo, "0.2.6", "--dry-run");
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /'Direct APK · v0\.2\.5' -> 'Direct APK · v0\.2\.6'/);
  assert.match(result.stdout, /\[dry-run\] would: git push origin main/);
  assert.equal(installHtml(repo).includes(LABEL_LINE), true);
  assert.equal(originMainSubject(origin), "fixture");
});

test("bumps only the version, keeps the trailing card copy, commits and pushes origin main", (t) => {
  const { repo, origin } = marketingFixture(tempRoot(t, "bump-card-"));
  const result = bump(repo, "v0.2.6");
  assert.equal(result.status, 0, result.stderr);
  const html = installHtml(repo);
  assert.equal(html.includes(LABEL_LINE.replace("v0.2.5", "v0.2.6")), true);
  assert.equal(html.includes("v0.2.5"), false);
  assert.equal(originMainSubject(origin), "Downloads page: bump Android APK card to v0.2.6");
  assert.match(result.stdout, /bumped to v0\.2\.6 and pushed/);
});

test("is a no-op when the card already shows the version", (t) => {
  const { repo, origin } = marketingFixture(tempRoot(t, "bump-card-"));
  const result = bump(repo, "0.2.5");
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /already at 'Direct APK · v0\.2\.5'/);
  assert.equal(originMainSubject(origin), "fixture");
});

test("skips with a warning when install.html has local edits", (t) => {
  const { repo, origin } = marketingFixture(tempRoot(t, "bump-card-"));
  writeFileSync(path.join(repo, "site-content/install.html"), `${installHtml(repo)}<!-- wip -->\n`);
  const result = bump(repo, "0.2.6");
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stderr, /WARNING: .*uncommitted local changes/);
  assert.equal(originMainSubject(origin), "fixture");
});

test("skips with a warning when the marketing checkout is missing", (t) => {
  const root = tempRoot(t, "bump-card-");
  const result = bump(path.join(root, "nowhere"), "0.2.6");
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stderr, /WARNING: Marketing repo checkout missing/);
});

test("refuses to edit when the label pattern is not matched exactly once", (t) => {
  const { repo, origin } = marketingFixture(tempRoot(t, "bump-card-"));
  writeFileSync(path.join(repo, "site-content/install.html"), "<html>\n<p>no card here</p>\n</html>\n");
  // Commit so the file is clean (otherwise the dirty-file skip fires first).
  git(repo, "commit", "-q", "-am", "drop card");
  const result = bump(repo, "0.2.6");
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Expected exactly one Android APK card label .* found 0/);
  assert.equal(originMainSubject(origin), "fixture");
});

