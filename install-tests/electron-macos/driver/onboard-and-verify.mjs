// Playwright-Electron clickthrough + verification for the Openbase Coder macOS
// install flow. Runs INSIDE a disposable Tart VM (see ../README.md), where no
// sandboxing is needed — the whole VM is the sandbox.
//
// It launches the installed /Applications app, advances onboarding to the Setup
// step, clicks "Run setup" and confirms, waits for `openbase-coder setup` to
// finish, then verifies the resulting install. UI copy can drift, so the pass
// criteria are the resulting SYSTEM STATE (installation.json, activated
// standalone package, launchd services, doctor), not screen text.
//
// Env:
//   APP_PATH   /Applications/<ProductName>.app   (required)
//   RESULT     path to write result JSON          (default: ./result.json)
//   TIMEOUT_MS overall budget                      (default: 900000 = 15 min)
//
// Exit code 0 iff every verification passed.

import { _electron as electron } from "playwright";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, existsSync, readdirSync } from "node:fs";
import os from "node:os";
import path from "node:path";

const APP_PATH = process.env.APP_PATH;
const RESULT = process.env.RESULT || path.resolve("result.json");
const TIMEOUT_MS = Number(process.env.TIMEOUT_MS || 900000);
const HOME = os.homedir();
const OPENBASE = process.env.OPENBASE_CODER_HOME || path.join(HOME, ".openbase");

