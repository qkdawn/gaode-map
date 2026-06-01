from modules.ppt_planning.schemas import PptSpecRequest
from modules.ppt_planning.service import generate_deck_brief, generate_ppt_spec
from modules.ppt_planning.schemas import DeckBriefRequest


def test_generate_ppt_spec_returns_editable_structure():
    response = generate_ppt_spec(
        PptSpecRequest(
            area_id="area-1",
            source_ids=["summary", "scope"],
            topic="长沙县政府原址城市更新",
            audience="政府评审",
            page_count=15,
            research_enabled=True,
        )
    )

    assert response.page_count == 15
    assert response.audience == "政府评审"
    assert "PPT Spec" in response.title
    assert response.outline
    assert response.missing_inputs == []


def test_generate_ppt_spec_marks_missing_inputs_without_pretending_ready():
    response = generate_ppt_spec(PptSpecRequest())

    assert response.title.startswith("待输入主题")
    assert "topic" in response.missing_inputs
    assert "source_ids" in response.missing_inputs


def test_generate_deck_brief_returns_page_brief_not_pptx():
    spec = generate_ppt_spec(PptSpecRequest(topic="更新策划", source_ids=["summary"], page_count=15))
    response = generate_deck_brief(DeckBriefRequest(spec=spec, source_ids=["summary"], topic="更新策划"))

    assert response.status == "draft"
    assert response.slides
    assert response.slides[0].title == "封面"
    assert "不直接生成 PPTX" in response.slides[0].speaker_notes
