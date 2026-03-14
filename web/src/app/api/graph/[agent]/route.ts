import { NextResponse } from "next/server";
import path from "node:path";
import fs from "node:fs/promises";
import { normalizeOutDir } from "@/lib/cartography";

type AgentId = "surveyor" | "hydrologist";

type ApiNode = {
  id: string;
  label: string;
  group: string;
  isDeadCode?: boolean;
};

type ApiLink = {
  source: string;
  target: string;
};

type GraphResponse = {
  nodes: ApiNode[];
  links: ApiLink[];
};

type JsonObject = Record<string, unknown>;

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asObject(value: unknown): JsonObject {
  return value !== null && typeof value === "object" ? (value as JsonObject) : {};
}

async function loadJson(agent: AgentId, outDir: string): Promise<JsonObject> {
  let jsonPath: string;

  if (agent === "surveyor") {
    jsonPath = path.join(outDir, "module_graph.json");
  } else if (agent === "hydrologist") {
    jsonPath = path.join(outDir, "lineage_graph.json");
  } else {
    throw new Error(`Unsupported agent: ${agent}`);
  }

  const raw = await fs.readFile(jsonPath, "utf8");
  return asObject(JSON.parse(raw));
}

function normalizeSurveyor(data: JsonObject): GraphResponse {
  const nodes: ApiNode[] = asArray(data.nodes).map((nodeRaw) => {
    const n = asObject(nodeRaw);
    const id = String(n.id ?? "");
    const fullPath = typeof n.path === "string" ? n.path : undefined;
    const base = fullPath ? path.basename(fullPath) : id;
    const deadCodeCandidates = asArray(n.dead_code_candidates);
    const isDeadCode =
      n.is_dead_code_candidate === true || deadCodeCandidates.length > 0;
    return {
      id,
      label: base,
      group:
        typeof n.language === "string"
          ? n.language
          : typeof n.type === "string"
            ? n.type
            : "module",
      isDeadCode,
    };
  });

  const rawEdges = asArray(data.links).length > 0 ? asArray(data.links) : asArray(data.edges);
  const links: ApiLink[] = rawEdges
    .map((edgeRaw) => {
      const e = asObject(edgeRaw);
      return {
        source: String(e.source ?? ""),
        target: String(e.target ?? ""),
      };
    })
    .filter((e: ApiLink) => e.source && e.target);

  return { nodes, links };
}

function normalizeHydrologist(data: JsonObject): GraphResponse {
  const nodes: ApiNode[] = asArray(data.nodes).map((nodeRaw) => {
    const n = asObject(nodeRaw);
    const id = String(n.id ?? "");
    const type = typeof n.type === "string" ? n.type : "unknown";
    let label = typeof n.name === "string" ? n.name : "";

    if (!label && typeof n.source_file === "string" && n.source_file) {
      label = path.basename(n.source_file);
    }
    if (!label) {
      label = id;
    }

    return {
      id,
      label,
      group: type,
    };
  });

  const links: ApiLink[] = asArray(data.edges)
    .map((edgeRaw) => {
      const e = asObject(edgeRaw);
      return {
        source: String(e.source ?? ""),
        target: String(e.target ?? ""),
      };
    })
    .filter((e: ApiLink) => e.source && e.target);

  return { nodes, links };
}

export async function GET(
  request: Request,
  context: { params: Promise<{ agent: string }> },
) {
  const { agent } = await context.params;
  const out = normalizeOutDir(new URL(request.url).searchParams.get("out") ?? undefined);

  if (agent !== "surveyor" && agent !== "hydrologist") {
    return NextResponse.json(
      { error: "Unknown agent. Use 'surveyor' or 'hydrologist'." },
      { status: 400 },
    );
  }

  try {
    const raw = await loadJson(agent as AgentId, out);
    const normalized =
      agent === "surveyor" ? normalizeSurveyor(raw) : normalizeHydrologist(raw);

    return NextResponse.json<GraphResponse>(normalized);
  } catch (error: unknown) {
    console.error(error);
    return NextResponse.json(
      { error: "Failed to load graph JSON for agent." },
      { status: 500 },
    );
  }
}

