from __future__ import annotations

from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field


class ModelNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    model_id: str
    role: str
    purpose: str
    required: bool = True
    outputs: List[str] = Field(default_factory=list)


class ModelEdge(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str
    target: str
    relation: str
    required: bool = False
    use_when: List[str] = Field(default_factory=list)


class ModelGraph(BaseModel):
    model_config = ConfigDict(extra="ignore")

    graph_id: str
    title: str
    entry_nodes: List[str] = Field(default_factory=list)
    target_nodes: List[str] = Field(default_factory=list)
    nodes: Dict[str, ModelNode] = Field(default_factory=dict)
    edges: List[ModelEdge] = Field(default_factory=list)

    def out_edges(self, model_id: str) -> List[ModelEdge]:
        return [edge for edge in self.edges if edge.source == model_id]

    def in_edges(self, model_id: str) -> List[ModelEdge]:
        return [edge for edge in self.edges if edge.target == model_id]


class SkillSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    skill_id: str
    title: str
    purpose: str
    uses_model_graph: str
    entry_nodes: List[str] = Field(default_factory=list)
    target_nodes: List[str] = Field(default_factory=list)
    required_path: List[str] = Field(default_factory=list)
    optional_branches: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    model_tool_map: Dict[str, Dict[str, List[str]]] = Field(default_factory=dict)
    skip_conditions: Dict[str, List[str]] = Field(default_factory=dict)
    guardrails: List[str] = Field(default_factory=list)
    agent_autonomy: Dict[str, bool] = Field(default_factory=dict)
    trigger_tokens: List[str] = Field(default_factory=list)


class BusinessAnalystInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scope: Dict[str, Any] = Field(default_factory=dict)
    evidence_layers: List[str] = Field(default_factory=list)
    question_type: str = ""


class BusinessAnalystSkeleton(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str = "skipped"
    reason: str = ""
    selected_skill: SkillSpec | None = None
    candidate_skills: List[str] = Field(default_factory=list)
    model_graph: Dict[str, Any] = Field(default_factory=dict)
    recommended_path: List[str] = Field(default_factory=list)
    path_relations: List[Dict[str, Any]] = Field(default_factory=list)
    optional_branches: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    model_tool_map: Dict[str, Dict[str, List[str]]] = Field(default_factory=dict)
    skip_conditions: Dict[str, List[str]] = Field(default_factory=dict)
    guardrails: List[str] = Field(default_factory=list)
    missing_evidence_defaults: List[str] = Field(default_factory=list)
    answer_guidance: List[str] = Field(default_factory=list)
