import { existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export const folderAdjectives = ["amber", "brave", "calm", "clear", "happy", "lucky", "quiet", "swift"];
export const folderNouns = ["apple", "bridge", "field", "garden", "harbor", "meadow", "river", "window"];

export type FileTaskWorkspace = {
  root: string;
  path: (...parts: string[]) => string;
};

export function createCleanWorkspace(root: string): FileTaskWorkspace {
  rmSync(root, { recursive: true, force: true });
  mkdirSync(root, { recursive: true });

  return {
    root,
    path: (...parts: string[]) => join(root, ...parts),
  };
}

export function writeTaskInstructions(path: string, lines: string[]): void {
  writeFileSync(path, [...lines, ""].join("\n"), "utf8");
}

export function writeBriefing(path: string, title: string, lines: string[]): void {
  writeFileSync(path, [`# ${title}`, "", ...lines, ""].join("\n"), "utf8");
}

export async function waitForFile(path: string, timeoutMs: number): Promise<void> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    if (existsSync(path)) {
      return;
    }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error(`Timed out waiting for file ${path}`);
}

export async function waitForFileText(
  path: string,
  pattern: string | RegExp,
  timeoutMs: number,
): Promise<string> {
  await waitForFile(path, timeoutMs);

  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const text = readFileSync(path, "utf8");
    if (typeof pattern === "string" ? text.includes(pattern) : pattern.test(text)) {
      return text;
    }
    await new Promise(resolve => setTimeout(resolve, 500));
  }

  throw new Error(`Timed out waiting for ${path} to contain ${String(pattern)}`);
}

export function readFileTrimmed(path: string): string {
  return readFileSync(path, "utf8").trim();
}

export function fileMtimeMs(path: string): number {
  return statSync(path).mtimeMs;
}

export function randomFolderName(prefix = "openbase"): string {
  const adjective = folderAdjectives[Math.floor(Math.random() * folderAdjectives.length)];
  const noun = folderNouns[Math.floor(Math.random() * folderNouns.length)];
  const number = Math.floor(100 + Math.random() * 900);
  return `${prefix}-${adjective}-${noun}-${number}`;
}
