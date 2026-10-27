import { useEffect, useState } from "react";
import { Card, Button, Tag, InputGroup, Dialog, DialogBody, DialogFooter, TextArea } from "@blueprintjs/core";
import { api, Workflow } from "../api/client";
import { toast } from "../components/toaster";

const CATEGORY_META: Record<string, { icon: any; intent: any }> = {
  security: { icon: "shield", intent: "danger" },
  documents: { icon: "document", intent: "primary" },
  general: { icon: "flows", intent: "success" },
};

export function Templates({ onRun }: { onRun: (runId: string, wf: Workflow) => void }) {
  const [wfs, setWfs] = useState<Workflow[]>([]);
  const [runTarget, setRunTarget] = useState<Workflow | null>(null);
  const [inputText, setInputText] = useState("");

  useEffect(() => { api.listWorkflows().then(setWfs); }, []);

  const templates = wfs.filter((w) => (w as any).config?.template);
  const samples = wfs.filter((w) => !(w as any).config?.template);

  const launch = async () => {
    if (!runTarget) return;
    const cat = (runTarget as any).config?.category;
    let input: any = {};
    if (cat === "documents") input = { documents: inputText.split("\n").filter(Boolean) };
    else if (cat === "security") input = { scope: inputText || "org" };
    else input = { goal: inputText };
    try {
      const res = await api.startRun(runTarget.workflow_id, input);
      onRun(res.run_id, runTarget);
    } catch (e: any) { toast.error(e.message); }
    setRunTarget(null); setInputText("");
  };

  const Grid = ({ items, label }: { items: Workflow[]; label: string }) => (
    <>
      <div className="muted" style={{ margin: "16px 0 8px", textTransform: "uppercase", letterSpacing: ".08em", fontSize: 11 }}>{label}</div>
      <div className="garden-grid">
        {items.map((w) => {
          const cat = (w as any).config?.category || "general";
          const meta = CATEGORY_META[cat] || CATEGORY_META.general;
          return (
            <Card key={w.workflow_id} style={{ padding: 16 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <b style={{ fontSize: 14 }}>{w.name}</b>
                <Tag minimal round icon={meta.icon} intent={meta.intent}>{cat}</Tag>
              </div>
              <div className="muted" style={{ fontSize: 12, margin: "8px 0 10px", minHeight: 48 }}>
                {(w as any).config?.description || w.goal_prompt}
              </div>
              <div className="chip-row" style={{ marginBottom: 12 }}>
                <Tag minimal icon="flow-linear">{w.nodes.length} agents</Tag>
                {w.approval_gates?.length > 0 && <Tag minimal icon="hand-up" intent="warning">approval</Tag>}
              </div>
              <Button fill intent="primary" icon="play" text="Use & run template" onClick={() => setRunTarget(w)} />
            </Card>
          );
        })}
      </div>
    </>
  );

  return (
    <div>
      <div className="section-head">
        <div><h2>Workflow Templates</h2><span className="muted">Launch ready-made, multi-agent workflows</span></div>
      </div>
      {templates.length > 0 && <Grid items={templates} label="Scenario templates" />}
      <Grid items={samples} label="Sample workflows" />

      <Dialog isOpen={!!runTarget} onClose={() => setRunTarget(null)} title={runTarget?.name} className="bp5-dark">
        <DialogBody>
          <div className="muted" style={{ marginBottom: 10, fontSize: 13 }}>
            {(runTarget as any)?.config?.category === "documents"
              ? "Paste document names or text (one per line) to process:"
              : (runTarget as any)?.config?.category === "security"
              ? "Scope to analyze (e.g. org, team:finance):"
              : "Optional input for this run:"}
          </div>
          <TextArea fill rows={5} value={inputText} onChange={(e) => setInputText(e.target.value)}
            placeholder={(runTarget as any)?.config?.category === "documents"
              ? "policy_2026.pdf\ncontract_acme.pdf\nmeeting_notes.txt" : "org"} />
        </DialogBody>
        <DialogFooter actions={<>
          <Button text="Cancel" onClick={() => setRunTarget(null)} />
          <Button intent="primary" icon="play" text="Run" onClick={launch} />
        </>} />
      </Dialog>
    </div>
  );
}
