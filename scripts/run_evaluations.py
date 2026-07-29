"""Run the reproducible mocked behavioral evaluation suite."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.evaluation.runner import run_mock_evaluations  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=PROJECT_ROOT / "evals" / "evaluation_cases.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "evaluation_results" / "mock_latest.json",
    )
    args = parser.parse_args(argv)
    report = run_mock_evaluations(args.dataset, PROJECT_ROOT / "data")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(report["metrics"], indent=2))
    if report["failures"]:
        print(json.dumps({"failures": report["failures"]}, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
