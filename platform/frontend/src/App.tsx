import { useState } from "react";
import { Navbar, Alignment, Button, Tag, Tooltip } from "@blueprintjs/core";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Landing } from "./screens/Landing";
import { Home } from "./screens/Home";
import { Garden } from "./screens/Garden";
import { Studio } from "./screens/Studio";
import { Tools } from "./screens/Tools";
import { Connectors } from "./screens/Connectors";
import { McpServers } from "./screens/McpServers";
import { Analytics } from "./screens/Analytics";
import { ModelEndpoints } from "./screens/ModelEndpoints";
import { Ontology } from "./screens/Ontology";
import { RagStudio } from "./screens/RagStudio";
import { DataScienceLab } from "./screens/DataScienceLab";
import { Files } from "./screens/Files";
import { Monitoring } from "./screens/Monitoring";
import { Bundles } from "./screens/Bundles";
import { Schedules } from "./screens/Schedules";
import { Governance } from "./screens/Governance";
import { Insights } from "./screens/Insights";
import { Templates } from "./screens/Templates";
import { Chat } from "./screens/Chat";
import { SetupGuide } from "./screens/SetupGuide";
import { RunView } from "./screens/RunView";
import { Workflow } from "./api/client";

type Screen = "home" | "garden" | "tools" | "connectors" | "mcp" | "endpoints" | "analytics" | "ontology" | "rag" | "dsl" | "files" | "studio" | "templates" | "chat" | "run"
  | "monitor" | "bundles" | "schedules" | "governance" | "insights" | "help";

export default function App() {
  const [entered, setEntered] = useState(false);
  const [screen, setScreen] = useState<Screen>("home");
  const [collapsed, setCollapsed] = useState(false);
  const [activeRun, setActiveRun] = useState<{ runId: string; wf: Workflow } | null>(null);

  const openRun = (runId: string, wf: Workflow) => { setActiveRun({ runId, wf }); setScreen("run"); };
  const openTest = (runId: string, name: string) =>
    openRun(runId, { workflow_id: "", name: `Test: ${name}`, goal_prompt: "", nodes: [], edges: [], approval_gates: [] });

  if (!entered) return <Landing onEnter={() => setEntered(true)} />;

  const nav = (icon: any, label: string, key: Screen) => {
    const btn = (
      <Button minimal fill={!collapsed} alignText="left" icon={icon} text={collapsed ? undefined : label}
        active={screen === key} onClick={() => setScreen(key)}
        aria-label={label} style={collapsed ? { justifyContent: "center" } : undefined} />
    );
    return collapsed ? <Tooltip content={label} placement="right" key={key}>{btn}</Tooltip> : btn;
  };

  return (
    <div className="app-shell">
      <Navbar style={{ background: "var(--panel)", borderBottom: "1px solid var(--border)" }}>
        <Navbar.Group align={Alignment.LEFT}>
          <Navbar.Heading style={{ fontWeight: 800, cursor: "pointer" }} onClick={() => setScreen("home")}>
            TCS <span style={{ color: "var(--accent)" }}>AI Studio</span>
            <Tag minimal round intent="primary" style={{ marginLeft: 8 }}>v1.0</Tag>
          </Navbar.Heading>
        </Navbar.Group>
        <Navbar.Group align={Alignment.RIGHT}>
          <Tag minimal icon="cloud" className="metric">Enterprise Agentic AI Platform</Tag>
        </Navbar.Group>
      </Navbar>

      <div className="app-body">
        <div className={collapsed ? "nav-rail collapsed" : "nav-rail"}>
          <div className="brand-row">
            {!collapsed && <div className="brand">TCS AI Studio</div>}
            <Tooltip content={collapsed ? "Expand menu" : "Collapse menu"} placement="right">
              <Button minimal icon={collapsed ? "menu-open" : "menu-closed"}
                aria-label="Toggle menu" onClick={() => setCollapsed(!collapsed)} />
            </Tooltip>
          </div>
          {nav("home", "Home", "home")}
          {nav("layout-grid", "Agent Garden", "garden")}
          {nav("wrench", "Tool Registry", "tools")}
          {nav("data-connection", "Connectors", "connectors")}
          {nav("data-lineage", "MCP Servers", "mcp")}
          {nav("grouped-bar-chart", "Analytics", "analytics")}
          {nav("ip-address", "Model Endpoints", "endpoints")}
          {nav("graph", "Ontology", "ontology")}
          {nav("search-template", "RAG Studio", "rag")}
          {nav("lab-test", "Data Science Lab", "dsl")}
          {nav("folder-close", "File Storage", "files")}
          {nav("flows", "Workflow Studio", "studio")}
          {nav("grid-view", "Templates", "templates")}
          {nav("chat", "Chat", "chat")}
          {nav("cube", "Bundles", "bundles")}
          {nav("time", "Schedules", "schedules")}
          {nav("pulse", "Runs", "run")}
          {nav("timeline-line-chart", "Monitoring", "monitor")}
          {nav("lightbulb", "Insights", "insights")}
          {nav("shield", "Governance", "governance")}
          {nav("help", "Setup & Help", "help")}
        </div>

        <div className="main-pane" key={screen}>
          <ErrorBoundary onReset={() => setScreen("home")}>
          {screen === "home" && <Home go={setScreen} />}
          {screen === "garden" && <Garden onTest={openTest} />}
          {screen === "tools" && <Tools />}
          {screen === "connectors" && <Connectors />}
          {screen === "mcp" && <McpServers />}
          {screen === "analytics" && <Analytics />}
          {screen === "endpoints" && <ModelEndpoints />}
          {screen === "ontology" && <Ontology />}
          {screen === "rag" && <RagStudio />}
          {screen === "dsl" && <DataScienceLab />}
          {screen === "files" && <Files />}
          {screen === "studio" && <Studio onRun={openRun} />}
          {screen === "templates" && <Templates onRun={openRun} />}
          {screen === "chat" && <Chat />}
          {screen === "bundles" && <Bundles />}
          {screen === "schedules" && <Schedules />}
          {screen === "monitor" && <Monitoring />}
          {screen === "insights" && <Insights />}
          {screen === "governance" && <Governance />}
          {screen === "help" && <SetupGuide />}
          {screen === "run" && activeRun && <RunView runId={activeRun.runId} workflow={activeRun.wf} />}
          {screen === "run" && !activeRun && <Empty text="Start a run from the Workflow Studio, or test an agent in the Garden." />}
          </ErrorBoundary>
        </div>
      </div>

      <div className="app-footer">
        © 2026 <b>Tata Consultancy Services</b>. All rights reserved. · TCS AI Studio v1.0
      </div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="muted" style={{ padding: 40, textAlign: "center" }}>{text}</div>;
}
