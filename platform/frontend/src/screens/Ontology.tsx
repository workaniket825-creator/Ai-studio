import { useEffect, useState } from "react";
import { Card, Button, Tag, InputGroup, FormGroup, HTMLSelect, Switch, Callout, Tabs, Tab,
  HTMLTable, NonIdealState, NumericInput, TextArea, Spinner, ProgressBar, Collapse } from "@blueprintjs/core";
import { api } from "../api/client";
import { toast } from "../components/toaster";
import { GraphCanvas } from "./GraphCanvas";

export function Ontology() {
  return (
    <div>
      <div className="section-head">
        <div><h2>Ontology Intelligence</h2>
          <span className="muted">Optional knowledge-graph grounding — off by default, per tenant &amp; workflow</span></div>
      </div>
      <Callout icon="info-sign" intent="primary" style={{ marginBottom: 14 }}>
        When <b>off</b>, the platform behaves exactly as today (plain retrieval). When <b>on</b> for a
        workflow/tenant with a published graph, agents ground design, retrieval, planning and actions
        in the ontology — falling back to plain retrieval for anything unmodeled.
      </Callout>
      <Tabs id="onto-tabs" defaultSelectedTabId="enable">
        <Tab id="enable" title="Enablement" panel={<Enablement />} />
        <Tab id="datastore" title="Datastore" panel={<Datastore />} />
        <Tab id="graphs" title="Graphs & Authoring" panel={<Graphs />} />
        <Tab id="telemetry" title="Telemetry" panel={<Telemetry />} />
      </Tabs>
    </div>
  );
}

