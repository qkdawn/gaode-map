from modules.ppt_planning.schemas import PptDataSourceSummary, PptSource


def test_ppt_source_ignores_legacy_source_field_aliases():
    source = PptSource.model_validate(
        {
            "id": "external:legacy",
            "title": "旧来源",
            "status": "ready",
            "sourceKind": "web",
            "evidenceCount": 3,
            "locatorSummary": "旧定位摘要",
            "meta": {
                "sourceKind": "document",
                "transport": {"evidenceCount": 2},
                "aiPayload": {
                    "evidenceNodes": [
                        {
                            "id": "external:legacy:node:1",
                            "sourceId": "external:legacy",
                            "sourceType": "web",
                            "content": "旧 camel evidence node 不应计数。",
                        }
                    ],
                    "counts": {"evidence": 4},
                },
            },
        }
    )

    assert source.source_kind == "unknown"
    assert source.evidence_count == 4
    assert source.locator_summary == ""


def test_ppt_data_source_summary_ignores_legacy_source_field_aliases():
    summary = PptDataSourceSummary.model_validate(
        {
            "id": "external:legacy",
            "title": "旧摘要",
            "status": "ready",
            "sourceKind": "database",
            "evidenceCount": 8,
            "locatorSummary": "旧定位摘要",
            "meta": {"sourceKind": "web"},
        }
    )

    assert summary.source_kind == "unknown"
    assert summary.evidence_count == 0
    assert summary.locator_summary == ""
