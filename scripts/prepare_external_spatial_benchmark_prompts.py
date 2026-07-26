"""Build answer-free prompt packs for externally maintained spatial benchmarks.

The pack is deliberately separated from scoring. It contains only benchmark
inputs, allowing an agent runtime to generate predictions without access to
the released answer labels.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


_EVALUATOR_PATH = Path(__file__).with_name("evaluate_external_spatial_benchmarks.py")
_EVALUATOR_SPEC = importlib.util.spec_from_file_location("external_spatial_benchmark_evaluator", _EVALUATOR_PATH)
assert _EVALUATOR_SPEC and _EVALUATOR_SPEC.loader
_EVALUATOR_MODULE = importlib.util.module_from_spec(_EVALUATOR_SPEC)
_EVALUATOR_SPEC.loader.exec_module(_EVALUATOR_MODULE)
_mapqa_rows = _EVALUATOR_MODULE._mapqa_rows


RUNNER_VERSION = "1"


def _sha256_paths(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def build_mapeval_textual_prompts(dataset_path: Path) -> list[dict[str, Any]]:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    prompts: list[dict[str, Any]] = []
    for item in dataset:
        options = item["answer"]["options"]
        option_text = "\n".join(
            f"Option {index}: {option}" for index, option in enumerate(options, 1) if option
        )
        prompt = (
            "Use only the supplied map context. Do not use external knowledge or assumptions.\n\n"
            f"Context:\n{item['context']}\n\n"
            f"Question:\n{item['question']}\n\n"
            f"{option_text}\n\n"
            "Reply with JSON only: {\"option_no\": <selected one-based option number>}. "
            "Use 0 only when none of the listed options is supported by the context."
        )
        prompts.append({"case_id": str(item["id"]), "prompt": prompt})
    return prompts


def build_mapqa_prompts(dataset_dir: Path) -> list[dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for path in sorted(dataset_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"Expected an object keyed by source ID in {path}")
        contexts[path.stem] = payload

    prompts: list[dict[str, Any]] = []
    for row in _mapqa_rows(dataset_dir):
        source_id = row["case_id"].split(":", 1)[1]
        context = contexts.get(row["task"], {}).get(source_id)
        if context is None:
            raise ValueError(f"Missing frozen MapQA evidence for {row['case_id']}")
        prompt = (
            "Answer the geospatial question using only the frozen OSM evidence below. "
            "Do not browse or use external knowledge. Preserve the requested answer format.\n\n"
            f"Question:\n{row['question']}\n\n"
            f"Frozen OSM evidence:\n{json.dumps(context, ensure_ascii=False)}\n\n"
            "Reply with JSON only: {\"answer\": \"<answer>\"}."
        )
        prompts.append({"case_id": row["case_id"], "task": row["task"], "prompt": prompt})
    return prompts


def _write_jsonl(path: Path, prompts: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in prompts),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build answer-free external spatial benchmark prompt packs.")
    subparsers = parser.add_subparsers(dest="benchmark", required=True)
    for name, dataset_help in (
        ("mapeval-textual", "Path to MapEval-Textual dataset.json"),
        ("mapqa", "Path to MapQA llm/<region>/question-answer directory"),
    ):
        command = subparsers.add_parser(name)
        command.add_argument("--dataset", required=True, type=Path, help=dataset_help)
        command.add_argument("--output", required=True, type=Path, help="Answer-free output JSONL path")
        command.add_argument("--manifest", required=True, type=Path, help="Run metadata JSON path")
    args = parser.parse_args()

    if args.benchmark == "mapeval-textual":
        prompts = build_mapeval_textual_prompts(args.dataset)
        source_paths = [args.dataset]
    else:
        prompts = build_mapqa_prompts(args.dataset)
        source_paths = list(args.dataset.glob("*.csv")) + list(args.dataset.glob("*.json"))

    _write_jsonl(args.output, prompts)
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "benchmark": "MapEval-Textual" if args.benchmark == "mapeval-textual" else "MapQA",
        "runner_version": RUNNER_VERSION,
        "input_sha256": _sha256_paths(source_paths),
        "prompt_count": len(prompts),
        "prompt_pack_sha256": _sha256_paths([args.output]),
        "answer_free": True,
    }
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
