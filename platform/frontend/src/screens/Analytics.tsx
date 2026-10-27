import { Callout, Button } from "@blueprintjs/core";

// Apache Superset is proxied same-origin at /superset/ by nginx, so it embeds here cleanly.
const SUPERSET_URL = "/superset/";

export function Analytics() {
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", minHeight: 0 }}>
      <div className="section-head" style={{ marginBottom: 10 }}>
        <div>
          <h2>Analytics &amp; Dashboards</h2>
          <span className="muted">Apache Superset — build and view dashboards; agents can create them via the Superset MCP server.</span>
        </div>
        <Button icon="share" text="Open in new tab" minimal
          onClick={() => window.open(SUPERSET_URL, "_blank", "noopener")} />
      </div>

      <Callout icon="info-sign" style={{ marginBottom: 10 }}>
        Superset runs as a container in this platform. The <b>Dynamic Dashboard</b> workflow can build
        dashboards here automatically by passing MLflow data to the Superset MCP server. First-time
        login uses the Superset admin account configured in your environment.
      </Callout>

      <div style={{ flex: 1, minHeight: 0, border: "1px solid var(--border)", borderRadius: 10, overflow: "hidden", background: "#0c120c" }}>
        <iframe
          title="Apache Superset"
          src={SUPERSET_URL}
          style={{ width: "100%", height: "100%", border: "none" }}
          allow="clipboard-read; clipboard-write; fullscreen"
        />
      </div>
    </div>
  );
}
