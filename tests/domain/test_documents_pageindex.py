from __future__ import annotations

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from modules.documents.pageindex import list_document_index_nodes, rebuild_document_index
from store.ai_models import AiBase, Document, DocumentBlock


def _session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, future=True)
    AiBase.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    monkeypatch.setattr("modules.documents.pageindex.SessionLocal", factory)
    return factory


def _seed_document(factory):
    session = factory()
    try:
        session.add(
            Document(
                id="doc-1",
                title="长沙县城市更新项目",
                file_name="project.docx",
                file_type="docx",
                file_path="/tmp/project.docx",
                upload_time=datetime(2026, 6, 13, 12, 0, 0),
                status="parsed",
            )
        )
        rows = [
            (0, 0, "title", "基于长沙县人民政府原址城市更新项目"),
            (0, 1, "paragraph", "初步交流"),
            (0, 2, "paragraph", "一、城区更新与功能定位层面："),
            (0, 3, "paragraph", "区域功能再定义问题："),
            (0, 4, "paragraph", "基于对开福区乃至长沙市整体规划，项目需要明确社区、综合体、街区之间的关系。"),
            (0, 5, "paragraph", "公共服务补位具体化问题："),
            (0, 6, "paragraph", "项目应补齐公共服务设施，支撑周边居民与游客复合需求。"),
            (0, 7, "paragraph", "二、产业定位与运营层面"),
            (0, 8, "paragraph", "1、主导产业锚定问题："),
            (0, 9, "paragraph", "结合文物建筑与街区消费场景，引入文创设计与数字媒体。"),
        ]
        for page, index, block_type, text in rows:
            session.add(DocumentBlock(document_id="doc-1", page_index=page, block_index=index, block_type=block_type, text=text))
        session.commit()
    finally:
        session.close()


def test_rebuild_document_index_builds_pageindex_style_outline(monkeypatch):
    factory = _session_factory(monkeypatch)
    _seed_document(factory)

    nodes = rebuild_document_index("doc-1")

    titles = [node.title for node in nodes]
    assert titles[:5] == [
        "长沙县城市更新项目",
        "长沙县城市更新项目",
        "基于长沙县人民政府原址城市更新项目",
        "一、城区更新与功能定位层面：",
        "区域功能再定义问题：",
    ]
    by_title = {node.title: node for node in nodes}
    assert by_title["区域功能再定义问题："].parent_node_id == by_title["一、城区更新与功能定位层面："].node_id
    assert by_title["1、主导产业锚定问题："].parent_node_id == by_title["二、产业定位与运营层面"].node_id
    assert by_title["区域功能再定义问题："].summary.startswith("基于对开福区")


def test_list_document_index_nodes_backfills_parsed_document(monkeypatch):
    factory = _session_factory(monkeypatch)
    _seed_document(factory)

    nodes = list_document_index_nodes("doc-1")
    second_read = list_document_index_nodes("doc-1")

    assert len(nodes) == len(second_read)
    assert any(node.title == "公共服务补位具体化问题：" for node in nodes)
