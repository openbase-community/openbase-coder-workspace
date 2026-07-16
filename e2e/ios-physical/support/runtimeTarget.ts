import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";

type RuntimeExpectation = "any" | "standalone" | "electron-bundled" | "workspace";

type InstallationConfig = {
  workspace_path?: string;
  package_path?: string;
  standalone?: boolean;
};

type PackageMetadata = {
  version?: string;
  target?: string;
};

export type RuntimeTarget = {
  ok: boolean;
  expectation: RuntimeExpectation;
  mode: "standalone" | "workspace" | "unknown";
  electronBundled: boolean;
  detail: string;
};

const defaultDesktopAppPath = "/Applications/Openbase.app";

export function detectRuntimeTarget(): RuntimeTarget {
  const expectation = readRuntimeExpectation();
  const installation = readInstallationConfig();
  if (!installation) {
    return runtimeResult(expectation, "unknown", false, "installation.json is missing or unreadable");
  }

  if (installation.standalone) {
    const activePackage = readPackageMetadata(installation.package_path);
    const desktopPackage = readDesktopPackageMetadata();
    const electronBundled = packagesMatch(activePackage, desktopPackage);
    const version = activePackage?.version ? ` ${activePackage.version}` : "";
    const detail = electronBundled
      ? `standalone/Electron-bundled${version}; active package matches installed desktop bundle`
      : `standalone${version}; active package does not match installed desktop bundle`;
    return runtimeResult(expectation, "standalone", electronBundled, detail);
  }

  if (installation.workspace_path) {
    return runtimeResult(expectation, "workspace", false, "workspace/dev runtime mode");
  }

  return runtimeResult(expectation, "unknown", false, "runtime mode is not configured");
}

export function assertExpectedRuntimeTarget(): void {
  const target = detectRuntimeTarget();
  if (!target.ok) {
    throw new Error(`Openbase runtime target check failed: ${target.detail}`);
  }
}

function runtimeResult(
  expectation: RuntimeExpectation,
  mode: RuntimeTarget["mode"],
  electronBundled: boolean,
  detail: string,
): RuntimeTarget {
  const ok =
    expectation === "any"
    || (expectation === "standalone" && mode === "standalone")
    || (expectation === "workspace" && mode === "workspace")
    || (expectation === "electron-bundled" && mode === "standalone" && electronBundled);

  return {
    ok,
    expectation,
    mode,
    electronBundled,
    detail: expectation === "any" ? detail : `${detail}; expected ${expectation}`,
  };
}

function readRuntimeExpectation(): RuntimeExpectation {
  const raw = process.env.OPENBASE_E2E_EXPECT_RUNTIME?.trim() || "any";
  if (raw === "any" || raw === "standalone" || raw === "electron-bundled" || raw === "workspace") {
    return raw;
  }
  throw new Error("OPENBASE_E2E_EXPECT_RUNTIME must be one of: any, standalone, electron-bundled, workspace.");
}

function readInstallationConfig(): InstallationConfig | undefined {
  const home = process.env.HOME;
  if (!home) {
    return undefined;
  }

  return readJson(resolve(home, ".openbase/installation.json"));
}

function readDesktopPackageMetadata(): PackageMetadata | undefined {
  const appPath = process.env.OPENBASE_E2E_DESKTOP_APP_PATH || defaultDesktopAppPath;
  return readPackageMetadata(join(appPath, "Contents/Resources/OpenbaseCoderCLI"));
}

function readPackageMetadata(packagePath: string | undefined): PackageMetadata | undefined {
  if (!packagePath) {
    return undefined;
  }
  return readJson(join(packagePath, "openbase-coder-package.json"));
}

function readJson<T>(path: string): T | undefined {
  if (!existsSync(path)) {
    return undefined;
  }

  try {
    return JSON.parse(readFileSync(path, "utf8")) as T;
  } catch {
    return undefined;
  }
}

function packagesMatch(left: PackageMetadata | undefined, right: PackageMetadata | undefined): boolean {
  if (!left?.version || !left.target || !right?.version || !right.target) {
    return false;
  }
  return left.version === right.version && left.target === right.target;
}
