// Host-side semantic driver for a guest app or page exposed over a forwarded
// endpoint (see ../guest-automate.sh). Runs on the HOST — the guest needs no
// Node, no Playwright, nothing installed. Two transports:
//
//   --cdp URL      Playwright over CDP: the guest Electron app launched by
//                  `guest-automate.sh app-cdp` (or any Chromium with a
//                  forwarded --remote-debugging-port).
//   --wd URL       Raw W3C WebDriver over HTTP: the guest Safari behind
//                  `guest-automate.sh safari-tunnel`. No extra deps — plain
//                  fetch against the JSON wire protocol.
//
// Commands (read stdin only where noted; never puts secrets in argv):
//   snapshot                          list interactive elements (role, text)
//   click TEXT_OR_SELECTOR            click a button/link by visible text
//                                     (CDP) or CSS selector (WebDriver)
//   fill SELECTOR                     set a field's value from STDIN,
//                                     byte-exact, firing real input events
//   goto URL                          navigate (WebDriver only)
//   text [SELECTOR]                   dump page (or element) text
//   shot PATH.png                     screenshot to a host path
//
// Examples:
//   node host-drive.mjs --cdp http://127.0.0.1:9222 snapshot
//   printf '%s' "$EMAIL" | node host-drive.mjs --wd http://127.0.0.1:4444 fill 'input[type=email]'
//
// Why: Tart-window keystroke forwarding corrupts shifted/option characters
// (openai/tart#1167). All text entry for field tests goes through this file
// or the Appium MCP — never through the Tart window.

import { readFileSync, writeFileSync } from "node:fs";

const args = process.argv.slice(2);
function takeFlag(name) {
  const i = args.indexOf(name);
  if (i === -1) return null;
  const v = args[i + 1];
  args.splice(i, 2);
  return v;
}
const cdpUrl = takeFlag("--cdp");
const wdUrl = takeFlag("--wd");
const [cmd, ...rest] = args;

if ((!cdpUrl && !wdUrl) || !cmd) {
  console.error("usage: host-drive.mjs (--cdp URL | --wd URL) <snapshot|click|fill|goto|text|shot> [args]");
  process.exit(2);
}

const stdinText = () => readFileSync(0, "utf8").replace(/\n$/, "");

// ---------------------------------------------------------------- CDP branch
async function cdpMain() {
  const { chromium } = await import("playwright");
  const browser = await chromium.connectOverCDP(cdpUrl);
  try {
    const pages = browser.contexts().flatMap((c) => c.pages());
    const page = pages[0];
    if (!page) throw new Error("no pages exposed over CDP");
    switch (cmd) {
      case "snapshot": {
        const items = await page.evaluate(() =>
          [...document.querySelectorAll("button, a, input, textarea, select, [role=button]")].map((el) => ({
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute("type") || undefined,
            text: (el.innerText || el.getAttribute("aria-label") || el.getAttribute("placeholder") || "").trim().slice(0, 80),
            id: el.id || undefined,
            disabled: el.disabled || undefined,
          }))
        );
        console.log(JSON.stringify(items, null, 1));
        break;
      }
      case "click": {
        const target = rest.join(" ");
        const byText = page.getByRole("button", { name: new RegExp(target, "i") }).first();
        if (await byText.count()) await byText.click();
        else await page.locator(target).first().click();
        console.log(`clicked: ${target}`);
        break;
      }
      case "fill": {
        const selector = rest.join(" ");
        await page.locator(selector).first().fill(stdinText());
        console.log(`filled: ${selector}`);
        break;
      }
      case "text": {
        const selector = rest.join(" ");
        console.log(selector ? await page.locator(selector).first().innerText() : await page.evaluate(() => document.body.innerText));
        break;
      }
      case "shot": {
        await page.screenshot({ path: rest[0] || "guest-page.png" });
        console.log(`saved: ${rest[0] || "guest-page.png"}`);
        break;
      }
      default:
        throw new Error(`unknown/unsupported CDP command: ${cmd}`);
    }
  } finally {
    // Process exit detaches from CDP without closing the guest app.
  }
  process.exit(0);
}

// ---------------------------------------------------------- WebDriver branch
// Minimal W3C wire client for guest Safari via safaridriver. Session state is
// kept in a sidecar file so successive invocations reuse one session.
const SESSION_FILE = "/tmp/openbase-guest-wd-session.json";

