import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { browser } from "@wdio/globals";
import { loadDeviceEnv, packageRoot } from "../support/deviceEnv.js";
import {
  assertApprovedSignupEmail,
  buildSignupEmail,
  ensureSignedOutAtWelcome,
  generateSignupPassword,
  openEmailSignIn,
  openSignupForm,
  submitSignupForm,
  waitForSignupOutcome,
} from "../support/signupFlow.js";

// This spec drives the real account-creation pathway against production
// Openbase Cloud (https://app.openbase.cloud). It creates a real account and
// production Resend sends a real verification email, so the address is locked
// to Gabe's own mailbox via plus addressing. It signs the phone out of the
// current session first; after the run, sign back in manually.
describe("Openbase iOS account creation against production cloud", () => {
  const env = loadDeviceEnv({ requirePhysicalDevice: true });

  it("signs up with email and reaches the Verify Your Email screen", async function (this: Mocha.Context) {
    const email = process.env.OPENBASE_E2E_SIGNUP_EMAIL || buildSignupEmail(new Date());
    assertApprovedSignupEmail(email);
    const password = process.env.OPENBASE_E2E_SIGNUP_PASSWORD || generateSignupPassword();
    console.warn(`Signing up with ${email}; password (kept for later account cleanup): ${password}`);

    try {
      await ensureSignedOutAtWelcome(env);
      await openEmailSignIn();
      await openSignupForm();
      await submitSignupForm(email, password);

      const outcome = await waitForSignupOutcome(90_000);
      if (outcome.kind === "error") {
        const decodeFailure = /couldn.{0,3}t be read|because it is missing|correct format/i.test(outcome.matchedText);
        throw new Error(
          `Account creation failed with on-screen error: "${outcome.matchedText}"`
            + (decodeFailure ? " (client-side response decode failure — matches the reported bug)" : "")
            + `. All visible texts: ${JSON.stringify(outcome.texts)}`,
        );
      }
      if (outcome.kind === "timeout") {
        throw new Error(
          "Account creation neither reached the Verify Your Email screen nor showed a "
            + `recognizable error within 90s. Visible texts: ${JSON.stringify(outcome.texts)}`,
        );
      }
      console.warn(`Account created; production sent a verification email to ${email}.`);
    } finally {
      try {
        const artifactsDir = resolve(packageRoot, "artifacts");
        mkdirSync(artifactsDir, { recursive: true });
        const screenshotPath = resolve(artifactsDir, `account-creation-${Date.now()}.png`);
        await browser.saveScreenshot(screenshotPath);
        console.warn(`Final screen captured at ${screenshotPath}`);
      } catch (error) {
        console.warn(`Unable to capture final screenshot: ${String(error)}`);
      }
    }
  });
});
