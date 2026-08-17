"""Evaluate Chinese-query retrieval against the English PDF corpus."""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Any

import lancedb
import pandas as pd


CASES = (
    ("历史城市景观方法如何统筹遗产保护和城市发展？", "UNESCO-HUL-2011.pdf"),
    ("历史城镇和历史城区保护应遵循哪些原则？", "ICOMOS-Washington-Charter-1987.pdf"),
    ("瓦莱塔原则如何处理历史城市中的当代干预？", "ICOMOS-Valletta-Principles-2011.pdf"),
    ("文化遗产地的阐释和展示应遵循什么原则？", "ICOMOS-Interpretation-Presentation-2008.pdf"),
    ("奈良真实性文件如何定义文化遗产的真实性？", "ICOMOS-Nara-Document-1994.pdf"),
    ("威尼斯宪章对古迹保护和修复提出了什么要求？", "ICOMOS-Venice-Charter-1964.pdf"),
    ("后工业用地转型如何改善城市活力不足？", "PMC11052914.pdf"),
    ("如何使用GIS多准则决策分析评价世界遗产城市的生态旅游适宜性？", "PMC11140709.pdf"),
    ("如何利用遥感和GIS管理济南文化遗产面临的自然灾害风险？", "PMC11471172.pdf"),
    ("历史城市景观视角下城墙原址如何演变？", "PMC11964278.pdf"),
    ("恩宁路历史街区的适应性如何评价？", "PMC12048587.pdf"),
    ("湖北不可移动文化遗产呈现怎样的时空分布？", "PMC12238651.pdf"),
    ("勾蓝瑶寨如何开展可持续规划？", "PMC12354706.pdf"),
    ("莱夫科沙的空间中心性、庭院多样性和旅游吸引物有什么关系？", "PMC12373240.pdf"),
    ("不同文化背景下城市公共空间的行人社会行为有何差异？", "PMC12381005.pdf"),
    ("城市治理如何把剩余街道空间转化为社会空间？", "PMC12402484.pdf"),
    ("如何用GIS为历史城市萨里制定可持续旅游步行性规划？", "PMC12891539.pdf"),
    ("如何结合社交媒体和街景图像研究街景视觉与情绪反应？", "PMC12927252.pdf"),
)


def _embed(api_base: str, model: str, dimensions: int, texts: list[str]) -> list[list[float]]:
    payload = json.dumps(
        {"model": model, "input": texts, "dimensions": dimensions, "encoding_format": "float"},
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{api_base.rstrip('/')}/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - configured local service
        result = json.load(response)
    ordered = sorted(result.get("data", []), key=lambda item: int(item["index"]))
    vectors = [item["embedding"] for item in ordered]
    if len(vectors) != len(texts) or any(len(vector) != dimensions for vector in vectors):
        raise RuntimeError("embedding_response_mismatch")
    return vectors


def evaluate(
    workspace: Path,
    api_base: str,
    model: str,
    dimensions: int,
    top_k: int,
) -> dict[str, Any]:
    output_dir = workspace / "output"
    documents = pd.read_parquet(output_dir / "documents.parquet")
    text_units = pd.read_parquet(output_dir / "text_units.parquet")
    title_by_document = dict(zip(documents["id"].astype(str), documents["title"].astype(str)))
    document_by_unit = dict(zip(text_units["id"].astype(str), text_units["document_id"].astype(str)))

    database = lancedb.connect(output_dir / "lancedb")
    table = database.open_table("text_unit_text")
    vectors = _embed(api_base, model, dimensions, [question for question, _ in CASES])
    results: list[dict[str, Any]] = []
    reciprocal_ranks: list[float] = []

    for (question, expected_title), vector in zip(CASES, vectors, strict=True):
        rows = table.search(vector).limit(top_k * 10).to_pandas()
        ranked_titles: list[str] = []
        for unit_id in rows["id"].astype(str):
            title = title_by_document.get(document_by_unit.get(unit_id, ""), "")
            if title and title not in ranked_titles:
                ranked_titles.append(title)
            if len(ranked_titles) >= top_k:
                break
        rank = ranked_titles.index(expected_title) + 1 if expected_title in ranked_titles else None
        reciprocal_ranks.append(1.0 / rank if rank else 0.0)
        results.append(
            {
                "question": question,
                "expected": expected_title,
                "rank": rank,
                "retrieved": ranked_titles[:top_k],
            }
        )

    total = len(results)
    metrics = {
        f"recall_at_{cutoff}": sum(
            1 for result in results if result["rank"] is not None and result["rank"] <= cutoff
        ) / total
        for cutoff in (1, 3, 5)
        if cutoff <= top_k
    }
    metrics["mrr"] = sum(reciprocal_ranks) / total
    return {
        "status": "success",
        "model": model,
        "dimensions": dimensions,
        "case_count": total,
        "top_k": top_k,
        "metrics": metrics,
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--api-base", default="http://127.0.0.1:11435/v1")
    parser.add_argument("--model", default="jinaai/jina-embeddings-v2-base-zh")
    parser.add_argument("--dimensions", type=int, default=768)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.workspace, args.api_base, args.model, args.dimensions, args.top_k)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
