import asyncio
import json

from modules.evidence_index.adapters.document_pageindex import DocumentPageIndexAdapter
from modules.evidence_index.schemas import EvidenceSearchQuery
from modules.evidence_retrieval.schemas import SourceRecord


def test_chinese_concept_matching_finds_resident_node():
    structure = [
        {
            "node_id": "resident-section",
            "line_num": 7,
            "title": "产权与住户安排",
            "summary": "三栋住宅仍有住户正常居住，改造需协商并由居民参与共建共管。",
            "text": "",
        },
        {
            "node_id": "traffic-section",
            "line_num": 9,
            "title": "交通条件",
            "summary": "周边道路与地铁站点情况。",
            "text": "",
        },
    ]
    contents = {
        "7": [{"content": "涉及约102户居民，应保留居住并参与园区维护。"}],
        "9": [{"content": "周边道路与地铁站点情况。"}],
    }
    adapter = DocumentPageIndexAdapter(
        "brief",
        get_structure=lambda document_id: json.dumps(structure, ensure_ascii=False),
        get_content=lambda document_id, line_num: json.dumps(contents[line_num], ensure_ascii=False),
    )
    source = SourceRecord(
        source_id="document:brief",
        title="项目基本情况",
        source_kind="document",
        status="ready",
    )

    records = asyncio.run(
        adapter.recall(
            EvidenceSearchQuery(
                question="住宅居民如何处理",
                source_ids=[source.source_id],
                sources=[source],
            ),
            adapter.manifest(source),
        )
    )

    assert records
    assert records[0].node.metadata["node_id"] == "resident-section"
    assert records[0].score > 0
    assert "102户" in records[0].node.content
