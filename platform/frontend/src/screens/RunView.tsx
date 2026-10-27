import { useEffect, useState } from "react";
import { Button, Callout, Card, Tag, InputGroup, Tabs, Tab, Collapse, Icon } from "@blueprintjs/core";
import { ActivityStream } from "../components/ActivityStream";
import { Markdown } from "../components/Markdown";
import { api, Workflow } from "../api/client";

function AgentOutput({ no }: { no: any }) {
  const [open, setOpen] = useState(false);
  return (
    <Card style={{ marginBottom: 10, padding: 14 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Icon icon="person" color="var(--accent)" />
        <b>{no.agent}</b>
        {no.steps?.length > 0 && (
          <Button minimal small rightIcon={open ? "chevron-up" : "chevron-down"}
            text={`${no.steps.length} steps`} onClick={() => setOpen(!open)} style={{ marginLeft: "auto" }} />
        )}
      </div>
      <Collapse isOpen={open}>
        <div className="muted" style={{ fontSize: 12, margin: "8px 0", paddingLeft: 8, borderLeft: "2px solid var(--border)" }}>
          {no.steps.map((s: string, i: number) => <div key={i}>• {s}</div>)}
        </div>
      </Collapse>
      <div style={{ marginTop: 8 }}><Markdown text={no.output} /></div>
    </Card>
  );
}

export function RunView({ runId, workflow }: { runId: string; workflow: Workflow }) {
  const [run, setRun] = useState<any>(null);
  const [outputs, setOutputs] = useState<any>({ node_outputs: [], artifacts: [] });
  const [steerText, setSteerText] = useState("");

  const refresh = () => {
    api.getRun(runId).then(setRun).catch(() => {});
    api.runOutputs(runId).then(setOutputs).catch(() => {});
  };
  useEffect(() => { refresh(); const t = setInterval(refresh, 1500); return () => clearInterval(t); }, [runId]);

  const approve = async () => { await api.approve(runId); refresh(); };
  const reject = async () => { await api.reject(runId); refresh(); };
  const doSteer = async () => { if (steerText.trim()) { await api.steer(runId, steerText); setSteerText(""); } };

  const awaiting = run?.status === "awaiting_approval";
  const done = run?.status === "succeeded";
  const artifacts = outputs.artifacts || [];

  const OutputPanel = (
    <div style={{ marginTop: 10 }}>
      {artifacts.length > 0 && (
        <Callout intent="success" icon="document" title="Generated files" style={{ marginBottom: 12 }}>
          {artifacts.map((a: any) => (
            <div key={a.name} style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
              <a href={api.artifactUrl(runId, a.name)} download>
                <Button small intent="primary" icon="download" text={a.name} />
              </a>
              <span className="muted" style={{ fontSize: 11 }}>{a.mime}</span>
            </div>
          ))}
          {artifacts[0]?.preview && (
            <Card style={{ marginTop: 12, maxHeight: 320, overflow: "auto", background: "#0c110d" }}>
              <Markdown text={artifacts[0].preview} />
            </Card>
          )}
        </Callout>
      )}
      {outputs.node_outputs.length === 0 && <div className="muted" style={{ padding: 20 }}>Output will appear here as agents produce it…</div>}
      {outputs.node_outputs.map((no: any, i: number) => <AgentOutput key={i} no={no} />)}
    </div>
  );

  return (
    <div>
      <div className="section-head">
        <div><h2>{workflow.name}</h2><span className="muted metric">{runId}</span></div>
        <Tag large intent={done ? "success" : awaiting ? "warning" : "primary"}>{run?.status || "…"}</Tag>
      </div>

      <div className="run-layout">
        <div style={{ display: "flex", flexDirection: "column", gap: 12, overflow: "auto" }}>
          {awaiting && (
            <Callout intent="warning" icon="hand-up" title="Approval required">
              <div style={{ marginBottom: 10 }}>An agent wants to perform a significant action. Approve to continue.</div>
              <Button intent="success" icon="tick" text="Approve" onClick={approve} style={{ marginRight: 8 }} />
              <Button icon="cross" text="Reject" onClick={reject} />
            </Callout>
          )}
          {run?.status === "running" && (
            <Card>
              <b>Steer this run</b>
              <div className="muted" style={{ fontSize: 12, margin: "4px 0 8px" }}>Inject guidance while it runs.</div>
              <div style={{ display: "flex", gap: 8 }}>
                <InputGroup fill placeholder="e.g. focus on Q3 only" value={steerText}
                  onChange={(e) => setSteerText(e.target.value)} onKeyDown={(e) => e.key === "Enter" && doSteer()} />
                <Button icon="direction-right" text="Steer" onClick={doSteer} />
              </div>
            </Card>
          )}
          <Card style={{ padding: "10px 14px" }}>
            <div style={{ display: "flex", gap: 24 }}>
              <Metric label="Input tok" value={run?.input_tokens ?? 0} />
              <Metric label="Output tok" value={run?.output_tokens ?? 0} />
              <Metric label="Latency" value={`${((run?.latency_ms ?? 0) / 1000).toFixed(1)}s`} />
              <Metric label="Verdict" value={run?.verification?.verdict ?? "—"} />
            </div>
          </Card>

          <Tabs id="runtabs" large defaultSelectedTabId="output">
            <Tab id="output" title="Output" panel={OutputPanel} />
            <Tab id="details" title="Details" panel={
              <div className="muted" style={{ marginTop: 10, fontSize: 12 }}>
                Trace id: {run?.mlflow_trace_id || "—"} · steers: {run?.steers?.length ?? 0}
                {done && <> · <a href="#" onClick={(e) => { e.preventDefault(); api.feedback(runId, "up"); }}>👍 helpful</a></>}
              </div>
            } />
          </Tabs>
        </div>

        <ActivityStream runId={runId} />
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: any }) {
  return (
    <div>
      <div className="muted" style={{ fontSize: 11 }}>{label}</div>
      <div className="metric" style={{ fontSize: 16, fontWeight: 600 }}>{value}</div>
    </div>
  );
}
