from .agent import router as agent_router
from .charting import router as charting_router
from .documents import router as documents_router
from .evidence_retrieval import router as evidence_retrieval_router
from .export import router as export_router
from .gwr import router as gwr_router
from .h3 import router as h3_router
from .history import router as history_router
from .isochrone import router as isochrone_router
from .jobs import router as jobs_router
from .map import router as map_router
from .nightlight import router as nightlight_router
from .poi import router as poi_router
from .population import router as population_router
from .ppt_planning import router as ppt_planning_router
from .ppt_web_source import router as ppt_web_source_router
from .road import router as road_router
from .spatial_action import router as spatial_action_router
from .shared_grid import router as shared_grid_router
from .spatial_projects import router as spatial_projects_router
from .system import router as system_router
from .timeseries import router as timeseries_router
from .tools import router as tools_router

__all__ = [
    "agent_router",
    "export_router",
    "gwr_router",
    "charting_router",
    "documents_router",
    "evidence_retrieval_router",
    "h3_router",
    "history_router",
    "isochrone_router",
    "jobs_router",
    "map_router",
    "nightlight_router",
    "poi_router",
    "population_router",
    "ppt_planning_router",
    "ppt_web_source_router",
    "road_router",
    "spatial_action_router",
    "shared_grid_router",
    "spatial_projects_router",
    "system_router",
    "timeseries_router",
    "tools_router",
]
