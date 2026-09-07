# POC Archive

This folder contains the archived Phase 1 experiment workflow that was used to compare prompt variants and models before the production pipeline was selected.

The goal of the experiment was to answer two questions:

1. Which model produced the most reliable CVE remediation output.
2. Which prompt style produced the best balance of actionable guidance, valid JSON, and reasonable risk scoring.

## What Is Here

### Scripts

The experiment scripts live in [scripts/](scripts/):

- [do_experiment.py](scripts/do_experiment.py) runs the model comparison experiments and writes per-run JSON output.
- [summarize_experiments.py](scripts/summarize_experiments.py) builds the comparison summary CSV and HTML report.
- [list_failing_runs.py](scripts/list_failing_runs.py) filters failed or incomplete runs for triage.
- [scan_experiment_failures.py](scripts/scan_experiment_failures.py) inspects failure patterns across experiment outputs.
- [visualize_experiments.py](scripts/visualize_experiments.py) creates charts from the summarized experiment data.
- [generate_ai_conclusion.py](scripts/generate_ai_conclusion.py) produces the written executive-style conclusion for the experiment results.

### What The Experiment Compared

The runner in [do_experiment.py](scripts/do_experiment.py) looped through a CSV of CVE rows, sent each row to several Gemini model variants, and repeated the run across multiple prompt templates.

The main pieces of the comparison were:

- Model variants such as `CDG_gemini/gemini-3.1-flash-lite`, `CDG_gemini/gemini-3.5-flash`, and `CDG_gemini/gemini-3.1-pro-preview`.
- Prompt styles such as `criteria_defined`, `mitigation_focused`, `cot_analytical`, and `devsecops_actionable`.
- Output quality checks for JSON structure, risk-level format, source citations, and practical remediation guidance.

Each generated response was saved per row so the later scripts could summarize performance, identify failures, and compare the prompt variants side by side.

### Outputs

The archived experiment artifacts live under [outputs/experiments/](outputs/experiments/). This folder typically contains:

- Per-run JSON files for each model and prompt combination
- `comparison_summary.csv` and `comparison_summary_clean.csv`
- `comparison_summary.html`
- Supporting analysis files such as grouped, reliability, and dropped-row summaries
- Final writeups such as the AI executive conclusion Markdown and HTML files

## How The POC Workflow Worked

1. Run [do_experiment.py](scripts/do_experiment.py) to generate raw experiment outputs.
2. Run [summarize_experiments.py](scripts/summarize_experiments.py) to aggregate scores and metadata.
3. Run [list_failing_runs.py](scripts/list_failing_runs.py) to isolate failed or noisy runs.
4. Run [visualize_experiments.py](scripts/visualize_experiments.py) to generate comparison charts.
5. Use [generate_ai_conclusion.py](scripts/generate_ai_conclusion.py) to produce the final written summary.

## How Results Were Judged

Some runs also used a judge step to score the generated remediation text. The judge focused on:

- Actionability: whether the recommendation was concrete enough to use.
- Rationale logic: whether the risk level explanation matched the CVE.
- Safety and accuracy: whether the model invented unsupported versions or sources.
- Formatting: whether the response stayed close to the required JSON structure.

That extra evaluation helped separate outputs that merely looked correct from outputs that were actually useful and trustworthy.

## Notes

- This folder is archived and is not the primary production path.
- The main production pipeline now lives in [../src/generate_remediations.py](../src/generate_remediations.py).
- The root project README describes the current live structure and production entrypoint.
