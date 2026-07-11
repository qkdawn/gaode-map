from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


ToolCategory = Literal["information", "action", "processing"]
ToolLayer = Literal["L1", "L2", "L4"]
ToolUiTier = Literal["foundation", "capability", "scenario"]
ToolDataDomain = Literal[
    "poi",
    "grid",
    "population",
    "nightlight",
    "road",
    "landuse",
    "remote_sensing",
    "commerce",
    "policy",
    "competitor",
    "general",
]
ToolCapabilityType = Literal["fetch", "transform", "analyze", "interpret", "decide", "none"]
ToolSceneType = Literal[
    "area_character",
    "site_selection",
    "vitality",
    "tod",
    "livability",
    "facility_gap",
    "renewal_priority",
    "general",
]
ToolLlmExposure = Literal["primary", "secondary", "hidden"]
GovernanceMode = Literal["auto", "guarded", "readonly"]
AgentExecutionMode = Literal["auto", "deep"]
AgentStatus = Literal["answered", "requires_clarification", "requires_risk_confirmation", "failed"]
AgentStage = Literal[
    "gating",
    "clarifying",
    "executing",
    "synthesizing",
    "answered",
    "requires_clarification",
    "requires_risk_confirmation",
    "failed",
]
PersistedAgentStatus = Literal[
    "idle",
    "running",
    "answered",
    "requires_clarification",
    "requires_risk_confirmation",
    "failed",
]
ToolStatus = Literal["success", "failed", "skipped"]
ExecutionTraceStatus = Literal["success", "failed", "skipped", "blocked"]
ToolLoopStatus = Literal["completed", "requires_risk_confirmation", "failed"]
AgentSessionTitleSource = Literal["user", "ai", "fallback"]
AgentTurnStreamEventType = Literal["meta", "status", "thinking", "reasoning_delta", "trace", "plan", "final", "error"]
AgentSummaryStreamEventType = Literal[
    "status",
    "section_start",
    "section_delta",
    "section_complete",
    "panel_payload",
    "final",
    "error",
]
ThinkingState = Literal["pending", "active", "completed", "failed"]
EvidenceConfidence = Literal["strong", "moderate", "weak"]


class AgentMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"] = "user"
    content: str = ""
    process: "AgentMessageProcess" = Field(default_factory=lambda: AgentMessageProcess())


class AnalysisSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: Dict[str, Any] = Field(default_factory=dict)
    scope: Dict[str, Any] = Field(default_factory=dict)
    pois: List[Dict[str, Any]] = Field(default_factory=list)
    poi_summary: Dict[str, Any] = Field(default_factory=dict)
    h3: Dict[str, Any] = Field(default_factory=dict)
    road: Dict[str, Any] = Field(default_factory=dict)
    population: Dict[str, Any] = Field(default_factory=dict)
    nightlight: Dict[str, Any] = Field(default_factory=dict)
    shared_grid: Dict[str, Any] = Field(default_factory=dict)
    param_bundles: Dict[str, Any] = Field(default_factory=dict)
    frontend_analysis: Dict[str, Any] = Field(default_factory=dict)
    active_panel: str = ""
    current_filters: Dict[str, Any] = Field(default_factory=dict)


class AgentVisualSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot_id: str = ""
    kind: str = ""
    title: str = ""
    data_url: str = ""
    source: str = "frontend_map"
    captured_at: str = ""
    bounds: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)


class AgentSelectedSourcesContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: List[Dict[str, Any]] = Field(default_factory=list)

    def source_items(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in self.sources]


class AgentMapSearchContext(BaseModel):
    model_config = ConfigDict(extra="allow")

    evidence_version: str = ""
    source: str = ""
    rule: str = ""
    place_anchors: Dict[str, Any] = Field(default_factory=dict)
    spatial_anchors: Dict[str, Any] = Field(default_factory=dict)

    def as_artifact(self) -> Dict[str, Any]:
        payload = self.model_dump(mode="json")
        return {key: value for key, value in payload.items() if value not in ("", None, {}, [])}


class AgentExecutionProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_profile_id: str = ""
    skill_id: str = ""
    skill_scope: Literal["turn", "conversation"] = "turn"


class EffectiveExecutionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_profile_id: str = ""
    model_display_name: str = ""
    provider: str = ""
    model: str = ""
    skill_id: str = ""
    skill_display_name: str = ""
    skill_scope: Literal["turn", "conversation"] = "turn"


class ConversationExecutionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_profile_id: str = ""
    pinned_skill_id: str = ""


class CapabilityInputSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    mode: Literal[
        "latest_successful", "specific_run", "recalculate", "ignore_optional"
    ] = "latest_successful"
    run_id: str = ""

    @model_validator(mode="after")
    def validate_run_selection(self):
        self.requirement_id = str(self.requirement_id or "").strip()
        self.run_id = str(self.run_id or "").strip()
        if not self.requirement_id:
            raise ValueError("capability_input_requirement_id_required")
        if self.mode == "specific_run" and not self.run_id:
            raise ValueError("capability_input_run_id_required")
        if self.mode != "specific_run" and self.run_id:
            raise ValueError("capability_input_run_id_not_allowed")
        return self


class AgentTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = ""
    history_id: str = ""
    target_capability_id: str = ""
    capability_input_selections: List[CapabilityInputSelection] = Field(default_factory=list)
    messages: List[AgentMessage] = Field(default_factory=list)
    analysis_snapshot: AnalysisSnapshot = Field(default_factory=AnalysisSnapshot)
    risk_confirmations: List[str] = Field(default_factory=list)
    governance_mode: GovernanceMode = "auto"
    execution_mode: AgentExecutionMode = "auto"
    visual_snapshots: List[AgentVisualSnapshot] = Field(default_factory=list)
    map_search_context: AgentMapSearchContext = Field(default_factory=AgentMapSearchContext)
    selected_sources_context: AgentSelectedSourcesContext = Field(default_factory=AgentSelectedSourcesContext)
    execution_profile: AgentExecutionProfileRequest = Field(default_factory=AgentExecutionProfileRequest)


class AgentSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = ""
    history_id: str = ""
    analysis_snapshot: AnalysisSnapshot = Field(default_factory=AnalysisSnapshot)


class AgentSiteSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = ""
    history_id: str = ""
    analysis_snapshot: AnalysisSnapshot = Field(default_factory=AnalysisSnapshot)
    place_type: str = ""
    policy_key: str = "business_catchment_1km"
    strategy: str = "balanced"
    scenario: str = "commuter"
    source: str = "local"
    year: Optional[int] = None


class AgentSiteSelectionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["success", "failed"] = "success"
    site_selection_pack: Dict[str, Any] = Field(default_factory=dict)
    current_target_supply_gap: Dict[str, Any] = Field(default_factory=dict)
    current_site_candidate_scores: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    error: str = ""


class ContextAskTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["report_section", "trend_chart", "trend_metric", "site_candidate", "analysis_sources", "capability_run"] = "report_section"
    id: str = ""
    title: str = ""
    source: Literal["report", "iteration", "site_selection", "analysis", "capability_run"] = "report"
    summary: str = ""
    evidence: List[Any] = Field(default_factory=list)
    artifact_refs: List[str] = Field(default_factory=list)
    payload: Dict[str, Any] = Field(default_factory=dict)


class AgentContextAskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str = ""
    history_id: str = ""
    question: str = ""
    analysis_snapshot: AnalysisSnapshot = Field(default_factory=AnalysisSnapshot)
    target: ContextAskTarget = Field(default_factory=ContextAskTarget)
    require_ai: bool = False


class AgentContextAskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["success", "failed"] = "success"
    answer: str = ""
    evidence: List[Any] = Field(default_factory=list)
    citations: List[Any] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    error: str = ""


class AgentSummaryDataReadiness(BaseModel):
    model_config = ConfigDict(extra="ignore")

    checked: bool = False
    ready: bool = False
    missing_tasks: List[str] = Field(default_factory=list)
    reused: List[str] = Field(default_factory=list)
    fetched: List[str] = Field(default_factory=list)


class AgentSummaryProgressStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = ""
    label: str = ""
    status: Literal["pending", "running", "completed", "failed"] = "pending"


class AgentSummaryReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_readiness: AgentSummaryDataReadiness = Field(default_factory=AgentSummaryDataReadiness)
    error: str = ""
    warnings: List[str] = Field(default_factory=list)
    phases: List[str] = Field(default_factory=list)
    progress_steps: List[AgentSummaryProgressStep] = Field(default_factory=list)


class AgentSummaryGenerateResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data_readiness: AgentSummaryDataReadiness = Field(default_factory=AgentSummaryDataReadiness)
    panel_payloads: Dict[str, Any] = Field(default_factory=dict)
    summary_pack: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    warnings: List[str] = Field(default_factory=list)
    phases: List[str] = Field(default_factory=list)
    progress_steps: List[AgentSummaryProgressStep] = Field(default_factory=list)


class AgentIterationNightlightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: Dict[str, Any] = Field(default_factory=dict)


class AgentIterationNightlightResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = "failed"
    ai_analysis: Dict[str, str] = Field(default_factory=dict)
    ai_prompt: str = ""
    ai_prompt_payload_note: str = ""
    prompt_snapshot: Dict[str, Any] = Field(default_factory=dict)
    prompt_snapshots: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class AgentIterationPoiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence: Dict[str, Any] = Field(default_factory=dict)


class AgentIterationPoiResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = "failed"
    ai_summary: List[str] = Field(default_factory=list)
    ai_insights: Dict[str, Any] = Field(default_factory=dict)
    driver_analysis: List[Dict[str, Any]] = Field(default_factory=list)
    planning_implications: List[Dict[str, Any]] = Field(default_factory=list)
    report_title: str = ""
    report_sections: List[Dict[str, Any]] = Field(default_factory=list)
    report_content: str = ""
    spatial_factors: Dict[str, Any] = Field(default_factory=dict)
    subcategory_spatial_trend_rows: List[Dict[str, Any]] = Field(default_factory=list)
    subcategory_spatial_summary: List[str] = Field(default_factory=list)
    ai_prompt: str = ""
    ai_prompt_payload_note: str = ""
    prompt_snapshot: Dict[str, Any] = Field(default_factory=dict)
    prompt_snapshots: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class AgentIterationPoiBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    history_id: str = ""
    years: List[int] = Field(default_factory=list)
    center: List[float] = Field(default_factory=list)
    h3_evidence: Dict[str, Any] = Field(default_factory=dict)
    yearly_grid_evidence: Dict[str, Any] = Field(default_factory=dict)


class AgentIterationPoiBuildResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = "failed"
    source: str = ""
    historyId: str = ""
    years: List[int] = Field(default_factory=list)
    center: List[float] = Field(default_factory=list)
    summaries: List[Dict[str, Any]] = Field(default_factory=list)
    trend_rows: List[Dict[str, Any]] = Field(default_factory=list)
    total_series: List[Dict[str, Any]] = Field(default_factory=list)
    category_stack: List[Dict[str, Any]] = Field(default_factory=list)
    subcategory_stack: List[Dict[str, Any]] = Field(default_factory=list)
    subcategory_trend_rows: List[Dict[str, Any]] = Field(default_factory=list)
    area_heatmaps: List[Dict[str, Any]] = Field(default_factory=list)
    area_heatmap_basemap: Dict[str, Any] = Field(default_factory=dict)
    area_heatmap_boundary: List[Dict[str, Any]] = Field(default_factory=list)
    area_heatmap_polygon: List[Any] = Field(default_factory=list)
    spatial_factors: Dict[str, Any] = Field(default_factory=dict)
    subcategory_spatial_trend_rows: List[Dict[str, Any]] = Field(default_factory=list)
    subcategory_spatial_summary: List[str] = Field(default_factory=list)
    h3_evidence: Dict[str, Any] = Field(default_factory=dict)
    yearly_grid_evidence: Dict[str, Any] = Field(default_factory=dict)
    rule_summary: List[str] = Field(default_factory=list)
    rule_insights: Dict[str, str] = Field(default_factory=dict)
    ai_summary: List[str] = Field(default_factory=list)
    ai_insights: Dict[str, Any] = Field(default_factory=dict)
    driver_analysis: List[Dict[str, Any]] = Field(default_factory=list)
    planning_implications: List[Dict[str, Any]] = Field(default_factory=list)
    report_title: str = ""
    report_sections: List[Dict[str, Any]] = Field(default_factory=list)
    report_content: str = ""
    ai_status: str = "pending"
    ai_prompt: str = ""
    ai_prompt_payload_note: str = ""
    ai_error: str = ""
    error: str = ""


class ToolSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str
    category: ToolCategory
    layer: ToolLayer
    ui_tier: ToolUiTier = "foundation"
    data_domain: ToolDataDomain = "general"
    capability_type: ToolCapabilityType = "none"
    scene_type: ToolSceneType = "general"
    llm_exposure: ToolLlmExposure = "secondary"
    toolkit_id: str = ""
    default_policy_key: str = ""
    evidence_contract: List[str] = Field(default_factory=list)
    applicable_scenarios: List[str] = Field(default_factory=list)
    cautions: List[str] = Field(default_factory=list)
    requires: List[str] = Field(default_factory=list)
    produces: List[str] = Field(default_factory=list)
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    readonly: bool = False
    cost_level: Literal["safe", "normal", "expensive"] = "safe"
    risk_level: Literal["safe", "guarded", "expensive"] = "safe"
    timeout_sec: int = 30
    cacheable: bool = False


class AgentToolSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    category: ToolCategory
    layer: ToolLayer
    ui_tier: ToolUiTier = "foundation"
    data_domain: ToolDataDomain = "general"
    capability_type: ToolCapabilityType = "none"
    scene_type: ToolSceneType = "general"
    llm_exposure: ToolLlmExposure = "secondary"
    toolkit_id: str = ""
    default_policy_key: str = ""
    evidence_contract: List[str] = Field(default_factory=list)
    applicable_scenarios: List[str] = Field(default_factory=list)
    cautions: List[str] = Field(default_factory=list)
    requires: List[str] = Field(default_factory=list)
    produces: List[str] = Field(default_factory=list)
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    readonly: bool = False
    cost_level: Literal["safe", "normal", "expensive"] = "safe"
    risk_level: Literal["safe", "guarded", "expensive"] = "safe"
    timeout_sec: int = 30
    cacheable: bool = False


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    evidence_goal: str = ""
    expected_artifacts: List[str] = Field(default_factory=list)
    optional: bool = False


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool_name: str
    status: ToolStatus = "success"
    result: Dict[str, Any] = Field(default_factory=dict)
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class ExecutionTraceItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tool_name: str
    status: ExecutionTraceStatus
    reason: str = ""
    message: str = ""
    cost_level: str = "safe"
    risk_level: str = "safe"
    evidence_count: int = 0
    warning_count: int = 0


class AgentEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    metric: str
    value: Any = None
    interpretation: str = ""
    source: str = ""
    confidence: EvidenceConfidence = "weak"
    limitation: str = ""


TranslationStatus = Literal["ready", "skipped", "failed"]


class AgentTranslationItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    metric: str = ""
    source: str = ""
    raw_signal: str = ""
    spatial_phenomenon: str = ""
    human_experience: str = ""
    planning_implication: str = ""
    action_hint: str = ""
    confidence: EvidenceConfidence = "weak"
    boundary: str = ""


