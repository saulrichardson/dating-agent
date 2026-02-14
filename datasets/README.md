# Datasets (Committed, No PII)

This folder contains **synthetic, committed** datasets used for offline validation of the LLM decision loop.

Goals:

- deterministic, reviewable inputs
- no device/Appium required
- nightly-friendly drift detection
- **no private Hinge data** committed to git

## What Is Here

- `hinge_llm_regression/`
  - `cases.synthetic.v1.jsonl`: fixed packets (and optional placeholder screenshots) with expected action constraints
  - `profile.synthetic.v1.json`: persona + policy used by the regression cases
  - `baselines/`: snapshot baselines (action/message) for drift detection
  - `assets/`: placeholder images safe to commit (no real profiles)
- `hinge_rollouts/`
  - `scenarios.synthetic.v1.json`: multi-step state machine scenarios for long-horizon validation

## What Must NOT Be Committed

- any real screenshots from Hinge/Tinder
- action logs from real sessions
- session packages built from real captures

Those should live under `artifacts/` (gitignored). Use:

- `scripts/build-llm-regression-dataset.py` to create a private regression dataset from real runs

