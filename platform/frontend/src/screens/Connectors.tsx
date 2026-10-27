import { useEffect, useState } from "react";
import { Card, Switch, Tag, InputGroup, Button, Collapse, Icon, Callout } from "@blueprintjs/core";
import { api } from "../api/client";
import { toast } from "../components/toaster";

const CAT_META: Record<string, { label: string; icon: any; intent: any }> = {
  builtin: { label: "ADK built-in tools", icon: "build", intent: "success" },
  mcp: { label: "MCP toolsets", icon: "data-connection", intent: "primary" },
  toolkit: { label: "Third-party toolkits", icon: "layers", intent: "primary" },
  openapi: { label: "OpenAPI / REST", icon: "globe-network", intent: "none" },
  integration: { label: "Enterprise connectors (Application Integration)", icon: "office", intent: "warning" },
};

function ConnectorCard({ c, onSaved }: { c: any; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [cfg, setCfg] = useState<Record<string, string>>(c.config || {});

  const toggle = async (enabled: boolean) => {
    try { await api.toggleConnector(c.id, enabled, cfg); toast.success(`${c.name} ${enabled ? "enabled" : "disabled"}`); onSaved(); }
    catch (e: any) { toast.error(e.message); }
  };
  const saveCfg = async () => {
    try { await api.toggleConnector(c.id, true, cfg); toast.success(`${c.name} configured`); onSaved(); }
    catch (e: any) { toast.error(e.message); }
  };

  return (
    <div className="agent-card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
        <div>
          <div style={{ fontWeight: 600 }}>{c.name}</div>
          <div className="role" style={{ fontSize: 12 }}>{c.description}</div>
        </div>
        <Switch large checked={c.enabled} onChange={(e) => toggle(e.currentTarget.checked)} style={{ margin: 0 }} />
      </div>
      <div className="chip-row">
        <Tag minimal round intent={c.cloud_free ? "success" : "warning"} icon={c.cloud_free ? "cloud-tick" : "cloud"}>
          {c.cloud_free ? "no cloud needed" : "needs GCP Integration"}
        </Tag>
        {c.enabled && <Tag minimal intent="success" icon="tick">enabled</Tag>}
      </div>
      {c.config_fields?.length > 0 && (
        <>
          <Button minimal small style={{ marginTop: 8 }} rightIcon={open ? "chevron-up" : "chevron-down"}
            icon="cog" text="Config" onClick={() => setOpen(!open)} />
          <Collapse isOpen={open}>
            <div style={{ marginTop: 8 }}>
              {c.config_fields.map((f: any) => (
                <div key={f.key} style={{ marginBottom: 8 }}>
                  <div className="muted" style={{ fontSize: 11, marginBottom: 3 }}>{f.key}</div>
                  <InputGroup small value={cfg[f.key] ?? ""} placeholder={f.example}
                    onChange={(e) => setCfg({ ...cfg, [f.key]: e.target.value })} />
                </div>
              ))}
              <Button small intent="primary" icon="floppy-disk" text="Save config" onClick={saveCfg} />
            </div>
          </Collapse>
        </>
      )}
      <div className="muted metric" style={{ fontSize: 10, marginTop: 8 }}>{c.adk}</div>
    </div>
  );
}

export function Connectors() {
  const [connectors, setConnectors] = useState<any[]>([]);
  const refresh = () => api.listConnectors().then(setConnectors);
  useEffect(() => { refresh(); }, []);

  const byCat = connectors.reduce((acc: Record<string, any[]>, c) => {
    (acc[c.category] = acc[c.category] || []).push(c); return acc;
  }, {});
  const enabledCount = connectors.filter((c) => c.enabled).length;

  return (
    <div>
      <div className="section-head">
        <div><h2>Connectors</h2><span className="muted">Google ADK out-of-box connectivity · {enabledCount} enabled</span></div>
      </div>
      <Callout icon="lightbulb" intent="primary" style={{ marginBottom: 16 }}>
        Enable a connector to make it available to agents (Create agent → Tools). ADK provides these
        connectivity options out of the box — built-in tools, MCP toolsets, third-party toolkits,
        OpenAPI, and 100+ enterprise connectors via Application Integration.
      </Callout>
      {Object.entries(CAT_META).map(([cat, meta]) =>
        byCat[cat] ? (
          <div key={cat} style={{ marginBottom: 22 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "0 0 10px" }}>
              <Icon icon={meta.icon} color="var(--accent)" />
              <b style={{ fontSize: 14 }}>{meta.label}</b>
              <Tag minimal>{byCat[cat].length}</Tag>
            </div>
            <div className="garden-grid">
              {byCat[cat].map((c) => <ConnectorCard key={c.id} c={c} onSaved={refresh} />)}
            </div>
          </div>
        ) : null
      )}
    </div>
  );
}
