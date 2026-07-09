from __future__ import annotations

from typing import Callable, Iterable, List, Tuple

from modules.evidence_index.adapters.base import EvidenceSourceAdapter
from modules.evidence_index.adapters.database_record import DatabaseEvidenceAdapter
from modules.evidence_index.adapters.document_pageindex import DocumentPageIndexAdapter
from modules.evidence_index.adapters.image_visual import ImageVisualIndexAdapter
from modules.evidence_index.adapters.package import PackageEvidenceAdapter
from modules.evidence_index.adapters.payload import PayloadEvidenceAdapter
from modules.evidence_index.adapters.web_page import WebPageIndexAdapter
from modules.evidence_index.manifests import manifest_from_source
from modules.evidence_retrieval.schemas import SourceRecord


PageIndexStructureReader = Callable[[str], str]
PageIndexContentReader = Callable[[str, str], str]


class EvidenceAdapterRegistry:
    def __init__(
        self,
        *,
        get_pageindex_document_structure: PageIndexStructureReader,
        get_pageindex_page_content: PageIndexContentReader,
    ):
        self._get_pageindex_document_structure = get_pageindex_document_structure
        self._get_pageindex_page_content = get_pageindex_page_content

    def adapters_for(self, sources: Iterable[SourceRecord], source_ids: List[str]) -> List[Tuple[EvidenceSourceAdapter, SourceRecord]]:
        allowed = {str(item or "").strip() for item in (source_ids or []) if str(item or "").strip()}
        adapters: List[Tuple[EvidenceSourceAdapter, SourceRecord]] = []
        source_by_id = {str(source.source_id or "").strip(): source for source in sources or [] if str(source.source_id or "").strip()}
        target_ids = list(allowed) if allowed else list(source_by_id.keys())
        for source_id in target_ids:
            source = source_by_id.get(source_id)
            if source is not None:
                adapter = self._adapter_for_source(source)
                if adapter is not None:
                    adapters.append((adapter, source))
            if source_id.startswith("document:"):
                document_source = source or SourceRecord.model_validate({"id": source_id, "source_kind": "document", "status": "ready"})
                adapters.append(
                    (
                        DocumentPageIndexAdapter(
                            source_id.split(":", 1)[1].strip(),
                            get_structure=self._get_pageindex_document_structure,
                            get_content=self._get_pageindex_page_content,
                        ),
                        document_source,
                    )
                )
        return adapters

    def _adapter_for_source(self, source: SourceRecord) -> EvidenceSourceAdapter | None:
        declared = manifest_from_source(source)
        if declared is not None and declared.native_index_kind == "webpage_index":
            return WebPageIndexAdapter(source)
        if declared is not None and declared.native_index_kind == "database_record_index":
            return DatabaseEvidenceAdapter(source)
        if declared is not None and declared.native_index_kind == "image_visual_index":
            return ImageVisualIndexAdapter(source)
        if declared is not None and declared.native_index_kind == "spatial_package_index":
            return PackageEvidenceAdapter(source)
        if declared is not None and declared.native_index_kind == "pageindex":
            return None
        return PayloadEvidenceAdapter(source)
