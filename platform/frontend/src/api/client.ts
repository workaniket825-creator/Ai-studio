// Typed client for the FastAPI contract (spec §18). Vite proxies /api -> :8099.

export interface AgentCard {
  agent_id: string;
  agent_name: string;
  role: string;
  description: string;
  category: string;
  status: string;
  tags: string[];
  model_config: { model: string; provider: string; temperature?: number };
  prompts?: { system_prompt?: string; user_prompt_template?: string };
  io_contract?: { output_key?: string };
  memory_config?: { enabled?: boolean };
  guardrails?: { human_in_the_loop?: { enabled?: boolean } };
  tools: { type: string; name?: string; ref?: string }[];
  collaboration: { role: string };
  version: number;
  metrics: { runs?: number; success_rate?: number | null; avg_cost_usd?: number | null };
}

export interface WorkflowNode {
  node_id: string;
  agent_ref?: string;
  status: string;
  output_key: string;
  input_bindings: Record<string, string>;
}
export interface WorkflowEdge { from: string; to: string; type: string }
export interface Workflow {
  workflow_id: string;
  name: string;
  goal_prompt: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  approval_gates: string[];
}

export interface ActivityEvent {
  run_id: string; seq: number; ts: string; node_id?: string; agent?: string;
  phase: string; kind: string; label: string; level: string;
  token_delta?: number | null; in_tokens?: number | null; out_tokens?: number | null;
}

