"""List failing experiment runs for quick triage.

Usage examples:
  python scripts\list_failing_runs.py
  python scripts\list_failing_runs.py --csv outputs/experiments/comparison_summary.csv --write-clean outputs/experiments/comparison_summary_clean.csv

This script reports runs with:
- non-empty `parse_error`
- `json_parse_success` == False
- missing `judge_total_score`

It can also write a cleaned CSV excluding failing runs for downstream analysis.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import pandas as pd


def summarize_failures(df: pd.DataFrame) -> dict:
    # safe masks if columns missing
    idx = df.index
    parse_mask = df['parse_error'].notna() & (df['parse_error'].astype(str).str.strip() != '') if 'parse_error' in df.columns else pd.Series(False, index=idx)
    json_fail_mask = (~df['json_parse_success'].astype(bool)) if 'json_parse_success' in df.columns else pd.Series(False, index=idx)
    judge_missing_mask = df['judge_total_score'].isna() if 'judge_total_score' in df.columns else pd.Series(True, index=idx)

    combined = parse_mask | json_fail_mask | judge_missing_mask

    return {
        'parse_errors': df[parse_mask].copy(),
        'json_failures': df[json_fail_mask].copy(),
        'missing_judge': df[judge_missing_mask].copy(),
        'combined': df[combined].copy(),
        'cleaned': df[~combined].copy(),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description='List failing experiment runs for triage')
    p.add_argument('--csv', type=Path, default=Path('outputs/experiments/comparison_summary.csv'), help='Comparison CSV to inspect')
    p.add_argument('--write-clean', type=Path, default=None, help='Optional path to write cleaned CSV (exclude failing runs)')
    p.add_argument('--show', choices=['parse','json','judge','combined','all'], default='combined', help='Which failures to show')
    p.add_argument('--limit', type=int, default=20, help='How many rows to preview for each category')
    args = p.parse_args(argv)

    if not args.csv.exists():
        print(f"Input CSV not found: {args.csv}")
        return 2

    df = pd.read_csv(args.csv)
    res = summarize_failures(df)

    def show_df(name, subdf):
        print(f"\n=== {name} ({len(subdf)} rows) ===")
        if subdf.empty:
            print("(none)")
            return
        cols = [c for c in ['file','model','variant','parse_error','json_parse_success','judge_total_score','judge_model'] if c in subdf.columns]
        print(subdf[cols].head(args.limit).to_string(index=False))

    if args.show in ('parse','all'):
        show_df('Parse errors', res['parse_errors'])
    if args.show in ('json','all'):
        show_df('JSON parse failures', res['json_failures'])
    if args.show in ('judge','all'):
        show_df('Missing judge scores', res['missing_judge'])
    if args.show in ('combined','all'):
        show_df('Combined failures (parse OR json OR missing judge)', res['combined'])

    if args.write_clean:
        args.write_clean.parent.mkdir(parents=True, exist_ok=True)
        res['cleaned'].to_csv(args.write_clean, index=False)
        print(f"\nWrote cleaned CSV (excluded failures) to: {args.write_clean} ({len(res['cleaned'])} rows)")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
