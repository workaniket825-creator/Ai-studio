import { useEffect, useRef, useState } from "react";
import { Button, HTMLSelect, TextArea, Tag, Card, Collapse, Icon, Spinner, Callout,
  InputGroup, Menu, MenuItem, Popover, Dialog, DialogBody } from "@blueprintjs/core";
import { api, Workflow } from "../api/client";
import { Markdown } from "../components/Markdown";
import { toast } from "../components/toaster";

type Msg = {
  role: "user" | "assistant";
  text: string;
  runId?: string;
  status?: string;
  pending?: boolean;
  steps?: { agent: string; output: string }[];
  artifacts?: any[];
  ontology?: any[];
  knowledge?: { text: string; score: number; source: string }[];
  error?: string;
};

function estTokens(text: string): number {
  if (!text) return 0;
  return Math.round(text.trim().split(/\s+/).filter(Boolean).length / 0.75);
}

export function Chat() {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [wfId, setWfId] = useState("");
  const [pipeId, setPipeId] = useState("");
  const [pipelines, setPipelines] = useState<any[]>([]);
  const [hops, setHops] = useState(1);
  const [compress, setCompress] = useState<any>(null);
  const [lastComp, setLastComp] = useState<any>(null);
  const [showDiff, setShowDiff] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [activeRun, setActiveRun] = useState<string | null>(null);
  // history
  const [convos, setConvos] = useState<any[]>([]);
  const [convId, setConvId] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { api.listWorkflows().then((w) => { setWorkflows(w); setWfId((prev) => prev || w[0]?.workflow_id || ""); }); }, []);
  useEffect(() => { api.ragList().then((ps: any[]) => setPipelines(ps.filter((p) => p.status === "ready"))).catch(() => {}); }, []);
  useEffect(() => { api.compressionConfig().then(setCompress).catch(() => {}); }, []);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy]);
  const refreshList = () => api.chatList(search, showArchived).then(setConvos);
  useEffect(() => { refreshList(); /* eslint-disable-next-line */ }, [search, showArchived]);

  // Restore context on mount: reopen the last-active conversation (persisted id), else the
  // most recent one — so history/context survive page refresh, restart, or returning to Chat.
  useEffect(() => {
    (async () => {
      const list = await api.chatList("", false);
      setConvos(list);
      const saved = (() => { try { return localStorage.getItem("tcs_active_chat"); } catch { return null; } })();
      const target = (saved && list.find((c: any) => c.id === saved)) ? saved : list[0]?.id;
      if (target) openConversation(target);
    })();
    /* eslint-disable-next-line */
  }, []);

  const wf = workflows.find((w) => w.workflow_id === wfId);

  // persist messages to the active conversation whenever they settle
  const persist = async (messages: Msg[]) => {
    if (!convId) return;
    try { await api.chatSaveMessages(convId, messages); refreshList(); } catch { /* ignore */ }
  };

  const newChat = () => { setConvId(null); setMsgs([]); try { localStorage.removeItem("tcs_active_chat"); } catch {} };

  const openConversation = async (cid: string) => {
    const conv = await api.chatGet(cid);
    setConvId(conv.id);
    setMsgs(conv.messages || []);
    if (conv.workflow_id) setWfId(conv.workflow_id);
    try { localStorage.setItem("tcs_active_chat", conv.id); } catch {}
  };

  const poll = (runId: string): Promise<any> =>
    new Promise((resolve) => {
      const iv = setInterval(async () => {
        try {
          const r = await api.getRun(runId);
          setMsgs((m) => {
            const copy = [...m];
            const last = copy[copy.length - 1];
            if (last && last.role === "assistant" && last.pending) {
              last.steps = (r.node_outputs || []).map((n: any) => ({ agent: n.agent, output: n.output }));
              // surface ontology usage live as each agent completes (not just at the end)
              const onto = (r.node_outputs || []).map((n: any) => n.ontology).filter(Boolean);
              if (onto.length) last.ontology = onto;
            }
            return copy;
          });
          if (["succeeded", "failed", "awaiting_approval", "cancelled"].includes(r.status)) {
            clearInterval(iv); resolve(r);
          }
        } catch { /* keep polling */ }
      }, 1000);
      setTimeout(() => { clearInterval(iv); resolve(null); }, 180000);
    });

  const stop = async () => { if (activeRun) { await api.cancelRun(activeRun); toast.info("Interrupting…"); } };

  const send = async () => {
    const text = input.trim();
    if (!text || !wfId) return;
    setInput(""); setBusy(true);

    // ensure a conversation exists to persist into
    let cid = convId;
    if (!cid) {
      try { const c = await api.chatCreate(wfId, wf?.name || ""); cid = c.id; setConvId(c.id); try { localStorage.setItem("tcs_active_chat", c.id); } catch {} } catch { /* ignore */ }
    }

    // Build history. Compression applies ONLY to the PREVIOUS conversation (not the new message).
    let history = msgs.filter((m) => m.role === "assistant").slice(-3).map((m) => m.text);
    let comp: any = null;
    if (compress?.enabled) {
      try {
        const prevTurns = msgs.map((m) => ({ role: m.role, text: m.text })).filter((t) => t.text);
        comp = await api.chatCompress(prevTurns);
        if (comp?.applied) {
          history = [comp.compressed_context];   // send summary + recent verbatim turns
        }
      } catch { /* compression best-effort; fall back to plain history */ }
    }

    const withUser: Msg[] = [...msgs, { role: "user", text }, { role: "assistant", text: "", pending: true, steps: [] }];
    setMsgs(withUser);

    // knowledge grounding: if a pipeline is attached, retrieve passages and inject as context
    let groundedInput = text;
    let knowledge: any[] = [];
    if (pipeId) {
      try {
        const kr = await api.ragQuery(pipeId, text);
        knowledge = kr.results || [];
        if (knowledge.length) {
          const ctx = knowledge.map((h: any, i: number) =>
            `[${i + 1}] (${(h.metadata || {}).source || "source"}) ${h.text}`).join("\n");
          groundedInput = `Use the following knowledge-base passages to answer. Cite them as [n].\n\n${ctx}\n\nQuestion: ${text}`;
        }
      } catch { /* retrieval best-effort */ }
    }

    // ---- token breakdown for the compression panel (all categories shown separately) ----
    if (compress?.enabled) {
      const retrievedText = knowledge.length
        ? knowledge.map((h: any, i: number) => `[${i + 1}] (${(h.metadata || {}).source || "source"}) ${h.text}`).join("\n")
        : "";
      setLastComp({
        ...(comp || { applied: false, reason: "under_threshold", tokens_before: 0 }),
        query_tokens: estTokens(text),
        retrieved_tokens: estTokens(retrievedText),
        retrieved_count: knowledge.length,
      });
    }

    try {
      const res = await api.startRun(wfId, { message: groundedInput, input: groundedInput, history }, hops);
      setActiveRun(res.run_id);
      const run = await poll(res.run_id);
      let finalMsgs: Msg[] = [];
      setMsgs((m) => {
        const copy = [...m];
        const last = copy[copy.length - 1];
        if (last && last.role === "assistant") {
          last.pending = false;
          last.runId = run?.run_id;
          last.status = run?.status;
          last.error = run?.error || (!run ? "Timed out waiting for the workflow." : "");
          last.artifacts = run?.artifacts || [];
          last.text = run?.final_output || (run?.node_outputs?.slice(-1)[0]?.output) || "";
          last.steps = (run?.node_outputs || []).map((n: any) => ({ agent: n.agent, output: n.output }));
          // ontology data retrieved/used during this run (spec §2)
          last.ontology = (run?.node_outputs || []).map((n: any) => n.ontology).filter(Boolean);
          // knowledge passages retrieved for this answer (RAG citations)
          if (knowledge.length) last.knowledge = knowledge.map((h: any) => ({
            text: h.text, score: h.score, source: (h.metadata || {}).source || "" }));
        }
        finalMsgs = copy;
        return copy;
      });
      // persist the settled conversation
      if (cid) { await api.chatSaveMessages(cid, finalMsgs); refreshList(); }
    } catch (e: any) { toast.error(e.message); }
    finally { setBusy(false); setActiveRun(null); }
  };

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0 }}>
      {/* horizontal top bar — conversations dropdown + controls (frees full width for chat) */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", paddingBottom: 10,
        borderBottom: "1px solid var(--border)", marginBottom: 10 }}>
        <div style={{ marginRight: "auto", display: "flex", alignItems: "baseline", gap: 10, minWidth: 0 }}>
          <h2 style={{ margin: 0 }}>Chat</h2>
          <span className="muted" style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {convId ? (convos.find((c) => c.id === convId)?.title || "conversation") : "new conversation"}
          </span>
        </div>

        <Button icon="add" intent="primary" text="New chat" onClick={newChat} />

        <Popover placement="bottom-end" content={
          <div style={{ width: 320, maxHeight: 420, overflow: "auto", padding: 6 }}>
            <InputGroup leftIcon="search" placeholder="Search chats…" value={search}
              onChange={(e) => setSearch(e.target.value)} style={{ marginBottom: 6 }} />
            {convos.length === 0 && <div className="muted" style={{ fontSize: 12, padding: 8 }}>No conversations yet.</div>}
            {convos.map((c) => (
              <div key={c.id} onClick={() => openConversation(c.id)}
                style={{ padding: "8px 10px", borderRadius: 8, cursor: "pointer", marginBottom: 2,
                  background: convId === c.id ? "rgba(118,185,0,.12)" : "transparent",
                  border: convId === c.id ? "1px solid var(--accent)" : "1px solid transparent" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 6 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {c.archived && <Icon icon="box" size={11} style={{ marginRight: 4 }} />}{c.title}
                  </div>
                  <Popover content={
                    <Menu>
                      <MenuItem icon="edit" text="Rename" onClick={async (e) => { e.stopPropagation();
                        const t = prompt("Rename chat:", c.title); if (t) { await api.chatRename(c.id, t); refreshList(); } }} />
                      <MenuItem icon={c.archived ? "unarchive" : "archive"} text={c.archived ? "Unarchive" : "Archive"}
                        onClick={async (e) => { e.stopPropagation(); await api.chatArchive(c.id, !c.archived); refreshList(); }} />
                      <MenuItem icon="trash" intent="danger" text="Delete" onClick={async (e) => { e.stopPropagation();
                        if (confirm(`Delete "${c.title}"?`)) { await api.chatDelete(c.id); if (convId === c.id) newChat(); refreshList(); } }} />
                    </Menu>
                  } placement="bottom-end">
                    <Button minimal small icon="more" onClick={(e) => e.stopPropagation()} />
                  </Popover>
                </div>
                <div className="muted" style={{ fontSize: 11 }}>
                  {c.workflow_name || "workflow"} · {c.message_count} msgs · {fmtWhen(c.updated_at)}
                </div>
              </div>
            ))}
            <Button minimal small fill icon={showArchived ? "eye-off" : "box"} text={showArchived ? "Hide archived" : "Show archived"}
              onClick={() => setShowArchived(!showArchived)} style={{ marginTop: 4 }} />
          </div>
        }>
          <Button icon="chat" rightIcon="caret-down" text={`Conversations${convos.length ? ` (${convos.length})` : ""}`} />
        </Popover>

        {pipelines.length > 0 && (
          <HTMLSelect value={pipeId} onChange={(e) => setPipeId(e.target.value)}
            title="Ground answers in a knowledge pipeline"
            options={[{ label: "No knowledge", value: "" },
                      ...pipelines.map((p) => ({ label: `Knowledge: ${p.name}`, value: p.id }))]} />
        )}
        <HTMLSelect value={wfId} onChange={(e) => { setWfId(e.target.value); if (!convId) setMsgs([]); }}
          options={workflows.map((w) => ({ label: w.name, value: w.workflow_id }))} />
        <HTMLSelect value={hops} onChange={(e) => setHops(Number(e.target.value))}
          title="Ontology hops — how many relationship hops to traverse in the knowledge graph"
          options={[{ label: "1 hop", value: 1 }, { label: "2 hops", value: 2 },
                    { label: "3 hops", value: 3 }, { label: "4 hops", value: 4 },
                    { label: "5 hops", value: 5 }]} />

        {/* compression chip → opens the per-category token breakdown */}
        {compress?.enabled && (
          <Tag round interactive minimal
            intent={lastComp?.applied ? "success" : "none"}
            icon="compressed"
            onClick={() => lastComp && setShowDiff(true)}
            title={lastComp ? "View token breakdown" : "Context compression is on"}>
            {lastComp?.applied ? `⇩ ${lastComp.saved_pct}% · view tokens`
              : lastComp
                ? `tokens: view`
                : "compression on"}
          </Tag>
        )}
      </div>

      {/* context banners (thin, only when relevant) */}
      {pipeId && <Callout icon="search-template" intent="primary" style={{ marginBottom: 10 }}>
        Answers grounded in <b>{pipelines.find((p) => p.id === pipeId)?.name}</b> — passages shown as citations.
      </Callout>}
      {wf && msgs.length === 0 && <Callout icon="flows" style={{ marginBottom: 10 }}>
        <b>{wf.name}</b> — {(wf as any).config?.description || wf.goal_prompt || "Sends your message through this workflow."}
        <span className="muted"> · {wf.nodes.length} agents</span>
      </Callout>}

      {/* messages — flex fills remaining height, scrolls internally, centered column */}
      <div style={{ flex: 1, overflow: "auto", minHeight: 0, padding: "4px 0" }}>
        <div style={{ maxWidth: 860, margin: "0 auto", padding: "0 8px" }}>
          {msgs.length === 0 && <div className="muted" style={{ textAlign: "center", padding: 40 }}>
            Type a message below — it runs through the selected workflow and returns the final answer.
            Your conversation is saved to history automatically.
          </div>}
          {msgs.map((m, i) => <Bubble key={i} m={m} />)}
          {busy && <div style={{ display: "flex", gap: 8, alignItems: "center", color: "var(--muted)", padding: "8px 12px" }}>
            <Spinner size={16} /> workflow running…
            <Button minimal small intent="danger" icon="stop" text="Stop" onClick={stop} />
          </div>}
          <div ref={endRef} />
        </div>
      </div>

      {/* composer — pinned at bottom */}
      <div style={{ maxWidth: 860, margin: "0 auto", width: "100%", padding: "0 8px" }}>
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <TextArea fill autoResize value={input} placeholder="Send a message to the workflow…  (Enter to send · Shift+Enter for newline)"
            style={{ maxHeight: 160, resize: "none" }}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
          <Button large intent="primary" icon="send-message" onClick={send} loading={busy} disabled={!wfId || !input.trim()} />
        </div>
      </div>

      {/* context breakdown dialog (overlay — never eats chat space) */}
      <Dialog isOpen={showDiff} onClose={() => setShowDiff(false)} title="Context breakdown — tokens by category"
        icon="compressed" style={{ width: "min(920px, 94vw)" }}>
        <DialogBody>
          {lastComp && (() => {
            const prevBefore = lastComp.tokens_before || 0;
            const prevAfter = lastComp.applied ? (lastComp.tokens_after || 0) : prevBefore;
            const q = lastComp.query_tokens || 0;
            const retr = lastComp.retrieved_tokens || 0;
            const totalSent = prevAfter + q + retr;
            const row = (label: string, val: number, intent = "", note = "") => (
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
                padding: "8px 12px", borderBottom: "1px solid var(--border)" }}>
                <span>{label}{note && <span className="muted" style={{ fontSize: 11 }}> · {note}</span>}</span>
                <Tag large minimal intent={intent as any}><b>{val.toLocaleString()}</b>&nbsp;tok</Tag>
              </div>
            );
            return (
              <>
                <div style={{ border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden", marginBottom: 14 }}>
                  {/* previous conversation — pre + post compression */}
                  {row("Previous conversation — before compression", prevBefore, "",
                       `${(lastComp.compressed_count ?? 0) + (lastComp.recent_turns?.length ?? 0)} turns`)}
                  {lastComp.applied
                    ? row("Previous conversation — after compression", prevAfter, "success",
                          `${lastComp.compressed_count} turns summarized · via ${lastComp.method}`)
                    : row("Previous conversation — after compression", prevAfter, "",
                          lastComp.reason === "under_threshold" ? "under threshold — not compressed yet" : "not compressed")}
                  {/* current query */}
                  {row("Current question / query", q)}
                  {/* retrieved knowledge context */}
                  {row("Retrieved information (agent context)", retr, "",
                       `${lastComp.retrieved_count || 0} passages`)}
                  {/* total actually sent */}
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
                    padding: "10px 12px", background: "var(--panel)" }}>
                    <b>Total sent to model</b>
                    <Tag large intent="primary"><b>{totalSent.toLocaleString()}</b>&nbsp;tok</Tag>
                  </div>
                </div>

                {lastComp.applied && (
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    <div>
                      <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
                        Previous conversation BEFORE — <b>{prevBefore.toLocaleString()}</b> tokens (all prior turns)
                      </div>
                      <div style={{ fontSize: 12, background: "var(--panel)", border: "1px solid var(--border)",
                        borderRadius: 8, padding: 12, color: "var(--muted)" }}>
                        {(lastComp.compressed_count + (lastComp.recent_turns?.length || 0))} turns
                        ({prevBefore.toLocaleString()} tokens) would have been sent uncompressed.
                        <div style={{ marginTop: 6 }}>
                          <b style={{ color: "var(--accent)" }}>{lastComp.saved_pct}%</b> saved on the
                          previous-conversation portion ({prevBefore.toLocaleString()} → {prevAfter.toLocaleString()}).
                        </div>
                      </div>
                    </div>
                    <div>
                      <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
                        Previous conversation AFTER — compressed content sent (<b>{prevAfter.toLocaleString()}</b> tokens)
                      </div>
                      <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, background: "var(--panel)", border: "1px solid var(--accent)",
                        borderRadius: 8, padding: 12, maxHeight: 380, overflow: "auto", margin: 0, fontFamily: "var(--mono)" }}>
                        {lastComp.compressed_context}
                      </pre>
                    </div>
                  </div>
                )}
              </>
            );
          })()}
        </DialogBody>
      </Dialog>
    </div>
  );
}

