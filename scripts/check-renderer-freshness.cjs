// Exit zero only when dist was built from every current dependency revision.
const fs = require("node:fs");
const path = require("node:path");
const workspace = path.resolve(process.argv[2]);
const component = process.argv[3];
if (!["desktop", "console"].includes(component)) process.exit(1);
const { capture, sameInputs } = require(path.join(workspace, "coder-react/scripts/runtime-provenance.cjs"));
try {
  const built = JSON.parse(fs.readFileSync(path.join(workspace, component, "dist/provenance.json"), "utf8"));
  process.exit(sameInputs(built, capture(workspace, component)) ? 0 : 1);
} catch {
  process.exit(1);
}
