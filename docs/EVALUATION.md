# Evaluation and calibration

> **No outcome dataset ships with this repo.** Calibration is a property of a
> dataset and a methodology, not a code feature. The harness is here so that a
> lawyer-reviewed dataset can be measured without inventing numbers.

## Structural checks (available now)

```bash
cd apps/api
uv run python scripts/evaluate_examples.py   # worked-example schema/range check
uv run pytest -m compliance                  # gates and protocol structure
```

## Range calibration (needs a dataset)

Create a CSV with one row per matter:

```
predicted_lower,predicted_point,predicted_upper,outcome
40,50,60,1
30,45,60,0
```

`outcome` is `1` if the plaintiff succeeded and `0` otherwise. Then:

```bash
cd apps/api
uv run python scripts/calibrate.py --input outcomes.csv --out report.json
```

Metrics: range coverage (how often the outcome fell inside the band), mean
interval width, Brier score, point MAE. A wide range can look “calibrated” while
being useless — report coverage and width together.

## What still requires humans

- A representative sample of decided matters (not synthetic examples).
- Lawyer/expert grading of reasoning, issue spotting and citations.
- A documented methodology and limitations before any calibration claim.
- Red-team/prompt-injection evaluation beyond the structural tests.
