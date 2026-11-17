import { useEffect, useState } from "react";
import { Card, Button, Tag, InputGroup, NonIdealState, Breadcrumbs, Callout,
  Dialog, DialogBody, HTMLTable, Icon, NumericInput, FormGroup, HTMLSelect } from "@blueprintjs/core";
import { api } from "../api/client";
import { toast } from "../components/toaster";

export function Files() {
  const [prefix, setPrefix] = useState("shared");
  const [ftCfg, setFtCfg] = useState<any>(null);
  const [catalog, setCatalog] = useState<Record<string, any>>({});
  const [showFt, setShowFt] = useState(false);
  const [entries, setEntries] = useState<any[]>([]);
  const [cfg, setCfg] = useState<any>(null);
  const [preview, setPreview] = useState<{ path: string; content: string } | null>(null);
  const [showSettings, setShowSettings] = useState(false);

  const refresh = (p = prefix) => api.filesList(p).then((r) => setEntries(r.entries));
  useEffect(() => { api.filesConfig().then(setCfg); api.ftConfig().then(setFtCfg).catch(() => {}); }, []);
  useEffect(() => { refresh(prefix); /* eslint-disable-next-line */ }, [prefix]);
  const nbDir = ftCfg?.notebooks_dir || "finetuning/notebooks";
  const inNotebooks = prefix === nbDir || prefix.startsWith(nbDir + "/");
  // in the fine-tuning notebooks folder, show how the planner sees each notebook
  useEffect(() => {
    if (!inNotebooks) return;
    api.ftCatalog().then((c) => setCatalog(Object.fromEntries((c.notebooks || []).map((n: any) => [n.path, n])))).catch(() => {});
  }, [inNotebooks, entries]);

  const crumbs = prefix.split("/").filter(Boolean).map((seg, i, arr) => ({
    text: seg, onClick: () => setPrefix(arr.slice(0, i + 1).join("/")),
  }));

  const onUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      const b64 = (reader.result as string).split(",")[1];
      try { await api.filesUpload(file.name, prefix, b64); toast.success(`Uploaded ${file.name}`); refresh(); }
      catch (err: any) { toast.error(err.message); }
    };
    reader.readAsDataURL(file);
    e.target.value = "";
  };

  const newFolder = async () => {
    const name = prompt("New folder name:"); if (!name) return;
    await api.filesMkdir(`${prefix}/${name}`); refresh();
  };

  return (
    <div>
      <div className="section-head">
        <div><h2>File Storage</h2>
          <span className="muted">Shared workspace on this instance — drop files for agents, collect what they generate.</span></div>
        <Button minimal icon="cog" onClick={() => setShowSettings(true)} />
      </div>

      <Callout icon="folder-shared-open" intent="primary" style={{ marginBottom: 12 }}>
        Files here are readable/writable by agents granted a matching <b>Workspace folder</b>. Put inputs in a
        folder (e.g. <code>shared/invoices</code>), point an agent at it, and its generated files appear back here.
      </Callout>

      {ftCfg && (
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
          <span className="muted" style={{ fontSize: 12, marginRight: 4 }}><Icon icon="predictive-analysis" size={12} /> Fine-tuning:</span>
          <Button small icon="document" text="Notebooks" active={inNotebooks} onClick={() => setPrefix(nbDir)} />
          <Button small icon="database" text="Datasets" active={prefix.startsWith(ftCfg.datasets_dir)} onClick={() => setPrefix(ftCfg.datasets_dir)} />
          <Button small icon="history" text="Run outputs" active={prefix.startsWith(ftCfg.runs_dir)} onClick={() => setPrefix(ftCfg.runs_dir)} />
          <Button small minimal icon="cog" text="Fine-tuning settings" onClick={() => setShowFt(true)} />
        </div>
      )}

      {inNotebooks && (
        <Callout icon="lightbulb" style={{ marginBottom: 12 }}>
          Upload your fine-tuning notebooks (<code>.ipynb</code>) here. The <b>Fine-Tuning (DSLab)</b> workflow picks one per request
          from its first markdown cell, its <code>studio_finetune</code> metadata and its cell tagged <code>parameters</code> —
          see <code>README.md</code> in this folder for the conventions.
        </Callout>
      )}

      <Card style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
          <Breadcrumbs items={[{ text: "root", onClick: () => setPrefix("") }, ...crumbs]} />
          <div style={{ display: "flex", gap: 6 }}>
            <label className="bp5-button bp5-small" style={{ cursor: "pointer" }}>
              <Icon icon="upload" /> <span style={{ marginLeft: 4 }}>Upload</span>
              <input type="file" style={{ display: "none" }} onChange={onUpload} />
            </label>
            <Button small icon="folder-new" text="New folder" onClick={newFolder} />
            <Button small minimal icon="refresh" onClick={() => refresh()} />
          </div>
        </div>
      </Card>

      {entries.length === 0 ? (
        <NonIdealState icon="folder-open" title="Empty folder"
          description="Upload a file or create a subfolder to get started." />
      ) : (
        <Card style={{ padding: 0 }}>
          <HTMLTable interactive style={{ width: "100%" }}>
            <thead><tr><th>Name</th><th>Size</th><th>Modified</th><th style={{ textAlign: "right" }}>Actions</th></tr></thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.path}>
                  <td>
                    {e.type === "folder" ? (
                      <a onClick={() => setPrefix(e.path)} style={{ cursor: "pointer" }}>
                        <Icon icon="folder-close" style={{ marginRight: 6 }} />{e.name}</a>
                    ) : (<span><Icon icon="document" style={{ marginRight: 6 }} />{e.name}</span>)}
                    {inNotebooks && catalog[e.path] && (
                      <div className="muted" style={{ fontSize: 11, marginLeft: 22 }}>
                        {catalog[e.path].title || "(no description)"} · {catalog[e.path].parameters?.length || 0} parameters
                        {(catalog[e.path].warnings || []).map((w: string, i: number) => (
                          <Tag key={i} minimal intent="warning" style={{ marginLeft: 6 }}>{w.split(" - ")[0]}</Tag>))}
                      </div>
                    )}
                  </td>
                  <td className="muted metric" style={{ fontSize: 12 }}>{e.type === "file" ? fmtSize(e.size) : "—"}</td>
                  <td className="muted metric" style={{ fontSize: 12 }}>{e.modified ? new Date(e.modified * 1000).toLocaleString([], { hour12: false }) : "—"}</td>
                  <td style={{ textAlign: "right" }}>
                    {e.type === "file" && <>
                      <Button small minimal icon="eye-open" title="Preview"
                        onClick={async () => { try { setPreview(await api.filesPreview(e.path)); } catch { toast.error("Not previewable"); } }} />
                      <a href={api.filesDownloadUrl(e.path)}><Button small minimal icon="download" title="Download" /></a>
                    </>}
                    <Button small minimal intent="danger" icon="trash" title="Delete"
                      onClick={async () => { if (confirm(`Delete ${e.name}?`)) { await api.filesDelete(e.path); refresh(); } }} />
                  </td>
                </tr>
              ))}
            </tbody>
          </HTMLTable>
        </Card>
      )}

      <Dialog isOpen={!!preview} onClose={() => setPreview(null)} title={preview?.path} style={{ width: 700 }}>
        <DialogBody>
          <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, maxHeight: "60vh", overflow: "auto" }}>{preview?.content}</pre>
        </DialogBody>
      </Dialog>

      <Dialog isOpen={showFt} onClose={() => setShowFt(false)} title="Fine-tuning settings" style={{ width: 600 }}>
        <DialogBody>
          {ftCfg && <FineTuneSettings cfg={ftCfg} onSaved={(c) => { setFtCfg({ ...ftCfg, ...c }); setShowFt(false); }} />}
        </DialogBody>
      </Dialog>

      <Dialog isOpen={showSettings} onClose={() => setShowSettings(false)} title="File Storage settings" style={{ width: 560 }}>
        <DialogBody>
          {cfg && <SettingsForm cfg={cfg} onSaved={(c) => { setCfg(c); setShowSettings(false); }} />}
        </DialogBody>
      </Dialog>
    </div>
  );
}

