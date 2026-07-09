from __future__ import annotations

from typing import Callable, List

from modules.documents.pageindex import get_pageindex_document_structure as default_get_pageindex_document_structure
from modules.documents.pageindex import get_pageindex_page_content as default_get_pageindex_page_content
from modules.evidence_index.registry import EvidenceAdapterRegistry
from modules.evidence_index.schemas import EvidenceIndexRecord, EvidenceSearchQuery, EvidenceTrace, SourceIndexManifest
from modules.evidence_retrieval.schemas import EvidenceNode, EvidenceSearchResponse
from modules.evidence_retrieval.schemas import SourceRecord


class EvidenceIndexService:
    def __init__(
        self,
        *,
        get_pageindex_document_structure: Callable[[str], str] = default_get_pageindex_document_structure,
        get_pageindex_page_content: Callable[[str, str], str] = default_get_pageindex_page_content,
    ):
        self._registry = EvidenceAdapterRegistry(
            get_pageindex_document_structure=get_pageindex_document_structure,
            get_pageindex_page_content=get_pageindex_page_content,
        )

    def index_source(self, source: SourceRecord) -> SourceIndexManifest:
        adapters = self._registry.adapters_for([source], [source.source_id])
        if not adapters:
            adapters = self._registry.adapters_for([source], [])
        if not adapters:
            raise ValueError("source_index_adapter_not_found")
        adapter, resolved_source = adapters[0]
        return adapter.manifest(resolved_source)

    async def search(self, query: EvidenceSearchQuery) -> EvidenceSearchResponse:
        adapters = self._registry.adapters_for(query.sources, query.source_ids)
        records: List[EvidenceIndexRecord] = []
        for adapter, source in adapters:
            manifest = adapter.manifest(source)
            records.extend(await adapter.recall(query, manifest))
        records.sort(key=lambda item: item.score, reverse=True)
        top_k = max(1, min(int(query.top_k or 8), 50))
        nodes: List[EvidenceNode] = [record.node for record in records[:top_k]]
        return EvidenceSearchResponse(nodes=nodes)

    def manifests(self, query: EvidenceSearchQuery) -> List[SourceIndexManifest]:
        return [adapter.manifest(source) for adapter, source in self._registry.adapters_for(query.sources, query.source_ids)]

    async def read(self, node_id: str, query: EvidenceSearchQuery) -> EvidenceNode | None:
        target = str(node_id or "").strip()
        if not target:
            return None
        for adapter, source in self._registry.adapters_for(query.sources, query.source_ids):
            manifest = adapter.manifest(source)
            node = await adapter.read(target, manifest)
            if node is not None:
                return node
        return None

    async def explain(self, node_id: str, query: EvidenceSearchQuery) -> EvidenceTrace:
        target = str(node_id or "").strip()
        manifests: List[SourceIndexManifest] = []
        diagnostics: List[str] = []
        if not target:
            return EvidenceTrace(node_id="", diagnostics=["node_id_required"])
        for adapter, source in self._registry.adapters_for(query.sources, query.source_ids):
            manifest = adapter.manifest(source)
            manifests.append(manifest)
            node = await adapter.read(target, manifest)
            if node is not None:
                return EvidenceTrace(
                    node_id=target,
                    matched=True,
                    source_id=node.source_id,
                    source_kind=node.source_type,
                    native_index_kind=manifest.native_index_kind,
                    adapter=adapter.__class__.__name__,
                    diagnostics=list(manifest.diagnostics or []),
                    manifests=manifests,
                )
            diagnostics.append(f"miss:{manifest.source_id}:{manifest.native_index_kind}")
        return EvidenceTrace(node_id=target, matched=False, diagnostics=diagnostics, manifests=manifests)


__all__ = ["EvidenceIndexService"]
