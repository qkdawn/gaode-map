from fastapi import APIRouter

from modules.ppt_planning.schemas import (
    DeckBriefRequest,
    DeckBriefResponse,
    PptSpecRequest,
    PptSpecResponse,
)
from modules.ppt_planning.service import generate_deck_brief, generate_ppt_spec

router = APIRouter()


@router.post("/api/v1/analysis/ppt/spec", response_model=PptSpecResponse)
def create_ppt_spec(payload: PptSpecRequest) -> PptSpecResponse:
    return generate_ppt_spec(payload)


@router.post("/api/v1/analysis/ppt/deck-brief", response_model=DeckBriefResponse)
def create_deck_brief(payload: DeckBriefRequest) -> DeckBriefResponse:
    return generate_deck_brief(payload)
