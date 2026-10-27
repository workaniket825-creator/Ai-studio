import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { Button, ButtonGroup, InputGroup, Tag, Card, Icon, Spinner, HTMLSelect,
  Callout, FormGroup, Divider } from "@blueprintjs/core";
import { api } from "../api/client";
import { toast } from "../components/toaster";

/** Flagship interactive knowledge-graph explorer.
 *  Force-directed physics (no external dep), drag / pan / zoom, click-to-focus with
 *  neighbor highlighting, double-click to expand, degree-based sizing (centrality),
 *  inline edit/delete of entities & edges, and a live data-science analytics panel. */

const STATUS_COLOR: Record<string, string> = {
  approved: "#76B900", pending_review: "#e0a800", rejected: "#d64550",
};
// distinct palette for entity types (knowledge dimension)
const TYPE_PALETTE = ["#38e1ff", "#b388ff", "#ff8ab3", "#ffd166", "#8affd6",
  "#ff9f6e", "#7ea6ff", "#c3f584", "#f58ec3", "#6ee7b7"];

type Node = { id: string; name: string; type: string; status: string;
  confidence?: number; x: number; y: number; vx: number; vy: number; deg: number; fixed?: boolean };
type Link = { id: string; source: string; target: string; relation: string; status: string };

export function GraphCanvas({ gid }: { gid: string }) {
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [colorMode, setColorMode] = useState<"type" | "status">("type");
  const [nodes, setNodes] = useState<Node[]>([]);
  const [links, setLinks] = useState<Link[]>([]);
  const [meta, setMeta] = useState<{ total: number; truncated: boolean }>({ total: 0, truncated: false });
  const [sel, setSel] = useState<Node | null>(null);
  const [selEdge, setSelEdge] = useState<Link | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [analytics, setAnalytics] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [collapsed, setCollapsed] = useState(false);  // collapse to selected neighborhood
  const [editing, setEditing] = useState(false);
  const [edit, setEdit] = useState<any>({});
  const [showPhysics, setShowPhysics] = useState(true);

  const svgRef = useRef<SVGSVGElement>(null);
  const W = 1000, H = 720;
  const nodesRef = useRef<Node[]>([]);
  const linksRef = useRef<Link[]>([]);
  const dragRef = useRef<{ id: string | null; panning: boolean; sx: number; sy: number; ox: number; oy: number }>(
    { id: null, panning: false, sx: 0, sy: 0, ox: 0, oy: 0 });
  const animRef = useRef<number | null>(null);

  const typeColors = useMemo(() => {
    const types = Array.from(new Set(nodes.map((n) => n.type)));
    const map: Record<string, string> = {};
    types.forEach((t, i) => { map[t] = TYPE_PALETTE[i % TYPE_PALETTE.length]; });
    return map;
  }, [nodes]);

  const colorOf = useCallback((n: Node) =>
    colorMode === "status" ? (STATUS_COLOR[n.status] || "#888") : (typeColors[n.type] || "#888"),
    [colorMode, typeColors]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const v = await api.ontologyGraphView(gid, q, statusFilter === "all" ? "" : statusFilter);
      const deg: Record<string, number> = {};
      (v.edges || []).forEach((e: any) => { deg[e.source] = (deg[e.source] || 0) + 1; deg[e.target] = (deg[e.target] || 0) + 1; });
      const existing = new Map(nodesRef.current.map((n) => [n.id, n]));
      const laid: Node[] = (v.entities || []).map((e: any, i: number) => {
        const prev = existing.get(e.id);
        const angle = (i / Math.max(1, v.entities.length)) * Math.PI * 2;
        return {
          id: e.id, name: e.name, type: e.type, status: e.status, confidence: e.confidence,
          x: prev?.x ?? W / 2 + Math.cos(angle) * 160, y: prev?.y ?? H / 2 + Math.sin(angle) * 160,
          vx: 0, vy: 0, deg: deg[e.id] || 0,
        };
      });
      setNodes(laid); setLinks(v.edges || []);
      nodesRef.current = laid; linksRef.current = v.edges || [];
      setMeta({ total: v.total, truncated: v.truncated });
      api.ontologyAnalytics(gid).then(setAnalytics).catch(() => {});
    } finally { setLoading(false); }
  }, [gid, q, statusFilter]);

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [gid]);

  // physics simulation loop
  useEffect(() => {
    if (!showPhysics) { if (animRef.current) cancelAnimationFrame(animRef.current); return; }
    const tick = () => {
      const ns = nodesRef.current, ls = linksRef.current;
      const cx = W / 2, cy = H / 2;
      for (let i = 0; i < ns.length; i++) {
        const a = ns[i];
        if (a.fixed) continue;
        // repulsion
        for (let j = 0; j < ns.length; j++) {
          if (i === j) continue;
          const b = ns[j];
          let dx = a.x - b.x, dy = a.y - b.y;
          let d2 = dx * dx + dy * dy || 0.01;
          const rep = 2600 / d2;
          const d = Math.sqrt(d2);
          a.vx += (dx / d) * rep; a.vy += (dy / d) * rep;
        }
        // centering
        a.vx += (cx - a.x) * 0.006; a.vy += (cy - a.y) * 0.006;
      }
      // springs
      for (const l of ls) {
        const s = ns.find((n) => n.id === l.source), t = ns.find((n) => n.id === l.target);
        if (!s || !t) continue;
        const dx = t.x - s.x, dy = t.y - s.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const f = (d - 90) * 0.02;
        const fx = (dx / d) * f, fy = (dy / d) * f;
        if (!s.fixed) { s.vx += fx; s.vy += fy; }
        if (!t.fixed) { t.vx -= fx; t.vy -= fy; }
      }
      let moving = 0;
      for (const a of ns) {
        if (a.fixed) { a.vx = a.vy = 0; continue; }
        a.vx *= 0.82; a.vy *= 0.82;
        a.x += Math.max(-8, Math.min(8, a.vx));
        a.y += Math.max(-8, Math.min(8, a.vy));
        a.x = Math.max(20, Math.min(W - 20, a.x));
        a.y = Math.max(20, Math.min(H - 20, a.y));
        moving += Math.abs(a.vx) + Math.abs(a.vy);
      }
      setNodes([...ns]);
      if (moving > 0.5) animRef.current = requestAnimationFrame(tick);
    };
    animRef.current = requestAnimationFrame(tick);
    return () => { if (animRef.current) cancelAnimationFrame(animRef.current); };
  }, [nodes.length, links.length, showPhysics]);

  const openDetail = async (n: Node) => {
    setSel(n); setSelEdge(null); setEditing(false);
    try { setDetail(await api.ontologyEntityDetail(gid, n.id)); } catch { setDetail(null); }
  };

  const expand = async (n: Node) => {
    try {
      const nb = await api.ontologyNeighbors(gid, n.id);
      const cur = new Map(nodesRef.current.map((x) => [x.id, x]));
      (nb.neighbors || []).forEach((e: any) => {
        if (!cur.has(e.id)) {
          cur.set(e.id, { id: e.id, name: e.name, type: e.type, status: e.status, confidence: e.confidence,
            x: n.x + (Math.random() - 0.5) * 120, y: n.y + (Math.random() - 0.5) * 120, vx: 0, vy: 0, deg: 1 });
        }
      });
      const merged = Array.from(cur.values());
      const lcur = new Map(linksRef.current.map((l) => [l.id, l]));
      (nb.edges || []).forEach((e: any) => lcur.set(e.id, e));
      nodesRef.current = merged; linksRef.current = Array.from(lcur.values());
      setNodes([...merged]); setLinks([...linksRef.current]);
      toast.success(`Expanded ${nb.neighbors?.length || 0} neighbors`);
    } catch { toast.info("No further neighbors"); }
  };

  // pointer interactions (drag nodes / pan background)
  const toSvg = (clientX: number, clientY: number) => {
    const r = svgRef.current!.getBoundingClientRect();
    return { x: (clientX - r.left) / (r.width / (W / zoom)) - pan.x, y: (clientY - r.top) / (r.height / (H / zoom)) - pan.y };
  };
  const onDownNode = (e: React.PointerEvent, n: Node) => {
    e.stopPropagation();
    dragRef.current = { id: n.id, panning: false, sx: 0, sy: 0, ox: 0, oy: 0 };
    n.fixed = true;
  };
  const onDownBg = (e: React.PointerEvent) => {
    dragRef.current = { id: null, panning: true, sx: e.clientX, sy: e.clientY, ox: pan.x, oy: pan.y };
  };
  const onMove = (e: React.PointerEvent) => {
    const dr = dragRef.current;
    if (dr.id) {
      const p = toSvg(e.clientX, e.clientY);
      const n = nodesRef.current.find((x) => x.id === dr.id);
      if (n) { n.x = p.x; n.y = p.y; n.vx = n.vy = 0; setNodes([...nodesRef.current]); }
    } else if (dr.panning) {
      const r = svgRef.current!.getBoundingClientRect();
      const sc = r.width / (W / zoom);
      setPan({ x: dr.ox + (e.clientX - dr.sx) / sc, y: dr.oy + (e.clientY - dr.sy) / sc });
    }
  };
  const onUp = () => {
    const dr = dragRef.current;
    if (dr.id) { const n = nodesRef.current.find((x) => x.id === dr.id); if (n) n.fixed = false; }
    dragRef.current = { id: null, panning: false, sx: 0, sy: 0, ox: 0, oy: 0 };
  };
  const onWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    setZoom((z) => Math.max(0.4, Math.min(3, +(z - Math.sign(e.deltaY) * 0.12).toFixed(2))));
  };

  const nodeById = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const neighborIds = useMemo(() => {
    if (!sel) return new Set<string>();
    const s = new Set<string>();
    links.forEach((l) => { if (l.source === sel.id) s.add(l.target); if (l.target === sel.id) s.add(l.source); });
    return s;
  }, [sel, links]);

  const maxDeg = Math.max(1, ...nodes.map((n) => n.deg));
  const radius = (n: Node) => 6 + (n.deg / maxDeg) * 10;

  // collapse mode: when a node is selected, render only it + its neighbors
  const visN = (collapsed && sel)
    ? nodes.filter((n) => n.id === sel.id || neighborIds.has(n.id))
    : nodes;
  const visIds = useMemo(() => new Set(visN.map((n) => n.id)), [visN]);
  const visL = (collapsed && sel)
    ? links.filter((l) => visIds.has(l.source) && visIds.has(l.target))
    : links;

  const saveEdit = async () => {
    try {
      if (sel) { await api.ontologyUpdateEntity(sel.id, { name: edit.name, type: edit.type, status: edit.status }); toast.success("Entity updated"); }
      else if (selEdge) { await api.ontologyUpdateEdge(selEdge.id, { relation: edit.relation, status: edit.status }); toast.success("Edge updated"); }
      setEditing(false); await load();
      if (sel) { const n = nodesRef.current.find((x) => x.id === sel.id); if (n) openDetail(n); }
    } catch (e: any) { toast.error(e.message); }
  };
  const delEntity = async () => {
    if (!sel || !confirm(`Delete entity "${sel.name}" and its relationships?`)) return;
    await api.ontologyDeleteEntity(sel.id); toast.success("Deleted"); setSel(null); setDetail(null); load();
  };
  const delEdge = async () => {
    if (!selEdge || !confirm(`Delete relationship "${selEdge.relation}"?`)) return;
    await api.ontologyDeleteEdge(selEdge.id); toast.success("Deleted"); setSelEdge(null); load();
  };

  return (
    <div>
      {/* toolbar */}
      <div style={{ display: "flex", gap: 8, marginBottom: 10, alignItems: "center", flexWrap: "wrap" }}>
        <InputGroup value={q} onChange={(e) => setQ(e.target.value)} placeholder="search entities…"
          onKeyDown={(e) => { if (e.key === "Enter") load(); }} leftIcon="search" style={{ width: 220 }} />
        <Button icon="search" text="Search" onClick={load} />
        <HTMLSelect value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setTimeout(load, 0); }}
          options={[{ label: "All statuses", value: "all" }, { label: "approved", value: "approved" },
                    { label: "pending review", value: "pending_review" }, { label: "rejected", value: "rejected" }]} />
        <HTMLSelect value={colorMode} onChange={(e) => setColorMode(e.target.value as any)}
          options={[{ label: "Color: type", value: "type" }, { label: "Color: status", value: "status" }]} />
        <ButtonGroup>
          <Button small icon="zoom-out" onClick={() => setZoom((z) => Math.max(0.4, +(z - 0.15).toFixed(2)))} />
          <Button small text={`${Math.round(zoom * 100)}%`} onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }} />
          <Button small icon="zoom-in" onClick={() => setZoom((z) => Math.min(3, +(z + 0.15).toFixed(2)))} />
        </ButtonGroup>
        <ButtonGroup>
          <Button small icon="minimize" text="Collapse" active={collapsed}
            disabled={!sel}
            title="Show only the selected node and its neighbors"
            onClick={() => setCollapsed(true)} />
          <Button small icon="maximize" text="Expand" active={!collapsed}
            title="Show the full graph"
            onClick={() => setCollapsed(false)} />
        </ButtonGroup>
        <Button small icon="reset" text="Reset view"
          title="Clear selection and return to the full graph"
          onClick={() => { setSel(null); setSelEdge(null); setCollapsed(false); setZoom(1); setPan({ x: 0, y: 0 }); }} />
        <Button small icon={showPhysics ? "pause" : "play"} text={showPhysics ? "Freeze" : "Animate"}
          onClick={() => setShowPhysics(!showPhysics)} />
        {loading && <Spinner size={16} />}
        <span className="muted" style={{ fontSize: 12 }}>
          {meta.total} entities{meta.truncated ? " · search to narrow" : ""}
        </span>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 12 }}>
        {/* canvas */}
        <Card style={{ padding: 0, position: "relative", overflow: "hidden",
          background: "radial-gradient(circle at 50% 40%, #0f1a0a 0%, #0a120a 70%)" }}>
          {nodes.length === 0 ? (
            <div className="muted" style={{ padding: 60, textAlign: "center" }}>
              No entities to show. Search above, or add/extract entities first.
            </div>
          ) : (
            <svg ref={svgRef} viewBox={`0 0 ${W / zoom} ${H / zoom}`}
              style={{ width: "100%", height: "min(76vh, 900px)", display: "block", cursor: dragRef.current.panning ? "grabbing" : "grab" }}
              onPointerDown={onDownBg} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={onUp}
              onWheel={onWheel}>
              <defs>
                <filter id="glow" x="-60%" y="-60%" width="220%" height="220%">
                  <feGaussianBlur stdDeviation="2.4" result="b" /><feMerge>
                    <feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge>
                </filter>
                <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
                  <path d="M0 0 L10 5 L0 10 z" fill="#3a4a2e" />
                </marker>
              </defs>
              <g transform={`translate(${pan.x},${pan.y})`}>
                {visL.map((l) => {
                  const s = nodeById.get(l.source), t = nodeById.get(l.target);
                  if (!s || !t) return null;
                  const hot = sel && (l.source === sel.id || l.target === sel.id);
                  const dim = sel && !hot;
                  return (
                    <g key={l.id} opacity={dim ? 0.15 : 1} style={{ cursor: "pointer" }}
                      onPointerDown={(e) => { e.stopPropagation(); setSelEdge(l); setSel(null); setEditing(false);
                        setEdit({ relation: l.relation, status: l.status }); }}>
                      <line x1={s.x} y1={s.y} x2={t.x} y2={t.y}
                        stroke={selEdge?.id === l.id ? "#76B900" : hot ? "#8fb85a" : "#33421f"}
                        strokeWidth={selEdge?.id === l.id ? 2.5 : hot ? 2 : 1} markerEnd="url(#arrow)" />
                      <text x={(s.x + t.x) / 2} y={(s.y + t.y) / 2 - 2} fill="#7fa356" fontSize={7.5}
                        textAnchor="middle">{l.relation}</text>
                    </g>
                  );
                })}
                {visN.map((n) => {
                  const focused = sel?.id === n.id;
                  const near = sel ? (focused || neighborIds.has(n.id)) : true;
                  return (
                    <g key={n.id} transform={`translate(${n.x},${n.y})`} style={{ cursor: "pointer" }}
                      opacity={near ? 1 : 0.25}
                      onPointerDown={(e) => onDownNode(e, n)}
                      onClick={(e) => { e.stopPropagation(); openDetail(n); }}
                      onDoubleClick={(e) => { e.stopPropagation(); expand(n); }}>
                      <circle r={radius(n) + (focused ? 4 : 0)} fill={colorOf(n)}
                        stroke={focused ? "#fff" : "#0c120c"} strokeWidth={focused ? 2 : 1.2}
                        filter={focused ? "url(#glow)" : undefined} />
                      {n.status !== "approved" && (
                        <circle r={radius(n) + 3} fill="none" stroke={STATUS_COLOR[n.status] || "#888"}
                          strokeWidth={1} strokeDasharray="2 2" />
                      )}
                      <text x={radius(n) + 4} y={4} fill="#dfeed2" fontSize={9}
                        style={{ pointerEvents: "none" }}>{n.name}</text>
                    </g>
                  );
                })}
              </g>
            </svg>
          )}
          {/* legend */}
          <div style={{ position: "absolute", left: 10, bottom: 10, background: "rgba(10,18,10,.8)",
            borderRadius: 8, padding: "6px 10px", fontSize: 10, maxWidth: 220 }}>
            <div className="muted" style={{ marginBottom: 3 }}>{colorMode === "type" ? "Entity types" : "Status"}</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {colorMode === "type"
                ? Object.entries(typeColors).slice(0, 8).map(([t, c]) => (
                  <span key={t} style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                    <span style={{ width: 8, height: 8, borderRadius: 8, background: c as string }} />{t}</span>))
                : Object.entries(STATUS_COLOR).map(([s, c]) => (
                  <span key={s} style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                    <span style={{ width: 8, height: 8, borderRadius: 8, background: c }} />{s}</span>))}
            </div>
            <div className="muted" style={{ marginTop: 4, fontSize: 9 }}>drag nodes · scroll to zoom · click=focus · double-click=expand</div>
          </div>
        </Card>

        {/* right rail: detail / edit / analytics */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {sel && detail ? (
            <Card>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <b style={{ fontSize: 14 }}>{sel.name}</b>
                <Tag minimal intent={sel.status === "approved" ? "success" : sel.status === "rejected" ? "danger" : "warning"}>
                  {sel.status}</Tag>
              </div>
              {!editing ? (
                <>
                  <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>
                    {sel.type} · degree {sel.deg}{sel.confidence != null ? ` · conf ${(sel.confidence * 100).toFixed(0)}%` : ""}</div>
                  {detail.entity?.properties && Object.keys(detail.entity.properties).length > 0 && (
                    <div style={{ marginTop: 8 }}>
                      {Object.entries(detail.entity.properties).map(([k, v]) => (
                        <div key={k} style={{ fontSize: 11 }}><span className="muted">{k}:</span> {String(v)}</div>))}
                    </div>
                  )}
                  <Divider />
                  <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
                    Relationships ({detail.relationships?.length || 0})</div>
                  <div style={{ maxHeight: 150, overflow: "auto" }}>
                    {(detail.relationships || []).map((r: any) => (
                      <div key={r.id} style={{ fontSize: 11, marginBottom: 3 }}>
                        <Tag minimal>{r.relation}</Tag> {r.source === sel.id ? "→" : "←"}{" "}
                        {nodeById.get(r.source === sel.id ? r.target : r.source)?.name || "?"}
                      </div>))}
                  </div>
                  <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
                    <Button small icon="edit" text="Edit" onClick={() => { setEditing(true); setEdit({ name: sel.name, type: sel.type, status: sel.status }); }} />
                    <Button small icon="graph" text="Expand" onClick={() => expand(sel)} />
                    <Button small intent="danger" minimal icon="trash" onClick={delEntity} />
                  </div>
                </>
              ) : (
                <div style={{ marginTop: 8 }}>
                  <FormGroup label="Name"><InputGroup value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></FormGroup>
                  <FormGroup label="Type"><InputGroup value={edit.type} onChange={(e) => setEdit({ ...edit, type: e.target.value })} /></FormGroup>
                  <FormGroup label="Status"><HTMLSelect fill value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}
                    options={["approved", "pending_review", "rejected"]} /></FormGroup>
                  <div style={{ display: "flex", gap: 6 }}>
                    <Button small intent="primary" icon="floppy-disk" text="Save" onClick={saveEdit} />
                    <Button small minimal text="Cancel" onClick={() => setEditing(false)} />
                  </div>
                </div>
              )}
            </Card>
          ) : selEdge ? (
            <Card>
              <b>Relationship</b>
              <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                {nodeById.get(selEdge.source)?.name} → {nodeById.get(selEdge.target)?.name}</div>
              <FormGroup label="Relation" style={{ marginTop: 8 }}>
                <InputGroup value={edit.relation} onChange={(e) => setEdit({ ...edit, relation: e.target.value })} /></FormGroup>
              <FormGroup label="Status"><HTMLSelect fill value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}
                options={["approved", "pending_review", "rejected"]} /></FormGroup>
              <div style={{ display: "flex", gap: 6 }}>
                <Button small intent="primary" icon="floppy-disk" text="Save" onClick={saveEdit} />
                <Button small intent="danger" minimal icon="trash" text="Delete" onClick={delEdge} />
              </div>
            </Card>
          ) : (
            <Callout icon="hand-up" style={{ fontSize: 12 }}>Click a node or relationship to inspect and edit it. Double-click a node to expand its neighbors.</Callout>
          )}

          {/* data-science analytics */}
          {analytics && (
            <Card>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                <Icon icon="timeline-bar-chart" color="var(--accent)" /><b style={{ fontSize: 13 }}>Graph analytics</b>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, fontSize: 12 }}>
                <Metric label="Entities" value={analytics.entities} />
                <Metric label="Relationships" value={analytics.edges} />
                <Metric label="Density" value={analytics.density} />
                <Metric label="Avg degree" value={analytics.avg_degree} />
                <Metric label="Components" value={analytics.components} />
                <Metric label="Types" value={Object.keys(analytics.type_distribution || {}).length} />
              </div>
              {analytics.top_hubs?.length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <div className="muted" style={{ fontSize: 11, marginBottom: 3 }}>Most connected (centrality)</div>
                  {analytics.top_hubs.slice(0, 5).map((h: any) => (
                    <div key={h.id} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 2 }}>
                      <div style={{ flex: 1, fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{h.name}</div>
                      <div style={{ width: 70, height: 6, background: "#22301a", borderRadius: 4 }}>
                        <div style={{ width: `${(h.degree / (analytics.top_hubs[0].degree || 1)) * 100}%`,
                          height: "100%", background: "var(--accent)", borderRadius: 4 }} /></div>
                      <span className="metric muted" style={{ fontSize: 10, width: 16, textAlign: "right" }}>{h.degree}</span>
                    </div>))}
                </div>
              )}
              {analytics.type_distribution && Object.keys(analytics.type_distribution).length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <div className="muted" style={{ fontSize: 11, marginBottom: 3 }}>Type distribution</div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                    {Object.entries(analytics.type_distribution).map(([t, c]) => (
                      <Tag key={t} minimal style={{ fontSize: 10 }}>
                        <span style={{ display: "inline-block", width: 7, height: 7, borderRadius: 7,
                          background: typeColors[t] || "#888", marginRight: 4 }} />{t}: {c as number}</Tag>))}
                  </div>
                </div>
              )}
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: any }) {
  return (
    <div style={{ background: "rgba(118,185,0,.06)", borderRadius: 6, padding: "5px 8px" }}>
      <div className="muted" style={{ fontSize: 10 }}>{label}</div>
      <div className="metric" style={{ fontSize: 15, fontWeight: 700, color: "var(--accent)" }}>{value}</div>
    </div>
  );
}
