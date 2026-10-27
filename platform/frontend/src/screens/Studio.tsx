import { useCallback, useEffect, useMemo, useState } from "react";
import ReactFlow, {
  Background, Controls, MiniMap, MarkerType, addEdge, useNodesState, useEdgesState,
  Handle, Position, Connection, Node, Edge,
} from "reactflow";
import {
  Button, HTMLSelect, InputGroup, Tag, Callout, Dialog, DialogBody, DialogFooter,
  Card, Switch, FormGroup, NumericInput, TextArea,
} from "@blueprintjs/core";
import { api, AgentCard, Workflow } from "../api/client";

const STATUS_COLOR: Record<string, string> = {
  reused: "var(--accent)", to_be_created: "var(--warning)",
  modified: "var(--violet)", remote: "#54c8ff",
};

// ---- custom draggable node ----
function AgentNode({ data, selected }: any) {
  return (
    <div className={`node-card ${selected ? "selected" : ""}`} style={{ position: "relative" }}>
      <Handle type="target" position={Position.Left} />
      <div>
        <span className="status-dot" style={{ background: STATUS_COLOR[data.status] || "var(--muted)", color: STATUS_COLOR[data.status] }} />
        <b>{data.name}</b>
      </div>
      <div className="n-model">→ {data.outputKey}</div>
      {data.approval && <Tag minimal intent="warning" style={{ marginTop: 4 }}>approval</Tag>}
      <Handle type="source" position={Position.Right} />
    </div>
  );
}
const nodeTypes = { agent: AgentNode };

let idc = 100;
const nextId = () => `n${++idc}`;

