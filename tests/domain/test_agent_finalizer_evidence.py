from modules.agent.finalizer_evidence import build_finalizer_evidence_pack
from modules.agent.schemas import AnalysisSnapshot


def test_finalizer_keeps_document_evidence_separate_without_gis_context():
    dossier = {
        "status": "ready",
        "has_project_anchor": True,
        "has_readable_project_anchor": True,
        "evidence": [
            {
                "id": "document:brief:project-evidence:buildings",
                "source_id": "document:brief",
                "document_role": "project_brief",
                "status": "confirmed",
                "title": "建筑规模",
                "content": "项目共有13栋地上建筑。",
            }
        ],
        "conflicts": [],
        "warnings": [],
    }

    pack = build_finalizer_evidence_pack(
        question="分析这个项目",
        snapshot=AnalysisSnapshot(),
        artifacts={},
        answer_evidence_payload={"project_evidence_dossier": dossier},
    )

    assert pack["status"] == "ready"
    assert pack["reason"] == "project_document_evidence"
    assert pack["document_evidence_nodes"][0]["content"] == "项目共有13栋地上建筑。"
    assert pack["evidence_nodes"] == []


def test_finalizer_surfaces_failed_core_document_instead_of_gis_only_confidence():
    dossier = {
        "status": "failed",
        "has_project_anchor": True,
        "has_readable_project_anchor": False,
        "evidence": [],
        "conflicts": [],
        "warnings": ["核心项目文档未成功读取；不得退化为自信的 GIS-only 项目结论。"],
    }

    pack = build_finalizer_evidence_pack(
        question="给出项目定位",
        snapshot=AnalysisSnapshot(),
        artifacts={},
        answer_evidence_payload={"project_evidence_dossier": dossier},
    )

    assert pack["status"] == "failed"
    assert pack["reason"] == "core_project_document_unreadable"
    assert any("不得退化" in warning for warning in pack["warnings"])


def test_finalizer_blocks_reference_evidence_when_selected_project_brief_is_unreadable():
    dossier = {
        "status": "failed",
        "has_project_anchor": True,
        "has_readable_project_anchor": False,
        "evidence": [
            {
                "id": "document:reference:project-evidence:legacy",
                "source_id": "document:reference",
                "document_role": "reference_document",
                "status": "confirmed",
                "title": "旧版资料",
                "content": "参考资料提供了周边背景。",
            }
        ],
        "conflicts": [],
        "warnings": ["项目摘要解析失败。"],
    }

    pack = build_finalizer_evidence_pack(
        question="给出项目定位",
        snapshot=AnalysisSnapshot(),
        artifacts={},
        answer_evidence_payload={"project_evidence_dossier": dossier},
    )

    assert pack["status"] == "failed"
    assert pack["reason"] == "core_project_document_unreadable"
    assert pack["document_evidence_nodes"][0]["document_role"] == "reference_document"
