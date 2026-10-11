# Codex brief: enter a password or email code on a field-test phone

You are a Codex session dispatched by a Claude Code field-test session to perform one authentication step on a field-test phone against a hosted (staging) deployment. The project owner authorized Codex specifically for typing passwords and email verification codes into the field-test app variants. Do nothing else on the device.

Fill in before dispatching:
- DEVICE: <iPhone <model>, UDID <udid>, USB> | <Android <model>, adb serial <serial>, adb at ~/Library/Android/sdk/platform-tools/adb>
- APP: <iOS bundle id or Android package of the field-test variant>
- TASK: <sign-in with email code | sign-in with password | sign-up (new account)>
- ACCOUNT: <delivered+openbase-field-<slug>@resend.dev>
- HANDOFF FILE: <absolute path to the handoff .md>
- Read the `field-testing` skill sections "Field-Test Account Lifecycle" and "Direct Appium Interaction"; the appium MCP server is available (select_device, session create, find_element, set_value, gesture).

Protocol:
1. Poll HANDOFF FILE every 15 s until it contains `status: ready`. The Claude session has prepared the screen (email entered and Send code tapped, or the Sign Up form open with the email filled in) and has CLOSED its own Appium/WDA/UiAutomator2 session.
2. Open your own Appium session on DEVICE.
   - Email code: codes expire 180 s after sending, so tap the app's resend / "Sign in with a code instead", fetch the newest verification mail for ACCOUNT via the Resend CLI (`resend emails list --limit 100 --json`, then the message body), type the code immediately, submit. Repeat as needed.
   - Password sign-in: read the password from the macOS keychain item `openbase-field-test-<email-local-part>` (`security find-generic-password -s <item> -w`), type it, submit.
   - Sign-up: generate a 16+ character alphanumeric password, type it into both password fields, tap Create Account, then handle the verification code as above. Store the password: `security add-generic-password -a "<email>" -s "openbase-field-test-<email-local-part>" -w "<password>" -U`.
3. Confirm the app is past the auth screen (home/call screen or onboarding). Close your Appium session so the device is free.
4. Append to HANDOFF FILE: `status: done` (or `status: failed` with the exact error and what the screen shows), a timestamp, and for sign-up the keychain item name. Then run `tts "<device> <task> done"` (or "failed"). Stop.

Rules: never type into any other app or device; never start a call; never restart services; never touch ~/.openbase; if `status: ready` has not appeared after 30 minutes, write `status: timeout` and stop.
