"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";

type AgentId = "surveyor" | "hydrologist";
type QueryType = "trace-lineage" | "blast-radius" | "explain-module" | "ask";

type GraphNode = {
  id: string;
  label: string;
  group: string;
  isDeadCode?: boolean;
};

type GraphLink = {
  source: string;
  target: string;
};

type GraphData = {
  nodes: GraphNode[];
  links: GraphLink[];
};

type AnalyzeResponse = {
  ok: boolean;
  runId: string | null;
  outDir: string | null;
  tracePath: string | null;
  stdout: string;
  stderr: string;
  error?: string;
};

type QueryResponse = {
  ok: boolean;
  data: unknown;
  stdout: string;
  stderr: string;
  error?: string;
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
  const [repo, setRepo] = useState(".");
  const [out, setOut] = useState(".cartography");
  const [incremental, setIncremental] = useState(true);
  const [llmEnabled, setLlmEnabled] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeResult, setAnalyzeResult] = useState<AnalyzeResponse | null>(null);

  const [queryType, setQueryType] = useState<QueryType>("ask");
  const [dataset, setDataset] = useState("");
  const [direction, setDirection] = useState<"upstream" | "downstream">("upstream");
  const [node, setNode] = useState("");
  const [modulePath, setModulePath] = useState("src/agents/hydrologist.py");
  const [question, setQuestion] = useState("What produces dataset customers?");
  const [querying, setQuerying] = useState(false);
  const [queryResult, setQueryResult] = useState<QueryResponse | null>(null);

  const [agent, setAgent] = useState<AgentId>("surveyor");
  const [graph, setGraph] = useState<GraphData>({ nodes: [], links: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runAnalysis = async () => {
    setAnalyzing(true);
    setAnalyzeResult(null);
    try {
      const res = await fetch("/api/analyze/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repo,
          out,
          incremental,
          llmEnabled,
        }),
      });
      const data = (await res.json()) as AnalyzeResponse;
      setAnalyzeResult(data);
    } catch (err) {
      setAnalyzeResult({
        ok: false,
        runId: null,
        outDir: null,
        tracePath: null,
        stdout: "",
        stderr: "",
        error: err instanceof Error ? err.message : "Failed to run analysis",
      });
    } finally {
      setAnalyzing(false);
    }
  };

  const runQuery = async () => {
    setQuerying(true);
    setQueryResult(null);
    const payload: Record<string, string | boolean> = { type: queryType, out };
    if (queryType === "trace-lineage") {
      payload.dataset = dataset;
      payload.direction = direction;
    } else if (queryType === "blast-radius") {
      payload.node = node;
    } else if (queryType === "explain-module") {
      payload.path = modulePath;
    } else {
      payload.question = question;
    }

    try {
      const res = await fetch("/api/query/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = (await res.json()) as QueryResponse;
      setQueryResult(data);
    } catch (err) {
      setQueryResult({
        ok: false,
        data: null,
        stdout: "",
        stderr: "",
        error: err instanceof Error ? err.message : "Failed to run query",
      });
    } finally {
      setQuerying(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({ out });
        const res = await fetch(`/api/graph/${agent}?${params.toString()}`);
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
  }, [agent, out]);

  const fgData = useMemo(
    () => ({
      nodes: graph.nodes.map((n) => ({ ...n })),
      links: graph.links.map((l) => ({ ...l })),
    }),
    [graph],
  );

  const currentAgentMeta = AGENTS.find((a) => a.id === agent)!;
  const getNodeColor = (node: Record<string, unknown>): string | undefined => {
    if (node.isDeadCode === true) {
      return "#dc2626";
    }
    return undefined;
  };

  return (
    <div className="flex min-h-screen flex-col bg-zinc-50 text-zinc-900">
      <header className="border-b border-zinc-200 bg-white px-6 py-4">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">
              Cartographer Web Console
            </h1>
            <p className="text-sm text-zinc-500">
              Analyze repos, run queries, and explore graphs without CLI.
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
        <section className="rounded-lg border border-zinc-200 bg-white p-4 shadow-sm">
          <h2 className="text-base font-semibold text-zinc-800">1) Run Analysis</h2>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <label className="flex flex-col gap-1 text-sm">
              Repo path or URL
              <input
                value={repo}
                onChange={(e) => setRepo(e.target.value)}
                className="rounded-md border border-zinc-300 px-3 py-2"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              Output directory
              <input
                value={out}
                onChange={(e) => setOut(e.target.value)}
                className="rounded-md border border-zinc-300 px-3 py-2"
              />
            </label>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={incremental}
                onChange={(e) => setIncremental(e.target.checked)}
              />
              Incremental
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={llmEnabled}
                onChange={(e) => setLlmEnabled(e.target.checked)}
              />
              Enable LLM
            </label>
            <button
              type="button"
              onClick={runAnalysis}
              disabled={analyzing}
              className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              {analyzing ? "Running..." : "Run Analyze"}
            </button>
          </div>
          {analyzeResult && (
            <div className="mt-3 rounded-md bg-zinc-50 p-3 text-xs text-zinc-700">
              <p>ok: {String(analyzeResult.ok)}</p>
              {analyzeResult.runId && <p>run_id: {analyzeResult.runId}</p>}
              {analyzeResult.outDir && <p>out_dir: {analyzeResult.outDir}</p>}
              {analyzeResult.tracePath && <p>trace: {analyzeResult.tracePath}</p>}
              {analyzeResult.error && <p className="text-red-600">error: {analyzeResult.error}</p>}
            </div>
          )}
        </section>

        <section className="rounded-lg border border-zinc-200 bg-white p-4 shadow-sm">
          <h2 className="text-base font-semibold text-zinc-800">2) Run Query</h2>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <label className="flex flex-col gap-1 text-sm">
              Query type
              <select
                value={queryType}
                onChange={(e) => setQueryType(e.target.value as QueryType)}
                className="rounded-md border border-zinc-300 px-3 py-2"
              >
                <option value="ask">ask (natural language)</option>
                <option value="trace-lineage">trace-lineage</option>
                <option value="blast-radius">blast-radius</option>
                <option value="explain-module">explain-module</option>
              </select>
            </label>
            {queryType === "trace-lineage" && (
              <label className="flex flex-col gap-1 text-sm">
                Dataset
                <input
                  value={dataset}
                  onChange={(e) => setDataset(e.target.value)}
                  className="rounded-md border border-zinc-300 px-3 py-2"
                  placeholder="customers"
                />
              </label>
            )}
            {queryType === "trace-lineage" && (
              <label className="flex flex-col gap-1 text-sm">
                Direction
                <select
                  value={direction}
                  onChange={(e) => setDirection(e.target.value as "upstream" | "downstream")}
                  className="rounded-md border border-zinc-300 px-3 py-2"
                >
                  <option value="upstream">upstream</option>
                  <option value="downstream">downstream</option>
                </select>
              </label>
            )}
            {queryType === "blast-radius" && (
              <label className="flex flex-col gap-1 text-sm">
                Node
                <input
                  value={node}
                  onChange={(e) => setNode(e.target.value)}
                  className="rounded-md border border-zinc-300 px-3 py-2"
                  placeholder="dataset:customers"
                />
              </label>
            )}
            {queryType === "explain-module" && (
              <label className="flex flex-col gap-1 text-sm">
                Module path
                <input
                  value={modulePath}
                  onChange={(e) => setModulePath(e.target.value)}
                  className="rounded-md border border-zinc-300 px-3 py-2"
                  placeholder="src/agents/hydrologist.py"
                />
              </label>
            )}
            {queryType === "ask" && (
              <label className="md:col-span-2 flex flex-col gap-1 text-sm">
                Question
                <input
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  className="rounded-md border border-zinc-300 px-3 py-2"
                />
              </label>
            )}
          </div>
          <div className="mt-3">
            <button
              type="button"
              onClick={runQuery}
              disabled={querying}
              className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              {querying ? "Running..." : "Run Query"}
            </button>
          </div>
          {queryResult && (
            <pre className="mt-3 max-h-64 overflow-auto rounded-md bg-zinc-950 p-3 text-xs text-zinc-100">
              {JSON.stringify(queryResult.data ?? queryResult, null, 2)}
            </pre>
          )}
        </section>

        <section className="flex flex-col gap-2">
          <h2 className="text-base font-semibold text-zinc-800">
            3) Graph Viewer — {currentAgentMeta.label}
          </h2>
          <p className="text-sm text-zinc-600">
            {currentAgentMeta.description} (from `{out}`)
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
            nodeLabel={(node) => String((node as Record<string, unknown>).label ?? "")}
            nodeColor={(node) => getNodeColor(node as Record<string, unknown>)}
            nodeAutoColorBy="group"
            linkColor={() => "rgba(0,0,0,0.25)"}
          />
        </section>
      </main>
    </div>
  );
}

