"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

type AgentId = "surveyor" | "hydrologist";

type GraphNode = {
  id: string;
  label: string;
  group: string;
};

type GraphLink = {
  source: string;
  target: string;
};

type GraphData = {
  nodes: GraphNode[];
  links: GraphLink[];
};

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
});

const AGENTS: { id: AgentId; label: string; description: string }[] = [
  {
    id: "surveyor",
    label: "Surveyor – Module graph",
    description: "Modules and their import relationships.",
  },
  {
    id: "hydrologist",
    label: "Hydrologist – Lineage graph",
    description: "Datasets, transformations, and lineage.",
  },
];

export default function Home() {
  const [agent, setAgent] = useState<AgentId>("surveyor");
  const [graph, setGraph] = useState<GraphData>({ nodes: [], links: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/graph/${agent}`);
        if (!res.ok) {
          throw new Error(`Failed to load graph (${res.status})`);
        }
        const data: GraphData = await res.json();
        if (!cancelled) {
          setGraph(data);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Unknown error");
          setGraph({ nodes: [], links: [] });
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    load();
    return () => {
      cancelled = true;
    };
  }, [agent]);

  const fgData = useMemo(
    () => ({
      nodes: graph.nodes.map((n) => ({ ...n })),
      links: graph.links.map((l) => ({ ...l })),
    }),
    [graph],
  );

  const currentAgentMeta = AGENTS.find((a) => a.id === agent)!;

  return (
    <div className="flex min-h-screen flex-col bg-zinc-50 text-zinc-900">
      <header className="border-b border-zinc-200 bg-white px-6 py-4">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">
              Cartographer Graph Viewer
            </h1>
            <p className="text-sm text-zinc-500">
              Explore Surveyor (module) and Hydrologist (lineage) graphs.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <label className="text-sm font-medium text-zinc-700">
              Agent
            </label>
            <select
              value={agent}
              onChange={(e) => setAgent(e.target.value as AgentId)}
              className="rounded-md border border-zinc-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-zinc-500 focus:outline-none"
            >
              {AGENTS.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </header>

      <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-4 px-6 py-4">
        <section className="flex flex-col gap-2">
          <h2 className="text-base font-semibold text-zinc-800">
            {currentAgentMeta.label}
          </h2>
          <p className="text-sm text-zinc-600">
            {currentAgentMeta.description}
          </p>
          {loading && (
            <p className="text-xs text-zinc-500">Loading graph…</p>
          )}
          {error && (
            <p className="text-xs text-red-600">
              Failed to load graph: {error}
            </p>
          )}
          {!loading && !error && (
            <p className="text-xs text-zinc-500">
              {graph.nodes.length.toLocaleString()} nodes,{" "}
              {graph.links.length.toLocaleString()} edges.
            </p>
          )}
        </section>

        <section className="flex-1 overflow-hidden rounded-lg border border-zinc-200 bg-white shadow-sm">
          <ForceGraph2D
            graphData={fgData}
            width={undefined}
            height={undefined}
            backgroundColor="#ffffff"
            nodeId="id"
            nodeLabel={(node: any) => node.label}
            nodeAutoColorBy="group"
            linkColor={() => "rgba(0,0,0,0.25)"}
          />
        </section>
      </main>
    </div>
  );
}

