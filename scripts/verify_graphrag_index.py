"""Fail when the GraphRAG output does not cover the prepared PDF corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


REQUIRED_TABLES = (
    "documents",
    "text_units",
    "entities",
    "relationships",
    "communities",
    "community_reports",
)


def verify(workspace: Path) -> dict[str, object]:
    manifest_path = workspace / "source_manifest.json"
    output_dir = workspace / "output"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        Path(str(item["input_file"])).name for item in manifest.get("documents", [])
    }

    frames: dict[str, pd.DataFrame] = {}
    missing_tables: list[str] = []
    for name in REQUIRED_TABLES:
        path = output_dir / f"{name}.parquet"
        if not path.exists():
            missing_tables.append(name)
            continue
        frames[name] = pd.read_parquet(path)

    documents = frames.get("documents", pd.DataFrame())
    actual = set(documents.get("title", pd.Series(dtype=str)).astype(str))
    duplicate_titles = sorted(
        documents.loc[documents.get("title", pd.Series(dtype=str)).duplicated(), "title"]
        .astype(str)
        .unique()
    ) if not documents.empty and "title" in documents else []

    covered_document_ids: set[str] = set()
    text_units = frames.get("text_units", pd.DataFrame())
    if not text_units.empty and "document_id" in text_units:
        covered_document_ids = set(text_units["document_id"].astype(str))
    uncovered_titles = sorted(
        str(row.title)
        for row in documents.itertuples()
        if str(row.id) not in covered_document_ids
    ) if not documents.empty else []

    counts = {name: len(frame) for name, frame in frames.items()}
    errors: list[str] = []
    if missing_tables:
        errors.append(f"missing_tables:{','.join(missing_tables)}")
    if len(expected) != int(manifest.get("source_count", -1)):
        errors.append("manifest_source_count_mismatch")
    missing_documents = sorted(expected - actual)
    unexpected_documents = sorted(actual - expected)
    if missing_documents:
        errors.append(f"missing_documents:{','.join(missing_documents)}")
    if unexpected_documents:
        errors.append(f"unexpected_documents:{','.join(unexpected_documents)}")
    if duplicate_titles:
        errors.append(f"duplicate_documents:{','.join(duplicate_titles)}")
    if uncovered_titles:
        errors.append(f"documents_without_text_units:{','.join(uncovered_titles)}")
    for name in REQUIRED_TABLES[1:]:
        if name in frames and frames[name].empty:
            errors.append(f"empty_table:{name}")

    return {
        "status": "success" if not errors else "error",
        "expected_documents": len(expected),
        "indexed_documents": len(actual),
        "counts": counts,
        "missing_documents": missing_documents,
        "unexpected_documents": unexpected_documents,
        "documents_without_text_units": uncovered_titles,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
