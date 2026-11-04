// Domain AI › Decision Intelligence FT
// Hosts the Decision Framework for Model Tuning (v3) as a native platform module. The framework's
// own engine (./dfm/engine.ts, adapted verbatim from the standalone HTML) renders inside .dfm-root;
// this screen supplies the platform pieces: shared backend persistence (multiple assessments),
// platform toasts/dialogs, AI report via a Model Endpoint, and a Word report saved to File Storage.
import { useEffect, useRef, useState } from "react";
import {
  Alert, Button, Callout, Dialog, DialogBody, DialogFooter, Drawer, DrawerSize, FormGroup, HTMLSelect,
  HTMLTable, Intent, NonIdealState, Spinner, Tag, Tooltip,
} from "@blueprintjs/core";
import { api } from "../../api/client";
import { toast } from "../../components/toaster";
import { Markdown } from "../../components/Markdown";
import { DFM_MARKUP } from "./dfm/markup";
import { createDfmEngine } from "./dfm/engine";
import "./dfm/dfm.css";

const STORAGE_KEY = "tcs-domain-ai-v3";               // the framework's own key (engine-internal)
const LAST_KEY = "tcs-dfm-last-assessment";            // UI preference: last opened assessment
const MIGRATED_KEY = "tcs-domain-ai-v3:migrated";      // legacy browser copy already imported

const VERDICT_INTENT: Record<string, Intent> = {
  pass: Intent.SUCCESS, fail: Intent.DANGER, pending: Intent.WARNING, "in-progress": Intent.PRIMARY,
};

type SaveStatus = "idle" | "saving" | "saved" | "error";

