# Signed macOS DMG field-test installation track

This document contains only the signed-DMG installation delta for a full field test. The root [`field-testing` skill's documentation-ownership section](../../.agents/skills/field-testing/SKILL.md#documentation-ownership-keep-the-install-tracks-dry) identifies and owns all behavior shared with the developer-install flow. Do not copy those procedures here; update the shared skill when a lesson applies to both tracks.

## Entry and completion gates

Begin with [Preflight Sequence step 0](../../.agents/skills/field-testing/SKILL.md#preflight-sequence) and remain inside the [blocking early iPhone VPN passcode gate](../../.agents/skills/field-testing/SKILL.md#blocking-early-iphone-vpn-passcode-gate) until it resolves as `VISIBLE` or genuinely `NOT_PRESENT`. After completing the signed-DMG steps below, return to the shared [Field-Test Procedure](../../.agents/skills/field-testing/SKILL.md#field-test-procedure). The run passes only when both the signed-DMG checks here and every shared smoke, acoustic, Super Agent, reporting, and teardown gate pass.

Signed-DMG-specific pass criteria:

- A channel DMG obtained through the public download path was installed into `/Applications` on a fresh SIP-enabled Tart clone.
- The downloaded artifact's version and SHA-256 were recorded, quarantine was present, deep/strict code-signature verification passed, and Gatekeeper accepted the notarized Developer ID app.
- Browser OAuth used the intended origin, and the installed CLI persisted that same Cloud origin.
- All nine desktop onboarding stages completed using the bundled CLI and real Openbase VPN.
- The embedded Netmesh components matched the sampled release, survived one VM reboot, and restored VPN plus backend health without rerunning setup.

## 1. Clone the VM used by this run

Use a new run-specific name and a SIP-enabled source. The default cirruslabs source is SIP-disabled and cannot exercise Openbase VPN; the shared skill owns the diagnosis and recovery for that failure.

```bash
./install-tests/electron-macos/manual-vm.sh \
  --source <sip-enabled-source> \
  --name <run-name> \
  --display 1600x900pt
```

Record the clone provenance immediately. Do not reuse an earlier VM for a result that will be reported as a field test. Choose the largest fixed guest resolution that fits the host; on a 1920x1200 host, use 1600x900pt. The shared skill owns the Tart display and input-recovery rules.

## 2. Acquire and verify the real channel artifact

Inside the VM, use `https://openbase.cloud/downloads?staging=true` for staging or `https://openbase.cloud/downloads` for production and click the page's normal download control. A direct release-bucket URL is a diagnostic fallback, not the complete user path; if it is needed, record the public download surface as untested and follow the fallback in the shared skill.

Keep the DMG in `~/Downloads`, open it in Finder, drag Openbase to Applications, and launch it through the ordinary Gatekeeper confirmation. Do not strip quarantine or right-click-bypass Gatekeeper during a signed-channel field test.

Before onboarding, record artifact identity and verify the installed app:

```bash
shasum -a 256 ~/Downloads/Openbase*.dmg
xattr -p com.apple.quarantine /Applications/Openbase.app
codesign --verify --deep --strict --verbose=2 /Applications/Openbase.app
spctl --assess --type execute --verbose=4 /Applications/Openbase.app
defaults read /Applications/Openbase.app/Contents/Info CFBundleShortVersionString
```

If a staging retry produces a replacement artifact, mount and verify the new DMG before replacing the installed app. Keep the previous app as a recoverable backup until Openbase has reconciled its registered helper; macOS can continue resolving a registered background helper through the moved bundle during replacement.

## 3. Drive release onboarding

Release builds fuse off Electron CDP. Apply the shared [Safari-before-OAuth procedure](../../.agents/skills/field-testing/SKILL.md#the-one-hard-boundary-never-touch-the-developers-state) before clicking the login action; if the visible OAuth page opens outside the controlled Safari window, use the shared `safari-adopt` recovery. Do not type credentials through Tart.

Drive all nine release onboarding stages: Overview → Prerequisites → Setup → Agent sign-in → Voice → Sign in → Phone → Pairing → Verify.

- Install and activate the bundled CLI at Prerequisites.
- Choose Openbase Cloud for coding agents and `openbase-cloud` audio unless the test matrix selects another real provider.
- Choose Openbase VPN. A signed non-developer build must offer Openbase VPN and Openbase Direct, not the developer-only standalone Tailscale option.
- Verify the browser origin before credentials are entered and verify `OPENBASE_CODER_CLI_WEB_BACKEND_URL` persisted afterward.
- Approve the Netmesh background item through System Settings with Computer Use, following the shared disposable-VM rule. Keep setup running while macOS authorization completes.
- Before pairing, apply shared Preflight checks 4.5–4.7, including Cloud netmesh configuration, model availability, and the actual backend-health check on port 7999. Port 49154 alone proves only that the Electron control shell is running.

## 4. Verify the embedded VPN components

Record both embedded Netmesh build numbers so a stale or wrong-channel prebuilt is visible:

```bash
/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' \
  /Applications/Openbase.app/Contents/Resources/OpenbaseNetmeshCompanion.app/Contents/Info.plist
/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' \
  /Applications/Openbase.app/Contents/Resources/OpenbaseNetmesh.app/Contents/Info.plist
```

For a staging DMG, require the builds expected by that staging release. Apply the shared post-approval readiness and concurrent-client checks; they are not repeated here.

For an upgrade test, launch the replacement app and compare `netmesh-ctl version` with the embedded build before rebooting. The already-onboarded desktop must reconcile the registered privileged helper at launch. If it does not, inspect bounded log tails and record the failure rather than rerunning setup or using `tailnet set-provider` to hide it:

```bash
tail -n 200 ~/.openbase/logs/electron-main.log | grep 'netmesh-helper-launch' | tail -n 10
tail -n 200 ~/Library/Logs/OpenbaseNetmesh/companion.log | grep -E 'replace-helper|register:' | tail -n 20
```

After the first successful connection, reboot the disposable VM once. Pass only when Openbase VPN restores the same private identity, the status command returns promptly, the local backend and LiveKit listeners recover, and the renderer leaves any temporary loading state without requiring a refocus, manual Recheck, or another setup run.

## 5. Return to the shared procedure

Complete the shared [Full Acoustic Loop](../../.agents/skills/field-testing/SKILL.md#full-acoustic-loop), [Mandatory Super Agent and Desktop-permission gate](../../.agents/skills/field-testing/SKILL.md#mandatory-super-agent-and-desktop-permission-gate), [Handling Failures](../../.agents/skills/field-testing/SKILL.md#handling-failures-every-failure-three-ways--maybe-four), and [Reporting](../../.agents/skills/field-testing/SKILL.md#reporting) sections. Those sections are intentionally not repeated in this installation track.
