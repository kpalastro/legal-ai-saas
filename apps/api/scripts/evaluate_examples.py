"""Structural evaluation over the worked examples (no live model required).

Checks every `requirement/examples/*/05_verdict.json` for the calibrated-range
schema and every case directory for a manifest. This is a regression net for
output *structure*; legal-quality grading still requires expert review.
"""

from __future__ import annotations

import json
import pathlib

EXAMPLES = pathlib.Path(__file__).resolve().parents[3] / "requirement" / "examples"


def main() -> int:
    failures: list[str] = []
    cases = sorted(path for path in EXAMPLES.iterdir() if path.is_dir())
    if not cases:
        print(f"no example directories in {EXAMPLES}")
        return 2
    for case in cases:
        manifest = case / "MANIFEST.json"
        verdict_path = case / "05_verdict.json"
        if not manifest.exists():
            failures.append(f"{case.name}: missing MANIFEST.json")
        if not verdict_path.exists():
            failures.append(f"{case.name}: missing 05_verdict.json")
            continue
        try:
            record = json.loads(verdict_path.read_text())
        except json.JSONDecodeError as exc:
            failures.append(f"{case.name}: invalid JSON ({exc})")
            continue
        # The worked examples store the model's JSON payload as a string field.
        raw = record.get("verdict")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                failures.append(f"{case.name}: verdict payload is not valid JSON")
                continue
        elif isinstance(raw, dict):
            parsed = raw
        else:
            parsed = record
        values = [parsed.get(key) for key in ("lower", "point", "upper")]
        if not all(isinstance(value, (int, float)) for value in values):
            failures.append(f"{case.name}: verdict is not a numeric range")
            continue
        lower, point, upper = values
        if not (0 <= lower <= point <= upper <= 100):
            failures.append(f"{case.name}: range is not 0 <= lower <= point <= upper <= 100")
        haystack = json.dumps(record).lower() + json.dumps(parsed).lower()
        if "not legal advice" not in haystack:
            failures.append(f"{case.name}: missing not-legal-advice note")
        print(f"ok   {case.name}: {lower}%–{upper}% (point {point}%)")
    if failures:
        print("\nExample evaluation failures:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
