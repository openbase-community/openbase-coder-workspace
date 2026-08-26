import { spawn } from "node:child_process";
import { accessSync, constants } from "node:fs";
import { resolve } from "node:path";
import type { DeviceEnv } from "../deviceEnv.js";
import { workspaceRoot } from "../deviceEnv.js";

export type TtsResult = {
  command: string;
  args: string[];
  text: string;
};

export async function sayFromOpenbaseApp(env: DeviceEnv, text: string): Promise<TtsResult> {
  const trimmed = text.trim();
  if (!trimmed) {
    throw new Error("TTS text must not be empty.");
  }

  const command = env.ttsCommand ?? defaultOpenbaseCoderCommand();
  const args = ["user", "say", "dispatcher", trimmed];
  await run(command, args, process.env);
  return { command, args, text: trimmed };
}

export async function sayFromMacTts(text: string): Promise<TtsResult> {
  const trimmed = text.trim();
  if (!trimmed) {
    throw new Error("TTS text must not be empty.");
  }
  await run("tts", [trimmed], process.env);
  return { command: "tts", args: [trimmed], text: trimmed };
}

function defaultOpenbaseCoderCommand(): string {
  const venvCommand = resolve(workspaceRoot, ".venv/bin/openbase-coder");
  try {
    accessSync(venvCommand, constants.X_OK);
    return venvCommand;
  } catch {
    return "openbase-coder";
  }
}

function run(command: string, args: string[], env: NodeJS.ProcessEnv): Promise<void> {
  return new Promise((resolveRun, reject) => {
    const child = spawn(command, args, {
      cwd: workspaceRoot,
      env,
      stdio: "inherit",
    });

    child.once("error", reject);
    child.once("exit", code => {
      if (code === 0) {
        resolveRun();
      } else {
        reject(new Error(`${command} ${args.join(" ")} exited with code ${code ?? "unknown"}.`));
      }
    });
  });
}
