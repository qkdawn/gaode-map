"""Evaluate predictions on externally maintained spatial QA benchmarks.

The runner deliberately does not invoke an LLM or a map provider. It scores
previously generated predictions against a pinned local benchmark snapshot so a
reported result can be reproduced without live-map drift.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any


RUNNER_VERSION = "1"
MAPQA_DISTANCE_TOLERANCE_METERS = 100.0


def _sha256_paths(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _read_jsonl(path: Path) -> dict[str, dict[str, Any]]:
    predictions: dict[str, dict[str, Any]] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        item = json.loads(line)
        case_id = str(item.get("case_id", item.get("id", "")))
        if not case_id:
            raise ValueError(f"{path}:{line_number} is missing case_id or id")
        if case_id in predictions:
            raise ValueError(f"{path}:{line_number} duplicates prediction {case_id}")
        predictions[case_id] = item
    return predictions


def _normalize_text(value: Any) -> str:
    return " ".join(str(value).casefold().strip().split())


def evaluate_mapeval_textual(dataset_path: Path, predictions_path: Path) -> dict[str, Any]:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    predictions = _read_jsonl(predictions_path)
    expected_ids = {str(item["id"]) for item in dataset}
    extra_ids = sorted(set(predictions) - expected_ids)
    correct = invalid = missing = 0

    for item in dataset:
        case_id = str(item["id"])
        prediction = predictions.get(case_id)
        if prediction is None:
            missing += 1
            continue
        try:
            option_no = int(prediction["option_no"])
        except (KeyError, TypeError, ValueError):
            invalid += 1
            continue
        if option_no == 0:
            invalid += 1
            continue
        if option_no - 1 == int(item["answer"]["correct"]):
            correct += 1

    total = len(dataset)
    return {
        "benchmark": "MapEval-Textual",
        "runner_version": RUNNER_VERSION,
        "dataset_sha256": _sha256_paths([dataset_path]),
        "predictions_sha256": _sha256_paths([predictions_path]),
        "total": total,
        "correct": correct,
        "wrong": total - correct - invalid - missing,
        "invalid": invalid,
        "missing": missing,
        "extra_prediction_ids": extra_ids,
        "coverage": (total - missing) / total if total else 0.0,
        "accuracy": correct / total if total else 0.0,
    }


def _mapqa_rows(dataset_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(dataset_dir.glob("*.csv")):
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            next(reader, None)
            for row_number, row in enumerate(reader, 1):
                if len(row) == 3:
                    source_id, question, answer = row
                elif len(row) == 2:
                    source_id, question, answer = str(row_number), row[0], row[1]
                else:
                    raise ValueError(f"Unexpected row shape in {path}:{row_number}")
                rows.append(
                    {
                        "case_id": f"{path.stem}:{source_id}",
                        "task": path.stem,
                        "question": question,
                        "answer": answer,
                    }
                )
    if not rows:
        raise ValueError(f"No MapQA CSV files found in {dataset_dir}")
    return rows


def _distance_meters(value: Any) -> float | None:
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(km|kilometers?|mi|miles?|m|meters?)?", str(value).casefold())
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or "m"
    if unit.startswith("km") or unit.startswith("kilometer"):
        return number * 1000
    if unit.startswith("mi") or unit.startswith("mile"):
        return number * 1609.344
    return number


def evaluate_mapqa(dataset_dir: Path, predictions_path: Path) -> dict[str, Any]:
    rows = _mapqa_rows(dataset_dir)
    predictions = _read_jsonl(predictions_path)
    expected_ids = {row["case_id"] for row in rows}
    extra_ids = sorted(set(predictions) - expected_ids)
    correct = invalid = missing = 0
    per_task: dict[str, dict[str, int]] = {}

    for row in rows:
        metrics = per_task.setdefault(row["task"], {"total": 0, "correct": 0, "invalid": 0, "missing": 0})
        metrics["total"] += 1
        prediction = predictions.get(row["case_id"])
        if prediction is None:
            missing += 1
            metrics["missing"] += 1
            continue
        answer = prediction.get("answer")
        if answer is None:
            invalid += 1
            metrics["invalid"] += 1
            continue
        if row["task"] == "distance_dataset":
            actual = _distance_meters(row["answer"])
            proposed = _distance_meters(answer)
            is_correct = actual is not None and proposed is not None and abs(actual - proposed) < MAPQA_DISTANCE_TOLERANCE_METERS
        else:
            is_correct = _normalize_text(answer) == _normalize_text(row["answer"])
        if is_correct:
            correct += 1
            metrics["correct"] += 1

    total = len(rows)
    for metrics in per_task.values():
        metrics["accuracy"] = metrics["correct"] / metrics["total"] if metrics["total"] else 0.0
    return {
        "benchmark": "MapQA",
        "runner_version": RUNNER_VERSION,
        "dataset_sha256": _sha256_paths(dataset_dir.glob("*.csv")),
        "predictions_sha256": _sha256_paths([predictions_path]),
        "distance_tolerance_meters": MAPQA_DISTANCE_TOLERANCE_METERS,
        "total": total,
        "correct": correct,
        "wrong": total - correct - invalid - missing,
        "invalid": invalid,
        "missing": missing,
        "extra_prediction_ids": extra_ids,
        "coverage": (total - missing) / total if total else 0.0,
        "accuracy": correct / total if total else 0.0,
        "per_task": per_task,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Score reproducible external spatial benchmark predictions.")
    subparsers = parser.add_subparsers(dest="benchmark", required=True)
    for name, dataset_help in (
        ("mapeval-textual", "Path to MapEval-Textual dataset.json"),
        ("mapqa", "Path to MapQA llm/<region>/question-answer directory"),
    ):
        command = subparsers.add_parser(name)
        command.add_argument("--dataset", required=True, type=Path, help=dataset_help)
        command.add_argument("--predictions", required=True, type=Path, help="JSONL predictions with case_id and answer fields")
        command.add_argument("--output", required=True, type=Path, help="Result JSON path")
    subparsers.add_parser("mapeval-api", help="Explain why the live API benchmark is intentionally unsupported.")
    args = parser.parse_args()

    if args.benchmark == "mapeval-api":
        parser.error(
            "MapEval-API is not self-contained: its official runner requires an unpublished localhost map backend. "
            "Do not report a Gaode-backed run as an official MapEval-API score."
        )

    if args.benchmark == "mapeval-textual":
        result = evaluate_mapeval_textual(args.dataset, args.predictions)
    else:
        result = evaluate_mapqa(args.dataset, args.predictions)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
