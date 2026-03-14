import { NextResponse } from "next/server";
import path from "node:path";
import fs from "node:fs/promises";

type AgentId = "surveyor" | "hydrologist";

type ApiNode = {
  id: string;
  label: string;
  group: string;
};

type ApiLink = {
  source: string;
  target: string;
};

type GraphResponse = {
  nodes: ApiNode[];
  links: ApiLink[];
};

function getProjectRoot(): string {
  // Next.js app is in web/, project root is one level up.
  return path.resolve(process.cwd(), "..");
}

async function loadJson(agent: AgentId): Promise<any> {
  const projectRoot = getProjectRoot();
  let jsonPath: string;

  if (agent === "surveyor") {
    jsonPath = path.join(projectRoot, ".cartography", "module_graph.json");
  } else if (agent === "hydrologist") {
    jsonPath = path.join(projectRoot, ".cartography", "lineage_graph.json");
  } else {
    throw new Error(`Unsupported agent: ${agent}`);
  }

  const raw = await fs.readFile(jsonPath, "utf8");
  return JSON.parse(raw);
}

function normalizeSurveyor(data: any): GraphResponse {
  const nodes: ApiNode[] = (data.nodes ?? []).map((n: any) => {
    const id = String(n.id);
    const fullPath: string | undefined = n.path;
    const base = fullPath ? path.basename(fullPath) : id;
    return {
      id,
      label: base,
      group: n.language ?? n.type ?? "module",
    };
  });

  const rawEdges = data.links ?? data.edges ?? [];
  const links: ApiLink[] = rawEdges
    .map((e: any) => ({
      source: String(e.source),
      target: String(e.target),
    }))
    .filter((e: ApiLink) => e.source && e.target);

  return { nodes, links };
}

function normalizeHydrologist(data: any): GraphResponse {
  const nodes: ApiNode[] = (data.nodes ?? []).map((n: any) => {
    const id = String(n.id);
    const type: string = n.type ?? "unknown";
    let label: string = n.name ?? "";

    if (!label && typeof n.source_file === "string") {
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

  const links: ApiLink[] = (data.edges ?? [])
    .map((e: any) => ({
      source: String(e.source),
      target: String(e.target),
    }))
    .filter((e: ApiLink) => e.source && e.target);

  return { nodes, links };
}

export async function GET(
  _request: Request,
  context: { params: Promise<{ agent: AgentId }> },
) {
  const { agent } = await context.params;

  if (agent !== "surveyor" && agent !== "hydrologist") {
    return NextResponse.json(
      { error: "Unknown agent. Use 'surveyor' or 'hydrologist'." },
      { status: 400 },
    );
  }

  try {
    const raw = await loadJson(agent);
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