async function wd(method, path, body) {
  const res = await fetch(`${wdUrl}${path}`, {
    method,
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(`WebDriver ${method} ${path} -> ${res.status}: ${JSON.stringify(json).slice(0, 300)}`);
  return json.value;
}

async function wdSession() {
  try {
    const { sessionId } = JSON.parse(readFileSync(SESSION_FILE, "utf8"));
    await wd("GET", `/session/${sessionId}/url`); // liveness probe
    return sessionId;
  } catch {
    const v = await wd("POST", "/session", { capabilities: { alwaysMatch: { browserName: "safari" } } });
    writeFileSync(SESSION_FILE, JSON.stringify({ sessionId: v.sessionId }));
    return v.sessionId;
  }
}

async function wdFind(sessionId, selector) {
  const el = await wd("POST", `/session/${sessionId}/element`, { using: "css selector", value: selector });
  return el[Object.keys(el)[0]];
}

async function wdMain() {
  const s = await wdSession();
  switch (cmd) {
    case "goto":
      await wd("POST", `/session/${s}/url`, { url: rest[0] });
      console.log(`at: ${rest[0]}`);
      break;
    case "snapshot": {
      const items = await wd("POST", `/session/${s}/execute/sync`, {
        script: `return [...document.querySelectorAll("button, a, input, textarea, select, [role=button]")].map(el => ({
          tag: el.tagName.toLowerCase(), type: el.getAttribute("type") || undefined,
          text: (el.innerText || el.getAttribute("aria-label") || el.getAttribute("placeholder") || "").trim().slice(0, 80),
          id: el.id || undefined, name: el.getAttribute("name") || undefined }))`,
        args: [],
      });
      console.log(JSON.stringify(items, null, 1));
      break;
    }
    case "click": {
      const id = await wdFind(s, rest.join(" "));
      await wd("POST", `/session/${s}/element/${id}/click`, {});
      console.log(`clicked: ${rest.join(" ")}`);
      break;
    }
    case "clicktext": {
      // Click the first visible button/link whose text matches (case-insensitive).
      const target = rest.join(" ");
      const clicked = await wd("POST", `/session/${s}/execute/sync`, {
        script: `const want = arguments[0].toLowerCase();
          const els = [...document.querySelectorAll("button, a, [role=button], input[type=submit]")];
          const el = els.find(e => (e.innerText || e.value || "").trim().toLowerCase().includes(want)
            && e.offsetParent !== null && !e.disabled);
          if (!el) return null;
          el.click();
          return (el.innerText || el.value || "").trim();`,
        args: [target],
      });
      if (clicked === null) throw new Error(`no visible control matching text: ${target}`);
      console.log(`clicked: "${clicked}"`);
      break;
    }
    case "fill": {
      const selector = rest.join(" ");
      const value = stdinText();
      const id = await wdFind(s, selector);
      await wd("POST", `/session/${s}/element/${id}/clear`, {});
      // Set via script + real events: Safari sendKeys types through the guest
      // input path; direct assignment + events is byte-exact and layout-proof.
      await wd("POST", `/session/${s}/execute/sync`, {
        script: `const el = arguments[0], v = arguments[1];
          const set = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value")?.set
            || Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
          set.call(el, v);
          el.dispatchEvent(new Event("input", { bubbles: true }));
          el.dispatchEvent(new Event("change", { bubbles: true }));`,
        args: [{ "element-6066-11e4-a52e-4f735466cecf": id }, value],
      });
      console.log(`filled: ${selector} (${value.length} chars)`);
      break;
    }
    case "text": {
      const out = await wd("POST", `/session/${s}/execute/sync`, {
        script: rest.length
          ? `return document.querySelector(${JSON.stringify(rest.join(" "))})?.innerText || ""`
          : "return document.body.innerText",
        args: [],
      });
      console.log(out);
      break;
    }
    case "shot": {
      const b64 = await wd("GET", `/session/${s}/screenshot`);
      writeFileSync(rest[0] || "guest-safari.png", Buffer.from(b64, "base64"));
      console.log(`saved: ${rest[0] || "guest-safari.png"}`);
      break;
    }
    default:
      throw new Error(`unknown WebDriver command: ${cmd}`);
  }
  process.exit(0);
}

(cdpUrl ? cdpMain() : wdMain()).catch((err) => {
  console.error(String(err?.message || err));
  process.exit(1);
});
