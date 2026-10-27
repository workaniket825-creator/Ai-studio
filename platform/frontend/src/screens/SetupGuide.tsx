import { useState } from "react";
import { Card, Tag, Button, Callout, Collapse, Icon, Code, Pre } from "@blueprintjs/core";
import { toast } from "../components/toaster";
import { HelpBot } from "./HelpBot";

function Snippet({ code }: { code: string }) {
  const copy = () => { navigator.clipboard?.writeText(code); toast.success("Copied to clipboard"); };
  return (
    <div style={{ position: "relative" }}>
      <Pre style={{ background: "#0c110d", border: "1px solid var(--border)", borderRadius: 8,
        padding: 12, overflow: "auto", fontSize: 12 }}>{code}</Pre>
      <Button small minimal icon="duplicate" onClick={copy}
        style={{ position: "absolute", top: 6, right: 6 }} />
    </div>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(n <= 2);
  return (
    <Card style={{ marginBottom: 12, padding: 0, overflow: "hidden" }}>
      <div onClick={() => setOpen(!open)} style={{ display: "flex", alignItems: "center", gap: 10,
        padding: "12px 16px", cursor: "pointer" }}>
        <Tag round intent="primary" style={{ minWidth: 24, textAlign: "center" }}>{n}</Tag>
        <b style={{ fontSize: 14, flex: 1 }}>{title}</b>
        <Icon icon={open ? "chevron-up" : "chevron-down"} color="var(--muted)" />
      </div>
      <Collapse isOpen={open}><div style={{ padding: "0 16px 16px 50px" }}>{children}</div></Collapse>
    </Card>
  );
}

export function SetupGuide() {
  return (
    <div className="help-scope" style={{ maxWidth: 980, position: "relative", paddingRight: 70 }}>
      <HelpBot />
      <div className="section-head">
        <div><h2>Setup Guide &amp; Help</h2><span className="muted">Everything you need to configure the platform — with examples</span></div>
      </div>

      <Callout intent="success" icon="tick" style={{ marginBottom: 16 }}>
        The platform runs out-of-the-box in <b>mock mode</b> (no keys). Follow the steps below to
        connect real models (Mistral / Gemini), add tools, and map them to agents. All open-source,
        no cloud platform required.
      </Callout>

      <Step n={1} title="Add a model endpoint">
        <p className="muted">Open <b>Model Endpoints</b>, add your LLM connection (Azure OpenAI / OpenAI / Mistral / Gemini), fill the fields, and click <b>Test</b>. It then appears in the Create-Agent wizard's model list. Start the backend with <Code>litellm</Code> installed so live calls work (default runtime is <Code>live</Code>).</p>
        <Snippet code={`# backend
pip install -r requirements.txt      # includes litellm
uvicorn app.main:app --port 8099

# Model Endpoints screen -> Add (example: Azure OpenAI / AI Foundry)
#   Provider:      Azure OpenAI
#   Deployment:    gpt-4o-mini            (your Foundry deployment name)
#   Endpoint:      https://<resource>.openai.azure.com
#   API version:   2024-08-01-preview
#   API key:       <your key>`} />
        <p className="muted" style={{ marginTop: 8 }}>Each agent picks one of these endpoints on its Model step — different agents can use different endpoints.</p>
      </Step>

      <Step n={2} title="Register a function tool (and make it callable)">
        <p className="muted">Go to <b>Tool Registry → Function tool</b>. Give it a clear name and description (the model uses these to decide when to call it) and, optionally, a JSON-Schema for its parameters. To make it actually execute, add a <b>Webhook URL</b> — at run time the platform POSTs the call arguments there and feeds the response back to the model.</p>
        <Snippet code={`POST /api/v1/tools/function
{
  "name": "get_weather",
  "description": "Get the current weather for a city",
  "parameters": {
    "type": "object",
    "properties": { "city": { "type": "string" } },
    "required": ["city"]
  },
  "webhook_url": "https://your-service/tools/get_weather"   // optional but needed to run
}`} />
        <p className="muted" style={{ marginTop: 8 }}>Your webhook receives <Code>{`{"city": "..."}`}</Code> and returns JSON. Without a webhook the tool is a declaration only (the model can reference it but there's nothing to execute).</p>
      </Step>

      <Step n={3} title="Register a REST API (OpenAPI) — callable operations">
        <p className="muted">Go to <b>Tool Registry → REST API (OpenAPI)</b>, click <b>Load sample</b> or paste your spec (JSON/YAML). Each operation becomes a callable tool. <b>Include <Code>servers[].url</Code></b> so operations can be invoked, and add a <b>Bearer token</b> if the API needs auth.</p>
        <Snippet code={`{
  "openapi": "3.0.0",
  "info": { "title": "ERP API", "description": "Invoices & payments" },
  "servers": [{ "url": "https://api.example-erp.com" }],   // REQUIRED for calls
  "paths": {
    "/invoices":      { "get":  { "operationId": "getInvoices",   "summary": "List invoices" } },
    "/invoices/{id}": { "get":  { "operationId": "getInvoice",    "summary": "Get an invoice" } },
    "/payments":      { "post": { "operationId": "createPayment", "summary": "Create a payment" } }
  }
}`} />
        <p className="muted" style={{ marginTop: 8 }}>At run time the model calls an operation, the platform makes the real HTTP request (adding your bearer token), and returns the response to the model.</p>
      </Step>

      <Step n={4} title="Enable a connector (out-of-box connectivity)">
        <p className="muted">Google ADK ships a wide set of connectivity options. Open the <b>Connectors</b> screen, flip a connector on, fill its config, and it becomes selectable on the agent's <b>Tools</b> step. Categories: built-in tools, MCP toolsets, third-party toolkits (LangChain/CrewAI), OpenAPI, and enterprise Application Integration connectors.</p>
        <Snippet code={`# Enable via API (or use the Connectors screen)
POST /api/v1/connectors/google_search/toggle   { "enabled": true }

POST /api/v1/connectors/mcp_postgres/toggle
{ "enabled": true, "config": { "url": "postgresql://user:DUMMY@localhost:5432/app" } }

POST /api/v1/connectors/slack/toggle
{ "enabled": true, "config": { "bot_token": "xoxb-DUMMY-000" } }`} />
        <p className="muted" style={{ marginTop: 8 }}>In the real ADK runtime these map to ADK toolsets, e.g. MCP + built-in tools:</p>
        <Snippet code={`from google.adk.agents import LlmAgent
from google.adk.tools import google_search
from google.adk.tools.mcp_tool import MCPToolset, StdioServerParameters

agent = LlmAgent(
    name="ops_agent", model="gemini-1.5-flash",
    tools=[
        google_search,
        MCPToolset(connection_params=StdioServerParameters(
            command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "/data"])),
    ],
)`} />
        <Callout intent="warning" icon="cloud" style={{ marginTop: 8 }}>
          Connectors marked <b>needs GCP Integration</b> (Salesforce, ServiceNow, Slack, Jira, BigQuery)
          use Application Integration; the rest (built-in, MCP, toolkits, OpenAPI) run with no cloud platform.
        </Callout>
      </Step>

      <Step n={5} title="Map a REST API (or function) to an agent — and verify it calls">
        <p className="muted">Open <b>Agent Garden → Create agent</b> (or <b>Edit</b>). On the <b>Tools</b> step, toggle the functions, APIs, and enabled connectors you want — the agent now has access to them. When the agent runs, it decides when to call each tool and the platform executes the real API and feeds the result back to the model.</p>
        <Snippet code={`POST /api/v1/agents
{
  "agent_name": "Invoice Analyst",
  "model_config": { "provider": "azure", "endpoint_id": "ep_xxxx" },
  "prompts": { "system_prompt": "You analyze invoices. Use the ERP API to look up customers and orders." },
  "io_contract": { "output_key": "invoice_analysis" },
  "tools": [
    { "type": "function", "name": "parse_invoice", "ref": "tool_xxxx" },
    { "type": "openapi",  "name": "ERP API",       "ref": "tool_yyyy" }
  ]
}`} />
        <Callout icon="confirm" intent="success" style={{ margin: "10px 0" }}>
          <b>Make the API reliably callable — 4 things that matter:</b>
          <ol style={{ margin: "6px 0 0 18px", padding: 0 }}>
            <li><b>Good operationId + summary in the OpenAPI spec.</b> The model chooses a tool by its name and summary. "getCustomer — Get a customer by id" works; a blank summary doesn't.</li>
            <li><b>Declared parameters.</b> The platform reads each operation's <i>path, query, and request-body</i> parameters from your spec and exposes them to the model as named, typed fields. If your spec declares <Code>customer_id</Code> as a path parameter, the model fills it correctly. Specs that omit parameters make the model guess — always declare them.</li>
            <li><b>Mention the tool in the agent's system prompt.</b> e.g. "Use the ERP API to look up customers." Models call tools far more reliably when the prompt tells them to.</li>
            <li><b>SSRF allow-list for internal APIs.</b> By default the platform blocks calls to private/internal addresses. If your API is internal (e.g. <Code>10.x</Code> or a corporate host), add its host under <b>Governance → Platform Settings → Allowed internal hosts</b>, or the call is blocked for safety.</li>
          </ol>
        </Callout>
        <p className="muted"><b>Verify before wiring to an agent:</b> on the <b>Tool Registry</b> screen, click <b>Test</b> on the API tool, pick an operation, pass JSON args (e.g. <Code>{`{"customer_id":"C1001"}`}</Code>), and confirm you get a real response. Then test the agent in the <b>Garden</b> — open the run and you'll see a <b>tool call</b> step in the live trace (and a matching span in MLflow if enabled). If the agent answers without a tool-call step, check the 4 points above (usually #3 the prompt, or #4 SSRF for internal hosts).</p>
      </Step>

      <Step n={6} title="Design & run a workflow">
        <p className="muted">In <b>Workflow Studio</b>, type a goal and click <b>Design</b> for a reuse-first graph, or build it manually: click agents in the palette to add them, drag handle-to-handle to connect, select a node to edit, then <b>Save</b> and <b>Plan &amp; run</b>. Or start from a ready-made <b>Template</b>.</p>
        <Snippet code={`POST /api/v1/workflows/design   { "goal": "Extract the sales CSV, find anomalies, email a summary" }
POST /api/v1/runs               { "workflow_id": "wf_xxxx", "input": { "file": "sales.csv" } }
# then open the run to watch the live "thinking" and see agent Output + files`} />
      </Step>

      <Step n={7} title="Enable durable tracing (optional MLflow)">
        <p className="muted">Metrics work locally with zero setup. For durable traces, point at a self-hosted MLflow (open-source):</p>
        <Snippet code={`export OBSERVABILITY=mlflow
export MLFLOW_TRACKING_URI=http://localhost:5000   # local file store or SQL backend
# start MLflow:  mlflow server --host 0.0.0.0 --port 5000`} />
      </Step>

      <Step n={8} title="Tune stability & safety (Governance → Platform Settings)">
        <p className="muted">All platform controls are editable from the UI — no backend edits. Open <b>Governance → Platform Settings</b> to set: <b>max concurrent runs</b>, <b>per-run timeout</b>, <b>retry attempts / backoff</b>, <b>max request size</b>, and the <b>SSRF safety</b> policy. Changes save automatically and apply on the next run.</p>
        <Callout icon="shield" intent="primary" style={{ marginBottom: 8 }}>
          <b>Outbound tool-call safety (SSRF):</b> by default the platform blocks tools/webhooks from calling
          private/internal addresses. Public APIs (like your Azure endpoint) work normally. If a tool must reach
          an internal host, add it under <b>Allowed internal hosts</b>.
        </Callout>
        <Snippet code={`# Optional ops overrides (the UI is the primary source of truth):
export MAX_CONCURRENT_RUNS=8
export RUN_TIMEOUT_SECONDS=240
export RETRY_ATTEMPTS=2
export MAX_REQUEST_KB=512`} />
        <p className="muted" style={{ marginTop: 8 }}>Runs also self-heal: if the server restarts mid-run, those runs are marked failed on the next start (no stuck "running"), and writes are atomic so data can't be corrupted by a crash.</p>
      </Step>

      <Step n={9} title="Data Science Lab — register a GPU runtime (Brev / Azure)">
        <p className="muted">Enable the <b>Data Science Lab</b>, then <b>Add Runtime</b> to register a compute target.
        In the form, fields tagged <span style={{ color: "var(--accent)", fontWeight: 600 }}>required</span> must be filled;
        the rest are optional. Use the <b>Brev sample</b> / <b>Azure sample</b> buttons to prefill typical values, then edit.</p>
        <Callout icon="info-sign" style={{ marginBottom: 8 }}>
          <b>Key parameters:</b> <b>Provider</b> (managed can start/stop; SSH is connect-only) ·
          <b>Host</b> (Brev: instance name; Azure: <Code>{`<resource_group>/<vm_name>`}</Code>; SSH: host/IP) ·
          <b>Region</b> (required for Azure/AWS) · <b>Auth secret reference</b> (a <Code>vault://…</Code> pointer,
          never the raw key) · <b>Runtime image</b> (NGC container) · <b>Idle auto-shutdown</b> (saves cost on managed).
        </Callout>
        <Snippet code={`# Brev (NVIDIA-managed) — example
Name:               Team A100 (Brev)
Provider:           brev
Host:               team-a100-dev        # the Brev instance name
GPU type:           NVIDIA A100 80GB
Region:             us-west-1
Auth secret ref:    vault://brev-token
Idle auto-shutdown: 30

# Azure (managed VM) — example
Name:               GPU-RG / gpu-vm-01 (Azure)
Provider:           azure
Host:               ml-rg/gpu-vm-01      # <resource_group>/<vm_name>
Region:             eastus
Auth secret ref:    vault://azure-sp     # service principal in your vault
Idle auto-shutdown: 45`} />
        <p className="muted" style={{ marginTop: 8 }}>To activate the real ADK/GPU runtime set <Code>RUNTIME=adk</Code>
        and install the optional deps (<Code>google-adk</Code>, provider SDKs). Without them, Test reports honestly
        that the control plane/credentials aren't present — it never fabricates a connection.</p>
      </Step>

      <Step n={10} title="RAG — ingesting PDFs and enabling OCR">
        <p className="muted">Plain text and digital documents (txt, md, html, docx, and PDFs that have a
        text layer) ingest with no extra setup. Scanned PDFs and images need OCR.</p>
        <Callout icon="info-sign" style={{ marginBottom: 8 }}>
          <b>Digital PDFs</b> require <Code>pypdf</Code> (now in the backend image). If a PDF ingests as
          empty, it's usually <b>scanned</b> (no text layer) — enable OCR.
        </Callout>
        <p><b>To OCR scanned PDFs/images, register an OCR endpoint</b> (Model Endpoints → Type = OCR):</p>
        <Snippet code={`# Option A — Azure AI Document Intelligence
Provider:  Azure AI Document Intelligence (OCR)
Type:      OCR / document parsing        # auto-set
api_base:  https://<resource>.cognitiveservices.azure.com
api_key:   <your Document Intelligence key>
model:     prebuilt-read                 # optional

# Option B — Google Cloud Document AI
Provider:  Google Cloud Document AI (OCR)
api_base:  https://<region>-documentai.googleapis.com/v1/projects/<proj>/locations/<loc>/processors/<id>:process
api_key:   <OAuth bearer token>

# Option C — a vision LLM (GPT-4o / Gemini / Mistral vision)
Provider:  OpenAI / Gemini / Mistral
Type:      OCR (or Multimodal)`} />
        <p className="muted" style={{ marginTop: 8 }}>Then in <b>RAG Studio → your pipeline → Configuration →
        Processing</b>, set <b>OCR = API endpoint</b> and pick the endpoint. Ingest the PDF again; the
        index catalog will show <b>Pages OCR'd</b>. Local <Code>tesseract-ocr</Code> also works if installed
        in the image (OCR = Local). Embedding models are configured the same way (Type = Embedding).</p>
      </Step>

      <Step n={11} title="Data Science Lab — SSH connectivity & Auth Ref (detailed)">
        <p className="muted">The <b>Auth Secret Ref</b> tells the backend how to authenticate to the target.
        What to put depends on the provider:</p>
        <Callout icon="key" style={{ marginBottom: 8 }}>
          <b>SSH / on-prem:</b> the absolute path to the VM's private key <b>on the backend host</b>, e.g.
          <Code>/home/app/.ssh/vm.pem</Code> (or a <Code>vault://</Code> ref). The key must be readable by the
          backend process and have <Code>chmod 600</Code> permissions.<br/>
          <b>Brev:</b> <Code>vault://brev-token</Code> or <Code>env:BREV_API_KEY</Code>.<br/>
          <b>Azure:</b> service principal ref <Code>vault://azure-sp</Code> or <Code>env:AZURE_CLIENT_SECRET</Code>.
        </Callout>
        <p><b>SSH setup steps:</b></p>
        <Snippet code={`# 1. Register the runtime (Data Science Lab → Add runtime)
Provider:        SSH / on-prem
Host / IP:       <vm-ip>
SSH user:        ubuntu               # or azureuser
Target Python:   ~/lab/bin/python     # the interpreter that has jupyterlab + papermill

# 2. Upload the key — click 'Upload .pem' on the runtime card and pick your key file.
#    It's stored 0600 on the backend and bound automatically (no manual ~/.ssh copying).

# 3. On the TARGET VM, install the lab server bits on THAT interpreter
~/lab/bin/pip install jupyterlab papermill      # or: python3 -m pip install jupyterlab papermill

# 4. Test → 'SSH auth OK (via uploaded key)'. Open Lab launches JupyterLab on the VM and
#    verifies port 8888 is actually listening before the Workspace tab opens.`} />
        <Callout intent="primary" icon="tick-circle" style={{ marginTop: 8 }}>
          Fixed: you no longer place the key in <Code>~/.ssh</Code> manually — <b>Upload .pem</b> handles it.
          <b> Open Lab</b> now validates JupyterLab is really up on <Code>:8888</Code> (no more "ready" then
          "connection refused"), and <b>Run</b> uses the runtime's <b>Target Python</b> so papermill is found
          on the same interpreter you installed it on.
        </Callout>
        <Callout intent="warning" icon="warning-sign" style={{ marginTop: 8 }}>
          If Open Lab still reports JupyterLab didn't start, check <Code>/tmp/jupyter.log</Code> on the target
          and confirm <Code>&lt;Target Python&gt; -m jupyterlab --version</Code> works there.
        </Callout>
      </Step>

      <Callout icon="lightbulb" title="Try the scenario templates" style={{ marginTop: 8 }}>
        The <b>Templates</b> screen includes <b>Agent Security &amp; Threat Analysis</b> (detects prompt
        injection / jailbreaks / exfiltration and writes an incident report) and <b>Document Processing
        &amp; Synthesis</b> (ingests documents → produces a deliverable file). Run either and open the
        <b> Output</b> tab to read the content and download the generated file.
      </Callout>
    </div>
  );
}
