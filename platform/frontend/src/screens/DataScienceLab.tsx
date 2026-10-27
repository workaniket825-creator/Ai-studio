import { useEffect, useState } from "react";
import { Card, Button, Tag, InputGroup, FormGroup, HTMLSelect, Switch, Callout, Tabs, Tab,
  NonIdealState, NumericInput, Icon, HTMLTable } from "@blueprintjs/core";
import { api } from "../api/client";
import { toast } from "../components/toaster";

export function DataScienceLab() {
  const [cfg, setCfg] = useState<any>(null);
  useEffect(() => { api.dslConfig().then(setCfg); }, []);

  return (
    <div>
      <div className="section-head">
        <div><h2>Data Science Lab</h2>
          <span className="muted">Colab-style notebooks on your own NVIDIA GPUs — execution runs on the
            remote target; results surface here.</span></div>
        {cfg && <Tag large minimal intent={cfg.enabled ? "success" : "none"}
          icon={cfg.enabled ? "power" : "disable"}>{cfg.enabled ? "enabled" : "disabled (dark)"}</Tag>}
      </div>

      {cfg && !cfg.enabled && (
        <Callout icon="moon" intent="warning" style={{ marginBottom: 14 }} title="Module is in dark mode">
          The Data Science Lab ships disabled. Turn it on below to register GPU runtimes and open notebooks.
          The rest of the platform is unaffected either way.
          <div style={{ marginTop: 10 }}>
            <Button intent="primary" icon="power" text="Enable Data Science Lab"
              onClick={async () => { await api.dslSetConfig({ enabled: true }); setCfg(await api.dslConfig()); toast.success("Enabled"); }} />
          </div>
        </Callout>
      )}

      <Tabs id="dsl-tabs" defaultSelectedTabId="runtimes">
        <Tab id="runtimes" title="Runtimes" panel={<Runtimes enabled={cfg?.enabled} />} />
        <Tab id="workspace" title="Workspace" panel={<Workspace enabled={cfg?.enabled} />} />
        <Tab id="templates" title="Template Library" panel={<Templates enabled={cfg?.enabled} />} />
        <Tab id="blueprints" title="NVIDIA Blueprints" panel={<Blueprints />} />
        <Tab id="models" title="Experiments & Models" panel={<Models />} />
        <Tab id="registry" title="Model Registry" panel={<Registry enabled={cfg?.enabled} />} />
        {cfg?.enabled && <Tab id="settings" title="Settings" panel={<Settings cfg={cfg} onChange={setCfg} />} />}
      </Tabs>
    </div>
  );
}

const BLANK = { name: "", provider: "brev", host: "", ssh_user: "ubuntu", ssh_port: 22,
  gpu_type: "", region: "", runtime_image: "nvcr.io/nvidia/rapidsai/base:24.10-cuda12.5-py3.11",
  workdir: "/home/ubuntu/workspace", jupyter_port: 8888, idle_timeout_min: 30, python_path: "python3",
  auth_secret_ref: "", persistent_volume_ref: "", backup_remote: "", mlflow_uri: "",
  multiuser: false, hub_url: "", mig_enabled: false, mig_profile: "" };

// Sample values per provider so users see exactly what to enter.
const SAMPLES: Record<string, any> = {
  brev: { ...BLANK, provider: "brev", name: "Team A100 (Brev)", gpu_type: "NVIDIA A100 80GB",
    host: "team-a100-dev", ssh_user: "ubuntu", ssh_port: 22, region: "us-west-1",
    auth_secret_ref: "vault://brev-token", idle_timeout_min: 30,
    mlflow_uri: "http://mlflow:5000", persistent_volume_ref: "vol-home-teamA" },
  azure: { ...BLANK, provider: "azure", name: "GPU-RG / gpu-vm-01 (Azure)", gpu_type: "NVIDIA A100 80GB",
    host: "ml-rg/gpu-vm-01", ssh_user: "azureuser", ssh_port: 22, region: "eastus",
    auth_secret_ref: "vault://azure-sp", idle_timeout_min: 45,
    mlflow_uri: "http://mlflow:5000", backup_remote: "az://mlblob/lab" },
};

// Which fields are required, by provider (drives color-coding).
const REQUIRED: Record<string, string[]> = {
  brev: ["name", "provider", "host", "auth_secret_ref"],
  azure: ["name", "provider", "host", "region", "auth_secret_ref"],
  ssh: ["name", "provider", "host", "ssh_user"],
};