export function DecisionIntelligenceFT({ go }: { go?: (screen: any) => void }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<any>(null);
  const cur = useRef<{ id: string | null; startedAt: string | null; json: string | null }>(
    { id: null, startedAt: null, json: null });
  const timer = useRef<any>(null);
  const chain = useRef<Promise<void>>(Promise.resolve());
  const dirty = useRef(false);

  const [list, setList] = useState<any[]>([]);
  const [currentId, setCurrentId] = useState<string | null>(null);
  const [currentName, setCurrentName] = useState("");
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [savedAt, setSavedAt] = useState<string>("");
  const [drawer, setDrawer] = useState(false);
  const [confirmReq, setConfirmReq] = useState<{ msg: string; resolve: (ok: boolean) => void } | null>(null);
  const [delTarget, setDelTarget] = useState<any | null>(null);
  const [aiOpen, setAiOpen] = useState(false);
  const [endpoints, setEndpoints] = useState<any[]>([]);
  const [endpointId, setEndpointId] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [aiReport, setAiReport] = useState<any | null>(null);
  const [wordBusy, setWordBusy] = useState(false);
  const [lastWord, setLastWord] = useState<string>("");

  const refreshList = () => api.dfmList().then(setList).catch(() => {});

  const setCurrent = (id: string | null, state: any | null) => {
    cur.current = { id, startedAt: state?.meta?.startedAt ?? null, json: state ? JSON.stringify(state) : null };
    setCurrentId(id);
    setCurrentName(state?.meta?.assessmentName || "");
    if (id) localStorage.setItem(LAST_KEY, id); else localStorage.removeItem(LAST_KEY);
  };

  // ---------------------------------------------------------------- persistence (debounced)
  const flush = () => {
    clearTimeout(timer.current);
    chain.current = chain.current.then(async () => {
      if (!dirty.current || !cur.current.json) return;
      dirty.current = false;
      const json = cur.current.json;
      const state = JSON.parse(json);
      const started = state?.meta?.startedAt ?? null;
      let summary: any = {};
      try { summary = engineRef.current?.summary() ?? {}; } catch { /* summary is optional */ }
      try {
        const isNew = !cur.current.id || cur.current.startedAt !== started;   // new / imported assessment
        let saved: any;
        if (!isNew) {
          try { saved = await api.dfmUpdate(cur.current.id!, { state, summary }); }
          catch (e: any) { if (!/not found/i.test(e.message)) throw e; }      // deleted elsewhere -> recreate
        }
        if (!saved) {
          saved = await api.dfmCreate({ state, summary });
          cur.current.id = saved.id;
          cur.current.startedAt = started;
          setCurrentId(saved.id);
          setAiReport(null);
          localStorage.setItem(LAST_KEY, saved.id);
        }
        setCurrentName(saved.name || "");
        setSavedAt(saved.updated_at || "");
        setSaveStatus(dirty.current ? "saving" : "saved");
        refreshList();
      } catch (e: any) {
        dirty.current = true;
        setSaveStatus("error");
        toast.error(`Assessment not saved: ${e.message}`);
      }
    });
    return chain.current;
  };

  const scheduleSave = () => {
    dirty.current = true;
    setSaveStatus("saving");
    clearTimeout(timer.current);
    timer.current = setTimeout(flush, 600);
  };

  const removeCurrent = () => {                     // the framework's Reset (original: clear storage)
    const id = cur.current.id;
    clearTimeout(timer.current);
    dirty.current = false;
    setCurrent(null, null);
    setAiReport(null);
    setSaveStatus("idle");
    if (id) api.dfmDelete(id).then(() => { toast.success("Assessment reset and removed."); refreshList(); })
      .catch((e) => toast.error(e.message));
  };

  // host services handed to the engine (replace localStorage / alert / confirm)
  const host = {
    storage: {
      getItem: (k: string) => (k === STORAGE_KEY ? cur.current.json : null),
      setItem: (k: string, v: string) => { if (k === STORAGE_KEY) { cur.current.json = v; scheduleSave(); } },
      removeItem: (k: string) => { if (k === STORAGE_KEY) removeCurrent(); },
    },
    notify: (msg: string) => {
      if (/invalid|failed|error/i.test(msg)) toast.error(msg);
      else if (/^please/i.test(msg)) toast.info(msg);
      else toast.success(msg);
    },
    confirm: (msg: string) => new Promise<boolean>((resolve) => setConfirmReq({ msg, resolve })),
  };

  // ---------------------------------------------------------------- mount
  useEffect(() => {
    const root = rootRef.current!;
    root.innerHTML = DFM_MARKUP;
    const engine = createDfmEngine(root, host);
    engineRef.current = engine;
    (window as any).__dfm = engine.handlers;

    const pane = root.closest(".main-pane") as HTMLElement | null;
    const setVh = () => root.style.setProperty("--dfm-vh", `${pane ? pane.clientHeight : window.innerHeight}px`);
    setVh();
    const ro = new ResizeObserver(setVh);
    if (pane) ro.observe(pane);

    let cancelled = false;
    (async () => {
      let rows: any[] = [];
      try { rows = await api.dfmList(); } catch (e: any) { toast.error(`Could not load saved assessments: ${e.message}`); }
      // one-time: bring an assessment saved by the standalone page (this browser) into shared storage
      try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw && !localStorage.getItem(MIGRATED_KEY)) {
          const st = JSON.parse(raw);
          const known = rows.some((r) => r.started_at === st?.meta?.startedAt && r.name === st?.meta?.assessmentName);
          if (st?.meta?.startedAt && !known) {
            const created = await api.dfmCreate({ state: st, summary: {} });
            rows = [created, ...rows];
            if (!localStorage.getItem(LAST_KEY)) localStorage.setItem(LAST_KEY, created.id);
            toast.info(`Imported "${created.name}" from this browser into shared assessments.`);
          }
          localStorage.setItem(MIGRATED_KEY, "1");
        }
      } catch { /* legacy copy unreadable: ignore, never block the module */ }
      if (cancelled) return;
      setList(rows);
      const last = localStorage.getItem(LAST_KEY);
      if (last && rows.some((r) => r.id === last)) {
        try {
          const rec = await api.dfmGet(last);
          if (cancelled) return;
          setCurrent(rec.id, rec.state);
          setAiReport(rec.ai_report || null);
          setSaveStatus("saved");
          setSavedAt(rec.updated_at || "");
        } catch { setCurrent(null, null); }
      }
      if (!cancelled) engine.boot();               // original DOMContentLoaded behaviour
    })();

    return () => {
      cancelled = true;
      ro.disconnect();
      if (dirty.current) flush();
      if ((window as any).__dfm === engine.handlers) delete (window as any).__dfm;
      root.innerHTML = "";
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Escape closes the drawer / AI dialog even when focus stayed on the button that opened them
  useEffect(() => {
    if (!drawer && !aiOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !confirmReq && !delTarget) { setDrawer(false); setAiOpen(false); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawer, aiOpen, confirmReq, delTarget]);

  // ---------------------------------------------------------------- actions
  const openAssessment = async (id: string) => {
    await flush();
    try {
      const rec = await api.dfmGet(id);
      setCurrent(rec.id, rec.state);
      setAiReport(rec.ai_report || null);
      setSaveStatus("saved");
      setSavedAt(rec.updated_at || "");
      engineRef.current.open(rec.state);
      setDrawer(false);
    } catch (e: any) { toast.error(e.message); }
  };

  const deleteAssessment = async (row: any) => {
    try {
      await api.dfmDelete(row.id);
      if (row.id === cur.current.id) {
        clearTimeout(timer.current);
        dirty.current = false;
        setCurrent(null, null);
        setAiReport(null);
        setSaveStatus("idle");
        engineRef.current.close();
      }
      toast.success(`Deleted "${row.name}".`);
      refreshList();
    } catch (e: any) { toast.error(e.message); }
  };

  const newAssessment = () => { setDrawer(false); engineRef.current.handlers.startNewAssessment(); };

  const openAi = async () => {
    setAiOpen(true);
    try {
      const eps = (await api.listEndpoints()).filter((e: any) => (e.type || "chat") === "chat");
      setEndpoints(eps);
      if (!endpointId && eps.length) setEndpointId(aiReport?.endpoint_id && eps.some((e: any) => e.id === aiReport.endpoint_id)
        ? aiReport.endpoint_id : eps[0].id);
    } catch (e: any) { toast.error(e.message); }
  };

  const generateAi = async () => {
    if (!cur.current.id) return;
    setAiBusy(true);
    try {
      await flush();
      const prompt = engineRef.current.generateLlmPrompt();       // the framework's own prompt, unchanged
      const r = await api.dfmAiReport(cur.current.id, { endpoint_id: endpointId, prompt });
      setAiReport(r);
      toast.success("AI report generated.");
      refreshList();
    } catch (e: any) { toast.error(e.message); }
    setAiBusy(false);
  };

  const saveWord = async () => {
    if (!cur.current.id) return;
    setWordBusy(true);
    try {
      await flush();
      const r = await api.dfmWord(cur.current.id, { report: engineRef.current.reportModel(), include_ai_report: true });
      setLastWord(r.path);
      toast.success(`Word report saved to File Storage: ${r.path}`);
    } catch (e: any) { toast.error(e.message); }
    setWordBusy(false);
  };

  const copyAi = () => {
    if (!aiReport?.markdown) return;
    navigator.clipboard?.writeText(aiReport.markdown).then(() => toast.success("Report copied."),
      () => toast.error("Copy failed - select the text manually."));
  };

  const statusTag = !currentId
    ? <Tag minimal icon="cloud">Not saved yet</Tag>
    : saveStatus === "saving" ? <Tag minimal icon={<Spinner size={12} />}>Saving…</Tag>
      : saveStatus === "error" ? <Tag minimal intent="danger" icon="error">Save failed - retrying on next change</Tag>
        : <Tooltip content={savedAt ? `Last saved ${new Date(savedAt).toLocaleString()}` : "Saved"}>
          <Tag minimal intent="success" icon="cloud-upload">Saved</Tag></Tooltip>;

  return (
    <div className="dfm-screen">
      <div className="section-head dfm-pagehead" style={{ flexWrap: "wrap", gap: 10 }}>
        <div>
          <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>Domain AI › Decision Intelligence FT</div>
          <h2>Decision Intelligence FT</h2>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          {currentName && <Tag minimal large icon="clipboard">{currentName}</Tag>}
          {statusTag}
          <Button icon="folder-open" text={`Saved assessments (${list.length})`} onClick={() => { refreshList(); setDrawer(true); }} />
          <Tooltip content={currentId ? "Generate the decision report with a platform model" : "Start or open an assessment first"}>
            <Button icon="predictive-analysis" text="AI report" disabled={!currentId} onClick={openAi} />
          </Tooltip>
          <Tooltip content={currentId ? "Create a Word report and save it to File Storage" : "Start or open an assessment first"}>
            <Button icon="document" intent="primary" text="Save as Word" disabled={!currentId} loading={wordBusy} onClick={saveWord} />
          </Tooltip>
          {lastWord && go && <Button minimal icon="folder-shared-open" text="Open File Storage" onClick={() => go("files")} />}
        </div>
      </div>

      <div ref={rootRef} className="dfm-root" />

      <Alert isOpen={!!confirmReq} intent={Intent.DANGER} icon="reset" confirmButtonText="Reset"
        cancelButtonText="Cancel"
        onConfirm={() => { confirmReq?.resolve(true); setConfirmReq(null); }}
        onCancel={() => { confirmReq?.resolve(false); setConfirmReq(null); }}>
        <p>{confirmReq?.msg}</p>
        {currentId && <p className="muted">This also deletes the saved copy shared with your team.</p>}
      </Alert>

      <Alert isOpen={!!delTarget} intent={Intent.DANGER} icon="trash" confirmButtonText="Delete" cancelButtonText="Cancel"
        onConfirm={() => { const t = delTarget; setDelTarget(null); if (t) deleteAssessment(t); }}
        onCancel={() => setDelTarget(null)}>
        <p>Delete the assessment <b>{delTarget?.name}</b>? It is removed for everyone. This cannot be undone.</p>
      </Alert>

      <Drawer isOpen={drawer} onClose={() => setDrawer(false)} title="Saved assessments" icon="folder-open"
        size={DrawerSize.LARGE}>
        <div style={{ padding: 16, overflow: "auto" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <span className="muted">Shared across the team. Changes save automatically.</span>
            <Button intent="primary" icon="plus" text="New assessment" onClick={newAssessment} />
          </div>
          {list.length === 0 ? (
            <NonIdealState icon="clipboard" title="No assessments yet"
              description="Start a new assessment - it is saved here automatically." />
          ) : (
            <HTMLTable compact striped interactive style={{ width: "100%" }}>
              <thead><tr><th>Assessment</th><th>Lead consultant</th><th>Progress</th><th>Overall</th><th>Updated</th><th /></tr></thead>
              <tbody>
                {list.map((r) => {
                  const s = r.summary || {};
                  return (
                    <tr key={r.id} style={r.id === currentId ? { boxShadow: "inset 3px 0 0 var(--accent)" } : undefined}>
                      <td onClick={() => openAssessment(r.id)} style={{ cursor: "pointer" }}>
                        <b>{r.name}</b>
                        <div className="muted" style={{ fontSize: 12 }}>{[r.client, r.industry].filter(Boolean).join(" · ") || "—"}</div>
                      </td>
                      <td>{r.lead_consultant || "—"}</td>
                      <td className="metric">
                        {s.total_questions ? `${s.answered}/${s.total_questions} answers` : "—"}
                        {s.gates_total ? <div className="muted" style={{ fontSize: 12 }}>{s.gates_decided}/{s.gates_total} gates</div> : null}
                      </td>
                      <td>
                        <Tag minimal intent={VERDICT_INTENT[s.overall] || Intent.NONE}>{s.overall_label || "Not started"}</Tag>
                        {r.has_ai_report && <Tag minimal icon="predictive-analysis" style={{ marginLeft: 4 }}>AI</Tag>}
                      </td>
                      <td className="muted" style={{ fontSize: 12 }}>{r.updated_at ? new Date(r.updated_at).toLocaleString() : ""}</td>
                      <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                        <Button small icon="folder-open" text="Open" onClick={() => openAssessment(r.id)} />{" "}
                        <Button small minimal intent="danger" icon="trash" aria-label="Delete" onClick={() => setDelTarget(r)} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </HTMLTable>
          )}
        </div>
      </Drawer>

      <Dialog isOpen={aiOpen} onClose={() => setAiOpen(false)} title="AI decision report" icon="predictive-analysis"
        style={{ width: "min(920px, 94vw)" }}>
        <DialogBody>
          <Callout intent="primary" icon="info-sign" style={{ marginBottom: 12 }}>
            Sends the framework's complete LLM prompt (every answer, verdict and rationale) to a platform
            Model Endpoint and stores the report with this assessment. It is included in the Word report.
          </Callout>
          {endpoints.length === 0 ? (
            <Callout intent="warning" icon="warning-sign">
              No chat model endpoint is configured.{" "}
              {go && <Button small minimal intent="primary" text="Add one in Model Endpoints" onClick={() => { setAiOpen(false); go("endpoints"); }} />}
            </Callout>
          ) : (
            <FormGroup label="Model endpoint" inline style={{ marginBottom: 8 }}>
              <HTMLSelect value={endpointId} onChange={(e) => setEndpointId(e.target.value)}
                options={endpoints.map((e: any) => ({ label: `${e.name || e.model} (${e.provider})`, value: e.id }))} />
            </FormGroup>
          )}
          {aiBusy && <div style={{ padding: 30, textAlign: "center" }}><Spinner size={28} /><div className="muted" style={{ marginTop: 8 }}>Generating the report…</div></div>}
          {!aiBusy && aiReport?.markdown && (
            <div>
              <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
                {aiReport.model} · {aiReport.generated_at ? new Date(aiReport.generated_at).toLocaleString() : ""}
              </div>
              <div style={{ maxHeight: "52vh", overflow: "auto", padding: "8px 12px", background: "var(--panel)",
                border: "1px solid var(--border)", borderRadius: 4 }}>
                <Markdown text={aiReport.markdown} />
              </div>
            </div>
          )}
          {!aiBusy && !aiReport?.markdown && endpoints.length > 0 && (
            <NonIdealState icon="predictive-analysis" title="No AI report yet" description="Choose a model and generate." />
          )}
        </DialogBody>
        <DialogFooter actions={<>
          <Button icon="duplicate" text="Copy" disabled={!aiReport?.markdown} onClick={copyAi} />
          <Button icon="document" text="Save as Word" disabled={!aiReport?.markdown || wordBusy} loading={wordBusy} onClick={saveWord} />
          <Button intent="primary" icon="predictive-analysis" text={aiReport?.markdown ? "Regenerate" : "Generate report"}
            disabled={!endpointId || aiBusy} loading={aiBusy} onClick={generateAi} />
        </>} />
      </Dialog>
    </div>
  );
}
