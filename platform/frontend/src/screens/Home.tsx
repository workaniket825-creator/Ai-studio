import { useEffect, useState } from "react";
import { Card, Button, Tag, Callout } from "@blueprintjs/core";
import { api } from "../api/client";

function Kpi({ label, value, sub, tone }: { label: string; value: any; sub?: string; tone?: string }) {
  return (
    <Card style={{ padding: 18, flex: 1 }}>
      <div className="muted" style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: ".08em" }}>{label}</div>
      <div className="metric" style={{ fontSize: 30, fontWeight: 800, color: tone || "var(--text)", marginTop: 6 }}>{value}</div>
      {sub && <div className="muted" style={{ fontSize: 12 }}>{sub}</div>}
    </Card>
  );
}

export function Home({ go }: { go: (s: any) => void }) {
  const [d, setD] = useState<any>({ agents: 0, workflows: 0, bundles: 0 });
  const [ov, setOv] = useState<any>(null);
  const [hasModel, setHasModel] = useState<boolean | null>(null);

  useEffect(() => {
    Promise.all([api.listAgents(), api.listWorkflows(), api.listBundles(), api.metricsOverview()])
      .then(([a, w, b, m]) => { setD({ agents: a.length, workflows: w.length, bundles: b.length }); setOv(m); })
      .catch(() => {});
    api.listEndpoints().then((e: any[]) => setHasModel(e.length > 0)).catch(() => setHasModel(null));
  }, []);

  return (
    <div>
      {hasModel === false && (
        <Callout intent="warning" icon="warning-sign" title="Finish setup: add a model endpoint" style={{ marginBottom: 16 }}>
          No model endpoint is configured yet. Agents, Chat, and ontology extraction need a model to run.
          Add your Azure OpenAI / Mistral / Gemini key to get started.
          <div style={{ marginTop: 8 }}>
            <Button small intent="primary" icon="ip-address" text="Add a model endpoint" onClick={() => go("endpoints")} />
            <Button small minimal icon="help" text="Setup guide" style={{ marginLeft: 6 }} onClick={() => go("help")} />
          </div>
        </Callout>
      )}

      <div style={{ padding: "18px 0 26px" }}>
        <div style={{ fontSize: 28, fontWeight: 800, letterSpacing: "-.02em" }}>
          Build, run &amp; observe <span style={{ color: "var(--accent)" }}>agentic workflows</span>
        </div>
        <div className="muted" style={{ marginTop: 6, fontSize: 14 }}>
          TCS AI Studio — build, run and observe enterprise agentic workflows on a single canvas.
        </div>
        <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
          <Button large intent="primary" icon="flows" text="Open Workflow Studio" onClick={() => go("studio")} />
          <Button large icon="layout-grid" text="Browse Agent Garden" onClick={() => go("garden")} />
          <Button large icon="chat" text="Open Chat" onClick={() => go("chat")} />
          <Button large minimal icon="grid-view" text="Browse Templates" onClick={() => go("templates")} />
          <Button large minimal icon="lightbulb" text="Run Platform Insights" onClick={() => go("insights")} />
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 14 }}>
        <Kpi label="Agents" value={d.agents} sub="in the Garden" />
        <Kpi label="Workflows" value={d.workflows} sub="designed" />
        <Kpi label="Runs" value={ov?.total_runs ?? 0} sub={`${ov?.success_rate ?? 0}% success`}
          tone="var(--accent)" />
        <Kpi label="Tokens" value={ov?.total_tokens ?? 0} sub={`${ov?.total_input_tokens ?? 0} in · ${ov?.total_output_tokens ?? 0} out`} />
        <Kpi label="Bundles" value={d.bundles} sub="role packs" />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 12 }}>
        {[
          { t: "Create an agent", d: "Role, prompts, model, tools & collaboration.", i: "plus", s: "garden" },
          { t: "Map an API", d: "Upload OpenAPI → grant operations to agents.", i: "wrench", s: "tools" },
          { t: "Connectors", d: "Enable out-of-box connectivity for agents.", i: "data-connection", s: "connectors" },
          { t: "Design a workflow", d: "Describe a goal; reuse-first graph.", i: "predictive-analysis", s: "studio" },
          { t: "Monitor runs", d: "Traces, tokens, latency, feedback.", i: "timeline-line-chart", s: "monitor" },
          { t: "Schedule runs", d: "Unattended interval triggers.", i: "time", s: "schedules" },
          { t: "Governance", d: "Roles, budget, guardrails, audit.", i: "shield", s: "governance" },
        ].map((c) => (
          <Card key={c.t} interactive onClick={() => go(c.s)} style={{ padding: 16 }}>
            <Tag minimal round icon={c.i as any} style={{ marginBottom: 8 }} />
            <div style={{ fontWeight: 600 }}>{c.t}</div>
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>{c.d}</div>
          </Card>
        ))}
      </div>
    </div>
  );
}
