import { useEffect, useState } from "react";
import { Card, HTMLSelect, HTMLTable, NumericInput, Switch, Tag, Button, Tabs, Tab, Callout, InputGroup, TextArea } from "@blueprintjs/core";
import { api } from "../api/client";

export function Governance() {
  const [gov, setGov] = useState<any>(null);
  const [audit, setAudit] = useState<any[]>([]);

  const refresh = () => { api.governance().then(setGov); api.audit().then(setAudit); };
  useEffect(() => { refresh(); const t = setInterval(refresh, 5000); return () => clearInterval(t); }, []);

  const save = async (patch: object) => { await api.updateGovernance(patch); refresh(); };
  if (!gov) return <div className="muted" style={{ padding: 20 }}>Loading…</div>;

  const b = gov.budget, s = gov.settings;
  const pct = Math.min(100, b.pct);

  return (
    <div>
      <div className="section-head">
        <div><h2>Governance &amp; Admin</h2><span className="muted">Roles · budget · guardrails · stability · audit</span></div>
      </div>

      <Tabs id="gov-tabs" defaultSelectedTabId="admin">
        <Tab id="admin" title="Access & Budget" panel={
          <div style={{ paddingTop: 12 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 16 }}>
        <Card style={{ padding: 16 }}>
          <b>Monthly token usage</b>
          <div style={{ display: "flex", justifyContent: "space-between", margin: "10px 0 6px" }}>
            <span className="metric" style={{ fontSize: 22, fontWeight: 700, color: b.over_budget ? "var(--danger)" : "var(--accent)" }}>
              {b.used_tokens.toLocaleString()}</span>
            <span className="muted metric">of {b.budget_tokens.toLocaleString()} · {b.pct}%</span>
          </div>
          <div className="gauge-track"><div className="gauge-fill"
            style={{ width: `${pct}%`, background: b.over_budget ? "var(--danger)" : undefined }} /></div>
          <div style={{ marginTop: 14 }}>
            <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>Monthly token budget</div>
            <NumericInput value={s.monthly_token_budget} min={1000} stepSize={100000} majorStepSize={1000000}
              onValueChange={(v) => save({ monthly_token_budget: v })} style={{ width: 180 }} />
          </div>
        </Card>

        <Card style={{ padding: 16 }}>
          <b>Access &amp; guardrails</b>
          <div style={{ marginTop: 10 }}>
            <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>Your role (RBAC)</div>
            <HTMLSelect value={s.role} onChange={(e) => save({ role: e.target.value })}
              options={["viewer", "builder", "admin"]} />
          </div>
          <div style={{ marginTop: 14 }}>
            <Switch label="PII redaction" checked={s.guardrails.pii_redaction}
              onChange={() => save({ guardrails: { ...s.guardrails, pii_redaction: !s.guardrails.pii_redaction } })} />
            <Switch label="Content filter" checked={s.guardrails.content_filter}
              onChange={() => save({ guardrails: { ...s.guardrails, content_filter: !s.guardrails.content_filter } })} />
            <Switch label="Require approval for destructive actions" checked={s.guardrails.require_approval_destructive}
              onChange={() => save({ guardrails: { ...s.guardrails, require_approval_destructive: !s.guardrails.require_approval_destructive } })} />
            <Switch label="SIEM export (OpenTelemetry)" checked={s.siem_export}
              onChange={() => save({ siem_export: !s.siem_export })} />
          </div>
        </Card>
      </div>
          </div>
        } />

        <Tab id="platform" title="Platform Settings" panel={<PlatformSettings />} />

        <Tab id="audit" title="Audit Log" panel={
      <Card style={{ marginTop: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <b>Audit log</b><Button minimal small icon="refresh" onClick={refresh} />
        </div>
        <HTMLTable compact striped style={{ width: "100%", marginTop: 8 }}>
          <thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Entity</th><th>Detail</th></tr></thead>
          <tbody>
            {audit.map((e, i) => (
              <tr key={i}>
                <td className="metric muted" style={{ fontSize: 11 }}>{new Date(e.ts).toLocaleString([], { hour12: false })}</td>
                <td>{e.actor}</td>
                <td><Tag minimal>{e.action}</Tag></td>
                <td className="muted">{e.entity_type}</td>
                <td>{e.detail}</td>
              </tr>
            ))}
            {audit.length === 0 && <tr><td colSpan={5} className="muted">No activity yet.</td></tr>}
          </tbody>
        </HTMLTable>
      </Card>
        } />
      </Tabs>
    </div>
  );
}

function PlatformSettings() {
  const [p, setP] = useState<any>(null);
  const [hosts, setHosts] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => { api.platformSettings().then((r) => { setP(r.effective); setHosts((r.effective.ssrf_allowed_hosts || []).join(", ")); }); }, []);
  if (!p) return <div className="muted" style={{ padding: 20 }}>Loading…</div>;

  const put = async (patch: object) => {
    const r = await api.updatePlatformSettings(patch);
    setP(r.effective); setSaved(true); setTimeout(() => setSaved(false), 1500);
  };
  const num = (label: string, key: string, help: string, min: number, max: number, step = 1) => (
    <div style={{ marginBottom: 14 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>{label}</div>
      <NumericInput value={p[key]} min={min} max={max} stepSize={step} style={{ width: 140 }}
        onValueChange={(v) => setP({ ...p, [key]: v })} onBlur={() => put({ [key]: p[key] })} />
      <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>{help}</div>
    </div>
  );

  return (
    <div style={{ paddingTop: 12, maxWidth: 900 }}>
      <Callout icon="cog" intent="primary" style={{ marginBottom: 14 }}>
        These control platform <b>stability & safety</b>. Changes save automatically and take effect on the next run —
        no backend edits needed. {saved && <b style={{ color: "var(--accent)" }}> ✓ saved</b>}
      </Callout>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <Card style={{ padding: 16 }}>
          <b>Concurrency & timeouts</b>
          <div style={{ marginTop: 12 }}>
            {num("Max concurrent runs", "max_concurrent_runs", "Runs beyond this queue until a slot frees up.", 1, 100)}
            {num("Per-run timeout (seconds)", "run_timeout_seconds", "A run is stopped cleanly if it exceeds this.", 10, 3600, 10)}
          </div>
        </Card>
        <Card style={{ padding: 16 }}>
          <b>Retries & limits</b>
          <div style={{ marginTop: 12 }}>
            {num("Retry attempts", "retry_attempts", "Extra tries on a transient model/tool failure.", 0, 6)}
            {num("Retry backoff (seconds)", "retry_backoff_seconds", "Base wait between retries (grows each try).", 0, 30)}
            {num("Max request size (KB)", "max_request_kb", "Requests larger than this are rejected.", 16, 10240, 16)}
          </div>
        </Card>
      </div>
      <Card style={{ padding: 16, marginTop: 16 }}>
        <b>Outbound tool-call safety (SSRF)</b>
        <div style={{ marginTop: 10 }}>
          <Switch label="Block calls to private / internal addresses" checked={p.ssrf_block_private}
            onChange={() => put({ ssrf_block_private: !p.ssrf_block_private })} />
          <div className="muted" style={{ fontSize: 12, margin: "2px 0 12px" }}>
            When on, tools/webhooks can only call public addresses. Public APIs (e.g. your Azure endpoint) work normally;
            calls to internal/private IPs are blocked unless listed below.
          </div>
          <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>Allowed internal hosts (comma-separated)</div>
          <div style={{ display: "flex", gap: 8 }}>
            <InputGroup fill placeholder="internal-api.corp, 10.0.0.5" value={hosts}
              onChange={(e) => setHosts(e.target.value)} />
            <Button intent="primary" text="Save hosts"
              onClick={() => put({ ssrf_allowed_hosts: hosts.split(",").map((h) => h.trim()).filter(Boolean) })} />
          </div>
        </div>
      </Card>
      <CompressionSettings />
    </div>
  );
}

function CompressionSettings() {
  const [c, setC] = useState<any>(null);
  const [endpoints, setEndpoints] = useState<any[]>([]);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    api.compressionConfig().then(setC).catch(() => {});
    api.listEndpoints().then((e: any[]) => setEndpoints(e.filter((x) => (x.type || "chat") === "chat"))).catch(() => {});
  }, []);
  if (!c) return null;
  const put = async (patch: object) => {
    const next = { ...c, ...patch };
    setC(next);
    await api.updateGovernance({ compression: next });
    setSaved(true); setTimeout(() => setSaved(false), 1500);
  };
  return (
    <Card style={{ padding: 16, marginTop: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <b>Conversation context compression</b>
        {saved && <span style={{ color: "var(--accent)", fontSize: 12 }}>✓ saved</span>}
      </div>
      <div className="muted" style={{ fontSize: 12, margin: "4px 0 10px" }}>
        When on, long Chat conversations are compressed (rolling summary + recent turns) before
        being sent to the model, saving context. When off, nothing changes and the UI meter is hidden.
      </div>
      <Switch large checked={!!c.enabled} label="Enable context compression"
        onChange={() => put({ enabled: !c.enabled })} />
      {c.enabled && (
        <div style={{ marginTop: 10 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
            <div>
              <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>Summarizer model (Model Endpoint)</div>
              <HTMLSelect fill value={c.endpoint_id || ""} onChange={(e) => put({ endpoint_id: e.target.value })}
                options={[{ label: endpoints.length ? "— local fallback —" : "no chat endpoints (uses local fallback)", value: "" },
                          ...endpoints.map((e) => ({ label: e.label || e.model, value: e.id }))]} />
              <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>If none is set (or a call fails), a local offline summarizer is used.</div>
            </div>
            <div>
              <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>Compress after (tokens)</div>
              <NumericInput value={c.trigger_tokens} min={500} max={100000} stepSize={500} style={{ width: 140 }}
                onValueChange={(v) => setC({ ...c, trigger_tokens: v })} onBlur={() => put({ trigger_tokens: c.trigger_tokens })} />
              <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>Transcript is compressed once it exceeds this size.</div>
            </div>
            <div>
              <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>Keep recent turns (verbatim)</div>
              <NumericInput value={c.keep_recent_turns} min={1} max={30} style={{ width: 140 }}
                onValueChange={(v) => setC({ ...c, keep_recent_turns: v })} onBlur={() => put({ keep_recent_turns: c.keep_recent_turns })} />
            </div>
            <div>
              <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>Target summary size (tokens)</div>
              <NumericInput value={c.target_summary_tokens} min={100} max={2000} stepSize={50} style={{ width: 140 }}
                onValueChange={(v) => setC({ ...c, target_summary_tokens: v })} onBlur={() => put({ target_summary_tokens: c.target_summary_tokens })} />
            </div>
          </div>
          <div className="muted" style={{ fontSize: 11, margin: "12px 0 4px" }}>
            Compression prompt (scientific — edit to tune what's preserved). Placeholders:
            <code> {"{history}"} </code> and <code> {"{target_tokens}"} </code>.
          </div>
          <TextArea fill rows={10} value={c.prompt || ""} style={{ fontFamily: "var(--mono)", fontSize: 12 }}
            onChange={(e) => setC({ ...c, prompt: (e.target as HTMLTextAreaElement).value })} />
          <Button intent="primary" icon="floppy-disk" text="Save prompt" style={{ marginTop: 8 }}
            onClick={() => put({ prompt: c.prompt })} />
        </div>
      )}
    </Card>
  );
}
