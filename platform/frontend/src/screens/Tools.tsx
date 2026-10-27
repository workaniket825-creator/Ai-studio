import { useEffect, useState } from "react";
import { Button, Callout, Card, FileInput, InputGroup, Tag, TextArea, FormGroup, Tabs, Tab, Dialog, DialogBody, HTMLSelect } from "@blueprintjs/core";
import { api } from "../api/client";
import { toast } from "../components/toaster";

const SAMPLE = JSON.stringify({
  openapi: "3.0.0",
  info: { title: "ERP API", description: "Invoices & payments" },
  servers: [{ url: "https://api.example.com" }],
  paths: {
    "/invoices": { get: { operationId: "getInvoices", summary: "List invoices" } },
    "/invoices/{id}": { get: { operationId: "getInvoice", summary: "Get an invoice" } },
    "/payments": { post: { operationId: "createPayment", summary: "Create a payment" } },
  },
}, null, 2);

const SAMPLE_PARAMS = JSON.stringify({
  type: "object",
  properties: { city: { type: "string", description: "City name" } },
  required: ["city"],
}, null, 2);

export function Tools() {
  const [tools, setTools] = useState<any[]>([]);
  const [testing, setTesting] = useState<any>(null);
  const [editing, setEditing] = useState<any>(null);
  const refresh = () => api.listTools().then(setTools);
  useEffect(() => { refresh(); }, []);

  return (
    <div>
      <div className="section-head">
        <div><h2>Tool Registry</h2><span className="muted">Functions & APIs agents can call at run time</span></div>
      </div>

      <Callout icon="info-sign" intent="primary" style={{ marginBottom: 16 }}>
        Register a tool here, then grant it to an agent on the <b>Tools</b> step of the agent
        wizard. At run time the model can call granted tools. <b>OpenAPI</b> operations call the
        real API; <b>function</b> tools call your <b>webhook URL</b> (if provided).
      </Callout>

      <Card style={{ marginBottom: 16 }}>
        <Tabs id="tool-tabs" defaultSelectedTabId="fn">
          <Tab id="fn" title="Function tool" panel={<FunctionForm onDone={refresh} />} />
          <Tab id="api" title="REST API (OpenAPI)" panel={<OpenApiForm onDone={refresh} />} />
        </Tabs>
      </Card>

      <b>Registered tools ({tools.length})</b>
      <div className="garden-grid" style={{ marginTop: 10 }}>
        {tools.length === 0 && <div className="muted">No tools yet — register one above.</div>}
        {tools.map((t) => (
          <div className="agent-card" key={t.id}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <b>{t.name}</b><Tag minimal intent={t.type === "openapi" ? "primary" : "none"}>{t.type}</Tag>
            </div>
            <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>{t.description}</div>
            {t.type === "function" && t.spec?.webhook_url && (
              <div className="muted metric" style={{ fontSize: 11, marginTop: 4 }}>→ {t.spec.webhook_url}</div>)}
            {t.type === "function" && !t.spec?.webhook_url && (
              <Tag minimal intent="warning" style={{ marginTop: 6 }}>declaration only — add a webhook to call it</Tag>)}
            {t.operations?.length > 0 && (
              <div className="chip-row">
                {t.operations.slice(0, 6).map((o: string) => <Tag key={o} minimal className="metric">{o}</Tag>)}
              </div>
            )}
            <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
              <Button small icon="pulse" text="Test" onClick={() => setTesting(t)} />
              <Button small minimal icon="edit" text="Edit" onClick={() => setEditing(t)} />
              <Button small minimal intent="danger" icon="trash"
                onClick={async () => { if (confirm(`Delete tool "${t.name}"?`)) { await api.deleteTool(t.id); toast.success("Deleted"); refresh(); } }} />
            </div>
          </div>
        ))}
      </div>

      <TestToolDialog tool={testing} onClose={() => setTesting(null)} />
      <EditToolDialog tool={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); refresh(); }} />
    </div>
  );
}

