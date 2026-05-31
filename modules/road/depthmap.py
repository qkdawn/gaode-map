from __future__ import annotations

import csv
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from core.config import settings


def resolve_depthmap_cli_path() -> str:
    candidates: List[str] = []
    if getattr(settings, "depthmapx_cli_path", ""):
        candidates.append(str(settings.depthmapx_cli_path).strip())
    candidates.extend(["depthmapXcli", "depthmapXcli.exe"])

    dedup: List[str] = []
    seen = set()
    for item in candidates:
        if not item or item in seen:
            continue
        seen.add(item)
        dedup.append(item)

    for item in dedup:
        path = Path(item)
        if path.exists():
            return str(path)
        resolved = shutil.which(item)
        if resolved:
            return resolved

    raise RuntimeError(
        "depthmapXcli 未找到。请安装 depthmapXcli 并配置 DEPTHMAPX_CLI_PATH。"
    )


def run_depthmap_cmd(
    cli_path: str,
    args: List[str],
    workdir: Path,
    timeout_s: int,
) -> None:
    command = [cli_path] + args
    try:
        proc = subprocess.run(
            command,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=max(30, int(timeout_s)),
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"depthmapXcli 超时（>{timeout_s}s）：{' '.join(command)}") from exc
    except OSError as exc:
        raise RuntimeError(f"执行 depthmapXcli 失败：{exc}") from exc

    if proc.returncode != 0:
        stderr_tail = (proc.stderr or "").strip().splitlines()[-8:]
        stdout_tail = (proc.stdout or "").strip().splitlines()[-8:]
        tail = "\n".join((stderr_tail or stdout_tail)[:8])
        raise RuntimeError(
            f"depthmapXcli 命令失败（exit={proc.returncode}）：{' '.join(command)}\n{tail}"
        )


def write_depthmap_lines_csv(lines_csv: Path, edge_inputs: List[Dict[str, Any]]) -> None:
    with lines_csv.open("w", newline="", encoding="utf-8") as handle:
        # depthmapXcli IMPORT is sensitive to CRLF in large CSV inputs.
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["Ref", "x1", "y1", "x2", "y2"])
        for edge in edge_inputs:
            writer.writerow([edge["ref"], edge["x1"], edge["y1"], edge["x2"], edge["y2"]])


def run_depthmap_segment_pipeline(
    cli_path: str,
    tmpdir: Path,
    graph_imported: Path,
    graph_analysed: Path,
    timeout_s: int,
    tulip_bins_value: int,
    local_radii: List[int],
    build_radius_arg,
    run_cmd=run_depthmap_cmd,
) -> None:
    graph_segment = tmpdir / "02_segment.graph"
    run_cmd(
        cli_path,
        [
            "-m",
            "MAPCONVERT",
            "-f",
            str(graph_imported),
            "-o",
            str(graph_segment),
            "-co",
            "segment",
            "-con",
            "road_segments",
        ],
        tmpdir,
        timeout_s,
    )
    run_cmd(
        cli_path,
        [
            "-m",
            "SEGMENT",
            "-f",
            str(graph_segment),
            "-o",
            str(graph_analysed),
            "-st",
            "tulip",
            "-srt",
            "metric",
            "-stb",
            str(tulip_bins_value),
            "-sic",
            "-sr",
            build_radius_arg(local_radii),
        ],
        tmpdir,
        timeout_s,
    )


def run_depthmap_axial_pipeline(
    cli_path: str,
    tmpdir: Path,
    graph_imported: Path,
    graph_analysed: Path,
    timeout_s: int,
    local_radii: List[int],
    build_radius_arg,
    run_cmd=run_depthmap_cmd,
) -> None:
    graph_axial = tmpdir / "02_axial.graph"
    run_cmd(
        cli_path,
        [
            "-m",
            "MAPCONVERT",
            "-f",
            str(graph_imported),
            "-o",
            str(graph_axial),
            "-co",
            "axial",
            "-con",
            "road_axial",
        ],
        tmpdir,
        timeout_s,
    )
    run_cmd(
        cli_path,
        [
            "-m",
            "AXIAL",
            "-f",
            str(graph_axial),
            "-o",
            str(graph_analysed),
            "-xa",
            build_radius_arg(local_radii),
            "-xac",
            "-xal",
        ],
        tmpdir,
        timeout_s,
    )
