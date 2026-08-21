from .schemas import (
    LocalPatternAnalysisRequest,
    LocalizedPatternCell,
    LocalizedPatternInputCell,
    LocalizedPatternResult,
    LocalizedPatternZone,
)
from .service import SpatialActionService

__all__ = [
    "LocalPatternAnalysisRequest",
    "LocalizedPatternCell",
    "LocalizedPatternInputCell",
    "LocalizedPatternResult",
    "LocalizedPatternZone",
    "SpatialActionService",
    "SpatialToolAgentError",
    "analyze_spatial_question",
    "ProjectSpatialAnalysis",
    "ProjectSpatialAnalysisService",
]

from .project_context import ProjectSpatialAnalysis, ProjectSpatialAnalysisService


def __getattr__(name: str):
    if name in {"SpatialToolAgentError", "analyze_spatial_question"}:
        from . import spatial_tool_agent

        return getattr(spatial_tool_agent, name)
    raise AttributeError(name)
