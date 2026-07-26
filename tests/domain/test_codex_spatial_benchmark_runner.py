from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "run_codex_spatial_benchmark.py"
SPEC = importlib.util.spec_from_file_location("codex_spatial_benchmark_runner", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_converts_only_valid_json_answers_to_predictions():
    case = {"case_id": "test:1", "prompt": "unused"}

    assert MODULE._prediction(case, '{"answer":"Alpha Cafe"}') == {"case_id": "test:1", "answer": "Alpha Cafe"}
    assert MODULE._prediction(case, '{"option_no":2}') == {"case_id": "test:1", "option_no": 2}
    assert MODULE._prediction(case, "not json") == {"case_id": "test:1"}


def test_instruction_uses_only_prompt_pack_content():
    case = {"case_id": "test:2", "prompt": "Question: where?"}

    prompt = MODULE._instruction(case)

    assert "Question: where?" in prompt
    assert "answer key" not in prompt.casefold()


def test_response_filename_is_safe_on_windows():
    assert MODULE._response_filename("distance_dataset:1") == "distance_dataset_1.json"


def test_isolated_worker_delegates_to_case_runner(monkeypatch, tmp_path):
    observed = {}

    def fake_run_case(**kwargs):
        observed.update(kwargs)
        return {"case_id": "test:3", "option_no": 1}, '{"option_no":1}'

    monkeypatch.setattr(MODULE, "run_case", fake_run_case)
    response_path = tmp_path / "response.json"

    prediction, response = MODULE._run_in_isolated_workspace(
        codex_bin=tmp_path / "codex.exe",
        case={"case_id": "test:3", "prompt": "Question"},
        response_path=response_path,
        timeout_seconds=10,
        model=None,
    )

    assert prediction["option_no"] == 1
    assert response == '{"option_no":1}'
    assert observed["workspace"] != tmp_path
