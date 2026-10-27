import { useEffect, useRef, useState } from "react";
import { Icon, Tag } from "@blueprintjs/core";
import { ActivityEvent, streamRun } from "../api/client";

const KIND_ICON: Record<string, any> = {
  phase: "flow-linear", agent_enter: "person", agent_exit: "tick",
  tool_call: "cog", tool_result: "import", reasoning: "lightbulb",
  verification: "confirm", approval_pending: "hand-up", complete: "endorsed",
  error: "error", token: "font", state_update: "database",
};

export function ActivityStream({ runId }: { runId: string }) {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [thinking, setThinking] = useState(false);
  const [tokens, setTokens] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setEvents([]);
    const stop = streamRun(runId, (e) => {
      setEvents((prev) => {
        // merge consecutive token frames from the same agent into one line
        if (e.kind === "token" && prev.length && prev[prev.length - 1].kind === "token"
            && prev[prev.length - 1].agent === e.agent) {
          const merged = [...prev];
          merged[merged.length - 1] = {
            ...merged[merged.length - 1],
            label: merged[merged.length - 1].label + e.label,
          };
          return merged;
        }
        return [...prev, e];
      });
      if (e.token_delta) setTokens((c) => c + (e.token_delta || 0));
      setThinking(!["complete", "error", "approval_pending"].includes(e.kind));
    });
    return stop;
  }, [runId]);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [events]);

  return (
    <div className="activity-panel">
      <div className="activity-head">
        <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Icon icon="pulse" color="var(--accent)" />
          <b>Activity</b>
          {thinking && <span className="muted thinking-dots" style={{ fontSize: 12 }}>thinking</span>}
        </span>
        <Tag minimal className="metric">{tokens} out tok</Tag>
      </div>
      <div className="activity-list" ref={listRef}>
        {events.map((e, i) => (
          <div key={i} className={`activity-row k-${e.kind}`}>
            <span className="ts">{new Date(e.ts).toLocaleTimeString([], { hour12: false })}</span>
            <Icon icon={KIND_ICON[e.kind] || "dot"} size={12}
                  color={e.level === "warn" ? "var(--warning)" : "var(--muted)"}
                  style={{ marginTop: 2 }} />
            <span className="label">{e.label}</span>
          </div>
        ))}
        {events.length === 0 && <div className="muted" style={{ padding: 16 }}>Waiting for the run to start…</div>}
      </div>
    </div>
  );
}
