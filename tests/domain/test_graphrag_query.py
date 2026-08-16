from __future__ import annotations

import pandas as pd

from scripts.graphrag_query import _source_contexts


def test_global_report_context_maps_community_id_to_original_text_unit():
    contexts = _source_contexts(
        {"reports": pd.DataFrame([{"id": "7", "title": "Community report", "content": "Summary"}])},
        pd.DataFrame([
            {
                "id": "unit-1",
                "human_readable_id": 42,
                "document_id": "doc-1",
                "text": "Original evidence text.",
            }
        ]),
        pd.DataFrame([{"id": "doc-1", "title": "source.pdf", "text": "Original evidence text."}]),
        pd.DataFrame([{"community": 7, "text_unit_ids": ["unit-1"]}]),
    )

    assert contexts == [
        {
            "citation_id": "graphrag:text_unit:42",
            "title": "source.pdf",
            "source_type": "public_knowledge_graphrag",
            "source_url": "",
            "source_locator": "text_unit:42",
            "page_start": 1,
            "page_end": 1,
            "section": "",
            "content": "Original evidence text.",
        }
    ]
