"""Visualize experiment results.

Reads `outputs/experiments/comparison_summary.csv`, aggregates by `model` and
`variant`, writes `grouped_summary.csv`, and saves two charts:
- `chart_cost_vs_quality.png` (cost vs judge score scatter)
- `chart_model_performance.png` (grouped bar chart of judge scores)

Module is organized into functions with type hints for clarity.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import numpy as np

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns


INPUT_CSV = Path("outputs/experiments/comparison_summary.csv")
OUT_GROUPED = Path("outputs/experiments/grouped_summary.csv")
OUT_SCATTER = Path("outputs/experiments/chart_cost_vs_quality_avg.png")
OUT_SCATTER_ALL = Path("outputs/experiments/chart_cost_vs_quality_per_run.png")
OUT_BAR = Path("outputs/experiments/chart_model_performance_box_per_run.png")
OUT_BAR_AVG = Path("outputs/experiments/chart_model_performance_bar_avg.png")

# Desired fixed model legend/order: pro, flash, flash-lite
MODEL_ORDER = [
    "CDG_gemini/gemini-3.1-pro-preview",
    "CDG_gemini/gemini-3.5-flash",
    "CDG_gemini/gemini-3.1-flash-lite",
]


def load_and_aggregate_data(csv_path: Path) -> pd.DataFrame:
    """Load the comparison CSV and return an aggregated dataframe.

    Group by `model` and `variant` and compute means for requested fields.
    Performs cleaning and rounding per spec.
    """
    if not csv_path.exists():
        print(f"Input file not found: {csv_path}. Run experiments first.")
        raise SystemExit(1)

    df = pd.read_csv(csv_path)

    # Ensure key columns exist
    cols_expected = [
        "json_parse_success",
        "schema_adherence_pct",
        "latency_ms",
        "total_tokens",
        "score",
        "judge_total_score",
    ]

    # Normalize json_parse_success to numeric percent (0 or 100)
    if "json_parse_success" in df.columns:
        # handle booleans, numbers, and strings like 'True'/'False'
        def _to_percent(x):
            if pd.isna(x):
                return float("nan")
            if isinstance(x, (int, float)):
                return 100.0 if x else 0.0
            s = str(x).strip().lower()
            if s in ("true", "1", "yes", "y"):
                return 100.0
            if s in ("false", "0", "no", "n"):
                return 0.0
            return float("nan")

        df["json_parse_success"] = df["json_parse_success"].apply(_to_percent)

    # Coerce numeric columns
    for c in ("schema_adherence_pct", "latency_ms", "total_tokens", "score", "judge_total_score"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    # Before aggregating, apply the same cleaning rules used for per-run plots
    drop_mask = pd.Series(False, index=df.index)
    if 'parse_error' in df.columns:
        parse_err_mask = df['parse_error'].notna() & (df['parse_error'] != 'None')
        drop_mask = drop_mask | parse_err_mask
    missing_mask = df['total_tokens'].isna() | df['judge_total_score'].isna()
    drop_mask = drop_mask | missing_mask
    cleaned_for_agg = df[~drop_mask].copy()

    # Group and aggregate (mean) using cleaned rows only
    grouped = (
        cleaned_for_agg.groupby(["model", "variant"], dropna=False)
        .agg(
            json_parse_success_mean=("json_parse_success", "mean"),
            schema_adherence_pct_mean=("schema_adherence_pct", "mean"),
            latency_ms_mean=("latency_ms", "mean"),
            total_tokens_mean=("total_tokens", "mean"),
            score_mean=("score", "mean"),
            judge_total_score_mean=("judge_total_score", "mean"),
            count=("file", "count"),
        )
        .reset_index()
    )

    # Rounding rules: percent & scores -> 2 decimals; latency & tokens -> integers
    grouped["json_parse_success_mean"] = grouped["json_parse_success_mean"].round(2)
    grouped["schema_adherence_pct_mean"] = grouped["schema_adherence_pct_mean"].round(2)
    grouped["score_mean"] = grouped["score_mean"].round(2)
    grouped["judge_total_score_mean"] = grouped["judge_total_score_mean"].round(2)

    grouped["latency_ms_mean"] = grouped["latency_ms_mean"].round(0).astype("Int64")
    grouped["total_tokens_mean"] = grouped["total_tokens_mean"].round(0).astype("Int64")

    # Sorting: by judge_total_score desc (NaN last), then score desc
    grouped["judge_sort_key"] = grouped["judge_total_score_mean"].fillna(-1)
    grouped = grouped.sort_values(by=["judge_sort_key", "score_mean"], ascending=[False, False])
    grouped = grouped.drop(columns=["judge_sort_key"])

    return grouped


def plot_scatter(df: pd.DataFrame, out_path: Path, palette: Optional[dict] = None, data_origin: Optional[str] = None) -> None:
    """Plot cost (tokens) vs. judge score scatter plot.

    - X: total_tokens_mean
    - Y: judge_total_score_mean
    - hue: model
    - style: variant
    """
    sns.set(style="whitegrid")
    plt.figure(figsize=(10, 6))
    ax = sns.scatterplot(
        data=df,
        x="total_tokens_mean",
        y="judge_total_score_mean",
        hue="model",
        hue_order=MODEL_ORDER,
        style="variant",
        s=120,
        palette=palette or "tab10",
        edgecolor="w",
    )
    ax.set_title("Cost vs Quality (Average)")
    ax.set_xlabel("Total Tokens")
    ax.set_ylabel("Judge Total Score")
    ax.grid(True)
    # annotate data origin (clean vs original)
    if data_origin:
        ax.text(1.0, 1.02, f"Data origin: {data_origin}", transform=ax.transAxes, ha='right', fontsize=9)
    plt.legend(bbox_to_anchor=(1.05, 1), loc="upper left")
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=200)
    plt.close()


def plot_scatter_all_runs(raw_df: pd.DataFrame, out_path: Path, palette: Optional[dict] = None, jitter: float = 0.0, data_origin: Optional[str] = None) -> None:
    """Plot scatter of all individual runs (not aggregated).

    - X: total_tokens
    - Y: judge_total_score
    - hue: model
    - style: variant
    """
    sns.set(style="whitegrid")
    plt.figure(figsize=(11, 7))
    # coerce numeric
    raw_df = raw_df.copy()
    raw_df["total_tokens"] = pd.to_numeric(raw_df.get("total_tokens"), errors="coerce")
    raw_df["judge_total_score"] = pd.to_numeric(raw_df.get("judge_total_score"), errors="coerce")
    # optionally add jitter to the x axis to make overlapping points visible
    x_vals = raw_df["total_tokens"].to_numpy()
    if jitter and np.nanstd(x_vals) > 0:
        scale = float(np.nanstd(x_vals)) * float(jitter)
        x_plot = x_vals + np.random.normal(0, scale, size=x_vals.shape)
    else:
        x_plot = x_vals
    # plot with explicit x array
    # convert raw_df model values to a column for plotting consistency
    plot_df = raw_df.copy()
    plot_df["x_plot"] = x_plot
    ax = sns.scatterplot(
        data=plot_df,
        x="x_plot",
        y="judge_total_score",
        hue="model",
        hue_order=MODEL_ORDER,
        style="variant",
        palette=palette or "tab10",
        s=60,
        alpha=0.8,
        edgecolor="w",
    )
    ax.set_title("Cost vs Quality (Per-run)")
    ax.set_xlabel("Total Tokens")
    ax.set_ylabel("Judge Total Score")
    ax.grid(True)
    # If multiple origins exist, plot markers per origin and add legend
    origins = list(raw_df['data_origin'].dropna().unique()) if 'data_origin' in raw_df.columns else ([data_origin] if data_origin else [])
    if len(origins) > 1:
        # rebuild plot by iterating models and origins for clearer markers
        plt.clf()
        fig, ax = plt.subplots(figsize=(11, 7))
        ordered_models = list(raw_df['model'].dropna().unique())
        marker_map = {'clean': 'o', 'original': 'X'}
        for i, model in enumerate(ordered_models):
            model_color = (palette.get(model) if isinstance(palette, dict) else None) or (sns.color_palette('tab10')[i % 10])
            for origin in origins:
                subset = raw_df[(raw_df['model'] == model) & (raw_df['data_origin'] == origin)]
                if subset.empty:
                    continue
                x_vals_o = subset['x_plot'].to_numpy()
                y_vals_o = subset['judge_total_score'].to_numpy()
                ax.scatter(x_vals_o, y_vals_o, label=f"{model} ({origin})", marker=marker_map.get(origin, 'o'), color=model_color, s=60, alpha=0.8, edgecolor='w')
        ax.set_title("Cost vs Quality (Per-run)")
        ax.set_xlabel("Total Tokens")
        ax.set_ylabel("Judge Total Score")
        ax.grid(True)
        ax.legend(bbox_to_anchor=(1.05, 1), loc="upper left")
        if data_origin:
            ax.text(1.0, 1.02, f"Data origin: {data_origin}", transform=ax.transAxes, ha='right', fontsize=9)
        plt.tight_layout()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(out_path, dpi=200)
        plt.close()
        return
    else:
        plt.legend(bbox_to_anchor=(1.05, 1), loc="upper left")
        if data_origin:
            plt.gca().text(1.0, 1.02, f"Data origin: {data_origin}", transform=plt.gca().transAxes, ha='right', fontsize=9)
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=200)
    plt.close()


def plot_model_performance_box(raw_df: pd.DataFrame, out_path: Path, palette: Optional[dict] = None, data_origin: Optional[str] = None) -> None:
    """Plot boxplot (by variant) of judge scores grouped by model, with swarm overlay.

    - X: variant
    - Y: judge_total_score (per-run)
    - hue: model
    """
    sns.set(style="whitegrid")
    plt.figure(figsize=(14, 7))
    # coerce numeric
    raw_df = raw_df.copy()
    raw_df["judge_total_score"] = pd.to_numeric(raw_df.get("judge_total_score"), errors="coerce")

    if raw_df["judge_total_score"].dropna().empty:
        print(f"No judge scores available for boxplot; skipping {out_path}")
        return

    # Create grouped boxplots per-variant per-model using matplotlib to avoid
    # seaborn internal legend bug when using `hue` with boxplot.
    from matplotlib.patches import Patch

    variants = list(raw_df['variant'].dropna().unique())
    models_present = list(raw_df['model'].dropna().unique())
    # preserve preferred model order then append others
    models = [m for m in MODEL_ORDER if m in models_present] + [m for m in models_present if m not in MODEL_ORDER]

    x = np.arange(len(variants))
    n_models = len(models)
    if n_models == 0:
        print(f"No models found for boxplot; skipping {out_path}")
        return

    width = 0.8 / n_models
    left = x - 0.4
    ax = plt.gca()
    legend_patches = []

    for i, model in enumerate(models):
        # collect data per variant for this model
        data_per_variant = []
        counts = []
        for v in variants:
            vals = raw_df.loc[(raw_df['model'] == model) & (raw_df['variant'] == v), 'judge_total_score'].dropna().values
            if vals.size == 0:
                data_per_variant.append(np.array([np.nan]))
                counts.append(0)
            else:
                data_per_variant.append(vals)
                counts.append(vals.size)

        if sum(counts) == 0:
            continue

        positions = left + i * width + width / 2
        color = (palette.get(model) if isinstance(palette, dict) else None) or palette or sns.color_palette('tab10')[i % 10]

        bp = ax.boxplot(
            data_per_variant,
            positions=positions,
            widths=width * 0.9,
            patch_artist=True,
            showfliers=False,
        )
        # style boxes
        for box in bp['boxes']:
            box.set(facecolor=color, linewidth=0.8)
        for whisker in bp['whiskers']:
            whisker.set(color='black', linewidth=0.6)
        for cap in bp['caps']:
            cap.set(color='black', linewidth=0.6)

        # overlay individual points
        for j, v in enumerate(variants):
            subset = raw_df.loc[(raw_df['model'] == model) & (raw_df['variant'] == v)]
            vals = subset['judge_total_score'].dropna().to_numpy()
            if vals.size == 0:
                continue
            xpos = positions[j]
            jitter_vals = (np.random.rand(len(vals)) - 0.5) * width * 0.6
            # if data_origin column exists, color markers by origin shape
            if 'data_origin' in subset.columns:
                origins_arr = subset.loc[subset['judge_total_score'].notna(), 'data_origin'].to_numpy()
                # plot per-origin subsets
                marker_map = {'clean': 'o', 'original': 'X'}
                unique_origins = list(dict.fromkeys(origins_arr))
                for origin in unique_origins:
                    mask = origins_arr == origin
                    if not any(mask):
                        continue
                    ax.scatter(xpos + jitter_vals[mask], vals[mask], color=color, alpha=0.7, s=20, edgecolor='w', marker=marker_map.get(origin, 'o'), label=None)
            else:
                ax.scatter(xpos + jitter_vals, vals, color=color, alpha=0.7, s=20, edgecolor='w')

        legend_patches.append(Patch(facecolor=color, edgecolor='k', label=model))

    ax.set_title("Model Performance by Prompt Variant (Per-run)")
    ax.set_xlabel("Prompt Variant")
    ax.set_ylabel("Judge Total Score")
    ax.set_xticks(x)
    ax.set_xticklabels(variants)
    ax.grid(True, axis='y')
    if legend_patches:
        ax.legend(handles=legend_patches, title="Model", bbox_to_anchor=(1.05, 1), loc='upper left')
    # annotate data origin
    if data_origin:
        ax.text(1.0, 1.02, f"Data origin: {data_origin}", transform=ax.transAxes, ha='right', fontsize=9)
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=200)
    plt.close()


def plot_bar_avg(grouped_df: pd.DataFrame, out_path: Path, palette: Optional[dict] = None, data_origin: Optional[str] = None) -> None:
    """Plot grouped bar chart of averaged judge scores per variant grouped by model.

    - X: variant
    - Y: judge_total_score_mean
    - hue: model
    """
    sns.set(style="whitegrid")
    plt.figure(figsize=(12, 6))
    ax = sns.barplot(
        data=grouped_df,
        x="variant",
        y="judge_total_score_mean",
        hue="model",
        hue_order=MODEL_ORDER,
        palette=palette or "tab10",
        ci=None,
    )
    ax.set_title("Model Performance by Prompt Variant (Average)")
    ax.set_xlabel("Prompt Variant")
    ax.set_ylabel("Judge Total Score")
    ax.grid(True, axis="y")
    plt.legend(title="Model", bbox_to_anchor=(1.05, 1), loc="upper left")
    # annotate data origin
    if data_origin:
        ax.text(1.0, 1.02, f"Data origin: {data_origin}", transform=ax.transAxes, ha='right', fontsize=9)
    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=200)
    plt.close()


def main(input_csv: Path = INPUT_CSV) -> None:
    grouped = load_and_aggregate_data(input_csv)
    raw_df = pd.read_csv(input_csv)
    # detect data origin: prefer explicit `data_origin` column, else infer from filename
    origin_from_filename = None
    name = input_csv.name.lower() if isinstance(input_csv, Path) else str(input_csv).lower()
    if 'clean' in name:
        origin_from_filename = 'clean'
    elif 'original' in name:
        origin_from_filename = 'original'
    # ensure a `data_origin` column exists for plotting logic
    if 'data_origin' not in raw_df.columns:
        raw_df['data_origin'] = origin_from_filename or 'original'
    # determine a single label to annotate plots (handle mixed origins)
    unique_origins = sorted(raw_df['data_origin'].dropna().unique())
    if len(unique_origins) == 0:
        data_origin_label = origin_from_filename or 'unknown'
    elif len(unique_origins) == 1:
        data_origin_label = unique_origins[0]
    else:
        data_origin_label = 'mixed'
    # coerce numeric columns for filtering
    raw_df['total_tokens'] = pd.to_numeric(raw_df.get('total_tokens'), errors='coerce')
    raw_df['judge_total_score'] = pd.to_numeric(raw_df.get('judge_total_score'), errors='coerce')
    # determine rows to drop for plotting: missing tokens or missing judge score or explicit parse_error
    drop_reasons = []
    drop_mask = pd.Series(False, index=raw_df.index)
    if 'parse_error' in raw_df.columns:
        parse_err_mask = raw_df['parse_error'].notna() & (raw_df['parse_error'] != 'None')
        drop_mask = drop_mask | parse_err_mask
        drop_reasons.append(('parse_error', parse_err_mask))
    missing_mask = raw_df['total_tokens'].isna() | raw_df['judge_total_score'].isna()
    drop_mask = drop_mask | missing_mask
    drop_reasons.append(('missing_vals', missing_mask))
    # write dropped rows for inspection
    dropped = raw_df[drop_mask]
    if not dropped.empty:
        out_drop = Path('outputs/experiments/dropped_rows.csv')
        dropped[['file','model','variant','parse_error','total_tokens','judge_total_score']].to_csv(out_drop, index=False)
        print(f"Wrote dropped rows to: {out_drop} ({len(dropped)} rows)")
    # cleaned dataframe for plotting
    cleaned_raw = raw_df[~drop_mask].copy()
    # Export grouped CSV
    OUT_GROUPED.parent.mkdir(parents=True, exist_ok=True)
    grouped.to_csv(OUT_GROUPED, index=False)
    print(f"Wrote grouped summary to: {OUT_GROUPED}")

    # build a consistent palette mapping for models
    # Ensure palette respects our fixed MODEL_ORDER; include any other models found afterwards
    found_models = list(raw_df['model'].dropna().unique())
    ordered_models = MODEL_ORDER + [m for m in found_models if m not in MODEL_ORDER]
    palette_colors = sns.color_palette('tab10', n_colors=max(10, len(ordered_models)))
    palette_map = {m: palette_colors[i % len(palette_colors)] for i, m in enumerate(ordered_models)}

    # Diagnostic counts (before plotting)
    total_rows = len(raw_df)
    has_tokens = raw_df['total_tokens'].notna().sum() if 'total_tokens' in raw_df.columns else 0
    has_judge = raw_df['judge_total_score'].notna().sum() if 'judge_total_score' in raw_df.columns else 0
    has_both = raw_df.dropna(subset=['total_tokens', 'judge_total_score']).shape[0] if {'total_tokens','judge_total_score'}.issubset(raw_df.columns) else 0
    print(f"Diagnostic: total runs={total_rows}, rows with tokens={has_tokens}, rows with judge score={has_judge}, rows with both={has_both}")

    # Plot scatter and bar
    # average scatter (existing)
    plot_scatter(grouped, OUT_SCATTER, palette=palette_map, data_origin=data_origin_label)
    print(f"Wrote average scatter chart to: {OUT_SCATTER}")
    # all-runs scatter (with jitter to reveal overlapping points)
    plot_scatter_all_runs(cleaned_raw, OUT_SCATTER_ALL, palette=palette_map, jitter=0.03, data_origin=data_origin_label)
    print(f"Wrote all-runs scatter chart to: {OUT_SCATTER_ALL}")
    # box + scatter per-run model performance (only if judge scores exist)
    if has_judge > 0 and not cleaned_raw.empty:
        plot_model_performance_box(cleaned_raw, OUT_BAR, palette=palette_map, data_origin=data_origin_label)
        print(f"Wrote model performance box plot to: {OUT_BAR}")
    elif has_judge > 0:
        print("All rows with judge scores were filtered out (parse errors or missing tokens); no boxplot created.")
    else:
        print("Skipping boxplot: no judge scores available in the data.")
    # also keep the averaged bar chart
    plot_bar_avg(grouped, OUT_BAR_AVG, palette=palette_map, data_origin=data_origin_label)
    print(f"Wrote model performance averaged bar chart to: {OUT_BAR_AVG}")

    # Diagnostic prints to explain why some points may be missing
    total_rows = len(raw_df)
    has_tokens = raw_df['total_tokens'].notna().sum() if 'total_tokens' in raw_df.columns else 0
    has_judge = raw_df['judge_total_score'].notna().sum() if 'judge_total_score' in raw_df.columns else 0
    has_both = raw_df.dropna(subset=['total_tokens', 'judge_total_score']).shape[0] if {'total_tokens','judge_total_score'}.issubset(raw_df.columns) else 0
    print(f"Diagnostic: total runs={total_rows}, rows with tokens={has_tokens}, rows with judge score={has_judge}, rows with both={has_both}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate experiment visualizations")
    parser.add_argument(
        "--csv",
        type=str,
        default=str(INPUT_CSV),
        help="Path to comparison CSV to visualize (default: outputs/experiments/comparison_summary.csv)",
    )
    args = parser.parse_args()
    main(Path(args.csv))
