"""Calibration/backtesting harness for verdict ranges.

Input CSV columns:
  predicted_lower, predicted_point, predicted_upper, outcome
where points are 0-100 and outcome is 0/1 (plaintiff did/did not succeed).

This computes what can be measured without inventing data: coverage of the
range, interval width, Brier score and point MAE. It does not replace expert
review or a proper outcome dataset.

Usage:
  uv run python scripts/calibrate.py --input outcomes.csv [--out report.json]
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib

REQUIRED = {"predicted_lower", "predicted_point", "predicted_upper", "outcome"}


def load(path: pathlib.Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"missing columns: {sorted(missing)}")
        rows: list[dict] = []
        for line, raw in enumerate(reader, start=2):
            try:
                lower = float(raw["predicted_lower"])
                point = float(raw["predicted_point"])
                upper = float(raw["predicted_upper"])
                outcome = int(raw["outcome"])
            except (TypeError, ValueError):
                raise ValueError(f"line {line}: non-numeric field") from None
            if not (0 <= lower <= point <= upper <= 100):
                raise ValueError(f"line {line}: require 0 <= lower <= point <= upper <= 100")
            if outcome not in (0, 1):
                raise ValueError(f"line {line}: outcome must be 0 or 1")
            rows.append(
                {
                    "predicted_lower": lower,
                    "predicted_point": point,
                    "predicted_upper": upper,
                    "outcome": outcome,
                }
            )
    return rows


def summarise(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("no rows")
    n = len(rows)
    covered = sum(
        1
        for row in rows
        if row["predicted_lower"] <= row["outcome"] * 100 <= row["predicted_upper"]
    )
    width = sum(row["predicted_upper"] - row["predicted_lower"] for row in rows) / n
    brier = sum((row["predicted_point"] / 100 - row["outcome"]) ** 2 for row in rows) / n
    mae = sum(abs(row["predicted_point"] - row["outcome"] * 100) for row in rows) / n
    return {
        "n": n,
        "range_coverage": round(covered / n, 4),
        "mean_interval_width": round(width, 2),
        "brier_score": round(brier, 4),
        "point_mae": round(mae, 2),
        "note": (
            "Structural calibration metrics only. A defensible calibration claim "
            "also needs a representative settled-matter dataset and expert review."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=pathlib.Path)
    parser.add_argument("--out", type=pathlib.Path)
    args = parser.parse_args()

    report = summarise(load(args.input))
    rendered = json.dumps(report, indent=2)
    print(rendered)
    if args.out:
        args.out.write_text(rendered + "\n")


if __name__ == "__main__":
    main()
