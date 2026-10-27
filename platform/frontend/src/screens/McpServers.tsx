import { useEffect, useState } from "react";
import { Card, HTMLSelect, InputGroup, Button, FormGroup, Tag, Callout } from "@blueprintjs/core";
import { api } from "../api/client";
import { toast } from "../components/toaster";

const BLANK = { name: "", transport: "sse", url: "", command: "", args: "", enabled: true };

export function McpServers() {
  const [servers, setServers] = useState<any[]>([]);
  const [f, setF] = useState<any>({ ...BLANK });
  const [tools, setTools] = useState<Record<string, string[]>>({});
  const [status, setStatus] = useState<Record<string, { ok: boolean; msg: string }>>({});
  const [jcfg, setJcfg] = useState<Record<string, { url: string; token: string }>>({});
  const set = (k: string, v: any) => setF((p: any) => ({ ...p, [k]: v }));
  const [runtimes, setRuntimes] = useState<any[]>([]);
  const [linkRt, setLinkRt] = useState<string>("");
  const refresh = () => api.mcpServers().then(setServers).catch(() => {});
  useEffect(() => { refresh(); api.dslRuntimes().then(setRuntimes).catch(() => setRuntimes([])); }, []);

  const linkJupyter = async (sid: string) => {
    const rid = linkRt || runtimes[0]?.id;
    if (!rid) { toast.error("Register a DSLab runtime first (Data Science Lab → Runtimes)"); return; }
    const r = await api.mcpJupyterLink(rid);
    setStatus((st) => ({ ...st, [sid]: { ok: !!r.ok,
      msg: r.ok ? `${r.detail}  Run once:  cd platform/infra && ${r.apply_command}` : (r.detail || "link failed") } }));
    r.ok ? toast.success("Linked. Run the shown command once on the AI Studio host, then Test.") : toast.error(r.detail || "link failed");
    refresh();
  };

  const save = async () => {
    if (!f.name) { toast.error("Name required"); return; }
    const body: any = { name: f.name, transport: f.transport, enabled: f.enabled };
    if (f.transport === "stdio") { body.command = f.command; body.args = f.args.split(" ").filter(Boolean); }
    else body.url = f.url;
    try { await api.mcpAddServer(body); toast.success("MCP server saved"); setF({ ...BLANK }); refresh(); }
    catch (e: any) { toast.error(e.message); }
  };

  const test = async (s: any) => {
    const r = await api.mcpTestServer(s.id);
    if (r.ok) {
      toast.success(`Connected — ${r.tool_count} tools`);
      if (r.note) toast.info(r.note);
      setTools((t) => ({ ...t, [s.id]: r.tools || [] }));
      setStatus((st) => ({ ...st, [s.id]: { ok: true, msg: `${r.tool_count} tools available` } }));
    } else {
      toast.error(r.detail || "connection failed");
      setStatus((st) => ({ ...st, [s.id]: { ok: false, msg: r.detail || "connection failed" } }));
    }
  };

  return (
    <div>
      <div className="section-head">
        <div><h2>MCP Servers</h2><span className="muted">Connect Model Context Protocol servers (e.g. MLflow) — their tools become attachable to agents.</span></div>
      </div>

      <Callout icon="info-sign" style={{ marginBottom: 12 }}>
        Register a server here, click <b>Test</b> to discover its tools, then attach it to an agent in the
        Agent wizard (Tools → MCP). The agent will call the server's tools automatically.
      </Callout>

      <Card style={{ padding: 16, marginBottom: 16, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
        <FormGroup label="Name" style={{ minWidth: 180 }}>
          <InputGroup value={f.name} placeholder="MLflow (traces)" onChange={(e) => set("name", e.target.value)} />
        </FormGroup>
        <FormGroup label="Transport">
          <HTMLSelect value={f.transport} onChange={(e) => set("transport", e.target.value)}
            options={[{ label: "SSE (network)", value: "sse" },
                      { label: "Streamable HTTP (network)", value: "streamable-http" },
                      { label: "stdio (subprocess)", value: "stdio" }]} />
        </FormGroup>
        {f.transport === "stdio" ? (
          <>
            <FormGroup label="Command" style={{ minWidth: 140 }}>
              <InputGroup value={f.command} placeholder="uv" onChange={(e) => set("command", e.target.value)} />
            </FormGroup>
            <FormGroup label="Args" style={{ minWidth: 260 }}>
              <InputGroup value={f.args} placeholder="run --with mlflow[mcp] mlflow mcp run" onChange={(e) => set("args", e.target.value)} />
            </FormGroup>
          </>
        ) : (
          <FormGroup label="Server URL" style={{ minWidth: 320 }}>
            <InputGroup value={f.url} placeholder="http://mlflow-mcp:5000/sse" onChange={(e) => set("url", e.target.value)} />
          </FormGroup>
        )}
        <Button intent="primary" icon="cloud-upload" text="Save server" onClick={save} />
      </Card>

      {servers.length === 0 && <div className="muted" style={{ padding: 20 }}>No MCP servers registered yet.</div>}
      {servers.map((s) => (
        <Card key={s.id} style={{ padding: 14, marginBottom: 10 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <b>{s.name}</b> <Tag minimal>{s.transport}</Tag>{" "}
              <span className="muted" style={{ fontSize: 12 }}>{s.url || `${s.command} ${(s.args || []).join(" ")}`}</span>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <Button small icon="pulse" text="Test" onClick={() => test(s)} />
              <Button small minimal icon="trash" onClick={async () => { if (confirm(`Delete "${s.name}"?`)) { await api.mcpDeleteServer(s.id); refresh(); } }} />
            </div>
          </div>
          {s.env?.DSLAB_RUNTIME_ID && (
            <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
              Built-in DSLab server for runtime <b>{s.env.DSLAB_RUNTIME_NAME || s.env.DSLAB_RUNTIME_ID}</b>: runs Python,
              shell commands and notebooks on that machine. No URL or token needed — it goes through the
              platform's authenticated lab proxy and opens the lab automatically if it is closed.
            </div>
          )}
          {/* External jupyter-mcp container (optional). The target is read at container start. */}
          {(s.jupyter_url !== undefined || s.id === "mcp_jupyter") && (
            <div style={{ marginTop: 10, padding: 10, background: "var(--panel, #F4F7FB)", borderRadius: 8, border: "1px solid var(--border, #E1E8F0)" }}>
              <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>
                Optional external Jupyter MCP container. To drive a <b>DSLab runtime</b>, pick it and click
                <b> Link to DSLab runtime</b> (fills a stable URL via the lab proxy), then run the shown command once.
                For the simplest setup use <b>Enable agent access</b> on the runtime instead.
              </div>
              <div style={{ display: "flex", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
                <FormGroup label="Jupyter URL" style={{ marginBottom: 0, minWidth: 320 }}>
                  <InputGroup value={jcfg[s.id]?.url ?? s.jupyter_url ?? ""} placeholder="http://host.docker.internal:8888"
                    onChange={(e) => setJcfg((c) => ({ ...c, [s.id]: { ...(c[s.id] || { token: s.jupyter_token || "" }), url: e.target.value } }))} />
                </FormGroup>
                <FormGroup label="Jupyter token" style={{ marginBottom: 0, minWidth: 220 }}>
                  <InputGroup type="password" value={jcfg[s.id]?.token ?? s.jupyter_token ?? ""} placeholder="(token, if any)"
                    onChange={(e) => setJcfg((c) => ({ ...c, [s.id]: { ...(c[s.id] || { url: s.jupyter_url || "" }), token: e.target.value } }))} />
                </FormGroup>
                <FormGroup label="DSLab runtime" style={{ marginBottom: 0 }}>
                  <HTMLSelect value={linkRt || runtimes[0]?.id || ""} onChange={(e) => setLinkRt(e.target.value)}
                    options={runtimes.length ? runtimes.map((r) => ({ label: r.name, value: r.id })) : [{ label: "(no runtimes)", value: "" }]} />
                </FormGroup>
                <Button small intent="success" icon="data-lineage" text="Link to DSLab runtime" onClick={() => linkJupyter(s.id)} />
                <Button small icon="link" text="Save & Connect (manual URL)"
                  onClick={async () => {
                    const cfg = jcfg[s.id] || { url: s.jupyter_url || "", token: s.jupyter_token || "" };
                    const r = await api.mcpConnect(s.id, cfg.url, cfg.token);
                    if (r.ok) {
                      toast.success("Saved. Apply with the shown command, then Test.");
                      setStatus((st) => ({ ...st, [s.id]: { ok: true,
                        msg: `${r.detail}  Run:  ${r.apply_command || "docker compose up -d jupyter-mcp"}` } }));
                    } else {
                      toast.error(r.detail || "save failed");
                      setStatus((st) => ({ ...st, [s.id]: { ok: false, msg: r.detail || "save failed" } }));
                    }
                    refresh();
                  }} />
              </div>
            </div>
          )}
          {status[s.id] && (
            <div style={{ marginTop: 8, fontSize: 12, color: status[s.id].ok ? "var(--success, #1F9E6E)" : "var(--danger, #C0392B)" }}>
              {status[s.id].ok ? "✓ " : "✗ "}{status[s.id].msg}
            </div>
          )}
          {tools[s.id] && tools[s.id].length > 0 && (
            <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
              {tools[s.id].map((t) => <Tag key={t} minimal intent="success">{t}</Tag>)}
            </div>
          )}
        </Card>
      ))}
    </div>
  );
}
