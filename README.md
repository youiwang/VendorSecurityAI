# Vendor Security AI

## Overview

This repository contains a CVE remediation pipeline that turns vendor software inventory data into structured remediation output using an LLM-backed API.

The project has two parts:

1. Phase 1 POC assets are archived under [poc/](poc/).
2. Phase 2 production code lives under [src/](src/) and writes results to [outputs/prod/](outputs/prod/).

## Current Structure

```text
VendorSecurityAI/
├── data/
│   ├── poc/
│   │   └── VendorDeploymentCVE_20250901.csv
│   └── raw/
│       └── admyncec0904.csv
├── outputs/
│   └── prod/
│       ├── admyncec0904_remediated.csv
│       └── row_<n>_CVE-<id>.json
├── poc/
│   ├── README.md
│   ├── outputs/
│   │   └── experiments/
│   └── scripts/
│       ├── do_experiment.py
│       ├── generate_ai_conclusion.py
│       ├── list_failing_runs.py
│       ├── scan_experiment_failures.py
│       ├── summarize_experiments.py
│       └── visualize_experiments.py
├── src/
│   ├── generate_remediations.py
│   └── prompts/
│       ├── cot_analytical.txt
│       ├── criteria_defined.txt
│       ├── devsecops_actionable.txt
│       └── mitigation_focused.txt
├── requirements.txt
└── README.md
```

## How To Run Production

1. Create a virtual environment and install dependencies.

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

2. Create a `.env` file in the repository root.

```env
AI_ENDPOINT="your_ai_api_url"
API_KEY="your_api_key"
```

3. Run the production script.

```powershell
.venv\Scripts\python src\generate_remediations.py
```

The production script reads [data/raw/admyncec0904.csv](data/raw/admyncec0904.csv), applies [src/prompts/criteria_defined.txt](src/prompts/criteria_defined.txt), calls the configured API endpoint with the `CDG_gemini/gemini-3.5-flash` model, and writes results to [outputs/prod/](outputs/prod/).

## POC Archive

The archived experiment workflow is documented in [poc/README.md](poc/README.md). Use that folder when you want the model-and-prompt comparison history, experiment summaries, and triage helpers.

## Notes

1. The repository root is now the main entrypoint for the current project.
2. `poc/` is archived reference material, not the active production path.
3. Generated outputs remain under [outputs/prod/](outputs/prod/) for production runs.