function SettingsForm({ cfg, onSaved }: { cfg: any; onSaved: (c: any) => void }) {
  const [c, setC] = useState({ ...cfg });
  return (
    <div>
      <Callout icon="info-sign" style={{ marginBottom: 12 }}>
        Backend is the instance's local storage. Azure Blob will be added later.
      </Callout>
      <FormGroup label="Backend"><InputGroup value="local (instance storage)" disabled /></FormGroup>
      <FormGroup label="Storage root path" helperText="Folder on this instance where all files live">
        <InputGroup value={c.root_path} onChange={(e) => setC({ ...c, root_path: e.target.value })} /></FormGroup>
      <FormGroup label="Max file size (KB)">
        <NumericInput value={c.max_file_kb} min={16} stepSize={1024} onValueChange={(v) => setC({ ...c, max_file_kb: v })} /></FormGroup>
      <FormGroup label="Allowed extensions" helperText="comma-separated, blank = allow all (e.g. csv,txt,pdf)">
        <InputGroup value={(c.allowed_ext || []).join(", ")}
          onChange={(e) => setC({ ...c, allowed_ext: e.target.value.split(",").map((x) => x.trim()).filter(Boolean) })} /></FormGroup>
      <Button intent="primary" icon="floppy-disk" text="Save"
        onClick={async () => { const saved = await api.filesUpdateConfig({ root_path: c.root_path, max_file_kb: c.max_file_kb, allowed_ext: c.allowed_ext }); toast.success("Saved"); onSaved(saved); }} />
    </div>
  );
}