function Enablement() {
  const [cfg, setCfg] = useState<any>(null);
  const [wf, setWf] = useState(""); const [tenant, setTenant] = useState("default");
  const [workflows, setWorkflows] = useState<any[]>([]);
  const [pubGraphs, setPubGraphs] = useState<any[]>([]);
  const [selGraph, setSelGraph] = useState("");
  const refresh = () => api.ontologyConfig().then((c) => { setCfg(c); setSelGraph((prev) => prev || (c.workflow_graphs || {})[wf] || ""); });
  useEffect(() => { refresh(); api.listWorkflows().then((w) => { setWorkflows(w); setWf((p) => p || w[0]?.workflow_id || ""); });
    api.ontologyPublishedGraphs().then(setPubGraphs).catch(() => {}); }, []);
  const wfName = (id: string) => workflows.find((w) => w.workflow_id === id)?.name || id;
  if (!cfg) return <div className="muted" style={{ padding: 20 }}>Loading…</div>;
  return (
    <div style={{ paddingTop: 12, maxWidth: 760 }}>
      <Card style={{ marginBottom: 14 }}>
        <b>System default</b>
        <div className="muted" style={{ fontSize: 12, margin: "4px 0 10px" }}>
          The global fallback when a workflow/tenant has no explicit setting. Keep off unless you want
          ontology on everywhere.</div>
        <Switch large checked={cfg.enabled_default} label="Ontology enabled by default"
          onChange={async () => { await api.ontologySetConfig({ enabled_default: !cfg.enabled_default }); toast.success("Updated default"); refresh(); }} />
      </Card>
      <Card style={{ marginBottom: 14 }}>
        <b>Per-workflow</b>
        <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "flex-end" }}>
          <FormGroup label="Workflow" style={{ marginBottom: 0, minWidth: 280 }}>
            <HTMLSelect fill value={wf} onChange={(e) => { setWf(e.target.value); setSelGraph((cfg.workflow_graphs || {})[e.target.value] || ""); }}
              options={workflows.length
                ? workflows.map((w) => ({ label: w.name, value: w.workflow_id }))
                : [{ label: "no workflows yet", value: "" }]} />
          </FormGroup>
          <FormGroup label="Ontology graph" style={{ marginBottom: 0, minWidth: 260 }}
            helperText="Which published ontology this workflow uses.">
            <HTMLSelect fill value={selGraph} onChange={(e) => setSelGraph(e.target.value)}
              options={[{ label: pubGraphs.length ? "— auto (tag/tenant match) —" : "no published graphs yet", value: "" },
                        ...pubGraphs.map((g) => ({ label: g.name, value: g.id }))]} />
          </FormGroup>
          <Button intent="success" icon="tick" text="Enable" disabled={!wf}
            onClick={async () => {
              if (selGraph) { await api.ontologySetWorkflowGraph(wf, selGraph); }
              else { await api.ontologyEnableWorkflow(wf, true); }
              toast.success(`Ontology enabled for ${wfName(wf)}${selGraph ? " → " + (pubGraphs.find((g) => g.id === selGraph)?.name || "") : ""}`);
              refresh();
            }} />
          <Button text="Disable" disabled={!wf}
            onClick={async () => { await api.ontologySetWorkflowGraph(wf, ""); await api.ontologyEnableWorkflow(wf, false); toast.info("Disabled for " + wfName(wf)); setSelGraph(""); refresh(); }} />
        </div>
        <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
          Enabled workflows: {Object.entries(cfg.workflows || {}).filter(([, v]) => v).map(([k]) => {
            const gid = (cfg.workflow_graphs || {})[k];
            const gname = pubGraphs.find((g) => g.id === gid)?.name;
            return wfName(k) + (gname ? ` → ${gname}` : "");
          }).join(", ") || "none"}
        </div>
        {cfg.workflows?.[wf] && !((cfg.workflow_graphs || {})[wf]) && pubGraphs.length === 0 && (
          <Callout intent="warning" style={{ marginTop: 8 }}>
            This workflow is enabled, but no <b>published</b> ontology exists yet — so agents fall back to plain context.
            Create + approve + publish a graph, then bind it above for the ontology to actually be used.
          </Callout>
        )}
        <div className="muted" style={{ textTransform: "uppercase", letterSpacing: ".08em", fontSize: 11, margin: "16px 0 6px" }}>
          Context size — how much connected graph an agent receives
        </div>
        <div style={{ display: "flex", gap: 12, alignItems: "flex-end" }}>
          <FormGroup label="Expansion depth (hops)" style={{ marginBottom: 0 }}
            helperText="From each matched node, how many relationship hops to include.">
            <NumericInput min={0} max={6} value={cfg.expansion?.max_hops ?? 1} style={{ width: 90 }}
              onValueChange={(v) => setCfg({ ...cfg, expansion: { ...(cfg.expansion || {}), max_hops: v } })} />
          </FormGroup>
          <FormGroup label="Max nodes (cap)" style={{ marginBottom: 0 }}
            helperText="Hard cap so a large ontology never floods the agent.">
            <NumericInput min={1} max={200} value={cfg.expansion?.max_nodes ?? 15} style={{ width: 110 }}
              onValueChange={(v) => setCfg({ ...cfg, expansion: { ...(cfg.expansion || {}), max_nodes: v } })} />
          </FormGroup>
          <Button intent="primary" text="Save context size"
            onClick={async () => { await api.ontologySetConfig({ expansion: cfg.expansion }); toast.success("Context size saved"); refresh(); }} />
        </div>
      </Card>
      <Card>
        <b>Per-tenant</b>
        <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "flex-end" }}>
          <FormGroup label="Tenant" style={{ marginBottom: 0 }}>
            <InputGroup value={tenant} onChange={(e) => setTenant(e.target.value)} /></FormGroup>
          <Button intent="success" text="Enable" disabled={!tenant}
            onClick={async () => { await api.ontologyEnableTenant(tenant, true); toast.success("Enabled for " + tenant); refresh(); }} />
          <Button text="Disable" disabled={!tenant}
            onClick={async () => { await api.ontologyEnableTenant(tenant, false); toast.info("Disabled for " + tenant); refresh(); }} />
        </div>
        <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>Resolution order: workflow → tenant → system default.</div>
      </Card>
    </div>
  );

  async function apiPut(c: any) {
    await fetch(`/api/v1/ontology/config`, { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled_default: c.enabled_default }) });
    refresh();
  }
}