// One-line definitions shown as helper text under each field.
const DEFS: Record<string, string> = {
  name: "A friendly label for this compute target (shown in the feed).",
  gpu_type: "GPU model/size on the instance — informational, e.g. 'NVIDIA A100 80GB'.",
  host: "Brev: the instance name. Azure: '<resource_group>/<vm_name>'. SSH: host/IP.",
  ssh_user: "SSH login user on the instance (Brev/Azure images usually 'ubuntu'/'azureuser').",
  ssh_port: "SSH port (default 22).",
  region: "Cloud region of the instance (Azure/AWS). Required for managed providers.",
  runtime_image: "Container image the notebook/job runs in (NGC image recommended).",
  workdir: "Working directory on the instance where notebooks/jobs run.",
  jupyter_port: "Port the notebook server listens on (tunneled locally).",
  python_path: "Python interpreter on the target that has jupyterlab + papermill (e.g. python3, or ~/lab/bin/python for a venv). Used to launch the lab and run notebooks.",
  auth_secret_ref: "Where the credential lives. SSH: absolute path to the .pem private key on the backend host (e.g. /home/app/.ssh/vm.pem) or a vault:// ref. Brev: vault:// ref or 'env:BREV_API_KEY'. Azure: service-principal ref 'vault://azure-sp' or 'env:AZURE_CLIENT_SECRET'. Never paste the raw key.",
  persistent_volume_ref: "Optional volume kept across restarts so work isn't lost.",
  idle_timeout_min: "Auto-shutdown after this many idle minutes (managed providers) to save cost.",
  mlflow_uri: "Existing MLflow tracking server to log runs/metrics to (optional).",
  backup_remote: "Optional rclone/registry remote for verified backups before stop.",
};

// Color-coded field: required labels get the accent "required" tag, optional get muted.
function Fld({ k, f, req, def_, label, children }:
  { k: string; f: any; req: Record<string, string[]>; def_: string; label?: string; children: any }) {
  const isReq = (req[f.provider] || []).includes(k);
  const pretty = label || k.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return (
    <FormGroup helperText={def_}
      label={<span>{pretty}{" "}
        {isReq ? <span style={{ color: "var(--accent)", fontWeight: 600, fontSize: 11 }}>• required</span>
               : <span className="muted" style={{ fontSize: 11 }}>• optional</span>}</span>}>
      {children}
    </FormGroup>
  );
}

