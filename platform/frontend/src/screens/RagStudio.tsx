import { useEffect, useState, useRef } from "react";
import { Card, Button, Tag, InputGroup, FormGroup, HTMLSelect, TextArea, Callout,
  Spinner, ProgressBar, NumericInput, Icon, Divider, NonIdealState } from "@blueprintjs/core";
import { api } from "../api/client";
import { toast } from "../components/toaster";

/** RAG Studio — create knowledge pipelines, configure processing/chunking/embeddings,
 *  ingest documents (runs server-side; survives navigation), inspect the index, and
 *  test retrieval. A ready pipeline can be linked to agents (search_knowledge tool) and Chat. */

const STATUS: Record<string, string> = { empty: "none", ingesting: "warning", ready: "success", error: "danger" };

export function RagStudio() {
  const [pipes, setPipes] = useState<any[]>([]);
  const [sel, setSel] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");

  const refresh = () => api.ragList().then(setPipes);
  useEffect(() => { refresh(); const t = setInterval(refresh, 4000); return () => clearInterval(t); }, []);

  const create = async () => {
    if (!newName.trim()) return;
    const p = await api.ragCreate({ name: newName.trim() });
    toast.success("Pipeline created"); setNewName(""); setCreating(false); await refresh(); setSel(p.id);
  };

  return (
    <div>
      <div className="section-head">
        <div>
          <h2>RAG Studio — Knowledge Pipelines</h2>
          <span className="muted" style={{ fontSize: 13 }}>Ingest documents into a searchable index, then link it to agents or Chat.</span>
        </div>
        <Button intent="primary" icon="plus" text="New pipeline" onClick={() => setCreating(true)} />
      </div>

      {creating && (
        <Card style={{ marginBottom: 12, display: "flex", gap: 8, alignItems: "flex-end" }}>
          <FormGroup label="Pipeline name" style={{ marginBottom: 0, flex: 1 }}>
            <InputGroup value={newName} autoFocus onChange={(e) => setNewName(e.target.value)}
              placeholder="e.g. HR Policies, Engineering Docs" onKeyDown={(e) => { if (e.key === "Enter") create(); }} />
          </FormGroup>
          <Button intent="primary" text="Create" onClick={create} />
          <Button minimal text="Cancel" onClick={() => setCreating(false)} />
        </Card>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "300px 1fr", gap: 14 }}>
        {/* pipelines list — always shows current status (survives navigation) */}
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {pipes.length === 0 && <Callout icon="database">No pipelines yet. Create one to start ingesting knowledge.</Callout>}
          {pipes.map((p) => (
            <Card key={p.id} interactive onClick={() => setSel(p.id)}
              style={{ padding: 12, border: sel === p.id ? "1px solid var(--accent)" : undefined }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <b style={{ fontSize: 14 }}>{p.name}</b>
                <Tag minimal intent={STATUS[p.status] as any}>
                  {p.status === "ingesting" ? <span><Spinner size={12} /> ingesting</span> : p.status}</Tag>
              </div>
              <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>
                {p.stats?.documents || 0} docs · {p.stats?.chunks || 0} chunks · {(p.stats?.tokens || 0).toLocaleString()} tokens
              </div>
            </Card>
          ))}
        </div>

        {/* detail */}
        <div>{sel ? <PipelineDetail pid={sel} onChange={refresh} onDeleted={() => { setSel(null); refresh(); }} />
          : <NonIdealState icon="arrow-left" title="Select a pipeline" description="Pick a pipeline to configure, ingest, and inspect." />}</div>
      </div>
    </div>
  );
}

function PipelineDetail({ pid, onChange, onDeleted }: { pid: string; onChange: () => void; onDeleted: () => void }) {
  const [p, setP] = useState<any>(null);
  const [tab, setTab] = useState<"config" | "ingest" | "index" | "test">("ingest");
  const load = () => api.ragGet(pid).then(setP);
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [pid]);
  if (!p) return <Spinner />;

  return (
    <Card>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div><b style={{ fontSize: 16 }}>{p.name}</b>
          <Tag minimal intent={STATUS[p.status] as any} style={{ marginLeft: 8 }}>{p.status}</Tag></div>
        <div style={{ display: "flex", gap: 6 }}>
          <Button minimal small icon="trash" intent="danger"
            onClick={async () => { if (confirm(`Delete pipeline "${p.name}" and its index?`)) { await api.ragDelete(pid); toast.success("Deleted"); onDeleted(); } }} />
        </div>
      </div>
      <div style={{ display: "flex", gap: 4, margin: "10px 0" }}>
        {(["ingest", "config", "index", "test"] as const).map((t) => (
          <Button key={t} small minimal active={tab === t} onClick={() => setTab(t)}
            text={{ ingest: "Ingest", config: "Configuration", index: "Index catalog", test: "Test retrieval" }[t]} />
        ))}
      </div>
      <Divider />
      {tab === "config" && <ConfigTab p={p} onSaved={() => { load(); onChange(); }} />}
      {tab === "ingest" && <IngestTab p={p} onDone={() => { load(); onChange(); }} />}
      {tab === "index" && <IndexTab pid={pid} />}
      {tab === "test" && <TestTab pid={pid} ready={p.status === "ready"} />}
    </Card>
  );
}