function Datastore() {
  const [ds, setDs] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.ontologyDatastore().then(setDs); }, []);
  if (!ds) return <div className="muted" style={{ padding: 20 }}>Loading…</div>;
  const set = (k: string, v: any) => setDs({ ...ds, [k]: v });
  const test = async () => { setBusy(true); try { const r = await api.ontologyTestDatastore(ds);
    r.ok ? toast.success(r.detail) : toast.error(r.detail); } finally { setBusy(false); } };
  const save = async () => { setBusy(true); try { const r = await api.ontologySaveDatastore(ds);
    setDs(r.datastore); r.ok ? toast.success("Saved & applied — " + r.detail) : toast.error(r.detail); }
    finally { setBusy(false); } };
  return (
    <div style={{ paddingTop: 12, maxWidth: 760 }}>
      <Callout icon="cog" intent="primary" style={{ marginBottom: 14 }}>
        Configure the knowledge store entirely here — no backend/code change. Enter the endpoint, test it,
        and save; changes are hot-applied. Secrets are stored by reference, never displayed.
      </Callout>
      <Card>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <b>Datastore connection</b>
          <Tag intent={ds.status === "connected" ? "success" : ds.status === "failing" ? "danger" : "none"}
            minimal>{ds.status}</Tag>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 12 }}>
          <FormGroup label="Store type">
            <HTMLSelect fill value={ds.type} onChange={(e) => set("type", e.target.value)}
              options={[{ label: "Built-in JSON (default, zero-dep)", value: "json" },
                        { label: "PostgreSQL + pgvector", value: "postgres" }]} />
          </FormGroup>
          <FormGroup label="Secret reference" helperText="Name in the secret store — not the value">
            <InputGroup value={ds.secret_ref} onChange={(e) => set("secret_ref", e.target.value)}
              placeholder="vault/ontology_db" disabled={ds.type === "json"} />
          </FormGroup>
          <FormGroup label="Host / endpoint">
            <InputGroup value={ds.host} onChange={(e) => set("host", e.target.value)}
              placeholder="db.example.com" disabled={ds.type === "json"} /></FormGroup>
          <FormGroup label="Port">
            <NumericInput fill value={ds.port} onValueChange={(v) => set("port", v)} disabled={ds.type === "json"} /></FormGroup>
          <FormGroup label="Database">
            <InputGroup value={ds.database} onChange={(e) => set("database", e.target.value)} disabled={ds.type === "json"} /></FormGroup>
          <FormGroup label="Schema">
            <InputGroup value={ds.schema} onChange={(e) => set("schema", e.target.value)} disabled={ds.type === "json"} /></FormGroup>
        </div>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <Switch checked={ds.tls} label="TLS" onChange={() => set("tls", !ds.tls)} disabled={ds.type === "json"} />
          <Switch checked={ds.vector} label="pgvector" onChange={() => set("vector", !ds.vector)} disabled={ds.type === "json"} />
        </div>
        {ds.last_error && <Callout intent="danger" style={{ margin: "8px 0" }}>{ds.last_error}</Callout>}
        <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
          <Button icon="pulse" text="Test connection" onClick={test} loading={busy} />
          <Button intent="primary" icon="floppy-disk" text="Save & apply" onClick={save} loading={busy} />
        </div>
      </Card>
    </div>
  );
}

