from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "prepare_external_spatial_benchmark_prompts.py"
SPEC = importlib.util.spec_from_file_location("external_spatial_benchmark_prompts", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_builds_answer_free_mapeval_prompt_pack(tmp_path):
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps(
            [{"id": 7, "context": "A is next to B.", "question": "What is next to B?", "answer": {"options": ["A", "C"], "correct": 0}}]
        ),
        encoding="utf-8",
    )

    prompts = MODULE.build_mapeval_textual_prompts(dataset)

    assert prompts == [{"case_id": "7", "prompt": prompts[0]["prompt"]}]
    assert "Option 1: A" in prompts[0]["prompt"]
    assert "correct" not in prompts[0]["prompt"]


def test_builds_mapqa_prompts_with_frozen_evidence_but_no_answer(tmp_path):
    dataset_dir = tmp_path / "question-answer"
    dataset_dir.mkdir()
    (dataset_dir / "adjacent_dataset.csv").write_text(
        "ID,Question,Answer\n3,Which place is adjacent?,Secret Answer\n",
        encoding="utf-8",
    )
    (dataset_dir / "adjacent_dataset.json").write_text(
        json.dumps({"3": {"Alpha Cafe": {"latitude": 41.0, "longitude": -87.0}}}),
        encoding="utf-8",
    )

    prompts = MODULE.build_mapqa_prompts(dataset_dir)

    assert prompts[0]["case_id"] == "adjacent_dataset:3"
    assert "Alpha Cafe" in prompts[0]["prompt"]
    assert "Secret Answer" not in prompts[0]["prompt"]
