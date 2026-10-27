import { useEffect, useState } from "react";
import { Button, InputGroup, Tag, NonIdealState } from "@blueprintjs/core";
import { AgentCard, api } from "../api/client";
import { CreateAgentWizard } from "../components/CreateAgentWizard";

const modelTone = (m: string) => (m.includes("pro") || m.includes("large") ? "var(--violet)" : "var(--accent)");

export function Garden({ onTest }: { onTest: (runId: string, name: string) => void }) {
  const [agents, setAgents] = useState<AgentCard[]>([]);
  const [q, setQ] = useState("");
  const [wizard, setWizard] = useState(false);
  const [editing, setEditing] = useState<AgentCard | undefined>(undefined);

  const refresh = () => api.listAgents(q).then(setAgents);
  useEffect(() => { refresh(); }, [q]);

  const clone = async (id: string) => { await api.cloneAgent(id); refresh(); };
  const del = async (id: string) => { if (confirm("Delete this agent?")) { await api.deleteAgent(id); refresh(); } };
  const edit = (a: AgentCard) => { setEditing(a); setWizard(true); };
  const create = () => { setEditing(undefined); setWizard(true); };
  const test = async (a: AgentCard) => {
    const r = await api.testAgent(a.agent_id, {});
    onTest(r.run_id, a.agent_name);
  };

  return (
    <div>
      <div className="section-head">
        <div><h2>Agent Garden</h2><span className="muted">{agents.length} agents · reuse-first catalog</span></div>
        <div style={{ display: "flex", gap: 8 }}>
          <InputGroup leftIcon="search" placeholder="Search capabilities…"
            value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 260 }} />
          <Button intent="primary" icon="plus" text="Create agent" onClick={create} />
        </div>
      </div>

      {agents.length === 0 ? (
        <NonIdealState icon="search" title="No agents match"
          action={<Button icon="plus" text="Create one" onClick={create} />} />
      ) : (
        <div className="garden-grid">
          {agents.map((a) => (
            <div className="agent-card" key={a.agent_id}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
                <div>
                  <div style={{ fontWeight: 600 }}>
                    {a.agent_name}
                    {a.status === "deprecated" && <Tag minimal intent="warning" style={{ marginLeft: 6 }}>deprecated</Tag>}
                  </div>
                  <div className="role">{a.role}</div>
                </div>
                <Tag minimal round className="metric" style={{ color: modelTone(a.model_config.model) }}>
                  {a.model_config.model.replace("gemini-", "").replace("-latest", "")}
                </Tag>
              </div>
              <div className="muted" style={{ fontSize: 12, marginTop: 8, minHeight: 32 }}>{a.description}</div>
              <div className="chip-row">
                <Tag minimal icon="git-branch" className="metric">v{a.version}</Tag>
                {a.collaboration?.role !== "standalone" && <Tag minimal icon="people">{a.collaboration.role}</Tag>}
                {(a.tools || []).map((t, i) => <Tag key={i} minimal icon="wrench">{t.name || t.type}</Tag>)}
              </div>
              <div style={{ display: "flex", gap: 6, marginTop: 12 }}>
                <Button small icon="play" text="Test" onClick={() => test(a)} />
                <Button small icon="edit" text="Edit" onClick={() => edit(a)} />
                <Button small minimal icon="duplicate" onClick={() => clone(a.agent_id)} />
                <Button small minimal icon="trash" onClick={() => del(a.agent_id)} />
              </div>
            </div>
          ))}
        </div>
      )}

      <CreateAgentWizard isOpen={wizard} editing={editing}
        onClose={() => { setWizard(false); setEditing(undefined); }} onCreated={refresh} />
    </div>
  );
}
