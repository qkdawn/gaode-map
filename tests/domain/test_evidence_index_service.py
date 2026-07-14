from __future__ import annotations

import asyncio

from modules.evidence_index import EvidenceIndexService, EvidenceSearchQuery, manifest_from_source
from modules.evidence_index import attach_index_manifest, build_source_index_manifest_payload
from modules.evidence_retrieval.schemas import SourceRecord as _SourceRecord


_KIND_BY_SOURCE = {
    "system": "dataset_record",
    "document": "document_excerpt",
    "image": "image_observation",
    "web": "web_excerpt",
    "database": "database_record",
    "package": "package_item",
}


def _canonicalize(value):
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    if not isinstance(value, dict):
        return value
    payload = {key: _canonicalize(item) for key, item in value.items()}
    nodes = payload.get("evidence_nodes")
    if isinstance(nodes, list):
        canonical = []
        for raw in nodes:
            node = dict(raw)
            if "kind" not in node:
                source_id = str(node.pop("source_id", "") or "")
                source_type = str(node.pop("source_type", "system") or "system")
                node.update({
                    "kind": _KIND_BY_SOURCE.get(source_type, "dataset_record"),
                    "run_id": "",
                    "source_ids": [source_id],
                    "metric_ids": [],
                    "data": node.pop("metadata", {}),
                    "time_scope": {},
                    "spatial_scope": {},
                    "method": node.pop("evidence_level", ""),
                    "quality_flags": [],
                })
                node.pop("score", None)
                node.pop("warnings", None)
            canonical.append(node)
        payload["evidence_nodes"] = canonical
    return payload


def _source_record(value):
    return _SourceRecord.model_validate(_canonicalize(value))


def _nodes(response):
    return [hit.node for hit in response.hits]


def test_evidence_index_service_unifies_payload_and_pageindex_adapters():
    service = EvidenceIndexService(
        get_pageindex_document_structure=lambda _document_id: (
            '[{"title":"公共服务","node_id":"n1","line_num":3,"summary":"补齐公共服务。"}]'
        ),
        get_pageindex_page_content=lambda _document_id, _pages: (
            '[{"page":3,"content":"补齐公共服务设施，改善片区服务短板。"}]'
        ),
    )
    response = asyncio.run(
        service.search(
            EvidenceSearchQuery(
                question="公共服务",
                top_k=10,
                source_ids=["document:doc-1", "web:area-1"],
                sources=[
                    _source_record(
                        {
                            "id": "web:area-1",
                            "title": "网页来源",
                            "status": "ready",
                            "meta": {
                                "sourceKind": "web",
                                "aiPayload": {
                                    "evidence_nodes": [
                                        {
                                            "id": "web:area-1:node:1",
                                            "source_id": "web:area-1",
                                            "source_type": "web",
                                            "title": "政策网页",
                                            "content": "公共服务和城市更新政策资料。",
                                        }
                                    ]
                                },
                            },
                        }
                    )
                ],
            )
        )
    )

    node_ids = {node.id for node in _nodes(response)}
    assert "document:doc-1:pageindex:n1" in node_ids
    assert "web:area-1:node:1" in node_ids
    assert {node.kind for node in _nodes(response)} == {"document_excerpt", "web_excerpt"}


def test_evidence_index_service_reads_payload_and_pageindex_nodes():
    service = EvidenceIndexService(
        get_pageindex_document_structure=lambda _document_id: (
            '[{"title":"公共服务","node_id":"n1","line_num":3,"summary":"补齐公共服务。"}]'
        ),
        get_pageindex_page_content=lambda _document_id, _pages: (
            '[{"page":3,"content":"补齐公共服务设施，改善片区服务短板。"}]'
        ),
    )
    query = EvidenceSearchQuery(
        question="公共服务",
        source_ids=["document:doc-1", "web:area-1"],
        sources=[
            _source_record(
                {
                    "id": "web:area-1",
                    "title": "网页来源",
                    "status": "ready",
                    "meta": {
                        "sourceKind": "web",
                        "aiPayload": {
                            "evidence_nodes": [
                                {
                                    "id": "web:area-1:node:1",
                                    "source_id": "web:area-1",
                                    "source_type": "web",
                                    "title": "政策网页",
                                    "content": "公共服务和城市更新政策资料。",
                                }
                            ]
                        },
                    },
                }
            )
        ],
    )

    page_node = asyncio.run(service.read("document:doc-1:pageindex:n1", query))
    web_node = asyncio.run(service.read("web:area-1:node:1", query))
    manifests = service.manifests(query)

    assert page_node is not None
    assert page_node.kind == "document_excerpt"
    assert web_node is not None
    assert web_node.kind == "web_excerpt"
    assert {manifest.native_index_kind for manifest in manifests} == {"pageindex", "payload_index"}


