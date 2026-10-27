import { useEffect, useState } from "react";
import { Button, Card, Tabs, Tab, Tag, HTMLTable, NonIdealState, Callout } from "@blueprintjs/core";
import { api } from "../api/client";
import { ActivityStream } from "../components/ActivityStream";
import { toast } from "../components/toaster";

const sevIntent = (s: string) => (s === "high" ? "danger" : s === "medium" ? "warning" : "success");

export function Insights() {
  const [reports, setReports] = useState<any[]>([]);
  const [findings, setFindings] = useState<any[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = () => { api.listReports().then(setReports); api.latestFindings().then(setFindings); };
  useEffect(() => { refresh(); }, []);

  const run = async () => {
    setBusy(true);
    try {
      const r = await api.runInsights();
      setRunId(r.run_id);
      toast.info("Insights workflow started — generating report…");
      setTimeout(() => { refresh(); setBusy(false); }, 4000);
    } catch (e: any) { toast.error(e.message); setBusy(false); }
  };

  const AnalysisPanel = (
    <div style={{ marginTop: 12 }}>
      <Callout icon="lightbulb" intent="primary" style={{ marginBottom: 14 }}>
        The Platform Insights meta-workflow analyzes runs, agents, workflows and metrics,
        then generates a Word recommendation report. It dogfoods the platform — you'll see it
        think in the live stream.
      </Callout>
      <Button large intent="primary" icon="predictive-analysis" loading={busy}
        text="Run insights analysis" onClick={run} />
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginTop: 16 }}>
        <Card>
          <b>Latest findings</b>
          <div style={{ marginTop: 10 }}>
            {findings.length === 0 && <span className="muted">Run analysis to generate findings.</span>}
            {findings.map((f, i) => (
              <div key={i} style={{ padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
                <Tag minimal intent={sevIntent(f.severity)} style={{ marginRight: 8 }}>{f.severity}</Tag>
                <b style={{ fontSize: 13 }}>{f.title}</b>
                <div className="muted" style={{ fontSize: 12, marginTop: 3 }}>→ {f.recommendation}</div>
              </div>
            ))}
          </div>
        </Card>
        <div style={{ height: 360 }}>
          {runId ? <ActivityStream runId={runId} />
            : <Card style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                <span className="muted">Live analysis stream appears here.</span></Card>}
        </div>
      </div>
    </div>
  );

  const ReportsPanel = (
    <div style={{ marginTop: 12 }}>
      {reports.length === 0 ? (
        <NonIdealState icon="document" title="No reports yet"
          description="Run an analysis to generate a downloadable Word report." />
      ) : (
        <Card>
          <HTMLTable compact striped style={{ width: "100%" }}>
            <thead><tr><th>Report</th><th>Generated</th><th>Summary</th><th>Findings</th><th></th></tr></thead>
            <tbody>
              {reports.map((r) => (
                <tr key={r.id}>
                  <td className="metric">{r.id}</td>
                  <td className="muted metric" style={{ fontSize: 11 }}>{new Date(r.generated_at).toLocaleString([], { hour12: false })}</td>
                  <td>{r.summary}</td>
                  <td>{(r.findings || []).length}</td>
                  <td>
                    <a href={api.reportDownloadUrl(r.id)} download>
                      <Button small intent="primary" icon="download" text="Word report" />
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </HTMLTable>
        </Card>
      )}
    </div>
  );

  return (
    <div>
      <div className="section-head">
        <div><h2>Platform Insights</h2><span className="muted">Module 6 · usage analysis → Word recommendation reports</span></div>
      </div>
      <Tabs id="insights" large>
        <Tab id="analysis" title="Analysis" panel={AnalysisPanel} />
        <Tab id="reports" title="Reports" panel={ReportsPanel} />
      </Tabs>
    </div>
  );
}