function TestToolDialog({ tool, onClose }: { tool: any; onClose: () => void }) {
  const [op, setOp] = useState("");
  const [argsText, setArgsText] = useState("{}");
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setOp(tool?.operations?.[0] || tool?.name || ""); setArgsText("{}"); setResult(null); }, [tool]);
  if (!tool) return null;
  const run = async () => {
    let args = {}; try { args = JSON.parse(argsText || "{}"); } catch { toast.error("Args must be JSON"); return; }
    setBusy(true);
    try { setResult(await api.testTool(tool.id, op, args)); } catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  };
  return (
    <Dialog isOpen={!!tool} onClose={onClose} title={`Test: ${tool.name}`} style={{ width: 600 }}>
      <DialogBody>
        <Callout style={{ marginBottom: 10 }}>Execute this tool directly to verify it works — no agent needed.</Callout>
        {tool.type === "openapi" && (
          <FormGroup label="Operation">
            <HTMLSelect fill value={op} onChange={(e) => setOp(e.target.value)}
              options={(tool.operations || []).map((o: string) => ({ label: o, value: o }))} /></FormGroup>
        )}
        <FormGroup label="Arguments (JSON)" helperText='e.g. {"customer_id":"C1001"} or {"query":{...}}'>
          <TextArea fill rows={3} value={argsText} onChange={(e) => setArgsText(e.target.value)}
            style={{ fontFamily: "var(--mono)", fontSize: 12 }} /></FormGroup>
        <Button intent="primary" icon="play" text="Run test" loading={busy} onClick={run} />
        {result && (
          <Callout intent={result.ok ? "success" : "danger"} style={{ marginTop: 12 }}
            title={result.ok ? `Success · ${result.elapsed_ms}ms` : `Failed · ${result.elapsed_ms ?? ""}ms`}>
            <pre style={{ whiteSpace: "pre-wrap", fontSize: 11, maxHeight: 240, overflow: "auto" }}>
              {result.result || result.detail}</pre>
          </Callout>
        )}
      </DialogBody>
    </Dialog>
  );
}