function FineTuneSettings({ cfg, onSaved }: { cfg: any; onSaved: (c: any) => void }) {
  const [c, setC] = useState({ ...cfg });
  const [runtimes, setRuntimes] = useState<any[]>([]);
  useEffect(() => { api.ftRuntimes().then((r) => setRuntimes(r.runtimes || [])).catch(() => {}); }, []);
  const num = (k: string, label: string, help = "") => (
    <FormGroup label={label} helperText={help} style={{ marginBottom: 8 }}>
      <NumericInput fill value={c[k]} min={1} onValueChange={(v) => setC({ ...c, [k]: v })} /></FormGroup>);
  return (
    <div>
      <FormGroup label="Default DSLab runtime" helperText="Used when a request names no runtime.">
        <HTMLSelect fill value={c.default_runtime_id} onChange={(e) => setC({ ...c, default_runtime_id: e.target.value })}
          options={[{ label: "Automatic (the only runtime, or the one with agent access)", value: "" },
            ...runtimes.map((r) => ({ label: r.name, value: r.id }))]} />
      </FormGroup>
      <FormGroup label="MLflow URI used by notebooks on the runtime"
        helperText={`Must be reachable FROM the DSLab machine. Blank = the runtime's own MLflow URI, then the backend's (${cfg.backend_mlflow_uri || "not set"}).`}>
        <InputGroup value={c.remote_mlflow_uri} placeholder="http://<platform-host>:5000" onChange={(e) => setC({ ...c, remote_mlflow_uri: e.target.value })} /></FormGroup>
      <FormGroup label="MLflow UI link (for the browser)" helperText={`Blank = MLFLOW_UI_URL / tracking URI (now: ${cfg.mlflow_ui_url_effective || "—"})`}>
        <InputGroup value={c.mlflow_ui_url} placeholder="http://localhost:5000" onChange={(e) => setC({ ...c, mlflow_ui_url: e.target.value })} /></FormGroup>
      <FormGroup label="MLflow experiment"><InputGroup value={c.experiment} onChange={(e) => setC({ ...c, experiment: e.target.value })} /></FormGroup>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 16px" }}>
        {num("job_timeout_hours", "Job time limit (h)", "stopped on the runtime after this")}
        {num("poll_seconds", "Progress check every (s)")}
        {num("copy_max_file_mb", "Copy output files up to (MB)", "larger ones stay on the runtime + MLflow")}
        {num("copy_max_total_mb", "Copy at most (MB in total)")}
        {num("dataset_max_mb", "Largest dataset to stage (MB)")}
      </div>
      <Button intent="primary" icon="floppy-disk" text="Save" style={{ marginTop: 8 }}
        onClick={async () => { try { const saved = await api.ftSetConfig(c); toast.success("Saved"); onSaved(saved); } catch (e: any) { toast.error(e.message); } }} />
    </div>
  );
}

function fmtSize(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
