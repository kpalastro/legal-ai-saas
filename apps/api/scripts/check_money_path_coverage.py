"""Fail CI when the compliance/money-path modules lose coverage.

Overall coverage can hide a weak money path. Run after:
  uv run pytest --cov=app --cov-report=json:coverage.json
"""

from __future__ import annotations

import json
import pathlib

THRESHOLDS = {
    "app/agents/debate_state_machine.py": 100.0,
    "app/documents/registry.py": 100.0,
    "app/audit.py": 95.0,
    "app/citations/service.py": 85.0,
    "app/documents/generator.py": 90.0,
    "app/privacy.py": 80.0,
    "app/routers/features.py": 75.0,
}


def main() -> int:
    path = pathlib.Path("coverage.json")
    if not path.exists():
        print("coverage.json missing — run pytest with --cov-report=json:coverage.json")
        return 2
    data = json.loads(path.read_text())
    files = data.get("files", {})
    failures: list[str] = []
    for name, minimum in THRESHOLDS.items():
        entry = files.get(name)
        if entry is None:
            failures.append(f"{name}: missing from coverage report")
            continue
        actual = float(entry["summary"]["percent_covered"])
        status = "ok" if actual >= minimum else "FAIL"
        print(f"{status:4} {name:45} {actual:6.2f}% (min {minimum:.0f}%)")
        if actual < minimum:
            failures.append(f"{name}: {actual:.2f}% < {minimum:.0f}%")
    if failures:
        print("\nMoney-path coverage failures:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
