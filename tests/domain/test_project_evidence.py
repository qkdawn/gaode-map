from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modules.documents.project_evidence import EvidenceStatus, build_project_evidence_dossier
from store.ai_models import AiBase, Document, DocumentBlock


def _install_db(monkeypatch, documents, blocks):
    engine = create_engine("sqlite:///:memory:", future=True)
    AiBase.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as session:
        session.add_all(documents)
        session.add_all(blocks)
        session.commit()
    monkeypatch.setattr("modules.documents.project_evidence.SessionLocal", factory)


def _document(document_id, title, role, status="parsed"):
    return Document(
        id=document_id,
        title=title,
        file_name=f"{document_id}.docx",
        file_type="docx",
        file_path=f"/tmp/{document_id}.docx",
        document_role=role,
        upload_time=datetime(2026, 7, 10),
        status=status,
    )


def _node(document_id, node_id, title, text, ordinal, page=1):
    return DocumentBlock(
        document_id=document_id,
        page_index=page - 1,
        block_index=ordinal,
        block_type="paragraph",
        text=text,
        section_title=title,
    )


def test_generic_project_question_reads_category_covered_core_evidence(monkeypatch):
    document = _document("brief", "项目基本情况", "project_brief")
    nodes = [
        _node("brief", "buildings", "建筑现状", "项目共有13栋地上建筑，其中8栋为历史或保护建筑。", 1),
        _node("brief", "residents", "居民情况", "现有3栋住宅建筑，约102户居民，居民留存并参与共建共管。", 2),
        _node("brief", "problems", "现状问题", "建筑存在消防、排水、渗漏和无障碍问题。", 3),
        _node("brief", "space", "空间构想", "空间组织为“一路、一院、一园”，礼堂作为城市记忆锚点。", 4),
    ]
    _install_db(monkeypatch, [document], nodes)

    dossier = build_project_evidence_dossier(
        [{"source_id": "document:brief", "document_role": "project_brief"}],
        question="分析这个项目",
    )

    assert dossier.status == "ready"
    assert {item.category for item in dossier.evidence} >= {
        "building_scale",
        "resident_stakeholders",
        "existing_problems",
        "spatial_vision",
    }
    assert any("13栋" in item.content and "8栋" in item.content for item in dossier.evidence)
    assert any("102户" in item.content for item in dossier.evidence)
    assert any("共建共管" in item.content for item in dossier.evidence)
    assert any("一路、一院、一园" in item.content and "礼堂" in item.content for item in dossier.evidence)


def test_project_brief_wins_reference_conflict_but_keeps_both_sources(monkeypatch):
    documents = [
        _document("brief", "项目摘要", "project_brief"),
        _document("reference", "旧版资料", "reference_document"),
    ]
    nodes = [
        _node("brief", "households", "居民情况", "项目现有102户居民。", 1),
        _node("reference", "households", "居民情况", "旧版资料记载项目现有120户居民。", 1),
    ]
    _install_db(monkeypatch, documents, nodes)

    dossier = build_project_evidence_dossier(
        [{"source_id": "document:brief"}, {"source_id": "document:reference"}],
        question="居民如何处理",
    )

    conflict = next(item for item in dossier.conflicts if item.metric_key == "households")
    assert conflict.preferred_value == "102户"
    assert conflict.unresolved is False
    assert set(conflict.values) == {"102户", "120户"}
    assert len(conflict.evidence_ids) == 2
    assert "项目摘要口径" in conflict.explanation



def test_reference_conflict_survives_core_evidence_budget(monkeypatch):
    documents = [
        _document("brief", "项目摘要", "project_brief"),
        _document("reference", "旧版资料", "reference_document"),
    ]
    nodes = [
        _node("brief", "households", "居民情况", "项目现有102户居民。", 1),
        *[
            _node("brief", f"core-{index}", f"项目问题{index}", f"第{index}项消防排水更新约束。", index + 2)
            for index in range(35)
        ],
        _node("reference", "households", "居民情况", "旧版资料记载项目现有120户居民。", 1),
    ]
    _install_db(monkeypatch, documents, nodes)

    dossier = build_project_evidence_dossier(
        [{"source_id": "document:brief"}, {"source_id": "document:reference"}],
        question="分析这个项目",
        max_evidence=12,
    )

    conflict = next(item for item in dossier.conflicts if item.metric_key == "households")
    assert conflict.preferred_value == "102户"
    assert all(evidence_id in {item.id for item in dossier.evidence} for evidence_id in conflict.evidence_ids)

