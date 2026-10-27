import { useEffect, useState } from "react";
import { Button, Card, HTMLSelect, HTMLTable, NumericInput, Switch, Tag, NonIdealState } from "@blueprintjs/core";
import { api, Workflow } from "../api/client";

export function Schedules() {
  const [schedules, setSchedules] = useState<any[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [wf, setWf] = useState("");
  const [interval, setIntervalSec] = useState(300);

  const refresh = () => api.listSchedules().then(setSchedules);
  useEffect(() => {
    refresh();
    api.listWorkflows().then((w) => { setWorkflows(w); setWf(w[0]?.workflow_id || ""); });
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, []);

  const create = async () => { if (wf) { await api.createSchedule(wf, interval); refresh(); } };
  const toggle = async (s: any) => { await api.toggleSchedule(s.id, !s.enabled); refresh(); };
  const trigger = async (s: any) => { await api.triggerSchedule(s.id); refresh(); };
  const del = async (s: any) => { if (confirm("Delete this schedule?")) { await api.deleteSchedule(s.id); refresh(); } };

  return (
    <div>
      <div className="section-head">
        <div><h2>Schedules</h2><span className="muted">Unattended runs — interval triggers</span></div>
      </div>

      <Card style={{ marginBottom: 16 }}>
        <b>New schedule</b>
        <div style={{ display: "flex", gap: 10, alignItems: "flex-end", marginTop: 10 }}>
          <div>
            <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>Workflow</div>
            <HTMLSelect value={wf} onChange={(e) => setWf(e.target.value)}
              options={workflows.map((w) => ({ label: w.name, value: w.workflow_id }))} />
          </div>
          <div>
            <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>Every (seconds)</div>
            <NumericInput value={interval} min={3} onValueChange={setIntervalSec} style={{ width: 110 }} />
          </div>
          <Button intent="primary" icon="time" text="Create schedule" onClick={create} disabled={!wf} />
        </div>
      </Card>

      {schedules.length === 0 ? (
        <NonIdealState icon="time" title="No schedules" description="Create one above to run a workflow unattended." />
      ) : (
        <Card>
          <HTMLTable compact striped style={{ width: "100%" }}>
            <thead><tr><th>Workflow</th><th>Every</th><th>Enabled</th><th>Last run</th><th>Next run</th><th></th></tr></thead>
            <tbody>
              {schedules.map((s) => (
                <tr key={s.id}>
                  <td>{s.workflow_name}</td>
                  <td className="metric">{s.interval_seconds}s</td>
                  <td><Switch checked={s.enabled} onChange={() => toggle(s)} style={{ margin: 0 }} /></td>
                  <td className="metric muted" style={{ fontSize: 11 }}>
                    {s.last_run ? new Date(s.last_run).toLocaleTimeString([], { hour12: false }) : "—"}</td>
                  <td className="metric muted" style={{ fontSize: 11 }}>
                    {s.next_run ? new Date(s.next_run).toLocaleTimeString([], { hour12: false }) : "—"}</td>
                  <td>
                    <Button small minimal icon="play" onClick={() => trigger(s)} />
                    <Button small minimal icon="trash" onClick={() => del(s)} />
                  </td>
                </tr>
              ))}
            </tbody>
          </HTMLTable>
        </Card>
      )}
    </div>
  );
}
