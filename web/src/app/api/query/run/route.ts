import { NextResponse } from "next/server";
import { extractJsonFromOutput, normalizeOutDir, runCartographerCli } from "@/lib/cartography";

export const runtime = "nodejs";

type QueryType = "trace-lineage" | "blast-radius" | "explain-module" | "ask";

type QueryRequest = {
  type?: QueryType;
  out?: string;
  dataset?: string;
  direction?: "upstream" | "downstream";
  node?: string;
  path?: string;
  question?: string;
};

function buildArgs(payload: QueryRequest): string[] {
  const out = normalizeOutDir(payload.out);
  const type = payload.type;

  if (type === "trace-lineage") {
    return [
      "query",
      "trace-lineage",
      "--dataset",
      (payload.dataset ?? "").trim(),
      "--direction",
      payload.direction === "downstream" ? "downstream" : "upstream",
      "--out",
      out,
    ];
  }

  if (type === "blast-radius") {
    return [
      "query",
      "blast-radius",
      "--node",
      (payload.node ?? "").trim(),
      "--out",
      out,
    ];
  }

  if (type === "explain-module") {
    return [
      "query",
      "explain-module",
      "--path",
      (payload.path ?? "").trim(),
      "--out",
      out,
    ];
  }

  if (type === "ask") {
    return [
      "query",
      "ask",
      "--question",
      (payload.question ?? "").trim(),
      "--out",
      out,
    ];
  }

  return [];
}

function validatePayload(payload: QueryRequest): string | null {
  if (!payload.type) {
    return "Missing query type.";
  }
  if (payload.type === "trace-lineage" && !(payload.dataset ?? "").trim()) {
    return "Dataset is required for trace-lineage.";
  }
  if (payload.type === "blast-radius" && !(payload.node ?? "").trim()) {
    return "Node is required for blast-radius.";
  }
  if (payload.type === "explain-module" && !(payload.path ?? "").trim()) {
    return "Path is required for explain-module.";
  }
  if (payload.type === "ask" && !(payload.question ?? "").trim()) {
    return "Question is required for ask.";
  }
  return null;
}

export async function POST(request: Request) {
  let payload: QueryRequest;
  try {
    payload = (await request.json()) as QueryRequest;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const validationError = validatePayload(payload);
  if (validationError) {
    return NextResponse.json({ error: validationError }, { status: 400 });
  }

  const args = buildArgs(payload);
  if (args.length === 0) {
    return NextResponse.json({ error: "Unsupported query type." }, { status: 400 });
  }

  const result = await runCartographerCli(args);
  const parsedJson = extractJsonFromOutput(result.stdout);

  if (result.exitCode !== 0) {
    return NextResponse.json(
      {
        ok: false,
        error: "Query command failed.",
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
    data: parsedJson,
    stdout: result.stdout,
    stderr: result.stderr,
  });
}

