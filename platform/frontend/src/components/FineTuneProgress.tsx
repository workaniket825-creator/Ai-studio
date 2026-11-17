import { useState } from "react";
import { Button, Callout, Collapse, Icon, ProgressBar, Tag } from "@blueprintjs/core";

// Structured progress of a fine-tuning run (run.progress, kind === "finetune").
// Rendered in Chat (inside the workflow's reply bubble) and in the Run view. The data is
// persisted on the run by the backend, so it survives reloads and backend restarts.
export type FineTuneProgressData = {
  kind?: string; stage?: string; state?: string;
  stages?: { key: string; label: string; status: string; detail?: string }[];
  selection?: { notebook?: string; title?: string; method?: string; confidence?: number; reason?: string;
                parameters?: Record<string, unknown>; dataset?: { path: string } | null };
  runtime?: { name?: string; gpu_type?: string };
  job?: { pid?: number; remote_dir?: string; started_at?: string; ended_at?: string };
  cells?: { total?: number; completed?: number; number?: number; title?: string };
  bar?: { n: number; total: number; desc?: string; eta_s?: number } | null;
  custom?: Record<string, any>;
  cell_fraction?: number; cell_eta_s?: number | null; percent?: number; elapsed_s?: number;
  train?: { loss?: number; eval_loss?: number; epoch?: number; step?: number; loss_key?: string;
            loss_history?: { step: number; value: number }[] };
  log_tail?: string[]; warnings?: string[]; contact_warning?: string;
  mlflow?: { url?: string; run_id?: string; experiment?: string; error?: string };
  mlflow_reachable?: boolean | null;
  output_dir?: string;
  outputs?: { files?: number; copied?: number; copied_bytes?: number };
  error?: string; updated_at?: string;
};

const STAGE_ICON: Record<string, { icon: any; color: string }> = {
  done: { icon: "tick-circle", color: "var(--success)" },
  active: { icon: "refresh", color: "var(--accent-2)" },
  failed: { icon: "error", color: "var(--danger)" },
  skipped: { icon: "minus", color: "var(--muted)" },
  pending: { icon: "circle", color: "var(--border)" },
};

export function fmtDuration(s?: number | null) {
  if (s == null || !isFinite(s)) return "";
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : m ? `${m}m ${String(sec).padStart(2, "0")}s` : `${sec}s`;
}

