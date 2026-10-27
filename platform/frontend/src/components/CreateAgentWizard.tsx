import { useEffect, useState } from "react";
import {
  MultistepDialog, DialogStep, FormGroup, InputGroup, TextArea, HTMLSelect,
  NumericInput, Switch, Tag, Button, Callout, Checkbox,
} from "@blueprintjs/core";
import { api } from "../api/client";

const MODELS = [
  { label: "Mistral · large", value: "mistral-large-latest", provider: "mistral" },
  { label: "Mistral · small", value: "mistral-small-latest", provider: "mistral" },
  { label: "Gemini · 1.5 Flash", value: "gemini-1.5-flash", provider: "gemini" },
  { label: "Gemini · 1.5 Pro", value: "gemini-1.5-pro", provider: "gemini" },
  { label: "Mock (no key)", value: "mock-model", provider: "mock" },
];

export function CreateAgentWizard({ isOpen, onClose, onCreated, editing }:
  { isOpen: boolean; onClose: () => void; onCreated: () => void; editing?: any }) {
  const [f, setF] = useState<any>({
    agent_name: "", role: "", description: "", model: "mistral-large-latest",
    provider: "mistral", endpoint_id: "", system_prompt: "", user_prompt_template: "",
    output_key: "result", temperature: 0.2, collab_role: "standalone",
    memory: false, hitl: false, toolIds: [] as string[],
    fileAccess: false, workspace: "shared",
    useModel: false, modelName: "", toolPolicy: "auto",
    toolOps: {} as Record<string, string[]>,  // toolId -> allowed operationIds ([] = all)
    pipelineIds: [] as string[],               // linked RAG knowledge pipelines
    mcpServerIds: [] as string[],              // linked MCP servers (their tools become callable)
  });
  const [tools, setTools] = useState<any[]>([]);
  const [connectors, setConnectors] = useState<any[]>([]);
  const [endpoints, setEndpoints] = useState<any[]>([]);
  const [pipelines, setPipelines] = useState<any[]>([]);
  const [mcpServers, setMcpServers] = useState<any[]>([]);
  const set = (k: string, v: any) => setF((p: any) => ({ ...p, [k]: v }));

  useEffect(() => {
    if (isOpen) {
      api.listTools().then(setTools);
      api.enabledConnectors().then(setConnectors).catch(() => setConnectors([]));
      api.listEndpoints().then(setEndpoints).catch(() => setEndpoints([]));
      api.ragList().then((ps: any[]) => setPipelines(ps.filter((p) => p.status === "ready"))).catch(() => setPipelines([]));
      api.mcpServers().then(setMcpServers).catch(() => setMcpServers([]));
    }
  }, [isOpen]);
  useEffect(() => {
    if (editing) setF({
      agent_name: editing.agent_name, role: editing.role, description: editing.description,
      model: editing.model_config?.model || "mistral-large-latest",
      provider: editing.model_config?.provider || "mistral",
      endpoint_id: editing.model_config?.endpoint_id || "",
      system_prompt: editing.prompts?.system_prompt || "",
      user_prompt_template: editing.prompts?.user_prompt_template || "",
      output_key: editing.io_contract?.output_key || "result",
      temperature: editing.model_config?.temperature ?? 0.2,
      collab_role: editing.collaboration?.role || "standalone",
      memory: editing.memory_config?.enabled || false,
      hitl: editing.guardrails?.human_in_the_loop?.enabled || false,
      toolIds: (editing.tools || []).map((t: any) => t.ref).filter(Boolean),
      fileAccess: (editing.tools || []).some((t: any) => t.type === "file_access"),
      workspace: (editing.tools || []).find((t: any) => t.type === "file_access")?.workspace || "shared",
      useModel: (editing.tools || []).some((t: any) => t.type === "model"),
      modelName: (editing.tools || []).find((t: any) => t.type === "model")?.model_name || "",
      toolPolicy: editing.tool_policy || "auto",
      toolOps: Object.fromEntries((editing.tools || [])
        .filter((t: any) => t.ref && (t.operations || []).length)
        .map((t: any) => [t.ref, t.operations])),
      pipelineIds: (editing.tools || []).filter((t: any) => t.type === "knowledge").map((t: any) => t.ref),
      mcpServerIds: (editing.tools || []).filter((t: any) => t.type === "mcp").map((t: any) => t.ref),
    });
  }, [editing]);

  const submit = async () => {
    const payload = {
      agent_name: f.agent_name, role: f.role || f.agent_name, description: f.description,
      model_config: { model: f.model, provider: f.provider, temperature: f.temperature,
                      endpoint_id: f.endpoint_id || undefined },
      prompts: { system_prompt: f.system_prompt, user_prompt_template: f.user_prompt_template },
      io_contract: { output_key: f.output_key },
      tool_policy: f.toolPolicy || "auto",
      collaboration: { role: f.collab_role },
      memory_config: { enabled: f.memory },
      guardrails: { human_in_the_loop: { enabled: f.hitl } },
      tools: [
        ...f.toolIds.map((id: string) => {
          const t = tools.find((x) => x.id === id);
          const ops = f.toolOps[id] || [];
          return { type: t?.type || "function", ref: id, name: t?.name,
                   ...(ops.length ? { operations: ops } : {}) };
        }),
        ...(f.fileAccess ? [{ type: "file_access", workspace: (f.workspace || "shared").trim() }] : []),
        ...(f.useModel && f.modelName.trim() ? [{ type: "model", model_name: f.modelName.trim() }] : []),
        ...f.pipelineIds.map((pid: string) => {
          const p = pipelines.find((x) => x.id === pid);
          return { type: "knowledge", ref: pid, name: p?.name || "knowledge" };
        }),
        ...f.mcpServerIds.map((sid: string) => {
          const m = mcpServers.find((x) => x.id === sid);
          return { type: "mcp", ref: sid, name: m?.name || "mcp" };
        }),
      ],
    };
    if (editing) await api.updateAgent(editing.agent_id, payload);
    else await api.createAgent({ ...payload, category: "use_case" });
    onCreated(); onClose();
  };

  return (
    <MultistepDialog isOpen={isOpen} onClose={onClose} title={editing ? "Edit agent" : "Create agent"}
      className="bp5-dark" finalButtonProps={{ text: editing ? "Save changes" : "Create agent",
        onClick: submit, disabled: !f.agent_name }}>
      <DialogStep id="identity" title="Identity"
        panel={
          <div style={{ padding: 20 }}>
            <FormGroup label="Name" labelInfo="(required)">
              <InputGroup value={f.agent_name} onChange={(e) => set("agent_name", e.target.value)}
                placeholder="e.g. Contract Analyst" />
            </FormGroup>
            <FormGroup label="Role"><InputGroup value={f.role}
              onChange={(e) => set("role", e.target.value)} placeholder="Senior Contract Analyst" /></FormGroup>
            <FormGroup label="Description" helperText="One line the Designer uses to match this agent">
              <TextArea fill value={f.description} onChange={(e) => set("description", e.target.value)} />
            </FormGroup>
          </div>
        } />
      <DialogStep id="prompts" title="Prompts"
        panel={
          <div style={{ padding: 20 }}>
            <FormGroup label="System prompt" helperText="Behavior, constraints, role">
              <TextArea fill rows={4} value={f.system_prompt}
                onChange={(e) => set("system_prompt", e.target.value)} />
            </FormGroup>
            <FormGroup label="User prompt template" helperText="{placeholders} bind from workflow state">
              <TextArea fill rows={2} value={f.user_prompt_template}
                onChange={(e) => set("user_prompt_template", e.target.value)} />
            </FormGroup>
            <FormGroup label="Output key" helperText="Where this agent writes its result in shared state">
              <InputGroup value={f.output_key} onChange={(e) => set("output_key", e.target.value)} />
            </FormGroup>
          </div>
        } />
      <DialogStep id="model" title="Model"
        panel={
          <div style={{ padding: 20 }}>
            <FormGroup label="Model" helperText="Built-in providers, or an endpoint you configured in Model Endpoints">
              <HTMLSelect fill
                value={f.endpoint_id ? `ep:${f.endpoint_id}` : f.model}
                onChange={(e) => {
                  const v = e.target.value;
                  if (v.startsWith("ep:")) {
                    const ep = endpoints.find((x) => `ep:${x.id}` === v)!;
                    set("endpoint_id", ep.id); set("model", ep.model); set("provider", ep.provider);
                  } else {
                    const m = MODELS.find((x) => x.value === v)!;
                    set("endpoint_id", ""); set("model", m.value); set("provider", m.provider);
                  }
                }}>
                {endpoints.length > 0 && (
                  <optgroup label="Your configured endpoints">
                    {endpoints.map((ep) => (
                      <option key={ep.id} value={`ep:${ep.id}`}>{ep.label} · {ep.provider}</option>
                    ))}
                  </optgroup>
                )}
                <optgroup label="Built-in providers">
                  {MODELS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                </optgroup>
              </HTMLSelect>
            </FormGroup>
            <FormGroup label={`Temperature: ${f.temperature}`}>
              <NumericInput min={0} max={1} stepSize={0.1} value={f.temperature}
                onValueChange={(v) => set("temperature", v)} />
            </FormGroup>
            <Tag minimal icon="cloud">provider: {f.provider}{f.endpoint_id ? " · via endpoint" : ""}</Tag>
          </div>
        } />
      <DialogStep id="tools" title="Tools"
        panel={
          <div style={{ padding: 20 }}>
            <Callout icon="wrench" style={{ marginBottom: 12 }}>
              Grant this agent access to functions or APIs. Register APIs on the Tools screen
              (OpenAPI upload) — they appear here.
            </Callout>
            {tools.length === 0 && <div className="muted">No tools registered yet.</div>}
            {tools.map((t) => {
              const selected = f.toolIds.includes(t.id);
              const ops: string[] = t.operations || [];
              const allowed: string[] = f.toolOps[t.id] || [];
              const isOpenapiMulti = t.type === "openapi" && ops.length > 1;
              return (
                <div key={t.id}>
                  <Switch label={`${t.name} · ${t.type}${ops.length ? ` · ${ops.length} ops` : ""}`}
                    checked={selected}
                    onChange={() => set("toolIds", selected
                      ? f.toolIds.filter((x: string) => x !== t.id) : [...f.toolIds, t.id])} />
                  {selected && isOpenapiMulti && (
                    <div style={{ margin: "-4px 0 8px 28px", paddingLeft: 10, borderLeft: "2px solid var(--border)" }}>
                      <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
                        Allowed operations {allowed.length ? `(${allowed.length} selected)` : "(all — agent may call any)"}:
                      </div>
                      <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 14px" }}>
                        {ops.map((op) => (
                          <Checkbox key={op} label={op} style={{ marginBottom: 2 }}
                            checked={allowed.length === 0 || allowed.includes(op)}
                            onChange={() => {
                              // start from "all" when nothing chosen yet
                              const base = allowed.length ? allowed : ops;
                              const next = base.includes(op) ? base.filter((x) => x !== op) : [...base, op];
                              // if all are selected, store [] (= all, unscoped)
                              set("toolOps", { ...f.toolOps, [t.id]: next.length === ops.length ? [] : next });
                            }} />
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
            {connectors.length > 0 && (
              <>
                <div className="muted" style={{ margin: "12px 0 6px", textTransform: "uppercase",
                  letterSpacing: ".08em", fontSize: 11 }}>ADK connectors (enabled)</div>
                {connectors.map((c) => (
                  <Switch key={c.id} label={`${c.name} · ${c.category}`}
                    checked={f.toolIds.includes(c.id)}
                    onChange={() => set("toolIds", f.toolIds.includes(c.id)
                      ? f.toolIds.filter((x: string) => x !== c.id) : [...f.toolIds, c.id])} />
                ))}
              </>
            )}
            {tools.length === 0 && connectors.length === 0 && (
              <div className="muted" style={{ marginTop: 8 }}>Tip: enable ADK connectors in the Connectors screen to grant out-of-box connectivity.</div>
            )}
            <div className="muted" style={{ margin: "16px 0 6px", textTransform: "uppercase",
              letterSpacing: ".08em", fontSize: 11 }}>Knowledge pipelines (RAG)</div>
            {pipelines.length === 0 ? (
              <div className="muted" style={{ fontSize: 12 }}>No ready pipelines. Build one in RAG Studio, then link it here so the agent can search it.</div>
            ) : (
              <>
                <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>Link an index so the agent can search it (gets a <code>search_knowledge</code> tool):</div>
                {pipelines.map((p) => (
                  <Switch key={p.id} label={`${p.name} · ${p.stats?.chunks || 0} chunks`}
                    checked={f.pipelineIds.includes(p.id)}
                    onChange={() => set("pipelineIds", f.pipelineIds.includes(p.id)
                      ? f.pipelineIds.filter((x: string) => x !== p.id) : [...f.pipelineIds, p.id])} />
                ))}
              </>
            )}
            <div className="muted" style={{ margin: "16px 0 6px", textTransform: "uppercase",
              letterSpacing: ".08em", fontSize: 11 }}>MCP servers</div>
            {mcpServers.length === 0 ? (
              <div className="muted" style={{ fontSize: 12 }}>No MCP servers registered. Add one in <b>MCP Servers</b> (e.g. MLflow), then link it so the agent can call its tools.</div>
            ) : (
              <>
                <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>Link a server so the agent can call its tools automatically (e.g. MLflow trace analysis):</div>
                {mcpServers.map((m) => (
                  <Switch key={m.id} label={`${m.name} · ${m.transport}`}
                    checked={f.mcpServerIds.includes(m.id)}
                    onChange={() => set("mcpServerIds", f.mcpServerIds.includes(m.id)
                      ? f.mcpServerIds.filter((x: string) => x !== m.id) : [...f.mcpServerIds, m.id])} />
                ))}
              </>
            )}
            <div className="muted" style={{ margin: "16px 0 6px", textTransform: "uppercase",
              letterSpacing: ".08em", fontSize: 11 }}>File access</div>
            <Switch label="Let this agent read & write files in a storage folder"
              checked={f.fileAccess} onChange={() => set("fileAccess", !f.fileAccess)} />
            {f.fileAccess && (
              <FormGroup label="Workspace folder"
                helperText="Folder in File Storage the agent reads inputs from and writes outputs to (e.g. shared/invoices). It also gets a create_document tool to generate real .docx/.xlsx/.pdf files here. Cannot access anything outside this folder.">
                <InputGroup value={f.workspace} onChange={(e) => set("workspace", e.target.value)}
                  placeholder="shared" leftIcon="folder-close" />
              </FormGroup>
            )}
            <div className="muted" style={{ margin: "16px 0 6px", textTransform: "uppercase",
              letterSpacing: ".08em", fontSize: 11 }}>Registered ML model (Data Science Lab)</div>
            <Switch label="Let this agent call a registered ML model as a tool"
              checked={f.useModel} onChange={() => set("useModel", !f.useModel)} />
            {f.useModel && (
              <FormGroup label="Model name (Production)"
                helperText="Name of a model promoted to Production in the Data Science Lab registry. Separate from the foundation LLM above; used for specialized predictions.">
                <InputGroup value={f.modelName} onChange={(e) => set("modelName", e.target.value)}
                  placeholder="fraud-classifier" leftIcon="cube" />
              </FormGroup>
            )}
            {(f.toolIds.length > 0 || f.useModel) && (
              <>
                <div className="muted" style={{ margin: "16px 0 6px", textTransform: "uppercase",
                  letterSpacing: ".08em", fontSize: 11 }}>Tool-use policy (determinism)</div>
                <FormGroup helperText="Auto = model decides. Required = it MUST call a tool (no skipping). Force = always call one specific operation by its exact registered name — the most deterministic option, ideal when the agent's job is to call one API.">
                  <HTMLSelect fill value={f.toolPolicy} onChange={(e) => set("toolPolicy", e.target.value)}
                    options={[
                      { label: "Auto — model decides (default)", value: "auto" },
                      { label: "Required — must call a tool", value: "required" },
                      ...f.toolIds.flatMap((id: string) => {
                        const t = tools.find((x) => x.id === id);
                        const ops = t?.operations || [];
                        return ops.length
                          ? ops.map((op: string) => ({ label: `Force: ${op}`, value: `force:${op}` }))
                          : [{ label: `Force: ${t?.name || id}`, value: `force:${t?.name || id}` }];
                      }),
                    ]} />
                </FormGroup>
              </>
            )}
          </div>
        } />
      <DialogStep id="collab" title="Collaboration & memory"
        panel={
          <div style={{ padding: 20 }}>
            <FormGroup label="Collaboration role">
              <HTMLSelect fill value={f.collab_role} onChange={(e) => set("collab_role", e.target.value)}
                options={["standalone", "coordinator", "specialist", "peer"]} />
            </FormGroup>
            <Switch label="Enable long-term memory" checked={f.memory}
              onChange={() => set("memory", !f.memory)} />
            <Switch label="Require human approval for significant actions" checked={f.hitl}
              onChange={() => set("hitl", !f.hitl)} />
          </div>
        } />
    </MultistepDialog>
  );
}