const checks = [];
const record = (name, ok, detail = "") => {
  checks.push({ name, ok: !!ok, detail: String(detail) });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  — ${detail}` : ""}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function bundledCli() {
  // Prefer the launcher the install wired onto PATH; fall back to the activated
  // standalone package.
  const candidates = [
    path.join(HOME, ".local", "bin", "openbase-coder"),
    path.join(OPENBASE, "packages", "standalone", "current", "bin", "openbase-coder"),
  ];
  return candidates.find(existsSync) || "openbase-coder";
}

function appExecutable(appPath) {
  const plist = path.join(appPath, "Contents", "Info.plist");
  try {
    const exe = execFileSync("/usr/bin/defaults", ["read", plist.replace(/\.plist$/, ""), "CFBundleExecutable"])
      .toString().trim();
    return path.join(appPath, "Contents", "MacOS", exe);
  } catch {
    // Fall back to the single binary under MacOS/.
    const macos = path.join(appPath, "Contents", "MacOS");
    const only = execFileSync("/bin/ls", [macos]).toString().trim().split("\n")[0];
    return path.join(macos, only);
  }
}

// Onboarding wizard: Overview -> Prerequisites -> Setup -> (login/pairing, out
// of scope). Button texts, discovered empirically against the real app:
//   Overview:      "Let's get you set up"
//   Prerequisites: "Check prerequisites" / "Continue" (gated on Tailscale)
//   Setup:         "Run setup" -> confirmation modal
const ADVANCE = [
  /let'?s get you set up/i, /get you set up/i, /set up this mac/i,
  /continue to setup/i, /continue/i, /next/i,
  /get started/i, /proceed/i, /use launchd/i,
];
const SETUP_TRIGGER = [/run setup/i, /start setup/i];
// The confirmation modal's primary button is "I understand, run setup". Match
// ONLY that — a generic /run setup/ also matches the Setup page button behind
// the modal, and re-clicking it launches setup a SECOND time. Two concurrent
// setup runs make the app re-activate the bundled CLI, whose file collisions
// delete the running setup's own files mid-run and abort it before services.
const CONFIRM = [/i understand.*run setup/i, /i understand/i];

async function listButtons(page) {
  try {
    return await page.getByRole("button").evaluateAll((els) =>
      els
        .filter((e) => e.offsetParent !== null)
        .map((e) => (e.innerText || e.getAttribute("aria-label") || "").replace(/\s+/g, " ").trim())
        .filter(Boolean),
    );
  } catch {
    return [];
  }
}

// Click the first visible+enabled button whose accessible name matches any
// pattern. Returns the clicked button's label (string) or null.
async function clickButton(page, patterns) {
  for (const re of patterns) {
    const btn = page.getByRole("button", { name: re }).first();
    try {
      if ((await btn.isVisible()) && (await btn.isEnabled())) {
        const name = (await btn.innerText().catch(() => "")).replace(/\s+/g, " ").trim();
        await btn.click();
        return name || "(unnamed)";
      }
    } catch {
      /* not present this frame */
    }
  }
  return null;
}

const CURRENT_CLI = path.join(OPENBASE, "packages", "standalone", "current", "bin", "openbase-coder");

// A bundled-CLI activation is mid-copy when a `.staging-` release dir exists.
// Clicking Recheck/Activate during a copy starts a SECOND concurrent copy; they
// collide (ENOTEMPTY) and neither finishes, so `current` never populates. We
// therefore never trigger a prereq re-check or activation while one is running.
// Count `.staging-` copy dirs. A GROWING count means the app is still firing
// activations; a stable count (even if >0 from leftover failed copies) means
// activation has settled.
function stagingCount() {
  try {
    return readdirSync(path.join(OPENBASE, "packages", "standalone", "releases"))
      .filter((d) => d.includes(".staging-")).length;
  } catch {
    return 0;
  }
}

// The activated CLI is usable when its launcher actually runs. A half-copied /
// concurrently-clobbered `current` (the app re-activates on every prereq poll,
// and failing copies rmdir files out of the live release dir) will throw here.
function cliFunctional() {
  try {
    execFileSync(CURRENT_CLI, ["--version"], { stdio: "pipe", timeout: 20000 });
    return true;
  } catch {
    return false;
  }
}

async function driveOnboarding(page, deadline) {
  // Wizard: Overview -> Prerequisites -> Setup. On Prerequisites, "Continue to
  // setup" stays DISABLED until the bundled CLI is activated and Tailscale is
  // detected connected. The prereq page AUTO-triggers CLI activation on mount;
  // we wait for it to finish via the filesystem (CURRENT_CLI), nudging
  // "Activate CLI" at most once and never clicking during a copy. We never
  // click "Open Tailscale" (opens an external app; the VM is already on the
  // tailnet). Setup runs as a child process; completion is detected by
  // waitForSetupComplete, not UI text.
  let cliReady = false;
  let nudged = false;
  let stableTicks = 0;
  let lastStaging = -1;
  let lastDump = 0;
  while (Date.now() < deadline) {
    const trigger = await clickButton(page, SETUP_TRIGGER);
    if (trigger) {
      record(`clicked setup trigger: "${trigger}"`, true);
      // Confirm the modal, then VERIFY setup actually launched. The modal takes
      // a moment to render and its button text can vary, so retry the confirm
      // until the setup process/artifacts appear.
      const installJson = path.join(OPENBASE, "installation.json");
      let confirmed = null;
      let started = false;
      for (let i = 0; i < 12 && !started; i++) {
        await sleep(1500);
        const c = await clickButton(page, CONFIRM);
        if (c) confirmed = c;
        started = setupRunning() || existsSync(installJson);
      }
      record(`confirmed setup dialog: "${confirmed || "(none)"}"`, started, started ? "setup launched" : "setup did NOT start");
      return true;
    }

    // Phase A: get the bundled CLI activated AND SETTLED before advancing.
    // "Settled" = current exists, no staging copies pending, launcher runs, and
    // it has stayed that way for a couple of ticks. Advancing before the app's
    // activation churn stops means a later failing copy corrupts current and
    // setup dies. Once current is complete, the app's forward-only logic stops
    // re-activating.
    if (!cliReady) {
      const staging = stagingCount();
      const settled = existsSync(CURRENT_CLI) && cliFunctional() && staging === lastStaging;
      stableTicks = settled ? stableTicks + 1 : 0;
      lastStaging = staging;
      if (stableTicks >= 3) {
        cliReady = true;
        record("bundled CLI activated + settled (staging stable, --version ok)", true);
        await clickButton(page, [/check prerequisites/i, /recheck/i]); // refresh UI once
        await sleep(3000);
        continue;
      }
      // Still on the Overview intro? advance it (this lands us on Prerequisites,
      // which auto-starts activation).
      const intro = await clickButton(page, [/let'?s get you set up/i, /get you set up/i]);
      if (intro) {
        console.log(`  advanced via "${intro}"`);
        await sleep(1500);
        continue;
      }
      // Nudge activation ONCE if nothing has started copying after a while.
      if (!nudged && staging === 0 && !existsSync(CURRENT_CLI)) {
        const act = await clickButton(page, [/activate cli/i]);
        if (act) {
          nudged = true;
          console.log("  nudged activation via Activate CLI");
        }
      }
      if (Date.now() - lastDump > 6000) {
        console.log(`  waiting for CLI activation to settle (staging=${staging}, functional=${existsSync(CURRENT_CLI) && cliFunctional()}, stableTicks=${stableTicks})`);
        lastDump = Date.now();
      }
      await sleep(3000);
      continue;
    }

    // Phase B: CLI ready — advance to the Setup step.
    const advanced = await clickButton(page, ADVANCE);
    if (advanced) {
      console.log(`  advanced via "${advanced}"`);
      await sleep(1500);
      continue;
    }
    // Gated (e.g. Tailscale still verifying) — recheck occasionally. Safe now:
    // current is valid, so a re-check won't re-activate (forward-only).
    const rechecked = await clickButton(page, [/check prerequisites/i, /recheck/i]);
    if (rechecked) {
      console.log(`  re-scanned prerequisites via "${rechecked}"`);
      await sleep(4000);
      continue;
    }
    if (Date.now() - lastDump > 8000) {
      console.log(`  waiting on this step; visible buttons: ${JSON.stringify(await listButtons(page))}`);
      lastDump = Date.now();
    }
    await sleep(1500);
  }
  return false;
}

// True while `openbase-coder setup` is still running as a child of the app.
// The app spawns it via a login shell, so the cmdline is shell-quoted
// ('openbase-coder' 'setup' '--json-progress' ...); match the setup-only
// --json-progress flag, which is unique to this invocation.
function setupRunning() {
  for (const pat of ["json-progress", "openbase-coder. ?.?setup"]) {
    try {
      execFileSync("/usr/bin/pgrep", ["-f", pat], { stdio: "pipe" });
      return true;
    } catch {
      /* no match for this pattern */
    }
  }
  return false;
}

async function waitForSetupComplete(deadline) {
  const installJson = path.join(OPENBASE, "installation.json");
  // installation.json is written EARLY in setup (before the services and
  // Tailscale phases). If we returned here and closed the app, we'd kill the
  // setup child mid-flight and the launchd services would never install. So we
  // wait for the setup process itself to exit.
  let sawRunning = false;
  while (Date.now() < deadline) {
    const running = setupRunning();
    if (running) sawRunning = true;
    // Done when: setup has started (json written) or we saw the process run,
    // and it is no longer running. Re-confirm after a short settle.
    if (!running && (sawRunning || existsSync(installJson))) {
      await sleep(2500);
      if (!setupRunning()) break;
    }
    await sleep(2000);
  }
  try {
    return existsSync(installJson) ? JSON.parse(readFileSync(installJson, "utf8")) : null;
  } catch {
    return null;
  }
}

function verifyInstall() {
  const installJson = path.join(OPENBASE, "installation.json");
  record("installation.json exists", existsSync(installJson), installJson);
  let doc = {};
  if (existsSync(installJson)) {
    doc = JSON.parse(readFileSync(installJson, "utf8"));
    record("installation.json is standalone (desktop activates the bundled package)", doc.standalone === true, `standalone=${doc.standalone}`);
  }

  const current = path.join(OPENBASE, "packages", "standalone", "current");
  record("standalone package activated", existsSync(path.join(current, "bin", "openbase-coder")), current);
  const meta = path.join(current, "openbase-coder-package.json");
  if (existsSync(meta)) {
    const m = JSON.parse(readFileSync(meta, "utf8"));
    record("activated package metadata present", !!m.version, `version=${m.version}`);
  } else {
    record("activated package metadata present", false, meta);
  }

  // launchd services registered under the fixed label. Check both the
  // installed plists and the loaded domain.
  let plists = [];
  try {
    plists = execFileSync("/bin/ls", [path.join(HOME, "Library", "LaunchAgents")])
      .toString().split("\n").filter((f) => /openbase[.-]?coder/i.test(f));
  } catch { /* dir may not exist */ }
  let printed = "";
  try {
    printed = execFileSync("/bin/launchctl", ["print", `gui/${process.getuid()}`]).toString();
  } catch { /* domain query can fail */ }
  const loaded = plists.length > 0 || /com\.openbase\.coder/.test(printed);
  record(
    "launchd services installed (com.openbase.coder)",
    loaded,
    plists.length ? `${plists.length} plist(s): ${plists.join(", ")}` : "via launchctl print",
  );

  // doctor: services/ports/credentials health.
  const cli = bundledCli();
  try {
    const out = execFileSync(cli, ["doctor"], { timeout: 120000 }).toString();
    record("openbase-coder doctor ran", true, `${out.split("\n").length} lines`);
  } catch (e) {
    // doctor exits non-zero when unhealthy; capture but don't hard-fail the
    // whole run on health nuances — the install itself is what we assert.
    record("openbase-coder doctor ran", false, (e.stdout || e.message || "").toString().slice(0, 200));
  }
}

async function main() {
  const deadline = Date.now() + TIMEOUT_MS;
  if (!APP_PATH) throw new Error("APP_PATH env is required");
  const executablePath = appExecutable(APP_PATH);
  record("app executable located", existsSync(executablePath), executablePath);

  const app = await electron.launch({
    executablePath,
    args: [],
    env: {
      ...process.env,
      // Suppress the first-launch native installer-cleanup modal, which would
      // otherwise block automation (see live-installation-test skill).
      OPENBASE_DESKTOP_DISABLE_INSTALLER_CLEANUP: "1",
    },
  });

  let onboarded = false;
  try {
    const page = await app.firstWindow({ timeout: 60000 });
    await page.waitForLoadState("domcontentloaded").catch(() => {});
    record("app window opened", true);

    onboarded = await driveOnboarding(page, deadline);
    record("reached + triggered Setup step", onboarded);
  } finally {
    // Setup runs as a child process of the app; keep the app alive while we
    // wait for it to finish, then close.
    if (onboarded) {
      const doc = await waitForSetupComplete(deadline);
      record("setup completed (install artifacts appeared)", !!doc);
    }
    await app.close().catch(() => {});
  }

  verifyInstall();

  const passed = checks.every((c) => c.ok);
  writeFileSync(RESULT, JSON.stringify({ passed, checks }, null, 2));
  console.log(`\n${passed ? "ALL PASS" : "FAILURES PRESENT"} — wrote ${RESULT}`);
  process.exit(passed ? 0 : 1);
}

main().catch((err) => {
  console.error("driver error:", err);
  try { writeFileSync(RESULT, JSON.stringify({ passed: false, error: String(err), checks }, null, 2)); } catch {}
  process.exit(1);
});