const base = "/api/v1";
async function j(r: Response) {
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`;
    try { const b = await r.json(); detail = b.detail || detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  return r.json();
}
const send = (p: string, method: string, body?: object) =>
  fetch(`${base}${p}`, { method, headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined }).then(j);
const getJson = (p: string) => fetch(`${base}${p}`).then(j);

export const api = {
  health: () => fetch(`${base}/health`).then(j),

  // agents (Phase 1)
  listAgents: (q = ""): Promise<AgentCard[]> =>
    fetch(`${base}/agents${q ? `?q=${encodeURIComponent(q)}` : ""}`).then(j),
  getAgent: (id: string): Promise<AgentCard> => fetch(`${base}/agents/${id}`).then(j),
  createAgent: (card: object) => send("/agents", "POST", card),
  updateAgent: (id: string, patch: object) => send(`/agents/${id}`, "PATCH", patch),
  cloneAgent: (id: string) => send(`/agents/${id}/clone`, "POST"),
  deprecateAgent: (id: string) => send(`/agents/${id}/deprecate`, "POST"),
  deleteAgent: (id: string) => send(`/agents/${id}`, "DELETE"),
  testAgent: (id: string, input: object = {}) => send(`/agents/${id}/test`, "POST", { input }),

  // tools (Phase 1)
  listTools: () => fetch(`${base}/tools`).then(j),
  registerOpenApi: (name: string, spec: string, auth_token?: string) =>
    send("/tools/openapi", "POST", { name, spec, auth_token }),
  registerFunction: (name: string, description: string, parameters?: object, webhook_url?: string) =>
    send("/tools/function", "POST", { name, description, parameters, webhook_url }),
  registerBuiltin: (name: string, description: string) =>
    send("/tools/builtin", "POST", { name, description }),
  updateTool: (id: string, patch: object) => send(`/tools/${id}`, "PUT", patch),
  getTool: (id: string) => fetch(`${base}/tools/${id}`).then(j),
  deleteTool: (id: string) => send(`/tools/${id}`, "DELETE"),
  testTool: (id: string, operationId: string, args: object) => send(`/tools/${id}/test`, "POST", { operationId, args }),

  // workflows (Phase 3)
  listWorkflows: (): Promise<Workflow[]> => fetch(`${base}/workflows`).then(j),
  getWorkflow: (id: string): Promise<Workflow> => fetch(`${base}/workflows/${id}`).then(j),
  createWorkflow: (wf: object) => send("/workflows", "POST", wf),
  updateWorkflow: (id: string, patch: object) => send(`/workflows/${id}`, "PATCH", patch),
  designWorkflow: (goal: string): Promise<Workflow> => send("/workflows/design", "POST", { goal }),
  planWorkflow: (id: string) => send(`/workflows/${id}/plan`, "POST"),
  validateWorkflow: (id: string) => send(`/workflows/${id}/validate`, "POST"),
  materializeNode: (wid: string, nid: string) =>
    send(`/workflows/${wid}/nodes/${nid}/materialize`, "POST"),

  // runs
  startRun: (workflow_id: string, input: object = {}, ontology_hops = 1) =>
    send("/runs", "POST", { workflow_id, input, ontology_hops }),
  getRun: (id: string) => fetch(`${base}/runs/${id}`).then(j),
  listRuns: () => fetch(`${base}/runs`).then(j),
  approve: (id: string) => send(`/approvals/${id}/approve`, "POST"),
  reject: (id: string) => send(`/approvals/${id}/reject`, "POST"),
  cancelRun: (id: string) => send(`/runs/${id}/cancel`, "POST"),

  // monitoring (Phase 2)
  metricsOverview: () => fetch(`${base}/metrics/overview`).then(j),
  getTrace: (runId: string) => fetch(`${base}/traces/${runId}`).then(j),
  feedback: (runId: string, vote: "up" | "down", comment = "") =>
    send(`/runs/${runId}/feedback`, "POST", { vote, comment }),

  // Phase 4 — learnings layer
  steer: (runId: string, text: string) => send(`/runs/${runId}/steer`, "POST", { text }),
  listBundles: () => fetch(`${base}/bundles`).then(j),
  installBundle: (id: string) => send(`/bundles/${id}/install`, "POST"),
  listSchedules: () => fetch(`${base}/schedules`).then(j),
  createSchedule: (workflow_id: string, interval_seconds: number) =>
    send("/schedules", "POST", { workflow_id, interval_seconds }),
  toggleSchedule: (id: string, enabled: boolean) => send(`/schedules/${id}`, "PATCH", { enabled }),
  deleteSchedule: (id: string) => send(`/schedules/${id}`, "DELETE"),
  triggerSchedule: (id: string) => send(`/schedules/${id}/trigger`, "POST"),

  // Phase 5 — governance
  governance: () => fetch(`${base}/governance`).then(j),
  updateGovernance: (patch: object) => send("/governance", "PUT", patch),
  compressionConfig: () => fetch(`${base}/chat/compression-config`).then(j),
  chatCompress: (turns: object[]) => send("/chat/compress", "POST", { turns }),
  audit: () => fetch(`${base}/audit`).then(j),
  observabilityStatus: () => fetch(`${base}/observability/status`).then(j),
  platformSettings: () => fetch(`${base}/platform-settings`).then(j),
  updatePlatformSettings: (patch: object) => send("/platform-settings", "PUT", patch),

  // ontology intelligence layer
  ontologyConfig: () => fetch(`${base}/ontology/config`).then(j),
  ontologyDatastore: () => fetch(`${base}/ontology/datastore`).then(j),
  ontologyTestDatastore: (conn: object) => send("/ontology/datastore/test", "POST", conn),
  ontologySaveDatastore: (conn: object) => send("/ontology/datastore", "PUT", conn),
  ontologyEnableWorkflow: (wf: string, enabled: boolean) => send(`/ontology/enable/workflow/${wf}`, "POST", { enabled }),
  ontologyEnableTenant: (t: string, enabled: boolean) => send(`/ontology/enable/tenant/${t}`, "POST", { enabled }),
  ontologyGraphs: () => fetch(`${base}/ontology/graphs`).then(j),
  ontologyCreateGraph: (body: object) => send("/ontology/graphs", "POST", body),
  ontologyDeleteGraph: (gid: string) => send(`/ontology/graphs/${gid}`, "DELETE"),
  ontologyAddEntity: (gid: string, body: object) => send(`/ontology/graphs/${gid}/entities`, "POST", body),
  ontologyAddEdge: (gid: string, body: object) => send(`/ontology/graphs/${gid}/edges`, "POST", body),
  ontologyReviewQueue: (gid: string) => fetch(`${base}/ontology/graphs/${gid}/review-queue`).then(j),
  ontologyBulkApprove: (gid: string, min_confidence: number) => send(`/ontology/graphs/${gid}/bulk-approve`, "POST", { min_confidence }),
  ontologySetItemStatus: (kind: string, id: string, status: string) => send(`/ontology/items/${kind}/${id}/status`, "POST", { status }),
  ontologyVersions: (gid: string) => fetch(`${base}/ontology/graphs/${gid}/versions`).then(j),
  ontologyCreateVersion: (gid: string) => send(`/ontology/graphs/${gid}/versions`, "POST"),
  ontologyTransition: (vid: string, state: string) => send(`/ontology/versions/${vid}/transition`, "POST", { state }),
  ontologyRollback: (gid: string, version_id: string) => send(`/ontology/graphs/${gid}/rollback`, "POST", { version_id }),
  ontologyGraphView: (gid: string, q = "", status = "") => fetch(`${base}/ontology/graphs/${gid}/view?q=${encodeURIComponent(q)}${status ? `&status=${status}` : ""}`).then(j),
  ontologyExtractFile: (gid: string, path: string) => send(`/ontology/graphs/${gid}/extract/file`, "POST", { path }),
  ontologyUpdateEntity: (eid: string, patch: object) => send(`/ontology/entities/${eid}`, "PUT", patch),
  ontologyDeleteEntity: (eid: string) => send(`/ontology/entities/${eid}`, "DELETE"),
  ontologyUpdateEdge: (edid: string, patch: object) => send(`/ontology/edges/${edid}`, "PUT", patch),
  ontologyDeleteEdge: (edid: string) => send(`/ontology/edges/${edid}`, "DELETE"),
  ontologyAnalytics: (gid: string) => fetch(`${base}/ontology/graphs/${gid}/analytics`).then(j),
  ontologyModels: () => fetch(`${base}/ontology/models`).then(j),

  // ---- RAG / Knowledge Pipelines ----
  ragList: () => fetch(`${base}/rag/pipelines`).then(j),
  ragGet: (pid: string) => fetch(`${base}/rag/pipelines/${pid}`).then(j),
  ragCreate: (body: object) => send("/rag/pipelines", "POST", body),
  ragUpdate: (pid: string, body: object) => send(`/rag/pipelines/${pid}`, "PUT", body),
  ragDelete: (pid: string) => send(`/rag/pipelines/${pid}`, "DELETE"),
  ragEmbeddingEndpoints: () => fetch(`${base}/rag/embedding-endpoints`).then(j),
  ragPreviewChunking: (text: string, chunking: object) => send("/rag/preview-chunking", "POST", { text, chunking }),
  ragIngest: (pid: string, items: object[]) => send(`/rag/pipelines/${pid}/ingest`, "POST", { items }),
  ragJob: (jobId: string) => fetch(`${base}/rag/jobs/${jobId}`).then(j),
  ragCancelJob: (jobId: string) => send(`/rag/jobs/${jobId}/cancel`, "POST"),
  ragDocuments: (pid: string) => fetch(`${base}/rag/pipelines/${pid}/documents`).then(j),
  ragStats: (pid: string) => fetch(`${base}/rag/pipelines/${pid}/stats`).then(j),
  ragQuery: (pid: string, query: string, top_k = 0) => send(`/rag/pipelines/${pid}/query`, "POST", { query, top_k }),
  ontologyExtractTextM: (gid: string, text: string, endpoint_id: string, instructions: string, source = "doc") =>
    send(`/ontology/graphs/${gid}/extract/text`, "POST", { text, endpoint_id, instructions, source }),
  ontologyExtractFileM: (gid: string, path: string, endpoint_id: string, instructions: string) =>
    send(`/ontology/graphs/${gid}/extract/file`, "POST", { path, endpoint_id, instructions }),
  ontologySetConfig: (patch: object) => send("/ontology/config", "PUT", patch),
  ontologyExport: (gid: string) => fetch(`${base}/ontology/graphs/${gid}/export?source=live`).then(j),
  ontologyPublishedGraphs: () => fetch(`${base}/ontology/graphs/published`).then(j),
  ontologySetWorkflowGraph: (workflow_id: string, graph_id: string) =>
    send("/ontology/workflow-graph", "PUT", { workflow_id, graph_id }),
  ontologyImport: (snapshot: object) => send("/ontology/import", "POST", { snapshot }),
  ontologyExtractTextJob: (gid: string, text: string, endpoint_id: string, instructions: string, source = "doc", prompt = "") =>
    send(`/ontology/graphs/${gid}/extract/text`, "POST", { text, endpoint_id, instructions, source, prompt, async_job: true }),
  ontologyExtractJob: (jobId: string) => fetch(`${base}/ontology/extract/jobs/${jobId}`).then(j),
  ontologyExtractFileJob: (gid: string, path: string, endpoint_id: string, instructions: string, prompt = "") =>
    send(`/ontology/graphs/${gid}/extract/file`, "POST", { path, endpoint_id, instructions, prompt, async_job: true }),
  ontologyCancelExtractJob: (jobId: string) => send(`/ontology/extract/jobs/${jobId}/cancel`, "POST"),
  ontologyNeighbors: (gid: string, eid: string) => fetch(`${base}/ontology/graphs/${gid}/neighbors/${eid}`).then(j),
  ontologyEntityDetail: (gid: string, eid: string) => fetch(`${base}/ontology/graphs/${gid}/entity/${eid}`).then(j),
  ontologyExtractStructured: (gid: string, table: string, rows: object[]) => send(`/ontology/graphs/${gid}/extract/structured`, "POST", { table, rows }),
  ontologyExtractText: (gid: string, text: string, source?: string) => send(`/ontology/graphs/${gid}/extract/text`, "POST", { text, source }),
  ontologyGraphDatastore: (gid: string) => fetch(`${base}/ontology/graphs/${gid}/datastore`).then(j),
  ontologySaveGraphDatastore: (gid: string, conn: object) => send(`/ontology/graphs/${gid}/datastore`, "PUT", conn),
  ontologyTelemetry: () => fetch(`${base}/ontology/telemetry`).then(j),

  // data science lab (self-contained module)
  dslConfig: () => fetch(`${base}/dsl/config`).then(j),
  dslSetConfig: (body: object) => send("/dsl/config", "PUT", body),
  dslStatus: () => fetch(`${base}/dsl/status`).then(j),
  dslRuntimes: (tenant = "default") => fetch(`${base}/dsl/runtimes?tenant=${tenant}`).then(j),
  dslCreateRuntime: (body: object) => send("/dsl/runtimes", "POST", body),
  dslUploadKey: (rid: string, key_pem: string, passphrase = "") => send(`/dsl/runtimes/${rid}/ssh-key`, "POST", { key_pem, passphrase }),
  dslUpdateRuntime: (rid: string, patch: object) => send(`/dsl/runtimes/${rid}`, "PUT", patch),
  dslDeleteRuntime: (rid: string) => send(`/dsl/runtimes/${rid}`, "DELETE"),
  dslTestRuntime: (rid: string) => send(`/dsl/runtimes/${rid}/test`, "POST"),
  dslStartRuntime: (rid: string) => send(`/dsl/runtimes/${rid}/start`, "POST"),
  dslStopRuntime: (rid: string, verify_backup = true) => send(`/dsl/runtimes/${rid}/stop`, "POST", { verify_backup }),
  dslOpenLab: (rid: string) => send(`/dsl/runtimes/${rid}/open`, "POST"),
  dslAgentAccess: (rid: string, body: object = {}) => send(`/dsl/runtimes/${rid}/agent-access`, "POST", body),
  dslRevokeAgentAccess: (rid: string) => send(`/dsl/runtimes/${rid}/agent-access`, "DELETE"),
  dslCloseLab: (rid: string) => send(`/dsl/runtimes/${rid}/lab`, "DELETE"),
  dslMetrics: (rid: string) => fetch(`${base}/dsl/runtimes/${rid}/metrics`).then(j),
  dslHeadless: (rid: string, notebook: string, params: object) => send(`/dsl/runtimes/${rid}/headless`, "POST", { notebook, params }),
  dslMultiuser: (rid: string) => send(`/dsl/runtimes/${rid}/multiuser`, "POST"),
  dslTemplates: () => fetch(`${base}/dsl/templates`).then(j),
  dslCreateTemplate: (body: object) => send("/dsl/templates", "POST", body),
  dslBumpTemplate: (tid: string, version: string, changelog: string) => send(`/dsl/templates/${tid}/version`, "POST", { version, changelog }),
  dslTemplateCI: (tid: string, runtime_id: string) => send(`/dsl/templates/${tid}/ci`, "POST", { runtime_id }),
  dslDeleteTemplate: (tid: string) => send(`/dsl/templates/${tid}`, "DELETE"),
  dslBlueprints: () => fetch(`${base}/dsl/blueprints`).then(j),
  dslMlflow: () => fetch(`${base}/dsl/mlflow`).then(j),
  dslRegistryModels: () => fetch(`${base}/dsl/registry/models`).then(j),
  dslRegisterModel: (body: object) => send("/dsl/registry/models", "POST", body),
  dslModelStage: (name: string, version: string, stage: string) => send(`/dsl/registry/models/${encodeURIComponent(name)}/stage`, "POST", { version, stage }),
  dslDeleteModel: (name: string) => send(`/dsl/registry/models/${encodeURIComponent(name)}`, "DELETE"),

  // file storage
  filesConfig: () => fetch(`${base}/files/config`).then(j),
  filesUpdateConfig: (patch: object) => send("/files/config", "PUT", patch),
  filesList: (prefix = "") => fetch(`${base}/files/list?prefix=${encodeURIComponent(prefix)}`).then(j),
  filesUpload: (filename: string, prefix: string, content_b64: string) => send("/files/upload", "POST", { filename, prefix, content_b64 }),
  filesPreview: (path: string) => fetch(`${base}/files/preview?path=${encodeURIComponent(path)}`).then(j),
  filesMkdir: (path: string) => send("/files/mkdir", "POST", { path }),
  filesDelete: (path: string) => send(`/files/delete?path=${encodeURIComponent(path)}`, "DELETE"),
  filesDownloadUrl: (path: string) => `${base}/files/download?path=${encodeURIComponent(path)}`,

  // chat history (persistent conversations)
  chatList: (q = "", archived = false) => fetch(`${base}/chat/conversations?q=${encodeURIComponent(q)}${archived ? "&archived=true" : ""}`).then(j),
  chatCreate: (workflow_id: string, workflow_name: string) => send("/chat/conversations", "POST", { workflow_id, workflow_name }),
  chatGet: (cid: string) => fetch(`${base}/chat/conversations/${cid}`).then(j),
  chatSaveMessages: (cid: string, messages: any[]) => send(`/chat/conversations/${cid}/messages`, "PUT", { messages }),
  chatRename: (cid: string, title: string) => send(`/chat/conversations/${cid}/rename`, "PUT", { title }),
  chatArchive: (cid: string, archived: boolean) => send(`/chat/conversations/${cid}/archive`, "PUT", { archived }),
  chatDelete: (cid: string) => send(`/chat/conversations/${cid}`, "DELETE"),

  // Module 6 — Platform Insights
  runInsights: () => send("/insights/run", "POST"),
  listReports: () => fetch(`${base}/insights/reports`).then(j),
  latestFindings: () => fetch(`${base}/insights/findings`).then(j),
  reportDownloadUrl: (id: string) => `${base}/insights/reports/${id}/download`,

  // outputs & artifacts (Claude-style output viewer)
  runOutputs: (runId: string) => fetch(`${base}/runs/${runId}/outputs`).then(j),
  artifactUrl: (runId: string, name: string) => `${base}/runs/${runId}/artifacts/${name}`,

  // ADK connectors
  listConnectors: () => fetch(`${base}/connectors`).then(j),
  mcpServers: () => fetch(`${base}/mcp/servers`).then(j),
  mcpAddServer: (body: object) => send("/mcp/servers", "POST", body),
  mcpUpdateServer: (sid: string, body: object) => send(`/mcp/servers/${sid}`, "PUT", body),
  mcpDeleteServer: (sid: string) => send(`/mcp/servers/${sid}`, "DELETE"),
  mcpTestServer: (sid: string) => send(`/mcp/servers/${sid}/test`, "POST"),
  mcpServerTools: (sid: string, refresh = false) => fetch(`${base}/mcp/servers/${sid}/tools?refresh=${refresh}`).then(j),
  mcpJupyterLink: (rid: string) => send(`/mcp/jupyter/link/${rid}`, "POST"),
  mcpConnect: (sid: string, jupyter_url: string, jupyter_token: string) =>
    send(`/mcp/servers/${sid}/connect`, "POST", { jupyter_url, jupyter_token }),
  enabledConnectors: () => fetch(`${base}/connectors/enabled`).then(j),
  toggleConnector: (id: string, enabled: boolean, config?: object) =>
    send(`/connectors/${id}/toggle`, "POST", { enabled, config }),

  // model endpoints (UI-managed LLM connections)
  listEndpoints: () => fetch(`${base}/model-endpoints`).then(j),
  addEndpoint: (data: object) => send("/model-endpoints", "POST", data),
  deleteEndpoint: (id: string) => send(`/model-endpoints/${id}`, "DELETE"),
  testEndpoint: (id: string) => send(`/model-endpoints/${id}/test`, "POST"),
};

// Live activity stream (spec §25). Reconnects with ?after_seq to resume.
export function streamRun(
  runId: string,
  onEvent: (e: ActivityEvent) => void,
  afterSeq = 0
): () => void {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}${base}/runs/${runId}/stream?after_seq=${afterSeq}`);
  ws.onmessage = (m) => onEvent(JSON.parse(m.data));
  return () => ws.close();
}
