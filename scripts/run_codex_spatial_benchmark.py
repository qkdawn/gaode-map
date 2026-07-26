"""Run an answer-free spatial benchmark prompt pack through Codex CLI.

Each case is executed in a fresh temporary workspace. This prevents an agent
from discovering local benchmark answer files while retaining raw responses for
audit and conversion to the scorer's JSONL format.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _prediction(case: dict[str, Any], response: str) -> dict[str, Any]:
    result: dict[str, Any] = {"case_id": str(case["case_id"])}
    try:
        parsed = json.loads(response)
    except json.JSONDecodeError:
        return result
    if "option_no" in parsed:
        result["option_no"] = parsed["option_no"]
    if "answer" in parsed:
        result["answer"] = parsed["answer"]
    return result


def _instruction(case: dict[str, Any]) -> str:
    return (
        "You are the benchmark adapter for the spatial-business-analyst capability. "
        "Treat the supplied content as a standalone spatial question. Do not inspect files, "
        "browse the web, or use external knowledge. Return only the requested JSON object.\n\n"
        + str(case["prompt"])
    )


def _response_filename(case_id: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "_" for character in case_id) + ".json"


def run_case(
    *,
    codex_bin: Path,
    workspace: Path,
    case: dict[str, Any],
    response_path: Path,
    timeout_seconds: int,
    model: str | None,
) -> tuple[dict[str, Any], str]:
    command = [
        str(codex_bin),
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "-C",
        str(workspace),
        "-s",
        "read-only",
        "--color",
        "never",
        "-o",
        str(response_path),
    ]
    if model:
        command.extend(["--model", model])
    command.append("-")
    completed = subprocess.run(
        command,
        input=_instruction(case),
        text=True,
        encoding="utf-8",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
    )
    response = response_path.read_text(encoding="utf-8").strip() if response_path.exists() else ""
    if not response and completed.returncode:
        response = json.dumps({"error": "codex_failed", "returncode": completed.returncode, "stderr": completed.stderr[-2000:]})
    return _prediction(case, response), response


def _run_in_isolated_workspace(
    *,
    codex_bin: Path,
    case: dict[str, Any],
    response_path: Path,
    timeout_seconds: int,
    model: str | None,
) -> tuple[dict[str, Any], str]:
    with tempfile.TemporaryDirectory(prefix="codex-spatial-benchmark-") as temporary_workspace:
        return run_case(
            codex_bin=codex_bin,
            workspace=Path(temporary_workspace),
            case=case,
            response_path=response_path,
            timeout_seconds=timeout_seconds,
            model=model,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an answer-free spatial prompt pack through Codex CLI.")
    parser.add_argument("--prompt-pack", required=True, type=Path)
    parser.add_argument("--codex-bin", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--raw-output-dir", required=True, type=Path)
    parser.add_argument("--limit", type=int, help="Maximum number of cases. Required unless --all is set.")
    parser.add_argument("--all", action="store_true", help="Run every case in the prompt pack.")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--model", help="Optional Codex model override. The configured default is used otherwise.")
    parser.add_argument("--workers", type=int, default=1, help="Concurrent isolated Codex sessions (default: 1).")
    args = parser.parse_args()
    if args.all == (args.limit is not None):
        parser.error("Provide exactly one of --limit or --all")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.workers < 1:
        parser.error("--workers must be positive")
    if not args.codex_bin.is_file():
        parser.error(f"Codex executable not found: {args.codex_bin}")

    cases = _read_jsonl(args.prompt_pack)
    selected = cases if args.all else cases[: args.limit]
    args.predictions.parent.mkdir(parents=True, exist_ok=True)
    args.raw_output_dir.mkdir(parents=True, exist_ok=True)
    completed_ids = {str(item.get("case_id", item.get("id", ""))) for item in _read_jsonl(args.predictions)} if args.predictions.exists() else set()

    pending = [case for case in selected if str(case["case_id"]) not in completed_ids]
    with args.predictions.open("a", encoding="utf-8") as predictions_file:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(
                    _run_in_isolated_workspace,
                    codex_bin=args.codex_bin,
                    case=case,
                    response_path=args.raw_output_dir / _response_filename(str(case["case_id"])),
                    timeout_seconds=args.timeout_seconds,
                    model=args.model,
                ): case
                for case in pending
            }
            for completed_count, future in enumerate(as_completed(futures), 1):
                case = futures[future]
                case_id = str(case["case_id"])
                response_path = args.raw_output_dir / _response_filename(case_id)
                try:
                    prediction, response = future.result()
                except Exception as error:  # Keep a failed case auditable and score it invalid.
                    response = json.dumps({"error": type(error).__name__, "message": str(error)})
                    prediction = {"case_id": case_id}
                if not response_path.exists():
                    response_path.write_text(response + "\n", encoding="utf-8")
                predictions_file.write(json.dumps(prediction, ensure_ascii=False) + "\n")
                predictions_file.flush()
                print(f"{completed_count}/{len(pending)} {case_id}")


if __name__ == "__main__":
    main()
