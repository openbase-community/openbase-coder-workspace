import { randomBytes } from "node:crypto";
import { $, browser } from "@wdio/globals";
import type { DeviceEnv } from "./deviceEnv.js";

// Live signup runs create real production accounts and trigger real Resend
// verification emails. Every address must deliver to Gabe's own mailbox so a
// test can never bounce mail and damage sender reputation; Gmail plus
// addressing keeps each attempt unique while landing in the same inbox.
const approvedSignupMailboxPattern = /^montague\.gabe(\+[A-Za-z0-9._-]+)?@gmail\.com$/;

const freshStartArgument = "--openbase-fresh-start";

const welcomeSelectors = [
  "~Continue with email",
  '-ios predicate string:label == "Continue with email"',
];

const signupLinkSelectors = [
  '-ios predicate string:type == "XCUIElementTypeButton" AND label == "Sign up"',
  "~Sign up",
];

const signInScreenSelectors = [
  '-ios predicate string:label == "Sign In"',
  "~Sign In",
];

const createAccountButtonSelectors = [
  '-ios predicate string:type == "XCUIElementTypeButton" AND label == "Create Account"',
  "~Create Account",
];

const verifyEmailSelectors = [
  "~Verify Your Email",
  '-ios predicate string:label == "Verify Your Email"',
  "~I've Verified My Email",
];

const emailFieldSelectors = [
  '-ios predicate string:type == "XCUIElementTypeTextField" AND (name == "Email" OR label == "Email" OR value == "Email")',
  "-ios class chain:**/XCUIElementTypeTextField[1]",
];

const passwordFieldSelectors = [
  '-ios predicate string:type == "XCUIElementTypeSecureTextField" AND (name == "Password" OR label == "Password" OR value == "Password")',
  "-ios class chain:**/XCUIElementTypeSecureTextField[1]",
];

const confirmPasswordFieldSelectors = [
  '-ios predicate string:type == "XCUIElementTypeSecureTextField" AND (name == "Confirm Password" OR label == "Confirm Password" OR value == "Confirm Password")',
  "-ios class chain:**/XCUIElementTypeSecureTextField[2]",
];

const signupErrorPatterns = [
  /couldn.{0,3}t be read/i,
  /because it is missing/i,
  /correct format/i,
  /already registered/i,
  /something went wrong/i,
  /unable to/i,
  /try again/i,
  /this password/i,
  /too short|too common|entirely numeric/i,
  /this field is required/i,
];

export type SignupOutcome =
  | { kind: "verify-email" }
  | { kind: "error"; matchedText: string; texts: string[] }
  | { kind: "timeout"; texts: string[] };

export function assertApprovedSignupEmail(email: string): void {
  if (!approvedSignupMailboxPattern.test(email)) {
    throw new Error(
      `Refusing to sign up with ${email}: live signup must use montague.gabe@gmail.com `
        + "(plus-addressing allowed) so no production email can ever bounce.",
    );
  }
}

export function buildSignupEmail(now: Date): string {
  const stamp = [
    now.getFullYear(),
    pad(now.getMonth() + 1),
    pad(now.getDate()),
  ].join("") + "-" + [pad(now.getHours()), pad(now.getMinutes()), pad(now.getSeconds())].join("");
  return `montague.gabe+ios-e2e-${stamp}@gmail.com`;
}

export function generateSignupPassword(): string {
  return `Openbase-e2e-${randomBytes(4).toString("hex")}`;
}

export async function ensureSignedOutAtWelcome(env: DeviceEnv): Promise<void> {
  await relaunchAppWithFreshStart(env);
  if (await waitForAny(welcomeSelectors, 30_000)) {
    return;
  }

  // The fresh-start launch argument is compiled out of release builds; fall
  // back to the in-app sign-out flow (account surface -> Sign Out -> confirm).
  await clickFirstExisting(["~nav.account", "~Account"]);
  await browser.pause(1_000);
  for (let attempt = 0; attempt < 4; attempt += 1) {
    if (await clickFirstExisting(['-ios predicate string:label == "Sign Out"', "~Sign Out"])) {
      break;
    }
    await swipeUp();
  }
  await browser.pause(1_000);
  await clickFirstExisting([
    '-ios predicate string:type == "XCUIElementTypeButton" AND label == "Sign Out"',
  ]);

  if (!(await waitForAny(welcomeSelectors, 30_000))) {
    const source = await browser.getPageSource();
    throw new Error(
      "Unable to reach the signed-out Welcome screen: the fresh-start launch argument "
        + "had no effect (release build?) and the in-app sign-out fallback did not land on "
        + `"Continue with email". Page source excerpt: ${source.slice(0, 1500)}`,
    );
  }
}