function ConfigTab({ p, onSaved }: { p: any; onSaved: () => void }) {
  const [cfg, setCfg] = useState<any>(p.config);
  const [eps, setEps] = useState<any>({ embedding: [], ocr: [], multimodal: [], has_embedding: false });
  const [preview, setPreview] = useState<any>(null);
  const [sample, setSample] = useState("Paste a sample paragraph to preview how it will be chunked. " .repeat(6));
  useEffect(() => { api.ragEmbeddingEndpoints().then(setEps); }, []);
  const setC = (path: string[], v: any) => {
    const next = structuredClone(cfg); let o = next; for (let i = 0; i < path.length - 1; i++) o = o[path[i]];
    o[path[path.length - 1]] = v; setCfg(next);
  };
  const save = async () => { await api.ragUpdate(p.id, { config: cfg }); toast.success("Configuration saved"); onSaved(); };
  const doPreview = async () => setPreview(await api.ragPreviewChunking(sample, cfg.chunking));

  return (
    <div>
      <div className="muted" style={{ textTransform: "uppercase", letterSpacing: ".08em", fontSize: 11, margin: "10px 0 6px" }}>Chunking</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
        <FormGroup label="Strategy"><HTMLSelect fill value={cfg.chunking.strategy} onChange={(e) => setC(["chunking", "strategy"], e.target.value)}
          options={[{ label: "Recursive (sentence-aware)", value: "recursive" }, { label: "Fixed size", value: "fixed" }, { label: "By heading", value: "by_heading" }]} /></FormGroup>
        <FormGroup label="Chunk size (tokens)"><NumericInput fill value={cfg.chunking.size} onValueChange={(v) => setC(["chunking", "size"], v)} /></FormGroup>
        <FormGroup label="Overlap (tokens)"><NumericInput fill value={cfg.chunking.overlap} onValueChange={(v) => setC(["chunking", "overlap"], v)} /></FormGroup>
      </div>
      <FormGroup label="Chunking preview (sample)">
        <TextArea fill rows={2} value={sample} onChange={(e) => setSample(e.target.value)} />
        <Button small icon="eye-open" text="Preview chunks" style={{ marginTop: 6 }} onClick={doPreview} />
      </FormGroup>
      {preview && (
        <Callout style={{ marginBottom: 10 }}>
          <b>{preview.count} chunks</b> · avg {preview.avg_tokens} tokens (min {preview.min_tokens}, max {preview.max_tokens})
          <div style={{ maxHeight: 120, overflow: "auto", marginTop: 6 }}>
            {preview.chunks.map((c: any, i: number) => (
              <div key={i} style={{ fontSize: 11, padding: "3px 0", borderBottom: "1px solid var(--border)" }}>
                <Tag minimal>{c.tokens}t</Tag> {c.text.slice(0, 120)}…</div>))}
          </div>
        </Callout>
      )}

      <div className="muted" style={{ textTransform: "uppercase", letterSpacing: ".08em", fontSize: 11, margin: "10px 0 6px" }}>Embeddings</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <FormGroup label="Backend" helperText="Local runs offline; API uses a Model Endpoint of type 'embedding'.">
          <HTMLSelect fill value={cfg.embeddings.backend} onChange={(e) => setC(["embeddings", "backend"], e.target.value)}
            options={[{ label: "Local (offline)", value: "local" }, { label: "API (Model Endpoint)", value: "api" }]} /></FormGroup>
        {cfg.embeddings.backend === "api" && (
          <FormGroup label="Embedding endpoint" helperText={eps.has_embedding ? "" : "Add one in Model Endpoints (type = embedding)"}>
            <HTMLSelect fill value={cfg.embeddings.endpoint_id || ""} onChange={(e) => setC(["embeddings", "endpoint_id"], e.target.value)}
              options={[{ label: eps.has_embedding ? "— select —" : "no embedding endpoints", value: "" },
                        ...eps.embedding.map((m: any) => ({ label: m.label, value: m.id }))]} /></FormGroup>
        )}
      </div>

      <div className="muted" style={{ textTransform: "uppercase", letterSpacing: ".08em", fontSize: 11, margin: "10px 0 6px" }}>Processing (OCR / tables / images)</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        <FormGroup label="OCR (scanned docs/images)" helperText="local = Tesseract (Phase 2); api = an OCR Model Endpoint">
          <HTMLSelect fill value={cfg.processing.ocr.backend} onChange={(e) => setC(["processing", "ocr", "backend"], e.target.value)}
            options={[{ label: "Off", value: "off" }, { label: "Local (Tesseract)", value: "local" }, { label: "API endpoint", value: "api" }]} /></FormGroup>
        {cfg.processing.ocr.backend === "api" && (
          <FormGroup label="OCR endpoint">
            <HTMLSelect fill value={cfg.processing.ocr.endpoint_id || ""} onChange={(e) => setC(["processing", "ocr", "endpoint_id"], e.target.value)}
              options={[{ label: eps.ocr.length ? "— select —" : "no OCR endpoints", value: "" },
                        ...eps.ocr.map((m: any) => ({ label: m.label, value: m.id }))]} /></FormGroup>
        )}
      </div>
      <Callout intent="primary" icon="info-sign" style={{ margin: "8px 0" }}>
        Tables are extracted and preserved as structured chunks. OCR runs on scanned pages when a backend is set (local Tesseract or an OCR endpoint); digital docs use their text layer automatically. Image captioning uses a multimodal endpoint when configured.
      </Callout>
      <div className="muted" style={{ textTransform: "uppercase", letterSpacing: ".08em", fontSize: 11, margin: "10px 0 6px" }}>Retrieval</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
        <FormGroup label="Top-K results"><NumericInput fill value={cfg.retrieval.top_k} onValueChange={(v) => setC(["retrieval", "top_k"], v)} /></FormGroup>
        <FormGroup label="Hybrid (vector + keyword)" helperText="Blends dense + lexical for exact terms/IDs.">
          <HTMLSelect fill value={cfg.retrieval.hybrid ? "on" : "off"} onChange={(e) => setC(["retrieval", "hybrid"], e.target.value === "on")}
            options={[{ label: "On (recommended)", value: "on" }, { label: "Off (vector only)", value: "off" }]} /></FormGroup>
        <FormGroup label="Rerank" helperText="local = lexical re-order; api = a rerank endpoint">
          <HTMLSelect fill value={cfg.retrieval.rerank?.backend || "off"} onChange={(e) => setC(["retrieval", "rerank", "backend"], e.target.value)}
            options={[{ label: "Off", value: "off" }, { label: "Local", value: "local" }, { label: "API endpoint", value: "api" }]} /></FormGroup>
      </div>
      {cfg.retrieval.rerank?.backend === "api" && (
        <FormGroup label="Rerank endpoint">
          <HTMLSelect fill value={cfg.retrieval.rerank?.endpoint_id || ""} onChange={(e) => setC(["retrieval", "rerank", "endpoint_id"], e.target.value)}
            options={[{ label: eps.rerank?.length ? "— select —" : "no rerank endpoints", value: "" },
                      ...(eps.rerank || []).map((m: any) => ({ label: m.label, value: m.id }))]} /></FormGroup>
      )}
      <Button intent="primary" icon="floppy-disk" text="Save configuration" onClick={save} />
    </div>
  );
}