def test_same_role_conflict_remains_unresolved(monkeypatch):
    documents = [
        _document("brief-a", "摘要A", "project_brief"),
        _document("brief-b", "摘要B", "project_brief"),
    ]
    nodes = [
        _node("brief-a", "households", "居民情况", "项目现有102户居民。", 1),
        _node("brief-b", "households", "居民情况", "项目现有120户居民。", 1),
    ]
    _install_db(monkeypatch, documents, nodes)

    dossier = build_project_evidence_dossier(
        [{"source_id": "document:brief-a"}, {"source_id": "document:brief-b"}],
        question="分析这个项目",
    )

    conflict = next(item for item in dossier.conflicts if item.metric_key == "households")
    assert conflict.unresolved is True
    assert conflict.preferred_value == ""
    assert "不静默选边" in conflict.explanation


def test_pending_area_and_design_vision_keep_evidence_status(monkeypatch):
    documents = [
        _document("brief", "项目摘要", "project_brief"),
        _document("vision", "改造愿景", "design_vision"),
    ]
    nodes = [
        _node("brief", "area", "建筑规模", "项目总建筑面积约20000㎡，具体数据待确认。", 1),
        _node("vision", "space", "空间愿景", "拟形成“一路、一院、一园”，以礼堂作为记忆锚点。", 1),
    ]
    _install_db(monkeypatch, documents, nodes)

    dossier = build_project_evidence_dossier(
        [{"source_id": "document:brief"}, {"source_id": "document:vision"}],
        question="这个项目适合做什么",
    )

    area = next(item for item in dossier.evidence if "20000㎡" in item.content)
    vision = next(item for item in dossier.evidence if item.document_id == "vision")
    assert area.status == EvidenceStatus.PENDING_VERIFICATION
    assert vision.status == EvidenceStatus.DESIGN_INTENT



def test_mixed_exact_and_pending_quantities_get_separate_statuses(monkeypatch):
    document = _document("brief", "项目基本情况", "project_brief")
    nodes = [
        _node(
            "brief",
            "scale",
            "建筑规模与历史属性",
            "项目用地范围内共有地上建筑13栋，总建筑面积约20000㎡（具体数据待确认）；历史保护建筑（8栋，总建筑面积约13071.78㎡）。",
            1,
        )
    ]
    _install_db(monkeypatch, [document], nodes)

    dossier = build_project_evidence_dossier(
        [{"source_id": "document:brief"}],
        question="分析这个项目",
    )

    total_buildings = next(item for item in dossier.evidence if "13栋" in item.content)
    total_area = next(item for item in dossier.evidence if "20000㎡" in item.content)
    protected_buildings = next(item for item in dossier.evidence if "8栋" in item.content)
    protected_area = next(item for item in dossier.evidence if "13071.78㎡" in item.content)
    assert total_buildings.status == EvidenceStatus.CONFIRMED
    assert total_area.status == EvidenceStatus.PENDING_VERIFICATION
    assert protected_buildings.status == EvidenceStatus.CONFIRMED
    assert protected_area.status == EvidenceStatus.PENDING_VERIFICATION

def test_failed_project_brief_blocks_gis_only_confidence(monkeypatch):
    document = _document("brief", "项目摘要", "project_brief", status="failed")
    _install_db(monkeypatch, [document], [])

    dossier = build_project_evidence_dossier(
        [{"source_id": "document:brief"}],
        question="给出项目定位",
    )

    assert dossier.status == "failed"
    assert dossier.has_project_anchor is True
    assert dossier.has_readable_project_anchor is False
    assert dossier.unreadable_document_ids == ["brief"]
    assert any("不得退化" in warning for warning in dossier.warnings)


def test_missing_selected_project_brief_role_is_preserved_as_core_failure(monkeypatch):
    _install_db(monkeypatch, [], [])

    dossier = build_project_evidence_dossier(
        [{"source_id": "document:missing-brief", "document_role": "project_brief"}],
        question="分析这个项目",
    )

    assert dossier.status == "failed"
    assert dossier.has_project_anchor is True
    assert dossier.has_readable_project_anchor is False
    assert dossier.document_roles["missing-brief"].value == "project_brief"
    assert dossier.unreadable_document_ids == ["missing-brief"]
    assert any("核心文档未找到" in warning for warning in dossier.warnings)


def test_failed_project_brief_is_not_masked_by_readable_reference(monkeypatch):
    documents = [
        _document("brief", "项目摘要", "project_brief", status="failed"),
        _document("reference", "参考资料", "reference_document"),
    ]
    nodes = [_node("reference", "context", "周边背景", "参考资料记录了周边商业背景。", 1)]
    _install_db(monkeypatch, documents, nodes)

    dossier = build_project_evidence_dossier(
        [{"source_id": "document:brief"}, {"source_id": "document:reference"}],
        question="给出项目定位",
    )

    assert dossier.status == "failed"
    assert dossier.has_project_anchor is True
    assert dossier.has_readable_project_anchor is False
    assert any(item.document_role.value == "reference_document" for item in dossier.evidence)
    assert any("不得退化为参考资料" in warning for warning in dossier.warnings)
