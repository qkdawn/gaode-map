from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_external_spatial_benchmarks.py"
SPEC = importlib.util.spec_from_file_location("external_spatial_benchmarks", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _write_jsonl(path: Path, items: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(item) for item in items) + "\n", encoding="utf-8")


def test_scores_mapeval_textual_with_coverage_and_invalid_answers(tmp_path):
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps(
            [
                {"id": 1, "answer": {"correct": 0}},
                {"id": 2, "answer": {"correct": 2}},
                {"id": 3, "answer": {"correct": 1}},
            ]
        ),
        encoding="utf-8",
    )
    predictions = tmp_path / "predictions.jsonl"
    _write_jsonl(
        predictions,
        [
            {"id": 1, "option_no": 1},
            {"id": 2, "option_no": 0},
            {"id": 999, "option_no": 2},
        ],
    )

    result = MODULE.evaluate_mapeval_textual(dataset, predictions)

    assert result["correct"] == 1
    assert result["invalid"] == 1
    assert result["missing"] == 1
    assert result["wrong"] == 0
    assert result["coverage"] == 2 / 3
    assert result["extra_prediction_ids"] == ["999"]


def test_scores_mapqa_text_and_distance_answers(tmp_path):
    dataset_dir = tmp_path / "question-answer"
    dataset_dir.mkdir()
    (dataset_dir / "adjacent_dataset.csv").write_text(
        "ID,Question,Answer\n7,Which place is adjacent?,Alpha Cafe\n",
        encoding="utf-8",
    )
    # The released distance CSV has a three-column row under a two-column header.
    (dataset_dir / "distance_dataset.csv").write_text(
        "Question,Answer\n1,How far?,1609.344 meters\n",
        encoding="utf-8",
    )
    predictions = tmp_path / "predictions.jsonl"
    _write_jsonl(
        predictions,
        [
            {"case_id": "adjacent_dataset:7", "answer": " alpha   cafe "},
            {"case_id": "distance_dataset:1", "answer": "1 mile"},
        ],
    )

    result = MODULE.evaluate_mapqa(dataset_dir, predictions)

    assert result["total"] == 2
    assert result["correct"] == 2
    assert result["accuracy"] == 1.0
    assert result["per_task"]["distance_dataset"]["accuracy"] == 1.0