export async function openEmailSignIn(): Promise<void> {
  await clickRequired(welcomeSelectors, 'welcome button "Continue with email"');
  if (!(await waitForAny([...signupLinkSelectors, ...signInScreenSelectors], 30_000))) {
    const source = await browser.getPageSource();
    throw new Error(`Sign In screen never appeared after "Continue with email". Page source excerpt: ${source.slice(0, 1500)}`);
  }
}

export async function openSignupForm(): Promise<void> {
  if (!(await waitForAny(signupLinkSelectors, 15_000))) {
    const source = await browser.getPageSource();
    throw new Error(
      'The "Sign up" link is missing from the Sign In screen. Either the production allauth '
        + "config has signup disabled (signupAllowed=false) or the config fetch failed. "
        + `Page source excerpt: ${source.slice(0, 1500)}`,
    );
  }
  await clickRequired(signupLinkSelectors, '"Sign up" link');
  if (!(await waitForAny(createAccountButtonSelectors, 30_000))) {
    const source = await browser.getPageSource();
    throw new Error(`Create Account screen never appeared. Page source excerpt: ${source.slice(0, 1500)}`);
  }
}

export async function submitSignupForm(email: string, password: string): Promise<void> {
  assertApprovedSignupEmail(email);
  await setRequiredValue(emailFieldSelectors, email, "email field");
  await setRequiredValue(passwordFieldSelectors, password, "password field");
  await setRequiredValue(confirmPasswordFieldSelectors, password, "confirm-password field");

  // The keyboard can cover the submit button; retry with an upward swipe.
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      await clickRequired(createAccountButtonSelectors, '"Create Account" button');
      return;
    } catch (error) {
      if (attempt === 2) {
        throw error;
      }
      await swipeUp();
    }
  }
}

export async function waitForSignupOutcome(timeoutMs: number): Promise<SignupOutcome> {
  const startedAt = Date.now();
  let lastTexts: string[] = [];
  while (Date.now() - startedAt < timeoutMs) {
    await dismissSystemAlertIfPresent();
    if (await existsAny(verifyEmailSelectors)) {
      return { kind: "verify-email" };
    }
    lastTexts = await readVisibleTexts();
    const matchedText = lastTexts.find(text => signupErrorPatterns.some(pattern => pattern.test(text)));
    if (matchedText !== undefined) {
      return { kind: "error", matchedText, texts: lastTexts };
    }
    await browser.pause(1_000);
  }
  return { kind: "timeout", texts: lastTexts };
}

export async function readVisibleTexts(): Promise<string[]> {
  const source = await browser.getPageSource();
  const texts = new Set<string>();
  for (const match of source.matchAll(/(?:label|value)="([^"]+)"/g)) {
    const text = decodeXmlEntities(match[1]).trim();
    if (text) {
      texts.add(text);
    }
  }
  return [...texts];
}

async function relaunchAppWithFreshStart(env: DeviceEnv): Promise<void> {
  await browser.terminateApp(env.bundleId);
  await browser.pause(1_000);
  await browser.execute("mobile: launchApp", {
    bundleId: env.bundleId,
    arguments: [freshStartArgument],
  });
  await browser.pause(3_000);
}

async function existsAny(selectors: string[]): Promise<boolean> {
  for (const selector of selectors) {
    const element = await $(selector);
    if (await element.isExisting()) {
      return true;
    }
  }
  return false;
}

async function waitForAny(selectors: string[], timeoutMs: number): Promise<boolean> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (await existsAny(selectors)) {
      return true;
    }
    await browser.pause(500);
  }
  return false;
}

async function clickFirstExisting(selectors: string[]): Promise<boolean> {
  for (const selector of selectors) {
    const element = await $(selector);
    if (await element.isExisting()) {
      await element.click();
      return true;
    }
  }
  return false;
}

async function clickRequired(selectors: string[], description: string): Promise<void> {
  if (!(await clickFirstExisting(selectors))) {
    const source = await browser.getPageSource();
    throw new Error(`Unable to find ${description}. Page source excerpt: ${source.slice(0, 1500)}`);
  }
}

async function setRequiredValue(selectors: string[], value: string, description: string): Promise<void> {
  for (const selector of selectors) {
    const element = await $(selector);
    if (await element.isExisting()) {
      await element.click();
      await element.setValue(value);
      return;
    }
  }
  const source = await browser.getPageSource();
  throw new Error(`Unable to find ${description}. Page source excerpt: ${source.slice(0, 1500)}`);
}

async function swipeUp(): Promise<void> {
  await browser.execute("mobile: swipe", { direction: "up" });
  await browser.pause(500);
}

async function dismissSystemAlertIfPresent(): Promise<void> {
  try {
    const alertText = await browser.getAlertText();
    if (alertText) {
      console.warn(`Dismissing unexpected system alert during signup: ${alertText}`);
      await browser.dismissAlert();
    }
  } catch {
    // No alert present.
  }
}

function decodeXmlEntities(value: string): string {
  return value
    .replace(/&#(\d+);/g, (_, code: string) => String.fromCodePoint(Number(code)))
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}
