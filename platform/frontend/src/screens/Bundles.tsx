import { useEffect, useState } from "react";
import { Button, Card, Tag } from "@blueprintjs/core";
import { api } from "../api/client";
import { toast } from "../components/toaster";

export function Bundles() {
  const [bundles, setBundles] = useState<any[]>([]);
  const refresh = () => api.listBundles().then(setBundles);
  useEffect(() => { refresh(); }, []);

  const install = async (b: any) => {
    try {
      const res = await api.installBundle(b.id);
      toast.success(res.agents_created.length
        ? `Installed ${b.name}: added ${res.agents_created.join(", ")}`
        : `${b.name} already installed (reuse-first, no duplicates)`);
      refresh();
    } catch (e: any) { toast.error(e.message || "Install failed"); }
  };

  return (
    <div>
      <div className="section-head">
        <div><h2>Bundles</h2><span className="muted">Role Packs — installable agents for a domain</span></div>
      </div>
      <div className="garden-grid">
        {bundles.map((b) => (
          <Card key={b.id} style={{ padding: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <b style={{ fontSize: 15 }}>{b.name}</b>
              <Tag minimal round intent={b.category === "finance" ? "success" : "primary"}>{b.category}</Tag>
            </div>
            <div className="muted" style={{ fontSize: 12, margin: "6px 0 10px" }}>{b.description}</div>
            <div className="chip-row">
              {b.agents.map((a: any) => <Tag key={a.agent_name} minimal icon="person">{a.agent_name}</Tag>)}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12 }}>
              <span className="muted metric" style={{ fontSize: 11 }}>{b.installs} installs</span>
              <Button small intent="primary" icon="cube-add" text="Install" onClick={() => install(b)} />
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
