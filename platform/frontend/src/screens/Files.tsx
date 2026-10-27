import { useEffect, useState } from "react";
import { Card, Button, Tag, InputGroup, NonIdealState, Breadcrumbs, Callout,
  Dialog, DialogBody, HTMLTable, Icon, NumericInput, FormGroup } from "@blueprintjs/core";
import { api } from "../api/client";
import { toast } from "../components/toaster";

export function Files() {
  const [prefix, setPrefix] = useState("shared");
  const [entries, setEntries] = useState<any[]>([]);
  const [cfg, setCfg] = useState<any>(null);
  const [preview, setPreview] = useState<{ path: string; content: string } | null>(null);
  const [showSettings, setShowSettings] = useState(false);

  const refresh = (p = prefix) => api.filesList(p).then((r) => setEntries(r.entries));
  useEffect(() => { api.filesConfig().then(setCfg); }, []);
  useEffect(() => { refresh(prefix); /* eslint-disable-next-line */ }, [prefix]);

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

function fmtSize(n: number) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