def test_evidence_index_service_ignores_legacy_evidence_nodes_alias():
    source = _source_record(
        {
            "id": "web:area-legacy",
            "title": "旧网页来源",
            "source_kind": "web",
            "status": "ready",
            "meta": {
                "aiPayload": {
                    "evidenceNodes": [
                        {
                            "id": "web:area-legacy:node:1",
                            "sourceId": "web:area-legacy",
                            "sourceType": "web",
                            "title": "旧节点",
                            "content": "旧 camel EvidenceNode 不应再进入索引。",
                        }
                    ]
                }
            },
        }
    )
    service = EvidenceIndexService()
    query = EvidenceSearchQuery(question="旧节点", source_ids=["web:area-legacy"], sources=[source])

    response = asyncio.run(service.search(query))
    node = asyncio.run(service.read("web:area-legacy:node:1", query))

    assert _nodes(response) == []
    assert node is None


def test_evidence_search_query_ignores_legacy_source_ids_alias():
    query = EvidenceSearchQuery(question="公共服务", sourceIds=["web:legacy"])

    assert query.source_ids == []


def test_index_manifest_payload_uses_canonical_key_only():
    payload = attach_index_manifest(
        {"evidence_nodes": []},
        build_source_index_manifest_payload(
            source_id="web:area-1",
            source_kind="web",
            native_index_kind="webpage_index",
            node_count=1,
        ),
    )

    assert "index_manifest" in payload
    assert "indexManifest" not in payload


def test_manifest_from_source_ignores_legacy_manifest_fields():
    legacy_key_source = _source_record(
        {
            "id": "web:area-legacy",
            "source_kind": "web",
            "meta": {
                "aiPayload": {
                    "indexManifest": build_source_index_manifest_payload(
                        source_id="web:area-legacy",
                        source_kind="web",
                        native_index_kind="webpage_index",
                        node_count=1,
                    )
                }
            },
        }
    )
    legacy_kind_source = _source_record(
        {
            "id": "external:area-kind",
            "meta": {
                "aiPayload": {
                    "index_manifest": {
                        "source_id": "external:area-kind",
                        "sourceKind": "web",
                        "native_index_kind": "webpage_index",
                        "node_count": 1,
                    }
                }
            },
        }
    )

    legacy_kind_manifest = manifest_from_source(legacy_kind_source)

    assert manifest_from_source(legacy_key_source) is None
    assert legacy_kind_manifest is not None
    assert legacy_kind_manifest.source_kind == "unknown"


def test_evidence_index_service_uses_declared_source_manifest():
    service = EvidenceIndexService(
        get_pageindex_document_structure=lambda _document_id: (
            '[{"title":"公共服务","node_id":"n1","line_num":3,"summary":"补齐公共服务。"}]'
        ),
        get_pageindex_page_content=lambda _document_id, _pages: (
            '[{"page":3,"content":"补齐公共服务设施。"}]'
        ),
    )
    image_payload = attach_index_manifest(
        {
            "evidence_nodes": [
                {
                    "id": "image:att-1:node:1",
                    "source_id": "image:att-1",
                    "source_type": "image",
                    "title": "图片 OCR",
                    "content": "公共服务导视牌。",
                }
            ]
        },
        build_source_index_manifest_payload(
            source_id="image:att-1",
            source_kind="image",
            native_index_kind="image_visual_index",
            node_count=1,
            model_versions={"image_text_embedding": "openclip_target"},
        ),
    )
    document_payload = attach_index_manifest(
        {"evidence_nodes": []},
        build_source_index_manifest_payload(
            source_id="document:doc-1",
            source_kind="document",
            native_index_kind="pageindex",
            node_count=1,
            retrieval_modes=["structure", "keyword"],
        ),
    )
    query = EvidenceSearchQuery(
        question="公共服务",
        source_ids=["image:att-1", "document:doc-1"],
        sources=[
            _source_record({"id": "image:att-1", "source_kind": "image", "status": "ready", "meta": {"aiPayload": image_payload}}),
            _source_record({"id": "document:doc-1", "source_kind": "document", "status": "ready", "meta": {"aiPayload": document_payload}}),
        ],
    )

    manifests = service.manifests(query)
    native_kinds = [manifest.native_index_kind for manifest in manifests]

    assert native_kinds.count("pageindex") == 1
    assert "payload_index" not in native_kinds
    assert "image_visual_index" in native_kinds
    image_manifest = next(item for item in manifests if item.source_kind == "image")
    assert image_manifest.model_versions["image_text_embedding"] == "openclip_target"