class AgentTranslationPack(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: TranslationStatus = "skipped"
    summary: str = ""
    items: List[AgentTranslationItem] = Field(default_factory=list)
    error: str = ""

    @model_validator(mode="before")
    @classmethod
    def _normalize_nullable_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        value = dict(value)
        if value.get("status") is None:
            value["status"] = "skipped"
        for key in ["summary", "error"]:
            if value.get(key) is None:
                value[key] = ""
        if value.get("items") is None:
            value["items"] = []
        return value


class GateDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["pass", "clarify", "block"] = "pass"
    clarification_question: str = ""
    clarification_questions: List[str] = Field(default_factory=list)
    clarification_options: List[str] = Field(default_factory=list)
    missing_information: List[str] = Field(default_factory=list)
    question_type: str = ""
    summary: str = ""
    blocked_reason: str = ""
    research_notes: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_nullable_fields(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        value = dict(value)
        for key in [
            "status",
            "clarification_question",
            "question_type",
            "summary",
            "blocked_reason",
        ]:
            if value.get(key) is None:
                value[key] = ""
        for key in [
            "clarification_questions",
            "clarification_options",
            "missing_information",
            "research_notes",
        ]:
            if value.get(key) is None:
                value[key] = []
        return value

    @model_validator(mode="after")
    def _normalize_clarification(self):
        if not self.clarification_question and self.clarification_questions:
            self.clarification_question = "\n".join(
                f"{index + 1}. {item}"
                for index, item in enumerate(self.clarification_questions[:3])
                if str(item).strip()
            )
        return self


class ClarificationBundle(BaseModel):
    model_config = ConfigDict(extra="ignore")

    missing_information: List[str] = Field(default_factory=list)
    questions: List[str] = Field(default_factory=list)
    summary: str = ""


class AgentContextSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    has_scope: bool = False
    available_results: List[str] = Field(default_factory=list)
    available_context_sources: List[str] = Field(default_factory=list)
    active_panel: str = ""
    filters_digest: Dict[str, Any] = Field(default_factory=dict)


class ContextBundle(BaseModel):
    model_config = ConfigDict(extra="ignore")

    facts: Dict[str, Any] = Field(default_factory=dict)
    analysis: Dict[str, Any] = Field(default_factory=dict)
    limits: List[str] = Field(default_factory=list)
    available_artifacts: List[str] = Field(default_factory=list)
    context_summary: AgentContextSummary = Field(default_factory=AgentContextSummary)


class AuditResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    passed: bool = True
    issues: List[str] = Field(default_factory=list)
    missing_evidence: List[str] = Field(default_factory=list)
    required_evidence: List[str] = Field(default_factory=list)


class WorkingMemory(BaseModel):
    model_config = ConfigDict(extra="ignore")

    artifacts: Dict[str, Any] = Field(default_factory=dict)
    tool_results: List[ToolResult] = Field(default_factory=list)
    execution_trace: List[ExecutionTraceItem] = Field(default_factory=list)
    research_notes: List[str] = Field(default_factory=list)
    audit_issues: List[str] = Field(default_factory=list)


class ToolLoopResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: ToolLoopStatus = "completed"
    steps: List[PlanStep] = Field(default_factory=list)
    used_tools: List[str] = Field(default_factory=list)
    execution_trace: List[ExecutionTraceItem] = Field(default_factory=list)
    tool_results: List[ToolResult] = Field(default_factory=list)
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    research_notes: List[str] = Field(default_factory=list)
    provider_response_id: Optional[str] = None
    assistant_summary: str = ""
    stop_reason: str = ""
    warnings: List[str] = Field(default_factory=list)
    error: str = ""
    risk_prompt: str = ""


class AgentTurnOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = ""
    clarification_question: str = ""
    clarification_options: List[str] = Field(default_factory=list)
    risk_prompt: str = ""
    panel_payloads: Dict[str, Any] = Field(default_factory=dict)


class AgentTurnDiagnostics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    execution_trace: List[ExecutionTraceItem] = Field(default_factory=list)
    used_tools: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    research_notes: List[str] = Field(default_factory=list)
    audit_issues: List[str] = Field(default_factory=list)
    thinking_timeline: List["AgentThinkingItem"] = Field(default_factory=list)
    planning_summary: str = ""
    audit_summary: str = ""
    translation_pack: AgentTranslationPack = Field(default_factory=AgentTranslationPack)
    latency_ms: Dict[str, int] = Field(default_factory=dict)
    error: str = ""


class AgentThinkingItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    phase: str
    title: str
    detail: str = ""
    display_text: str = ""
    items: List[str] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)
    state: ThinkingState = "pending"

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        value = dict(value)
        if "display_text" not in value and "displayText" in value:
            value["display_text"] = value.get("displayText")
        return value


class AgentTurnStreamEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: AgentTurnStreamEventType
    payload: Dict[str, Any] = Field(default_factory=dict)


class AgentSummaryStreamEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: AgentSummaryStreamEventType
    payload: Dict[str, Any] = Field(default_factory=dict)


class AgentPlanEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: List[PlanStep] = Field(default_factory=list)
    summary: str = ""


class AgentMessageProcess(BaseModel):
    model_config = ConfigDict(extra="ignore")

    turn_id: str = ""
    status: str = ""
    stage: str = ""
    started_at: str = ""
    completed_at: str = ""
    elapsed_ms: int = 0
    thinking_timeline: List[AgentThinkingItem] = Field(default_factory=list)
    execution_trace: List[ExecutionTraceItem] = Field(default_factory=list)
    plan: AgentPlanEnvelope = Field(default_factory=AgentPlanEnvelope)
    pending_task_confirmation: Dict[str, Any] = Field(default_factory=dict)
    execution_profile: EffectiveExecutionProfile = Field(default_factory=EffectiveExecutionProfile)

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        value = dict(value)
        aliases = {
            "turnId": "turn_id",
            "startedAt": "started_at",
            "completedAt": "completed_at",
            "elapsedMs": "elapsed_ms",
            "thinkingTimeline": "thinking_timeline",
            "executionTrace": "execution_trace",
            "pendingTaskConfirmation": "pending_task_confirmation",
        }
        for source, target in aliases.items():
            if target not in value and source in value:
                value[target] = value.get(source)
        return value


AgentMessage.model_rebuild()


class AgentTurnResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: AgentStatus
    stage: AgentStage = "answered"
    output: AgentTurnOutput = Field(default_factory=AgentTurnOutput)
    diagnostics: AgentTurnDiagnostics = Field(default_factory=AgentTurnDiagnostics)
    context_summary: AgentContextSummary = Field(default_factory=AgentContextSummary)
    plan: AgentPlanEnvelope = Field(default_factory=AgentPlanEnvelope)
    messages: List[AgentMessage] = Field(default_factory=list)
    effective_execution_profile: EffectiveExecutionProfile = Field(default_factory=EffectiveExecutionProfile)

    @model_validator(mode="before")
    @classmethod
    def _populate_stage(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        value = dict(value)
        if value.get("stage"):
            return value
        status = str(value.get("status") or "").strip()
        if status == "requires_clarification":
            value["stage"] = "requires_clarification"
        elif status == "requires_risk_confirmation":
            value["stage"] = "requires_risk_confirmation"
        elif status == "failed":
            value["stage"] = "failed"
        else:
            value["stage"] = "answered"
        return value

    @property
    def clarification_question(self) -> str:
        return str(self.output.clarification_question or "")

    @property
    def risk_prompt(self) -> str:
        return str(self.output.risk_prompt or "")

    @property
    def execution_trace(self) -> List[ExecutionTraceItem]:
        return list(self.diagnostics.execution_trace or [])

    @property
    def used_tools(self) -> List[str]:
        return list(self.diagnostics.used_tools or [])

    @property
    def citations(self) -> List[str]:
        return list(self.diagnostics.citations or [])

    @property
    def research_notes(self) -> List[str]:
        return list(self.diagnostics.research_notes or [])


class AgentSessionSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str = ""
    preview: str = ""
    status: PersistedAgentStatus = "idle"
    history_id: str = ""
    is_pinned: bool = False
    title_source: AgentSessionTitleSource = "fallback"
    panel_kind: str = ""
    created_at: str = ""
    updated_at: str = ""
    pinned_at: Optional[str] = None


class AgentSessionSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = ""
    preview: str = ""
    status: PersistedAgentStatus = "idle"
    stage: AgentStage = "gating"
    history_id: str = ""
    panel_kind: str = ""
    is_pinned: Optional[bool] = None
    input: str = ""
    messages: List[AgentMessage] = Field(default_factory=list)
    output: AgentTurnOutput = Field(default_factory=AgentTurnOutput)
    diagnostics: AgentTurnDiagnostics = Field(default_factory=AgentTurnDiagnostics)
    context_summary: AgentContextSummary = Field(default_factory=AgentContextSummary)
    plan: AgentPlanEnvelope = Field(default_factory=AgentPlanEnvelope)
    risk_confirmations: List[str] = Field(default_factory=list)
    conversation_execution_profile: ConversationExecutionProfile = Field(default_factory=ConversationExecutionProfile)


class AgentSessionMetadataPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None
    is_pinned: Optional[bool] = None


class AgentSessionDetail(AgentSessionSummary):
    stage: AgentStage = "gating"
    input: str = ""
    messages: List[AgentMessage] = Field(default_factory=list)
    output: AgentTurnOutput = Field(default_factory=AgentTurnOutput)
    diagnostics: AgentTurnDiagnostics = Field(default_factory=AgentTurnDiagnostics)
    context_summary: AgentContextSummary = Field(default_factory=AgentContextSummary)
    plan: AgentPlanEnvelope = Field(default_factory=AgentPlanEnvelope)
    risk_confirmations: List[str] = Field(default_factory=list)
    conversation_execution_profile: ConversationExecutionProfile = Field(default_factory=ConversationExecutionProfile)
