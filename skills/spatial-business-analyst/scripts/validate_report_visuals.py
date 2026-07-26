"""Validate one formal report's visual plan, manifest, Markdown and assets."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from modules.report_visuals.service import validate_report_visual_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True, help="Directory containing project-report.md and the visual bundle")
    args = parser.parse_args()
    report_dir = Path(args.report_dir).resolve()
    required = ("project-report.md", "visual-plan.json", "visual-manifest.json")
    errors = [f"visual_bundle_missing_required_file:{name}" for name in required if not (report_dir / name).is_file()]
    if not errors:
        errors.extend(validate_report_visual_bundle(report_dir))
    payload = {
        "status": "passed" if not errors else "failed",
        "report_dir": str(report_dir),
        "errors": errors,
    }
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
