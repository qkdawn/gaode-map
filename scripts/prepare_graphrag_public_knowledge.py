"""Prepare the public literature corpus for Microsoft GraphRAG.

The source PDFs remain the evidence authority. This adapter copies the PDFs
unchanged into GraphRAG's input directory and records a manifest so generated
claims can be checked against the original file and the PostgreSQL evidence
index. GraphRAG's MarkItDown input adapter performs PDF reading at index time.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

DEFAULT_SOURCE_DIR = Path("runtime/public-knowledge-sources-20260815")
DEFAULT_WORKSPACE = Path("runtime/graphrag-public-knowledge")


def _safe_stem(path: Path) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", path.stem).strip("-._")
    return stem or "document"


def prepare(source_dir: Path, workspace: Path) -> dict[str, object]:
    input_dir = workspace / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []
    for source in sorted(source_dir.glob("*.pdf")):
        if "-test" in source.stem or source.stat().st_size < 5_000:
            continue
        output = input_dir / f"{_safe_stem(source)}.pdf"
        shutil.copy2(source, output)
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        manifest.append(
            {
                "input_file": str(output.relative_to(workspace)).replace("\\", "/"),
                "source_file": str(source).replace("\\", "/"),
                "source_checksum": digest,
                "source_locator_policy": "GraphRAG reads the original PDF through MarkItDown; use the original PDF and kb_chunks page_start/page_end for citation verification.",
            }
        )
    payload = {
        "corpus": "urban-renewal-public-knowledge-20260815",
        "source_count": len(manifest),
        "documents": manifest,
    }
    (workspace / "source_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    args = parser.parse_args()
    result = prepare(args.source_dir, args.workspace)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