function Runtimes({ enabled }: { enabled?: boolean }) {
  const [rows, setRows] = useState<any[]>([]);
  const [f, setF] = useState<any>({ ...BLANK });
  const [show, setShow] = useState(false);
  const [metrics, setMetrics] = useState<Record<string, any>>({});
  const set = (k: string, v: any) => setF((p: any) => ({ ...p, [k]: v }));
  const refresh = () => api.dslRuntimes().then(setRows);
  useEffect(() => { refresh(); }, []);
  const managed = f.provider !== "ssh";

  // poll GPU metrics for running runtimes (§7)
  useEffect(() => {
    const poll = () => rows.filter((r) => r.status === "running").forEach((r) =>
      api.dslMetrics(r.id).then((m) => setMetrics((p) => ({ ...p, [r.id]: m }))).catch(() => {}));
    poll(); const t = setInterval(poll, 5000); return () => clearInterval(t);
  }, [rows]);

  const create = async () => {
    if (!f.name.trim()) { toast.error("Name required"); return; }
    try { await api.dslCreateRuntime(f); toast.success("Runtime registered"); setF({ ...BLANK }); setShow(false); refresh(); }
    catch (e: any) { toast.error(e.message); }
  };
  const test = async (r: any) => { const t = await api.dslTestRuntime(r.id); t.ok ? toast.success(t.detail) : toast.error(t.detail); refresh(); };
  const start = async (r: any) => { const t = await api.dslStartRuntime(r.id); t.ok ? toast.success("Started") : toast.error(t.detail); refresh(); };
  const stop = async (r: any) => { const t = await api.dslStopRuntime(r.id); t.ok ? toast.success("Stopped") : toast.error(t.detail); refresh(); };
  const openLab = async (r: any) => {
    const s = await api.dslOpenLab(r.id);
    if (s.ok) toast.success("Lab session ready — open the Workspace tab");
    else toast.info(s.detail || "Session prepared; complete target setup.");
    sessionStorage.setItem("dsl_active", JSON.stringify({ ...s, runtime: r.name, runtime_id: r.id }));
    refresh();
  };

  const agentAccess = async (r: any) => {
    try {
      const s = await api.dslAgentAccess(r.id, { create_agent: true });
      if (s.ok) {
        toast.success(`Agents can now run code on ${r.name}. Use the "${s.agent_name}" agent ` +
          `(workflow "${s.workflow_name}"), or attach MCP server "${s.server_name}" to any agent.`);
        if (!s.model_endpoint_set) toast.info(`Pick a model for "${s.agent_name}" in Agent Garden → Edit → Model.`);
      } else toast.error(s.detail || "Could not enable agent access");
    } catch (e: any) { toast.error(e.message); }
    refresh();
  };

  const badge = (s: string) => s === "running" ? "success" : s === "unreachable" ? "danger" : s === "idle" ? "primary" : "none";

  return (
    <div style={{ paddingTop: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
        <span className="muted">Registered compute targets (the feed)</span>
        <Button intent="primary" icon="add" text="Add Runtime" disabled={!enabled} onClick={() => setShow(!show)} />
      </div>

      {show && enabled && (
        <Card style={{ marginBottom: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <b>Add a compute target</b>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <span className="muted" style={{ fontSize: 12 }}>Prefill an example:</span>
              <Button small icon="clean" text="Brev sample" onClick={() => setF({ ...SAMPLES.brev })} />
              <Button small icon="clean" text="Azure sample" onClick={() => setF({ ...SAMPLES.azure })} />
            </div>
          </div>
          <Callout style={{ margin: "8px 0", fontSize: 12 }} icon="info-sign">
            Fields marked <span style={{ color: "var(--accent)", fontWeight: 600 }}>required</span> must be filled;
            the rest are <span className="muted">optional</span>. Click a sample above to see typical values, then edit.
          </Callout>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12, marginTop: 4 }}>
            <Fld k="provider" f={f} req={REQUIRED} def_="Where the compute lives. Managed = platform can start/stop it; SSH = connect-only.">
              <HTMLSelect fill value={f.provider} onChange={(e) => set("provider", e.target.value)}
                options={[{ label: "Brev (managed, NVIDIA)", value: "brev" }, { label: "AWS (managed)", value: "aws" },
                          { label: "Azure (managed)", value: "azure" }, { label: "SSH / on-prem (connect-only)", value: "ssh" }]} /></Fld>
            <Fld k="name" f={f} req={REQUIRED} def_={DEFS.name}>
              <InputGroup value={f.name} onChange={(e) => set("name", e.target.value)} placeholder="Team A100 (Brev)" /></Fld>
            <Fld k="gpu_type" f={f} req={REQUIRED} def_={DEFS.gpu_type}>
              <InputGroup value={f.gpu_type} onChange={(e) => set("gpu_type", e.target.value)} placeholder="NVIDIA A100 80GB" /></Fld>
            <Fld k="host" f={f} req={REQUIRED} label={managed ? "Instance / host" : "Host / IP"} def_={DEFS.host}>
              <InputGroup value={f.host} onChange={(e) => set("host", e.target.value)}
                placeholder={f.provider === "azure" ? "ml-rg/gpu-vm-01" : managed ? "team-a100-dev" : "10.20.30.40"} /></Fld>
            <Fld k="region" f={f} req={REQUIRED} def_={DEFS.region}>
              <InputGroup value={f.region} onChange={(e) => set("region", e.target.value)} placeholder="eastus / us-west-1" /></Fld>
            <Fld k="auth_secret_ref" f={f} req={REQUIRED} def_={DEFS.auth_secret_ref}>
              <InputGroup value={f.auth_secret_ref} onChange={(e) => set("auth_secret_ref", e.target.value)} placeholder="vault://brev-token" /></Fld>
            <Fld k="ssh_user" f={f} req={REQUIRED} def_={DEFS.ssh_user}>
              <InputGroup value={f.ssh_user} onChange={(e) => set("ssh_user", e.target.value)} placeholder="ubuntu / azureuser" /></Fld>
            <Fld k="ssh_port" f={f} req={REQUIRED} def_={DEFS.ssh_port}>
              <NumericInput fill value={f.ssh_port} onValueChange={(v) => set("ssh_port", v)} /></Fld>
            <Fld k="runtime_image" f={f} req={REQUIRED} def_={DEFS.runtime_image}>
              <InputGroup value={f.runtime_image} onChange={(e) => set("runtime_image", e.target.value)} /></Fld>
            <Fld k="workdir" f={f} req={REQUIRED} def_={DEFS.workdir}>
              <InputGroup value={f.workdir} onChange={(e) => set("workdir", e.target.value)} /></Fld>
            <Fld k="jupyter_port" f={f} req={REQUIRED} def_={DEFS.jupyter_port}>
              <NumericInput fill value={f.jupyter_port} onValueChange={(v) => set("jupyter_port", v)} /></Fld>
            <Fld k="python_path" f={f} req={REQUIRED} label="Target Python (jupyter/papermill)" def_={DEFS.python_path}>
              <InputGroup value={f.python_path} onChange={(e) => set("python_path", e.target.value)} placeholder="python3 or ~/lab/bin/python" /></Fld>
            <Fld k="idle_timeout_min" f={f} req={REQUIRED} label={`Idle auto-shutdown (min)${managed ? "" : " — managed only"}`} def_={DEFS.idle_timeout_min}>
              <NumericInput fill value={f.idle_timeout_min} onValueChange={(v) => set("idle_timeout_min", v)} disabled={!managed} /></Fld>
            <Fld k="persistent_volume_ref" f={f} req={REQUIRED} def_={DEFS.persistent_volume_ref}>
              <InputGroup value={f.persistent_volume_ref} onChange={(e) => set("persistent_volume_ref", e.target.value)} placeholder="vol-home-teamA" /></Fld>
            <Fld k="mlflow_uri" f={f} req={REQUIRED} def_={DEFS.mlflow_uri}>
              <InputGroup value={f.mlflow_uri} onChange={(e) => set("mlflow_uri", e.target.value)} placeholder="http://mlflow:5000" /></Fld>
            <Fld k="backup_remote" f={f} req={REQUIRED} def_={DEFS.backup_remote}>
              <InputGroup value={f.backup_remote} onChange={(e) => set("backup_remote", e.target.value)} placeholder="s3:bucket/lab or az://mlblob/lab" /></Fld>
            <FormGroup label="Multi-user (JupyterHub)"><HTMLSelect fill value={f.multiuser ? "yes" : "no"} onChange={(e) => set("multiuser", e.target.value === "yes")} options={[{ label: "single-user", value: "no" }, { label: "multi-user (Hub)", value: "yes" }]} /></FormGroup>
            <FormGroup label="Hub URL"><InputGroup value={f.hub_url} onChange={(e) => set("hub_url", e.target.value)} placeholder="http://hub:8000" disabled={!f.multiuser} /></FormGroup>
            <FormGroup label="MIG slicing"><HTMLSelect fill value={f.mig_enabled ? "yes" : "no"} onChange={(e) => set("mig_enabled", e.target.value === "yes")} options={[{ label: "off", value: "no" }, { label: "on (share GPU)", value: "yes" }]} /></FormGroup>
            <FormGroup label="MIG profile"><InputGroup value={f.mig_profile} onChange={(e) => set("mig_profile", e.target.value)} placeholder="1g.10gb" disabled={!f.mig_enabled} /></FormGroup>
          </div>
          <Button intent="primary" icon="floppy-disk" text="Register runtime" onClick={create} />
        </Card>
      )}

      {rows.length === 0 ? <NonIdealState icon="database" title="No runtimes yet"
        description={enabled ? "Register a GPU/CPU target above." : "Enable the module, then register a target."} /> : (
        <div className="garden-grid">
          {rows.map((r) => (
            <div className="agent-card" key={r.id}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <b>{r.name}</b><Tag minimal intent={badge(r.status)}>{r.status}</Tag>
              </div>
              <div className="chip-row" style={{ marginTop: 6 }}>
                <Tag minimal icon="cloud">{r.provider}</Tag>
                {r.gpu_type && <Tag minimal icon="cell-tower">{r.gpu_type}</Tag>}
                {r.can_manage_lifecycle && <Tag minimal icon="time">idle {r.idle_timeout_min}m</Tag>}
                {r.multiuser && <Tag minimal icon="people">Hub</Tag>}
                {r.mig_enabled && <Tag minimal icon="layers">MIG {r.mig_profile}</Tag>}
              </div>
              {metrics[r.id] && (metrics[r.id].available ? (
                <div style={{ marginTop: 8 }}>
                  {metrics[r.id].gpus.map((gp: any, i: number) => (
                    <div key={i} className="muted metric" style={{ fontSize: 11 }}>
                      GPU{i}: {gp.util_pct}% util · {Math.round(gp.mem_used_mb)}/{Math.round(gp.mem_total_mb)}MB · {gp.temp_c}°C
                    </div>))}
                </div>
              ) : <div className="muted" style={{ fontSize: 11, marginTop: 6 }}>GPU metrics: {metrics[r.id].detail}</div>)}
              {r.last_error && <div className="muted" style={{ fontSize: 11, marginTop: 6, color: "var(--danger)" }}>{r.last_error}</div>}
              <div style={{ display: "flex", gap: 6, marginTop: 10, flexWrap: "wrap" }}>
                <Button small icon="pulse" text="Test" onClick={() => test(r)} />
                {r.provider === "ssh" && (
                  <Button small icon="key" text={r.has_uploaded_key ? "Replace .pem" : "Upload .pem"}
                    intent={r.has_uploaded_key ? "none" : "warning"}
                    onClick={() => {
                      const inp = document.createElement("input");
                      inp.type = "file"; inp.accept = ".pem,.key,text/plain";
                      inp.onchange = async () => {
                        const file = inp.files?.[0]; if (!file) return;
                        const pem = await file.text();
                        try { const res = await api.dslUploadKey(r.id, pem);
                          res.ok ? toast.success("Key uploaded & bound (0600)") : toast.error(res.detail || "upload failed"); refresh();
                        } catch { toast.error("Upload failed — is it a valid PEM key?"); }
                      };
                      inp.click();
                    }} />
                )}
                {r.can_manage_lifecycle && <Button small icon="play" text="Start" onClick={() => start(r)} />}
                <Button small intent="primary" icon="code-block" text="Open Lab" onClick={() => openLab(r)} />
                <Button small icon="console" intent={r.agent_mcp_server ? "success" : "none"}
                  text={r.agent_mcp_server ? "Agent access: on" : "Enable agent access"}
                  title="Register this runtime as an MCP server (run_python, run_shell, notebooks) and create a ready-made agent"
                  onClick={() => agentAccess(r)} />
                {r.multiuser && <Button small icon="people" text="Hub"
                  onClick={async () => { const s = await api.dslMultiuser(r.id); s.ok ? toast.success(s.detail) : toast.info(s.detail); }} />}
                {r.can_manage_lifecycle && <Button small icon="stop" text="Stop" onClick={() => stop(r)} />}
                <Button small minimal icon="trash" onClick={async () => { if (confirm(`Delete runtime "${r.name}"?`)) { await api.dslDeleteRuntime(r.id); refresh(); } }} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function workspaceUrl(raw: string): string {
  const url = new URL(raw, window.location.origin);
  if (["127.0.0.1", "localhost", "::1"].includes(url.hostname)) {
    throw new Error("Backend returned a private SSH tunnel address");
  }
  if (url.origin !== window.location.origin) {
    throw new Error("Workspace URL must use the AI Studio origin");
  }
  return url.toString();
}

function Workspace({ enabled }: { enabled?: boolean }) {
  const [s, setS] = useState<any>(null);
  const [gpu, setGpu] = useState<any>(null);
  const [nb, setNb] = useState("train.ipynb");
  const closeWorkspace = async () => {
    try {
      if (s?.runtime_id) await api.dslCloseLab(s.runtime_id);
    } catch {
      // The backend may already have restarted or closed the tunnel.
    }
    sessionStorage.removeItem("dsl_active");
    setS(null);
  };
  useEffect(() => { const raw = sessionStorage.getItem("dsl_active"); if (raw) setS(JSON.parse(raw)); }, []);
  useEffect(() => {
    if (!s?.runtime_id) return;
    const poll = () => api.dslMetrics(s.runtime_id).then(setGpu).catch(() => {});
    poll(); const t = setInterval(poll, 5000); return () => clearInterval(t);
  }, [s]);
  if (!enabled) return <div className="muted" style={{ padding: 20 }}>Enable the module to use the workspace.</div>;
  if (!s) return <NonIdealState icon="code-block" title="No active session"
    description="Open a runtime from the Runtimes tab to launch JupyterLab here." />;
  return (
    <div style={{ paddingTop: 12 }}>
      <Card style={{ marginBottom: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
          <Tag large minimal icon="cell-tower" intent={s.ok ? "success" : "warning"}>{s.kernel_badge}</Tag>
          {s.mlflow_uri && <Tag minimal icon="chart">MLflow: {s.mlflow_uri}</Tag>}
          {s.workdir && <Tag minimal icon="folder-close">{s.workdir}</Tag>}
          {gpu && gpu.available && gpu.gpus[0] && (
            <Tag minimal icon="dashboard" intent="primary">
              GPU {gpu.gpus[0].util_pct}% · {Math.round(gpu.gpus[0].mem_used_mb)}/{Math.round(gpu.gpus[0].mem_total_mb)}MB · {gpu.gpus[0].temp_c}°C
            </Tag>)}
          {gpu && !gpu.available && <Tag minimal icon="offline">GPU metrics: {gpu.detail}</Tag>}
        </div>
        {!s.ok && <Callout intent="warning" icon="info-sign" style={{ marginTop: 10 }}>
          {s.detail}
          {s.steps && <HTMLTable compact style={{ width: "100%", marginTop: 8 }}>
            <thead><tr><th>Step</th><th>OK</th><th>Detail</th></tr></thead>
            <tbody>{s.steps.map((st: any, i: number) => (
              <tr key={i}><td className="metric">{st.step}</td><td>{st.ok ? "✓" : "✗"}</td>
                <td className="muted" style={{ fontSize: 11 }}>{st.detail || st.stderr || st.stdout || ""}</td></tr>))}</tbody>
          </HTMLTable>}
        </Callout>}
        <div style={{ display: "flex", gap: 6, marginTop: 10, alignItems: "center" }}>
          <span className="muted" style={{ fontSize: 12 }}>Headless run (papermill):</span>
          <InputGroup small value={nb} onChange={(e) => setNb(e.target.value)} style={{ width: 180 }} />
          <Button small icon="play" text="Run" onClick={async () => {
            const r = await api.dslHeadless(s.runtime_id, nb, {});
            r.ok ? toast.success("Ran → " + r.output_notebook) : toast.info(r.detail); }} />
        </div>
      </Card>
      {s.ok && s.embed_url ? (
        <div>
          <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
            <Button
              small
              icon="cross"
              text="Close Lab"
              onClick={closeWorkspace}
            />
          </div>
          <iframe
            title="JupyterLab"
            src={workspaceUrl(s.embed_url)}
            style={{
              width: "100%",
              height: "70vh",
              border: "1px solid var(--border)",
              borderRadius: 10,
              background: "#0c120c",
            }}
            allow="clipboard-read; clipboard-write"
          />
        </div>
      ) : (
        <Card><div className="muted" style={{ padding: 20, textAlign: "center" }}>
          <Icon icon="code-block" size={28} /><div style={{ marginTop: 8 }}>
            JupyterLab will embed here once the target serves it over the tunnel. The kernel executes on the
            remote GPU; outputs and MLflow runs surface back in the platform.</div></div></Card>
      )}
    </div>
  );
}

function Templates({ enabled }: { enabled?: boolean }) {
  const [rows, setRows] = useState<any[]>([]);
  const [f, setF] = useState({ name: "", tags: "", repo_path: "", status: "draft", description: "" });
  const refresh = () => api.dslTemplates().then(setRows);
  useEffect(() => { refresh(); }, []);
  const create = async () => {
    if (!f.name.trim()) { toast.error("Name required"); return; }
    await api.dslCreateTemplate({ ...f, tags: f.tags.split(",").map((t) => t.trim()).filter(Boolean) });
    toast.success("Template added"); setF({ name: "", tags: "", repo_path: "", status: "draft", description: "" }); refresh();
  };
  return (
    <div style={{ paddingTop: 12 }}>
      <Callout icon="git-repo" style={{ marginBottom: 12 }}>
        Internal, tried-and-tested notebooks (source of truth = git). Open → run on a runtime → modify → save as a new version.
      </Callout>
      {enabled && (
        <Card style={{ marginBottom: 12 }}>
          <b>Add a template</b>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10, marginTop: 10 }}>
            <FormGroup label="Name"><InputGroup value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="EDA Starter (RAPIDS)" /></FormGroup>
            <FormGroup label="Git repo path"><InputGroup value={f.repo_path} onChange={(e) => setF({ ...f, repo_path: e.target.value })} placeholder="templates/eda-starter" /></FormGroup>
            <FormGroup label="Tags"><InputGroup value={f.tags} onChange={(e) => setF({ ...f, tags: e.target.value })} placeholder="eda, rapids" /></FormGroup>
            <FormGroup label="Tier"><HTMLSelect value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} options={[{ label: "draft", value: "draft" }, { label: "tried & tested", value: "tried_and_tested" }]} /></FormGroup>
            <FormGroup label="Description" style={{ gridColumn: "span 2" }}><InputGroup value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></FormGroup>
          </div>
          <Button intent="primary" icon="add" text="Add template" onClick={create} />
        </Card>
      )}
      {rows.length === 0 ? <div className="muted">No templates yet.</div> : (
        <div className="garden-grid">
          {rows.map((t) => (
            <div className="agent-card" key={t.id}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <b>{t.name}</b><Tag minimal intent={t.status === "tried_and_tested" ? "success" : "none"}>{t.status === "tried_and_tested" ? "tried & tested" : "draft"}</Tag>
              </div>
              <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>v{t.version} · {t.description}</div>
              <div className="chip-row" style={{ marginTop: 6 }}>
                {(t.tags || []).map((x: string) => <Tag key={x} minimal>{x}</Tag>)}
                <Tag minimal intent={t.ci_status === "passing" ? "success" : t.ci_status === "failing" ? "danger" : "none"}
                  icon={t.ci_status === "passing" ? "tick" : t.ci_status === "failing" ? "cross" : "help"}>CI {t.ci_status || "untested"}</Tag>
              </div>
              <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
                <Button small icon="git-commit" text="New version" onClick={async () => {
                  const v = prompt("New semver version (e.g. 1.0.0):", t.version); if (!v) return;
                  const cl = prompt("Changelog:", "") || "";
                  await api.dslBumpTemplate(t.id, v, cl); toast.success("Version " + v); refresh(); }} />
                <Button small icon="pulse" text="Run CI" onClick={async () => {
                  const rts = await api.dslRuntimes();
                  if (!rts.length) { toast.error("Register a runtime first to run CI"); return; }
                  const r = await api.dslTemplateCI(t.id, rts[0].id);
                  r.ok ? toast.success("CI passing") : toast.info("CI: " + (r.ci_status || r.detail)); refresh(); }} />
                <Button small icon="trash" minimal onClick={async () => { if (confirm(`Delete template "${t.name}"?`)) { await api.dslDeleteTemplate(t.id); refresh(); } }} />
              </div>
              {t.versions && t.versions.length > 1 && (
                <div className="muted" style={{ fontSize: 10, marginTop: 6 }}>
                  {t.versions.length} versions · latest: {t.changelog || "—"}</div>)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Blueprints() {
  const [rows, setRows] = useState<any[]>([]);
  useEffect(() => { api.dslBlueprints().then(setRows); }, []);
  return (
    <div style={{ paddingTop: 12 }}>
      <Callout icon="link" intent="primary" style={{ marginBottom: 12 }}>
        <b>External</b> NVIDIA reference workflows (build.nvidia.com). Distinct from your internal templates —
        clone one into a runtime to try it. Verify licence/availability before internal use.
      </Callout>
      <div className="garden-grid">
        {rows.map((b) => (
          <div className="agent-card" key={b.name}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <b>{b.name}</b><Tag minimal intent={b.category === "agentic" ? "primary" : "none"}>{b.category}</Tag>
            </div>
            <div className="muted" style={{ fontSize: 12, margin: "6px 0" }}>{b.summary}</div>
            <div style={{ display: "flex", gap: 6 }}>
              <a href={b.docs} target="_blank" rel="noreferrer"><Button small minimal icon="document-open" text="Docs" /></a>
              <a href={b.repo} target="_blank" rel="noreferrer"><Button small minimal icon="git-branch" text="Repo" /></a>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Models() {
  const [m, setM] = useState<any>(null);
  useEffect(() => { api.dslMlflow().then(setM); }, []);
  if (!m) return <div className="muted" style={{ padding: 20 }}>Loading…</div>;
  return (
    <div style={{ paddingTop: 12, maxWidth: 720 }}>
      <Callout icon="chart" intent={m.configured ? "success" : "warning"} title="Reuses the existing MLflow">
        Experiments and models from the lab are tracked in the platform's existing MLflow — no second system.
        Models registered here are consumable by the agentic-AI layer.
      </Callout>
      <Card style={{ marginTop: 12 }}>
        <b>MLflow</b>
        <div className="muted metric" style={{ fontSize: 12, margin: "6px 0" }}>{m.tracking_uri || "not configured (set MLFLOW_TRACKING_URI)"}</div>
        {m.configured && <div style={{ display: "flex", gap: 8 }}>
          <a href={m.experiments_url} target="_blank" rel="noreferrer"><Button icon="timeline-events" text="Experiments" /></a>
          <a href={m.models_url} target="_blank" rel="noreferrer"><Button icon="cube" text="Model Registry" /></a>
        </div>}
      </Card>
    </div>
  );
}

function Registry({ enabled }: { enabled?: boolean }) {
  const [data, setData] = useState<any>(null);
  const [show, setShow] = useState(false);
  const [f, setF] = useState({ name: "", model_uri: "", description: "" });
  const refresh = () => api.dslRegistryModels().then(setData);
  useEffect(() => { refresh(); }, []);

  const stageColor = (s: string) => s === "Production" ? "success" : s === "Staging" ? "warning" : s === "Archived" ? "none" : "none";
  const register = async () => {
    if (!f.name.trim()) { toast.error("Model name required"); return; }
    await api.dslRegisterModel(f); toast.success("Registered " + f.name);
    setF({ name: "", model_uri: "", description: "" }); setShow(false); refresh();
  };
  const setStage = async (name: string, version: string, stage: string) => {
    await api.dslModelStage(name, version, stage); toast.success(`${name} v${version} → ${stage}`); refresh();
  };

  return (
    <div style={{ paddingTop: 12 }}>
      <Callout icon="cube" intent="primary" style={{ marginBottom: 12 }}>
        Versions and promotes <b>ML models trained in the Lab</b> (e.g. a classifier) using the platform's
        existing MLflow registry. These are separate from the foundation LLMs in <b>Model Endpoints</b> —
        promote one to <b>Production</b> and an agent can call it as a tool.
        {data && <Tag minimal style={{ marginLeft: 8 }}>source: {data.source}</Tag>}
      </Callout>

      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 10 }}>
        <span className="muted">Registered models</span>
        <Button intent="primary" icon="add" text="Register model" disabled={!enabled} onClick={() => setShow(!show)} />
      </div>

      {show && enabled && (
        <Card style={{ marginBottom: 12 }}>
          <b>Register a model version</b>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginTop: 10 }}>
            <FormGroup label="Model name"><InputGroup value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="fraud-classifier" /></FormGroup>
            <FormGroup label="Model URI" helperText="e.g. runs:/<run_id>/model"><InputGroup value={f.model_uri} onChange={(e) => setF({ ...f, model_uri: e.target.value })} /></FormGroup>
            <FormGroup label="Description" style={{ gridColumn: "span 2" }}><InputGroup value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></FormGroup>
          </div>
          <Button intent="primary" icon="floppy-disk" text="Register" onClick={register} />
        </Card>
      )}

      {!data || data.models.length === 0 ? (
        <NonIdealState icon="cube" title="No registered models"
          description={enabled ? "Register a model or push one from a Lab run (mlflow.register_model)." : "Enable the module to manage models."} />
      ) : data.models.map((m: any) => (
        <Card key={m.name} style={{ marginBottom: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div><b>{m.name}</b> <span className="muted" style={{ fontSize: 12 }}>{m.description}</span></div>
            <Button small minimal icon="trash" onClick={async () => { if (confirm(`Delete model "${m.name}"?`)) { await api.dslDeleteModel(m.name); refresh(); } }} />
          </div>
          <HTMLTable compact style={{ width: "100%", marginTop: 8 }}>
            <thead><tr><th>Version</th><th>Stage</th><th>Source</th><th style={{ textAlign: "right" }}>Promote</th></tr></thead>
            <tbody>
              {(m.versions || []).map((v: any) => (
                <tr key={v.version}>
                  <td className="metric">v{v.version}</td>
                  <td><Tag minimal intent={stageColor(v.stage)}>{v.stage}</Tag></td>
                  <td className="muted metric" style={{ fontSize: 11 }}>{v.source || "—"}</td>
                  <td style={{ textAlign: "right" }}>
                    <Button small minimal text="Staging" disabled={!enabled || v.stage === "Staging"} onClick={() => setStage(m.name, v.version, "Staging")} />
                    <Button small minimal intent="success" text="Production" disabled={!enabled || v.stage === "Production"} onClick={() => setStage(m.name, v.version, "Production")} />
                    <Button small minimal text="Archive" disabled={!enabled || v.stage === "Archived"} onClick={() => setStage(m.name, v.version, "Archived")} />
                  </td>
                </tr>
              ))}
            </tbody>
          </HTMLTable>
        </Card>
      ))}
    </div>
  );
}

function Settings({ cfg, onChange }: { cfg: any; onChange: (c: any) => void }) {
  const [tenant, setTenant] = useState("default");
  return (
    <div style={{ paddingTop: 12, maxWidth: 640 }}>
      <Card>
        <b>Feature flag</b>
        <div style={{ marginTop: 10 }}>
          <Switch large checked={cfg.enabled} label="Data Science Lab enabled (system default)"
            onChange={async () => { await api.dslSetConfig({ enabled: !cfg.enabled }); onChange(await api.dslConfig()); }} />
        </div>
        <div className="muted" style={{ fontSize: 12, marginBottom: 10 }}>
          Off = module inert; the rest of the platform is unaffected. Rollback is instant (flip off).
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
          <FormGroup label="Per-tenant override" style={{ marginBottom: 0 }}>
            <InputGroup value={tenant} onChange={(e) => setTenant(e.target.value)} /></FormGroup>
          <Button text="Enable tenant" onClick={async () => { await api.dslSetConfig({ tenant, tenant_enabled: true }); onChange(await api.dslConfig()); toast.success("Enabled " + tenant); }} />
          <Button text="Disable tenant" onClick={async () => { await api.dslSetConfig({ tenant, tenant_enabled: false }); onChange(await api.dslConfig()); toast.info("Disabled " + tenant); }} />
        </div>
      </Card>
    </div>
  );
}