function fmtWhen(iso?: string) {
  if (!iso) return "";
  const d = new Date(iso), now = new Date();
  const sameDay = d.toDateString() === now.toDateString();
  return sameDay ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                 : d.toLocaleDateString([], { month: "short", day: "numeric" });
}

function Bubble({ m }: { m: Msg }) {
  const [open, setOpen] = useState(false);
  const [ontoOpen, setOntoOpen] = useState(false);
  const [kbOpen, setKbOpen] = useState(false);
  const mine = m.role === "user";
  return (
    <div style={{ display: "flex", justifyContent: mine ? "flex-end" : "flex-start", margin: "10px 0" }}>
      <div style={{ maxWidth: "82%" }}>
        <div className="chat-role" style={{ justifyContent: mine ? "flex-end" : "flex-start" }}>
          <Icon icon={mine ? "user" : "predictive-analysis"} size={12} color={mine ? "#9ccf4a" : "var(--accent)"} />
          {mine ? "You" : "Workflow"}
        </div>
        <Card className={mine ? "chat-bubble-user" : "chat-bubble-assistant"} style={{ padding: "10px 14px" }}>
          {mine ? <div style={{ whiteSpace: "pre-wrap" }}>{m.text}</div> : (
            m.error ? <Callout intent="danger" icon="error" title="Run failed">{m.error}</Callout>
              : m.pending ? <div className="muted"><span className="thinking-dots">working</span></div>
              : <Markdown text={m.text || "(no output)"} />
          )}
        </Card>
        {!mine && (m.steps?.length || m.artifacts?.length || m.ontology?.length || m.knowledge?.length) ? (
          <div style={{ marginTop: 4 }}>
            {m.artifacts?.map((a: any) => (
              <a key={a.name} href={api.artifactUrl(m.runId!, a.name)} download style={{ marginRight: 8 }}>
                <Button minimal small icon="download" text={a.name} />
              </a>
            ))}
            {m.knowledge?.length ? (
              <>
                <Button minimal small icon="search-template" rightIcon={kbOpen ? "chevron-up" : "chevron-down"}
                  text={`Knowledge sources (${m.knowledge.length})`} onClick={() => setKbOpen(!kbOpen)} />
                <Collapse isOpen={kbOpen}>
                  <div style={{ borderLeft: "2px solid var(--accent)", paddingLeft: 10, marginTop: 6 }}>
                    {m.knowledge.map((k, i) => (
                      <div key={i} style={{ fontSize: 12, padding: "4px 0", borderBottom: "1px solid var(--border)" }}>
                        <Tag minimal intent="success" style={{ marginRight: 6 }}>[{i + 1}] {k.score}</Tag>
                        <span className="muted">{k.source}</span>
                        <div style={{ marginTop: 2 }}>{k.text.slice(0, 220)}{k.text.length > 220 ? "…" : ""}</div>
                      </div>
                    ))}
                  </div>
                </Collapse>
              </>
            ) : null}
            {m.ontology?.length ? (
              <>
                <Button minimal small icon="graph" rightIcon={ontoOpen ? "chevron-up" : "chevron-down"}
                  text="Ontology data used" onClick={() => setOntoOpen(!ontoOpen)} />
                <Collapse isOpen={ontoOpen}>
                  <div style={{ borderLeft: "2px solid var(--accent)", paddingLeft: 10, marginTop: 6 }}>
                    {m.ontology.map((o: any, i: number) => (
                      <div key={i} style={{ marginBottom: 8, fontSize: 12 }}>
                        {o.entities?.length ? (
                          <div style={{ marginBottom: 4 }}>
                            <span className="muted">Entities retrieved: </span>
                            {o.entities.map((e: any, j: number) => (
                              <Tag key={j} minimal style={{ marginRight: 4, marginBottom: 3 }}>
                                {e.name}{e.type ? ` · ${e.type}` : ""}</Tag>))}
                          </div>) : null}
                        {o.relations?.length ? (
                          <div style={{ marginBottom: 4 }}>
                            <span className="muted">Relationships: </span>
                            {o.relations.map((r: any, j: number) => (
                              <span key={j} style={{ marginRight: 8 }}>{r.source} →<i>{r.relation}</i>→ {r.target}</span>))}
                          </div>) : null}
                      </div>
                    ))}
                  </div>
                </Collapse>
              </>
            ) : null}
            {m.steps?.length ? (
              <>
                <Button minimal small icon="diagram-tree" rightIcon={open ? "chevron-up" : "chevron-down"}
                  text={`${m.steps.length} agent steps`} onClick={() => setOpen(!open)} />
                <Collapse isOpen={open || !!m.pending}>
                  <div style={{ borderLeft: "2px solid var(--border)", paddingLeft: 10, marginTop: 6 }}>
                    {m.steps.map((s, i) => (
                      <div key={i} style={{ marginBottom: 8 }}>
                        <div style={{ fontWeight: 600, fontSize: 12 }}><Icon icon="person" color="var(--accent)" /> {s.agent}</div>
                        <div className="muted" style={{ fontSize: 12 }}><Markdown text={s.output} /></div>
                      </div>
                    ))}
                  </div>
                </Collapse>
              </>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