function Graphs() {
  const [graphs, setGraphs] = useState<any[]>([]);
  const [sel, setSel] = useState<any>(null);
  const [name, setName] = useState(""); const [mode, setMode] = useState("hybrid"); const [domain, setDomain] = useState("");
  const refresh = () => api.ontologyGraphs().then(setGraphs);
  useEffect(() => { refresh(); }, []);

  const create = async () => {
    if (!name.trim()) { toast.error("Name required"); return; }
    const g = await api.ontologyCreateGraph({ name, authoring_mode: mode, tags: { domain } });
    toast.success("Created " + g.name); setName(""); setDomain(""); refresh();
  };

  return (
    <div style={{ paddingTop: 12 }}>
      <Card style={{ marginBottom: 14 }}>
        <b>Create a graph</b>
        <div style={{ display: "flex", gap: 8, marginTop: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
          <FormGroup label="Name" style={{ marginBottom: 0 }}>
            <InputGroup value={name} onChange={(e) => setName(e.target.value)} placeholder="Supply Chain" /></FormGroup>
          <FormGroup label="Authoring mode" style={{ marginBottom: 0 }}>
            <HTMLSelect value={mode} onChange={(e) => setMode(e.target.value)}
              options={["hybrid", "auto", "manual"]} /></FormGroup>
          <FormGroup label="Domain tag" style={{ marginBottom: 0 }}>
            <InputGroup value={domain} onChange={(e) => setDomain(e.target.value)} placeholder="supply chain" /></FormGroup>
          <Button intent="primary" icon="add" text="Create" onClick={create} />
        </div>
      </Card>

      {graphs.length === 0 ? <NonIdealState icon="graph" title="No graphs yet"
        description="Create one above. Graphs stay invisible to agents until published and enabled." /> : (
        <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", gap: 14 }}>
          <div>
            {graphs.map((g) => (
              <Card key={g.id} interactive onClick={() => setSel(g)}
                style={{ marginBottom: 8, borderColor: sel?.id === g.id ? "var(--accent)" : undefined }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <b>{g.name}</b>
                  <Tag minimal intent={g.status === "published" ? "success" : "none"}>{g.status}</Tag>
                </div>
                <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
                  {g.authoring_mode} · {Object.values(g.tags || {}).join(", ") || "no tags"}</div>
                <Button small minimal intent="danger" icon="trash" text="Delete" style={{ marginTop: 6 }}
                  onClick={async (e: any) => { e.stopPropagation();
                    if (confirm(`Delete graph "${g.name}" and all its entities/edges?`)) {
                      await api.ontologyDeleteGraph(g.id); toast.success("Graph deleted");
                      if (sel?.id === g.id) setSel(null); refresh(); } }} />
              </Card>
            ))}
          </div>
          {sel ? <GraphDetail g={sel} onChange={refresh} /> :
            <div className="muted" style={{ padding: 20 }}>Select a graph to author, review, and publish.</div>}
        </div>
      )}
    </div>
  );
}

function GraphDetail({ g, onChange }: { g: any; onChange: () => void }) {
  const [queue, setQueue] = useState<any[]>([]);
  const [versions, setVersions] = useState<any[]>([]);
  const [en, setEn] = useState({ type: "", name: "" });
  const [txt, setTxt] = useState("");
  const [rowsTxt, setRowsTxt] = useState("");
  const [filePath, setFilePath] = useState("");
  const [ds, setDs] = useState<any>({ type: "json", host: "", database: "" });
  const [models, setModels] = useState<any>({ models: [], default: "", has_models: false });
  const [modelId, setModelId] = useState("");
  const [instr, setInstr] = useState("");
  const [exPrompt, setExPrompt] = useState("");   // scientific extraction prompt (editable, mandatory)
  const [showPrompt, setShowPrompt] = useState(false);
  const [job, setJob] = useState<any>(null);  // live extraction progress
  useEffect(() => { api.ontologyModels().then((m) => { setModels(m); setModelId(m.default || m.models[0]?.id || ""); }); }, []);
  useEffect(() => { api.ontologyConfig().then((c) => setExPrompt(c.extraction_prompt || "")); }, []);

  // poll an extraction job for real-time progress; refresh graph when done
  const runExtractionJob = async (starter: () => Promise<any>) => {
    try {
      const { job_id } = await starter();
      setJob({ status: "running", phase: "starting", processed: 0, total: 0, entities: 0, edges: 0, id: job_id });
      const tick = async () => {
        const p = await api.ontologyExtractJob(job_id);
        setJob(p);
        if (p.status === "running") setTimeout(tick, 400);
        else {
          const r = p.result || {};
          if (p.status === "cancelled") toast.info(`Extraction cancelled (${r.entities || 0} entities kept)`);
          else if (p.status === "error") toast.error("Extraction failed: " + p.error);
          else toast.success(`Extracted ${r.entities || 0} entities, ${r.edges || 0} edges (${r.method || "?"})`);
          setTimeout(() => setJob(null), 1500);
          refresh();
        }
      };
      tick();
    } catch (e: any) { toast.error(e.message); setJob(null); }
  };

  const refresh = () => {
    api.ontologyReviewQueue(g.id).then(setQueue);
    api.ontologyVersions(g.id).then(setVersions);
    api.ontologyGraphDatastore(g.id).then((d) => setDs({ type: d.type, host: d.host, database: d.database }));
    onChange();
  };
  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [g.id]);

  const addEntity = async () => {
    if (!en.name.trim()) return;
    await api.ontologyAddEntity(g.id, { type: en.type || "Thing", name: en.name });
    setEn({ type: "", name: "" }); refresh();
  };
  const publish = async () => {
    const v = await api.ontologyCreateVersion(g.id);
    try {
      await api.ontologyTransition(v.id, "review");
      await api.ontologyTransition(v.id, "published");
      toast.success("Published"); refresh();
    } catch (e: any) { toast.error(e.message); }
  };

  return (
    <div>
      <Card style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <b>{g.name}</b>
          <div style={{ display: "flex", gap: 6 }}>
            <Button small icon="tick-circle" intent="primary" text="Approve all ≥ 0.8"
              onClick={async () => { const r = await api.ontologyBulkApprove(g.id, 0.8); toast.success(`Approved ${r.approved}`); refresh(); }} />
            <Button small icon="export" text="Export"
              onClick={async () => {
                const snap = await api.ontologyExport(g.id);
                const blob = new Blob([JSON.stringify(snap, null, 2)], { type: "application/json" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url; a.download = `${g.name.replace(/\s+/g, "_")}_ontology.json`; a.click();
                URL.revokeObjectURL(url); toast.success("Exported ontology snapshot");
              }} />
            <label className="bp5-button bp5-small" style={{ cursor: "pointer" }}>
              <span className="bp5-button-text">Import</span>
              <input type="file" accept="application/json" style={{ display: "none" }}
                onChange={(e) => {
                  const file = e.target.files?.[0]; if (!file) return;
                  const reader = new FileReader();
                  reader.onload = async () => {
                    try {
                      const snap = JSON.parse(reader.result as string);
                      const gph = await api.ontologyImport(snap);
                      toast.success(`Imported as "${gph.name}"`); onChange();
                    } catch (err: any) { toast.error("Import failed: " + err.message); }
                  };
                  reader.readAsText(file); (e.target as HTMLInputElement).value = "";
                }} />
            </label>
            <Button small icon="cloud-upload" intent="success" text="Publish" onClick={publish} />
          </div>
        </div>
      </Card>

      <Card style={{ marginBottom: 12, padding: 12 }}>
        <div className="section-head" style={{ marginBottom: 8 }}>
          <div><h2 style={{ fontSize: 16 }}>Knowledge graph</h2>
            <span className="muted" style={{ fontSize: 12 }}>Drag to pan · scroll to zoom · click a node to focus · double-click to expand</span></div>
        </div>
        <GraphCanvas gid={g.id} />
      </Card>

      <Card style={{ marginBottom: 12 }}>
        <b>Add entity (authoring)</b>
        <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "flex-end" }}>
          <FormGroup label="Type" style={{ marginBottom: 0 }}>
            <InputGroup value={en.type} onChange={(e) => setEn({ ...en, type: e.target.value })} placeholder="Supplier" /></FormGroup>
          <FormGroup label="Name" style={{ marginBottom: 0 }}>
            <InputGroup value={en.name} onChange={(e) => setEn({ ...en, name: e.target.value })} placeholder="Acme Corp" /></FormGroup>
          <Button icon="add" text="Add" onClick={addEntity} />
        </div>
      </Card>

      <Card style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <b>Review queue ({queue.length})</b>
        </div>
        {queue.length === 0 ? <div className="muted" style={{ marginTop: 6 }}>Nothing pending review.</div> : (
          <HTMLTable compact style={{ width: "100%", marginTop: 6 }}>
            <thead><tr><th>Kind</th><th>Name / relation</th><th>Conf.</th><th>Status</th><th></th></tr></thead>
            <tbody>{queue.map((it) => (
              <tr key={it.id}>
                <td><Tag minimal>{it._kind}</Tag></td>
                <td>{it.name || it.relation}</td>
                <td className="metric">{(it.confidence ?? 1).toFixed(2)}</td>
                <td className="muted">{it.status}</td>
                <td>
                  <Button small minimal intent="success" icon="tick"
                    onClick={async () => { await api.ontologySetItemStatus(it._kind, it.id, "approved"); refresh(); }} />
                  <Button small minimal intent="danger" icon="cross"
                    onClick={async () => { await api.ontologySetItemStatus(it._kind, it.id, "rejected"); refresh(); }} />
                </td>
              </tr>))}</tbody>
          </HTMLTable>
        )}
      </Card>

      <Card style={{ marginBottom: 12 }}>
        <b>Auto-extract (Stage 1)</b>
        <div className="muted" style={{ fontSize: 12, margin: "2px 0 8px" }}>
          {g.authoring_mode === "manual"
            ? "Manual mode — auto-extraction is disabled; author entities above."
            : "The LLM builds the ontology & taxonomy for you — pick the model, add optional instructions, then extract from text, rows, or a file. Everything lands as review candidates."}
        </div>
        {g.authoring_mode !== "manual" && (
          <>
            <div style={{ display: "flex", gap: 10, alignItems: "flex-end", marginBottom: 10, flexWrap: "wrap" }}>
              <FormGroup label="Model" style={{ margin: 0, minWidth: 220 }}
                helperText={models.has_models ? "The LLM that will build the graph" : "No models — add one in Model Endpoints"}>
                <HTMLSelect fill value={modelId} disabled={!models.has_models}
                  onChange={(e) => setModelId(e.target.value)}
                  options={models.has_models
                    ? models.models.map((m: any) => ({ label: `${m.name} (${m.model})`, value: m.id }))
                    : [{ label: "no models configured", value: "" }]} />
              </FormGroup>
              <Button minimal small icon="star" text="Set as default"
                disabled={!modelId} onClick={async () => { await api.ontologySetConfig({ extraction_model: modelId });
                  toast.success("Default extraction model saved"); }} />
            </div>
            <div style={{ marginBottom: 10 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <b style={{ fontSize: 13 }}>Extraction prompt (scientific)</b>
                <Tag minimal intent="danger">required</Tag>
                <Button minimal small icon={showPrompt ? "chevron-up" : "chevron-down"}
                  text={showPrompt ? "Hide" : "View / edit"} onClick={() => setShowPrompt(!showPrompt)} />
                <Button minimal small icon="reset" text="Reset to default"
                  onClick={() => api.ontologyConfig().then((c) => setExPrompt(c.extraction_prompt || ""))} />
              </div>
              <div className="muted" style={{ fontSize: 11, margin: "2px 0" }}>
                This scientific prompt drives extraction. Placeholders <code>{"{text}"}</code> (source)
                and <code>{"{instructions}"}</code> (your notes below) are required. Edit to tune.
              </div>
              <Collapse isOpen={showPrompt}>
                <TextArea fill rows={12} value={exPrompt} style={{ fontFamily: "var(--mono)", fontSize: 12 }}
                  onChange={(e) => setExPrompt((e.target as HTMLTextAreaElement).value)} />
                <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
                  <Button small intent="primary" icon="floppy-disk" text="Save as default prompt"
                    onClick={async () => { await api.ontologySetConfig({ extraction_prompt: exPrompt }); toast.success("Extraction prompt saved"); }} />
                  {!exPrompt.includes("{text}") && <Tag intent="danger" minimal>prompt must contain {"{text}"}</Tag>}
                </div>
              </Collapse>
            </div>
            <FormGroup label="Instructions to the LLM (optional)"
              helperText="Extra steering appended to the prompt above, e.g. 'Focus on suppliers and their parent companies; treat products as a separate type.'">
              <TextArea fill rows={2} value={instr} onChange={(e) => setInstr(e.target.value)}
                placeholder="Describe the ontology/taxonomy you want the model to build…" />
            </FormGroup>
            {!models.has_models && (
              <Callout intent="warning" icon="warning-sign" style={{ marginBottom: 10 }}>
                No model configured — extraction will fall back to a basic offline heuristic. Add a model in
                Model Endpoints for real LLM-driven ontology creation.
              </Callout>
            )}
          </>
        )}
        {g.authoring_mode !== "manual" && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
            {job && (
              <div style={{ gridColumn: "span 2", background: "rgba(118,185,0,.06)",
                border: "1px solid var(--border)", borderRadius: 8, padding: 10 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <Spinner size={16} />
                  <b style={{ fontSize: 13 }}>Extracting… {job.phase}</b>
                  <span className="muted" style={{ fontSize: 12 }}>
                    {job.entities || 0} entities · {job.edges || 0} relationships
                    {job.total ? ` · ${job.processed}/${job.total} processed` : ""}
                  </span>
                  <span style={{ flex: 1 }} />
                  <Button small intent="danger" icon="cross" text="Cancel"
                    disabled={job.status !== "running"}
                    onClick={async () => { await api.ontologyCancelExtractJob(job.id); toast.info("Cancelling…"); }} />
                </div>
                <ProgressBar intent="success" value={job.total ? job.processed / job.total : undefined}
                  stripes={job.status === "running"} />
              </div>
            )}
            <div>
              <TextArea fill rows={4} value={txt} onChange={(e) => setTxt(e.target.value)}
                placeholder="Paste text… e.g. 'Acme Corporation supplies Widget Assembly.'" />
              <Button small icon="predictive-analysis" text="Extract from text" style={{ marginTop: 6 }}
                disabled={!!job || !txt.trim()}
                onClick={() => runExtractionJob(() => api.ontologyExtractTextJob(g.id, txt, modelId, instr, "doc", exPrompt)).then(() => setTxt(""))} />
            </div>
            <div>
              <TextArea fill rows={4} value={rowsTxt} onChange={(e) => setRowsTxt(e.target.value)}
                placeholder='Structured rows JSON: {"table":"suppliers","rows":[{"id":"s1","name":"Acme"}]}' />
              <Button small icon="th" text="Extract from rows" style={{ marginTop: 6 }}
                onClick={async () => { try { const p = JSON.parse(rowsTxt);
                  const r = await api.ontologyExtractStructured(g.id, p.table || "rows", p.rows || []);
                  toast.success(`Created ${r.entities} entities, ${r.edges} edges`); setRowsTxt(""); refresh(); }
                  catch { toast.error("Rows must be valid JSON"); } }} />
            </div>
            <div style={{ gridColumn: "span 2", borderTop: "1px solid var(--border)", paddingTop: 8 }}>
              <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
                Or extract from a file (upload a .txt/.docx to File Storage first, then give its path):
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <label className="bp5-button bp5-small" style={{ cursor: "pointer" }}>
                  <span>Upload file…</span>
                  <input type="file" style={{ display: "none" }} onChange={(e) => {
                    const file = e.target.files?.[0]; if (!file) return;
                    const reader = new FileReader();
                    reader.onload = async () => {
                      const b64 = (reader.result as string).split(",")[1];
                      await api.filesUpload(file.name, "shared/ontology", b64);
                      setFilePath(`shared/ontology/${file.name}`);
                      toast.success(`Uploaded to shared/ontology/${file.name}`);
                    };
                    reader.readAsDataURL(file); (e.target as HTMLInputElement).value = "";
                  }} />
                </label>
                <InputGroup fill value={filePath} onChange={(e) => setFilePath(e.target.value)}
                  placeholder="shared/ontology/spec.docx" />
                <Button small icon="predictive-analysis" text="Extract from file"
                  disabled={!!job || !filePath.trim()}
                  onClick={() => runExtractionJob(() => api.ontologyExtractFileJob(g.id, filePath, modelId, instr, exPrompt))} />
              </div>
            </div>
          </div>
        )}
      </Card>


      <Card style={{ marginBottom: 12 }}>
        <b>Per-graph datastore (optional override)</b>
        <div className="muted" style={{ fontSize: 12, margin: "2px 0 8px" }}>
          Point this graph at its own store, or leave blank to use the default. Front-end driven, hot-applied.
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
          <FormGroup label="Type" style={{ marginBottom: 0 }}>
            <HTMLSelect value={ds.type} onChange={(e) => setDs({ ...ds, type: e.target.value })}
              options={["json", "postgres"]} /></FormGroup>
          <FormGroup label="Host" style={{ marginBottom: 0 }}>
            <InputGroup value={ds.host || ""} onChange={(e) => setDs({ ...ds, host: e.target.value })}
              disabled={ds.type === "json"} /></FormGroup>
          <FormGroup label="Database" style={{ marginBottom: 0 }}>
            <InputGroup value={ds.database || ""} onChange={(e) => setDs({ ...ds, database: e.target.value })}
              disabled={ds.type === "json"} /></FormGroup>
          <Button text="Save override" onClick={async () => {
            const r = await api.ontologySaveGraphDatastore(g.id, ds.type === "json" ? {} : ds);
            toast.success("Saved (" + (r.datastore._source || "default") + ")"); }} />
        </div>
      </Card>

      <Card>
        <b>Versions & rollback</b>
        {versions.length === 0 ? <div className="muted" style={{ marginTop: 6 }}>No versions yet.</div> : (
          <HTMLTable compact style={{ width: "100%", marginTop: 6 }}>
            <thead><tr><th>Version</th><th>State</th><th>By</th><th></th></tr></thead>
            <tbody>{versions.map((v) => (
              <tr key={v.id}>
                <td className="metric" style={{ fontSize: 11 }}>{v.id}</td>
                <td><Tag minimal intent={v.state === "published" ? "success" : "none"}>{v.state}</Tag></td>
                <td className="muted">{v.created_by}</td>
                <td>{v.state === "archived" && <Button small minimal icon="undo" text="Rollback"
                  onClick={async () => { await api.ontologyRollback(g.id, v.id); toast.success("Rolled back"); refresh(); }} />}</td>
              </tr>))}</tbody>
          </HTMLTable>
        )}
      </Card>
    </div>
  );
}

function Telemetry() {
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => { api.ontologyTelemetry().then(setRows); const t = setInterval(() => api.ontologyTelemetry().then(setRows), 4000); return () => clearInterval(t); }, []);
  return (
    <div style={{ paddingTop: 12 }}>
      <Callout icon="chart" style={{ marginBottom: 12 }}>
        Per-request record of which provider grounded each agent step (spec §7) — proves the toggle and
        helps compare ontology vs plain.
      </Callout>
      {rows.length === 0 ? <div className="muted">No runs recorded yet.</div> : (
        <HTMLTable compact striped style={{ width: "100%" }}>
          <thead><tr><th>Run</th><th>Agent</th><th>Provider</th><th>Ontology used</th><th>Entities</th></tr></thead>
          <tbody>{rows.map((r, i) => (
            <tr key={i}>
              <td className="metric" style={{ fontSize: 11 }}>{r.run_id}</td>
              <td>{r.agent}</td>
              <td><Tag minimal intent={r.provider === "ontology" ? "success" : "none"}>{r.provider}</Tag></td>
              <td>{r.ontology_used ? "yes" : "no"}</td>
              <td className="metric">{r.entities}</td>
            </tr>))}</tbody>
        </HTMLTable>
      )}
    </div>
  );
}
