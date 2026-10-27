import { useEffect, useState } from "react";
import { Card, Button, Tag, InputGroup, HTMLSelect, FormGroup, Callout, HTMLTable, NonIdealState } from "@blueprintjs/core";
import { api } from "../api/client";
import { toast } from "../components/toaster";

const PROVIDERS = [
  { label: "Azure OpenAI (AI Foundry)", value: "azure" },
  { label: "OpenAI", value: "openai" },
  { label: "Mistral", value: "mistral" },
  { label: "Gemini", value: "gemini" },
  { label: "Azure AI Document Intelligence (OCR)", value: "azure_docai" },
  { label: "Google Cloud Document AI (OCR)", value: "google_docai" },
];

const TYPES = [
  { label: "Chat / completion", value: "chat" },
  { label: "Embedding (for RAG)", value: "embedding" },
  { label: "Multimodal / vision", value: "multimodal" },
  { label: "OCR / document parsing", value: "ocr" },
  { label: "Rerank", value: "rerank" },
];

const BLANK = { label: "", provider: "azure", type: "chat", model: "", api_base: "", api_version: "2024-08-01-preview", api_key: "" };

export function ModelEndpoints() {
  const [eps, setEps] = useState<any[]>([]);
  const [f, setF] = useState<any>({ ...BLANK });
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string) => setF((p: any) => ({ ...p, [k]: v }));
  const refresh = () => api.listEndpoints().then(setEps);
  useEffect(() => { refresh(); }, []);

  const isAzure = f.provider === "azure";
  const isOpenAI = f.provider === "openai";
  const isDocAI = f.provider === "azure_docai" || f.provider === "google_docai";

  const save = async () => {
    if (!f.model || !f.api_key) { toast.error("Model/deployment and API key are required"); return; }
    setBusy(true);
    try { const ep = await api.addEndpoint(f); toast.success(`Saved ${ep.label}`); setF({ ...BLANK }); refresh(); }
    catch (e: any) { toast.error(e.message); } finally { setBusy(false); }
  };
  const test = async (id: string) => {
    const r = await api.testEndpoint(id);
    r.ok ? toast.success(r.detail) : toast.error(r.detail);
  };
  const del = async (id: string) => { if (confirm("Delete this model endpoint?")) { await api.deleteEndpoint(id); refresh(); } };

  return (
    <div style={{ maxWidth: 980 }}>
      <div className="section-head">
        <div><h2>Model Endpoints</h2><span className="muted">Connect LLM endpoints (Azure AI Foundry, OpenAI, Mistral, Gemini)</span></div>
      </div>

      <Callout icon="info-sign" intent="primary" style={{ marginBottom: 16 }}>
        Add an endpoint here, <b>Test</b> it, then pick it in <b>Agent Garden → Create agent → Model</b>.
        Keys are stored server-side and shown masked. Live calls require the backend started with
        <code> RUNTIME=adk</code> and <code>litellm</code> installed.
      </Callout>

      <Card style={{ marginBottom: 18 }}>
        <b>Add a model endpoint</b>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginTop: 12 }}>
          <FormGroup label="Provider">
            <HTMLSelect fill value={f.provider} onChange={(e) => {
              const pv = e.target.value;
              setF((prev: any) => ({ ...prev, provider: pv,
                type: (pv === "azure_docai" || pv === "google_docai") ? "ocr" : prev.type }));
            }} options={PROVIDERS} />
          </FormGroup>
          <FormGroup label="Type / capability" helperText="RAG uses this to show the right endpoints per stage.">
            <HTMLSelect fill value={f.type} onChange={(e) => set("type", e.target.value)} options={TYPES} />
          </FormGroup>
          <FormGroup label="Display name">
            <InputGroup value={f.label} placeholder="Azure GPT-4o mini (prod)" onChange={(e) => set("label", e.target.value)} />
          </FormGroup>
          <FormGroup label={isDocAI ? "Model / processor (optional)" : isAzure ? "Deployment name" : "Model id"} labelInfo={isDocAI ? "" : "(required)"}>
            <InputGroup value={f.model} placeholder={isDocAI ? "prebuilt-read" : isAzure ? "gpt-4o-mini (your deployment)" : "gpt-4o-mini"}
              onChange={(e) => set("model", e.target.value)} />
          </FormGroup>
          <FormGroup label="API key" labelInfo="(required)">
            <InputGroup type="password" value={f.api_key} placeholder="paste your key"
              onChange={(e) => set("api_key", e.target.value)} />
          </FormGroup>
          {(isAzure || isOpenAI || isDocAI) && (
            <FormGroup label={isDocAI ? "Service endpoint (api_base)" : isAzure ? "Azure endpoint (api_base)" : "Base URL (optional)"}
              labelInfo={isAzure || isDocAI ? "(required)" : ""}>
              <InputGroup value={f.api_base}
                placeholder={f.provider === "azure_docai" ? "https://<resource>.cognitiveservices.azure.com"
                  : f.provider === "google_docai" ? "https://<region>-documentai.googleapis.com/v1/projects/.../processors/...:process"
                  : isAzure ? "https://<resource>.openai.azure.com" : "https://api.openai.com/v1"}
                onChange={(e) => set("api_base", e.target.value)} />
            </FormGroup>
          )}
          {isAzure && (
            <FormGroup label="API version">
              <InputGroup value={f.api_version} placeholder="2024-08-01-preview"
                onChange={(e) => set("api_version", e.target.value)} />
            </FormGroup>
          )}
        </div>
        <Button intent="primary" icon="cloud-upload" text="Save endpoint" loading={busy} onClick={save} />
      </Card>

      {eps.length === 0 ? (
        <NonIdealState icon="cloud" title="No endpoints yet" description="Add one above to make it selectable when creating agents." />
      ) : (
        <Card>
          <b>Configured endpoints</b>
          <HTMLTable compact striped style={{ width: "100%", marginTop: 8 }}>
            <thead><tr><th>Name</th><th>Provider</th><th>Model / deployment</th><th>Endpoint</th><th>Key</th><th></th></tr></thead>
            <tbody>
              {eps.map((e) => (
                <tr key={e.id}>
                  <td>{e.label}</td>
                  <td><Tag minimal intent={e.provider === "azure" ? "primary" : "none"}>{e.provider}</Tag></td>
                  <td className="metric">{e.model}</td>
                  <td className="muted metric" style={{ fontSize: 11 }}>{e.api_base || "—"}</td>
                  <td className="metric">{e.api_key}</td>
                  <td>
                    <Button small minimal icon="pulse" text="Test" onClick={() => test(e.id)} />
                    <Button small minimal icon="trash" onClick={() => del(e.id)} />
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
