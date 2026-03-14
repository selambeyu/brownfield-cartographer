import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";

export type CliResult = {
  exitCode: number | null;
  stdout: string;
  stderr: string;
};

export function getProjectRoot(): string {
  // Next.js app lives in web/, project root is one level up.
  return path.resolve(process.cwd(), "..");
}

export function normalizeOutDir(out?: string): string {
  const projectRoot = getProjectRoot();
  const raw = out?.trim() ? out.trim() : ".cartography";
  const resolved = path.isAbsolute(raw)
    ? path.resolve(raw)
    : path.resolve(projectRoot, raw);

  // Keep artifact writes inside project root for safety.
  if (!resolved.startsWith(projectRoot)) {
    return path.resolve(projectRoot, ".cartography");
  }
  return resolved;
}

export async function runCartographerCli(args: string[]): Promise<CliResult> {
  const projectRoot = getProjectRoot();
  return new Promise((resolve) => {
    const child = spawn("uv", ["run", "python", "-m", "src.cli", ...args], {
      cwd: projectRoot,
      stdio: ["ignore", "pipe", "pipe"],
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk) => {
      stdout += String(chunk);
    });
    child.stderr.on("data", (chunk) => {
      stderr += String(chunk);
    });
    child.on("close", (exitCode) => {
      resolve({ exitCode, stdout, stderr });
    });
    child.on("error", (err) => {
      resolve({ exitCode: 1, stdout, stderr: `${stderr}\n${String(err)}` });
    });
  });
}

export function parseKeyValueLines(stdout: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of stdout.split(/\r?\n/)) {
    const idx = line.indexOf("=");
    if (idx <= 0) {
      continue;
    }
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim();
    if (key) {
      out[key] = value;
    }
  }
  return out;
}

export function extractJsonFromOutput(stdout: string): unknown | null {
  const first = stdout.indexOf("{");
  const last = stdout.lastIndexOf("}");
  if (first < 0 || last <= first) {
    return null;
  }
  const slice = stdout.slice(first, last + 1);
  try {
    return JSON.parse(slice);
  } catch {
    return null;
  }
}

export async function readJsonIfExists(filePath: string): Promise<unknown | null> {
  try {
    const raw = await fs.readFile(filePath, "utf8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

