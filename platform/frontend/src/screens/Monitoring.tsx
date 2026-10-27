import { useEffect, useState } from "react";
import { Card, Drawer, DrawerSize, Tag, Tree, TreeNodeInfo, Button, HTMLTable, NonIdealState } from "@blueprintjs/core";
import { api } from "../api/client";

function Stat({ label, value, tone }: { label: string; value: any; tone?: string }) {
  return (
    <Card style={{ flex: 1, padding: "12px 14px" }}>
      <div className="muted" style={{ fontSize: 11 }}>{label}</div>
      <div className="metric" style={{ fontSize: 22, fontWeight: 700, color: tone }}>{value}</div>
    </Card>
  );
}

function Bar({ pct, color }: { pct: number; color: string }) {
  return (
    <div style={{ background: "#252a31", borderRadius: 3, height: 8, width: "100%" }}>
      <div style={{ width: `${Math.max(2, pct)}%`, background: color, height: 8, borderRadius: 3 }} />
    </div>
  );
}

function toTree(node: any, path = "0"): TreeNodeInfo {
  const icon = node.kind === "run" ? "layers" : node.kind === "agent" ? "person"
    : node.kind === "tool_call" ? "cog" : node.kind === "reasoning" ? "lightbulb"
    : node.kind === "verification" ? "confirm" : "dot";
  return {
    id: path, icon,
    label: <span>{node.name}{node.out_tokens ? <Tag minimal className="metric" style={{ marginLeft: 6 }}>{node.out_tokens} out</Tag> : null}</span>,
    isExpanded: true,
    childNodes: (node.children || []).map((c: any, i: number) => toTree(c, `${path}.${i}`)),
  };
}

export function Monitoring({ onOpenRun }: { onOpenRun?: (id: string) => void }) {
  const [ov, setOv] = useState<any>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const [trace, setTrace] = useState<any>(null);
  const [obs, setObs] = useState<any>(null);

  const refresh = () => {
    api.metricsOverview().then(setOv);
    api.listRuns().then(setRuns);
    api.observabilityStatus().then(setObs).catch(() => {});
  };
  useEffect(() => { refresh(); const t = setInterval(refresh, 4000); return () => clearInterval(t); }, []);

  const openTrace = async (id: string) => setTrace(await api.getTrace(id));
  const vote = async (id: string, v: "up" | "down") => { await api.feedback(id, v); refresh(); };

  if (!ov) return <div className="muted" style={{ padding: 20 }}>Loading metrics…</div>;
  const maxRuns = Math.max(1, ...ov.by_workflow.map((b: any) => b.runs));

  return (
    <div>
      <div className="section-head">
        <div><h2>Monitoring</h2><span className="muted">Observability across all runs · MLflow-ready</span></div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {obs && <Tag minimal icon={obs.sink === "mlflow" ? "cloud-tick" : "cloud"}
            intent={obs.sink === "mlflow" ? "success" : "none"}
            title={obs.last_error || obs.tracking_uri}>
            tracing: {obs.sink}{obs.sink === "mlflow" ? ` · ${obs.tracking_uri}` : ""}
          </Tag>}
          <Button minimal icon="refresh" onClick={refresh} />
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
        <Stat label="Total runs" value={ov.total_runs} />
        <Stat label="Success rate" value={`${ov.success_rate}%`}
          tone={ov.success_rate >= 90 ? "var(--accent)" : "var(--warning)"} />
        <Stat label="Total tokens" value={ov.total_tokens} />
        <Stat label="In / Out" value={`${ov.total_input_tokens} / ${ov.total_output_tokens}`} />
        <Stat label="p95 latency" value={`${(ov.p95_latency_ms / 1000).toFixed(1)}s`} />
      </div>

      <Card style={{ marginBottom: 16 }}>
        <b>Runs by workflow</b>
        <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 10 }}>
          {ov.by_workflow.length === 0 && <span className="muted">No runs yet.</span>}
          {ov.by_workflow.map((b: any) => (
            <div key={b.name} style={{ display: "grid", gridTemplateColumns: "200px 1fr 150px", gap: 12, alignItems: "center" }}>
              <span style={{ fontSize: 13 }}>{b.name}</span>
              <Bar pct={(b.runs / maxRuns) * 100} color="var(--accent)" />
              <span className="muted metric" style={{ fontSize: 12 }}>
                {b.runs} runs · {b.success_rate}% · {b.tokens} tok
              </span>
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <b>Recent runs</b>
        {runs.length === 0 ? <NonIdealState icon="history" title="No runs yet"
          description="Run a workflow to populate observability." /> : (
          <HTMLTable compact striped style={{ width: "100%", marginTop: 8 }}>
            <thead><tr><th>Workflow</th><th>Status</th><th>In tok</th><th>Out tok</th><th>Latency</th><th>Trace</th><th>Feedback</th></tr></thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id}>
                  <td>{r.workflow_name}</td>
                  <td><Tag minimal intent={r.status === "succeeded" ? "success" : r.status === "awaiting_approval" ? "warning" : "none"}>{r.status}</Tag></td>
                  <td className="metric">{r.input_tokens ?? 0}</td>
                  <td className="metric">{r.output_tokens ?? 0}</td>
                  <td className="metric">{(r.latency_ms / 1000).toFixed(1)}s</td>
                  <td><Button small minimal icon="diagram-tree" onClick={() => openTrace(r.run_id)} /></td>
                  <td>
                    <Button small minimal icon="thumbs-up"
                      intent={r.feedback?.some((f: any) => f.vote === "up") ? "success" : "none"}
                      onClick={() => vote(r.run_id, "up")} />
                    <Button small minimal icon="thumbs-down" onClick={() => vote(r.run_id, "down")} />
                  </td>
                </tr>
              ))}
            </tbody>
          </HTMLTable>
        )}
      </Card>

      <Drawer isOpen={!!trace} onClose={() => setTrace(null)} size={DrawerSize.SMALL}
        title="Execution trace" className="bp5-dark">
        <div style={{ padding: 12 }}>
          {trace && (
            <>
              <div className="muted" style={{ marginBottom: 10, fontSize: 12 }}>
                {trace.name} · {trace.input_tokens} in / {trace.output_tokens} out tokens · {(trace.latency_ms / 1000).toFixed(1)}s
              </div>
              <Tree contents={[toTree(trace)]} />
            </>
          )}
        </div>
      </Drawer>
    </div>
  );
}