function fmtBytes(n?: number) {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0; let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i ? 1 : 0)} ${u[i]}`;
}

function fmtNum(v: any) {
  if (typeof v !== "number") return String(v);
  if (Number.isInteger(v)) return String(v);
  return Math.abs(v) >= 100 ? v.toFixed(1) : String(Number(v.toPrecision(4)));
}

function Sparkline({ points }: { points: { step: number; value: number }[] }) {
  if (!points || points.length < 2) return null;
  const w = 160, h = 34, pad = 2;
  const xs = points.map((p) => p.step), ys = points.map((p) => p.value);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const sx = (x: number) => pad + ((x - x0) / Math.max(1e-9, x1 - x0)) * (w - 2 * pad);
  const sy = (y: number) => h - pad - ((y - y0) / Math.max(1e-9, y1 - y0)) * (h - 2 * pad);
  const d = points.map((p, i) => `${i ? "L" : "M"}${sx(p.step).toFixed(1)},${sy(p.value).toFixed(1)}`).join(" ");
  const last = points[points.length - 1];
  return (
    <svg width={w} height={h} role="img" aria-label="training loss trend" style={{ display: "block" }}>
      <path d={d} fill="none" stroke="var(--accent)" strokeWidth={1.5} />
      <circle cx={sx(last.step)} cy={sy(last.value)} r={2.5} fill="var(--accent-2)" />
    </svg>
  );
}

export function FineTuneProgress({ p, status, error, onStop, compact = false }: {
  p: FineTuneProgressData; status?: string; error?: string; onStop?: () => void; compact?: boolean;
}) {
  const [logOpen, setLogOpen] = useState(false);
  const [notesOpen, setNotesOpen] = useState(false);
  const running = status === "running" || status === "pending";
  const state = running ? "running" : status === "succeeded" ? "completed"
    : status === "cancelled" ? "stopped" : status === "failed" ? "failed" : (p.state || status || "");
  const stateIntent: any = { running: "primary", completed: "success", stopped: "warning", failed: "danger" }[state] || "none";
  const cells = p.cells || {};
  const sel = p.selection || {};
  const tr = p.train || {};
  const custom = p.custom || {};
  const step = custom.step ?? tr.step;
  const totalSteps = custom.total_steps;
  const executing = p.stage === "execute" && running;
  const pct = typeof p.percent === "number" ? p.percent : 0;
  const elapsed = p.elapsed_s ?? undefined;
  const stageDetail = (p.stages || []).find((s) => s.key === p.stage);

  return (
    <div className="ft-progress" style={{ border: "1px solid var(--border)", borderRadius: 10,
      background: "var(--panel)", padding: compact ? 10 : 14, fontSize: 12 }}>
      {/* header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <Icon icon="predictive-analysis" color="var(--accent)" />
        <b style={{ fontSize: 13 }}>Fine-tuning</b>
        <Tag minimal round intent={stateIntent}>{state || "starting"}</Tag>
        {sel.notebook && <Tag minimal icon="document">{sel.notebook}</Tag>}
        {p.runtime?.name && <Tag minimal icon="lab-test">{p.runtime.name}{p.runtime.gpu_type ? ` · ${p.runtime.gpu_type}` : ""}</Tag>}
        {elapsed != null && p.job?.started_at && <span className="muted metric">{fmtDuration(elapsed)} elapsed</span>}
        {running && onStop && (
          <Button small minimal intent="danger" icon="stop" text="Stop" onClick={onStop} style={{ marginLeft: "auto" }} />
        )}
      </div>

      {/* stage tracker */}
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap", margin: "10px 0 8px" }}>
        {(p.stages || []).map((s) => {
          const st = STAGE_ICON[s.status] || STAGE_ICON.pending;
          const isActive = s.status === "active";
          return (
            <span key={s.key} title={s.detail || s.label}
              style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", borderRadius: 999,
                border: `1px solid ${isActive ? "var(--accent)" : "var(--border)"}`,
                background: isActive ? "rgba(118,185,0,.10)" : "transparent",
                color: s.status === "pending" || s.status === "skipped" ? "var(--muted)" : "var(--text)" }}>
              <Icon icon={st.icon} size={11} color={st.color} className={isActive ? "ft-spin" : undefined} />
              {s.label}
            </span>
          );
        })}
      </div>

      {/* what is happening now */}
      {running && stageDetail && p.stage !== "execute" && (
        <div className="muted" style={{ marginBottom: 6 }}>
          <span className="thinking-dots">{stageDetail.label}</span>
        </div>
      )}

      {(executing || (cells.total ?? 0) > 0) && (
        <div style={{ margin: "6px 0 8px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 4 }}>
            <span>
              {cells.total ? <>Cell <b className="metric">{cells.number ?? cells.completed ?? 0}/{cells.total}</b></> : "Starting job"}
              {cells.title ? <span className="muted"> · {cells.title}</span> : null}
            </span>
            <span className="metric">{pct.toFixed(0)}%</span>
          </div>
          <ProgressBar value={Math.max(0.02, pct / 100)} intent={state === "failed" ? "danger" : state === "stopped" ? "warning" : "success"}
            animate={executing} stripes={executing} />
          {(totalSteps || p.bar) && executing && (
            <div className="muted" style={{ marginTop: 4, display: "flex", gap: 10, flexWrap: "wrap" }}>
              {totalSteps ? <span>step <b className="metric">{step}/{totalSteps}</b></span>
                : p.bar ? <span>{p.bar.desc || "progress"} <b className="metric">{p.bar.n}/{p.bar.total}</b></span> : null}
              {p.cell_fraction != null && <span className="metric">{Math.round((p.cell_fraction || 0) * 100)}% of this cell</span>}
              {p.cell_eta_s ? <span>≈ {fmtDuration(p.cell_eta_s)} left in this cell</span> : null}
            </div>
          )}
        </div>
      )}

      {/* training metrics */}
      {(tr.loss != null || tr.eval_loss != null || custom.loss != null) && (
        <div style={{ display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap", margin: "6px 0" }}>
          {[["loss", tr.loss ?? custom.loss], ["eval loss", tr.eval_loss ?? custom.eval_loss],
            ["epoch", tr.epoch ?? custom.epoch], ["step", step]].filter(([, v]) => v != null).map(([k, v]) => (
            <div key={k as string}>
              <div className="muted" style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: ".06em" }}>{k}</div>
              <div className="metric" style={{ fontSize: 14, fontWeight: 600 }}>{fmtNum(v)}</div>
            </div>
          ))}
          {tr.loss_history && tr.loss_history.length > 1 && (
            <div title={`${tr.loss_key || "loss"} from MLflow`}><Sparkline points={tr.loss_history} /></div>
          )}
        </div>
      )}

      {p.contact_warning && (
        <Callout intent="warning" icon="offline" style={{ margin: "6px 0", fontSize: 12 }}>{p.contact_warning}</Callout>
      )}
      {!running && (state === "failed" || state === "stopped") && (error || p.error) && (
        <Callout intent={state === "failed" ? "danger" : "warning"} icon="error" style={{ margin: "6px 0", fontSize: 12 }}>
          {error || p.error}
        </Callout>
      )}

      {/* results */}
      {!running && p.outputs && (
        <div className="muted" style={{ margin: "6px 0" }}>
          {p.outputs.files ?? 0} output file(s) · {p.outputs.copied ?? 0} copied to File Storage ({fmtBytes(p.outputs.copied_bytes)})
        </div>
      )}

      {/* links */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginTop: 6 }}>
        {p.mlflow?.url && (
          <a href={p.mlflow.url} target="_blank" rel="noreferrer">
            <Button small minimal icon="timeline-line-chart" text="MLflow run" rightIcon="share" />
          </a>
        )}
        {p.mlflow_reachable === false && <Tag minimal intent="warning" icon="warning-sign">notebook can't reach MLflow</Tag>}
        {p.output_dir && (
          <Tag minimal icon="folder-close" interactive title="Copy the File Storage path"
            onClick={() => { try { navigator.clipboard.writeText(p.output_dir!); } catch { /* ignore */ } }}>
            {p.output_dir}
          </Tag>
        )}
        {(p.log_tail?.length ?? 0) > 0 && (
          <Button small minimal icon="console" text={logOpen ? "Hide log" : "Live log"} onClick={() => setLogOpen(!logOpen)} />
        )}
        {(p.warnings?.length ?? 0) > 0 && (
          <Button small minimal icon="info-sign" text={`Notes (${p.warnings!.length})`} onClick={() => setNotesOpen(!notesOpen)} />
        )}
      </div>
      <Collapse isOpen={logOpen}>
        <pre style={{ margin: "6px 0 0", maxHeight: 220, overflow: "auto", fontSize: 11, fontFamily: "var(--mono)",
          background: "var(--app-bg)", border: "1px solid var(--border)", borderRadius: 6, padding: 8, whiteSpace: "pre-wrap" }}>
          {(p.log_tail || []).join("\n")}
        </pre>
      </Collapse>
      <Collapse isOpen={notesOpen}>
        <ul style={{ margin: "6px 0 0", paddingLeft: 18 }} className="muted">
          {(p.warnings || []).map((w, i) => <li key={i}>{w.replace(/`/g, "")}</li>)}
        </ul>
      </Collapse>
    </div>
  );
}
