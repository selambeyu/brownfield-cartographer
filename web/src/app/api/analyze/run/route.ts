import { NextResponse } from "next/server";
import { normalizeOutDir, parseKeyValueLines, runCartographerCli } from "@/lib/cartography";

export const runtime = "nodejs";

type AnalyzeRequest = {
  repo?: string;
  out?: string;
  incremental?: boolean;
  llmEnabled?: boolean;
};

export async function POST(request: Request) {
  let payload: AnalyzeRequest;
  try {
    payload = (await request.json()) as AnalyzeRequest;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const repo = (payload.repo ?? ".").trim() || ".";
  const out = normalizeOutDir(payload.out);
  const incremental = Boolean(payload.incremental);
  const llmEnabled = Boolean(payload.llmEnabled);

  const args = [
    "analyze",
    "run",
    "--repo",
    repo,
    "--out",
    out,
    incremental ? "--incremental" : "--no-incremental",
    llmEnabled ? "--llm" : "--no-llm",
  ];

  const result = await runCartographerCli(args);
  const parsed = parseKeyValueLines(result.stdout);

  if (result.exitCode !== 0) {
    return NextResponse.json(
      {
        ok: false,
        error: "Analysis command failed.",
        exitCode: result.exitCode,
        stdout: result.stdout,
        stderr: result.stderr,
      },
      { status: 500 },
    );
  }

  return NextResponse.json({
    ok: true,
    exitCode: result.exitCode,
    runId: parsed.run_id ?? null,
    outDir: parsed.out_dir ?? out,
    tracePath: parsed.trace ?? null,
    stdout: result.stdout,
    stderr: result.stderr,
  });
}

