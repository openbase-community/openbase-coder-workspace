import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { browser } from "@wdio/globals";
import { loadDeviceEnv, packageRoot } from "../support/deviceEnv.js";
import {
  assertApprovedSignupEmail,
  ensureSignedOutAtWelcome,
  generateSignupPassword,
  openEmailSignIn,
  openSignupForm,
  submitSignupForm,
  waitForSignupOutcome,
} from "../support/signupFlow.js";

// This spec drives real account creation against production Openbase Cloud with
// an exact allowlisted Resend testing recipient. The surrounding field-test
// procedure retrieves the rendered message and completes normal verification.
// It must run against the isolated field-test app variant, never the normal app.
describe("Openbase iOS account creation against production cloud", () => {
  const env = loadDeviceEnv({ requirePhysicalDevice: true });

  it("signs up with email and reaches the Verify Your Email screen", async function (this: Mocha.Context) {
    const email = process.env.OPENBASE_E2E_SIGNUP_EMAIL;
    if (!email) {
      throw new Error(
        "OPENBASE_E2E_SIGNUP_EMAIL is required; there is no personal-inbox fallback.",
      );
    }
    assertApprovedSignupEmail(email);
    const password = process.env.OPENBASE_E2E_SIGNUP_PASSWORD || generateSignupPassword();
    console.warn(`Signing up with separately authorized test recipient ${email}.`);

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
      console.warn(`Account created; retrieve and verify the exact Resend test message for ${email}.`);
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