def test_evidence_index_service_routes_image_visual_index_manifest():
    image_payload = attach_index_manifest(
        {
            "evidence_nodes": [
                {
                    "id": "image:att-1:node:ocr-1",
                    "source_id": "image:att-1",
                    "source_type": "image",
                    "title": "现场照片 OCR",
                    "content": "OCR 识别到图中标注：主入口、沿街商业、停车场。",
                    "metadata": {"attachment_id": "att-1", "filename": "site-photo.png", "bbox_id": "ocr-1"},
                    "locator": "image:bbox:ocr-1",
                    "evidence_level": "ocr_text",
                }
            ]
        },
        build_source_index_manifest_payload(
            source_id="image:att-1",
            source_kind="image",
            native_index_kind="image_visual_index",
            node_count=1,
            retrieval_modes=["keyword", "vector"],
            read_modes=["node_id", "attachment_id", "locator", "bbox"],
        ),
    )
    source = _source_record({"id": "image:att-1", "source_kind": "image", "status": "ready", "meta": {"aiPayload": image_payload}})
    service = EvidenceIndexService()
    query = EvidenceSearchQuery(question="沿街商业", source_ids=["image:att-1"], sources=[source])

    response = asyncio.run(service.search(query))
    by_bbox = asyncio.run(service.read("ocr-1", query))
    by_locator = asyncio.run(service.read("image:bbox:ocr-1", query))
    manifests = service.manifests(query)

    assert _nodes(response)[0].id == "image:att-1:node:ocr-1"
    assert by_bbox is not None
    assert by_bbox.id == "image:att-1:node:ocr-1"
    assert by_locator is not None
    assert by_locator.id == "image:att-1:node:ocr-1"
    assert manifests[0].native_index_kind == "image_visual_index"


def test_evidence_index_service_routes_webpage_index_manifest():
    web_payload = attach_index_manifest(
        {
            "evidence_nodes": [
                {
                    "id": "web:area-1:web:node-1",
                    "source_id": "web:area-1",
                    "source_type": "web",
                    "title": "政策网页",
                    "content": "公共服务和城市更新政策资料。",
                    "metadata": {"url": "https://example.com/policy", "source_domain": "example.com"},
                    "locator": "https://example.com/policy",
                }
            ]
        },
        build_source_index_manifest_payload(
            source_id="web:area-1",
            source_kind="web",
            native_index_kind="webpage_index",
            node_count=1,
            read_modes=["node_id", "url"],
            storage_ref={"urls": ["https://example.com/policy"]},
        ),
    )
    source = _source_record({"id": "web:area-1", "source_kind": "web", "status": "ready", "meta": {"aiPayload": web_payload}})
    service = EvidenceIndexService()
    query = EvidenceSearchQuery(question="公共服务", source_ids=["web:area-1"], sources=[source])

    response = asyncio.run(service.search(query))
    by_node_id = asyncio.run(service.read("web:area-1:web:node-1", query))
    by_url = asyncio.run(service.read("https://example.com/policy", query))
    manifests = service.manifests(query)

    assert _nodes(response)[0].id == "web:area-1:web:node-1"
    assert by_node_id is not None
    assert by_url is not None
    assert by_url.id == "web:area-1:web:node-1"
    assert manifests[0].native_index_kind == "webpage_index"


def test_evidence_index_service_routes_database_record_index_manifest():
    database_payload = attach_index_manifest(
        {
            "evidence_nodes": [
                {
                    "id": "database:history-1:history:summary",
                    "source_id": "database:history-1:package",
                    "source_type": "database",
                    "title": "当前分析区域详情",
                    "content": "区域分析包含 POI 总量和公共服务配置。",
                    "metadata": {"history_id": "history-1", "record_id": "history-1"},
                    "locator": "analysis_history:history-1",
                    "evidence_level": "history_summary",
                }
            ]
        },
        build_source_index_manifest_payload(
            source_id="database:history-1:package",
            source_kind="database",
            native_index_kind="database_record_index",
            node_count=1,
            retrieval_modes=["keyword", "structured"],
            read_modes=["node_id", "record_id", "locator"],
        ),
    )
    source = _source_record(
        {
            "id": "database:history-1:package",
            "source_kind": "database",
            "status": "ready",
            "meta": {"aiPayload": database_payload},
        }
    )
    service = EvidenceIndexService()
    query = EvidenceSearchQuery(question="公共服务", source_ids=["database:history-1:package"], sources=[source])

    response = asyncio.run(service.search(query))
    by_record = asyncio.run(service.read("history-1", query))
    by_locator = asyncio.run(service.read("analysis_history:history-1", query))
    manifests = service.manifests(query)

    assert _nodes(response)[0].kind == "database_record"
    assert by_record is not None
    assert by_record.id == "database:history-1:history:summary"
    assert by_locator is not None
    assert by_locator.id == "database:history-1:history:summary"
    assert manifests[0].native_index_kind == "database_record_index"


