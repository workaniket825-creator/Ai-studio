"""Data contracts — Appendix A of the architecture spec.

Every persisted entity is defined here so the API and store share one source of truth.
These mirror the AgentCard (9.1), WorkflowGraph (9.2) and Appendix A schemas.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:8]}"


# ----------------------------- enums -----------------------------
class Visibility(str, Enum):
    private = "private"
    team = "team"
    org = "org"


class AgentCategory(str, Enum):
    foundation = "foundation"
    use_case = "use_case"
    system = "system"


class CollaborationRole(str, Enum):
    standalone = "standalone"
    coordinator = "coordinator"
    specialist = "specialist"
    peer = "peer"


class CollaborationType(str, Enum):
    delegate = "delegate"
    agent_tool = "agent_tool"
    a2a_peer = "a2a_peer"


class CollaborationMode(str, Enum):
    chat = "chat"
    task = "task"
    single_turn = "single_turn"


class ToolType(str, Enum):
    function = "function"
    openapi = "openapi"
    mcp = "mcp"
    agent = "agent"
    builtin = "builtin"
    file_access = "file_access"
    model = "model"
    connector = "connector"


class NodeStatus(str, Enum):
    reused = "reused"
    to_be_created = "to_be_created"
    modified = "modified"
    remote = "remote"


class RunStatus(str, Enum):
    pending = "pending"
    planning = "planning"
    awaiting_approval = "awaiting_approval"
    running = "running"
    paused = "paused"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class ActivityKind(str, Enum):
    phase = "phase"
    agent_enter = "agent_enter"
    agent_exit = "agent_exit"
    tool_call = "tool_call"
    tool_result = "tool_result"
    reasoning = "reasoning"
    token = "token"
    state_update = "state_update"
    verification = "verification"
    approval_pending = "approval_pending"
    error = "error"
    complete = "complete"


# ------------------------- nested models -------------------------
class ModelConfig(BaseModel):
    provider: str = "google"
    model: str = "gemini-3-flash"
    endpoint_id: Optional[str] = None   # link to a UI-configured Model Endpoint
    fallback_model: Optional[str] = None
    temperature: float = 0.2
    max_output_tokens: int = 4096


class Prompts(BaseModel):
    system_prompt: str = ""
    user_prompt_template: str = ""
    prompt_registry_ref: Optional[str] = None


class IOContract(BaseModel):
    output_key: str = "result"
    output_schema: Optional[dict[str, Any]] = None
    state_reads: list[str] = Field(default_factory=list)
    state_writes: list[str] = Field(default_factory=list)


class ToolBinding(BaseModel):
    type: ToolType
    ref: Optional[str] = None       # -> ToolSpec id
    name: Optional[str] = None      # builtin name
    operations: list[str] = Field(default_factory=list)
    workspace: Optional[str] = None  # file_access: storage folder the agent reads/writes
    model_name: Optional[str] = None  # model: registered ML model name
    serving_url: Optional[str] = None  # model: optional serving endpoint override
    tool_policy: Optional[str] = None  # "auto" (default) | "required" | "force:<tool_fn_name>"


class Collaborator(BaseModel):
    agent_ref: str
    type: CollaborationType
    mode: Optional[CollaborationMode] = None
    auth_ref: Optional[str] = None


class TransferPolicy(BaseModel):
    allow_transfer_to_parent: bool = True
    allow_transfer_to_peers: bool = False
    escalation_policy: str = "on_failure"


class CollaborationBlock(BaseModel):
    role: CollaborationRole = CollaborationRole.standalone
    collaborators: list[Collaborator] = Field(default_factory=list)
    transfer: TransferPolicy = Field(default_factory=TransferPolicy)
    routing_instruction: Optional[str] = None
    shared_state_keys: list[str] = Field(default_factory=list)


class MemoryConfig(BaseModel):
    enabled: bool = False
    scope: str = "user"
    service: str = "in_memory"
    read: bool = True
    write_on_complete: bool = True


class Guardrails(BaseModel):
    pii_redaction: bool = False
    human_in_the_loop: dict[str, Any] = Field(default_factory=dict)
    limits: dict[str, Any] = Field(
        default_factory=lambda: {"max_steps": 25, "max_tool_calls": 15,
                                 "timeout_s": 120, "max_output_tokens": 8000}
    )


# ------------------------------ entities ------------------------------
class AgentCard(BaseModel):
    agent_id: str = Field(default_factory=lambda: _id("agent"))
    agent_name: str
    version: int = 1
    status: str = "published"
    category: AgentCategory = AgentCategory.use_case
    role: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    owner: dict[str, str] = Field(default_factory=dict)
    visibility: Visibility = Visibility.org
    model_config_: ModelConfig = Field(default_factory=ModelConfig, alias="model_config")
    prompts: Prompts = Field(default_factory=Prompts)
    io_contract: IOContract = Field(default_factory=IOContract)
    tools: list[ToolBinding] = Field(default_factory=list)
    tool_policy: str = "auto"  # auto | required | force:<tool_fn_name> — deterministic tool use
    collaboration: CollaborationBlock = Field(default_factory=CollaborationBlock)
    memory_config: MemoryConfig = Field(default_factory=MemoryConfig)
    guardrails: Guardrails = Field(default_factory=Guardrails)
    metrics: dict[str, Any] = Field(default_factory=dict)  # runs, success_rate, avg_cost (from MLflow)
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)

    model_config = {"populate_by_name": True, "protected_namespaces": ()}


class ToolSpec(BaseModel):
    id: str = Field(default_factory=lambda: _id("tool"))
    name: str
    type: ToolType
    description: str = ""
    spec: dict[str, Any] = Field(default_factory=dict)
    operations: list[str] = Field(default_factory=list)
    auth_ref: Optional[str] = None
    requires_confirmation: bool = False
    version: int = 1
    lint: dict[str, Any] = Field(default_factory=dict)


class WorkflowNode(BaseModel):
    node_id: str
    agent_ref: Optional[str] = None
    provisional_card: Optional[dict[str, Any]] = None
    status: NodeStatus = NodeStatus.reused
    overrides: dict[str, Any] = Field(default_factory=dict)
    input_bindings: dict[str, str] = Field(default_factory=dict)
    output_key: str = "result"


class WorkflowEdge(BaseModel):
    from_: str = Field(alias="from")
    to: str
    type: str = "sequential"  # sequential | parallel | delegation | call | a2a

    model_config = {"populate_by_name": True}


class WorkflowGraph(BaseModel):
    workflow_id: str = Field(default_factory=lambda: _id("wf"))
    name: str
    version: int = 1
    goal_prompt: str = ""
    designed_by: Optional[str] = None
    nodes: list[WorkflowNode] = Field(default_factory=list)
    edges: list[WorkflowEdge] = Field(default_factory=list)
    control_flow: dict[str, Any] = Field(default_factory=lambda: {"type": "sequential"})
    approval_gates: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)


class Run(BaseModel):
    run_id: str = Field(default_factory=lambda: _id("run"))
    workflow_id: Optional[str] = None
    agent_id: Optional[str] = None
    workflow_name: str = ""
    status: RunStatus = RunStatus.pending
    ontology_hops: int = 1
    input: dict[str, Any] = Field(default_factory=dict)
    plan: Optional[list[dict[str, Any]]] = None
    mlflow_trace_id: Optional[str] = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    tokens: int = 0
    latency_ms: int = 0
    meta: bool = False
    feedback: list[dict[str, Any]] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)  # {verdict, revisions}
    steers: list[dict[str, Any]] = Field(default_factory=list)  # mid-run guidance (§7)
    node_outputs: list[dict[str, Any]] = Field(default_factory=list)  # per-agent content + steps
    final_output: str = ""       # the workflow's final answer (last node output)
    error: str = ""              # honest error message when a run fails
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)


class Bundle(BaseModel):
    """Role Pack (spec §19): installable agents + tools + skills for a domain."""
    id: str = Field(default_factory=lambda: _id("bundle"))
    name: str
    category: str = "custom"
    description: str = ""
    agents: list[dict[str, Any]] = Field(default_factory=list)   # agent card templates
    tools: list[dict[str, Any]] = Field(default_factory=list)
    version: int = 1
    installs: int = 0


class Schedule(BaseModel):
    """Unattended run trigger (spec §7)."""
    id: str = Field(default_factory=lambda: _id("sched"))
    workflow_id: str
    workflow_name: str = ""
    trigger: str = "interval"          # interval | manual
    interval_seconds: int = 300
    input: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    next_run: Optional[str] = None
    last_run: Optional[str] = None
    last_status: Optional[str] = None
    created_at: str = Field(default_factory=_now)


class ActivityEvent(BaseModel):
    run_id: str
    seq: int
    ts: str = Field(default_factory=_now)
    node_id: Optional[str] = None
    agent: Optional[str] = None
    phase: str = "act"           # plan | act | verify | done
    kind: ActivityKind = ActivityKind.phase
    label: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    level: str = "info"          # info | warn | error
    token_delta: Optional[int] = None
    in_tokens: Optional[int] = None
    out_tokens: Optional[int] = None
    latency_ms: Optional[int] = None


# ------------------------- request models -------------------------
class RunRequest(BaseModel):
    workflow_id: Optional[str] = None
    agent_id: Optional[str] = None
    ontology_hops: int = 1
    input: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input", mode="before")
    @classmethod
    def _coerce_input(cls, v):
        if v is None:
            return {}
        if isinstance(v, dict):
            return v
        return {"input": v}
