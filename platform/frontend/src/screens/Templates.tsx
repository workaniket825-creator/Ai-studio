import { useEffect, useState } from "react";
import { Card, Button, Tag, InputGroup, Dialog, DialogBody, DialogFooter, TextArea, FormGroup, HTMLSelect, Callout } from "@blueprintjs/core";
import { api, Workflow } from "../api/client";
import { toast } from "../components/toaster";

const CATEGORY_META: Record<string, { icon: any; intent: any }> = {
  security: { icon: "shield", intent: "danger" },
  documents: { icon: "document", intent: "primary" },
  general: { icon: "flows", intent: "success" },
  finetuning: { icon: "predictive-analysis", intent: "warning" },
};

export function Templates({ onRun }: { onRun: (runId: string, wf: Workflow) => void }) {
  const [wfs, setWfs] = useState<Workflow[]>([]);
  const [runTarget, setRunTarget] = useState<Workflow | null>(null);
  const [inputText, setInputText] = useState("");
  // fine-tuning template form
  const [ft, setFt] = useState({ runtime_id: "", notebook: "", dataset: "", parameters: "" });
  const [ftRuntimes, setFtRuntimes] = useState<any>(null);
  const [ftNotebooks, setFtNotebooks] = useState<any[]>([]);

  useEffect(() => { api.listWorkflows().then(setWfs); }, []);
  const isFt = (runTarget as any)?.config?.category === "finetuning";
  useEffect(() => {
    if (!isFt) return;
    api.ftRuntimes().then((r) => { setFtRuntimes(r); setFt((f) => ({ ...f, runtime_id: f.runtime_id || r.default_runtime_id || "" })); }).catch(() => setFtRuntimes(null));
    api.ftCatalog().then((c) => setFtNotebooks((c.notebooks || []).filter((n: any) => n.valid))).catch(() => setFtNotebooks([]));
  }, [isFt]);

  const templates = wfs.filter((w) => (w as any).config?.template);
  const samples = wfs.filter((w) => !(w as any).config?.template);

  const launch = async () => {
    if (!runTarget) return;
    const cat = (runTarget as any).config?.category;
    let input: any = {};
    if (cat === "documents") input = { documents: inputText.split("\n").filter(Boolean) };
    else if (cat === "security") input = { scope: inputText || "org" };
    else if (cat === "finetuning") {
      let parameters: any = {};
      if (ft.parameters.trim()) {
        try { parameters = JSON.parse(ft.parameters); } catch { toast.error("Parameters must be a JSON object, e.g. {\"epochs\": 3}"); return; }
      }
      if (!inputText.trim() && !ft.notebook) { toast.error("Describe the fine-tuning you need, or pick a notebook."); return; }
      input = { message: inputText, input: inputText, goal: inputText, runtime_id: ft.runtime_id,
                notebook: ft.notebook, dataset: ft.dataset.trim(), parameters };
    }
    else input = { goal: inputText };
    try {
      const res = await api.startRun(runTarget.workflow_id, input);
      onRun(res.run_id, runTarget);
    } catch (e: any) { toast.error(e.message); }
    setRunTarget(null); setInputText(""); setFt({ runtime_id: "", notebook: "", dataset: "", parameters: "" });
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
                {(w as any).config?.long_running && <Tag minimal icon="time">long-running · live progress</Tag>}
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
          {isFt ? (
            <div>
              <FormGroup label="What should be fine-tuned?" helperText="The planner agent picks the best notebook from File Storage › finetuning/notebooks and sets its parameters from this description.">
                <TextArea fill rows={4} value={inputText} onChange={(e) => setInputText(e.target.value)}
                  placeholder={(runTarget as any)?.config?.input_hint || "e.g. Fine-tune distilbert on finetuning/datasets/tickets.csv to classify ticket intent, 3 epochs"} />
              </FormGroup>
              <FormGroup label="DSLab runtime">
                {ftRuntimes && !ftRuntimes.dsl_enabled
                  ? <Callout intent="warning" icon="warning-sign">Data Science Lab is disabled — enable it and register a runtime first.</Callout>
                  : ftRuntimes && ftRuntimes.runtimes.length === 0
                  ? <Callout intent="warning" icon="warning-sign">No DSLab runtime registered yet (Data Science Lab › Runtimes).</Callout>
                  : <HTMLSelect fill value={ft.runtime_id} onChange={(e) => setFt({ ...ft, runtime_id: e.target.value })}
                      options={[{ label: "Default runtime", value: "" },
                        ...(ftRuntimes?.runtimes || []).map((r: any) => ({ label: `${r.name}${r.gpu_type ? ` · ${r.gpu_type}` : ""}`, value: r.id }))]} />}
              </FormGroup>
              <FormGroup label="Notebook" helperText={`${ftNotebooks.length} notebook(s) available`}>
                <HTMLSelect fill value={ft.notebook} onChange={(e) => setFt({ ...ft, notebook: e.target.value })}
                  options={[{ label: "Let the agent choose (recommended)", value: "" },
                    ...ftNotebooks.map((n: any) => ({ label: `${n.name}${n.title ? ` — ${n.title}` : ""}`, value: n.name }))]} />
              </FormGroup>
              <FormGroup label="Dataset (optional)" helperText="A File Storage path, e.g. finetuning/datasets/train.jsonl — staged to the runtime. A Hugging Face dataset id is passed through as-is.">
                <InputGroup value={ft.dataset} onChange={(e) => setFt({ ...ft, dataset: e.target.value })} placeholder="finetuning/datasets/…" />
              </FormGroup>
              <FormGroup label="Parameter overrides (optional JSON)" helperText="Always applied on top of what the agent derives.">
                <InputGroup value={ft.parameters} onChange={(e) => setFt({ ...ft, parameters: e.target.value })} placeholder='{"num_train_epochs": 3, "learning_rate": 0.0002}' style={{ fontFamily: "var(--mono)" }} />
              </FormGroup>
            </div>
          ) : <>
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
          </>}
        </DialogBody>
        <DialogFooter actions={<>
          <Button text="Cancel" onClick={() => setRunTarget(null)} />
          <Button intent="primary" icon="play" text="Run" onClick={launch} />
        </>} />
      </Dialog>
    </div>
  );
}