export function Studio({ onRun }: { onRun: (runId: string, wf: Workflow) => void }) {
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [agents, setAgents] = useState<AgentCard[]>([]);
  const [wfId, setWfId] = useState<string>("");
  const [wfName, setWfName] = useState("Untitled workflow");
  const [maxIter, setMaxIter] = useState(20);
  const [runInput, setRunInput] = useState("");
  const [ontologyHops, setOntologyHops] = useState(1);
  const [goal, setGoal] = useState("");
  const [designing, setDesigning] = useState(false);
  const [plan, setPlan] = useState<any[] | null>(null);
  const [dirty, setDirty] = useState(false);

  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [sel, setSel] = useState<Node | null>(null);

  useEffect(() => {
    api.listWorkflows().then((w) => { setWorkflows(w); if (w[0]) load(w[0]); });
    api.listAgents().then(setAgents);
  }, []);

  const toNodes = (wf: Workflow): Node[] => wf.nodes.map((n, i) => ({
    id: n.node_id, type: "agent",
    position: (n as any).overrides?.position || { x: 80 + i * 210, y: 120 + (i % 2) * 80 },
    data: { name: (n.agent_ref || "").replace("agent_cards/", "") || "New agent",
            outputKey: n.output_key, status: n.status,
            approval: wf.approval_gates?.includes(n.node_id) },
  }));
  const toEdges = (wf: Workflow): Edge[] => wf.edges.map((e, i) => ({
    id: `e${i}`, source: e.from, target: e.to, animated: true,
    markerEnd: { type: MarkerType.ArrowClosed, color: "#4f7a00" },
  }));

  const load = (wf: Workflow) => {
    setWfId(wf.workflow_id || ""); setWfName(wf.name); setGoal(wf.goal_prompt || "");
    setMaxIter(((wf as any).config?.max_iterations) || 20);
    setNodes(toNodes(wf)); setEdges(toEdges(wf)); setSel(null); setDirty(false);
  };

  const onConnect = useCallback((c: Connection) => {
    setEdges((e) => addEdge({ ...c, animated: true, markerEnd: { type: MarkerType.ArrowClosed, color: "#4f7a00" } }, e));
    setDirty(true);
  }, [setEdges]);

  const addAgent = (a: AgentCard) => {
    const id = nextId();
    setNodes((ns) => ns.concat({
      id, type: "agent", position: { x: 120 + Math.random() * 240, y: 120 + Math.random() * 160 },
      data: { name: a.agent_name, outputKey: a.io_contract?.output_key || "result", status: "reused", approval: false },
    }));
    setDirty(true);
  };

  const updateSel = (patch: any) => {
    if (!sel) return;
    setNodes((ns) => ns.map((n) => n.id === sel.id ? { ...n, data: { ...n.data, ...patch } } : n));
    setSel((s) => s ? { ...s, data: { ...s.data, ...patch } } : s);
    setDirty(true);
  };
  const deleteSel = () => {
    if (!sel) return;
    setNodes((ns) => ns.filter((n) => n.id !== sel.id));
    setEdges((es) => es.filter((e) => e.source !== sel.id && e.target !== sel.id));
    setSel(null); setDirty(true);
  };

  const buildGraph = (): any => ({
    workflow_id: wfId || undefined, name: wfName, goal_prompt: goal,
    nodes: nodes.map((n) => ({
      node_id: n.id, agent_ref: `agent_cards/${n.data.name}`, status: n.data.status,
      output_key: n.data.outputKey, input_bindings: {},
      overrides: { position: n.position },
    })),
    edges: edges.map((e) => ({ from: e.source, to: e.target, type: "sequential" })),
    approval_gates: nodes.filter((n) => n.data.approval).map((n) => n.id),
    config: { max_iterations: maxIter },
  });

  const newWorkflow = () => {
    const name = window.prompt("Name the new workflow", "New workflow");
    if (name === null) return;
    setWfId(""); setWfName(name || "New workflow"); setGoal("");
    setNodes([]); setEdges([]); setSel(null); setDirty(true);
  };

  const save = async () => {
    if (!nodes.length) { return; }
    const g = buildGraph();
    const saved = wfId ? await api.updateWorkflow(wfId, g) : await api.createWorkflow(g);
    const list = await api.listWorkflows(); setWorkflows(list);
    setWfId(saved.workflow_id); setDirty(false);
  };

  const design = async () => {
    if (!goal.trim()) return;
    setDesigning(true);
    const wf = await api.designWorkflow(goal);
    setWfId(""); setWfName(wf.name); setNodes(toNodes(wf)); setEdges(toEdges(wf));
    setDesigning(false); setDirty(true);
  };

  const openPlan = async () => {
    if (dirty || !wfId) await save();
    const id = wfId || (await api.listWorkflows()).slice(-1)[0]?.workflow_id;
    if (id) setPlan((await api.planWorkflow(id)).steps);
  };
  const runApproved = useCallback(async () => {
    setPlan(null);
    if (!wfId) return;
    // no hardcoded inputs — pass the run input the user typed (or empty)
    const res = await api.startRun(wfId, runInput.trim() ? { input: runInput, message: runInput } : {}, ontologyHops);
    onRun(res.run_id, { workflow_id: wfId, name: wfName } as Workflow);
  }, [wfId, wfName, runInput, ontologyHops, onRun]);

  const flowNodes = useMemo(() => nodes, [nodes]);

  return (
    <div style={{ height: "calc(100vh - 40px)", display: "flex", flexDirection: "column" }}>
      <div className="section-head">
        <div><h2>Workflow Studio</h2><span className="muted">Drag, connect, edit — then plan &amp; run</span></div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <HTMLSelect value={wfId} onChange={(e) => {
            const w = workflows.find((x) => x.workflow_id === e.target.value);
            if (w) load(w);
          }} options={[{ label: "— open workflow —", value: "" },
            ...workflows.map((w) => ({ label: w.name, value: w.workflow_id }))]} />
          <Button icon="add" text="New workflow" onClick={newWorkflow} />
          <InputGroup value={wfName} onChange={(e) => { setWfName(e.target.value); setDirty(true); }}
            style={{ width: 190 }} leftIcon="tag" placeholder="Workflow name" />
          <Tag minimal icon="repeat" title="Max agent steps (loop guard)">
            <NumericInput buttonPosition="none" min={1} max={100} value={maxIter} style={{ width: 46 }}
              onValueChange={(v) => { setMaxIter(v); setDirty(true); }} />
          </Tag>
          <Button icon="floppy-disk" text={dirty ? "Save *" : "Save"} intent={dirty ? "primary" : "none"}
            onClick={save} disabled={!nodes.length} />
          <Button icon="form" text="Plan & run" intent="primary" onClick={openPlan} disabled={!nodes.length} />
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
        <InputGroup fill leftIcon="lightbulb" value={goal} onChange={(e) => setGoal(e.target.value)}
          placeholder="Describe a goal — e.g. 'Extract the sales CSV, find anomalies, draft an exec email'"
          onKeyDown={(e) => e.key === "Enter" && design()} />
        <Button icon="predictive-analysis" text="Design" loading={designing} onClick={design} />
      </div>

      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "180px 1fr 250px", gap: 10, minHeight: 0 }}>
        {/* palette */}
        <div style={{ overflow: "auto" }}>
          <div className="muted" style={{ fontSize: 11, marginBottom: 6, textTransform: "uppercase", letterSpacing: ".08em" }}>Agents · click to add</div>
          {agents.map((a) => (
            <div key={a.agent_id} className="palette-item" onClick={() => addAgent(a)}>
              <span className="status-dot" style={{ background: "var(--accent)", color: "var(--accent)" }} />
              {a.agent_name}
            </div>
          ))}
        </div>

        {/* canvas */}
        <div style={{ border: "1px solid var(--border)", borderRadius: 10, background: "#0a0e0b", overflow: "hidden" }}>
          <ReactFlow nodes={flowNodes} edges={edges} nodeTypes={nodeTypes}
            onNodesChange={(c) => { onNodesChange(c); if (c.some((x) => x.type === "position")) setDirty(true); }}
            onEdgesChange={onEdgesChange} onConnect={onConnect}
            onNodeClick={(_, n) => setSel(n)} onPaneClick={() => setSel(null)}
            fitView deleteKeyCode={["Backspace", "Delete"]}>
            <Background color="#1c2a1f" gap={18} />
            <MiniMap style={{ background: "#12171400" }} maskColor="rgba(0,0,0,.6)" nodeColor="#76b900" />
            <Controls />
          </ReactFlow>
        </div>

        {/* inspector */}
        <div style={{ overflow: "auto" }}>
          {sel ? (
            <Card style={{ padding: 14 }}>
              <b>Node</b>
              <FormGroup label="Agent" style={{ marginTop: 10 }}>
                <HTMLSelect fill value={sel.data.name}
                  onChange={(e) => updateSel({ name: e.target.value })}
                  options={agents.map((a) => a.agent_name)} />
              </FormGroup>
              <FormGroup label="Output key">
                <InputGroup value={sel.data.outputKey} onChange={(e) => updateSel({ outputKey: e.target.value })} />
              </FormGroup>
              <Switch label="Requires approval" checked={!!sel.data.approval}
                onChange={() => updateSel({ approval: !sel.data.approval })} />
              <Button fill minimal intent="danger" icon="trash" text="Delete node" onClick={deleteSel} style={{ marginTop: 8 }} />
            </Card>
          ) : (
            <Callout icon="info-sign" title="Editing">
              Click an agent to add it. Drag from a node's right handle to another's left to connect.
              Select a node to edit or delete. Drag nodes to reposition.
            </Callout>
          )}
          <div className="muted" style={{ marginTop: 10, fontSize: 11 }}>
            <span className="status-dot" style={{ background: "var(--accent)", color: "var(--accent)" }} />reused&nbsp;
            <span className="status-dot" style={{ background: "var(--warning)", color: "var(--warning)" }} />to create&nbsp;
            <span className="status-dot" style={{ background: "var(--violet)", color: "var(--violet)" }} />modified
          </div>
        </div>
      </div>

      <Dialog isOpen={!!plan} onClose={() => setPlan(null)} title="Plan — approve before running" className="bp5-dark">
        <DialogBody>
          <Callout icon="info-sign" style={{ marginBottom: 12 }}>These steps run in order. Approve to execute.</Callout>
          <FormGroup label="Run input (optional)" helperText="Passed to the workflow as the user input">
            <TextArea fill rows={2} value={runInput} onChange={(e) => setRunInput(e.target.value)}
              placeholder="e.g. analyze these traces / summarize these documents…" />
          </FormGroup>
          <FormGroup label="Ontology hops" helperText="How many relationship hops the agent may traverse in the knowledge graph for this run.">
            <HTMLSelect value={ontologyHops} onChange={(e) => setOntologyHops(Number(e.target.value))}
              options={[{ label: "1 hop", value: 1 }, { label: "2 hops", value: 2 },
                        { label: "3 hops", value: 3 }, { label: "4 hops", value: 4 },
                        { label: "5 hops", value: 5 }]} />
          </FormGroup>
          {(plan || []).map((s) => (
            <div key={s.step} style={{ display: "flex", gap: 10, padding: "6px 0" }}>
              <Tag round intent="primary">{s.step}</Tag><span>{s.action}</span>
            </div>
          ))}
        </DialogBody>
        <DialogFooter actions={<>
          <Button text="Cancel" onClick={() => setPlan(null)} />
          <Button intent="success" icon="play" text="Approve & run" onClick={runApproved} />
        </>} />
      </Dialog>
    </div>
  );
}