def test_evidence_index_service_routes_spatial_package_index_manifest():
    package_payload = attach_index_manifest(
        {
            "evidence_nodes": [
                {
                    "id": "package:poi-road-carriers:test:package:carrier:corridor_01",
                    "source_id": "package:poi-road-carriers:test",
                    "source_type": "package",
                    "title": "corridor_01",
                    "content": "廊道串联 POI、人口与夜光热点。",
                    "metadata": {"carrier_id": "corridor_01", "carrier_type": "corridor"},
                    "locator": "package:carrier:corridor_01",
                    "evidence_level": "package_carrier",
                },
                {
                    "id": "package:poi-road-carriers:test:package:item:poi-1",
                    "source_id": "package:poi-road-carriers:test",
                    "source_type": "package",
                    "title": "文化馆",
                    "content": "公共服务设施样本，位于廊道沿线。",
                    "metadata": {"id": "poi-1", "category": "科教文化", "carrier_id": "corridor_01"},
                    "locator": "package:item:poi-1",
                    "evidence_level": "package_poi_sample",
                },
            ]
        },
        build_source_index_manifest_payload(
            source_id="package:poi-road-carriers:test",
            source_kind="package",
            native_index_kind="spatial_package_index",
            node_count=2,
            retrieval_modes=["keyword", "structured"],
            read_modes=["node_id", "carrier_id", "item_id", "locator"],
        ),
    )
    source = _source_record(
        {
            "id": "package:poi-road-carriers:test",
            "source_kind": "package",
            "status": "ready",
            "meta": {"aiPayload": package_payload},
        }
    )
    service = EvidenceIndexService()
    query = EvidenceSearchQuery(question="廊道", source_ids=["package:poi-road-carriers:test"], sources=[source])

    response = asyncio.run(service.search(query))
    by_carrier = asyncio.run(service.read("corridor_01", query))
    by_item = asyncio.run(service.read("poi-1", query))
    by_locator = asyncio.run(service.read("package:item:poi-1", query))
    manifests = service.manifests(query)

    assert _nodes(response)[0].kind in {"package_summary", "package_item", "spatial_carrier"}
    assert by_carrier is not None
    assert by_carrier.id == "package:poi-road-carriers:test:package:carrier:corridor_01"
    assert by_item is not None
    assert by_item.id == "package:poi-road-carriers:test:package:item:poi-1"
    assert by_locator is not None
    assert by_locator.id == "package:poi-road-carriers:test:package:item:poi-1"
    assert manifests[0].native_index_kind == "spatial_package_index"


def test_evidence_index_service_uses_manifest_routing_without_explicit_source_ids():
    web_payload = attach_index_manifest(
        {
            "evidence_nodes": [
                {
                    "id": "web:area-1:web:node-1",
                    "source_id": "web:area-1",
                    "source_type": "web",
                    "title": "政策网页",
                    "content": "公共服务和城市更新政策资料。",
                    "metadata": {"url": "https://example.com/policy"},
                }
            ]
        },
        build_source_index_manifest_payload(
            source_id="web:area-1",
            source_kind="web",
            native_index_kind="webpage_index",
            node_count=1,
            read_modes=["node_id", "url"],
        ),
    )
    source = _source_record({"id": "web:area-1", "source_kind": "web", "status": "ready", "meta": {"aiPayload": web_payload}})
    service = EvidenceIndexService()
    query = EvidenceSearchQuery(question="公共服务", sources=[source])

    response = asyncio.run(service.search(query))
    by_url = asyncio.run(service.read("https://example.com/policy", query))
    manifests = service.manifests(query)

    assert _nodes(response)[0].id == "web:area-1:web:node-1"
    assert by_url is not None
    assert manifests[0].native_index_kind == "webpage_index"


def test_evidence_index_service_indexes_source_and_explains_read_path():
    web_payload = attach_index_manifest(
        {
            "evidence_nodes": [
                {
                    "id": "web:area-1:web:node-1",
                    "source_id": "web:area-1",
                    "source_type": "web",
                    "title": "政策网页",
                    "content": "公共服务和城市更新政策资料。",
                    "metadata": {"url": "https://example.com/policy"},
                }
            ]
        },
        build_source_index_manifest_payload(
            source_id="web:area-1",
            source_kind="web",
            native_index_kind="webpage_index",
            node_count=1,
            read_modes=["node_id", "url"],
        ),
    )
    source = _source_record({"id": "web:area-1", "source_kind": "web", "status": "ready", "meta": {"aiPayload": web_payload}})
    service = EvidenceIndexService()
    query = EvidenceSearchQuery(question="公共服务", source_ids=["web:area-1"], sources=[source])

    manifest = service.index_source(source)
    trace = asyncio.run(service.explain("https://example.com/policy", query))

    assert manifest.native_index_kind == "webpage_index"
    assert trace.matched is True
    assert trace.source_id == "web:area-1"
    assert trace.native_index_kind == "webpage_index"
    assert trace.adapter == "WebPageIndexAdapter"