function IngestTab({ p, onDone }: { p: any; onDone: () => void }) {
  const [text, setText] = useState("");
  const [paths, setPaths] = useState("");
  const [job, setJob] = useState<any>(null);
  const [browsePrefix, setBrowsePrefix] = useState("shared");
  const [entries, setEntries] = useState<any[]>([]);
  const [showBrowser, setShowBrowser] = useState(false);
  const pollRef = useRef<any>(null);

  const loadDir = (prefix: string) => {
    setBrowsePrefix(prefix);
    api.filesList(prefix).then((r: any) => setEntries(r.entries || [])).catch(() => setEntries([]));
  };
  useEffect(() => { if (showBrowser) loadDir(browsePrefix); /* eslint-disable-next-line */ }, [showBrowser]);

  const addPath = (path: string) => {
    const cur = paths.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!cur.includes(path)) setPaths([...cur, path].join("\n"));
  };

  // resume a running job if we navigated away and came back
  useEffect(() => {
    const saved = localStorage.getItem("rag_job_" + p.id);
    if (saved) resume(saved);
    return () => clearInterval(pollRef.current);
    /* eslint-disable-next-line */
  }, [p.id]);

  const resume = (jobId: string) => {
    clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const j = await api.ragJob(jobId); setJob(j);
        if (j.status !== "running") {
          clearInterval(pollRef.current); localStorage.removeItem("rag_job_" + p.id);
          if (j.status === "done") toast.success("Ingestion complete");
          else if (j.status === "cancelled") toast.info("Ingestion cancelled");
          onDone();
        }
      } catch { clearInterval(pollRef.current); localStorage.removeItem("rag_job_" + p.id); }
    }, 700);
  };

  const start = async () => {
    const items: any[] = [];
    text.trim().split("\n---\n").forEach((t, i) => t.trim() && items.push({ source: `pasted-${i + 1}`, text: t.trim() }));
    paths.split("\n").map((s) => s.trim()).filter(Boolean).forEach((path) => items.push({ path, source: path }));
    if (!items.length) { toast.info("Add text or file paths to ingest"); return; }
    const { job_id } = await api.ragIngest(p.id, items);
    localStorage.setItem("rag_job_" + p.id, job_id);
    setText(""); setPaths(""); toast.success(`Ingesting ${items.length} document(s)…`); resume(job_id);
  };

  const running = job?.status === "running";
  return (
    <div>
      <Callout icon="cloud-upload" style={{ marginBottom: 10 }}>
        Ingestion runs in the background — you can leave this screen and come back; the pipeline status updates on its own.
      </Callout>
      {running && (
        <Card style={{ background: "rgba(118,185,0,.06)", marginBottom: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <Spinner size={16} /><b>Ingesting — {job.phase}</b>
            <span className="muted" style={{ fontSize: 12 }}>
              doc {job.doc_index || 0}/{job.doc_total || "?"} · {job.entities || 0} chunks embedded</span>
            <span style={{ flex: 1 }} />
            <Button small intent="danger" icon="cross" text="Cancel" onClick={() => api.ragCancelJob(job.id)} />
          </div>
          <ProgressBar intent="success" stripes value={job.total ? (job.processed || 0) / job.total : undefined} />
        </Card>
      )}
      <FormGroup label="Paste text" helperText="Separate multiple documents with a line containing only ---">
        <TextArea fill rows={5} value={text} onChange={(e) => setText(e.target.value)} disabled={running}
          placeholder={"Document 1 text…\n---\nDocument 2 text…"} /></FormGroup>
      <FormGroup label="Or File Storage paths (one per line)"
        helperText="Type paths, or use Browse to pick files uploaded on the Files screen.">
        <div style={{ display: "flex", gap: 6, marginBottom: 6 }}>
          <Button small icon="folder-open" text={showBrowser ? "Hide browser" : "Browse File Storage"}
            onClick={() => setShowBrowser(!showBrowser)} disabled={running} />
        </div>
        {showBrowser && (
          <Card style={{ padding: 10, marginBottom: 8, background: "var(--raised)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6, fontSize: 12 }}>
              <Icon icon="folder-close" />
              <b>{browsePrefix || "/"}</b>
              {browsePrefix.includes("/") && (
                <Button minimal small icon="arrow-up" title="Up"
                  onClick={() => loadDir(browsePrefix.split("/").slice(0, -1).join("/"))} />
              )}
              <Button minimal small icon="refresh" onClick={() => loadDir(browsePrefix)} />
            </div>
            <div style={{ maxHeight: 180, overflow: "auto" }}>
              {entries.length === 0 && <div className="muted" style={{ fontSize: 12 }}>Empty. Upload files on the Files screen first.</div>}
              {entries.map((e) => (
                <div key={e.path} style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
                  fontSize: 12, padding: "3px 0", borderBottom: "1px solid var(--border)" }}>
                  <span style={{ cursor: e.type === "folder" ? "pointer" : "default" }}
                    onClick={() => e.type === "folder" && loadDir(e.path)}>
                    <Icon icon={e.type === "folder" ? "folder-close" : "document"} style={{ marginRight: 6 }} />{e.name}
                  </span>
                  {e.type === "file"
                    ? <Button minimal small icon="plus" text="Add" onClick={() => addPath(e.path)} />
                    : <Button minimal small icon="folder-open" onClick={() => loadDir(e.path)} />}
                </div>
              ))}
            </div>
          </Card>
        )}
        <TextArea fill rows={3} value={paths} onChange={(e) => setPaths(e.target.value)} disabled={running}
          placeholder={"shared/policies/handbook.docx\nshared/docs/faq.md"} /></FormGroup>
      <Button intent="primary" icon="import" text="Start ingestion" onClick={start} disabled={running} />
    </div>
  );
}

function IndexTab({ pid }: { pid: string }) {
  const [docs, setDocs] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  useEffect(() => { api.ragDocuments(pid).then(setDocs); api.ragStats(pid).then(setStats); }, [pid]);
  const ps = stats?.pipeline_stats || {};
  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 8, margin: "8px 0" }}>
        <Metric label="Documents" value={ps.documents || 0} />
        <Metric label="Chunks" value={ps.chunks || 0} />
        <Metric label="Tokens" value={(ps.tokens || 0).toLocaleString()} />
        <Metric label="Vector store" value={stats?.backend || "—"} />
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 8, margin: "0 0 8px" }}>
        <Metric label="Tables extracted" value={ps.tables || 0} />
        <Metric label="Pages OCR'd" value={ps.pages_ocr || 0} />
        <Metric label="Images" value={ps.images || 0} />
      </div>
      <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>Documents in this index</div>
      <div style={{ maxHeight: 320, overflow: "auto" }}>
        {docs.length === 0 && <div className="muted">No documents indexed yet.</div>}
        {docs.map((d) => (
          <div key={d.id} style={{ display: "flex", justifyContent: "space-between", fontSize: 12, padding: "5px 0", borderBottom: "1px solid var(--border)" }}>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: 300 }}>
              <Tag minimal intent={d.status === "indexed" ? "success" : "danger"} style={{ marginRight: 6 }}>{d.status}</Tag>{d.source}</span>
            <span className="muted">{d.status === "indexed"
              ? `${d.chunks} chunks · ${(d.tokens || 0).toLocaleString()} tok${d.tables ? ` · ${d.tables} tables` : ""}${d.pages_ocr ? ` · ${d.pages_ocr} OCR` : ""} · ${d.extract_method || d.embed_method || ""}`
              : (d.error || "")}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function TestTab({ pid, ready }: { pid: string; ready: boolean }) {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const run = async () => { setBusy(true); try { setRes(await api.ragQuery(pid, q)); } finally { setBusy(false); } };
  return (
    <div>
      {!ready && <Callout intent="warning" style={{ marginBottom: 10 }}>Ingest documents first — the index is empty.</Callout>}
      <div style={{ display: "flex", gap: 8 }}>
        <InputGroup fill value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask the knowledge base…"
          onKeyDown={(e) => { if (e.key === "Enter") run(); }} leftIcon="search" />
        <Button intent="primary" text="Search" onClick={run} loading={busy} />
      </div>
      {res && (
        <div style={{ marginTop: 12 }}>
          <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>{res.results?.length || 0} results · {res.retrieval_method || "vector"} · backend {res.vector_backend}</div>
          {(res.results || []).map((r: any, i: number) => (
            <Card key={i} style={{ padding: 10, marginBottom: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <Tag minimal intent="success">score {r.score}</Tag>
                <span className="muted" style={{ fontSize: 11 }}>{r.metadata?.source}</span>
              </div>
              <div style={{ fontSize: 13, marginTop: 6 }}>{r.text}</div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: any }) {
  return (
    <div style={{ background: "var(--raised)", border: "1px solid var(--border)", borderRadius: 8, padding: "8px 10px" }}>
      <div className="muted" style={{ fontSize: 10 }}>{label}</div>
      <div className="metric" style={{ fontSize: 18, fontWeight: 700, color: "var(--accent)" }}>{value}</div>
    </div>
  );
}