function EditToolDialog({ tool, onClose, onSaved }: { tool: any; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(""); const [desc, setDesc] = useState("");
  const [webhook, setWebhook] = useState(""); const [token, setToken] = useState("");
  const [specText, setSpecText] = useState(""); const [specErr, setSpecErr] = useState("");
  useEffect(() => {
    if (!tool) return;
    setName(tool.name || ""); setDesc(tool.description || "");
    setWebhook(tool.spec?.webhook_url || ""); setToken(tool.spec?.auth_token || ""); setSpecErr("");
    if (tool.type === "openapi") {
      // fetch the full editable OpenAPI document
      api.getTool(tool.id).then((full: any) =>
        setSpecText(JSON.stringify(full.spec_document || {}, null, 2))).catch(() => {});
    }
  }, [tool]);
  if (!tool) return null;
  const save = async () => {
    const patch: any = { name, description: desc };
    if (tool.type === "function") patch.webhook_url = webhook;
    if (tool.type === "openapi") {
      patch.auth_token = token;
      if (specText.trim()) {
        try { patch.spec_document = JSON.parse(specText); }
        catch (e: any) { setSpecErr("Invalid JSON: " + e.message); return; }
      }
    }
    try { await api.updateTool(tool.id, patch); toast.success("Tool updated"); onSaved(); }
    catch (e: any) { setSpecErr(e.message); }
  };
  return (
    <Dialog isOpen={!!tool} onClose={onClose} title={`Edit: ${tool.name}`}
      style={{ width: tool.type === "openapi" ? 720 : 560 }}>
      <DialogBody>
        <FormGroup label="Name"><InputGroup value={name} onChange={(e) => setName(e.target.value)} /></FormGroup>
        <FormGroup label="Description"><InputGroup value={desc} onChange={(e) => setDesc(e.target.value)} /></FormGroup>
        {tool.type === "function" && (
          <FormGroup label="Webhook URL" helperText="Makes the function callable">
            <InputGroup value={webhook} onChange={(e) => setWebhook(e.target.value)} /></FormGroup>)}
        {tool.type === "openapi" && (
          <>
            <FormGroup label="Bearer token" helperText="Sent as Authorization on calls">
              <InputGroup type="password" value={token} onChange={(e) => setToken(e.target.value)} /></FormGroup>
            <FormGroup label="OpenAPI specification (full — edit any server, path, parameter, or body)"
              helperText="Editing this re-parses every operation. All parameters are updatable here, not just name/token.">
              <TextArea fill rows={16} style={{ fontFamily: "var(--mono)", fontSize: 12 }}
                value={specText} onChange={(e) => setSpecText(e.target.value)} />
            </FormGroup>
            {specErr && <Callout intent="danger" style={{ marginBottom: 10 }}>{specErr}</Callout>}
          </>)}
        <Button intent="primary" icon="floppy-disk" text="Save" onClick={save} />
      </DialogBody>
    </Dialog>
  );
}

function FunctionForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [params, setParams] = useState("");
  const [webhook, setWebhook] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!name.trim()) { toast.error("Name is required"); return; }
    let parsed: any = undefined;
    if (params.trim()) {
      try { parsed = JSON.parse(params); } catch { toast.error("Parameters must be valid JSON schema"); return; }
    }
    setBusy(true);
    try {
      await api.registerFunction(name.trim(), desc.trim(), parsed, webhook.trim() || undefined);
      toast.success(`Registered ${name}`); setName(""); setDesc(""); setParams(""); setWebhook(""); onDone();
    } catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  };

  return (
    <div style={{ paddingTop: 8 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <FormGroup label="Function name" labelInfo="(required)">
          <InputGroup placeholder="get_weather" value={name} onChange={(e) => setName(e.target.value)} />
        </FormGroup>
        <FormGroup label="Webhook URL" helperText="POST target that runs the function (optional)">
          <InputGroup placeholder="https://your-service/tools/get_weather" value={webhook}
            onChange={(e) => setWebhook(e.target.value)} />
        </FormGroup>
      </div>
      <FormGroup label="Description" helperText="Tell the model when to use this tool">
        <InputGroup placeholder="Get the current weather for a city" value={desc}
          onChange={(e) => setDesc(e.target.value)} />
      </FormGroup>
      <FormGroup label="Parameters (JSON Schema, optional)">
        <TextArea fill rows={6} style={{ fontFamily: "var(--mono)", fontSize: 12 }}
          placeholder={SAMPLE_PARAMS} value={params} onChange={(e) => setParams(e.target.value)} />
      </FormGroup>
      <Button minimal small text="Load sample params" onClick={() => setParams(SAMPLE_PARAMS)} />
      <div style={{ marginTop: 10 }}>
        <Button intent="primary" icon="add" text="Register function" loading={busy} onClick={save} />
      </div>
    </div>
  );
}

function OpenApiForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [spec, setSpec] = useState("");
  const [token, setToken] = useState("");
  const [ops, setOps] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    file.text().then((t) => { setSpec(t); if (!name) setName(file.name.replace(/\.[^.]+$/, "")); });
  };
  const upload = async () => {
    setOps(null); setBusy(true);
    try {
      const res = await api.registerOpenApi(name || "API", spec, token.trim() || undefined);
      setOps(res.operations); onDone(); toast.success(`${res.operations.length} operations registered`);
    } catch { toast.error("Could not parse that spec as JSON or YAML."); } finally { setBusy(false); }
  };

  return (
    <div style={{ paddingTop: 8 }}>
      <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
        <InputGroup placeholder="Tool name" value={name} onChange={(e) => setName(e.target.value)} />
        <FileInput text="Choose spec file…" onInputChange={onFile} />
        <Button minimal text="Load sample" onClick={() => { setSpec(SAMPLE); setName("ERP API"); }} />
      </div>
      <FormGroup label="Bearer token" helperText="Optional — sent as Authorization header when calling the API">
        <InputGroup type="password" placeholder="token" value={token} onChange={(e) => setToken(e.target.value)} />
      </FormGroup>
      <TextArea fill rows={7} style={{ fontFamily: "var(--mono)", fontSize: 12 }}
        placeholder="Paste OpenAPI JSON/YAML here… (include servers[].url so operations are callable)"
        value={spec} onChange={(e) => setSpec(e.target.value)} />
      <div style={{ marginTop: 10 }}>
        <Button intent="primary" icon="cloud-upload" text="Parse & register" loading={busy}
          onClick={upload} disabled={!spec.trim()} />
      </div>
      {ops && (
        <Callout intent="success" icon="tick" style={{ marginTop: 10 }} title={`${ops.length} operations registered`}>
          {ops.map((o) => (
            <div key={o.operationId} style={{ fontFamily: "var(--mono)", fontSize: 12 }}>
              <Tag minimal intent="primary">{o.method}</Tag> {o.path} — {o.summary}
            </div>
          ))}
        </Callout>
      )}
    </div>
  );
}
